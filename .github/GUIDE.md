# vagaLume: the full guide

This is the detailed manual: how every source works, what each label means,
how to add companies and programs, and how to run your own copy. For the short
tour, see the [README](../README.md) (in Portuguese; [English version](README.en.md)). The website is at
**https://pedrocamargolince.github.io/vagaLume/**.

vagaLume is a small Python bot that runs every day on GitHub Actions and collects **student
opportunities**: internships (summer and regular, Brazil and abroad), estágio,
research internships, fellowships, summer schools, and student programs at big
tech companies, AI labs and trading firms.

**The core rule: show everything, never decide for the student.** Every student-level
posting found is kept. Nothing is dropped for eligibility, area or fit. Instead,
each posting gets **labels** (area, season, region) and **warnings** (such as
"US work auth?" or "PhD-level?"). When it is unclear whether a posting is for
students, it is still shown, with the warning `unsure if student role`.

Every day it updates:

- **The website** (`docs/`, served by GitHub Pages): one plain page with a
  search box, tabs (Today's highlights, All, New, Closing soon, Saved, Programs
  & schools, Applied, Hidden), filters and a table. See [The website](#the-website).
- `docs/feed-brasil.xml` and `docs/feed.xml`: the new roles of the day as
  feeds, and the Telegram highlights (see below).
- `data/opportunities.jsonl` and `data/page_hashes.jsonl`: the database as
  text, one posting per line, with every posting ever seen and its status
  (see [Statuses](#statuses-for-every-device)). Each run rebuilds a working SQLite file (`data/radar.db`, not
  committed) from them and writes them back at the end.

---

## Sources

Each source is one module in `radar/sources/`. They all return the same record
(`radar/models.py`). If one source fails, the run goes on, and the failure shows
up in the **Source health** table at the top of the report.

Roughly how many roles each source gives on a normal day, after removing
duplicates (the date says when it was counted; the site's Sources table has
today's numbers):

| Source | Module | How | Items |
|---|---|---|---|
| Greenhouse boards (127 companies, incl. Hudson River Trading, AB InBev, Mirakl, Trade Republic, Isar Aerospace) | `greenhouse.py` | public JSON API | 810 |
| Lever boards (29 companies; `eu: true` for boards in Lever's EU region) | `lever.py` | public JSON API | 107 |
| Ashby boards (63 companies, incl. Doctolib, Back Market, Enpal) | `ashby.py` | public JSON API | 98 |
| GitHub lists (SimplifyJobs Summer 2027, Off-Season, New Grad; vanshb03 Summer 2027; Tech Internships Europe; Canadian Tech Internships 2027) | `github_lists.py` | parses README tables (HTML and Markdown) | 3,898 + ~740 Europe/Canada (Oct 15) |
| Gupy (estágio, estágio de férias and trainee in Brazil) | `gupy.py` | the portal's JSON search API, filtered by job type, 100 per page; also "estágio"/"estagiário" titles that companies file as talent pools or regular jobs (Itaú's estágio program is one) | 3,226 (Oct 15) |
| Program pages (93<!--n:programs--> pages, 40<!--n:programs_brazil--> of them Brazilian) | `programs.py` | page-change watcher | 93<!--n:programs--> |
| Google Careers | `google.py` | reads the job data embedded in the results page | 90 |
| Amazon Jobs | `amazon.py` | JSON endpoint behind amazon.jobs search | 431 |
| NVIDIA (Workday) | `nvidia.py` | Workday JSON endpoint, "Intern" filter | 40 |
| Microsoft | `microsoft.py` | JSON endpoint behind its search page | 82 |
| D. E. Shaw | `nextjs_sites.py` | reads the JSON embedded in the page (Next.js) | 14 |
| DRW | `nextjs_sites.py` | reads the JSON embedded in the page (Next.js) | 27 |
| Meta | `meta.py` | **headless browser** (Playwright): opens the internship search and catches the job list the page downloads | 11 |
| **Brazil:** CIEE (graduação estágio) | `ciee.py` | the public JSON API behind portal.ciee.org.br, 1,000 per page | 2,223 |
| **Brazil:** Super Estágios (Superior level) | `superestagios.py` | one form POST that returns every active vacancy | 4,723 |
| **Brazil:** Sólides Vagas (estágio, last 60 days) | `solides.py` | the JSON route behind the search page, 20 per page | 972 |
| **Brazil:** IEL (estágio from the industry federations, last 60 days) | `iel.py` | public Liferay API | 826 |
| **Brazil:** Cia de Talentos (open estágio and trainee programs) | `ciadetalentos.py` | the public request the vacancy site makes before login | 10 |
| **Brazil:** FAPESP Oportunidades (IC, master's and doctoral grants) | `fapesp.py` | parses the static list page | 28 |
| SmartRecruiters (Bosch, Aumovio and Continental worldwide; Syngenta, Louis Dreyfus, Serasa in Brazil; Delivery Hero, Ubisoft, AUTO1, Eurofins, SGS, SIXT, CERN… abroad) | `smartrecruiters.py` | public API; `country` per company ("" = every country) | 92 in Brazil + abroad |
| Workday abroad (`workday_global`: Airbus, Thales, PwC campus, Visa, TRUMPF, Sanofi, ABB, GE Vernova, ZEISS, NXP, Chanel, RTX, Stryker, MSD, Saab, Cisco and 75 more) | `workday.py` | only the student job types (intern, working student, apprentice, thesis), country by country, 8 sites at a time | ~730 at Airbus alone (Oct 15) |
| **Brazil:** Workday (Santander, P&G, Citi, Mondelēz, Accenture, GE HealthCare, Toyota and 16 more) | `workday.py` | Workday JSON endpoint with the Brazil and intern/apprentice filters; sites with only a city filter are searched in their Brazilian cities | 70 + ~40 (Oct 15) |
| **Brazil:** Eureca (estágio programs of Aché, Serasa Experian, AkzoNobel, Motiva, Ardagh…) | `eureca.py` | the public JSON request its job site makes | 74 (Oct 15) |
| **Brazil:** Abler (Vale's estágio board) | `abler.py` | public JSON route of each company board | 47 (Oct 15) |
| **Brazil:** Oracle Recruiting Cloud (ArcelorMittal, PicPay) | `oracle_hcm.py` | public career-site search API | 17 (Oct 15) |
| **Brazil:** RSS job feeds (Klabin, Nestlé, Siemens, TotalEnergies) | `rss_jobs.py` | SuccessFactors and Avature feeds | 28 (Oct 15) |
| **Brazil:** InHire boards (KPMG, Deloitte, Sympla, Peers, Riachuelo, Contabilizei, Cielo, XP) | `inhire.py` | the public API behind `<tenant>.inhire.app`, one request per role page | 38 (Oct 16) |
| **Brazil:** Academia do Universitário (Braskem, Volkswagen, ONS, Vibra, RD Saúde, Ipiranga… programs) | `academia.py` | the public API of its job site; one item per program | 22 (Oct 16) |
| **Brazil:** TOTVS (its own "Atração de Talentos" board) | `totvs_rh.py` | reads the roles listed in the board's page | 1 (Oct 16) |
| BCG (Brazil), Goldman Sachs and IBM (Brazil and abroad) | `company_sites.py` | BCG's Phenom widget API, Goldman's GraphQL campus search, IBM's careers search API | 3 + 145 + 274 (Oct 16) |
| Eightfold sites (Infineon worldwide; Mercado Livre, Morgan Stanley in Brazil) | `eightfold.py` | the public `/api/pcsx/search` of each site | ~230 (Oct 16) |
| Shopee (Brazil, Singapore) | `shopee.py` | the public API of its careers site, internship type | 165 (Oct 16) |
| SuccessFactors sites, every country (SAP, Volvo Group, Volvo Cars) | `successfactors.py` | one RSS request per site with every job; places parsed from the titles | 319 (Oct 16) |
| **Brazil:** CIEE editais (public-sector estágio selections: courts, BNDES, FINEP, Fiocruz, SEFAZ-SP, Prefeitura de São Paulo…) | `ciee_editais.py` | the public API behind pp.ciee.org.br; one item per edital, with its deadline | 42 (Oct 21) |
| **Brazil:** Central de Estágios do Paraná (state government estágios) | `parana.py` | the public vacancy search and each vacancy's page | 204 (Oct 21) |
| **Brazil:** Fundação Mudes (Rio de Janeiro and Espírito Santo) | `mudes.py` | the public vacancy list and each vacancy's page | 72 (Oct 21) |
| **Brazil:** Recrutei (estágios of the companies on the platform) | `recrutei.py` | the public estágio board, with each role's details from the platform's API | 130 (Oct 21) |
| **Brazil:** Quickin boards (145 companies and recruiters) | `quickin.py` | the public API of each board | 389 (Oct 21) |
| **Brazil:** USP estágio murals (FFLCH) | `usp_estagios.py` | the mural's public list and each role's page | 19 (Oct 21) |
| Remote job boards (Himalayas, Remotive, Jobicy, Remote OK, Working Nomads): internships open to people in Brazil | `remote_boards.py` | each board's public API; only roles open worldwide, to Latin America or to Brazil, credited and linked to the board | 80 + 1 (Oct 21) |

Total: about **31,000<!--n:open--> open roles** a day from 45<!--n:sources--> sources, most of them in Brazil, Europe and the US.

**New companies, found every day** (`radar/discover.py`). Many companies, Brazilian startups
among them, post their jobs on Ashby, Greenhouse or Lever, which vagaLume reads; it only needs to
know the company's board. Before each run, vagaLume reads the list of boards that
[Common Crawl](https://commoncrawl.org/) (a free, public archive of the web) saw in its last six
crawls, about 12,000 of them, asks the new ones and the ones not asked for a while what jobs they
have, and keeps the boards with a job in Brazil in `config/discovered.yaml`. Their student roles
then show up like any other company's. A board with no job in Brazil any more, or gone, leaves the
list. To keep a company for good, add it to `config/companies.yaml`; to leave one out, add its slug
under `ignored_boards` there (`ignored_boards: {ashby: [some-slug]}`).

**Scraping without a public API.** Most sites that have no official API still
load their jobs from somewhere: a JSON endpoint that the search page calls
(Microsoft, Amazon, Gupy, CIEE, Sólides), or JSON embedded in the HTML (Google,
D. E. Shaw, DRW). The bot reads those directly with plain HTTP, which is fast and simple.
Only Meta answers plain requests with an empty page, so `meta.py` opens it
in a headless Chromium (`radar/browser.py`) and reads the job list the page
fetches for itself. Program pages that are built by JavaScript can use the
same browser: add `render: true` in `programs.yaml`. A plain page that
times out or answers 403/429 is also tried once in the browser: some sites
behind Cloudflare (Embraer's) don't answer plain requests from GitHub's
servers but do answer a real browser.

### Limits you should know about

- **Gupy, CIEE, Sólides, Super Estágios, IEL and Cia de Talentos** are read
  through the same JSON requests their own websites make. They are not
  official APIs, so a redesign can break one; it then shows as failed in the
  Sources table and the others keep working.
- **CIEE and Super Estágios vacancies have no job title.** vagaLume writes one
  from the professional area or the accepted courses ("Estágio em
  Informática"), and Super Estágios hides the company of about a third of its
  vacancies ("Empresa confidencial").
- **Sólides and IEL** keep old postings online, so only the last 60 days are
  read.
- **Google, Meta, Microsoft, D. E. Shaw, DRW** are scraped from their own
  websites. If one of them redesigns its site, that source will show as failed
  in the Sources table (the other sources keep working) and its parser needs a
  small update.
- **Microsoft** sometimes answers "429 Too Many Requests". The bot then waits
  15 s and 45 s before retrying, as the site asks.
- **Sites behind Cloudflare's bot check** (Citadel, MBZUAI, OpenAI Residency)
  stop even a full headless browser at a "security verification" page. Getting
  past it would mean disguising the browser or solving the challenge, which is
  defeating their anti-bot protection, so the radar doesn't do it. Where
  possible it reads the same postings from another source instead (see below).
- **New-grad roles** (full-time jobs for after graduation, from the
  SimplifyJobs new-grad list) are shown too, for students in their last year.
  They carry the warning `new-grad role (after graduation)`, are marked
  "check something" unless your résumé says you graduate within a year, and
  never appear in Today's highlights.
- Postings that a source stops listing are marked closed. If a source is only
  partly healthy, closing waits until a posting hasn't been seen for 30 days.
- No LinkedIn scraping, by design.

### Check these by hand

| Site | What the radar still sees | Link |
|---|---|---|
| Citadel / Citadel Securities | their internships and new-grad roles from the SimplifyJobs lists | https://www.citadel.com/careers/students/ |
| MBZUAI UGRIP | nothing | https://mbzuai.ac.ae/ugrip/ |
| OpenAI Residency | residency roles when OpenAI posts them on its Ashby board (already read daily) | https://openai.com/residency/ |

Hudson River Trading's website also blocks bots, but its jobs are on
Greenhouse (board `wehrtyou`), so they are read from the public API like any
other company.

### Companies not on Greenhouse, Lever or Ashby

They stay commented out in `config/companies.yaml`:

- **Trading:** Two Sigma and SIG (watched as program pages), G-Research,
  Radix, Headlands. D. E. Shaw and DRW have their own scrapers.
- **AI:** Google DeepMind (covered by the Google source and the Student
  Researcher page), Mistral AI, Hugging Face (uses Workable, which isn't
  supported).
- **Brazil:** iFood, Mercado Livre, PicPay, Creditas, Hotmart, Olist, TOTVS,
  Loggi. Most Brazilian companies hire interns through Gupy, which the Gupy
  source reads in full (every internship, summer and trainee posting).
  CloudWalk and Tractian are real Lever boards that were empty in October 2026.

### Brazilian job sites we don't read, and why

Checked in October 2026. vagaLume only reads sites that allow it and never
gets around a block.

| Site | Why not |
|---|---|
| Catho | answers bots with HTTP 403 |
| Indeed, Glassdoor | Cloudflare bot check |
| InfoJobs | its terms forbid robots and crawlers |
| Vagas.com.br | robots.txt allows it, but its terms forbid copying content without authorization (asking them is an option) |
| Nube | the vacancy search needs a login (many Nube vacancies are also on Gupy) |
| Companhia de Estágios | the vacancy board needs a login; its open programs page is watched in `programs.yaml` |
| estagiarios.com | Cloudflare block |
| Coodesh | its API's robots.txt disallows all bots |
| Remotar, Trampos.co | their terms forbid copying by robots or crawlers |
| 99jobs | its terms forbid copying or duplicating content |
| Empregos.com.br, BNE | they answer bots with "Acesso Bloqueado" (HTTP 403) |
| Pandapé (InfoJobs) | its terms forbid reproducing content and using robots |
| GeekHunter | robots.txt disallows the job pages |
| Universia | Incapsula block |
| LinkedIn | never |

---

## Labels

Labels come from keyword rules in `radar/labels.py`. All the keyword lists are
at the top of that file.

| Label | Values |
|---|---|
| area | `ML`, `SWE`, `research`, `data`, `quant`, `hardware`, `other`. The title decides. When it says nothing, only clear phrases in the description count ("machine learning", "ciência de dados", "desenvolvimento de software"), not words that are everywhere in Portuguese ads ("sistemas", "tecnologia", "dados", "desenvolvimento profissional"). A role for a non-tech field (law, health, business…) only gets a tech area when its title says so clearly: "Analista Financeiro" is not `data`. |
| season | `Dec–Feb` (Brazilian summer break), `Jan–Apr` (a northern "Winter"/"Spring" term), `Jul` (July break), `May–Aug` (northern summer), `Sep–Dec` ("Fall" term), `year-round`, `unknown` |
| level | `undergrad`, `masters`, `phd` (`radar/levels.py`), and `school` for estágios of high-school or technical courses ("Estágio Nível Médio", "Técnico de Enfermagem") and apprenticeships: no profile picks it, so they are hidden like any role for another level |
| fields | the areas a role is for (`radar/fields.py`); a role that names none but has a tech area gets that area's fields ("Applied Scientist Intern" is ML: engineering, computing, sciences), so it isn't shown to law or health students |
| region | `Brazil`, `LatAm`, `US/Canada`, `Europe`, `Asia/ME` (includes Oceania), `remote`, `unknown`. A posting can have several. |
| warnings | `US work auth?`, `PhD-level?`, `grad-year limit?`, `unsure if student role`, `new-grad role (after graduation)`. `US work auth?` is for roles in the US/Canada, wording only the US uses (US citizen, green card, security clearance, ITAR), or "work authorization"/"sponsorship" on a remote role or one whose place is unknown. A role in Europe that asks for local work authorization doesn't get it. |
| calendar note | whether it fits the usual Brazilian breaks or clashes with the semesters (Mar–Jul, Aug–Dec) |
| deadline | a date when the source or the text states one, otherwise `check page`. A role past its deadline leaves the lists (Saved and Applied still show it); a program page's past date is last year's edition and isn't shown |
| pay | when stated: the job board's own salary field (Ashby, Lever, Greenhouse, Sólides, CIEE, Super Estágios), otherwise read from the description by `radar/pay.py` (formats like `$54 — $60 USD`, `109,395.00 USD Annually`, `Bolsa auxílio: R$1.357,28/mês`). See **How pay is read** below. |
| skills | the skills a posting mentions, from a fixed list of about 125 in `radar/skills.py` (Python, SQL, PLC, MATLAB, Tax law, Patient care, Financial analysis, Figma…), in English and Portuguese. Used by the résumé match on the site. |

**What the site leaves out or merges.**

- Roles for a term that is already over ("Winter 2026", "Summer '25",
  "Estágio 2025").
- Roles whose own page says they are gone: list roles are re-read every week,
  and a job page that answers "not found" closes the role.
- Workday sites only for a company's own staff (Boeing's "External_Subsidiary").
- The same job twice: a GitHub list and the company's board, or two addresses of
  one job, show once.
- The same title at the same company in several places becomes one row with
  every place; the opened row links to the posting for each place ("A mesma
  vaga em outros lugares").
- A program whose page says this year's applications are closed stays in
  Programs & schools, marked **Inscrições encerradas** and listed last, and
  leaves the other tabs.

### How pay is read

**Job pages.** Many sources list only a title and a place (Workday,
SmartRecruiters, Microsoft, NVIDIA, IEL, the GitHub lists). For their roles,
`radar/details.py` reads the job's own page once, through the job board's
public API (Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Eightfold) or
the page itself (IEL), and adds its text to the description: pay, skills,
course and level come from there. A role is read again after 30 days; in
between, the database keeps what its page gave. Each run reads at most a few
thousand pages (new roles first), and opens a few Meta pages in the browser,
where Meta shows its pay. How often the page states pay depends on the
company: nearly every IEL estágio, about two thirds of the US roles from the
GitHub lists, rarely a Brazilian Workday or a European SmartRecruiters role.

A number in a description is shown as pay only when it is clearly the pay.
Better to show nothing than a perk as a salary: "a weekly lunch stipend of
$75" is not $75/hr.

- **A clear pay word** in the amount's sentence or in the heading above it:
  salary, pay, compensation, wage, remuneração, salário, bolsa. Amounts in a
  list under a pay heading ("Pay Range:", "Remuneração") count too.
- **Weaker words** (stipend, allowance, monthly, auxílio, 💰…) count only when
  nothing around the amount is a perk.
- **Perks are not pay**: an amount next to lunch, meals, housing, transport,
  internet, gym, VA/VR, health plan… or in a Benefits / Perks / Benefícios
  section is left out, unless a clear pay word is right next to it. "Next to"
  means its own item of the list: in "Bolsa: R$ 1.200 + Day off" the day off
  belongs to the next item, and in "R$ 1.600 (incluindo auxílio-transporte)"
  the transport is part of the pay.
- **The period** comes from the words right after the amount (`/hr`, "per
  month", "/mês"), then from the words before it in the same item ("Weekly
  stipend of…"), then from the heading. "30 horas semanais" is the workload,
  not the period, and "Primeiro Ano" is the year of the course. Brazilian
  amounts are monthly unless they say otherwise. Only when the sentence clearly
  talks about pay is the period guessed from the size of the number.
- **Believable amounts only**: `$3/hr` or `$100,000/mo` is a misreading, so it
  is dropped.
- **Totals for a whole program** ("$7,000 USD total internship stipend",
  "R$ 6.000 durante o programa") are shown as totals: `$7,000 total`.

The site marks pay read from the description with a `*` and "read from the
description, check the posting" in the opened row. Pay from a salary field has
no mark.

**When it's wrong.** Every opened row has a **Something wrong with this
role?** link: it opens a GitHub issue already filled in with the role, its
link and what the site shows. To fix a pay mistake, paste the part of the
description around the number into `tests/fixtures/pay_cases.yaml` with the
right answer, then change `radar/pay.py` until `pytest tests/test_pay.py`
passes. Every case in that file has to keep passing, so a fix for one posting
can't quietly break another. The file starts with the real mistakes found so
far.

**Optional Claude labelling.** If the secret `ANTHROPIC_API_KEY` is set, new
postings are also sent (title, location and description) to Claude Haiku 4.5,
the cheapest current model. It fills the labels and the deadline more
accurately. It can never remove a posting; if it thinks a posting isn't for
students, it only adds the `unsure if student role` warning. At most 150 new
postings are labelled per run (`RADAR_LLM_MAX_ITEMS` changes that). Without the
key, everything works the same using the keyword rules.

---

## The website

The site is one plain HTML file, `docs/index.html` (no frameworks, no build
step). Each run rewrites `docs/data.json` and the page shows it.

**English and Português.** The site opens in Portuguese when the browser is
set to Portuguese, and in English otherwise; the **EN | PT** switch at the top
of every screen changes it and is remembered. Everything is translated,
including the résumé prompt, dates and numbers (`5.474`, `6 de out.`).
Postings themselves stay as their companies wrote them. All the texts live in
`STRINGS` at the top of the page's script, one `[English, Português]` pair per
text, so adding a language means adding a column.

**First visit: your profile.** The page asks four things: your field of
study (Engineering, Computing & IT, Math/physics/chemistry, Business &
economics, Law, Health, Biology & agriculture, Communication & design,
Education & humanities, Architecture, or Other), what you're studying for
(Bachelor's, Master's or PhD) and where your university is (Brazil, other
Latin America, United States, Canada, United Kingdom, Europe, Asia, Middle
East, Oceania, Africa), and where you would work: in your state (pick the
state you live in), anywhere in Brazil, Latin America, the US and Canada,
Europe, Asia and the Middle East, or anywhere. Each question takes one or more
answers: an Engineering + Computing student, or someone studying in Brazil
with an exchange in Europe, picks both, and a role counts as yours if it suits
any of them. You can skip it and see everything unsorted. **Change your
answers any time** with the profile button at the top right (the one with the
pencil): it opens the same questions with your answers filled in. It is saved
in your browser only.

**Areas you're looking for.** The welcome screen asks "Você procura vagas em
quais áreas?": not only your course, so an engineering student can pick
Business too. The bot labels each role with the fields it is aimed at
(`radar/fields.py`): from the title, or, when the title doesn't say, from the
course phrases in the description ("cursando Direito", "degree in Computer
Science"). The site then:

- shows your field and the related ones together (Engineering, Computing and
  the exact sciences; Health and Biology; Communication, Business and
  Humanities...), with roles for your own field first;
- **hides roles clearly meant only for other fields** (a nursing estágio for
  an engineering student);
- always shows roles that don't say which field they want.

With "Other" as your field nothing is hidden.

**Level.** The bot also labels the levels a role is for (`radar/levels.py`):
from the title ("PhD Intern", "BS/MS", "Bolsa de Mestrado", "Estágio |
Pós-graduação") or, when the title doesn't say, from the description's
enrollment sentences ("currently pursuing a Bachelor's or Master's degree",
"cursando graduação em Direito"). A role only for other levels is hidden: a
PhD internship for an undergrad, an undergrad-only estágio for a master's
student. Roles that don't say, or that are open to all three levels, are
shown to everyone. Pick more than one level if more than one fits you.

**Remote, hybrid or on-site** (`radar/workplace.py`) comes from the job
board's own field, but a clear sentence in the description wins: plenty of
estágios are marked remote while the text says "Modelo de trabalho: Híbrido, 4
dias presenciais". Those count as hybrid (and stop passing as remote), and
their location shows "(hybrid)".

**What an estágio asks for** (`radar/requirements.py`). Open a Brazilian
estágio and a "Requisitos" line shows what its text asks for: the semester ("a
partir do 5º semestre", "do 2º ao 7º"), the expected graduation ("formatura entre
12/2025 e 12/2027"), English (level, and whether it is required or nice to have),
weekly hours and the courses it accepts. They are read with text patterns, no AI:
about 6 in 10 Brazilian estágios get at least one of them, and in a hand check of
100 values 93 were right. When a sentence is unclear the line leaves that part
out rather than guess, and the line only informs: it doesn't sort or hide roles.
Check the details on the job's page.

**A probable field for unplaced titles** (`radar/area_guess.py`). About one role
in six has no field, mostly titles in French, German, Swedish or Chinese that the
word lists don't know. A small multilingual model turns each title into numbers
that stand for its meaning, and such a role gets the fields most common among the
10 roles with the closest titles. In a hand check about 4 in 5 were right, so the
guess only moves a role up for students of that field ("Provavelmente uma vaga de
Engenharia, pelo título"); it never hides a role from anyone.

**Where you'd work.** Roles outside the places you picked are hidden. Remote
roles always show, and so do roles whose place we can't tell. For "in my
state", the bot reads the Brazilian state from each location
(`radar/places.py`: "Recife - PE", "Vitória, Espírito Santo"); a Brazilian role
without a clear state stays visible. "Anywhere" turns this off.

**Hidden roles come back with one click.** "Show roles outside your profile",
next to the number of roles and in the filters, shows everything again. The
note next to the number says why they're hidden ("78 hidden outside your
profile (elsewhere)", "39 hidden (33 for another level, 6 for another field)"),
so a search that finds few roles doesn't look like all there is. Those
roles are marked as long shots with the reason ("For another level: PhD",
"Outside where you'd work: DF"). The roles you saved, applied to or hid always
show in their own tabs.

**Fit.** With a profile, every role gets a dot: ● good fit, ◐ check something,
○ long shot. Open a row to see the reasons, for example:

- "Aimed at PhD or Master's students" (long shot for an undergrad)
- "Needs work authorization for the US or Canada" (when you study elsewhere)
- "Estágio requires enrollment at a Brazilian university" (when you study
  outside Brazil)
- "A job for after you graduate", "Mentions a graduation-year rule",
  "Might not be a student role"

Fit only sorts and flags. Every role stays on the page unless you filter it
out yourself.

**Résumé match (no AI inside vagaLume).** Click **Match my résumé**: the
filled button at the top, the one on the first screen, or the one in any opened
role (which already lists the skills that posting asks for):

1. Copy the prompt. It lists the skill names vagaLume knows, so the answer
   uses the same spelling.
2. Paste it into the AI chat you already use (ChatGPT, Gemini, Claude…) and
   attach your résumé. The prompt asks it to leave out your name and contact
   details and to answer with a small JSON summary: level, field, country,
   graduation month, where you can work, languages, areas, skills, the kind
   of roles you want and the months you're free.
3. Paste the answer back. vagaLume finds the `{ … }` part even if the AI
   wrapped it in text or a code block, and shows what it read.

It works for every area, not only tech: the skill list has law (Tax law,
Litigation, LGPD…), health (Patient care, Pharmacology…), business
(Financial analysis, SAP, CRM…), communication (SEO, Figma, Canva…) and more,
spelled in Portuguese and English in the postings; the "areas" can be any
sub-area of the Área filter (`tributario`, `enfermagem`, `financas`…); and the
role keywords come in both languages. If you already have a profile and the
résumé says something different (another area or level), the summary shows
the change with **Atualizar meu perfil** / **Manter como está** instead of
changing it silently. A graduation date in the past, or one it couldn't read,
is pointed out.

The summary is stored in your browser only. With it:

- Every role gets a **match**: *Strong*, *Good*, *Some* or *Low*. It adds up
  the skills the posting mentions that are in your résumé (programming
  languages listed as alternatives, like "Java, Python or Go", count as one),
  whether the role is in one of your areas, and whether its title contains
  one of the roles you want. Strong and Good matches get a tag; open a row to
  see which skills match (✓) and which are missing.
- **Strong résumé match** and **Good match or better** filters under "For
  you", and a **Best résumé match** sort (the default; long shots still go
  last).
- Your **profile** is filled in from the summary.
- **Fit gets sharper:** countries where you can already work don't get the
  visa warning; a new-grad job is fine when you graduate within a year; an
  estágio says it's in Portuguese if you don't list Portuguese; and your free
  months replace the usual Brazilian calendar in the month strip, the "Fits my breaks"
  filter, and a "runs outside the months you're free" note.

It's keyword matching, so it's a hint for sorting, not a verdict: read the
posting before deciding.

**Each row shows:**

| Column | What it is |
|---|---|
| Role | title (links to the posting), company, and at most two small tags: Applied, Strong match, New or Program. Under it, in amber or red, the first thing that might get in the way. |
| Where | the first location, then "+N more". Open the row for all of them. |
| Pay | when the posting states it, e.g. `$54–60/hr`, `R$1,357/mo`, `€1,800/mo`, `$94K–125K/yr`; a dash otherwise. A `*` means it was read from the description, not a salary field: check the posting (see [How pay is read](#how-pay-is-read)). |
| When | for roles with a season, a 12-month strip, January to December. Grey months are the usual Brazilian semesters (Mar–Jun, Aug–Nov), or the months you're not free if your résumé summary lists them. The role's months are green when they fall in a break and amber when they clash with classes. Year-round roles just say so; a dash means the posting doesn't say. |
| Deadline | the date (a dash when none is stated), with the days left in red when it closes within 14 days |

On a phone the row is shorter: the title, the company and one line with the
place, the deadline and the pay.

Click a row to open it. On the left, **for you**: the résumé match with the
skills you have (✓) and the missing ones, then every fit reason. On the right,
the **details**: all locations, when, deadline, pay, labels and where it was
found. Below, the buttons: open the posting, mark as applied, save, hide, and
**Something wrong with this role?**, which opens a pre-filled GitHub issue.

**Around the list:**

- **Search** over role, company and city. Press `/` to jump to it; matches
  are highlighted.
- **Tabs:** All · New · Closing soon · Saved · Programs & schools, plus
  Applied and Hidden once you have marked something. Only New, Closing soon
  and the lists you build show a count. Searching in a narrow tab says how
  many more matches "All" has ("mais 39 em Todas · ver").
- **Programs & schools** starts with the programs whose applications usually
  open soonest. A program with an `applications` window in `programs.yaml`
  gets a tag: "Inscrições costumam estar abertas" during the window,
  "Costuma abrir em nov" in the two months before it. Open the row to see the
  window. It comes from past years, so the page itself has the last word.
- **Filters** are in the left column, one folding menu per filter: click a
  title to open its chips (several can be open), and the title shows what you
  picked in it ("Área — ML +1"). On phones the column is the "Filtros" box
  above the list. They are:
  *For you* (good fit, no long shots, and with a résumé: strong
  match, good match or better), **Area** (one group per section: Direito with
  Tributário, Trabalhista, Contencioso…; Saúde with Enfermagem, Farmácia…;
  Negócios, Engenharias, Comunicação and the others, plus Tecnologia with ML,
  Software, Data…; your sections first, the rest under "Outras áreas"; picking
  an area outside your profile shows its roles), Where, **Work mode** (remote, hybrid,
  on-site), When (including a **Fits my breaks** shortcut) and **Pay
  currency** (R$, US$, €, £, CA$, other). Under **More filters**: only roles that state pay, and
  the source. The small number on each chip is how many roles you'd see after
  clicking it, given the other filters you already picked. Area, Where, Work
  mode, When and Pay currency take several chips at once and add up (ML **or** Data, Brazil **or**
  Remote); the *For you* ones take one. Click a selected chip again to turn it
  off.
- **Clear all** at the end of the row turns every filter off.
- **How to read** (next to the number of roles) explains the dots and the
  month strip.
- **Sort:** best résumé match (with a résumé), best fit (with a profile), deadline, newest, or company.
- **☆ Save** builds a shortlist (the Saved tab). **✕ Hide** moves a role to
  Hidden; it appears when you point at a row (on phones, it's inside the
  opened row). Inside an opened row you can also **Mark as applied**. All of this
  is saved in your browser, and clicking again undoes it.
- The list shows 60 roles; **Show more** adds 60 more. It never loads by
  itself, so the bottom of the page (sources and links) stays reachable.
- **Your filters live in the address bar** (for example
  `…/vagaLume/#area=ML,data&region=Europe`), so you can bookmark a view or send it
  to a friend.

**In your own copy** (see [Setting it up on GitHub](#setting-it-up-on-github)),
turn the site on once: *Settings → Pages*, *Source* **Deploy from a branch**,
branch **main**, folder **/docs**. A minute later it is live at
`https://<your-user>.github.io/vagaLume/` and it updates after every daily run.

To try it on your computer: `python -m http.server -d docs` and open
http://localhost:8000.

### Statuses for every device

The Save, Applied and Hide buttons only remember things in one browser. In your
own copy, a status that every device sees goes in `config/status.yaml` (edit it
on github.com), by the posting's id, for example:

```yaml
55047c2880ed6544: applied
3f9a1c2b7d4e5f60: ignored   # shows under "Hidden"
```

Statuses are `new`, `seen`, `applied` or `ignored`. The bot itself only
changes `new` to `seen` on the next run. Locally you can also run
`python -m radar status <id> applied`.

---

## How to add things

**A company.** Open one of its job postings and look at the URL:

| URL looks like | Put it under | slug |
|---|---|---|
| `boards.greenhouse.io/anthropic/...` or `job-boards.greenhouse.io/anthropic/...` | `greenhouse:` | `anthropic` |
| `jobs.lever.co/palantir/...` | `lever:` | `palantir` |
| `jobs.eu.lever.co/quantinuum/...` | `lever:` with `eu: true` | `quantinuum` |
| `jobs.ashbyhq.com/openai/...` | `ashby:` | `openai` |
| `jobs.smartrecruiters.com/BoschGroup/...` | `smartrecruiters:` (`id`, and `country: ""` for every country) | `BoschGroup` |
| `ag.wd3.myworkdayjobs.com/en-US/Airbus/...` | `workday_global:` (every country) or `workday_brazil:` | tenant `ag`, wd `3`, site `Airbus` |
| `estagionavale.abler.com.br` | `abler:` | `estagionavale` |
| `<host>.oraclecloud.com/hcmUI/CandidateExperience/en/sites/<site>` | `oracle_hcm:` | host and site |
| a SuccessFactors or Avature career site with an RSS feed | `rss_feeds:` | the feed address |
| a SuccessFactors career site, every country (`careers.sap.com/job/...`) | `successfactors:` | host |
| `<tenant>.inhire.app/vagas/...` | `inhire:` | tenant |
| `<host>/careers?...` on Eightfold (`/api/pcsx/search` answers) | `eightfold:` | host and domain |

Then add `- {slug: anthropic, name: Anthropic}` to `config/companies.yaml` and
run `python -m radar check-config` to confirm that it returns jobs.

**A program page.** Add an entry to `config/programs.yaml`:

```yaml
  - name: Some Summer School
    org: Some University
    url: https://example.org/summer-school
    area: ML              # optional; otherwise guessed from the page
    season: Jul           # optional
    regions: [Europe]     # optional
    applications: "Jan–Mar"  # optional: when applications usually open ("Feb, Aug" for two rounds)
    notes: "deadline usually in March"
```

Run `python -m radar check-config`. If the page shows fewer than 200
characters, it is probably built by JavaScript: add `render: true` and it will
be opened in the headless browser instead.

**Gupy job types, CIEE and Super Estágios school levels, GitHub lists,
Google/Amazon queries:** edit `config/search.yaml`. **Brazilian employers on
SmartRecruiters or Workday:** add them to `smartrecruiters` or `workday_brazil`
in `config/companies.yaml` (the comments there explain how to read the id from
a careers-site address). **Employers with many internships abroad on
Workday** go in `workday_global`: only their student job types are read, in
every country. For Workday, the tenant and site are in the address the career
site calls, `https://<tenant>.wd<N>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs`
(open the browser's network tab on the career site to see it).

---

## Setting it up on GitHub

To run your own copy, with your own companies, programs and searches:

1. **Fork the repository.** GitHub runs scheduled workflows only on the
   default branch (`main`).
2. **Allow the workflow to push.** Go to *Settings → Actions → General →
   Workflow permissions* and pick **Read and write permissions**. The workflow
   commits `data/*.jsonl` and the website data.
3. **Turn on the website:** *Settings → Pages → Deploy from a branch → main,
   /docs*.
4. It runs **once a day**. The schedule asks for 09:00 Brasília (12:00 UTC),
   but GitHub often starts scheduled runs a few hours late. To run it now, open
   *Actions → vagaLume → Run workflow*.

### Secrets (all optional)

Add them under *Settings → Secrets and variables → Actions → New repository
secret*. Anything you leave out is skipped without errors.

| Secret | What for |
|---|---|
| `ANTHROPIC_API_KEY` | better labels from Claude (see above). Get a key at console.anthropic.com. |
| `TELEGRAM_BOT_TOKEN` | Telegram digest. Create a bot by talking to **@BotFather** (`/newbot`); it gives you the token. |
| `TELEGRAM_CHAT_ID` | your chat id. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `message.chat.id`. |
| `SMTP_HOST`, `SMTP_PORT` | email server, e.g. `smtp.gmail.com` and `587` |
| `SMTP_USER`, `SMTP_PASSWORD` | login. For Gmail, use an **App password** (Google Account → Security → 2-Step Verification → App passwords), not your normal password. |
| `EMAIL_TO` | where to send the digest |
| `EMAIL_FROM` | optional sender address (defaults to `SMTP_USER`) |

You can also set the repository **variable** `RADAR_REPORT_URL` to the site
address (https://pedrocamargolince.github.io/vagaLume/) and the digest
will link to it.

### Today's highlights and the personal Telegram digest

The **Destaques de hoje** tab on the site shows the 3, 5 or 10 best *new* roles
of the day for you; with your résumé, sorted by what you know. The rule
(`radar/picks.py`, and the same in the site's JavaScript):

1. only roles first seen today, and only student roles (no "new grad" jobs);
2. that fit your profile: level, field (yours or a related one), where you'd
   work (remote roles that need US work authorization only if you picked the
   US), and the areas you pick in the tab (none = all). Roles whose place
   can't be told are left out here: highlights should be safe bets;
3. best résumé match first (the share of the skills the posting mentions that
   you have), then your own field before related ones, then roles that state
   the pay, then the closest deadline;
4. at most one per company.

"Receber estes todo dia no Telegram" opens the vagaLume bot with these
choices packed in the link. The bot confirms within 30 minutes, and every day
the run sends each person the same highlights the tab shows them. /parar (or
blocking the bot) stops it. To turn it on, once:

1. In Telegram, talk to **@BotFather**: `/newbot`, pick a name and a username
   (e.g. `vagalume_vagas_bot`). It gives you a token.
2. In the repository, *Settings → Secrets and variables → Actions*, add:
   - `TELEGRAM_BOT_TOKEN`: that token;
   - `DIGEST_KEY`: a random key that encrypts the subscriber list. Make one with
     `python -m radar.telegram_bot keygen`, and keep a copy:
     without it the list can't be read.
3. Write the bot's username in `config/digest.yaml` (`telegram_bot:`).

The subscriber list (Telegram chat ids and choices, nothing else) lives in
`data/subscribers.enc`, encrypted: the public repository shows nothing.
`.github/workflows/telegram.yml` reads new sign-ups every 30 minutes; it does
nothing until the two secrets exist.

### Daily updates for students (public digest)

The secrets above send the digest **to you**. To let students get it too,
without vagaLume keeping anyone's name or e-mail (`radar/digest.py`,
settings in `config/digest.yaml`):

- **Feeds, always on.** Every run writes `docs/feed-brasil.xml` (new roles in
  Brazil and remote) and `docs/feed.xml` (all new roles), at most 60 a day each,
  at most 2 per company. Anyone can follow them in a feed reader.
- **Telegram channel.** Create a public channel (e.g. `@vagalume_vagas`), add
  your bot (the `TELEGRAM_BOT_TOKEN` one) to it as an administrator, and write
  the channel name in `telegram_channel`. Each run then posts a short summary
  there: new roles in Brazil and remote, highlights abroad, what closes soon.
- **E-mail.** Make a free "RSS to e-mail" sign-up form for
  `https://pedrocamargolince.github.io/vagaLume/feed-brasil.xml` (follow.it,
  MailerLite or Mailchimp RSS campaigns) and paste its address in
  `email_signup_url`. The service keeps the addresses and sends the e-mails.

The site shows a **Receber todo dia** button as soon as the channel or the
e-mail form is set.

---

## Running it locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
python -m playwright install chromium   # headless browser, only needed for Meta

python -m radar                      # full run (about 35 minutes)
python -m radar --only gupy,programs # just some sources
python -m radar --no-notify          # don't send Telegram/email
python -m radar check-config         # verify every slug and program URL
python -m pytest -q                  # tests (offline, use saved samples)
```

---

## How the code is organised

```
radar/
  main.py          the daily run, step by step (start reading here)
  models.py        the Opportunity record every source returns
  http.py          polite HTTP: user-agent, timeouts, small delays, retries
  browser.py       headless Chromium, only for sites that need JavaScript
  labels.py        keyword rules for area / season / region / warnings
  pay.py           finds the pay in a description ("$54–60/hr", "R$1,357/mo")
  skills.py        finds the skills a posting mentions (for the résumé match)
  llm.py           optional Claude labelling (only with ANTHROPIC_API_KEY)
  db.py            SQLite storage, dedupe by id (hash of the URL)
  report.py        the run's summary for the private digest
  site.py          writes docs/data.json (website) and docs/stats.json (README badges)
  notify.py        optional Telegram / email digest
  textutil.py      HTML to text, date parsing, deadline finding
  sources/         one module per source; each has a pure parse() function
docs/              the website: index.html (fixed) + data.json and stats.json (updated daily)
config/            companies.yaml, programs.yaml, search.yaml, status.yaml, digest.yaml
tests/             pytest tests; tests/fixtures holds saved real responses
.github/           the workflows, this guide, the English README and the README images
pyproject.toml     dependencies (`pip install .`) and test settings
```

A run does four things, in this order: **collect** from each source (failures
are caught per source), **label** with rules (plus Claude if a key is set),
**store** in SQLite (dedupe by URL hash, keep your status), and **publish**
(website data, feeds, notifications).

## Notes

- **Polite scraping.** The bot sends a user-agent that says what it is and
  links here, waits 0.6 s before each request, uses 25 s timeouts, retries
  once (longer pauses after a 429), and does not get around bot protection.
  A full run makes a few thousand requests (most of them job pages) and opens
  a few dozen pages in the browser.
- **Repository size.** The database (`data/*.jsonl`, about 22 MB of text for
  28,000 roles) and `docs/data.json` are committed every
  day: the database is the bot's memory (first-seen dates, your statuses, page
  hashes) and the JSON is the website, so they stay in git on purpose. To keep
  the daily growth small:
  - the database is text, one role per line, sorted, so git stores only the
    lines that changed and merges cleanly;
  - each role's "last seen" date is refreshed once a week, not every day (it
    only decides when a role unseen for 30 days is closed), so on a normal day
    only new and changed roles touch the file;
  - `.gitignore` keeps everything else out (the working `radar.db`, caches,
    virtual environments, editor folders), and `.gitattributes` marks the
    daily files as generated so GitHub collapses them in diffs.
