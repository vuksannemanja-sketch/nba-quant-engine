#!/usr/bin/env python3
"""
refresh_daily.py — Auto Daily NBA Data Refresh
================================================
Pokreni ručno:  python refresh_daily.py
Ili iz app.py:  import refresh_daily; refresh_daily.run(log_fn=st.write)

Šta radi:
  1. ScoreboardV2  → Dohvata mečeve za DANAS
  2. CommonTeamRoster → Rosteri za timove koji igraju
  3. LeagueDashPlayerStats (Base / Advanced / Misc, last_n_games=10/5)
     → filtrira na igrače iz današnjih mečeva
  4. LeagueDashTeamStats → statistike timova
  5. ESPN Injuries API → povlači ozljede
  6. Izračunava L10/L5/trend formu
  7. Gradi def_matchup / off_matchup tablice
  8. Sve piše u data/ folder (merge s postojećim — bez duplikata)

Dependency-i:
  pip install nba_api requests pandas numpy
"""

import os, sys, time, datetime, traceback
import json, math
import requests
import pandas as pd
import numpy as np

# ─── CONFIG ───────────────────────────────────────────────────────────────────
SEASON   = "2025-26"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Koliko sekundi čekati između NBA API poziva (rate-limit zaštita)
NBA_SLEEP      = 0.65
NBA_SLEEP_LONG = 1.20   # za roster loop

# ─── TEAM MAPPINGS ────────────────────────────────────────────────────────────
TEAM_ID_TO_ABBR = {
    1610612737: "ATL", 1610612738: "BOS", 1610612751: "BKN", 1610612766: "CHA",
    1610612741: "CHI", 1610612739: "CLE", 1610612742: "DAL", 1610612743: "DEN",
    1610612765: "DET", 1610612744: "GSW", 1610612745: "HOU", 1610612754: "IND",
    1610612746: "LAC", 1610612747: "LAL", 1610612763: "MEM", 1610612748: "MIA",
    1610612749: "MIL", 1610612750: "MIN", 1610612740: "NOP", 1610612752: "NYK",
    1610612753: "ORL", 1610612755: "PHI", 1610612756: "PHX", 1610612757: "POR",
    1610612758: "SAC", 1610612759: "SAS", 1610612760: "OKC", 1610612761: "TOR",
    1610612762: "UTA", 1610612764: "WAS",
}
ABBR_TO_TEAM_ID = {v: k for k, v in TEAM_ID_TO_ABBR.items()}

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def _log(msg, log_fn=None):
    if log_fn:
        log_fn(msg)
    else:
        print(msg, flush=True)

def _sleep(s=NBA_SLEEP):
    time.sleep(s)

def _safe_read_csv(path):
    """Čita CSV ako postoji, inače vraća prazan DataFrame."""
    if path and os.path.exists(path):
        try:
            return pd.read_csv(path)
        except Exception:
            pass
    return pd.DataFrame()

