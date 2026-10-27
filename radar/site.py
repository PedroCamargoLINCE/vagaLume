"""Data for the web interface (docs/).

docs/index.html is a fixed page that you can read and edit by hand. Each
run only rewrites docs/data.json, which the page downloads and shows.
GitHub Pages serves the docs/ folder as a website.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .db import StoredOpportunity
from .models import is_internal_site, same_job_key, strip_tracking
from .report import SourceHealth
from .skills import NAMES as SKILL_NAMES
from .labels import past_term
from .sources.programs import CLOSED_NOTE, application_months


def item_record(opp: StoredOpportunity, apply_months: list[int] | None = None) -> dict[str, object]:
    """Only the fields the page shows, to keep data.json small."""
    record = {
        "id": opp.id,
        "title": opp.title,
        "org": opp.org,
        "url": strip_tracking(opp.url),
        "location": opp.location,
        "area": opp.area,
        "season": opp.season,
        "regions": opp.regions,
        "warnings": opp.warnings,
        "deadline": opp.deadline if opp.deadline[:1].isdigit() else "",
        "pay": opp.pay,
        "skills": opp.skills,
        "fields": opp.fields,
        "levels": opp.levels,
        "states": opp.states,
        "workplaces": opp.workplaces,
        "subs": opp.subs,
        # requirements read from the text (radar/requirements.py) and the probable fields of a role the
        # rules couldn't place (radar/area_guess.py): the page shows the first and sorts by the second
        "req": getattr(opp, "req", None) or getattr(opp, "requirements", {}),
        "guess": opp.guess,
        "posted": opp.posted_date,
        "added": opp.first_seen,
        "source": opp.source,
        "note": opp.note if opp.source == "programs" else "",
        "status": opp.status,
    }
    if opp.source == "programs" and opp.note.startswith(CLOSED_NOTE):
        record["closed"] = 1  # the page says this year's applications are over
        record["note"] = opp.note[len(CLOSED_NOTE):].lstrip(" ·")
    if apply_months:
        record["apply"] = apply_months  # programs: the months applications are usually open
    if opp.pay and opp.pay_from in ("text", "claude"):
        record["pay_text"] = 1  # read from the description, not a salary field: the page asks you to check it
    return record


def stats(opportunities: list[StoredOpportunity], health: list[SourceHealth], today: str) -> dict[str, object]:
    """Small summary used by the live badges in the README (shields.io reads it)."""
    open_items = [o for o in opportunities if o.is_open]
    healthy = sum(1 for h in health if h.status == "ok")
    return {
        "updated": today,
        "open": f"{len(open_items):,}",
        "new": str(sum(1 for o in open_items if o.first_seen == today and o.source != "programs")),
        "with_pay": f"{sum(1 for o in open_items if o.pay):,}",
        "sources": f"{healthy}/{len(health)} healthy",
        "sources_ok": healthy == len(health),
    }


# Placeholder company names: two roles under them are not the same company's.
_NO_COMPANY = re.compile(r"confidencial|n[ãa]o informad|^\s*$", re.I)


def _title_key(title: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", title.lower()).split())


def _union(lists: list[list[str]]) -> list[str]:
    return list(dict.fromkeys(x for values in lists for x in values))


def shown_items(opportunities: list[StoredOpportunity], today: str, windows: dict[str, list[int]] | None = None) -> list[dict[str, object]]:
    """The open roles the page lists, without:
    - roles for a term that is already over ("Winter 2026" in October 2026);
    - Workday sites only for a company's own staff (Boeing's "External_Subsidiary");
    - the same job twice: two addresses of one job (a GitHub list and the company's board,
      "/en-US/" or not, "?gh_jid=") keep one.
    The same title at the same company in several places (one Workday job per city, a public
    program listed once per region: 37 rows for one Distrito Federal estágio) becomes one row
    with every place; "alts" keeps the other places' own links.
    A program page's deadline in the past is last year's edition, so it isn't shown as a deadline."""
    day = date.fromisoformat(today)
    jobs: set[str] = set()
    groups: dict[tuple[str, str], list[StoredOpportunity]] = {}
    # The company's own board first (it has the description), then roles that state pay, then the oldest.
    for opp in sorted(opportunities, key=lambda o: (o.source == "github_lists", not o.pay, o.first_seen, o.id)):
        if not opp.is_open or (opp.source != "programs" and past_term(opp.title, day)) or is_internal_site(opp.url):
            continue
        job = same_job_key(opp.url)
        if job in jobs:
            continue
        jobs.add(job)
        alone = opp.source == "programs" or _NO_COMPANY.search(opp.org)
        key = ("", opp.id) if alone else (opp.org.lower().strip(), _title_key(opp.title))
        groups.setdefault(key, []).append(opp)
    items: list[dict[str, object]] = []
    for group in groups.values():
        first = group[0]
        record = item_record(first, (windows or {}).get(first.url) if first.source == "programs" else None)
        if first.source == "programs" and str(record["deadline"]) and str(record["deadline"]) < today:
            record["deadline"] = ""
        if len(group) > 1:
            places = _union([[p.strip() for p in o.location.split(" / ") if p.strip()] for o in group])
            record["location"] = " / ".join(places)
            for name in ("regions", "states", "workplaces", "fields", "levels", "subs"):
                record[name] = _union([getattr(o, name) for o in group])
            record["regions"] = [r for r in record["regions"] if r != "unknown"] or ["unknown"]  # type: ignore[union-attr]
            record["added"] = min(o.first_seen for o in group)
            if not record["deadline"]:
                record["deadline"] = next((o.deadline for o in group if o.deadline[:1].isdigit()), "")
            # One link per other place (KLA posts the same intern role several times in Shanghai).
            alts: dict[str, list[str]] = {}
            for o in group[1:]:
                if o.location.strip().lower() != first.location.strip().lower():
                    alts.setdefault(o.location.strip().lower(), [o.location, strip_tracking(o.url), o.id])
            if alts:
                record["alts"] = list(alts.values())
            record["also"] = [o.id for o in group[1:]]  # every merged id, so a saved or applied one keeps its mark
        items.append(record)
    return items


