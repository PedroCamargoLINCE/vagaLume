"""Keyword rules that attach labels to each opportunity.

These rules never remove anything. They only *describe* a posting:
which area it is in, when it happens, where it is, and what might be a
problem (warnings). You decide what to apply to.

Every list of keywords lives at the top of this file so you can tweak it
without touching the logic below.
"""

from __future__ import annotations

import re
from datetime import date

from .models import NO_DEADLINE, Opportunity
from .pay import find_pay
from .fields import find_fields
from .requirements import read as read_requirements
from .subareas import find_subareas
from .levels import LEVELS, find_levels
from .places import brazil_states
from .workplace import REMOTE_PLACE, find_workplaces
from .skills import find_skills
from .textutil import find_deadline

# ---------------------------------------------------------------------------
# 1. Is this a student-level posting?
# ---------------------------------------------------------------------------
# A title containing one of these is clearly for students.
STRONG_STUDENT_WORDS = [
    r"intern", r"interns", r"internship", r"internships",
    r"est[áa]gio", r"estagi[áa]ri[oa]s?", r"est[áa]gios",
    r"co-?op", r"student", r"students", r"fellowship", r"fellows?",
    r"residency", r"summer", r"insight", r"explore",
    r"apprentice", r"apprenticeship", r"jovem aprendiz", r"aprendiz", r"aprendizes",
    r"working student", r"werkstudent", r"praktikum",
    r"scholar", r"scholars", r"scholarship", r"bolsa", r"inicia[çc][ãa]o cient[íi]fica",
    r"undergrad", r"undergraduate", r"ugrip", r"isternship",
    # Europe and Latin America: "Stagiaire Data (F/H)", "Alternance", "Praktikant (m/w/d)", "Becario/a",
    # "Pasante", "Practicante", "Prácticas", "Tirocinio", "Master Thesis", "Technical Studentship" (CERN),
    # "12 Month Industrial Placement" (UK).
    r"stagiaires?", r"stagista", r"alternance", r"alternante?s?", r"apprentie?s?",
    r"praktikant(?:in|en)?", r"praktyki", r"becari[oa]s?", r"pasantes?", r"pasant[íi]as?", r"practicantes?",
    r"pr[áa]cticas", r"tirocini[oa]", r"thesis", r"abschlussarbeit", r"masterarbeit", r"bachelorarbeit",
    r"studentships?", r"industrial placement", r"placement year", r"\d+[- ]months? placement",
    # Sweden/Denmark "Examensarbete", "Praktik"; Germany "Industriepraktikum"; Malaysia "Industrial Trainee".
    r"examensarbete", r"praktik", r"\w+praktikum", r"industrial trainee",
    r"acad[êe]mic[oa]s? de",  # "Acadêmico de Enfermagem": a nursing student
]
# "Stage" is a French internship, but also part of a rocket ("Stage Integration Engineer"): it counts
# only as "Stage - ...", "Stage de/en ...", "Stage 2027", "Stage (6 mois)" or next to H/F, F/H.
STAGE = re.compile(r"\bstage\b(?=\s*(?:[-–:|(]|de\b|d['’]|en\b|20\d\d|\d+\s*mois|ing[ée]nieur))|\bstage\b.*\b(?:h/f|f/h|mois)\b"
                   r"|\b(?:h/f|f/h)\b.*\bstage\b", re.I)
# A title containing one of these *might* be for students -> label "unsure".
WEAK_STUDENT_WORDS = [
    r"program", r"programme", r"programa", r"school", r"course", r"curso",
    r"trainee", r"graduate", r"new grad", r"early career", r"early-career",
    r"university", r"campus", r"academy", r"bootcamp", r"resident", r"winter",
]
# Phrases that contain a weak word but are ordinary jobs, not programs.
# ("Technical Program Manager" is a job title, not a student program.)
NOT_A_PROGRAM = [
    r"program manager", r"programme manager", r"program management",
    r"programme management", r"program director", r"program lead",
    r"gerente de programa", r"program coordinator", r"program analyst",
    r"program specialist", r"program officer", r"school psychologist",
    r"graduate recruiter", r"university recruiter", r"campus recruiter", r"dean of students",
    r"member of technical staff",  # AI labs' generic title, not a "staff" (senior) level
]
_NOT_A_PROGRAM = [re.compile(phrase, re.I) for phrase in NOT_A_PROGRAM]
_WORD_RES: dict[tuple[tuple[str, ...], int], re.Pattern[str]] = {}


def _words_re(patterns: list[str], flags: int = re.I) -> re.Pattern[str]:
    """One compiled regex for "any of these words". Compiled once per list: there are
    more word patterns than Python's regex cache holds, so re.search(...) on each
    pattern recompiled them for every role (minutes per run)."""
    key = (tuple(patterns), flags)
    if key not in _WORD_RES:
        _WORD_RES[key] = re.compile("|".join(rf"(?:\b{p}\b)" for p in patterns) or r"(?!)", flags)
    return _WORD_RES[key]


def _any(patterns: list[str], text: str) -> bool:
    return _words_re(patterns).search(text) is not None


# If a title has a seniority word, a *clear* student word must also be there.
SENIOR_WORDS = [r"senior", r"sr\.?", r"staff", r"principal", r"distinguished", r"director", r"head of", r"vp", r"vice president", r"lead"]
CLEAR_STUDENT_WORDS = [r"intern", r"internship", r"student", r"est[áa]gio", r"estagi[áa]ri[oa]", r"co-?op", r"apprentice", r"summer", r"fellowship",
                       r"stagiaires?", r"praktikant(?:in)?", r"werkstudent", r"thesis", r"becari[oa]", r"pasantes?", r"practicantes?"]


