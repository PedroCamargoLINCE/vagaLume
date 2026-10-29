"""Companhia de Estágios: the agency that runs the estágio programs of many
big companies in Brazil (Boeing, Mercedes-Benz, Wabtec, Livelo, Ingredion...).

Its list of programs, https://www.ciadeestagios.com.br/vagas-de-estagio/, is a
plain WordPress page (robots.txt allows it). Each program is one card:

  <article class="vagas__card " data-permalink="https://www.ciadeestagios.com.br/vagas/wabtec/?utm_...">
    <h2 ...>Programa de Estágio Wabtec 2027</h2>
  <article class="vagas__card --expired" ...>   <- "Inscrições encerradas": skipped

Most programs have their own page on the same site (/vagas/<empresa>/ or
/programas/<empresa>), which declares a schema.org JobPosting in JSON-LD:
company, cities, datePosted, validThrough (the last day to apply) and the full
description. We open only the open programs' pages, one request each. A
program hosted elsewhere (estagiopirelli.com.br) keeps what the card says.
The application itself happens on carreira.ciadeestagios.com.br, behind a
login, which we never touch.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any, Callable

from ..http import get_text
from ..models import NO_DEADLINE, Opportunity, strip_tracking
from ..readers_more import _ld_job
from ..textutil import html_to_text, iso_date
from . import SourceResult

NAME = "ciadeestagios"
LIST_URL = "https://www.ciadeestagios.com.br/vagas-de-estagio/"
SITE = "ciadeestagios.com.br/"

_CARD = re.compile(r'<article class="vagas__card([^"]*)"(.*?)</article>', re.S)
_PERMALINK = re.compile(r'data-permalink="([^"]+)"')
_TITLE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)
# "Programa de Estágio Afirmativo Livelo 2027" -> "Livelo"; "Estágio de Último Ano Votorantim Cimentos 2027" -> ...
_TITLE_WORDS = re.compile(
    r"^(?:programa\s+de\s+)?est[áa]gio\s+(?:afirmativo\s+|de\s+[úu]ltimo\s+ano\s+)?|\s+\d{4}(?:[./]\d)?$", re.I
)
APPRENTICE = re.compile(r"aprendiz", re.I)  # jovem aprendiz is not a university role, like in gupy.py


def cards(page: str) -> list[dict[str, str]]:
    """The open programs on the list page: [{"title": ..., "url": ...}]."""
    found: list[dict[str, str]] = []
    for classes, body in _CARD.findall(page):
        link, title = _PERMALINK.search(body), _TITLE.search(body)
        if not link or not title or "--expired" in classes:
            continue  # the "faça seu cadastro" card, or applications closed
        name = html_to_text(unescape(title.group(1))).strip()
        if APPRENTICE.search(name):
            continue
        found.append({"title": name, "url": strip_tracking(unescape(link.group(1)))})
    if not found and "vagas__card" not in page:
        raise ValueError("unexpected page from Companhia de Estágios (no program cards)")
    return found


AGENCY = re.compile(r"^\s*(?:companhia|cia\.?)\s+de\s+est[áa]gios\s*$", re.I)


def _org(job: dict[str, Any], title: str) -> str:
    """The company: hiringOrganization.name, or the title without "Programa de Estágio ... 2027".
    Some pages name the agency too ("Companhia de Estágios | Mercedes-Benz"): keep the company."""
    company = job.get("hiringOrganization")
    name = str(company.get("name") or "") if isinstance(company, dict) else ""
    parts = [p.strip() for p in name.split("|") if p.strip() and not AGENCY.match(p)]
    if parts:
        return parts[-1]
    return _TITLE_WORDS.sub("", title).strip() or "Companhia de Estágios"


def _location(job: dict[str, Any]) -> str:
    """JSON-LD jobLocation (one place or a list) -> "Araraquara, SP; Contagem, MG, Brazil"."""
    places = job.get("jobLocation")
    places = places if isinstance(places, list) else [places] if places else []
    cities: list[str] = []
    for place in places:
        address = place.get("address") if isinstance(place, dict) else None
        if not isinstance(address, dict):
            continue
        parts = [str(address.get(k) or "").strip() for k in ("addressLocality", "addressRegion")]
        city = ", ".join(p for p in parts if p)
        if city and city not in cities:
            cities.append(city)
    return "; ".join(cities) + ", Brazil" if cities else "Brazil"


def parse_program(card: dict[str, str], page: str = "") -> Opportunity:
    """One program from its card and, when we have it, its own page's JSON-LD."""
    job = _ld_job(page) if page else {}
    title = str(job.get("title") or card["title"]).strip()
    deadline = iso_date(job.get("validThrough")) or NO_DEADLINE
    return Opportunity(
        title=title,
        org=_org(job, title),
        source=NAME,
        url=card["url"],
        location=_location(job),
        posted_date=iso_date(job.get("datePosted")),
        deadline=deadline,
        description=html_to_text(str(job.get("description") or "")),
        hints=["student"],  # every program here is an estágio
    )


def parse(page: str, program_pages: dict[str, str] | None = None) -> list[Opportunity]:
    """The list page plus {url: program page html} -> one Opportunity per open program."""
    program_pages = program_pages or {}
    return [parse_program(card, program_pages.get(card["url"], "")) for card in cards(page)]


def fetch(config: dict[str, Any], get: Callable[[str], str] = get_text) -> SourceResult:
    found = cards(get(LIST_URL))
    pages: dict[str, str] = {}
    errors: list[str] = []
    for card in found:
        if SITE not in card["url"]:
            continue  # hosted elsewhere: keep the card as it is
        try:
            pages[card["url"]] = get(card["url"])
        except Exception as error:  # noqa: BLE001 - one program page must not lose the others
            errors.append(f"{card['url']}: {type(error).__name__}: {error}")
    items = [parse_program(card, pages.get(card["url"], "")) for card in found]
    return SourceResult(items=items, errors=errors, checked=1 + len(pages) + len(errors))
