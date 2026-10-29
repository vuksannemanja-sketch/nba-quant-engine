# Arhiva — stari kod (ne koristi se u aplikaciji)

Ovdje je sačuvan sav raniji kod da se ništa ne izgubi. Aplikacija ga **ne učitava**.

## `legacy-root-scripts/`
Skripte koje su do refaktora (oktobar 2026) stajale u korijenu repoa:

| fajl | napomena |
|---|---|
| `app_legacy_2026-04.py` | originalni `app.py` (2530 redova) prije razdvajanja u paket `nba_engine/` |
| `fetch_dnevna_ponuda_multi.py`, `fetch_daily_offer.py` | dnevna ponuda sa The Odds API → sada `nba_engine/odds_api.py` |
| `fetch_todays_games.py` | verzija koju je pokretao GitHub robot (ključ upisan u kodu!) |
| `refresh_data.py` | statistika igrača → sada `nba_engine/refresh/players.py` |
| `refresh_h2h.py`, `refresh_injuries.py`, `refresh_matchups.py` | **polomljene** (pogrešno uvlačenje) verzije iz git istorije; ispravne su u `vscode-history/` |

## `vscode-history/`
Najnovije verzije fajlova pronađene u lokalnoj istoriji VS Code-a
(`~/Library/Application Support/Code/User/History`, februar–april 2026). Među njima su skripte koje
su nekad postojale u `~/Desktop/NBA_ENGINE`, a nisu bile u gitu:

- `refresh_all.py`, `refresh_daily.py`, `refresh_props.py`, `refresh_schedule.py`, `refresh_bref.py`
  i ispravne verzije `refresh_h2h.py`, `refresh_injuries.py`, `refresh_matchups.py`, `refresh_data.py`
  — upravo one su napravile CSV fajlove u `data/`; njihova logika je prenesena u `nba_engine/refresh/`.
- `refresh_daily.py` (1145 redova) nije prenesen: koristi parametre `nba_api` biblioteke koji više ne postoje
  (`measure_type_simple`, `per_mode_simple`) i piše `def_matchup` u drugačijem formatu od ostalih skripti.
- `filters.py` (april 2026): crna lista igrača i filteri pickova na osnovu analize 885 pickova — nije bio
  povezan sa `app.py`, pa nije ni ovdje; ostaje kao ideja za posebnu odluku.
- `*_engine.py`, `engine.py`, `data_loader*.py` (februar 2026): starija arhitektura modela (V3), zamijenjena
  jednim `app.py` u martu.
- `patch_*.py`: jednokratne skripte koje su mijenjale `app.py` (već primijenjene).