def student_level(title: str) -> str:
    """Return "yes", "unsure" or "no" for a job title."""
    cleaned = title
    for phrase in _NOT_A_PROGRAM:
        cleaned = phrase.sub(" ", cleaned)
    if _any(SENIOR_WORDS, cleaned) and not _any(CLEAR_STUDENT_WORDS, cleaned):
        return "no"  # e.g. "Senior Manager, Fellows Program" is a staff job
    if _any(STRONG_STUDENT_WORDS, cleaned) or STAGE.search(cleaned):
        return "yes"
    if _any(WEAK_STUDENT_WORDS, cleaned):
        return "unsure"
    return "no"


# ---------------------------------------------------------------------------
# 2. Area
# ---------------------------------------------------------------------------
# Checked in this order; the first match wins. Quant first because
# "Quantitative Researcher" should be quant, not research.
AREA_RULES: list[tuple[str, list[str]]] = [
    # Not "quant\w*": that is also "quantidade" and "quantitativo" in Portuguese.
    ("quant", [r"quants?", r"quantitative", r"trading", r"trader", r"market making", r"algorithmic trading"]),
    ("ML", [
        r"machine learning", r"ml", r"ai", r"a\.i\.", r"artificial intelligence", r"deep learning",
        r"llms?", r"nlp", r"natural language", r"computer vision", r"reinforcement learning",
        r"generative", r"genai", r"intelig[êe]ncia artificial", r"aprendizado de m[áa]quina",
        r"neural", r"perception", r"robot learning", r"foundation models?", r"alignment",
        r"interpretability", r"mlops", r"applied scientist",
    ]),
    # "Data Scientist" should be data, not research, so check it first.
    ("data", [r"data scien\w*", r"ci[êe]ncia de dados", r"cientista de dados"]),
    ("research", [r"research", r"researcher", r"pesquisa", r"pesquisador\w*", r"scientist", r"phd"]),
    ("data", [
        r"data", r"dados", r"analytics", r"analyst", r"business intelligence", r"bi",
        r"statistic\w*", r"estat[íi]stica", r"analista",
    ]),
    ("hardware", [
        r"hardware", r"asic", r"fpga", r"silicon", r"chip", r"embedded", r"embarcad\w*",
        r"electrical", r"el[ée]tric\w*", r"electronic\w*", r"eletr[ôo]nic\w*", r"rf", r"analog",
        r"firmware", r"verification", r"vlsi", r"automa[çc][ãa]o", r"automation", r"control systems?",
        r"controls", r"robotics", r"rob[óo]tica", r"mechanical", r"mec[âa]nic\w*", r"mechatronics",
        r"plc", r"clp", r"thermal", r"manufacturing", r"produ[çc][ãa]o",
    ]),
    ("SWE", [
        r"software", r"swe", r"developer", r"desenvolvedor\w*", r"desenvolvimento", r"engineer\w*",
        r"engenharia de software", r"backend", r"back-end", r"frontend", r"front-end", r"full[- ]?stack",
        r"devops", r"infrastructure", r"cloud", r"security", r"seguran[çc]a", r"programa[çc][ãa]o",
        r"mobile", r"android", r"ios", r"web", r"sre", r"platform", r"tecnologia", r"ti", r"sistemas",
        r"computer science", r"ci[êe]ncia da computa[çc][ãa]o", r"programador\w*",
    ]),
]


# Words that also mean something outside tech, above all in Portuguese job ads:
# "Analista Financeiro", "Segurança do Trabalho", "Tecnologia em Radiologia",
# "Engenharia de Produção", "desenvolvimento profissional". In a title they only
# count when the role is not clearly for a non-tech field.
GENERIC_AREA_WORDS = [
    r"data", r"dados", r"analytics", r"analyst", r"analista", r"bi", r"statistic\w*", r"estat[íi]stica",
    r"pesquisa", r"pesquisador\w*", r"scientist", r"engineer\w*", r"desenvolvimento",
    r"security", r"seguran[çc]a", r"tecnologia", r"sistemas", r"platform", r"web", r"mobile", r"produ[çc][ãa]o",
    r"automa[çc][ãa]o", r"automation", r"manufacturing", r"mec[âa]nic\w*", r"el[ée]tric\w*", r"ai",
]
# In the description (when the title says nothing), only clear signals count.
DESCRIPTION_AREA_RULES: list[tuple[str, list[str]]] = [
    ("quant", [r"quantitative (?:research|trading|finance|analyst|developer)", r"algorithmic trading", r"market making"]),
    ("ML", [r"machine learning", r"deep learning", r"intelig[êe]ncia artificial", r"aprendizado de m[áa]quina",
            r"computer vision", r"vis[ãa]o computacional", r"nlp", r"llms?", r"pytorch", r"tensorflow"]),
    ("data", [r"data scien\w*", r"ci[êe]ncia de dados", r"cientista de dados", r"an[áa]lise de dados", r"data analy\w*",
              r"engenharia de dados", r"data engineer\w*", r"power bi", r"business intelligence"]),
    ("research", [r"inicia[çc][ãa]o cient[íi]fica", r"research (?:intern|assistant|project|lab)", r"pesquisa cient[íi]fica"]),
    ("hardware", [r"sistemas embarcados", r"embedded (?:systems?|software)", r"firmware", r"fpga", r"vlsi",
                  r"automa[çc][ãa]o industrial", r"rob[óo]tica", r"robotics", r"plc", r"clp"]),
    ("SWE", [r"desenvolvimento de (?:software|sistemas|aplica[çc][õo]es)", r"software engineer\w*", r"desenvolvedor\w*",
             r"programa[çc][ãa]o", r"front[- ]?end", r"back[- ]?end", r"full[- ]?stack", r"devops", r"engenharia de software"]),
]
TECH_FIELDS = {"engenharia", "computacao", "exatas"}


