# Provjera portfolija: odakle podaci, šta model koristi, ima li fiktivnih vrijednosti (1.11.2026)

Provjera je rađena na prvoj pravoj analizi sezone 2026-27: `history/analysis_2026-11-01_19-13-52.csv`
(42 picka, 4 meča, ponuda povučena 1.11. u 19:13). Kod: `nba_engine/model.py`, `pipeline.py`, `loaders.py`, `prior.py`.

## 1. Kratki odgovor

- **Svi ulazi su stvarni.** Statistika igrača i timova, forma, H2H, odbrambeni matchup, ozljede, raspored i ponuda
  dolaze sa NBA Stats, ESPN-a i The Odds API-ja, osvježeni istog dana. Za 42 picka nijedan ulaz nije nedostajao,
  pa se nijedna rezervna („podrazumijevana“) vrijednost nije aktivirala.
- **Model ne koristi sve kolone iz fajlova, i to je namjerno.** Fajlovi igrača imaju 77 kolona (plus rangovi,
  biografija, fantasy poeni); model koristi 28 kolona po igraču, 4 po timu, 7 iz forme, 3 iz H2H, 2 iz ozljeda i
  7 iz ponude. Ostalo su podaci koji se ne tiču projekcije poena.
- **Jedan ulaz se koristi slabije nego što izgleda:** odbrambeni matchup (`def_matchup`, 1.645 redova po braniocu i
  kategoriji) ulazi u račun kao jedan prosjek po timu (dozvoljeni FG% za dvojke). To je naslijeđeno iz starog app.py,
  formule nisu dirane. Detalji u tački 6.
- **Fiktivnih podataka u produkcijskom putu nema.** Izmišljene brojke postoje samo u testovima (`tests/`), u arhivi
  starog koda (`archive/`) i u probnim analizama iz oktobra (`history/_probne_analize_2026-10/`), koje ne ulaze u
  evaluaciju. Ručna polja u bočnoj traci (Recent Form, B2B, Away, Rest, Injury) su prazna; sivi tekst u njima je
  samo primjer formata.

## 2. Odakle dolazi svaki podatak

| Fajl u `data/` | Izvor | Osvježava | Šta model uzima |
|---|---|---|---|
| `players_<sezona>.csv` (+`_base`, `_advanced`, `_misc`) | NBA Stats `LeagueDashPlayerStats` (Base, Advanced, Misc, PerGame, Regular Season) + `LeagueDashPlayerBioStats` | `daily` svaki dan (korak players) | PTS, MIN, GP, USG_PCT, TS_PCT, EFG_PCT, FG_PCT, FT_PCT, FG3_PCT, FG3A, PIE, AST_RATIO, AST_TO, TM_TOV_PCT, NET_RATING, PLUS_MINUS, PTS_PAINT, PTS_FB, PTS_2ND_CHANCE, PTS_OFF_TOV, OPP_PTS_PAINT, OPP_PTS_FB, OPP_PTS_2ND_CHANCE, OPP_PTS_OFF_TOV; izvedeno: PPM, FGA_PM, FTA_PM, FG3A_PM |
| `teams_<sezona>.csv` | NBA Stats `LeagueDashTeamStats` (Base + Advanced) | players korak | PACE, OFF_RATING, DEF_RATING, NET_RATING |
| `form_l10_<sezona>.csv` | NBA Stats `LeagueGameLog` igrača → zadnjih 10 utakmica | matchups korak | L3_PTS, L5_PTS, L10_PTS, TREND_SLOPE, L10_MIN, L10_STD, GAMES_PLAYED |
| `h2h_<sezona>.csv` | `LeagueGameLog` za 3 sezone, po paru igrač–protivnik | `refresh --steps h2h` (sporo, ručno) | H2H_PTS_AVG, H2H_GAMES, H2H_PTS_LAST |
| `def_matchup_<sezona>.csv` | NBA Stats `LeagueDashPtDefend` (4 kategorije odbrane, po braniocu) | matchups korak | prosjek FG2_PCT po timu protivnika (vidi tačku 6) |
| `off_matchup_<sezona>.csv` | `LeagueDashTeamStats` Advanced | matchups korak | **ništa** (prima se, ne koristi se; tako je bilo i u originalu) |
| `injuries_<sezona>.csv` | ESPN injuries API | injuries korak | TEAM_ABBR, STATUS (+ USG i MIN ozlijeđenih saigrača iz baze igrača) |
| `schedule_<sezona>.csv`, `b2b_<sezona>.csv` | `LeagueGameLog` timova (odigrani mečevi) | schedule korak | B2B samo za već odigrane datume; za današnji dan B2B, domaćin/gost i odmor dolaze **uživo sa ESPN rasporeda** |
| `offer_latest.csv` | The Odds API `player_points` (više kladionica, najbolja kvota na istoj liniji) + `totals` | offer korak | PLAYER, PLAYER_TEAM, OPP_TEAM, LINE, OVER_ODDS, UNDER_ODDS, TOTAL_MATCH |
| `players_2025-26*.csv`, `teams_2025-26.csv` | isti izvori, prošla sezona | ne mijenja se | dopuna rane sezone: do 20 odigranih utakmica statistika se miješa s prošlom sezonom (`prior.py`) |

