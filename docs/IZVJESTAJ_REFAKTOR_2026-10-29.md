# Izvještaj o refaktoru — 29.10.2026

Cilj: od postojećeg koda napraviti jednu urednu, pouzdanu aplikaciju, bez nove poslovne logike.
Nalaz prije refaktora: [NALAZ_2026-10-29.md](NALAZ_2026-10-29.md).

## Šta je urađeno

1. **Stanje repoa riješeno bez gubitka.** Lokalne izmjene sa Desktopa su na grani `local/desktop-2026-10`.
   Radna kopija je `~/dev/nba-engine` (van iCloud-a); Desktop kopija je netaknuta i sadrži obje grane kao rezervu.
2. **Izgubljene skripte oporavljene** iz VS Code lokalne istorije (`archive/vscode-history/`), a polomljene
   verzije iz korijena repoa prebačene u `archive/legacy-root-scripts/` (ništa nije obrisano).
3. **Kod podijeljen u paket `nba_engine/`**: podaci (`config`, `loaders`, `offer`, `odds_api`, `refresh/`),
   model (`model`, `pipeline`, `evaluation`), prikaz (`app.py`), ulazna tačka (`__main__.py`).
4. **Jedna komanda za sve**: `python -m nba_engine ui | analyze | fetch-offer | refresh | check`.
5. **Konfiguracija umjesto hardkodiranja**: `.env` (`ODDS_API_KEY`, `NBA_SEASON`, `NBA_DATA_DIR`…);
   sezona se automatski prepoznaje iz podataka; API ključevi više nisu u kodu.
6. **Testovi** (92, svi prolaze): jedinični, na stvarnim podacima i **regresioni** — novi kod daje
   potpuno iste brojke kao stari `app.py` (fajl `tests/fixtures/legacy_full_portfolio.csv`).
7. **README na srpskom** sa uputstvom za pokretanje i opisom potrebnih podataka.

## Provjereno pokretanjem

| šta | rezultat |
|---|---|
| `pytest` | 92 testa prolaze (Python 3.11, pandas 3.1, streamlit 1.66) |
| `python -m nba_engine analyze` na `data/offer_latest.csv` | 62 reda, 51 pick, identično starom app.py |
| `python -m nba_engine refresh` za sezonu **2026-27** (u privremeni folder) | svi koraci rade: igrači 425, timovi 30, ozljede 86 (sve sa timom), raspored 68 utakmica, forma 425, matchup 1565, H2H 13 151 (11 s) |
| `python -m nba_engine analyze` nad svježim 2026-27 podacima | radi (59/62 igrača nađeno — ponuda je iz prošle sezone) |
| Streamlit aplikacija u pregledaču | učitava, analizira, prikazuje portfolio, snima istoriju; bez grešaka u konzoli |
| Probno spajanje sa `origin/main` | samo 2 trivijalna konflikta (stari fajlovi robota `todays_offer.txt`, `todays_games.json`) |

Nije provjereno: povlačenje ponude sa The Odds API uživo (nema važećeg ključa) — testirano je lažnim serverom;
testovi pod sistemskim Pythonom 3.14 (nema pytest-a u njemu).

## Ispravljene greške (jedino što je promijenjeno u ponašanju)

| greška u starom kodu | ispravka | efekat na brojke |
|---|---|---|
| dvije definicije `safe_float` i `normalize_team_abbr` (druga, slabija, pregazi prvu) | zadržana bogatija (mapira i ID i puno ime tima); NaN → prazno | nema na postojećim podacima |
| blok ručnog injury override-a dva puta | jednom | nema |
| opcija „Preskoči H2H“ se ignorisala; app zvao skripte kojih nema | koraci osvježavanja se biraju, H2H je isključen dok se ne uključi | nema |
| istorija se snimala na svaki klik | jednom po rezultatu | nema |
| tabela ozljeda bez tima (ESPN bulk odgovor) → model ozljeda nikad nije radio | tim se izvodi iz imena tima / endpoint po timu; pri učitavanju dopuna iz baze igrača | **DA — ozljede sada utiču** (zato je ovo opcija `--no-fill-injury-team` i regresioni test radi u starom režimu) |
| `def_matchup` bez tima (pogrešno ime kolone u skripti) | kolona `PLAYER_LAST_TEAM_*` | DA, nakon novog osvježavanja (odbrambeni blok 2 u modelu postaje aktivan) |
| `nba_api` parametri koji više ne postoje (`measure_type_simple`, `per_mode_simple`) | ispravni nazivi | nema (skripte ranije nisu radile) |
| kladionica se birala po slučajnom redoslijedu odgovora | prioritet (Pinnacle, bet365, …), podesivo u `.env` | mala — zavisi od ponude |
| ključ API-ja u kodu (i u javnom repou) | `.env` / GitHub Secret | — |

Upozorenje: tabela ozljeda u `data/` je iz marta 2026. Pošto ozljede sada rade, stari statusi OUT utiču na projekcije
dok se ozljede ne osvježe. Aplikacija i komandna linija upozoravaju kada je tabela starija od 2 dana i prikazuju
koji igrači iz ponude su na injury listi.

## Šta NIJE rađeno (namjerno)

- Formule modela, težine i pragovi — nepromijenjeni.
- `ENGINE_REZULTATI` (poseban alat za poređenje predikcija i rezultata) — nije dio repoa.
- `refresh_daily.py`, `filters.py` (crna lista igrača), stari `*_engine.py` moduli — samo u `archive/`.
- Čišćenje duplikata u `data/` (`players_2025-26 copy.csv`, `offer_2026-03-*.csv`, `props_raw_*.json`) — nije brisano.

## Odluke koje čekaju

1. **Push i PR** grane `refactor/one-app` na GitHub (ne radi se bez odobrenja). Spajanje sa `main`: dva stara fajla robota se brišu.
2. **The Odds API ključ**: stari je javno vidljiv u istoriji repoa — poništiti ga i napraviti novi;
   novi upisati u `.env` (lokalno) i, ako robot treba da radi, u GitHub Secrets kao `ODDS_API_KEY`.
3. **Nova sezona**: upisati `NBA_SEASON=2026-27` u `.env` i pokrenuti `python -m nba_engine refresh --with-h2h`
   (ili dugme u aplikaciji); podaci u `data/` su još iz 2025-26.
4. Da li zadržati podatke (`data/*.csv`) u gitu ili ih izbaciti (sada su u repou, ~2 MB, mijenjaju se svaki dan).