def classify_area(title: str, description: str = "", fields: list[str] | None = None) -> str:
    """Pick one area. The title decides; the description is only a fallback.

    `fields` (radar/fields.py) keeps Portuguese ads honest: a role for law,
    health, business... only gets a tech area when its title says so clearly.
    """
    non_tech = bool(fields) and not set(fields) & TECH_FIELDS
    for area, words in AREA_RULES:
        for word in words:
            if _any([word], title):
                if non_tech and word in GENERIC_AREA_WORDS:
                    break  # "Analista Financeiro": this word doesn't make it a tech role
                return area
    if non_tech:
        return "other"
    text = description[:1500]
    for area, words in DESCRIPTION_AREA_RULES:
        if _any(words, text):
            return area
    return "other"


# ---------------------------------------------------------------------------
# 3. Season (when the opportunity happens)
# ---------------------------------------------------------------------------
SEASON_RULES: list[tuple[str, list[str]]] = [
    # Brazilian summer break. "verão" means the *southern* summer.
    ("Dec–Feb", [
        r"ver[ãa]o", r"est[áa]gio de f[ée]rias", r"f[ée]rias de (?:fim de ano|ver[ãa]o)",
        r"dec(?:ember)?\s*[-–]\s*feb\w*", r"dezembro a fevereiro", r"janeiro a fevereiro",
        r"jan(?:uary)?\s*[-–]\s*feb\w*", r"southern summer",
    ]),
    ("Jul", [r"f[ée]rias de julho", r"mid-year break", r"july break", r"curso de julho"]),
    ("May–Aug", [r"summer", r"may\s*[-–]\s*aug\w*", r"june\s*[-–]\s*aug\w*"]),
    # North American terms: "Winter 2027" (co-op Jan–Apr), "Spring 2027", "Fall 2026".
    # "spring" alone would match "Java Spring", so we require a term word.
    ("Jan–Apr", [r"(?:winter|spring)(?:/\w+)?\s+(?:20\d\d|semester|term|co-?op|internship|intern)"]),
    ("Sep–Dec", [r"(?:fall|autumn)(?:/\w+)?\s+(?:20\d\d|semester|term|co-?op|internship|intern)"]),
    ("year-round", [
        r"co-?op", r"off-?cycle", r"year-round", r"part[- ]time", r"meio per[íi]odo",
        r"(?:3|4|6|12)[- ]month (?:internship|program|placement)",
        r"est[áa]gio", r"estagi[áa]ri[oa]", r"student researcher", r"working student",
    ]),
]


def classify_season(title: str, description: str = "", hints: list[str] | None = None) -> str:
    """Guess the season from the title first, then from hints and the description."""
    for text in (title, " ".join(hints or []), description[:1500]):
        for season, words in SEASON_RULES:
            if _any(words, text):
                return season
    return "unknown"


