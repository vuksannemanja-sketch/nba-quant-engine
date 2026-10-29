# NBA Quant Engine

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
| `python -m nba_engine fetch-offer` | povlači današnju ponudu sa The Odds API u `data/offer_latest.csv` |
| `python -m nba_engine refresh` | osvježava CSV podatke: ponuda, igrači/timovi, ozljede, matchup + forma, raspored (H2H uz `--with-h2h`) |
| `python -m nba_engine check` | provjera podešavanja, podataka i biblioteka |

Korisne opcije: `analyze --offer PUTANJA --top 20 --min-ev 5 --only-positive --no-schedule`,
`refresh --steps players,injuries` (samo odabrani koraci), `--season 2026-27`, `--data-dir /drugi/folder`.
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
sezona po današnjem datumu (od oktobra nova). Na početku nove sezone: upiši `NBA_SEASON=2026-27` u `.env`
i pokreni `python -m nba_engine refresh`.

`.env` promjenljive: `ODDS_API_KEY`, `NBA_SEASON`, `NBA_DATA_DIR`, `NBA_HISTORY_DIR`, `ODDS_BOOKMAKERS` (vidi `.env.example`).
Fajl `.env` se ne šalje na GitHub.

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

- jedinični testovi: parsiranje ponude, normalizacija imena/timova, formule, evaluacija, konfiguracija, osvježavanje (čiste funkcije);
- testovi na stvarnim podacima iz `data/`;
- **regresija**: `tests/fixtures/legacy_full_portfolio.csv` je izlaz starog `app.py` na istim podacima;
  nova aplikacija mora dati iste brojke (`tests/test_regression_legacy.py`).

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
  __main__.py           komandna linija
tests/                  pytest
data/                   CSV podaci (ulaz)
history/                rezultati analiza (izlaz, nije u gitu)
archive/                stari kod (ne koristi se) — vidi archive/README.md
```

## GitHub robot (Actions)

`.github/workflows/fetch_offer.yml` svaki dan u 19:00 povlači ponudu u `data/offer_latest.csv`.
Radi samo ako je u GitHub repou postavljen secret `ODDS_API_KEY` (Settings → Secrets and variables → Actions);
bez njega korak se preskače.

## Napomene

- Podaci u `data/` su iz sezone 2025-26 (mart 2026). Za novu sezonu pokreni `refresh`.
- `nba_api` povlači sa NBA Stats servera koji povremeno odbija zahtjeve; koraci se ponavljaju do 3 puta,
  a greška u jednom koraku ne zaustavlja ostale.
- Codespaces/devcontainer: `.devcontainer/devcontainer.json` instalira zavisnosti i pokreće aplikaciju.
