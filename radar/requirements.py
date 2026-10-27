"""What a Brazilian estágio asks for, read from its description with text patterns (no AI):
semester, expected graduation, English, weekly hours and courses.

Brazilian postings write these in a few set phrases ("a partir do 5º semestre", "previsão de
formatura: Dez/2025 até Dez/2027", "inglês avançado", "30 horas semanais", "cursando Direito ou
Economia"), so patterns find most of them. Each reader returns nothing rather than a guess: a
missing field shows nothing on the site, a wrong one would mislead.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_ORDINAL_WORDS = {"primeiro": 1, "segundo": 2, "terceiro": 3, "quarto": 4, "quinto": 5, "sexto": 6, "setimo": 7,
                  "oitavo": 8, "nono": 9, "decimo": 10}
_ORD = r"(\d{1,2})\s*(?:º|°|o|ª|a|\.)?|(" + "|".join(_ORDINAL_WORDS) + r")"
_TERM = r"(semestre|periodo|ano|modulo)s?"
_MONTHS = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10,
           "nov": 11, "dez": 12}


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _ordinal(number: str | None, word: str | None) -> int:
    return int(number) if number else _ORDINAL_WORDS.get(word or "", 0)


def _pay_tier(text: str, match: re.Match[str]) -> bool:
    """ "R$ 1.684,00 para o 1º e 2º anos e R$ 1.895,00 a partir do 3º ano" is the stipend by year, not a requirement."""
    return bool(re.search(r"r\$|bolsa", text[max(0, match.start() - 45):match.start()]))


def _sane(found: dict[str, Any], match: re.Match[str]) -> dict[str, Any] | None:
    """ "no mínimo 1 ano" is how long the estágio lasts and "de 3 a 10 anos" an age, not a year of the course:
    a year counts only when written as an ordinal ("4º ano", "quarto ano") and up to the 6th."""
    if _pay_tier(match.string, match):
        return None
    if found.get("unit") != "ano":
        return found
    ordinal = re.search(r"\d\s*(?:º|°|o|ª)\b|" + "|".join(_ORDINAL_WORDS), match[0])
    return found if ordinal and max(found.get("from", 0), found.get("to", 0)) <= 6 else None


def semester(text: str) -> dict[str, Any] | None:
    """ "a partir do 5º semestre" -> {"from": 5, "unit": "semestre"}; "entre o 5º e 8º período" / "(2º ao 7º
    semestre)" -> from 5 (2), to 8 (7); "até o 4º período" -> {"to": 4}; "penúltimo ou último ano" -> {"last": True}.
    A pay table ("3º e 4º semestre: R$ 1.600") is not a requirement: "N e M" needs "entre" before it."""
    t = _plain(text)
    match = (re.search(rf"entre\s*(?:o\s*)?(?:{_ORD})\s*(?:{_TERM})?\s*e\s*(?:o\s*)?(?:{_ORD})\s*{_TERM}", t)
             or re.search(rf"(?:{_ORD})\s*(?:{_TERM})?\s*(?:ao|a|ate o|ate)\s*(?:o\s*)?(?:{_ORD})\s*{_TERM}", t))
    if match:
        low, high = _ordinal(match[1], match[2]), _ordinal(match[4], match[5])
        if 1 <= low < high <= 12 and (found := _sane({"from": low, "to": high, "unit": match[6]}, match)):
            return found
    match = (re.search(rf"(?:a partir d[oa]|acima d[oa]|minimo(?: de)?,?(?: o)?|cursando o|apartir do|pelo menos o)\s*(?:{_ORD})\s*{_TERM}", t)
             or re.search(rf"(?:{_ORD})\s*{_TERM}\s*(?:em diante|ou mais|para frente|ou superior)", t))
    if match and 1 <= (low := _ordinal(match[1], match[2])) <= 12 and (found := _sane({"from": low, "unit": match[3]}, match)):
        return found
    match = re.search(rf"(?:ter concluido|concluido|concluidos) (?:o|os|ate o)?\s*(?:{_ORD})\s*{_TERM}", t)
    if match and 1 <= (done := _ordinal(match[1], match[2])) <= 11 and (found := _sane({"from": done + 1, "unit": match[3]}, match)):
        return found
    match = re.search(rf"(?:cursando|estar|estudantes?|alunos?)[^.;\n]{{0,40}}\bate o\s*(?:{_ORD})\s*{_TERM}", t)
    if match and 1 <= (high := _ordinal(match[1], match[2])) <= 12 and (found := _sane({"to": high, "unit": match[3]}, match)):
        return found
    # "penúltimo ou último ano (ensino superior)", not "dobrou de tamanho nos últimos anos"
    for last in re.finditer(r"\b(?:penultimo|ultimo) (?:ou ultimo )?(ano|semestre|periodo)\b", t):
        if re.search(r"cursando|estudante|graduac|curso|matricul|faculdade", t[max(0, last.start() - 80):last.end() + 40]):
            return {"last": True, "unit": last[1]}
    return None


# A month, or half a year: "dez/2027", "12/2027", "dezembro de 2027", "2027.2", "2028/2", "2º semestre de 2028", "2028".
_WHEN = (r"(?:(?P<half>[12])\s*(?:o|º|°)?\s*semestre\s*(?:de|/)\s*(?P<hy>20\d\d)"
         r"|(?P<y2>20\d\d)\s*[./]\s*(?P<h2>[12])(?!\d)"
         r"|(?:(?P<mon>jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*\.?\s*(?:de\s*|/\s*)?|(?P<mm>\d{1,2})\s*/\s*)?(?P<y>20\d\d))")
_WHEN_B = re.sub(r"\?P<(\w+)>", r"?P<\1_b>", _WHEN)  # the same, for the second date of a range


def _span(match: re.Match[str], suffix: str = "") -> tuple[str, str]:
    """(first month, last month) that a matched _WHEN covers."""
    g = {k[:len(k) - len(suffix)]: v for k, v in match.groupdict().items() if k.endswith(suffix) and (suffix or not k.endswith("_b"))}
    if g.get("hy") or g.get("y2"):
        year, half = (g["hy"], g["half"]) if g.get("hy") else (g["y2"], g["h2"])
        return (f"{year}-01", f"{year}-06") if half == "1" else (f"{year}-07", f"{year}-12")
    month = _MONTHS.get((g.get("mon") or "")[:3]) or (int(g["mm"]) if g.get("mm") and 1 <= int(g["mm"]) <= 12 else 0)
    return (f"{g['y']}-{month:02d}", f"{g['y']}-{month:02d}") if month else (f"{g['y']}-01", f"{g['y']}-12")


_GRAD_WORDS = re.compile(r"formatura|conclusao|graduacao|termino|formacao prevista|se formar|formando")


def graduation(text: str) -> dict[str, str] | None:
    """When the course must end: "previsão de formatura: Dez/2025 até Dez/2027" -> {"from": "2025-12",
    "to": "2027-12"}; "conclusão a partir de dezembro de 2027" / "2027.2 em diante" -> {"from": ...};
    "formatura até 12/2028" -> {"to": "2028-12"}; "previsão de graduação para 2028" -> the whole year."""
    t = _plain(text)
    for word in _GRAD_WORDS.finditer(t):
        part = re.split(r"[;\n•]|\.\s", t[word.start():word.start() + 130])[0]
        if not re.search(r"previs|prevista|previsto|formatura|conclusao|formacao prevista|se formar|termino", part):
            continue
        if re.search(r"nao (?:representa|garante)|garantia", part):
            continue
        between = re.search(rf"(?:entre|de|no|em)?\s*{_WHEN}\s*(?:e|a|ate o|ate|-|–)\s*(?:o\s*)?{_WHEN_B}", part)
        if between:
            return {"from": _span(between)[0], "to": _span(between, "_b")[1]}
        after = (re.search(rf"(?:a partir d[eo]|apos|depois de|nao antes de|igual ou posterior a|posterior a|(?:no )?minimo,?\s*(?:em|para|de)?)\s*(?:o\s*)?{_WHEN}", part)
                 or re.search(rf"minima\s*(?:prevista\s*)?(?:para|em|de)\s*{_WHEN}", part)
                 or re.search(rf"{_WHEN}\s*(?:em diante|ou apos|ou depois|ou posterior)", part))
        if after:
            return {"from": _span(after)[0]}
        until = re.search(rf"(?:ate|antes de|no maximo em)\s*(?:o\s*)?(?:(?:final|fim) de\s*)?{_WHEN}", part)
        if until:
            return {"to": _span(until)[1]}
        single = re.search(rf"(?:para|em|:|no|de)\s*(?:o\s*)?{_WHEN}", part)
        if single:
            first, last = _span(single)
            return {"from": first, "to": last}
    return None


_LEVELS = {"basico": "básico", "intermediario": "intermediário", "avancado": "avançado", "fluente": "fluente",
           "fluencia": "fluente", "tecnico": "técnico", "leitura": "leitura"}
_LEVEL = r"(basico|intermediario|avancado|fluente|fluencia|tecnico|leitura)"
_WISH = re.compile(r"desejave(?:l|is)|diferencia(?:l|is)|preferencia(?:l|lmente)|nao obrigatori|sera um plus|nice to have|bonus")


def english(text: str) -> dict[str, Any] | None:
    """ "Inglês avançado" -> {"level": "avançado", "required": True}; "Desejável inglês intermediário" ->
    required False. "Letras Inglês" or "aulas em inglês" are courses or tasks, not a requirement."""
    t = _plain(text)
    for match in re.finditer(rf"ingles\s*(?:\(|:|-|a nivel|nivel|em nivel|no nivel|minimo)?\s*{_LEVEL}"
                             rf"|{_LEVEL}\w*\s+(?:(?:de|em|no)\s+)?(?:lingua\s+)?ingles|(?:fluencia|dominio) (?:em|no|do) ingles", t):
        if re.search(r"letras\W*$", t[max(0, match.start() - 12):match.start()]):
            continue
        word = match[1] or match[2] or ("fluente" if "fluencia" in match[0] else "avançado")
        clause = re.split(r"[;\n•]|\.\s", t[max(0, match.start() - 80):match.start()])[-1]
        after = re.split(r"[;\n•]|\.\s?|,\s", t[match.end():match.end() + 40])[0]  # "inglês avançado; diferencial: espanhol"
        return {"level": _LEVELS.get(word, word), "required": not _WISH.search(clause + " " + after)}
    return None


def hours(text: str) -> int | None:
    """Weekly hours: "30 horas semanais" -> 30, "6h por dia" / "carga horária de 06h/dia" -> 30 (5 days)."""
    t = _plain(text)
    weekly = re.search(r"\b([1-4]\d)\s*(?:h|hs|horas)\s*(?:semanais|por semana|/\s*semana|semanal)", t)
    if weekly and 10 <= int(weekly[1]) <= 40:
        return int(weekly[1])
    daily = re.search(r"\b0?([4-8])\s*(?:h|hs|horas)\s*(?:diarias|por dia|/\s*dia|diarios|ao dia)", t)
    if daily and "24" not in t[max(0, daily.start() - 3):daily.start()]:
        return int(daily[1]) * 5
    return None


_COURSE_STOP = re.compile(
    r"\s*(?:,\s*)?(?:a partir|com previs|preferencial|que esteja|do \d|entre o|no \d|em qualquer|cursando|matriculad|"
    r"com disponibilidade|disponibilidade|e ter|ter |que |para |estar |com conhecimento|conhecimento|com |\(|\d)",
    re.I)
_COURSE_LEAD = re.compile(r"^(?:faculdade(?: nas areas de| em| de)?|(?:tecnico|tecnologo) ou graduacao(?: em)?:?|o curso de|os cursos de|cursos? de|cursos? superior(?:es)? (?:de|em)|ensino superior(?: completo)?(?: em| de| nas seguintes areas:?| nos cursos de)?|"
                          r"graduacao(?: em| de)?|bacharelado(?: em| de)?|licenciatura(?: em| de)?|superior(?: em| de)?|"
                          r"tecnologo(?: em)?|ensino tecnico em|tecnico em|uma das seguintes areas:?|areas? de|nas areas de|"
                          r"em|de|as seguintes areas:?)\s*", re.I)
_NOT_COURSE = re.compile(r"^(?:ensino|superior|graduacao|qualquer|todos|areas?|cursos?|afins|correlat\w*|relacionad\w*|similares|"
                         r"outros|entre outros|etc|ou|e|ead|presencial|semipresencial|noturno|diurno|bacharelado|licenciatura|"
                         r"tecnologo|tecnico|andamento|em andamento)$")


def courses(text: str) -> list[str]:
    """ "Cursando Administração, Ciências Contábeis, Economia ou áreas correlatas" -> ["Administração",
    "Ciências Contábeis", "Economia"] (as written, accents kept). Empty when the text names no course."""
    # Lists glued together by the source ("RECURSOS HUMANOSFormação prevista", "AdministraçãoDisponibilidade").
    text = re.sub(r"(?<=[a-zà-ÿ])(?=[A-ZÀ-Þ][a-zà-ÿ])|(?<=[A-ZÀ-Þ]{2})(?=[A-ZÀ-Þ][a-zà-ÿ])", ". ", text)
    text = re.sub(r"\b(de|em|da|do|das|dos|e|ou)\s*\n\s*", r"\1 ", text)  # "Engenharia de\nProdução"
    for match in re.finditer(r"cursando\s+([^.;\n•]{3,160})", text, re.I):
        chunk = _COURSE_STOP.split(match[1], maxsplit=1)[0]
        lead = chunk
        while True:  # "ensino superior em Direito" -> "Direito"
            stripped = _COURSE_LEAD.sub("", _plain(lead), count=1)
            if stripped == _plain(lead):
                break
            lead = lead[len(lead) - len(stripped):]
        names = []
        for part in re.split(r",|/|\bou\b|\be\b(?=\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ])", lead):
            name = re.sub(r"\s+(?:e|ou)$", "", part.strip(" :-–"))
            name = re.sub(r"^(?:bacharelado|licenciatura|tecnologo|graduacao|curso)\s+(?:em|de)\s+", "", name, flags=re.I)
            name = re.sub(r"\s+(?:ou|e)\s+(?:(?:areas?|cursos?)\s+)?(?:afins|correlat\w*|relacionad\w*|similares).*$", "", name, flags=re.I)
            if 2 < len(name) <= 45 and not _NOT_COURSE.match(_plain(name)) and name[:1].isupper():
                names.append(name)
        if names:
            return names[:6]
    return []


def read(text: str) -> dict[str, Any]:
    """Everything found in a description; fields not found are left out."""
    found: dict[str, Any] = {}
    if value := semester(text):
        found["semester"] = value
    if value := graduation(text):
        found["graduation"] = value
    if value := english(text):
        found["english"] = value
    if value := hours(text):
        found["hours"] = value
    if value := courses(text):
        found["courses"] = value
    return found