# ---------------------------------------------------------------------------
# 4. Region (where it is). A posting can be in several regions.
# ---------------------------------------------------------------------------
BRAZIL = [
    r"brazil", r"brasil", r"s[ãa]o paulo", r"rio de janeiro", r"belo horizonte", r"curitiba",
    r"porto alegre", r"florian[óo]polis", r"campinas", r"sorocaba", r"recife", r"bras[íi]lia",
    r"salvador", r"fortaleza", r"manaus", r"goi[âa]nia", r"ribeir[ãa]o preto", r"s[ãa]o carlos",
    r"s[ãa]o jos[ée] dos campos", r"joinville", r"blumenau", r"barueri", r"osasco", r"jundia[íi]",
    r"uberl[âa]ndia", r"londrina", r"santos", r"niter[óo]i", r"distrito federal", r"minas gerais",
    r"santa catarina", r"paran[áa]", r"rio grande do sul", r"pernambuco", r"bahia", r"cear[áa]",
    r"goi[áa]s", r"esp[íi]rito santo", r"amazonas",
    # A location written only as "Remoto" (Portuguese) is almost always a Brazilian job.
    r"remoto",
]
# Two-letter state codes that do not clash with US state codes.
BRAZIL_STATE_CODES = r",\s*(SP|RJ|MG|RS|BA|PE|CE|DF|GO|ES|AM|PB|RN|PI|SE|TO|RO|RR|AP|AC|PR)\b|\bBRA\b"
LATAM = [
    r"MEX", r"ARG", r"CHL", r"COL", r"PER", r"URY", r"CRI",  # ISO country codes (checked case-sensitively below)
    r"(?<!new )mexico", r"m[ée]xico", r"bolivia", r"puerto rico", r"guadalajara", r"monterrey", r"argentina", r"buenos aires", r"chile",
    r"santiago", r"colombia", r"bogot[áa]", r"medell[íi]n", r"per[uú]", r"(?<!nova )(?<!abreu e )lima(?! duarte)", r"uruguay", r"montevideo",
    # districts Gupy sends without a country (Peru, Chile)
    r"surco", r"chincha", r"lurigancho", r"miraflores", r"callao", r"arequipa", r"las condes", r"providencia",
    r"costa rica", r"latam", r"latin america", r"am[ée]rica latina",
    r"quer[ée]taro", r"puebla", r"tijuana", r"guanajuato", r"saltillo", r"chihuahua", r"c[óo]rdoba, argentina",
    r"rosario", r"valpara[íi]so", r"cali", r"barranquilla", r"quito", r"guayaquil", r"la paz", r"asunci[óo]n",
    r"panam[áa]", r"managua", r"nicaragua", r"honduras", r"tegucigalpa", r"el salvador", r"guatemala",
    r"dominican", r"santo domingo", r"san jos[ée], costa rica",
]
US_CANADA = [
    r"usa", r"united states", r"u\.s\.", r"us remote", r"remote in usa", r"canada", r"toronto",
    r"vancouver", r"montr[ée]al", r"waterloo", r"ottawa", r"new york", r"nyc", r"san francisco",
    r"seattle", r"boston", r"chicago", r"austin", r"mountain view", r"palo alto", r"menlo park",
    r"sunnyvale", r"santa clara", r"san jose", r"los angeles", r"pittsburgh", r"atlanta", r"miami",
    r"denver", r"redmond", r"bay area", r"washington,? d\.?c\.?", r"san diego", r"philadelphia",
    r"bellevue", r"princeton", r"north america", r"cambridge, ma", r"california", r"texas",
    r"massachusetts", r"new jersey", r"illinois", r"colorado", r"virginia", r"maryland", r"michigan",
    r"ohio", r"pennsylvania", r"florida", r"oregon", r"utah", r"arizona", r"north carolina",
    r"south carolina", r"minnesota", r"wisconsin", r"missouri", r"tennessee", r"connecticut",
    r"alabama", r"ontario", r"british columbia", r"quebec", r"alberta", r"iowa", r"indiana", r"idaho",
    r"georgia", r"kansas", r"kentucky", r"nevada", r"oklahoma", r"south sf", r"americas",
    r"montr[ée]al", r"vancouver", r"ottawa", r"waterloo", r"calgary", r"edmonton", r"kitchener",
    r"mississauga", r"oakville", r"markham", r"burnaby", r"halifax", r"winnipeg", r"raleigh", r"evendale",
    r"schenectady", r"longmont", r"muskegon", r"bromont", r"brossard",
]
# US state codes + Canadian provinces that are unambiguous...
US_STATE_CODES = (
    r",\s*(AK|AZ|CA|CT|FL|GA|HI|IA|KS|KY|LA|ME|MD|MI|MN|MO|NE|NV|NH|NJ|NM|NY|"
    r"NC|ND|OH|OK|OR|RI|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|ON|BC|QC|AB)\b|\b(USA|CAN|SF|LA|NYC)\b"
)
# ...and codes that could also be a Brazilian state (SC, PA, MT, MS, AL, MA)
# or a country (DE, CO, AR, IN, IL, ID). These only count when no other
# region was recognised by name ("Berlin, DE" stays Europe only).
US_AMBIGUOUS_CODES = r",\s*(SC|PA|MT|MS|AL|MA|DE|CO|AR|IN|IL|ID)\b"
EUROPE = [
    r"uk", r"united kingdom", r"england", r"london", r"edinburgh", r"manchester", r"oxford", r"bristol",
    r"ireland", r"dublin", r"france", r"paris", r"germany", r"deutschland", r"berlin", r"munich", r"regensburg", r"warstein", r"dresden", r"neubiberg",
    r"m[üu]nchen", r"hamburg", r"frankfurt", r"netherlands", r"amsterdam", r"switzerland", r"zurich",
    r"z[üu]rich", r"geneva", r"lausanne", r"austria", r"vienna", r"klosterneuburg", r"spain", r"madrid",
    r"barcelona", r"portugal", r"lisbon", r"porto(?! (?:alegre|velho|nacional|feliz|ferreira|seguro|belo|real))", r"italy", r"milan", r"rome", r"sweden", r"stockholm",
    r"denmark", r"copenhagen", r"norway", r"oslo", r"finland", r"helsinki", r"poland", r"warsaw",
    r"krak[óo]w", r"prague", r"czech\w*", r"belgium", r"brussels", r"ghent", r"luxembourg", r"budapest",
    r"hungary", r"romania", r"bucharest", r"greece", r"athens", r"estonia", r"tallinn", r"europe", r"emea",
    r"cambridge, uk", r"t[üu]bingen", r"lyon", r"grenoble", r"serbia", r"belgrade", r"ukraine", r"kyiv",
    r"slovakia", r"bratislava", r"croatia", r"zagreb", r"bulgaria", r"sofia", r"lithuania", r"vilnius",
    r"latvia", r"riga", r"slovenia", r"ljubljana", r"cyprus", r"malta", r"iceland", r"zaragoza",
    r"GBR", r"DEU", r"FRA", r"NLD", r"CHE", r"AUT", r"ESP", r"PRT", r"ITA", r"SWE", r"DNK", r"NOR",
    r"FIN", r"POL", r"CZE", r"SVK", r"BEL", r"IRL", r"ROU", r"HUN", r"GRC", r"SRB", r"UKR", r"UA",
    # More cities (internships abroad often give just the city) and Turkey.
    r"warszawa", r"wroc[łl]aw", r"gda[ńn]sk", r"pozna[ńn]", r"[łl][óo]d[źz]", r"brno", r"ostrava", r"toulouse",
    r"marseille", r"bordeaux", r"lille", r"nantes", r"rennes", r"strasbourg", r"montpellier", r"belfort",
    r"villeurbanne", r"neuilly-sur-seine", r"aix-les-bains", r"massy", r"v[ée]lizy", r"saint[- ]nazaire",
    r"stuttgart", r"k[öo]ln", r"cologne", r"d[üu]sseldorf", r"dresden", r"leipzig", r"n[üu]rnberg", r"nuremberg",
    r"karlsruhe", r"mannheim", r"bremen", r"hannover", r"jena", r"oberkochen", r"erlangen", r"darmstadt",
    r"eindhoven", r"rotterdam", r"utrecht", r"den haag", r"the hague", r"delft", r"veghel", r"antwerp",
    r"leuven", r"wavre", r"basel", r"bern", r"lugano", r"visp", r"graz", r"linz", r"salzburg", r"villach",
    r"g[öo]teborg", r"gothenburg", r"malm[öo]", r"v[äa]ster[åa]s", r"aarhus", r"odense", r"trondheim",
    r"espoo", r"tampere", r"turin", r"torino", r"bologna", r"florence", r"firenze", r"naples", r"genoa",
    r"seville", r"sevilla", r"bilbao", r"m[áa]laga", r"getafe", r"glasgow", r"belfast", r"leeds",
    r"cardiff", r"galway", r"canary wharf", r"knutsford", r"northampton", r"gloucester",
    r"bucure[șs]ti", r"cluj", r"timi[șs]oara", r"ia[șs]i",
    r"turkey", r"t[üu]rkiye", r"istanbul", r"ankara", r"izmir", r"bursa", r"TUR",
]
ASIA_ME = [  # Asia, Middle East and Oceania
    r"singapore", r"hong kong", r"china", r"shanghai", r"beijing", r"shenzhen", r"taiwan", r"taipei",
    r"hsinchu", r"japan", r"tokyo", r"okinawa", r"korea", r"seoul", r"india", r"bangalore", r"bengaluru",
    r"hyderabad", r"pune", r"mumbai", r"delhi", r"gurgaon", r"gurugram", r"chennai", r"noida", r"israel",
    r"tel aviv", r"haifa", r"dubai", r"abu dhabi", r"uae", r"united arab emirates", r"saudi", r"thuwal",
    r"riyadh", r"qatar", r"doha", r"australia", r"sydney", r"melbourne", r"new zealand", r"vietnam",
    r"philippines", r"manila", r"malaysia", r"kuala lumpur", r"indonesia", r"jakarta", r"thailand",
    r"bangkok", r"apac", r"asia",
    r"SGP", r"JPN", r"KOR", r"CHN", r"HKG", r"TWN", r"IND", r"ISR", r"ARE", r"SAU", r"AUS", r"NZL",
    r"auckland", r"wellington", r"makati", r"taguig", r"cebu", r"suzhou", r"chengdu", r"wuhan", r"guangzhou",
    r"hangzhou", r"nanjing", r"tianjin", r"dalian", r"macau", r"ho chi minh", r"hanoi", r"penang", r"johor",
    r"cyberjaya", r"selangor", r"subang", r"melaka", r"malacca", r"kulim", r"kedah", r"samut prakan", r"chonburi",
    r"wuxi", r"xi'an", r"ahmedabad", r"yokohama", r"osaka", r"kyoto", r"nagoya", r"busan", r"pakistan",
    r"karachi", r"lahore", r"bangladesh", r"dhaka", r"sri lanka", r"cambodia", r"phnom penh", r"uzbekistan",
    r"tashkent", r"kazakhstan", r"almaty", r"amman", r"beirut", r"kuwait", r"bahrain",
    r"muscat",
    # Africa is shown with Asia and the Middle East ("Ásia, África e Oriente Médio").
    r"africa", r"cape town", r"johannesburg", r"ZAF", r"egypt", r"cairo", r"morocco", r"casablanca",
    r"rabat", r"tunisia", r"tunis", r"nigeria", r"lagos", r"kenya", r"nairobi", r"ghana", r"accra",
    r"algeria", r"algiers", r"senegal", r"dakar", r"c[ôo]te d'ivoire", r"abidjan", r"ethiopia",
]