Ponuda i raspored su „danas“; sve sa NBA Stats je stanje poslije sinoćnjih mečeva. ESPN raspored (danas + 6 dana
unazad) se povlači pri svakoj analizi.

## 3. Šta se računa iz čega (lanac)

1. **Minute**: sezonski prosjek MIN, dopunjen L10_MIN (težina do 0,60), pa korekcije za tempo, razliku snage timova,
   status ozljede samog igrača i minute ozlijeđenih saigrača; ograničeno na 8–40 i na +2 % do +10 % iznad osnove.
2. **Osnovna projekcija**: PPM × minute, usidrena na sezonski prosjek poena (težina po usage-u 0,12–0,40) i
   ograničena na 70–130 % sezonskog prosjeka.
3. **Odbrana protivnika**: faktor iz DEF_RATING tima i prosječnog dozvoljenog FG% za dvojke (0,85–1,20).
4. **Forma**: L3/L5/L10 (težina 0,58–0,88 prema odstupanju od sezone), trend, pa „auto recent form“ iz L5 (0,10–0,18).
5. **H2H**: prosjek protiv tog protivnika kad ima bar 2 meča (težina 0,25–0,55, smanjena kad H2H odskače).
6. **18 multiplikativnih faktora** sa težinama (tim vs protivnik, total meča, usage, ozljede, šut, slobodna bacanja,
   efikasnost, kreacija, izgubljene lopte, uloga, stil, odbrana šuta protivnika, stil protivnika, B2B, domaćin/gost,
   odmor, odmor protivnika), zajedno ograničeni na 0,88–1,12.
7. **Sigma**: koeficijent varijacije po usage-u, dopunjen stvarnim L10_STD (težina do 0,50), ograničen linijom.
8. **Kalibracija prema kladionici**: od projekcije se oduzima procijenjeni „offset“ kladionice po igraču, miješa se
   s linijom (25–55 %) i ograničava najveće odstupanje (2–8,5 poena).
9. **Monte Carlo** 5.000 normalnih simulacija (sjeme 42) → P(over), P(under), EV (gornja granica +35 %), True Score
   (0,5 EV + 0,3 edge + 0,2 pogodak), kazna za koncentraciju na jedan tim.

Svaki od ovih koraka ima svoju kolonu u punom portfoliju (74 kolone), pa se može pratiti kako je nastao svaki broj.

## 4. Provjera na današnjoj analizi (brojke)

- Igrača iz ponude nađeno u bazi: **42 od 42** (41 tačno po imenu, 1 po dijelovima imena: RJ Barrett → ispravno).
- Kolone koje model traži a nema ih u bazi igrača: **nijedna**. NaN u korišćenim kolonama: **nijedan**.
- Rezervna vrijednost PPM = 0,55 (kad igrač nema minute): **0 igrača**.
- Timovi: 30 redova, PACE/OFF/DEF/NET bez praznina.
- Forma L10: pokriva **42 od 42**; odigranih utakmica po igraču 4–6 (rana sezona).
- H2H: pokriva **37 od 42** parova; preostalih 5 ide bez H2H (težina 0).
- Odbrambeni matchup: svih 30 timova; faktor rekonstruisan ručno za TOR, BKN i GSW i poklapa se s analizom
  (1,039 / 1,078 / 1,102).
- Ozljede: 88 redova (70 OUT, 18 QUESTIONABLE), svaki s timom; 1 igrač iz ponude isključen kao OUT.
- Raspored: 4 meča, svi parovi iz ponude su današnji; domaćin/gost za 8 timova; nijedan B2B; svi timovi 1 dan
  odmora (nijedan nije igrao u subotu, provjereno) → Rest Factor 0,98 za 10 igrača s usage-om ≥ 25.
