"""The single record shape that every source returns.

Each source module (greenhouse.py, gupy.py, ...) turns whatever its website
sends back into a list of `Opportunity` objects. Everything after that
(labelling, storage, reports) only ever deals with this one shape.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

# Used when we could not find a deadline anywhere.
NO_DEADLINE = "check page"


def make_id(url: str) -> str:
    """Return a short, stable id for a posting: a hash of its URL.

    The same URL always gives the same id, which is how we spot duplicates
    across runs. We strip tracking junk such as `?utm_source=...` first so
    that the same job linked from two places still gets one id.
    """
    clean = strip_tracking(url).strip().rstrip("/").lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]


def strip_tracking(url: str) -> str:
    """Remove utm_* / ref= style tracking parameters from a URL."""
    if "?" not in url:
        return url
    base, query = url.split("?", 1)
    kept = [
        part
        for part in query.split("&")
        if part
        and not part.lower().startswith(("utm_", "ref=", "source=", "jobboardsource=", "gh_src="))
    ]
    return base + ("?" + "&".join(kept) if kept else "")


# Job boards whose address says which job it is without the query ("?gh_jid=", "?domain=microsoft.com"
# repeat what the path already says). Elsewhere the query can be the job (superestagios "...php?i=...").
_PATH_IS_THE_JOB = re.compile(r"myworkdayjobs\.com|greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|eightfold\.ai|careers\.microsoft\.com")
# Workday sites only for a company's own staff ("External_Subsidiary" at Boeing is for current employees).
_INTERNAL_SITE = re.compile(r"myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?[^/]*(?:subsidiar|internal|employee)", re.I)


def same_job_key(url: str) -> str:
    """One key for the addresses of one job: the same Workday job with and without "/en-US/" or in
    upper and lower case, a Greenhouse job with "?gh_jid=", a Microsoft job with "?domain="."""
    url = strip_tracking(url).split("#")[0].rstrip("/")
    # A Greenhouse job is its number, on any domain ("pinterest.com/...?gh_jid=8138039", ".../jobs/8138039").
    gh = re.search(r"[?&]gh_jid=(\d+)", url) or re.search(r"greenhouse\.io/[\w-]+/jobs/(\d+)", url)
    if gh:
        return f"greenhouse:{gh.group(1)}"
    url = re.sub(r"(lever\.co/[^?]+?)/apply$|(ashbyhq\.com/[^?]+?)/application$", lambda m: m.group(1) or m.group(2), url.split("?")[0]) \
        if re.search(r"lever\.co|ashbyhq\.com", url) else url
    if _PATH_IS_THE_JOB.search(url):
        url = url.split("?")[0]
    url = re.sub(r"^https?://(?:www\.)?", "", url)
    url = re.sub(r"(myworkdayjobs\.com)/[a-z]{2}-[A-Z]{2}/", r"\1/", url)
    return url.lower()


def is_internal_site(url: str) -> bool:
    return bool(_INTERNAL_SITE.search(url))


@dataclass
class Opportunity:
    """One posting (or one watched program page)."""

    # --- filled in by the source module -----------------------------------
    title: str
    org: str
    source: str  # e.g. "greenhouse", "gupy", "programs"
    url: str
    location: str = ""
    remote: bool = False
    posted_date: str = ""  # ISO date "YYYY-MM-DD" when known
    deadline: str = NO_DEADLINE  # ISO date, or "check page"
    pay: str = ""  # short label such as "$54–60/hr" or "R$1,800/mo"; "" = not stated
    # Where the pay came from: "field" (the job board's own salary field, set by the source),
    # "text" (read from the description by radar/pay.py) or "claude". The site asks you to check "text" ones.
    pay_from: str = ""
    # The day we last read the role's own job page (radar/details.py); "" = not this run.
    detail_checked: str = ""
    # Free text used only while labelling; it is NOT stored in the database
    # (that keeps the database small enough to commit every day).
    description: str = ""
    # Extra hints a source can pass to the labeller, e.g. the GitHub lists
    # mark roles that need US citizenship with an emoji.
    hints: list[str] = field(default_factory=list)
    # Optional manual labels (used by programs.yaml, where you set them).
    preset: dict[str, object] = field(default_factory=dict)
    # Whether the source still lists it as open (GitHub lists mark closed
    # roles with a lock emoji).
    is_open: bool = True
    # A short note shown in the report (e.g. "page changed on 2026-10-05").
    note: str = ""

    # --- filled in by radar.labels (or radar.llm) --------------------------
    area: str = "other"
    season: str = "unknown"
    regions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    calendar_note: str = ""
    labeled_by: str = "rules"
    skills: list[str] = field(default_factory=list)  # e.g. ["Python", "PyTorch"]; see radar/skills.py
    fields: list[str] = field(default_factory=list)  # fields of study, e.g. ["engenharia"]; see radar/fields.py
    levels: list[str] = field(default_factory=list)  # study levels it's for, e.g. ["masters", "phd"]; see radar/levels.py
    states: list[str] = field(default_factory=list)  # Brazilian states (UFs), e.g. ["SP"]; see radar/places.py
    workplaces: list[str] = field(default_factory=list)  # remote / hybrid / on-site; see radar/workplace.py
    subs: list[str] = field(default_factory=list)  # sub-areas, e.g. ["tributario"]; see radar/subareas.py
    # What a Brazilian estágio asks for, read from its text: semester, graduation, English, hours, courses
    # (radar/requirements.py). Shown on the site as it is, never used to sort or hide.
    requirements: dict[str, Any] = field(default_factory=dict)
    # Probable fields of a role the rules could not place, from similar titles (radar/area_guess.py).
    # Only moves the role up the list for students of that field; it never hides a role.
    guess: list[str] = field(default_factory=list)

    # --- filled in by radar.db ---------------------------------------------
    first_seen: str = ""
    status: str = "new"

    @property
    def id(self) -> str:
        return make_id(self.url)
