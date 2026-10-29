"""The daily run, step by step.

    python -m radar                 run everything
    python -m radar --only gupy     run only some sources (comma-separated)
    python -m radar status ID applied
    python -m radar check-config    verify every company slug and program URL
    python -m radar discover        find companies with jobs in Brazil on Ashby, Greenhouse, Lever
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any, Callable

from . import area_guess, counts, db, details, digest, labels, llm, notify, report, site, telegram_bot
from .config import ROOT, load_config
from .models import Opportunity
from .sources import (
    SourceResult, abler, academia, amazon, ashby, ciadeestagios, ciadetalentos, ciee, ciee_editais, company_sites, eightfold, eureca,
    fapesp, github_lists, google, greenhouse, gupy, iel, inhire, lever, meta, microsoft, mudes, nextjs_sites, nvidia,
    oracle_hcm, parana, programs, quickin, recrutei, remote_boards, rss_jobs, shopee, smartrecruiters, solides,
    successfactors, superestagios, totvs_rh, usp_estagios, workday,
)

log = logging.getLogger("radar")

DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "radar.db"  # working copy, rebuilt from the text files below (not committed)
SITE_DIR = ROOT / "docs"  # served by GitHub Pages

# name -> function(config, conn, today) -> SourceResult
SOURCES: dict[str, Callable[[dict[str, Any], sqlite3.Connection, str], SourceResult]] = {
    "greenhouse": lambda cfg, conn, today: greenhouse.fetch(cfg),
    "lever": lambda cfg, conn, today: lever.fetch(cfg),
    "ashby": lambda cfg, conn, today: ashby.fetch(cfg),
    "github_lists": lambda cfg, conn, today: github_lists.fetch(cfg),
    "gupy": lambda cfg, conn, today: gupy.fetch(cfg),
    "programs": lambda cfg, conn, today: programs.fetch(cfg, conn, today),
    "google": lambda cfg, conn, today: google.fetch(cfg),
    "amazon": lambda cfg, conn, today: amazon.fetch(cfg),
    "nvidia": lambda cfg, conn, today: nvidia.fetch(cfg),
    "microsoft": lambda cfg, conn, today: microsoft.fetch(cfg),
    "deshaw": lambda cfg, conn, today: nextjs_sites.fetch_deshaw(cfg),
    "drw": lambda cfg, conn, today: nextjs_sites.fetch_drw(cfg),
    "meta": lambda cfg, conn, today: meta.fetch(cfg),  # needs Playwright (headless browser)
    # --- Brazil -------------------------------------------------------------
    "ciee": lambda cfg, conn, today: ciee.fetch(cfg),
    "solides": lambda cfg, conn, today: solides.fetch(cfg),
    "superestagios": lambda cfg, conn, today: superestagios.fetch(cfg),
    "iel": lambda cfg, conn, today: iel.fetch(cfg),
    "ciadetalentos": lambda cfg, conn, today: ciadetalentos.fetch(cfg),
    "ciadeestagios": lambda cfg, conn, today: ciadeestagios.fetch(cfg),
    "fapesp": lambda cfg, conn, today: fapesp.fetch(cfg),
    "smartrecruiters": lambda cfg, conn, today: smartrecruiters.fetch(cfg),
    "workday": lambda cfg, conn, today: workday.fetch(cfg),
    "eureca": lambda cfg, conn, today: eureca.fetch(cfg),
    "abler": lambda cfg, conn, today: abler.fetch(cfg),
    "oracle_hcm": lambda cfg, conn, today: oracle_hcm.fetch(cfg),
    "rss_jobs": lambda cfg, conn, today: rss_jobs.fetch(cfg),
    "inhire": lambda cfg, conn, today: inhire.fetch(cfg),
    "eightfold": lambda cfg, conn, today: eightfold.fetch(cfg),
    "bcg": lambda cfg, conn, today: company_sites.fetch_bcg(cfg),
    "goldman": lambda cfg, conn, today: company_sites.fetch_goldman(cfg),
    "ibm": lambda cfg, conn, today: company_sites.fetch_ibm(cfg),
    "totvs_rh": lambda cfg, conn, today: totvs_rh.fetch(cfg),
    "shopee": lambda cfg, conn, today: shopee.fetch(cfg),
    "academia": lambda cfg, conn, today: academia.fetch(cfg),
    "successfactors": lambda cfg, conn, today: successfactors.fetch(cfg),
    "ciee_editais": lambda cfg, conn, today: ciee_editais.fetch(cfg),
    "mudes": lambda cfg, conn, today: mudes.fetch(cfg),
    "recrutei": lambda cfg, conn, today: recrutei.fetch(cfg),
    "quickin": lambda cfg, conn, today: quickin.fetch(cfg),
    "parana": lambda cfg, conn, today: parana.fetch(cfg),
    "usp_estagios": lambda cfg, conn, today: usp_estagios.fetch(cfg),
    # --- Remote job boards: one entry per board, so each one is credited and closes its own roles ---
    "himalayas": lambda cfg, conn, today: remote_boards.fetch(cfg, ["himalayas"]),
    "remotive": lambda cfg, conn, today: remote_boards.fetch(cfg, ["remotive"]),
    "jobicy": lambda cfg, conn, today: remote_boards.fetch(cfg, ["jobicy"]),
    "remoteok": lambda cfg, conn, today: remote_boards.fetch(cfg, ["remoteok"]),
    "workingnomads": lambda cfg, conn, today: remote_boards.fetch(cfg, ["workingnomads"]),
}


def run_source(name: str, config: dict[str, Any], conn: sqlite3.Connection | None, today: str) -> tuple[list[Opportunity], report.SourceHealth]:
    """Run one source. Whatever happens inside, this never raises."""
    health = report.SourceHealth(name=name)
    started = time.monotonic()
    try:
        result = SOURCES[name](config, conn, today)
        health.items, health.checked, health.errors = len(result.items), result.checked, result.errors
        health.failed_orgs = set(result.failed_orgs)
        if result.errors:
            # Everything failed -> "failed"; some parts failed -> "partial".
            health.status = "failed" if not result.items else "partial"
        items = result.items
    except Exception as error:  # noqa: BLE001 - one source must never break the run
        log.exception("Source %s crashed", name)
        health.status, health.errors, items = "failed", [f"{type(error).__name__}: {error}"], []
    health.seconds = time.monotonic() - started
    log.info("%-13s %-7s %4d items (%d checked, %d problems, %.0fs)",
             name, health.status, health.items, health.checked, len(health.errors), health.seconds)
    return items, health


# Sources that need the database run in the main thread (an SQLite connection stays in its own thread).
NEEDS_DB = {"programs"}
PARALLEL_SOURCES = 6


def collect(names: list[str], config: dict[str, Any], conn: sqlite3.Connection, today: str) -> dict[str, tuple[list[Opportunity], report.SourceHealth]]:
    """Run the sources side by side: each one asks a different site, one request at a time, so
    together they take as long as the slowest (Workday, the program pages) instead of the sum."""
    outcomes: dict[str, tuple[list[Opportunity], report.SourceHealth]] = {}
    with ThreadPoolExecutor(max_workers=PARALLEL_SOURCES) as pool:
        running = {name: pool.submit(run_source, name, config, None, today) for name in names if name not in NEEDS_DB}
        for name in names:
            if name in NEEDS_DB:
                outcomes[name] = run_source(name, config, conn, today)
        for name, future in running.items():
            outcomes[name] = future.result()
    return outcomes


def dedupe(items: list[Opportunity]) -> list[Opportunity]:
    """Same URL from two sources (e.g. Greenhouse and a GitHub list) -> keep the first."""
    unique: dict[str, Opportunity] = {}
    for opp in items:
        unique.setdefault(opp.id, opp)
    return list(unique.values())


def apply_status_file(conn: sqlite3.Connection, statuses: dict[str, str]) -> None:
    """Copy the statuses from config/status.yaml into the database."""
    for opp_id, status in (statuses or {}).items():
        try:
            if not db.set_status(conn, str(opp_id), str(status)):
                log.warning("status.yaml: id %s not found", opp_id)
        except ValueError as error:
            log.warning("status.yaml: %s (%s)", error, opp_id)


def run(
    only: list[str] | None = None,
    db_path: Path = DB_PATH,
    site_dir: Path = SITE_DIR,
    send: bool = True,
    text_dir: Path | None = None,
) -> report.ReportData:
    today = date.today().isoformat()
    config = load_config()
    text_dir = Path(text_dir or Path(db_path).parent)  # data/opportunities.jsonl, data/page_hashes.jsonl
    conn = db.open_state(db_path, text_dir)
    db.mark_previous_new_as_seen(conn, today)

    # 1. Collect from every source.
    collected: dict[str, list[Opportunity]] = {}
    health: list[report.SourceHealth] = []
    names = [name for name in SOURCES if not only or name in only]
    outcomes = collect(names, config, conn, today)
    for name in names:  # in the SOURCES order, whatever finished first (dedupe keeps the first copy)
        collected[name], source_health = outcomes[name]
        health.append(source_health)
    all_items = dedupe([opp for items in collected.values() for opp in items])

    # 1b. Read the job pages the lists left out (pay, skills, course, level).
    details.enrich(all_items, conn, today)

    # 2. Label: keyword rules always; Claude on top for new items if a key is set.
    for opp in all_items:
        labels.apply_rules(opp)
    area_guess.fill(all_items)  # a probable field for titles the rules can't place (sorting only)
    labeled_by = "keyword rules"
    if llm.enabled():
        known = db.existing_ids(conn)
        fresh = [opp for opp in all_items if opp.id not in known]
        done = llm.refine_labels(fresh)
        labeled_by = f"keyword rules + Claude ({done} new items)"

    # 3. Store. A source that worked also tells us which of its old postings disappeared (= closed).
    #    A partial source whose failures were whole companies' boards (one Workday site answered 429)
    #    still tells us for every other company; a source that failed in another way doesn't.
    for opp in all_items:
        db.upsert(conn, opp, today)
    for h in health:
        seen = {o.id for o in collected[h.name] if o.is_open}
        if h.status == "ok":
            db.mark_missing_as_closed(conn, h.name, seen)
        elif h.status == "partial" and h.failed_orgs and len(h.failed_orgs) == len(h.errors):
            db.mark_missing_as_closed(conn, h.name, seen, keep_orgs=h.failed_orgs)
    db.close_stale(conn, today)
    apply_status_file(conn, config.get("status") or {})
    conn.commit()

    # 4. Reports, website data and notifications.
    everything = db.load_all(conn)
    data = report.build(everything, health, today, labeled_by)
    digest_settings = config.get("digest") or {}
    site.write_data(everything, health, today, labeled_by, site_dir, digest.subscribe_links(digest_settings), config.get("programs"))
    digest.write_feeds(everything, today, digest_settings, site_dir)
    if Path(site_dir).resolve() == SITE_DIR.resolve():  # the real run (tests write their site elsewhere)
        # "45 fontes", "cerca de 31.000 vagas" in the README and the guide
        counts.update(ROOT, counts.counts(config, len(SOURCES), [o for o in everything if o.is_open]))
    db.save_text(conn, text_dir)  # the committed copy of the database (see db.save_text)
    conn.close()
    if send:
        notify.notify(data)  # your private digest (TELEGRAM_CHAT_ID / EMAIL_TO)
        digest.post(everything, today, digest_settings)  # the public channel, if configured
        # each subscriber's own highlights, the same the site shows (radar/picks.py)
        telegram_bot.send_daily([site.item_record(o) for o in everything if o.is_open], today)
    return data


def check_config() -> int:
    """Verify every company slug and program URL; print a table. Returns #problems."""
    from .http import get_json, get_text

    config = load_config()
    urls = {"greenhouse": greenhouse.URL, "lever": lever.URL, "ashby": ashby.URL}
    problems = 0
    for ats, url in urls.items():
        for company in config["companies"].get(ats) or []:
            try:
                data = get_json(url.format(slug=company["slug"]))
                count = len(data) if isinstance(data, list) else len(data.get("jobs", []))
                print(f"OK    {ats:10} {company['slug']:28} {count} jobs")
            except Exception as error:  # noqa: BLE001
                problems += 1
                print(f"FAIL  {ats:10} {company['slug']:28} {error}")
    for program in config["programs"]:
        try:
            text = programs.page_text(program)
            print(f"OK    program    {program['name'][:45]:45} {len(text)} chars")
        except Exception as error:  # noqa: BLE001
            problems += 1
            print(f"FAIL  program    {program['name'][:45]:45} {error}")
    return problems


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(prog="python -m radar", description="Collect student opportunities.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status", "check-config", "discover"])
    parser.add_argument("args", nargs="*", help="for status: <id> <new|seen|applied|ignored>")
    parser.add_argument("--only", help="comma-separated source names, e.g. gupy,programs")
    parser.add_argument("--no-notify", action="store_true", help="don't send Telegram/email")
    options = parser.parse_args(argv)

    if options.command == "status":
        if len(options.args) != 2:
            parser.error("usage: python -m radar status <id> <new|seen|applied|ignored>")
        conn = db.open_state(DB_PATH, DATA_DIR)
        found = db.set_status(conn, options.args[0], options.args[1])
        conn.commit()
        db.save_text(conn, DATA_DIR)
        print("updated" if found else "id not found")
        return 0 if found else 1
    if options.command == "check-config":
        return 1 if check_config() else 0
    if options.command == "discover":
        from . import discover

        discover.run()
        return 0

    only = [name.strip() for name in options.only.split(",")] if options.only else None
    if only:
        unknown = set(only) - set(SOURCES)
        if unknown:
            parser.error(f"unknown source(s): {', '.join(sorted(unknown))}; choose from {', '.join(SOURCES)}")
    data = run(only=only, send=not options.no_notify)
    print(f"\nDone: {data.total_open} open, {data.new_total} new. Website data in {SITE_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