def _mentions(patterns: list[str], text: str) -> bool:
    """Words match case-insensitively; ALL-CAPS codes (GBR, SGP...) only as written."""
    key = tuple(patterns)
    if key not in _MENTION_RES:
        codes = [p for p in patterns if re.fullmatch(r"[A-Z]{2,3}", p)]
        _MENTION_RES[key] = (_words_re([p for p in patterns if p not in codes]), _words_re(codes, 0))
    words, codes = _MENTION_RES[key]
    return bool(words.search(text) or codes.search(text))


_MENTION_RES: dict[tuple[str, ...], tuple[re.Pattern[str], re.Pattern[str]]] = {}


_LATAM_COUNTRIES = (r"\b(?:m[eé]xico|argentina|chile|colombia|per[uú]|uruguay|paraguay|bolivia|ecuador|venezuela"
                    r"|costa rica|panam[aá]|guatemala|MEX|CHL|ARG|COL|PER|CRI)\b")


# ", VA" or ", ON" at the end of a place: a US state or Canadian province (not "NYC" or "SF" inside a sentence).
_US_STATE_AT_END = US_STATE_CODES.split(r"|\b(USA")[0]

# A place that ends with its country ("Madrid, MD, Spain", "Porto Velho, RO, Brazil", "Albuquerque,
# New Mexico, United States") is in that country: its city and "state code" are not read again, so
# "MD" isn't Maryland, "Porto" isn't Portugal and "New Mexico" isn't Mexico.
COUNTRY_REGION: dict[str, str] = {
    **dict.fromkeys(["brazil", "brasil", "bra", "br"], "Brazil"),
    **dict.fromkeys(["united states", "united states of america", "usa", "us", "u.s.", "canada"], "US/Canada"),
    **dict.fromkeys(["mexico", "méxico", "argentina", "chile", "colombia", "peru", "perú", "uruguay", "paraguay", "bolivia",
                     "ecuador", "venezuela", "costa rica", "panama", "panamá", "guatemala", "el salvador", "honduras",
                     "dominican republic", "república dominicana", "nicaragua", "cuba", "puerto rico"], "LatAm"),
    **dict.fromkeys(["united kingdom", "uk", "england", "scotland", "wales", "northern ireland", "ireland", "france", "germany",
                     "deutschland", "spain", "españa", "portugal", "italy", "italia", "netherlands", "the netherlands",
                     "belgium", "switzerland", "austria", "sweden", "norway", "denmark", "finland", "iceland", "poland",
                     "czechia", "czech republic", "slovakia", "hungary", "romania", "bulgaria", "greece", "croatia",
                     "slovenia", "serbia", "estonia", "latvia", "lithuania", "luxembourg", "malta", "cyprus", "monaco",
                     "ukraine", "bosnia and herzegovina", "north macedonia", "albania", "montenegro", "moldova",
                     "türkiye", "turkey"], "Europe"),
    **dict.fromkeys(["china", "india", "japan", "south korea", "korea", "singapore", "hong kong", "taiwan", "malaysia",
                     "thailand", "vietnam", "indonesia", "philippines", "australia", "new zealand", "israel",
                     "united arab emirates", "uae", "saudi arabia", "qatar", "kuwait", "bahrain", "oman", "jordan",
                     "egypt", "morocco", "south africa", "nigeria", "kenya", "ghana", "tunisia", "algeria", "senegal",
                     "benin", "pakistan", "bangladesh", "sri lanka", "myanmar", "cambodia", "kazakhstan", "armenia",
                     "georgia (country)", "lebanon"], "Asia/ME"),
}
# "US-IA-CEDAR RAPIDS-182", "CA-QC-LONGUEUIL", "PL-18-RZESZOW", "USA - New York - Malta": the country comes first.
_LEADING_CODE = re.compile(r"^\s*(USA?|CA|MX|BR|BRA|PL|DE|FR|GB|UK|IN|CN|JP|SG|IT|ES|NL|CH|SE|IE|IL)\s*[-–,]")
_CODE_REGION = {"US": "US/Canada", "USA": "US/Canada", "CA": "US/Canada", "MX": "LatAm", "BR": "Brazil", "BRA": "Brazil",
                "IN": "Asia/ME", "CN": "Asia/ME", "JP": "Asia/ME", "SG": "Asia/ME", "IL": "Asia/ME"}


