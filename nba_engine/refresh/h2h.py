"""Head-to-head statistika: prosjek poena igrača protiv svakog protivnika u zadnje 3 sezone.

Prenesena logika ``refresh_h2h.py`` (oporavljena verzija). Traje duže (3 velika game loga).
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from ..config import Settings, seasons_back
from ._nba import Logger, call_with_retry, log_to, require_nba_api, sleep

H2H_SEASONS = 3
MIN_GAMES = 2


def fetch_game_logs(seasons: List[str], log: Logger, timeout: int = 90) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguegamelog
    parts = []
    for season in seasons:
        log(f"  📥 Game log {season}...")
        try:
            ep = call_with_retry(leaguegamelog.LeagueGameLog,
                                 season=season, season_type_all_star="Regular Season",
                                 player_or_team_abbreviation="P", sorter="DATE", direction="DESC",
                                 timeout=timeout)
            df = ep.get_data_frames()[0]
            df["SEASON"] = season
            parts.append(df)
            log(f"  ✅ {season}: {len(df)} zapisa")
            sleep(2.0)
        except Exception as e:  # noqa: BLE001
            log(f"  ❌ {season}: {e}")
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def extract_matchup_opponent(matchup_str: str, player_team: str) -> str:
    """'DET vs. MEM' ili 'DET @ MEM' → protivnik tima igrača."""
    if not matchup_str or not player_team:
        return ""
    m = str(matchup_str).strip().upper()
    p = str(player_team).strip().upper()
    if " VS. " in m:
        parts = m.split(" VS. ")
    elif " @ " in m:
        parts = m.split(" @ ")
    else:
        return ""
    if len(parts) != 2:
        return ""
    if parts[0].strip() == p:
        return parts[1].strip()
    if parts[1].strip() == p:
        return parts[0].strip()
    return ""


def compute_h2h(gl: pd.DataFrame) -> pd.DataFrame:
    """Iz game loga: PLAYER_NAME, OPP_TEAM, H2H_PTS_AVG, H2H_GAMES, H2H_PTS_LAST, H2H_PTS_STD, H2H_LAST_DATE."""
    if gl.empty:
        return pd.DataFrame()
    rename = {}
    for c in gl.columns:
        cl = c.upper()
        if cl in ("PLAYER_NAME", "PLAYER"):
            rename[c] = "PLAYER_NAME"
        elif cl in ("TEAM_ABBREVIATION", "TEAM"):
            rename[c] = "TEAM_ABBR"
        elif cl in ("MATCHUP", "PTS", "GAME_DATE", "SEASON"):
            rename[c] = cl
    gl = gl.rename(columns=rename)
    needed = ["PLAYER_NAME", "MATCHUP", "TEAM_ABBR", "PTS", "GAME_DATE"]
    if any(c not in gl.columns for c in needed):
        return pd.DataFrame()
    gl = gl.copy()
    gl["PTS"] = pd.to_numeric(gl["PTS"], errors="coerce")
    gl["GAME_DATE"] = pd.to_datetime(gl["GAME_DATE"], errors="coerce")
    gl = gl.dropna(subset=["PTS", "GAME_DATE", "PLAYER_NAME"])
    gl["OPP_TEAM"] = [extract_matchup_opponent(m, t) for m, t in zip(gl["MATCHUP"], gl["TEAM_ABBR"])]
    gl = gl[gl["OPP_TEAM"] != ""]
    gl = gl.sort_values(["PLAYER_NAME", "OPP_TEAM", "GAME_DATE"], ascending=[True, True, False])

    rows = []
    for (player, opp), grp in gl.groupby(["PLAYER_NAME", "OPP_TEAM"]):
        pts = grp["PTS"].tolist()
        if not pts:
            continue
        rows.append({
            "PLAYER_NAME": player, "OPP_TEAM": opp,
            "H2H_PTS_AVG": round(float(np.mean(pts)), 2),
            "H2H_GAMES": len(pts),
            "H2H_PTS_LAST": round(float(pts[0]), 2),
            "H2H_PTS_STD": round(float(np.std(pts)) if len(pts) > 1 else 0.0, 2),
            "H2H_LAST_DATE": grp["GAME_DATE"].iloc[0].strftime("%Y-%m-%d"),
        })
    return pd.DataFrame(rows)


def filter_relevant_h2h(h2h: pd.DataFrame, min_games: int = MIN_GAMES) -> pd.DataFrame:
    if h2h.empty:
        return h2h
    out = h2h[h2h["H2H_GAMES"] >= min_games].copy()
    return out.sort_values(["PLAYER_NAME", "H2H_GAMES"], ascending=[True, False]).reset_index(drop=True)


def run(settings: Settings, log: Optional[Logger] = None) -> str:
    log = log_to(log)
    require_nba_api()
    seasons = seasons_back(settings.season, H2H_SEASONS)
    gl = fetch_game_logs(seasons, log, max(settings.nba_api_timeout, 90))
    if gl.empty:
        raise RuntimeError("Nema game log podataka za H2H.")
    h2h = filter_relevant_h2h(compute_h2h(gl))
    if h2h.empty:
        raise RuntimeError("H2H izračun nije dao rezultate.")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    p = settings.primary_csv_path("h2h")
    h2h.to_csv(p, index=False)
    return f"Snimljeno {len(h2h)} H2H kombinacija ({', '.join(seasons)}) → {p.name}"