def _merge_and_save(new_df: pd.DataFrame, path: str, key_col: str = "PLAYER_ID"):
    """
    Merge novih podataka s postojećim CSV-om.
    Duplikati se eliminišu po key_col (nova verzija pobijedi).
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = _safe_read_csv(path)

    if existing.empty or key_col not in existing.columns or key_col not in new_df.columns:
        new_df.to_csv(path, index=False)
        return len(new_df)

    # Ukloni stare zapise koji postoje u novim podacima
    old_keys = existing[key_col].astype(str)
    new_keys = new_df[key_col].astype(str)
    kept_old = existing[~old_keys.isin(new_keys)]

    merged = pd.concat([kept_old, new_df], ignore_index=True)
    merged.to_csv(path, index=False)
    return len(merged)

def _nba_endpoint(cls, **kwargs):
    """Wraps NBA API call s retry logikom."""
    for attempt in range(3):
        try:
            return cls(**kwargs)
        except Exception as e:
            if attempt < 2:
                time.sleep(2 + attempt * 2)
            else:
                raise e

# ─── STEP 1: TODAY'S GAMES ───────────────────────────────────────────────────
def _parse_games_df(games_df: pd.DataFrame) -> pd.DataFrame:
    """Standardizira kolone game_header DataFrame-a."""
    col_map = {}
    for c in games_df.columns:
        cu = c.strip().upper()
        if cu == "HOME_TEAM_ID" or "HOME_TEAM_ID" in cu:
            col_map[c] = "HOME_TEAM_ID"
        elif cu in ("VISITOR_TEAM_ID", "AWAY_TEAM_ID") or "VISITOR_TEAM_ID" in cu or "AWAY_TEAM_ID" in cu:
            col_map[c] = "VISITOR_TEAM_ID"
        elif cu == "GAME_ID" or cu.endswith("GAME_ID"):
            col_map[c] = "GAME_ID"
    games_df = games_df.rename(columns=col_map)
    for col in ["GAME_ID", "HOME_TEAM_ID", "VISITOR_TEAM_ID"]:
        if col not in games_df.columns:
            games_df[col] = None
    return games_df[["GAME_ID", "HOME_TEAM_ID", "VISITOR_TEAM_ID"]].copy()


def _extract_team_ids(games_df: pd.DataFrame) -> set:
    team_ids = set()
    for _, row in games_df.iterrows():
        for col in ["HOME_TEAM_ID", "VISITOR_TEAM_ID"]:
            tid = row.get(col)
            if tid is not None and not pd.isna(tid):
                try:
                    team_ids.add(int(tid))
                except (ValueError, TypeError):
                    pass
    return team_ids


def _fetch_games_scoreboard(date_str: str, log_fn=None) -> pd.DataFrame:
    """ScoreboardV2 — primarni izvor."""
    from nba_api.stats.endpoints import ScoreboardV2
    sb = _nba_endpoint(ScoreboardV2, game_date=date_str)
    return sb.game_header.get_data_frame()


def _fetch_games_leaguegamefinder(date_str: str, log_fn=None) -> pd.DataFrame:
    """
    LeagueGameFinder — sekundarni izvor.
    Vraća sve igre za određeni datum iz LeagueGameFinder endpointa.
    date_str format: MM/DD/YYYY
    """
    from nba_api.stats.endpoints import LeagueGameFinder
    # LeagueGameFinder prima date u YYYY-MM-DD formatu
    dt = datetime.datetime.strptime(date_str, "%m/%d/%Y")
    date_iso = dt.strftime("%Y-%m-%d")

    gf = _nba_endpoint(
        LeagueGameFinder,
        date_from_nullable=date_iso,
        date_to_nullable=date_iso,
        league_id_nullable="00",
        season_type_nullable="Regular Season",
    )
    df = gf.league_game_finder_stats.get_data_frame()
    if df.empty:
        return pd.DataFrame()

    # LeagueGameFinder vraća jedan red po timu po igri — dedupliraj na GAME_ID razini
    ren = {}
    for c in df.columns:
        cu = c.strip().upper()
        if cu == "GAME_ID":   ren[c] = "GAME_ID"
        elif cu == "TEAM_ID": ren[c] = "TEAM_ID"
    df = df.rename(columns=ren)

    if "GAME_ID" not in df.columns or "TEAM_ID" not in df.columns:
        return pd.DataFrame()

    # Grupiraj po GAME_ID i izvuci HOME i VISITOR team
    rows = []
    for game_id, grp in df.groupby("GAME_ID"):
        team_list = grp["TEAM_ID"].dropna().astype(int).tolist()
        if len(team_list) >= 2:
            rows.append({
                "GAME_ID":         str(game_id),
                "HOME_TEAM_ID":    team_list[0],
                "VISITOR_TEAM_ID": team_list[1],
            })
        elif len(team_list) == 1:
            rows.append({
                "GAME_ID":         str(game_id),
                "HOME_TEAM_ID":    team_list[0],
                "VISITOR_TEAM_ID": None,
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _fetch_games_espn(date_str: str, log_fn=None) -> pd.DataFrame:
    """
    ESPN scoreboard API — tercijarni izvor, nema rate-limit.
    Vraća timove koji igraju na određeni datum.
    date_str format: MM/DD/YYYY → ESPN treba YYYYMMDD
    """
    try:
        dt = datetime.datetime.strptime(date_str, "%m/%d/%Y")
        espn_date = dt.strftime("%Y%m%d")
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={espn_date}"
        resp = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()

        rows = []
        for event in data.get("events", []):
            game_id = event.get("id", "")
            competitors = event.get("competitions", [{}])[0].get("competitors", [])
            home_tid, away_tid = None, None
            for comp in competitors:
                espn_team_id = comp.get("team", {}).get("id", "")
                abbr = comp.get("team", {}).get("abbreviation", "").upper()
                # Mapiramo ESPN team abbr → naš TEAM_ID
                nba_tid = ABBR_TO_TEAM_ID.get(abbr)
                if nba_tid is None:
                    continue
                if comp.get("homeAway", "") == "home":
                    home_tid = nba_tid
                else:
                    away_tid = nba_tid
            if home_tid or away_tid:
                rows.append({
                    "GAME_ID":         game_id,
                    "HOME_TEAM_ID":    home_tid,
                    "VISITOR_TEAM_ID": away_tid,
                })
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except Exception as e:
        _log(f"  ⚠️  ESPN scoreboard error: {e}", log_fn)
        return pd.DataFrame()


def fetch_todays_games(log_fn=None):
    """
    Vraća (team_ids_set, games_df) za danas.
    games_df kolone: GAME_ID, HOME_TEAM_ID, VISITOR_TEAM_ID

    Strategija — 4 datuma × 3 izvora:
      1. Danas (ET) via ScoreboardV2
      2. Sutra (ET) via ScoreboardV2 — hvatamo kasne igre koje su "sutra" u ET
      3. LeagueGameFinder za danas — neovisni endpoint, drugačiji cache
      4. ESPN Scoreboard — bez rate-limita, pouzdan fallback

    Sve igre se deduplikuju po GAME_ID (ili po paru team_ids).
    """
    # NBA radi u ET — ako smo >5h ispred ET, "danas" u ET = naš jučer
    # Sigurnost: provjeravamo i danas i ±1 dan
    utc_now    = datetime.datetime.utcnow()
    et_offset  = datetime.timedelta(hours=5)   # ET = UTC-5 (zimsko), UTC-4 (ljetno)
    et_now     = utc_now - et_offset
    et_today   = et_now.date()
    et_tomorrow = et_today + datetime.timedelta(days=1)

    dates_to_check = [
        et_today.strftime("%m/%d/%Y"),
        et_tomorrow.strftime("%m/%d/%Y"),
    ]

    all_games: list[dict] = []
    seen_game_ids: set = set()
    seen_team_pairs: set = set()

    def _add_games(df: pd.DataFrame, source: str):
        if df.empty:
            return 0
        df = _parse_games_df(df)
        added = 0
        for _, row in df.iterrows():
            gid  = str(row.get("GAME_ID", "")).strip()
            htid = row.get("HOME_TEAM_ID")
            vtid = row.get("VISITOR_TEAM_ID")

            try:
                htid = int(htid) if htid is not None and not pd.isna(htid) else None
                vtid = int(vtid) if vtid is not None and not pd.isna(vtid) else None
            except (ValueError, TypeError):
                htid = vtid = None

            # Deduplikacija po GAME_ID
            if gid and gid in seen_game_ids:
                continue
            # Deduplikacija po paru timova (ako GAME_ID nedostaje)
            pair = tuple(sorted(filter(None, [htid, vtid])))
            if pair and pair in seen_team_pairs:
                continue

            if gid:
                seen_game_ids.add(gid)
            if pair:
                seen_team_pairs.add(pair)

            all_games.append({
                "GAME_ID":         gid,
                "HOME_TEAM_ID":    htid,
                "VISITOR_TEAM_ID": vtid,
                "_SOURCE":         source,
            })
            added += 1
        return added

    # ── Izvor 1: ScoreboardV2 za danas i sutra (ET) ───────────────────────────
    for date_str in dates_to_check:
        _log(f"📅 ScoreboardV2 → {date_str} (ET)...", log_fn)
        try:
            raw = _fetch_games_scoreboard(date_str, log_fn)
            n   = _add_games(raw, f"ScoreboardV2/{date_str}")
            _log(f"   +{n} igara", log_fn)
            _sleep(0.5)
        except Exception as e:
            _log(f"  ⚠️  ScoreboardV2 greška za {date_str}: {e}", log_fn)

    # ── Izvor 2: LeagueGameFinder za danas (ET) ───────────────────────────────
    _log(f"📅 LeagueGameFinder → {dates_to_check[0]}...", log_fn)
    try:
        raw = _fetch_games_leaguegamefinder(dates_to_check[0], log_fn)
        n   = _add_games(raw, "LeagueGameFinder")
        _log(f"   +{n} novih igara", log_fn)
        _sleep(0.8)
    except Exception as e:
        _log(f"  ⚠️  LeagueGameFinder greška: {e}", log_fn)

    # ── Izvor 3: ESPN Scoreboard (bez rate-limita) ────────────────────────────
    for date_str in dates_to_check:
        _log(f"📅 ESPN Scoreboard → {date_str}...", log_fn)
        try:
            raw = _fetch_games_espn(date_str, log_fn)
            n   = _add_games(raw, f"ESPN/{date_str}")
            _log(f"   +{n} novih igara", log_fn)
        except Exception as e:
            _log(f"  ⚠️  ESPN greška za {date_str}: {e}", log_fn)

    if not all_games:
        _log("⚠️  Nema pronađenih NBA igara za danas.", log_fn)
        return set(), pd.DataFrame()

    games_df = pd.DataFrame(all_games)

    # Izvuci team_ids (ukloni None)
    team_ids: set = set()
    for _, row in games_df.iterrows():
        for col in ["HOME_TEAM_ID", "VISITOR_TEAM_ID"]:
            tid = row.get(col)
            if tid is not None:
                try:
                    team_ids.add(int(tid))
                except (ValueError, TypeError):
                    pass

    # Filtriraj samo poznate NBA team ID-ove
    team_ids = {t for t in team_ids if t in TEAM_ID_TO_ABBR}

    abbrs = sorted([TEAM_ID_TO_ABBR.get(t, str(t)) for t in team_ids])
    _log(f"✅ Ukupno pronađeno: {len(games_df)} igara, {len(team_ids)} timova", log_fn)
    _log(f"   Timovi: {', '.join(abbrs)}", log_fn)

    # Debug: prikaži igre po izvoru
    source_counts = games_df["_SOURCE"].value_counts().to_dict()
    for src, cnt in source_counts.items():
        _log(f"   [{src}]: {cnt} igara", log_fn)

    return team_ids, games_df[["GAME_ID", "HOME_TEAM_ID", "VISITOR_TEAM_ID"]]

# ─── STEP 2: ROSTERS ─────────────────────────────────────────────────────────
def fetch_rosters(team_ids: set, log_fn=None):
    """
    Vraća set player_ids i DataFrame s PLAYER_ID, PLAYER_NAME, TEAM_ID, TEAM_ABBR.
    """
    from nba_api.stats.endpoints import CommonTeamRoster

    all_rows = []
    for i, tid in enumerate(sorted(team_ids)):
        abbr = TEAM_ID_TO_ABBR.get(int(tid), str(tid))
        _log(f"  Roster [{i+1}/{len(team_ids)}] {abbr}...", log_fn)
        try:
            r = _nba_endpoint(CommonTeamRoster, team_id=tid, season=SEASON)
            df = r.common_team_roster.get_data_frame()
            df["TEAM_ID"]   = int(tid)
            df["TEAM_ABBR"] = abbr
            all_rows.append(df)
        except Exception as e:
            _log(f"  ⚠️  Roster error for {abbr}: {e}", log_fn)
        _sleep(NBA_SLEEP_LONG)

    if not all_rows:
        return set(), pd.DataFrame()

    combined = pd.concat(all_rows, ignore_index=True)

    # Normalizacija player ID kolone
    pid_col = next((c for c in combined.columns if "PLAYER_ID" in c.upper()), None)
    pname_col = next((c for c in combined.columns if "PLAYER" in c.upper() and "NAME" in c.upper()), None)
    if pid_col and pid_col != "PLAYER_ID":
        combined = combined.rename(columns={pid_col: "PLAYER_ID"})
    if pname_col and pname_col != "PLAYER_NAME":
        combined = combined.rename(columns={pname_col: "PLAYER_NAME"})

    player_ids = set(combined["PLAYER_ID"].dropna().astype(int).tolist())
    _log(f"✅ Total players in today's rosters: {len(player_ids)}", log_fn)

    # Sigurno uzmi kolone koje stvarno postoje
    keep_cols = ["PLAYER_ID", "TEAM_ID", "TEAM_ABBR"]
    if "PLAYER_NAME" in combined.columns:
        keep_cols.insert(1, "PLAYER_NAME")
    else:
        combined["PLAYER_NAME"] = combined.get("PLAYER", combined.get("NAME", ""))
        keep_cols.insert(1, "PLAYER_NAME")

    return player_ids, combined[keep_cols].copy()

# ─── STEP 3: PLAYER STATS (Base / Advanced / Misc) ───────────────────────────
def _fetch_dash_player(measure_type: str, last_n: int = 0, log_fn=None) -> pd.DataFrame:
    """
    Generički wrapper za LeagueDashPlayerStats.
    last_n=0 → sezonski kumulativ, last_n=10 → zadnjih 10 utakmica
    """
    from nba_api.stats.endpoints import LeagueDashPlayerStats

    kwargs = dict(
        season            = SEASON,
        per_mode_simple   = "PerGame",
        measure_type_simple = measure_type,
    )
    if last_n > 0:
        kwargs["last_n_games"] = last_n

    _log(f"  📊 LeagueDashPlayerStats({measure_type}, last_n={last_n})...", log_fn)
    ep = _nba_endpoint(LeagueDashPlayerStats, **kwargs)
    df = ep.league_dash_player_stats.get_data_frame()
    _sleep()
    return df

def fetch_player_stats_all(player_ids: set, log_fn=None):
    """
    Dohvata Base / Advanced / Misc statistike za cijelu sezonu
    i filtrira na player_ids.
    Vraća (base_df, adv_df, misc_df, main_df)
    """
    _log("📥 Fetching season stats (Base, Advanced, Misc)...", log_fn)

    base = _fetch_dash_player("Base",     log_fn=log_fn)
    adv  = _fetch_dash_player("Advanced", log_fn=log_fn)
    misc = _fetch_dash_player("Misc",     log_fn=log_fn)

    def _filter_and_rename(df: pd.DataFrame, label: str) -> pd.DataFrame:
        if df.empty:
            return df
        # Standardizacija kolona — broadni search po substring
        ren = {}
        for c in df.columns:
            cu = c.strip().upper()
            # PLAYER_ID — tačno ili sadrži "PLAYER_ID"
            if cu == "PLAYER_ID" or cu == "PLAYERID":
                ren[c] = "PLAYER_ID"
            # PLAYER_NAME — tačno, ili sadrži i PLAYER i NAME
            elif cu == "PLAYER_NAME" or cu == "PLAYERNAME":
                ren[c] = "PLAYER_NAME"
            elif "PLAYER" in cu and "NAME" in cu:
                ren[c] = "PLAYER_NAME"
            elif cu in ("TEAM_ABBREVIATION", "TEAM_ABBR", "TEAMABBR"):
                ren[c] = "TEAM_ABBR"
            elif cu == "TEAM_ID" or cu == "TEAMID":
                ren[c] = "TEAM_ID"
        df = df.rename(columns=ren)

        # Fallback: ako PLAYER_NAME ne postoji, potraži "NAME" ili "PLAYER"
        if "PLAYER_NAME" not in df.columns:
            for c in df.columns:
                cu = c.strip().upper()
                if cu in ("NAME", "FULL_NAME", "FULLNAME"):
                    df = df.rename(columns={c: "PLAYER_NAME"})
                    break
            else:
                # Zadnji fallback: napravi praznu kolonu da ostali kod ne puca
                df["PLAYER_NAME"] = ""

        # Osiguraj PLAYER_ID postoji
        if "PLAYER_ID" not in df.columns:
            for c in df.columns:
                if "ID" in c.strip().upper() and "PLAYER" in c.strip().upper():
                    df = df.rename(columns={c: "PLAYER_ID"})
                    break

        # Filter na igrače koji igraju danas
        if "PLAYER_ID" in df.columns and player_ids:
            df = df[df["PLAYER_ID"].isin(player_ids)].copy()
        df["_SRC"] = label
        return df

    base = _filter_and_rename(base, "BASE")
    adv  = _filter_and_rename(adv,  "ADV")
    misc = _filter_and_rename(misc, "MISC")

    # Main = Base + ključne kolone iz ADV
    main = base.copy()
    adv_extra_cols = [c for c in [
        "PLAYER_ID", "USG_PCT", "TS_PCT", "EFG_PCT", "OFF_RATING", "DEF_RATING",
        "NET_RATING", "PACE", "PIE", "AST_PCT", "AST_RATIO", "AST_TO",
        "TOV_PCT", "OREB_PCT", "DREB_PCT", "REB_PCT",
    ] if c in adv.columns]
    if adv_extra_cols and "PLAYER_ID" in main.columns:
        main = main.merge(adv[adv_extra_cols].drop_duplicates("PLAYER_ID"),
                          on="PLAYER_ID", how="left", suffixes=("", "_adv"))
        # Ukloni duplikate sufiksa
        for col in list(main.columns):
            if col.endswith("_adv"):
                base_col = col[:-4]
                if base_col in main.columns:
                    main[base_col] = main[base_col].combine_first(main[col])
                    main.drop(columns=[col], inplace=True)
                else:
                    main.rename(columns={col: base_col}, inplace=True)

    # USG normalizacija (ako je u decimalnom obliku)
    for df_ref in [main, adv, misc]:
        if "USG_PCT" in df_ref.columns:
            mean_u = pd.to_numeric(df_ref["USG_PCT"], errors="coerce").dropna().mean()
            if pd.notna(mean_u) and mean_u < 2.0:
                df_ref["USG_PCT"] = pd.to_numeric(df_ref["USG_PCT"], errors="coerce") * 100.0

    _log(f"✅ Player stats: base={len(base)}, adv={len(adv)}, misc={len(misc)}, main={len(main)}", log_fn)
    return base, adv, misc, main

# ─── STEP 4: L10 / L5 FORMA ──────────────────────────────────────────────────
def fetch_l10_form(player_ids: set, log_fn=None) -> pd.DataFrame:
    """
    Koristi LeagueDashPlayerStats s last_n_games=10 i 5.
    Izračunava L10_PTS, L5_PTS, L10_MIN, L10_STD, TREND_SLOPE.
    """
    _log("📈 Fetching L10/L5 form...", log_fn)

    l10 = _fetch_dash_player("Base", last_n=10, log_fn=log_fn)
    _sleep()
    l5  = _fetch_dash_player("Base", last_n=5,  log_fn=log_fn)
    _sleep()
    l3  = _fetch_dash_player("Base", last_n=3,  log_fn=log_fn)

    def _prep(df: pd.DataFrame, suffix: str) -> pd.DataFrame:
        if df.empty:
            return df
        ren = {}
        for c in df.columns:
            cu = c.strip().upper()
            if cu in ("PLAYER_ID", "PLAYERID"):
                ren[c] = "PLAYER_ID"
            elif cu in ("PLAYER_NAME", "PLAYERNAME") or ("PLAYER" in cu and "NAME" in cu):
                ren[c] = "PLAYER_NAME"
            elif cu in ("TEAM_ABBREVIATION", "TEAM_ABBR"):
                ren[c] = "TEAM_ABBR"
        df = df.rename(columns=ren)

        # Fallback: ako PLAYER_NAME ne postoji
        if "PLAYER_NAME" not in df.columns:
            for c in df.columns:
                if c.strip().upper() in ("NAME", "FULL_NAME"):
                    df = df.rename(columns={c: "PLAYER_NAME"})
                    break
            else:
                df["PLAYER_NAME"] = ""

        if "PLAYER_ID" not in df.columns:
            return pd.DataFrame()  # bez ID-a nema smisla

        if player_ids:  # None = svi igrači u ligi, set() = filter na subset
            df = df[df["PLAYER_ID"].isin(player_ids)].copy()

        pts_col = "PTS" if "PTS" in df.columns else None
        min_col = "MIN" if "MIN" in df.columns else None

        result = df[["PLAYER_ID", "PLAYER_NAME"]].copy()
        if pts_col:
            result[f"{suffix}_PTS"] = pd.to_numeric(df[pts_col], errors="coerce")
        if min_col:
            result[f"{suffix}_MIN"] = pd.to_numeric(df[min_col], errors="coerce")
        return result

    l10p = _prep(l10, "L10")
    l5p  = _prep(l5,  "L5")
    l3p  = _prep(l3,  "L3")

    # Merge
    form = l10p.copy()
    for extra in [l5p, l3p]:
        if extra.empty:
            continue
        merge_cols = ["PLAYER_ID"] + [c for c in extra.columns if c not in form.columns and c != "PLAYER_ID"]
        form = form.merge(extra[["PLAYER_ID"] + [c for c in extra.columns if c not in ["PLAYER_ID", "PLAYER_NAME"]]],
                          on="PLAYER_ID", how="left")

    # L10_STD: devijacija (L3 vs L5 vs L10 razlika kao proxy)
    if "L10_PTS" in form.columns and "L5_PTS" in form.columns and "L3_PTS" in form.columns:
        form["L10_STD"] = (
            (form["L10_PTS"] - form["L5_PTS"]).abs() * 0.5 +
            (form["L5_PTS"]  - form["L3_PTS"]).abs() * 0.5
        ).round(2)
        # TREND_SLOPE: pozitivan ako L3 > L5 > L10, negativan obratno
        l10_safe = form["L10_PTS"].fillna(0)
        l5_safe  = form["L5_PTS"].fillna(l10_safe)
        l3_safe  = form["L3_PTS"].fillna(l5_safe)
        form["TREND_SLOPE"] = ((l3_safe - l5_safe) * 0.6 + (l5_safe - l10_safe) * 0.4).round(3)

    # L10_PTS se rename-uje jer smo radili _prep
    rename_final = {}
    if "L10_PTS" not in form.columns and "L10_PTS_PTS" in form.columns:
        rename_final["L10_PTS_PTS"] = "L10_PTS"
    form = form.rename(columns=rename_final)

    _log(f"✅ L10 form built for {len(form)} players", log_fn)
    return form

# ─── STEP 5: TEAM STATS ───────────────────────────────────────────────────────
def fetch_team_stats(team_ids: set, log_fn=None):
    """
    Vraća teams_df s: TEAM_ID, TEAM_ABBR, OFF_RATING, DEF_RATING, NET_RATING, PACE, PTS, OPP_PTS
    i def_matchup_df, off_matchup_df.
    """
    from nba_api.stats.endpoints import LeagueDashTeamStats

    _log("🏀 Fetching team stats (Base + Advanced)...", log_fn)

    def _fetch_team(measure: str) -> pd.DataFrame:
        ep = _nba_endpoint(LeagueDashTeamStats,
                           season=SEASON,
                           per_mode_simple="PerGame",
                           measure_type_simple=measure)
        df = ep.league_dash_team_stats.get_data_frame()
        _sleep()
        return df

    base_t = _fetch_team("Base")
    adv_t  = _fetch_team("Advanced")
    opp_t  = _fetch_team("Opponent")   # OPP statistike

    def _std_team(df: pd.DataFrame) -> pd.DataFrame:
        ren = {}
        for c in df.columns:
            cu = c.upper()
            if cu == "TEAM_ID":                                  ren[c] = "TEAM_ID"
            elif cu in ("TEAM_ABBREVIATION","TEAM_ABBR"):       ren[c] = "TEAM_ABBR"
            elif cu == "TEAM_NAME":                              ren[c] = "TEAM_NAME"
        return df.rename(columns=ren)

    base_t = _std_team(base_t)
    adv_t  = _std_team(adv_t)
    opp_t  = _std_team(opp_t)

    # Merge base + adv
    teams = base_t.copy()
    adv_cols = ["TEAM_ID"] + [c for c in [
        "OFF_RATING","DEF_RATING","NET_RATING","PACE","PIE",
        "AST_PCT","AST_RATIO","TOV_PCT","EFG_PCT","TS_PCT",
    ] if c in adv_t.columns]
    if len(adv_cols) > 1:
        teams = teams.merge(adv_t[adv_cols].drop_duplicates("TEAM_ID"),
                            on="TEAM_ID", how="left", suffixes=("","_adv"))
        for col in list(teams.columns):
            if col.endswith("_adv"):
                bc = col[:-4]
                teams[bc] = teams[bc].combine_first(teams[col]) if bc in teams.columns else teams[col]
                teams.drop(columns=[col], inplace=True)

    # NET_RATING fallback
    if "NET_RATING" not in teams.columns:
        if "OFF_RATING" in teams.columns and "DEF_RATING" in teams.columns:
            teams["NET_RATING"] = teams["OFF_RATING"] - teams["DEF_RATING"]
        elif "PTS" in teams.columns:
            opp_pts = opp_t["PTS"].values if "PTS" in opp_t.columns else None
            if opp_pts is not None:
                teams["OPP_PTS"]   = opp_t.set_index("TEAM_ID")["PTS"].reindex(teams["TEAM_ID"].values).values
                teams["NET_RATING"] = teams["PTS"] - teams["OPP_PTS"]

    # OPP_PTS iz opponent tabele
    if "OPP_PTS" not in teams.columns and "PTS" in opp_t.columns:
        opp_pts_map = opp_t.set_index("TEAM_ID")["PTS"].to_dict()
        teams["OPP_PTS"] = teams["TEAM_ID"].map(opp_pts_map)

    # TEAM_ABBR fallback
    if "TEAM_ABBR" not in teams.columns:
        teams["TEAM_ABBR"] = teams["TEAM_ID"].map(TEAM_ID_TO_ABBR)
    else:
        # Osiguraj da ABBR nije prazan
        missing_mask = teams["TEAM_ABBR"].isna()
        teams.loc[missing_mask, "TEAM_ABBR"] = teams.loc[missing_mask, "TEAM_ID"].map(TEAM_ID_TO_ABBR)

    # Filter na timove koji igraju danas
    if team_ids:
        today_mask = teams["TEAM_ID"].isin(team_ids)
        teams_today = teams[today_mask].copy()
    else:
        teams_today = teams.copy()

    # ── DEF MATCHUP: koliko svaki tim dopušta suprotnoj ekipi ──────────────
    # Koristi OPP tabelu: OPP_PTS je prosječno dopuštenih bodova
    def_matchup = teams_today[["TEAM_ABBR", "TEAM_ID"]].copy()
    for col in ["DEF_RATING", "OPP_PTS"]:
        if col in teams_today.columns:
            def_matchup[col] = teams_today[col].values

    # Iz opponent tabele uzmi FG/3P/FT statistike
    if "TEAM_ID" in opp_t.columns:
        opp_shooting = opp_t.copy()
        if "TEAM_ABBR" not in opp_shooting.columns:
            opp_shooting["TEAM_ABBR"] = opp_shooting["TEAM_ID"].map(TEAM_ID_TO_ABBR)
        for col, new_col in [("FG_PCT","OPP_FG_PCT"),("FG3_PCT","OPP_FG3_PCT"),
                              ("FTA","OPP_FTA"),("PTS","OPP_PTS")]:
            if col in opp_shooting.columns:
                opp_map = opp_shooting.set_index("TEAM_ID")[col].to_dict()
                def_matchup[new_col] = def_matchup["TEAM_ID"].map(opp_map)

    # ── OFF MATCHUP: ofenzivni profil timova ────────────────────────────────
    off_matchup = teams_today[["TEAM_ABBR","TEAM_ID"]].copy()
    for col in ["OFF_RATING","PACE","PTS","NET_RATING"]:
        if col in teams_today.columns:
            off_matchup[col] = teams_today[col].values

    _log(f"✅ Team stats: {len(teams_today)} teams, "
         f"def_matchup={len(def_matchup)}, off_matchup={len(off_matchup)}", log_fn)
    return teams_today, def_matchup, off_matchup

# ─── STEP 6: INJURIES ────────────────────────────────────────────────────────
def fetch_injuries(team_ids: set, log_fn=None) -> pd.DataFrame:
    """
    Pokušava dohvatiti ozljede iz ESPN API-ja.
    Fallback: prazna tablica.
    """
    _log("🏥 Fetching injuries from ESPN...", log_fn)

    try:
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
        resp = requests.get(url, timeout=12,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        _log(f"  ⚠️  ESPN injury fetch failed: {e}", log_fn)
        return pd.DataFrame()

    rows = []
    try:
        for team_entry in data.get("injuries", []):
            team_abbr = team_entry.get("team", {}).get("abbreviation", "")
            for inj in team_entry.get("injuries", []):
                athlete  = inj.get("athlete", {})
                p_name   = athlete.get("fullName", "")
                status   = inj.get("status", "")
                desc     = inj.get("longComment", inj.get("shortComment", ""))
                rows.append({
                    "PLAYER":      p_name,
                    "TEAM_ABBR":   team_abbr.upper(),
                    "STATUS":      _map_espn_status(status),
                    "DESCRIPTION": desc,
                })
    except Exception as e:
        _log(f"  ⚠️  ESPN injury parse error: {e}", log_fn)
        return pd.DataFrame()

    inj_df = pd.DataFrame(rows)

    # Filter na timove koji igraju danas
    if team_ids and not inj_df.empty:
        today_abbrs = {TEAM_ID_TO_ABBR[t] for t in team_ids if t in TEAM_ID_TO_ABBR}
        inj_df = inj_df[inj_df["TEAM_ABBR"].isin(today_abbrs)].copy()

    _log(f"✅ Injuries fetched: {len(inj_df)} records", log_fn)
    return inj_df

def _map_espn_status(s: str) -> str:
    """Mapira ESPN status na naš format."""
    s = (s or "").strip().upper()
    if s in ("OUT", "DOUBTFUL", "QUESTIONABLE", "PROBABLE", "DAY-TO-DAY"):
        return s.replace("DAY-TO-DAY", "QUESTIONABLE")
    if "OUT" in s:       return "OUT"
    if "DOUBT" in s:     return "DOUBTFUL"
    if "QUEST" in s:     return "QUESTIONABLE"
    if "PROB" in s:      return "PROBABLE"
    if "INACTIVE" in s:  return "INACTIVE"
    return "UNKNOWN"

# ─── STEP 7: H2H (player vs specific opponent) ────────────────────────────────
def fetch_h2h_for_today(roster_df: pd.DataFrame, games_df: pd.DataFrame, log_fn=None) -> pd.DataFrame:
    """
    Gradi H2H tablicu: za svakog igrača koji igra danas dohvata
    historiku vs protivničkog tima (PlayerGameLog filtriran na protivnika).
    Ograničeno na max 50 igrača da ne prekorači rate limit.
    """
    from nba_api.stats.endpoints import PlayerGameLog

    if roster_df.empty or games_df.empty:
        return pd.DataFrame()

    _log("🔄 Fetching H2H data (last 2 seasons)...", log_fn)

    # Napravi mapu: PLAYER_ID → OPP_TEAM_ABBR (tim koji igraju danas)
    player_opp_map = {}
    for _, game in games_df.iterrows():
        home_tid = int(game.get("HOME_TEAM_ID", 0) or 0)
        away_tid = int(game.get("VISITOR_TEAM_ID", 0) or 0)
        home_abbr = TEAM_ID_TO_ABBR.get(home_tid, "")
        away_abbr = TEAM_ID_TO_ABBR.get(away_tid, "")
        # Home igrači imaju OPP = away tim i obratno
        home_players = roster_df[roster_df["TEAM_ID"] == home_tid]["PLAYER_ID"].tolist()
        away_players = roster_df[roster_df["TEAM_ID"] == away_tid]["PLAYER_ID"].tolist()
        for pid in home_players:
            player_opp_map[pid] = away_abbr
        for pid in away_players:
            player_opp_map[pid] = home_abbr

    rows = []
    total = min(len(player_opp_map), 60)  # cap na 60 igrača
    player_name_map = dict(zip(roster_df["PLAYER_ID"], roster_df["PLAYER_NAME"]))

    for i, (pid, opp_abbr) in enumerate(list(player_opp_map.items())[:total]):
        if i % 10 == 0:
            _log(f"  H2H progress: {i}/{total}", log_fn)
        try:
            gl = _nba_endpoint(PlayerGameLog,
                               player_id=int(pid),
                               season=SEASON,
                               season_type_all_star="Regular Season")
            gdf = gl.player_game_log.get_data_frame()
            if gdf.empty:
                continue

            # Filter na utakmice vs today's opponent
            matchup_col = next((c for c in gdf.columns if "MATCHUP" in c.upper()), None)
            pts_col     = next((c for c in gdf.columns if c.upper() == "PTS"), None)
            min_col     = next((c for c in gdf.columns if c.upper() == "MIN"), None)

            if matchup_col and pts_col and opp_abbr:
                opp_games = gdf[gdf[matchup_col].astype(str).str.contains(opp_abbr, case=False, na=False)]
                if not opp_games.empty:
                    pts_series = pd.to_numeric(opp_games[pts_col], errors="coerce").dropna()
                    if len(pts_series) > 0:
                        rows.append({
                            "PLAYER_NAME":   player_name_map.get(pid, str(pid)),
                            "OPP_TEAM":      opp_abbr,
                            "H2H_PTS_AVG":   round(float(pts_series.mean()), 2),
                            "H2H_GAMES":     len(pts_series),
                            "H2H_PTS_LAST":  round(float(pts_series.iloc[0]), 2) if len(pts_series) > 0 else None,
                        })
        except Exception:
            pass
        _sleep(NBA_SLEEP)

    h2h_df = pd.DataFrame(rows) if rows else pd.DataFrame()
    _log(f"✅ H2H records built: {len(h2h_df)}", log_fn)
    return h2h_df

# ─── MASTER RUN ──────────────────────────────────────────────────────────────
def run(data_dir: str = None, log_fn=None, skip_h2h: bool = False) -> dict:
    """
    Glavna funkcija — poziva sve korake i piše CSV fajlove.
    Vraća dict s rezultatima (counts, paths, errors).
    """
    os.makedirs(DATA_DIR if data_dir is None else data_dir, exist_ok=True)
    _dir = data_dir or DATA_DIR

    report = {
        "status":   "OK",
        "errors":   [],
        "files":    {},
        "counts":   {},
        "date":     str(datetime.date.today()),
        "season":   SEASON,
    }

    # Provjera zavisnosti
    try:
        import nba_api  # noqa
    except ImportError:
        msg = "❌ nba_api nije instaliran. Pokreni: pip install nba_api"
        _log(msg, log_fn)
        report["status"] = "ERROR"
        report["errors"].append(msg)
        return report

    # ── 1. Today's games ──────────────────────────────────────────────────────
    try:
        team_ids, games_df = fetch_todays_games(log_fn)
        if not team_ids:
            _log("ℹ️  No NBA games today. CSV files unchanged.", log_fn)
            report["status"] = "NO_GAMES"
            return report
    except Exception as e:
        report["errors"].append(f"ScoreboardV2 error: {e}")
        report["status"] = "ERROR"
        _log(f"❌ Cannot fetch today's schedule: {e}", log_fn)
        return report

    # ── 2. Rosters ────────────────────────────────────────────────────────────
    try:
        player_ids, roster_df = fetch_rosters(team_ids, log_fn)
    except Exception as e:
        report["errors"].append(f"Roster error: {e}")
        _log(f"❌ Roster fetch failed: {e}\n{traceback.format_exc()}", log_fn)
        player_ids, roster_df = set(), pd.DataFrame()

    if not player_ids:
        _log("❌ No players found in rosters. Aborting.", log_fn)
        report["status"] = "ERROR"
        return report

    # ── 3. Player stats ───────────────────────────────────────────────────────
    try:
        base_df, adv_df, misc_df, main_df = fetch_player_stats_all(player_ids, log_fn)
    except Exception as e:
        report["errors"].append(f"Player stats error: {e}")
        _log(f"❌ Player stats failed: {e}", log_fn)
        base_df = adv_df = misc_df = main_df = pd.DataFrame()

    # ── 4. L10 forma — fetchuje SVE igrače u ligi (ne samo danas) ───────────
    try:
        # None = bez filtera po player_ids → svi aktivni igrači u sezoni
        l10_df = fetch_l10_form(None, log_fn)
    except Exception as e:
        report["errors"].append(f"L10 form error: {e}")
        _log(f"⚠️  L10 form failed: {e}", log_fn)
        l10_df = pd.DataFrame()

    # ── 5. Team stats ─────────────────────────────────────────────────────────
    try:
        teams_df, def_matchup_df, off_matchup_df = fetch_team_stats(team_ids, log_fn)
    except Exception as e:
        report["errors"].append(f"Team stats error: {e}")
        _log(f"⚠️  Team stats failed: {e}", log_fn)
        teams_df = def_matchup_df = off_matchup_df = pd.DataFrame()

    # ── 6. Injuries ───────────────────────────────────────────────────────────
    try:
        inj_df = fetch_injuries(team_ids, log_fn)
    except Exception as e:
        report["errors"].append(f"Injury fetch error: {e}")
        _log(f"⚠️  Injury fetch failed: {e}", log_fn)
        inj_df = pd.DataFrame()

    # ── 7. H2H — koristi PUNI roster svih timova koji igraju ─────────────────
    # Ako roster_df nije pun (fetch_todays_games vratio manje timova),
    # dopunjavamo ga iz NBA API-ja direktno po team_ids iz games_df
    h2h_df = pd.DataFrame()
    if not skip_h2h and not games_df.empty:
        try:
            # Osiguraj da roster_df ima igrače za SVE timove iz games_df
            if roster_df.empty:
                _log("⚠️  roster_df prazan — pokušavam direktni fetch rosters...", log_fn)
                _, roster_df = fetch_rosters(team_ids, log_fn)

            # Provjeri ima li roster_df timova koji su u games_df a nisu u roster_df
            games_team_ids = set()
            for _, g in games_df.iterrows():
                for col in ["HOME_TEAM_ID", "VISITOR_TEAM_ID"]:
                    tid = g.get(col)
                    if tid is not None and not pd.isna(tid):
                        try:
                            games_team_ids.add(int(tid))
                        except (ValueError, TypeError):
                            pass
            games_team_ids = {t for t in games_team_ids if t in TEAM_ID_TO_ABBR}

            roster_team_ids = set()
            if not roster_df.empty and "TEAM_ID" in roster_df.columns:
                roster_team_ids = set(roster_df["TEAM_ID"].dropna().astype(int).tolist())

            missing_teams = games_team_ids - roster_team_ids
            if missing_teams:
                missing_abbrs = [TEAM_ID_TO_ABBR.get(t, str(t)) for t in missing_teams]
                _log(f"  ⚠️  H2H: nedostaju timovi {missing_abbrs} — dopunjujem rosters...", log_fn)
                try:
                    _, extra_roster = fetch_rosters(missing_teams, log_fn)
                    if not extra_roster.empty:
                        roster_df = pd.concat([roster_df, extra_roster], ignore_index=True).drop_duplicates(subset=["PLAYER_ID"])
                        _log(f"  ✅ Roster dopunjen: ukupno {len(roster_df)} igrača", log_fn)
                except Exception as re:
                    _log(f"  ⚠️  Roster dopuna failed: {re}", log_fn)

            h2h_df = fetch_h2h_for_today(roster_df, games_df, log_fn)
        except Exception as e:
            report["errors"].append(f"H2H error: {e}")
            _log(f"⚠️  H2H fetch failed: {e}", log_fn)

    # ── 8. PISANJE CSV FAJLOVA ────────────────────────────────────────────────
    _log("\n💾 Writing CSV files...", log_fn)

    def _write(df: pd.DataFrame, filename: str, key: str = "PLAYER_ID"):
        if df is None or df.empty:
            return 0
        path = os.path.join(_dir, filename)
        count = _merge_and_save(df, path, key_col=key)
        report["files"][filename] = path
        report["counts"][filename] = count
        _log(f"  ✅ {filename}: {count} rows", log_fn)
        return count

    _write(main_df,       f"players_{SEASON}.csv",          "PLAYER_ID")
    _write(base_df,       f"players_{SEASON}_base.csv",     "PLAYER_ID")
    _write(adv_df,        f"players_{SEASON}_advanced.csv", "PLAYER_ID")
    _write(misc_df,       f"players_{SEASON}_misc.csv",     "PLAYER_ID")
    _write(teams_df,      f"teams_{SEASON}.csv",            "TEAM_ID")
    _write(def_matchup_df,f"def_matchup_{SEASON}.csv",      "TEAM_ID")
    _write(off_matchup_df,f"off_matchup_{SEASON}.csv",      "TEAM_ID")
    _write(l10_df,        f"form_l10_{SEASON}.csv",         "PLAYER_ID")

    if not inj_df.empty:
        inj_path = os.path.join(_dir, f"injuries_{SEASON}.csv")
        inj_df.to_csv(inj_path, index=False)  # injuries se uvijek overwriteaju (svakodnevni snapshot)
        report["files"][f"injuries_{SEASON}.csv"] = inj_path
        report["counts"][f"injuries_{SEASON}.csv"] = len(inj_df)
        _log(f"  ✅ injuries_{SEASON}.csv: {len(inj_df)} rows (overwrite)", log_fn)

    if not h2h_df.empty:
        _write(h2h_df, f"h2h_{SEASON}.csv", "PLAYER_NAME")

    # ── 9. POKRENI refresh_all.py (ako postoji) ───────────────────────────────
    _run_refresh_all(log_fn, report)

    _log(f"\n🎉 Daily refresh complete! Files in: {_dir}", log_fn)
    report["status"] = "OK"
    return report


def _run_refresh_all(log_fn=None, report: dict = None):
    """
    Pokreće refresh_all.py ako postoji u root folderu projekta.
    Podržava tri načina pokretanja (detektira automatski):
      1. subprocess — ako je refresh_all.py standalone skripta
      2. importlib  — ako ima run() ili main() funkciju
      3. exec()     — zadnji fallback

    Greške ne zaustavljaju glavni refresh — samo se loguju kao warning.
    """
    root = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(root, "refresh_all.py")

    if not os.path.exists(script_path):
        _log("ℹ️  refresh_all.py nije pronađen — preskačem.", log_fn)
        return

    _log("\n🔁 Pokretanje refresh_all.py...", log_fn)

    # ── Pokušaj 1: subprocess (najsigurniji, izolirani proces) ────────────────
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=300,   # max 5 min za refresh_all
            cwd=root,
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if stdout:
            for line in stdout.splitlines()[-20:]:   # zadnjih 20 linija outputa
                _log(f"  [refresh_all] {line}", log_fn)

        if result.returncode == 0:
            _log("  ✅ refresh_all.py završen uspješno.", log_fn)
            if report is not None:
                report["refresh_all"] = "OK"
        else:
            _log(f"  ⚠️  refresh_all.py izašao s kodom {result.returncode}", log_fn)
            if stderr:
                _log(f"  stderr: {stderr[:500]}", log_fn)
            if report is not None:
                report["refresh_all"] = f"EXIT_{result.returncode}"
                report["errors"].append(f"refresh_all.py exit code {result.returncode}: {stderr[:200]}")
        return

    except subprocess.TimeoutExpired:
        _log("  ⚠️  refresh_all.py trajao >5 min — timeout. Nastavljam.", log_fn)
        if report is not None:
            report["errors"].append("refresh_all.py timeout (>5min)")
        return
    except FileNotFoundError:
        pass  # Python interpreter ne pronađen — probaj importlib
    except Exception as e:
        _log(f"  ⚠️  subprocess greška: {e} — probam importlib...", log_fn)

    # ── Pokušaj 2: importlib (direktni import, dijeli isti process) ───────────
    try:
        import importlib.util
        spec   = importlib.util.spec_from_file_location("refresh_all", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Potraži run() ili main() funkciju
        if hasattr(module, "run"):
            module.run()
            _log("  ✅ refresh_all.run() izvršen.", log_fn)
            if report is not None:
                report["refresh_all"] = "OK_importlib_run"
        elif hasattr(module, "main"):
            module.main()
            _log("  ✅ refresh_all.main() izvršen.", log_fn)
            if report is not None:
                report["refresh_all"] = "OK_importlib_main"
        else:
            # Modul se izvršio pri loadu (nema posebne funkcije)
            _log("  ✅ refresh_all.py učitan i izvršen (no run/main fn).", log_fn)
            if report is not None:
                report["refresh_all"] = "OK_importlib_exec"
        return

    except Exception as e:
        _log(f"  ⚠️  importlib greška: {e}", log_fn)

    # ── Pokušaj 3: exec() fallback ────────────────────────────────────────────
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            code = f.read()
        exec(compile(code, script_path, "exec"), {"__file__": script_path, "__name__": "__main__"})
        _log("  ✅ refresh_all.py izvršen via exec().", log_fn)
        if report is not None:
            report["refresh_all"] = "OK_exec"
    except Exception as e:
        _log(f"  ❌ refresh_all.py exec() greška: {e}", log_fn)
        if report is not None:
            report["errors"].append(f"refresh_all.py exec failed: {e}")


# ─── CLI ENTRYPOINT ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NBA Daily Data Refresh")
    parser.add_argument("--no-h2h",    action="store_true", help="Skip H2H fetch (faster)")
    parser.add_argument("--data-dir",  default=None,        help="Override data directory")
    args = parser.parse_args()

    result = run(
        data_dir  = args.data_dir,
        log_fn    = print,
        skip_h2h  = args.no_h2h,
    )
    print("\n── SUMMARY ──")
    print(f"Status  : {result['status']}")
    print(f"Season  : {result['season']}")
    print(f"Date    : {result['date']}")
    if result["counts"]:
        print("Files written:")
        for f, c in result["counts"].items():
            print(f"  {f}: {c} rows")
    if result["errors"]:
        print("Errors:")
        for e in result["errors"]:
            print(f"  ⚠️  {e}")
    sys.exit(0 if result["status"] in ("OK", "NO_GAMES") else 1)