def _named_country(part: str) -> str:
    """The region of the country a place names at its end (or starts with as a code); "" if none."""
    clean = re.sub(r"\((?:remote|hybrid|on-site|remoto|h[íi]brido|presencial)\)", "", part, flags=re.I).strip(" ,.-")
    segments = [x.strip().lower() for x in clean.split(",")]
    last = segments[-1]
    # "London, Montreal, Hong Kong, New York, Singapore" is a list of cities, not a place in Singapore.
    middle = segments[1:-1]
    if len(segments) > 3 and not all(len(x) <= 3 or x == last for x in middle):
        return ""
    if len(segments) == 3 and last in COUNTRY_REGION and middle[0] and len(middle[0]) > 3:
        # "London, Montreal, Singapore" (the first is already somewhere else) vs "Ilhéus, Bahia, Brazil".
        first_regions = [r for r in _regions_by_words(segments[0]) if r != "remote"]
        if first_regions and COUNTRY_REGION[last] not in first_regions:
            return ""
    if last in COUNTRY_REGION:
        return COUNTRY_REGION[last]
    first = clean.split(",", 1)[0].strip().lower()  # "Costa Rica, San Jose" (not "Lebanon, PA": a US town)
    if "," in clean and first in COUNTRY_REGION and len(first) > 3 and not re.fullmatch(r"[A-Z]{2}", clean.rsplit(",", 1)[-1].strip()):
        return COUNTRY_REGION[first]
    match = _LEADING_CODE.match(clean)
    if match:
        return _CODE_REGION.get(match.group(1).upper(), "Europe")
    return ""


def classify_regions(location: str, remote: bool = False) -> list[str]:
    """Return every region that the location string mentions."""
    regions: list[str] = []
    rest: list[str] = []
    for part in re.split(r"\s/\s|;|\|", location):
        country = _named_country(part)
        if country:
            regions.append(country)
        elif part.strip():
            rest.append(part)
    for part in rest:
        regions += [r for r in _regions_by_words(part) if r not in regions]
    if remote or REMOTE_PLACE.search(location) or re.search(r"\banywhere\b|\bworldwide\b|home[- ]based", location, re.I):
        if re.search(r"(?i:remote)[^/;]*\b(?:US|USA)\b|\b(?:US|USA)\b[^/;]*(?i:remote)", location) and "US/Canada" not in regions:
            regions.append("US/Canada")  # "Remote (US)", "Remote, US"
        regions.append("remote")
    ordered = [r for r in ("Brazil", "LatAm", "US/Canada", "Europe", "Asia/ME", "remote") if r in regions]
    return ordered or ["unknown"]


def _regions_by_words(location: str) -> list[str]:
    """Regions from city names and state codes, for places that don't name their country."""
    regions: list[str] = []
    checks = [
        ("Brazil", BRAZIL, BRAZIL_STATE_CODES),
        ("LatAm", LATAM, None),
        ("US/Canada", US_CANADA, US_STATE_CODES),
        ("Europe", EUROPE, None),
        ("Asia/ME", ASIA_ME, None),
    ]
    for name, words, codes in checks:
        if _mentions(words, location) or (codes is not None and re.search(codes, location)):
            regions.append(name)
    # "Santiago, Rio Grande do Sul, Brazil" is not Chile: a Brazilian place is only also
    # Latin America when another country is named ("São Paulo / Mexico City").
    if "Brazil" in regions and "LatAm" in regions and not re.search(_LATAM_COUNTRIES, location, re.I):
        regions.remove("LatAm")
    # "Boise, ID" -> US, but "Berlin, DE" was already recognised as Europe.
    if not regions and re.search(US_AMBIGUOUS_CODES, location):
        regions.append("US/Canada")
    # "Vienna, VA", "Melbourne, FL", "London, Ontario": a US state (or Canadian province) at the end
    # says the country; the city's European or Australian namesake doesn't count.
    us_end = re.search(rf"{_US_STATE_AT_END}\s*(?:\(|$)", location.strip()) or location.count(",") == 1 and re.search(
        r",\s*(?:ontario|quebec|british columbia|alberta|wisconsin|massachusetts|pennsylvania|illinois|indiana|colorado|"
        r"virginia|georgia|ohio|michigan|minnesota|texas|california|washington|oregon|arizona|florida|new york|new jersey|"
        r"north carolina|south carolina|tennessee|kentucky|missouri|maryland|connecticut|utah|alabama|iowa|kansas|"
        r"nebraska|nevada|new mexico|louisiana|oklahoma|arkansas|mississippi|idaho|montana|delaware|maine)\s*$", location.strip(), re.I)
    if "US/Canada" in regions and us_end and "Brazil" not in regions:
        regions = ["US/Canada"]
    return regions


