"""Companhia de Estágios: the list of programs and one program's own page.
Both are saved (trimmed) real pages from tests/fixtures/, read on 2026-10-21."""

import pytest
from conftest import fixture_text

from radar.labels import apply_rules
from radar.models import NO_DEADLINE
from radar.sources import ciadeestagios

LIST = fixture_text("ciadeestagios_lista.html")
WABTEC = fixture_text("ciadeestagios_wabtec.html")
WABTEC_URL = "https://www.ciadeestagios.com.br/vagas/wabtec/"


def test_cards_keep_only_open_programs():
    found = ciadeestagios.cards(LIST)
    titles = [card["title"] for card in found]
    assert len(found) == 11  # 15 programs: 4 closed ("--expired"), plus the "faça seu cadastro" card
    assert "Programa de Estágio Danone 2027" not in titles  # inscrições encerradas
    assert not any("Aprendiz" in t for t in titles)
    assert "Programa de Estágio Wabtec 2027" in titles
    assert all("utm_" not in card["url"] for card in found)  # tracking removed
    assert any(card["url"] == "https://estagiopirelli.com.br/" for card in found)  # hosted elsewhere


def test_program_page_gives_company_cities_and_deadline():
    card = {"title": "Programa de Estágio Wabtec 2027", "url": WABTEC_URL}
    opp = ciadeestagios.parse_program(card, WABTEC)
    assert opp.org == "Wabtec" and opp.source == "ciadeestagios"
    assert opp.deadline == "2026-10-30" and opp.posted_date == "2026-09-21"
    assert opp.location.startswith("Araraquara, SP; Contagem, MG") and opp.location.endswith(", Brazil")
    assert "Engenharia de Controle e Automação" in opp.description and "<" not in opp.description
    assert opp.hints == ["student"]
    apply_rules(opp)
    assert opp.regions == ["Brazil"]
    assert {"SP", "MG", "PR"} <= set(opp.states)


def test_card_alone_still_makes_a_role():
    opp = ciadeestagios.parse_program({"title": "Programa de Estágio Pirelli 2027", "url": "https://estagiopirelli.com.br/"})
    assert opp.org == "Pirelli" and opp.location == "Brazil" and opp.deadline == NO_DEADLINE


def test_org_from_other_title_shapes():
    org = ciadeestagios._org
    assert org({}, "Programa de Estágio Afirmativo Livelo 2027") == "Livelo"
    assert org({}, "Estágio de Último Ano Votorantim Cimentos 2027") == "Votorantim Cimentos"


def test_org_drops_the_agency_name():
    org = ciadeestagios._org
    title = "Programa de Estágio Mercedes-Benz 2027"
    assert org({"hiringOrganization": {"name": "Companhia de Estágios | Mercedes-Benz"}}, title) == "Mercedes-Benz"
    assert org({"hiringOrganization": {"name": "Companhia de Estágios"}}, title) == "Mercedes-Benz"


def test_fetch_opens_only_open_programs_on_the_site():
    asked = []

    def fake_get(url):
        asked.append(url)
        if url == ciadeestagios.LIST_URL:
            return LIST
        if url == WABTEC_URL:
            return WABTEC
        raise OSError("offline in the test")

    result = ciadeestagios.fetch({}, get=fake_get)
    assert len(result.items) == 11
    assert "https://estagiopirelli.com.br/" not in asked  # never leaves the site
    assert not any("danone" in url for url in asked)  # closed programs are not opened
    wabtec = next(o for o in result.items if o.url == WABTEC_URL)
    assert wabtec.deadline == "2026-10-30"
    assert len(result.errors) == 9  # the other pages failed in this test, but their cards stay


def test_unexpected_page_raises():
    with pytest.raises(ValueError):
        ciadeestagios.cards("<html><body>Manutenção</body></html>")