- Total meča: iz ponude (The Odds API totals) za sva 4 meča; procjena modela se vidi u koloni TOTAL_MATCH_MODEL,
  ali se koristi samo kad ponuda nema total.
- Prošla sezona: prosječna težina 0,69 (4–6 odigranih utakmica); 2 igrača bez prošle sezone (Keaton Wagler,
  Yaxel Lendeborg) idu samo na tekuću.
- Ledger evaluacije je prazan: prvo poravnanje sutra u 18:00.

## 5. Podrazumijevane vrijednosti i kad se aktiviraju

Model ima rezervne vrijednosti za slučaj da podatak nedostaje (naslijeđeno iz originala): ligaški prosjeci
(PACE 99, OFF/DEF 115, TS 0,56, EFG 0,54, USG 20), po igraču (FG% 0,46, FT% 0,76, 3P% 0,36, PIE 0,08, AST_RATIO 15,
AST_TO 1,5, TOV% 12, FG3A/min 0,12, GP 20), odmor 2 dana i domaćin kad ESPN nije dostupan, usage 20 kad nedostaje.
Danas se **nijedna** nije aktivirala za igrače; ligaški prosjeci se računaju iz stvarne tabele (rezerva se ne koristi).

Konstante u formulama (težine, granice, 5 % offset kladionice, 25–55 % miješanja s linijom) nisu podaci nego
parametri modela iz originalnog app.py. Nisu mijenjane. Da li su dobre, pokazaće tek evaluacija kroz `settle`.

## 6. Šta model koristi slabije nego što podaci dozvoljavaju (naslijeđeno, nije mijenjano)

1. **`def_matchup`** ima po braniocu i po 4 kategorije odbrane (Overall, 2 Pointers, 3 Pointers, Less Than 6Ft)
   kolone D_FG_PCT, NORMAL_FG_PCT, PCT_PLUSMINUS, FG2_PCT, FG3_PCT, LT_06_PCT i poziciju branioca. Model:
   - prvi blok traži kolone OPP_PTS/PTS/FREQ_PTS kojih u ovom fajlu nema → pada na DEF_RATING tima;
   - drugi blok traži poziciju, ali loader pretvara tekstualne kolone (PLAYER_POSITION, DEFENSE_CATEGORY) u brojeve
     (NaN), pa blok po poziciji nikad ne radi → koristi se prosjek FG2_PCT po timu (samo redovi „2 Pointers“);
   - korekcija „odbrana šuta protivnika“ traži OPP_FG_PCT/OPP_FG3_PCT kojih nema → uvijek 1,0.
   Rezultat je tačan i stvaran, ali gruba mjera: najbolje odbrambene informacije iz fajla (ukupni dozvoljeni FG%,
   odbrana trojke, odbrana blizu koša, po poziciji) ostaju neiskorišćene.
2. **`off_matchup`** se učitava i ne koristi (tako je bilo i u originalu).
3. **Kolona „H2H PTS Avg“** u portfoliju pokazuje sezonski prosjek kad H2H ne postoji (6 redova danas). U račun ne
   ulazi (težina 0), ali može zbuniti pri čitanju; „H2H Games“ je tada prazno.
4. **Rana sezona**: L10/L5/L3 i L10_STD su iz 4–6 utakmica; model ih uzima po pravilima za 10 utakmica (težine se
   skaliraju brojem utakmica samo za minute i sigmu). Dopuna prošlom sezonom ublažava statistiku, ali ne i formu.

Nijedna od ovih tačaka nije greška u podacima ni fiktivna vrijednost; to su mjesta gdje bi model mogao koristiti više
od onoga što već ima. Promjena bi bila nova poslovna logika i ide samo na odluku korisnika, poslije mjerenja.

## 7. Gdje postoje izmišljeni podaci (i zašto ne smetaju)

- `tests/fixtures/legacy_offer_2026-03.csv` i `legacy_full_portfolio.csv`: stvarna martovska ponuda i zlatni izlaz
  starog app.py, služe samo testu regresije.
- `tests/test_*.py`: mali izmišljeni primjeri (3–4 igrača) za provjeru formula; nikad se ne učitavaju u aplikaciju.
- `history/_probne_analize_2026-10/`: analize stare ponude iz testiranja; `settle` ih ne vidi (poseban folder).
- `archive/`: stari kod, ne pokreće se.
- `data/dnevna_ponuda.csv`: kopija `offer_latest.csv` radi starih skripti; isti sadržaj.