# ---------------------------------------------------------------------------
# 5. Warnings
# ---------------------------------------------------------------------------
W_US_AUTH = "US work auth?"
W_PHD = "PhD-level?"
W_GRAD_YEAR = "grad-year limit?"
W_UNSURE = "unsure if student role"
W_NEW_GRAD = "new-grad role (after graduation)"

# Only the US asks for these.
US_AUTH_TEXT = [r"u\.?s\.? citizen\w*", r"security clearance", r"green card", r"itar"]
# Any country can ask for these ("must hold valid work authorization ... for their specific work
# location" on a Google role in Europe): they only count for roles in the US/Canada, remote or unknown.
WORK_AUTH_TEXT = [r"work authori[sz]ation", r"authori[sz]ed to work", r"visa sponsorship", r"sponsorship", r"permanent resident",
                  r"export control"]  # Europe has export control too (German aerospace roles mention it)
PHD_TITLE = [r"ph\.?d", r"doctoral", r"doutorado", r"ms/phd", r"m\.s\./ph\.d", r"🎓"]
PHD_TEXT = [
    r"pursuing a ph\.?d", r"ph\.?d\.? (?:student|candidate|program)", r"enrolled in a ph\.?d",
    r"doctoral (?:student|candidate|program)", r"doutorando", r"advanced degree required",
]
NEW_GRAD_TITLE = [
    r"new grad\w*", r"new college grad\w*", r"recent grad\w*", r"university grad\w*",
    r"early career", r"early-career", r"graduate (?:engineer|program|programme|scheme|analyst)",
]
GRAD_YEAR_TEXT = [
    r"class of 20\d\d", r"graduat\w*[^.\n]{0,50}\b20\d\d\b", r"\b20\d\d graduates?",
    r"penultimate[- ]year", r"final[- ]year", r"previs[ãa]o de (?:formatura|conclus[ãa]o)",
    r"formatura (?:entre|em|at[ée])", r"conclus[ãa]o (?:do curso )?(?:entre|em|at[ée])",
    r"expected graduation", r"graduation date",
]


def find_warnings(opp: Opportunity, level: str, regions: list[str]) -> list[str]:
    """Collect warnings. They are hints with a '?', not verdicts."""
    text = f"{opp.title}\n{opp.description}"
    hints = set(opp.hints)
    warnings: list[str] = []
    elsewhere = any(r not in ("US/Canada", "remote", "unknown") for r in regions)  # a known place outside the US
    if ("US/Canada" in regions or _any(US_AUTH_TEXT, text) or (not elsewhere and _any(WORK_AUTH_TEXT, text))
            or hints & {"no-sponsorship", "us-citizen"}):
        warnings.append(W_US_AUTH)
    if _any(PHD_TITLE, opp.title) or _any(PHD_TEXT, opp.description) or "advanced-degree" in hints:
        warnings.append(W_PHD)
    if _any(GRAD_YEAR_TEXT, text):
        warnings.append(W_GRAD_YEAR)
    if "new-grad" in hints or (level != "yes" and _any(NEW_GRAD_TITLE, opp.title)):
        warnings.append(W_NEW_GRAD)  # not a student role, but kept: useful in a student's last year
    elif level != "yes":
        warnings.append(W_UNSURE)
    return warnings


# ---------------------------------------------------------------------------
# 6. Calendar note: does it clash with the usual Brazilian semesters (Mar–Jul, Aug–Dec)?
# ---------------------------------------------------------------------------
CALENDAR_NOTES = {
    "Dec–Feb": "fits the Brazilian summer break (Dec–Feb)",
    "Jul": "fits the July break",
    "Jan–Apr": "Jan–Feb fits the summer break, Mar–Apr clashes with the first semester",
    "Sep–Dec": "clashes with the second semester (Aug–Dec)",
    "May–Aug": "overlaps semesters: May–Jul clashes with Mar–Jul and Aug with Aug–Dec; needs a leave or remote deal",
    "year-round": "runs during semesters (Mar–Jul, Aug–Dec); OK only if part-time/remote or you take a semester off",
    "unknown": "dates unknown; compare with your semesters (usually Mar–Jul, Aug–Dec)",
}


# Fields implied by a tech area, for roles that name no field.
AREA_FIELDS = {
    "ML": ["engenharia", "computacao", "exatas"], "SWE": ["engenharia", "computacao"], "data": ["computacao", "exatas", "negocios", "engenharia"],
    "hardware": ["engenharia", "computacao"], "quant": ["exatas", "negocios", "computacao"],
}


# When a term ends: "Winter 2026" (co-op Jan–Apr) is over in May 2026.
_TERM = re.compile(r"\b(winter|spring|summer|fall|autumn)(?:/\w+)?\s*['’]?((?:20)?\d\d)\b", re.I)
_TERM_END = {"winter": 4, "spring": 5, "summer": 9, "fall": 12, "autumn": 12}


def past_term(title: str, today: date) -> bool:
    """Is the role for a term that is already over ("Winter 2026", "Summer '25", "Internship 2025")?"""
    terms = [(m.group(1).lower(), int(m.group(2)) % 100 + 2000) for m in _TERM.finditer(title)]
    if terms:
        return all((year, _TERM_END[name]) < (today.year, today.month) for name, year in terms)
    years = [int(y) for y in re.findall(r"\b(20\d\d)\b", title)]
    return bool(years) and max(years) < today.year


