# NBA Quant Engine

[![Tests](https://github.com/vuksannemanja-sketch/nba-quant-engine/actions/workflows/tests.yml/badge.svg)](https://github.com/vuksannemanja-sketch/nba-quant-engine/actions/workflows/tests.yml)

Aplikacija za dnevnu analizu NBA „player points“ ponude: za svakog igrača iz ponude računa projekciju poena,
Monte Carlo vjerovatnoću za OVER/UNDER, očekivanu vrijednost (EV) i rangira pickove.
Sadrži i ocjenu modela na stvarnim rezultatima.

Sav kod je u paketu `nba_engine/`. `app.py` je samo Streamlit prikaz, a iste funkcije rade i iz komandne linije.

## Brzi start

```bash
# 1) jednom: virtuelno okruženje i zavisnosti (Python 3.11 ili noviji)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2) podešavanja (ključ za ponudu); bez .env fajla radi sve osim povlačenja ponude
cp .env.example .env     # pa upiši ODDS_API_KEY=...

# 3) provjera stanja (sezona, fajlovi, zavisnosti)
python -m nba_engine check

# 4) aplikacija u pregledaču
python -m nba_engine ui
```

## Komande

| komanda | šta radi |
|---|---|
| `python -m nba_engine ui` | pokreće Streamlit aplikaciju (isto što i `streamlit run app.py`) |
| `python -m nba_engine analyze` | dnevna analiza u terminalu nad `data/offer_latest.csv`; ispisuje najbolje pickove i snima u `history/` |
| `python -m nba_engine fetch-offer` | povlači današnju ponudu sa The Odds API u `data/offer_latest.csv` (samo mečevi današnjeg američkog dana; `--all-events` za sve) |
| `python -m nba_engine refresh` | osvježava CSV podatke: ponuda, igrači/timovi, ozljede, matchup + forma, raspored (H2H uz `--with-h2h`) |
| `python -m nba_engine check` | provjera podešavanja, podataka i biblioteka |
| `python -m nba_engine daily` | dnevni posao u jednom potezu: refresh → settle → fetch-offer → analyze → ai (uz `--push` i slanje podataka na GitHub) |
| `python -m nba_engine ai` | AI izvještaj: Claude bira 10 najsigurnijih opklada iz današnje analize; `--report` ispisuje statistiku AI izbora |
| `python -m nba_engine schedule --install` | podešava da se `daily` sam pokreće svaki dan na ovom računaru (macOS launchd); `--status`, `--remove` |
| `python -m nba_engine schedule --install-closing` | podešava snimanje zatvorenih linija (00:45, 01:45, 02:45 i 03:45) za mjerenje CLV; `--remove-closing` |
| `python -m nba_engine v2` | v2 u sjeni: poređenje sa jednostavnim pravilima, starim modelom i AI izborima; `--settle`, `--calibrate`, `--backtest` |

Korisne opcije: `analyze --offer PUTANJA --top 20 --min-ev 5 --only-positive --no-schedule`,
`refresh --steps players,injuries` (samo odabrani koraci), `--season 2026-27`, `--data-dir /drugi/folder`.
`settle` poravnava snimljene analize sa stvarnim poenima (vidi „Automatska evaluacija“).
Svaka komanda ima `--help`.

## Šta treba od podataka

Svi fajlovi su u folderu `data/` i nose sezonu u imenu (npr. `players_2026-27.csv`).
Pravi ih komanda `refresh`; aplikacija ih samo čita.

| fajl | sadržaj | izvor (korak `refresh`) | obavezan |
|---|---|---|---|
| `offer_latest.csv` | dnevna ponuda: `PLAYER, PLAYER_TEAM, LINE, OVER_ODDS, UNDER_ODDS, OPP_TEAM, TOTAL_MATCH` | `offer` (The Odds API) ili ručni upload u aplikaciji | da |
| `players_<sezona>.csv` (+ `_advanced`, `_misc`, `_base`) | statistika igrača po utakmici (PTS, MIN, USG%, TS%, PIE…) | `players` (NBA Stats) | da |
| `teams_<sezona>.csv` | statistika timova (OFF/DEF rating, PACE, NET) | `players` | da |
| `injuries_<sezona>.csv` | ozljede: `PLAYER, TEAM_ABBR, STATUS, DESCRIPTION` | `injuries` (ESPN) | ne |
| `form_l10_<sezona>.csv` | forma: L3/L5/L10 prosjek, trend | `matchups` | ne |
| `def_matchup_<sezona>.csv`, `off_matchup_<sezona>.csv` | odbrambeni / napadački profil protivnika | `matchups` | ne |
| `schedule_<sezona>.csv`, `b2b_<sezona>.csv` | raspored i back-to-back oznake | `schedule` | ne |
| `h2h_<sezona>.csv` | prosjek igrača protiv svakog protivnika (3 sezone) | `h2h` (sporo, 10–20 min) | ne |

Ponuda može biti i ručno napravljen tekst/CSV sa 4–7 kolona (`ime, linija, over, under[, protivnik][, total]`).

Ako neki neobavezni fajl nedostaje, model radi bez te komponente (vidi „DEBUG DATA“ u aplikaciji).

## Sezona i podešavanja

Redoslijed: argument komande → `.env` (`NBA_SEASON`) → najnovija sezona za koju postoje fajlovi u `data/` →
sezona po današnjem datumu (od oktobra nova). Na početku nove sezone dovoljno je jednom pokrenuti
`python -m nba_engine refresh --season 2026-27 --with-h2h`: kad se pojave fajlovi `*_2026-27.csv`, aplikacija
sama bira najnoviju sezonu u `data/`. Stari fajlovi (`*_2025-26.csv`) ostaju i ne smetaju; `NBA_SEASON` u `.env`
treba samo ako želiš nasilno drugu sezonu.

`.env` promjenljive: `ODDS_API_KEY`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `NBA_SEASON`, `NBA_DATA_DIR`,
`NBA_HISTORY_DIR`, `ODDS_BOOKMAKERS` (vidi `.env.example`). Izmjena `.env` fajla se vidi i u aplikaciji koja već radi,
bez ponovnog pokretanja.
Fajl `.env` se ne šalje na GitHub.

## Automatska evaluacija (da li model pogađa)

Svaka analiza ponude za današnje mečeve se snima u `history/analysis_<datum>_<vrijeme>.csv`. Sutradan (ili bilo kad
kasnije) pokreni:

```bash
python -m nba_engine settle
```

Komanda povuče stvarne poene iz NBA game loga (isti izvor kao forma i H2H), poravna svaku još neporavnatu analizu
i upiše:

- `history/settled_<ime analize>.csv`: svaki pick sa stvarnim poenima, ishodom (WIN / LOSS / PUSH / VOID) i profitom;
- `history/ledger.csv`: jedan red po analizi (pogodak %, profit, ROI, MAE, ocjena A–F) i zbir preko svega.

Pravila: računa se samo OVER/UNDER (NO VALUE nije opklada); igrač koji nije igrao = VOID; analiza snimljena prije
06:00 pripada prethodnom (američkom) danu; meč se traži po protivniku iz analize (±1 dan). **Jedna analiza po danu**:
zvanična je analiza dnevnog posla (fajl sa oznakom `_daily`), a ako je tog dana nema, zadnja snimljena; ostale analize
istog dana dobijaju status „nije zvanična“ i ne ulaze u ledger. Aplikacija ne snima identične kopije istog rezultata. Isto radi dugme
„🔄 Poravnaj nove analize“ u aplikaciji, gdje se vidi i zbirna ocjena. `settle --report` samo ispisuje stanje, bez mreže.

Preporuka: dvije do tri sedmice samo snimati i poravnavati, bez uplata, pa tek onda zaključivati o modelu.

## AI izvještaj (10 najsigurnijih)

Poslije dnevne analize Claude (Anthropic API) dobija cijelu ponudu sa projekcijama modela, formom, minutama i listom
povreda, i bira **10 opklada sa najvećom vjerovatnoćom prolaza**. Za svaku piše kratko obrazloženje i glavni rizik, a
na vrhu kratak pregled dana. Smije izabrati i stranu suprotnu od modela.

- **Gdje se vidi:** rubrika „🤖 AI izvještaj“ na vrhu bočne trake aplikacije; u terminalu `python -m nba_engine ai`.
- **Kad se pravi:** u dnevnom poslu, odmah poslije analize (faza `ai`). Dugme „Napravi AI izvještaj sada“ u aplikaciji
  pravi ručni izvještaj nad trenutnom tabelom.
- **Zasebna statistika:** izbori se snimaju u `history/ai/` u istom formatu kao analiza, pa ih poravnava isti `settle`,
  ali u vlastiti ledger (`history/ai/ledger.csv`). Aplikacija i `python -m nba_engine ai --report` prikazuju zbir po
  danima i **po mjesecima**, odvojeno od modela. Važi isto pravilo „jedna po danu“: ocjenjuje se izvještaj dnevnog
  posla (oznaka `_daily`), ručni samo ako tog dana nema dnevnog.
- **Ključ:** `ANTHROPIC_API_KEY` u `.env` (pravi se na console.anthropic.com → API keys; API se plaća odvojeno od
  pretplate na Claude aplikaciju). Bez ključa se faza preskače i sve ostalo radi kao prije.
- **Model i trošak:** podrazumijevano `claude-opus-5-5` (`ANTHROPIC_MODEL` u `.env` za drugi). Jedan izvještaj je
  jedan poziv; stvarni broj tokena i okvirni trošak pišu ispod svakog izvještaja i zbirno za mjesec. Za istu analizu
  se izvještaj ne pravi dva puta (`ai --force` pravi novi i ostavlja stari).
- **Šta AI ne radi:** ne pretražuje internet i ne zna ništa što nije u podacima aplikacije; sastavi koji izađu pred
  sam meč mu nisu poznati.

## Dnevni posao i automatsko pokretanje

Sve što treba uraditi jednom dnevno stoji u jednoj komandi:

```bash
python -m nba_engine daily          # refresh → settle → fetch-offer → analyze → ai
python -m nba_engine daily --push   # isto + commit i slanje osvježenih data/*.csv na GitHub (grana main)
```

Faze idu redom i greška u jednoj ne zaustavlja ostale:

1. **refresh** – igrači/timovi, ozljede, DEF/OFF matchup + forma, raspored (H2H uz `--with-h2h`);
2. **settle** – poravnanje ranijih analiza sa stvarnim poenima (evaluacija), i modela i AI izbora;
3. **offer** – današnja ponuda sa The Odds API (preskače se ako `ODDS_API_KEY` nije u `.env`). Kvote se traže samo
   za mečeve današnjeg američkog dana, iz regija `us,eu` (2 zahtjeva po meču; `ODDS_REGIONS` u `.env`), a totali
   svih mečeva jednim zahtjevom. Jedno povlačenje tako staje oko 2 × broj mečeva + 1 zahtjev, oko 480 mjesečno
   uz jedno dnevno — besplatni paket ima 500, pa log upozorava kad kvota ne pokriva ostatak mjeseca.
   `fetch-offer --all-events` povlači i mečeve drugih dana;
4. **analyze** – analiza ponude i snimanje u `history/`, ali samo ako je ponuda povučena danas (mlađa od 20 h)
   i ako je bar polovina njenih parova među današnjim mečevima po ESPN rasporedu;
5. **ai** – AI izvještaj nad tom analizom (preskače se ako `ANTHROPIC_API_KEY` nije u `.env` ili analiza nije snimljena);
6. **push** (samo uz `--push`) – commit `data/*.csv` i slanje na GitHub. Radi samo sa grane `main`, odbija ako su
   izmijenjeni i drugi fajlovi (kod), a pri sukobu sa GitHub-om zadržava lokalne (novije) podatke. Ako nema mreže,
   commit ostaje lokalno i šalje se sutra.

Svaki run piše `logs/daily_<datum>_<vrijeme>.log`, a rezime u `logs/daily_last_report.json`; aplikacija ga pokazuje
u bočnoj traci („🕒 Dnevni posao“). Čuva se zadnjih 60 logova.

**Automatsko pokretanje na ovom računaru (macOS):**

```bash
python -m nba_engine schedule --install            # svaki dan u 22:30, sa --push
python -m nba_engine schedule --install --hour 23 --minute 45   # drugo vrijeme; --no-push bez slanja na GitHub
python -m nba_engine schedule --status             # da li je podešen i kako je prošao zadnji run
python -m nba_engine schedule --remove             # ukloni
```

Zašto 22:30: to je 16:30 u Americi — popodnevni izvještaj o povredama (13:00 ET) je objavljen, linije kladionica su
slegle, a prvi večernji mečevi počinju tek u 01:00 po našem vremenu. Vikendom popodne ima mečeva koji počinju ranije;
oni su u 22:30 već u toku i analiza ih preskače. Kasnije vrijeme (npr. 23:45) hvata i izvještaj iz 17:30 ET, ali Mac
tada mora biti budan.

Podešavanje se upisuje u `~/Library/LaunchAgents/com.nba-engine.daily.plist` i koristi Python iz `.venv` ovog
foldera. Računar mora biti uključen ili da spava u to vrijeme (po buđenju posao kreće odmah); ugašen računar
preskače taj dan. Zašto lokalno a ne na GitHub-u: NBA Stats server često odbija zahtjeve sa servera u oblaku,
pa osvježavanje podataka radi pouzdano samo sa kućnog računara. Na Linuxu `schedule --show` ispisuje cron liniju.

Za potpunu automatsku evaluaciju treba samo jedno: ključ The Odds API u `.env` na ovom računaru. Od tada se svaki
dan snima analiza, a sutradan poravnava sa stvarnim poenima.

## v2 (u sjeni): tržište kao osnova

Pregled od 22.11.2026 (`docs/PREGLED_2026-11-22.md`, 20 dana, 1.370 izbora) pokazao je da odstupanje modela od granice
kladionice ne predviđa ishod, da je raspon (sigma) preuzak za igrače sa niskom granicom i da rang po True Score nema
veze sa ishodom. v2 zato radi **uporedo** sa starim modelom, ne mijenja ga i piše u zasebnu evidenciju `history/v2/`.

- **Fer vjerovatnoća** je tržišna: kvote Pinnacle-a na istoj liniji bez marže; bez Pinnacle-a prosjek najmanje tri
  kladionice sa istom linijom; bez toga igrač ne ulazi u izbor.
- **Model** računa svoju vjerovatnoću sa stvarnim ostacima po grupi granice (`nba_engine/v2_calibration.json`,
  `v2 --calibrate`), ali ulazi u konačnu vjerovatnoću samo sa težinom `V2_MODEL_WEIGHT` iz `.env`
  (podrazumijevano **0**). Težina se podiže tek kad ocjena u aplikaciji („Težina modela iznad tržišta“) pokaže da je
  95 % raspon iznad nule.
- **Izbor**: najbolja kvota na istoj liniji, očekivana vrijednost najmanje +1 % nad fer cijenom; kvota više od 15 %
  iznad fer cijene je sumnjiva (zastarjela linija) i preskače se. Najviše 10 izbora dnevno i 3 po utakmici; dan bez
  izbora je ispravan ishod.
- **Evidencija**: `history/v2/analysis_*` (cijeli spisak igrača), `settled_*` i `ledger.csv` (izbori),
  `universe_settled_*` (cijeli spisak sa ishodima) i `benchmarks.csv` (po danu: v2, „uvijek manje“, „uvijek više“,
  „strana koju tržište smatra vjerovatnijom“, nasumična strana). Poređenje i kalibracija: `python -m nba_engine v2`
  i odjeljak „🧪 v2 (u sjeni)“ u aplikaciji.
- **Dnevni posao**: v2 se računa odmah poslije v1 u fazi `analyze`, a poravnava u fazi `settle`. Greška v2 nikad
  ne ruši ni ne mijenja stari model.
- **Sve kvote po kladionici** se od sada snimaju u `data/quotes_<datum>.csv` (bez dodatnih API zahtjeva).
- **Zatvorene linije (CLV)**: `schedule --install-closing` podešava `fetch-offer --closing` u 00:45, 01:45, 02:45 i 03:45
  (posebna launchd usluga). Snimak se imenuje po američkom datumu mečeva, uzima samo mečeve koji još nisu počeli i
  počinju u narednih ~4 h (stara linija snimljena pri kasnom pokretanju se ne prihvata) i mijenja samo redove igrača
  koje je ponovo povukao, pa svaki igrač dobija zadnju liniju prije svog meča (`data/closing_<datum>.csv` i
  `data/closing_quotes_<datum>.csv`). Trošak oko 60 API zahtjeva dnevno. Kad se linija pomjerila, CLV se računa
  pomjeranjem fer vjerovatnoće na našu liniju (normalna aproksimacija sa izmjerenim rasponom).
- **Pregledi unaprijed**: prvi na 500 izbora sa zatvorenom linijom (CLV), drugi na 2.000 izbora (pogodak i ROI).
  Prije toga se ne tvrdi da prednost postoji.
- **Provjera unazad**: `python -m nba_engine v2 --backtest` svaki dan uči kalibraciju samo iz ranijih dana i mjeri
  grešku vjerovatnoće na neviđenom danu (stari model, tržište, model sa ispravnim rasponom, mješavine).
  Na 20 dana: tržište 0,2491, bacanje novčića 0,2500, stari model 0,2615, model sa ispravnim rasponom 0,2586.

`v2 --calibrate` prepisuje praćeni fajl `nba_engine/v2_calibration.json`; dok se ne commit-uje, slanje podataka na GitHub
se preskače (zaštita od izmjena koda). Commit ide kroz PR.

Ograničenje: ponuda (Pinnacle i američke kladionice) ne mora biti dostupna kladionicama koje igrač stvarno koristi, pa je ROI u v2 „na papiru“.

## Ulazi modela iz grupe B (uključeni, mogu se isključiti)

Formule su iste kao u starom `app.py`; mijenjaju se samo ulazi. Sva tri prekidača su u bočnoj traci
(„🧪 Ulazi modela“) i u komandnoj liniji (`analyze --no-prior-season --no-l10-minutes --no-l10-sigma`).

- **Prošla sezona na početku sezone.** Do 20 odigranih utakmica statistika igrača i timova je ponderisani prosjek
  ove i prošle sezone: težina ove = utakmice/20; prošla sezona sa manje od 10 utakmica vrijedi srazmjerno manje;
  igrač bez prošle sezone ostaje netaknut. Kolona `Prior Weight` u tabeli pokazuje udio prošle sezone.
- **Minute iz zadnjih 10 utakmica.** Osnova minuta = sezonski prosjek dopunjen sa `L10_MIN` (težina 0,12 po utakmici
  u formi, najviše 0,60). Gornje granice minuta važe u odnosu na tu osnovu. Kolone `Minutes Base`, `L10 MIN`.
- **Rasipanje iz zadnjih 10 utakmica.** Rasipanje iz formule se miješa sa stvarnim `L10_STD` igrača (težina 0,10 po
  utakmici, najviše 0,50), pa ostaju iste granice kao prije. Kolona `L10 STD`.

Kvote: `fetch-offer` za svakog igrača uzima liniju od kladionice najvišeg prioriteta, a kvote najbolju Over i najbolju
Under među kladionicama koje nude **istu** liniju (detalji po kladionici u `data/offer_books_<datum>.csv`;
`--single-book` isključuje). `fetch-offer --closing` snima zatvorene linije u `data/closing_<datum>.csv` i tada
`settle` računa i CLV. Taj drugi poziv troši API zahtjeve, pa nije u dnevnom poslu nego u posebnoj usluzi
(`schedule --install-closing`, vidi „v2 u sjeni“).

## Šta se računa automatski i koje zaštite postoje

- **Domaćin/gost, back-to-back i dani odmora** se čitaju iz ESPN rasporeda (danas i prethodnih 6 dana) pri svakoj
  analizi. Ručni unos u bočnoj traci (Away timovi, B2B timovi, Rest days) služi samo za ispravke i ima prednost.
  Kad ESPN nije dostupan, važe stare podrazumijevane vrijednosti (svi domaćini, 2 dana odmora) i aplikacija to kaže.
- **Igrači sa statusom OUT/INACTIVE** (iz tabele ozljeda ili ručnog injury overridea) ne ulaze u rangiranje, jer
  kladionica opkladu na igrača koji ne igra poništava. Prikazani su posebno („⛔ Isključeni igrači“).
  Komandna linija: isto; u kodu se može ugasiti sa `AnalysisOptions(exclude_out=False)`.
- **Svježina ponude**: ako je manje od polovine parova tim–protivnik iz ponude među današnjim mečevima po ESPN
  rasporedu, aplikacija prikazuje crveno upozorenje, a analiza se **ne snima** u `history/` (jedan slučajno poklopljen
  par iz stare ponude nije dovoljan). Bez rasporeda provjera se preskače.

## Kako aplikacija računa (ukratko)

1. **Ponuda** se parsira, igrač se traži u bazi (tačno ime, „Prezime, Ime“, inicijal, dijelovi imena, slično ime).
2. **Projekcija** (`nba_engine/model.py`): minute × poeni po minuti, sidro na sezonski prosjek,
   pa faktori: tempo i matchup timova, total meča, usage, šut, slobodna bacanja, efikasnost, uloga, stil,
   odbrana protivnika, forma L3/L5/L10 i trend, H2H, ozljede saigrača, back-to-back, domaćin/gost, dani odmora.
3. **Monte Carlo** (`pipeline.py`): kalibracija prema liniji kladionice, 5000 simulacija → P(over), EV za obje strane,
   izbor OVER / UNDER / NO VALUE.
4. **Rangiranje**: True Score = 0.5·EV + 0.3·edge + 0.2·pouzdanost (z-skorovi); filteri Min EV / samo pozitivni.
5. **Koncentracija**: ako jedan tim ima 3+ OVER pickova, 3. i dalji dobijaju EV kaznu (×0.85 / ×0.55).
6. **Istorija**: rezultat se snima u `history/analysis_<vrijeme>.csv` (u aplikaciji jednom po rezultatu, ne na svaki klik).
7. **Evaluacija**: upload stvarnih rezultata → accuracy, ROI, MAE, CLV, ocjena A–F; moguće poređenje dva modela.

Formule su identične originalnom `app.py` (provjereno regresionim testom, vidi dolje).

## Testovi

```bash
.venv/bin/python -m pytest
```

Isti testovi se sami pokreću na GitHub-u pri svakom pull requestu i svakoj izmjeni na `main`
(`.github/workflows/tests.yml`, Python 3.11 i 3.12). Testovi ne koriste mrežu.

- jedinični testovi: parsiranje ponude, normalizacija imena/timova, formule, evaluacija, konfiguracija, osvježavanje (čiste funkcije);
- testovi na stvarnim podacima iz `data/`;
- **regresija**: `tests/fixtures/legacy_full_portfolio.csv` je izlaz starog `app.py` na martovskoj ponudi
  `tests/fixtures/legacy_offer_2026-03.csv` i podacima 2025-26; nova aplikacija mora dati iste brojke
  (`tests/test_regression_legacy.py`). Testovi ne čitaju `data/offer_latest.csv`, jer se on svaki dan mijenja.

## Struktura

```
app.py                  Streamlit prikaz
nba_engine/
  config.py             podešavanja (.env, sezona, putanje)
  teams.py utils.py     mape timova, pomoćne funkcije
  offer.py              parsiranje ponude i ručnih unosa
  loaders.py            učitavanje CSV-ova (DataBundle)
  model.py              projekcija poena (formule)
  pipeline.py           analiza: projekcije → Monte Carlo → rangiranje
  evaluation.py         ocjena modela
  schedule.py           raspored/stanje mečeva (ESPN)
  history.py            snimanje rezultata
  odds_api.py           The Odds API (ponuda)
  refresh/              osvježavanje: players, injuries, matchups, schedule, h2h
  settle.py             automatska evaluacija (poravnanje sa stvarnim poenima)
  prior.py              dopuna rane sezone prošlom sezonom
  ai_report.py          AI izvještaj: Claude bira 10 najsigurnijih opklada (history/ai/)
  v2.py                 v2 u sjeni: fer cijena tržišta, model sa stvarnim ostacima, izbor (history/v2/)
  v2_eval.py            v2: poravnanje cijelog spiska, jednostavna pravila, CLV, kalibracija, provjera unazad
  v2_calibration.json   stvarni ostaci po grupi granice (osvježava se sa `v2 --calibrate`)
  daily.py              dnevni posao (sve faze redom, log, slanje na GitHub)
  scheduler.py          dnevno pokretanje na računaru (macOS launchd)
  __main__.py           komandna linija
tests/                  pytest
data/                   CSV podaci (ulaz)
history/                rezultati analiza (izlaz, nije u gitu)
logs/                   logovi dnevnog posla (nije u gitu)
archive/                stari kod (ne koristi se) — vidi archive/README.md
```

## GitHub roboti (Actions)

- `.github/workflows/tests.yml` – pri svakom pull requestu i izmjeni na `main` instalira zavisnosti i pokreće testove.
- `.github/workflows/fetch_offer.yml` – svaki dan u 17:00 UTC (18:00 zimi / 19:00 ljeti) povlači ponudu u
  `data/offer_latest.csv`. Radi samo ako je u GitHub repou postavljen secret `ODDS_API_KEY`
  (Settings → Secrets and variables → Actions); bez njega korak se preskače. Ovo je rezerva za dane kad je kućni
  računar ugašen; glavni put je dnevni posao na računaru (vidi gore).

## Napomene

- Podaci u `data/` su za tekuću sezonu (dnevni posao ih osvježava); fajlovi sezone 2025-26 ostaju zbog testova
  i dopune rane sezone.
- `nba_api` povlači sa NBA Stats servera koji povremeno odbija zahtjeve; koraci se ponavljaju do 3 puta,
  a greška u jednom koraku ne zaustavlja ostale.
- Codespaces/devcontainer: `.devcontainer/devcontainer.json` instalira zavisnosti i pokreće aplikaciju.
- Verzije biblioteka su fiksirane u `requirements.txt` (streamlit, pandas, numpy, requests, nba_api, pytest), da se
  aplikacija ponaša isto i poslije godinu dana. Nadogradnja: promijeni verziju, `pip install -r requirements.txt`,
  pokreni testove, pa commit.
- Ako je Python instaliran preko Homebrew-a, njegova nadogradnja može pokvariti `.venv` (dnevni posao počne javljati
  grešku). Popravka: `rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, pa
  `python -m nba_engine schedule --install` ponovo.