# Values the page fills back in when a role leaves them out (ITEM_DEFAULTS in docs/index.html):
# leaving them out of data.json saves about a fifth of its size.
COMPACT_DEFAULTS: dict[str, object] = {
    "location": "", "warnings": [], "deadline": "", "pay": "", "skills": [], "fields": [], "levels": [], "states": [],
    "workplaces": [], "subs": [], "req": {}, "guess": [], "posted": "", "note": "", "season": "unknown", "area": "other",
    "status": "seen",
}


def compact(record: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in record.items() if k not in COMPACT_DEFAULTS or v != COMPACT_DEFAULTS[k]}


def write_data(
    opportunities: list[StoredOpportunity],
    health: list[SourceHealth],
    today: str,
    labeled_by: str,
    out_dir: str | Path,
    subscribe: dict[str, str] | None = None,
    programs: list[dict[str, object]] | None = None,
) -> Path:
    """Write docs/data.json with every open opportunity.

    `programs` is config/programs.yaml: its `applications` field (when applications
    usually open) goes to the page as month numbers.
    """
    windows = {str(p["url"]): application_months(str(p.get("applications") or "")) for p in programs or []}
    payload = {
        "updated": today,
        "labeledBy": labeled_by,
        "skillNames": SKILL_NAMES,  # the résumé prompt on the site lists these
        "subscribe": subscribe or {},  # the "daily updates" panel (radar/digest.py)
        "sources": [
            {"name": h.name, "status": h.status, "items": h.items, "problems": h.errors[:5]} for h in health
        ],
        "items": shown_items(opportunities, today, windows),
    }
    path = Path(out_dir) / "data.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # One item per line: easier to read in git diffs than one giant line.
    lines = ",\n".join(json.dumps(compact(item), ensure_ascii=False) for item in payload.pop("items"))
    head = json.dumps(payload, ensure_ascii=False)[:-1]
    path.write_text(f'{head}, "items": [\n{lines}\n]}}\n', encoding="utf-8")
    summary = stats(opportunities, health, today)
    (Path(out_dir) / "stats.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return path