def calendar_note(season: str) -> str:
    return CALENDAR_NOTES.get(season, CALENDAR_NOTES["unknown"])


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------
def level_for(opp: Opportunity) -> str:
    """Student level, taking the source's hints into account."""
    if "student" in opp.hints or "new-grad" in opp.hints:
        return "yes"  # the source itself says it is a student role (or a curated list)
    level = student_level(opp.title)
    if "unsure-student" in opp.hints:
        return "yes" if level == "yes" else "unsure"  # "Estágio em Administração" says so itself
    return level


def apply_rules(opp: Opportunity) -> Opportunity:
    """Fill in area, season, regions, workplaces, warnings, calendar note, deadline, pay, skills, fields, levels and states."""
    level = level_for(opp)
    preset = opp.preset
    opp.regions = list(preset.get("regions") or classify_regions(opp.location, opp.remote))  # type: ignore[arg-type]
    opp.workplaces = find_workplaces(opp.location, opp.remote, opp.description)
    if "remote" in opp.regions and opp.workplaces and "remote" not in opp.workplaces and not preset.get("regions"):
        # Marked remote, but the description says hybrid or on-site: it is not a remote role.
        opp.regions = [r for r in opp.regions if r != "remote"] or ["unknown"]
        # ...and the "(remote)" our sources add to the location says so too.
        opp.location = re.sub(r"\((?:remote|hybrid|on-site)\)$", f"({opp.workplaces[0]})", opp.location)
    opp.fields = find_fields(opp.title, opp.description)
    opp.subs = find_subareas(opp.title)
    opp.area = str(preset.get("area") or classify_area(opp.title, opp.description, opp.fields))
    # Sources can suggest an area ("area:quant") used when the rules find nothing.
    suggested = [hint.split(":", 1)[1] for hint in opp.hints if hint.startswith("area:")]
    # ...but not on a role for a non-tech field ("Finance Intern" under a list's "Data Science & ML" heading).
    if opp.area == "other" and suggested and (not opp.fields or set(opp.fields) & TECH_FIELDS):
        opp.area = suggested[0]
    # A role that names no field but has a tech area ("Applied Scientist Intern" is ML) is for
    # the fields of that area: otherwise it would show for every student, law and nursing too.
    if not opp.fields:
        opp.fields = list(AREA_FIELDS.get(opp.area, []))
    opp.season = str(preset.get("season") or classify_season(opp.title, opp.description, opp.hints))
    if not preset.get("season") and southern_summer(opp):
        opp.season = "Dec–Feb"  # "Summer Job" in São Paulo is the Brazilian summer, December to February
    elif not preset.get("season") and northern_verao(opp):
        opp.season = "May–Aug"  # "Estágio de Verão" in Portugal or Mexico is the northern summer
    opp.warnings = find_warnings(opp, level, opp.regions)
    for extra in preset.get("warnings") or []:  # type: ignore[union-attr]
        if extra not in opp.warnings:
            opp.warnings.append(str(extra))
    opp.calendar_note = calendar_note(opp.season)
    if opp.deadline == NO_DEADLINE or not opp.deadline:
        opp.deadline = find_deadline(opp.description) or NO_DEADLINE
    if opp.pay:
        opp.pay_from = opp.pay_from or "field"
    else:
        opp.pay = find_pay(opp.description)
        opp.pay_from = "text" if opp.pay else ""
    opp.skills = find_skills(f"{opp.title}\n{opp.description}")
    preset_levels = [level for level in LEVELS if level in (preset.get("levels") or [])]  # type: ignore[operator]
    opp.levels = preset_levels or find_levels(opp.title, opp.description)
    opp.states = brazil_states(opp.location) if "Brazil" in opp.regions else []
    opp.requirements = read_requirements(opp.description)
    opp.labeled_by = "rules"
    return opp


# The southern summer: a "summer" role in Brazil or the Southern Cone runs December to February,
# unless it names northern-summer months ("Summer 2027 (June–August)").
_SOUTHERN_PLACE = re.compile(r"\b(?:argentina|buenos aires|chile|santiago de chile|uruguay|montevideo|paraguay|asunci[óo]n)\b", re.I)
_NORTHERN_MONTHS = re.compile(r"\b(?:may|june|july|august|maio|junho|julho|agosto|mayo|junio|julio)\b", re.I)


def southern_summer(opp: Opportunity) -> bool:
    if opp.season != "May–Aug" or not re.search(r"\bsummer\b|\bver[ãa]o\b|\bverano\b", opp.title, re.I):
        return False
    southern = "Brazil" in opp.regions or bool(_SOUTHERN_PLACE.search(opp.location))
    northern = any(r in opp.regions for r in ("US/Canada", "Europe", "Asia/ME"))
    return southern and not northern and not _NORTHERN_MONTHS.search(opp.title)


def northern_verao(opp: Opportunity) -> bool:
    """ "Verão"/"verano" read as December–February, but the place is in the north (Portugal, Spain, Mexico)."""
    if opp.season != "Dec–Feb" or not re.search(r"\bver[ãa]o\b|\bverano\b", opp.title, re.I):
        return False
    if "Brazil" in opp.regions or _SOUTHERN_PLACE.search(opp.location):
        return False
    return any(r in opp.regions for r in ("Europe", "US/Canada", "Asia/ME")) or bool(re.search(r"m[ée]xico", opp.location, re.I))


def is_student_candidate(title: str) -> bool:
    """Used by sources that list *all* jobs: keep anything that might be for students."""
    return student_level(title) != "no"
