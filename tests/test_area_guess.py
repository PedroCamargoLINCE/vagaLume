"""Probable fields for roles the rules can't place (radar/area_guess.py), without the model."""

import pytest

from radar import area_guess
from radar.labels import apply_rules
from radar.models import Opportunity


@pytest.mark.parametrize("title, nothing", [
    ("Internship", True),
    ("Summer 2027 Interns - South Carolina", True),
    ("ESTÁGIO – OPORTUNIDADES EM DIFERENTES ÁREAS", True),
    ("STAGE - Câblage & Intégration Avionique (h/f)", False),
    ("Duales Studium Informatik 2027", False),
    ("Heavy Duty Mechanic Apprentice", False),
])
def test_titles_that_say_nothing_get_no_guess(title, nothing):
    assert area_guess.says_nothing(title) is nothing


def test_only_roles_without_a_field_need_a_guess():
    placed = apply_rules(Opportunity(title="Estágio em Direito", org="X", source="gupy", url="https://a", location="São Paulo, SP"))
    unplaced = apply_rules(Opportunity(title="STAGE - Câblage & Intégration Avionique", org="X", source="workday", url="https://b", location="Toulouse, France"))
    assert placed.fields and not area_guess.needs_guess(placed)
    assert not unplaced.fields and area_guess.needs_guess(unplaced)


def test_vote_keeps_the_main_field_and_a_strong_second_one():
    np = pytest.importorskip("numpy")
    fields = [["engenharia"]] * 7 + [["computacao"]] * 3 + [["direito"]] * 5
    sims = np.array([0.9] * 7 + [0.95] * 3 + [0.1] * 5)
    assert area_guess.vote(sims, fields) == ["engenharia", "computacao"]  # 69% / 31% of the 10 closest
    split = [["engenharia"]] * 5 + [["computacao"]] * 5
    assert area_guess.vote(np.array([0.9] * 10), split) == []  # no field holds 60%: no guess


def test_without_the_model_nothing_is_guessed(monkeypatch):
    def missing():
        raise ImportError("onnxruntime")

    monkeypatch.setattr(area_guess, "_Embedder", missing)
    roles = [apply_rules(Opportunity(title=f"Estágio em Direito {n}", org="X", source="gupy", url=f"https://a/{n}", location="São Paulo, SP")) for n in range(12)]
    roles.append(apply_rules(Opportunity(title="STAGE - Câblage avionique", org="X", source="workday", url="https://b", location="Toulouse, France")))
    assert area_guess.fill(roles) == 0 and roles[-1].guess == []
