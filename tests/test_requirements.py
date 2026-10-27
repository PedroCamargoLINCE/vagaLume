"""Requirements read from Brazilian estágio descriptions (radar/requirements.py); the cases are real phrasings."""

import pytest

from radar import requirements


@pytest.mark.parametrize("text, expected", [
    ("Cursando Direito, a partir do 5° semestre;", {"from": 5, "unit": "semestre"}),
    ("Cursando Geologia entre o 5º e 8º período com previsão", {"from": 5, "to": 8, "unit": "periodo"}),
    ("Ensino superior cursando (2º ao 7º semestre);", {"from": 2, "to": 7, "unit": "semestre"}),
    ("Estudantes de engenharia cursando, no mínimo, o 8º período;", {"from": 8, "unit": "periodo"}),
    ("Ter concluído o 5º período ou estar em conclusão", {"from": 6, "unit": "periodo"}),
    ("Cursando a partir do segundo semestre de História", {"from": 2, "unit": "semestre"}),
    ("Cursando penúltimo ou último ano (ensino superior)", {"last": True, "unit": "ano"}),
    ("Estar cursando até o 4º semestre do curso superior", {"to": 4, "unit": "semestre"}),
    ("Disponibilidade para estagiar por no mínimo 1 ano", None),  # how long, not which year
    ("Atendimento a crianças de 3 a 10 anos", None),
    ("R$ 1.684,00 para o 1º e 2º anos e R$ 1.895,00 a partir do 3º ano", None),  # stipend by year
])
def test_semester(text, expected):
    assert requirements.semester(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Previsão de formatura: Dez/2025 até Dez/2027", {"from": "2025-12", "to": "2027-12"}),
    ("previsão de conclusão entre 07/2028 e 12/2030", {"from": "2028-07", "to": "2030-12"}),
    ("Conclusão: no 1 semestre de 2027 até o 1 semestre de 2029.", {"from": "2027-01", "to": "2029-06"}),
    ("previsão de conclusão de curso a partir de 12/2027;", {"from": "2027-12"}),
    ("com previsão de formatura de 2027.2 em diante.", {"from": "2027-07"}),
    ("ter a previsão de formatura a partir de 2027.2interesse", {"from": "2027-07"}),
    ("data de conclusão de curso igual ou posterior a 2028/2", {"from": "2028-07"}),
    ("tem previsão de formatura até o final de 2028?", {"to": "2028-12"}),
    ("previsão de conclusão de curso para 2º semestre de 2028;", {"from": "2028-07", "to": "2028-12"}),
    ("A conclusão do curso não representa garantia de contratação em 2027", None),
])
def test_graduation(text, expected):
    assert requirements.graduation(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Inglês avançado (para comunicação)", {"level": "avançado", "required": True}),
    ("Desejável inglês a nível intermediário;", {"level": "intermediário", "required": False}),
    ("Inglês intermediário será um diferencial.", {"level": "intermediário", "required": False}),
    ("Fluência em inglês (para turmas bilíngues)", {"level": "fluente", "required": True}),
    ("Cursando Pedagogia, Psicologia ou Letras Inglês", None),
    ("pacote office avançadoinglês será considerado um diferencial", None),  # "avançado" is Office's
])
def test_english(text, expected):
    assert requirements.english(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Jornada de 30h semanais, de segunda a sexta", 30),
    ("Carga horária de 06h/dia", 30),
    ("Disponibilidade para estagiar 4 horas diárias", 20),
    ("Atendimento 7 dias por semana, 24 horas por dia", None),
])
def test_hours(text, expected):
    assert requirements.hours(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Cursando Administração, Ciências Contábeis, Economia ou áreas correlatas;", ["Administração", "Ciências Contábeis", "Economia"]),
    ("Estar cursando ensino superior em: Tecnologia da Informação, Redes de Computadores", ["Tecnologia da Informação", "Redes de Computadores"]),
    ("Cursando ensino superior em Administração, Economia e Engenharia de\nProdução, a partir", ["Administração", "Economia", "Engenharia de Produção"]),
    ("Cursando Licenciatura ou Bacharelado em Física, a partir do 5º semestre", ["Física"]),
    ("Cursando ADMINISTRAÇÃO DE EMPRESAS, RECURSOS HUMANOSFormação prevista para 2027", ["ADMINISTRAÇÃO DE EMPRESAS", "RECURSOS HUMANOS"]),
    ("Cursando ensino superior", []),
])
def test_courses(text, expected):
    assert requirements.courses(text) == expected


def test_read_leaves_out_what_is_not_there():
    assert requirements.read("Cursando Direito, a partir do 4º período; inglês intermediário; 30 horas semanais") == {
        "semester": {"from": 4, "unit": "periodo"}, "english": {"level": "intermediário", "required": True},
        "hours": 30, "courses": ["Direito"]}
    assert requirements.read("Venha fazer parte do nosso time!") == {}
