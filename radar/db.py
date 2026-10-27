"""SQLite storage (data/radar.db, rebuilt from data/*.jsonl on every run).

Two tables:
  opportunities  one row per posting, keyed by the URL hash (so no duplicates)
  page_hashes    for the program-page watcher: the last hash of each page

The `status` column is yours: new, seen, applied or ignored. The bot only
ever changes "new" -> "seen" (at the start of the next run). You can set it
by editing config/status.yaml (easiest, works from the GitHub website) or
with `python -m radar status <id> applied`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .models import Opportunity

STATUSES = ("new", "seen", "applied", "ignored")
LAST_SEEN_REFRESH_DAYS = 7  # see upsert()

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    org           TEXT NOT NULL,
    source        TEXT NOT NULL,
    location      TEXT,
    remote        INTEGER DEFAULT 0,
    url           TEXT NOT NULL,
    posted_date   TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    deadline      TEXT,
    pay           TEXT,           -- e.g. "$54–60/hr"; empty when not stated
    pay_from      TEXT,           -- where the pay came from: field (the job board's) / text (the description) / claude
    detail_checked TEXT,          -- last day its job page was read (radar/details.py)
    skills        TEXT,           -- comma-separated, e.g. "Python,PyTorch" (radar/skills.py)
    fields        TEXT,           -- fields of study, comma-separated, e.g. "engenharia" (radar/fields.py)
    levels        TEXT,           -- study levels, comma-separated, e.g. "masters,phd" (radar/levels.py)
    states        TEXT,           -- Brazilian states, comma-separated, e.g. "SP,RJ" (radar/places.py)
    workplaces    TEXT,           -- remote / hybrid / on-site, comma-separated (radar/workplace.py)
    subs          TEXT,           -- sub-areas, comma-separated, e.g. "tributario" (radar/subareas.py)
    req           TEXT,           -- requirements read from the text, JSON, e.g. {"semester":{"from":5}} (radar/requirements.py)
    guess         TEXT,           -- probable fields of a role the rules couldn't place, comma-separated (radar/area_guess.py)
    area          TEXT,
    season        TEXT,
    regions       TEXT,           -- comma-separated, e.g. "Brazil,remote"
    warnings      TEXT,           -- comma-separated
    calendar_note TEXT,
    note          TEXT,
    labeled_by    TEXT,           -- "rules" or "claude"
    is_open       INTEGER DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS page_hashes (
    url          TEXT PRIMARY KEY,
    hash         TEXT NOT NULL,
    last_checked TEXT NOT NULL,
    last_changed TEXT NOT NULL
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
    return conn


# --- the database as text -----------------------------------------------------
# The SQLite file is rebuilt from two text files at the start of every run and
# written back at the end. Only the text files are committed: one role per
# line, sorted, so git stores just the lines that changed each day (a binary
# database would be stored whole every day).
TEXT_FILES = {"opportunities": ("opportunities.jsonl", "id"), "page_hashes": ("page_hashes.jsonl", "url")}


def save_text(conn: sqlite3.Connection, text_dir: str | Path) -> None:
    """Write every table to data/<table>.jsonl, one row per line, sorted by its key."""
    out = Path(text_dir)
    out.mkdir(parents=True, exist_ok=True)
    for table, (name, key) in TEXT_FILES.items():
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        rows = conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {key}").fetchall()
        lines = [json.dumps(dict(zip(columns, row)), ensure_ascii=False, separators=(",", ":")) for row in rows]
        (out / name).write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def load_text(conn: sqlite3.Connection, text_dir: str | Path) -> int:
    """Fill the (empty) tables from data/<table>.jsonl. Returns how many roles were read."""
    loaded = 0
    for table, (name, _key) in TEXT_FILES.items():
        path = Path(text_dir) / name
        if not path.exists():
            continue
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = {k: v for k, v in json.loads(line).items() if k in columns}
            marks = ", ".join(f":{k}" for k in row)
            conn.execute(f"INSERT OR REPLACE INTO {table} ({', '.join(row)}) VALUES ({marks})", row)
            loaded += table == "opportunities"
    conn.commit()
    return loaded


def open_state(db_path: str | Path, text_dir: str | Path) -> sqlite3.Connection:
    """The database for a run: rebuilt from the text files when they exist.

    Without them (the first run after switching to text) it opens the old
    data/radar.db as before, and the end of the run writes the text files.
    """
    if (Path(text_dir) / TEXT_FILES["opportunities"][0]).exists():
        Path(db_path).unlink(missing_ok=True)
        conn = connect(db_path)
        load_text(conn, text_dir)
        return conn
    return connect(db_path)


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Databases made by an older version lack newer columns; add them."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(opportunities)")}
    if "pay" not in existing:
        conn.execute("ALTER TABLE opportunities ADD COLUMN pay TEXT")
    for column in ("pay_from", "detail_checked", "skills", "fields", "levels", "states", "workplaces", "subs", "req", "guess"):
        if column not in existing:
            conn.execute(f"ALTER TABLE opportunities ADD COLUMN {column} TEXT")


def _join(items: list[str]) -> str:
    return ",".join(items)


def _split(text: str | None) -> list[str]:
    return [part for part in (text or "").split(",") if part]


def existing_ids(conn: sqlite3.Connection) -> set[str]:
    return {row["id"] for row in conn.execute("SELECT id FROM opportunities")}


def mark_previous_new_as_seen(conn: sqlite3.Connection, today: str) -> None:
    """Items reported as "new" in an earlier run become "seen"."""
    conn.execute("UPDATE opportunities SET status='seen' WHERE status='new' AND first_seen < ?", (today,))


def upsert(conn: sqlite3.Connection, opp: Opportunity, today: str) -> bool:
    """Insert a new posting or refresh an existing one. Returns True if new.

    For existing rows we refresh the facts (title, deadline, labels...) but
    never touch first_seen or your status. last_seen is refreshed once a week
    at most: it only decides when a role unseen for 30 days is closed, and not
    rewriting it every day keeps the daily change to data/*.jsonl small.
    """
    row = conn.execute("SELECT labeled_by, last_seen, pay_from, detail_checked FROM opportunities WHERE id=?", (opp.id,)).fetchone()
    values = {
        "id": opp.id, "title": opp.title, "org": opp.org, "source": opp.source,
        "location": opp.location, "remote": int(opp.remote), "url": opp.url,
        "posted_date": opp.posted_date, "deadline": opp.deadline, "pay": opp.pay, "pay_from": opp.pay_from, "detail_checked": opp.detail_checked, "skills": _join(opp.skills), "fields": _join(opp.fields),
        "levels": _join(opp.levels), "states": _join(opp.states), "workplaces": _join(opp.workplaces), "subs": _join(opp.subs),
        "req": json.dumps(opp.requirements, ensure_ascii=False, separators=(",", ":"), sort_keys=True) if opp.requirements else "",
        "guess": _join(opp.guess),
        "area": opp.area,
        "season": opp.season, "regions": _join(opp.regions), "warnings": _join(opp.warnings),
        "calendar_note": opp.calendar_note, "note": opp.note, "labeled_by": opp.labeled_by,
        "is_open": int(opp.is_open), "last_seen": today,
    }
    if row is None:
        values["first_seen"] = today
        columns = ", ".join(values)
        marks = ", ".join(f":{name}" for name in values)
        conn.execute(f"INSERT INTO opportunities ({columns}) VALUES ({marks})", values)
        return True
    # Keep an earlier Claude label if this run only had keyword rules for it.
    if opp.labeled_by == "rules" and row["labeled_by"] == "claude":
        for name in ("area", "season", "regions", "warnings", "calendar_note", "labeled_by"):
            values.pop(name)
        if not opp.pay and row["pay_from"] == "claude":
            values.pop("pay")  # keep the pay Claude found
            values.pop("pay_from")
        if opp.deadline == "check page":
            values.pop("deadline")
    if not opp.note:
        values.pop("note")  # keep the old note (e.g. "page changed on ...")
    # Its job page was read on an earlier day but not today (radar/details.py): keep what the
    # page gave, since today's labels come from the list alone.
    if row["detail_checked"] and not opp.detail_checked:
        for name in ("detail_checked", "pay", "pay_from", "skills", "fields", "levels", "workplaces", "req"):
            values.pop(name, None)
        if opp.deadline == "check page":
            values.pop("deadline")
    # Its job page said the job is gone (radar/details.py): it stays closed even while a list still shows it.
    if str(row["detail_checked"] or "").startswith("gone"):
        values["is_open"] = 0
        values.pop("detail_checked", None)
    if row["last_seen"] and (date.fromisoformat(today) - date.fromisoformat(row["last_seen"])).days < LAST_SEEN_REFRESH_DAYS:
        values.pop("last_seen")

    assignments = ", ".join(f"{name}=:{name}" for name in values if name != "id")
    conn.execute(f"UPDATE opportunities SET {assignments} WHERE id=:id", values)
    return False


def mark_missing_as_closed(conn: sqlite3.Connection, source: str, seen_ids: set[str], keep_orgs: set[str] = frozenset()) -> None:  # type: ignore[assignment]
    """A healthy source that no longer lists a posting -> mark it closed. `keep_orgs`: companies
    whose board failed this run, so their roles' absence means nothing."""
    rows = conn.execute("SELECT id, org FROM opportunities WHERE source=? AND is_open=1", (source,)).fetchall()
    gone = [row["id"] for row in rows if row["id"] not in seen_ids and row["org"] not in keep_orgs]
    conn.executemany("UPDATE opportunities SET is_open=0 WHERE id=?", [(i,) for i in gone])


def close_stale(conn: sqlite3.Connection, today: str, days: int = 30) -> None:
    """Anything not seen for `days` days is treated as closed.

    This covers sources that are often only partly healthy (so
    mark_missing_as_closed never runs for them).
    """
    cutoff = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    conn.execute("UPDATE opportunities SET is_open=0 WHERE last_seen < ?", (cutoff,))


def set_status(conn: sqlite3.Connection, opp_id: str, status: str) -> bool:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    cursor = conn.execute("UPDATE opportunities SET status=? WHERE id=?", (status, opp_id))
    return cursor.rowcount > 0


@dataclass
class StoredOpportunity:
    """A row read back from the database, ready for the report."""

    id: str
    title: str
    org: str
    source: str
    location: str
    remote: bool
    url: str
    posted_date: str
    first_seen: str
    last_seen: str
    deadline: str
    pay: str
    pay_from: str
    detail_checked: str
    skills: list[str]
    fields: list[str]
    levels: list[str]
    states: list[str]
    workplaces: list[str]
    subs: list[str]
    req: dict[str, Any]
    guess: list[str]
    area: str
    season: str
    regions: list[str]
    warnings: list[str]
    calendar_note: str
    note: str
    labeled_by: str
    is_open: bool
    status: str


def load_all(conn: sqlite3.Connection) -> list[StoredOpportunity]:
    rows = conn.execute("SELECT * FROM opportunities").fetchall()
    return [
        StoredOpportunity(
            id=r["id"], title=r["title"], org=r["org"], source=r["source"],
            location=r["location"] or "", remote=bool(r["remote"]), url=r["url"],
            posted_date=r["posted_date"] or "", first_seen=r["first_seen"],
            last_seen=r["last_seen"], deadline=r["deadline"] or "check page", pay=r["pay"] or "", pay_from=r["pay_from"] or "", detail_checked=r["detail_checked"] or "",
            skills=_split(r["skills"]), fields=_split(r["fields"]),
            levels=_split(r["levels"]), states=_split(r["states"]), workplaces=_split(r["workplaces"]), subs=_split(r["subs"]),
            req=json.loads(r["req"]) if r["req"] else {}, guess=_split(r["guess"]), area=r["area"] or "other", season=r["season"] or "unknown",
            regions=_split(r["regions"]), warnings=_split(r["warnings"]),
            calendar_note=r["calendar_note"] or "", note=r["note"] or "",
            labeled_by=r["labeled_by"] or "rules", is_open=bool(r["is_open"]), status=r["status"],
        )
        for r in rows
    ]


# --- page watcher -----------------------------------------------------------
def page_hash_changed(conn: sqlite3.Connection, url: str, new_hash: str, today: str) -> tuple[bool, str]:
    """Store the latest hash of a page.

    Returns (changed, last_changed_date). The very first time we see a page
    we just record it; that does not count as a change.
    """
    row = conn.execute("SELECT hash, last_changed FROM page_hashes WHERE url=?", (url,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO page_hashes (url, hash, last_checked, last_changed) VALUES (?, ?, ?, ?)",
            (url, new_hash, today, today),
        )
        return False, today
    if row["hash"] == new_hash:
        conn.execute("UPDATE page_hashes SET last_checked=? WHERE url=?", (today, url))
        return False, row["last_changed"]
    conn.execute(
        "UPDATE page_hashes SET hash=?, last_checked=?, last_changed=? WHERE url=?",
        (new_hash, today, today, url),
    )
    return True, today
