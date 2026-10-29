"""DEF/OFF matchup tabele i L3/L5/L10 forma igrača (NBA Stats).

Prenesena logika ``refresh_matchups.py`` (oporavljena verzija):
  - def_matchup: LeagueDashPtDefend po kategorijama odbrane (po igraču-braniocu)
  - off_matchup: LeagueDashTeamStats (Advanced) po timu
  - form_l10:    LeagueGameLog igrača → L3/L5/L10 prosjek, std, trend (linearna regresija)

Ispravka u odnosu na original: PtDefend tabela nema kolonu TEAM_ID nego PLAYER_LAST_TEAM_ID /
PLAYER_LAST_TEAM_ABBREVIATION, pa je kolona TEAM_ABBR u originalu ostajala prazna.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..config import Settings
from ..teams import TEAM_ID_TO_ABBR
from ._nba import Logger, add_team_abbr, call_with_retry, log_to, require_nba_api, sleep

DEFENSE_CATEGORIES = ("Overall", "3 Pointers", "2 Pointers", "Less Than 6Ft")


def _team_abbr_for_defend(df: pd.DataFrame) -> pd.Series:
    for col in ("PLAYER_LAST_TEAM_ABBREVIATION", "TEAM_ABBREVIATION", "TEAM_ABBR"):
        if col in df.columns and df[col].notna().any():
            return df[col].astype(str).str.upper()
    for col in ("PLAYER_LAST_TEAM_ID", "TEAM_ID"):
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").map(TEAM_ID_TO_ABBR)
    return pd.Series([np.nan] * len(df), index=df.index)


def fetch_def_matchup(season: str, log: Logger, timeout: int = 60) -> Optional[pd.DataFrame]:
    from nba_api.stats.endpoints import leaguedashptdefend
    parts = []
    for category in DEFENSE_CATEGORIES:
        try:
            ep = call_with_retry(leaguedashptdefend.LeagueDashPtDefend,
                                 season=season, defense_category=category, per_mode_simple="PerGame",
                                 season_type_all_star="Regular Season", timeout=timeout)
            df = ep.get_data_frames()[0]
            df["DEFENSE_CATEGORY"] = category
            parts.append(df)
            sleep(1.2)
        except Exception as e:  # noqa: BLE001
            log(f"    ⚠️ {category}: {e}")
    if not parts:
        return None
    combined = pd.concat(parts, ignore_index=True)
    combined["TEAM_ABBR"] = _team_abbr_for_defend(combined)
    return combined


def fetch_off_matchup(season: str, timeout: int = 60) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguedashteamstats
    ep = call_with_retry(leaguedashteamstats.LeagueDashTeamStats,
                         season=season, measure_type_detailed_defense="Advanced",
                         per_mode_detailed="PerGame", season_type_all_star="Regular Season", timeout=timeout)
    return add_team_abbr(ep.get_data_frames()[0])


def fetch_player_game_log(season: str, timeout: int = 90) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguegamelog
    ep = call_with_retry(leaguegamelog.LeagueGameLog,
                         season=season, season_type_all_star="Regular Season",
                         player_or_team_abbreviation="P", sorter="DATE", direction="DESC", timeout=timeout)
    return ep.get_data_frames()[0]


def compute_form_table(gl: pd.DataFrame) -> pd.DataFrame:
    """Iz game loga igrača izračunaj L3/L5/L10 prosjeke, std, minute, trend (čista funkcija)."""
    needed = ["PLAYER_NAME", "PLAYER_ID", "GAME_DATE", "PTS", "MIN", "TEAM_ABBREVIATION"]
    gl = gl[[c for c in needed if c in gl.columns]].copy()
    if gl.empty:
        return pd.DataFrame()
    if "PLAYER_NAME" not in gl.columns and "PLAYER_ID" in gl.columns:
        gl["PLAYER_NAME"] = gl["PLAYER_ID"].astype(str)
    gl["GAME_DATE"] = pd.to_datetime(gl["GAME_DATE"], errors="coerce")
    gl["PTS"] = pd.to_numeric(gl["PTS"], errors="coerce")
    gl["MIN"] = pd.to_numeric(gl["MIN"].astype(str).str.replace(":", ".").str.split(".").str[0], errors="coerce")
    gl = gl.sort_values(["PLAYER_NAME", "GAME_DATE"], ascending=[True, False])

    rows = []
    for player_name, grp in gl.groupby("PLAYER_NAME"):
        grp = grp.reset_index(drop=True)
        pts_list = grp["PTS"].dropna().tolist()
        min_list = grp["MIN"].dropna().tolist()
        if not pts_list:
            continue
        l3 = float(np.mean(pts_list[:3])) if len(pts_list) >= 3 else float(np.mean(pts_list))
        l5 = float(np.mean(pts_list[:5])) if len(pts_list) >= 5 else float(np.mean(pts_list))
        l10 = float(np.mean(pts_list[:10])) if len(pts_list) >= 10 else float(np.mean(pts_list))
        l10_std = float(np.std(pts_list[:10])) if len(pts_list) >= 3 else 0.0
        last_pts = float(pts_list[0])
        l10_min = float(np.mean(min_list[:10])) if len(min_list) >= 3 else 0.0
        trend_slope = 0.0
        pts_for_trend = pts_list[:10]
        if len(pts_for_trend) >= 3:
            try:
                x = np.arange(len(pts_for_trend))
                y = np.array(pts_for_trend[::-1], dtype=float)  # najstarija → najnovija
                trend_slope = float(np.polyfit(x, y, 1)[0])
            except Exception:
                pass
        team_abbr = grp["TEAM_ABBREVIATION"].iloc[0] if "TEAM_ABBREVIATION" in grp.columns else ""
        last_date = grp["GAME_DATE"].iloc[0]
        rows.append({
            "PLAYER_NAME": player_name, "TEAM_ABBR": str(team_abbr).strip(),
            "L3_PTS": round(l3, 2), "L5_PTS": round(l5, 2), "L10_PTS": round(l10, 2),
            "L10_STD": round(l10_std, 2), "L10_MIN": round(l10_min, 2), "LAST_PTS": round(last_pts, 2),
            "TREND_SLOPE": round(trend_slope, 3), "GAMES_PLAYED": len(pts_list),
            "LAST_DATE": last_date.strftime("%Y-%m-%d") if not pd.isna(last_date) else "",
        })
    return pd.DataFrame(rows).sort_values("PLAYER_NAME").reset_index(drop=True)


def run(settings: Settings, log: Optional[Logger] = None) -> str:
    log = log_to(log)
    require_nba_api()
    season, t = settings.season, settings.nba_api_timeout
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    written = []

    log("  📥 DEF matchup (PtDefend po kategorijama)...")
    dm = fetch_def_matchup(season, log, t)
    if dm is not None:
        p = settings.primary_csv_path("def_matchup")
        dm.to_csv(p, index=False)
        written.append(f"{p.name} ({len(dm)})")
    else:
        log("  ⚠️ DEF matchup nije dostupan.")
    sleep(2.0)

    log("  📥 OFF matchup (timovi Advanced)...")
    om = fetch_off_matchup(season, t)
    p = settings.primary_csv_path("off_matchup")
    om.to_csv(p, index=False)
    written.append(f"{p.name} ({len(om)})")
    sleep(2.0)

    log("  📥 L10 forma (game log igrača)...")
    gl = fetch_player_game_log(season, max(t, 90))
    form = compute_form_table(gl)
    if form.empty:
        log("  ⚠️ Game log prazan — forma nije snimljena.")
    else:
        p = settings.primary_csv_path("l10")
        form.to_csv(p, index=False)
        written.append(f"{p.name} ({len(form)})")

    return "Snimljeno: " + ", ".join(written)
