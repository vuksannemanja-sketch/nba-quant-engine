"""Raspored sezone i back-to-back oznake (NBA Stats game log timova).

Prenesena logika ``refresh_schedule.py`` (oporavljena verzija).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..config import Settings
from ..teams import TEAM_ID_TO_ABBR
from ._nba import Logger, call_with_retry, log_to, require_nba_api, sleep


def fetch_team_game_log(season: str, log: Logger, timeout: int = 60) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguegamelog
    parts = []
    for season_type in ("Regular Season", "Playoffs"):
        try:
            ep = call_with_retry(leaguegamelog.LeagueGameLog,
                                 season=season, season_type_all_star=season_type,
                                 league_id="00", timeout=timeout)
            df = ep.get_data_frames()[0]
            parts.append(df)
            log(f"  ✅ {season_type}: {len(df)} redova")
            sleep(1.5)
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠️ {season_type}: {e}")
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def build_schedule(df: pd.DataFrame) -> pd.DataFrame:
    """Iz game loga timova (jedan red po timu po utakmici) napravi raspored: datum, domaćin, gost, GAME_ID."""
    if df.empty:
        return pd.DataFrame(columns=["GAME_DATE", "HOME_TEAM_ABBR", "AWAY_TEAM_ABBR", "GAME_ID"])
    df = df.copy()
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["TEAM_ABBR"] = pd.to_numeric(df["TEAM_ID"], errors="coerce").map(TEAM_ID_TO_ABBR)
    df["IS_HOME"] = df["MATCHUP"].astype(str).str.contains(" vs\\. ", na=False)
    home = df[df["IS_HOME"]][["GAME_ID", "GAME_DATE", "TEAM_ABBR"]].rename(columns={"TEAM_ABBR": "HOME_TEAM_ABBR"})
    away = df[~df["IS_HOME"]][["GAME_ID", "TEAM_ABBR"]].rename(columns={"TEAM_ABBR": "AWAY_TEAM_ABBR"})
    schedule = home.merge(away, on="GAME_ID", how="inner")
    schedule = schedule[["GAME_DATE", "HOME_TEAM_ABBR", "AWAY_TEAM_ABBR", "GAME_ID"]]
    return schedule.drop_duplicates("GAME_ID").sort_values("GAME_DATE").reset_index(drop=True)


def build_b2b_flags(schedule: pd.DataFrame) -> pd.DataFrame:
    """Za svaki tim i datum: IS_B2B = tim je igrao i prethodnog dana."""
    rows = []
    for _, row in schedule.iterrows():
        for col in ("HOME_TEAM_ABBR", "AWAY_TEAM_ABBR"):
            team = row.get(col)
            if pd.notna(team):
                rows.append({"GAME_DATE": row["GAME_DATE"], "TEAM_ABBR": team})
    if not rows:
        return pd.DataFrame(columns=["GAME_DATE", "TEAM_ABBR", "IS_B2B"])
    td = pd.DataFrame(rows).drop_duplicates()
    td["GAME_DATE"] = pd.to_datetime(td["GAME_DATE"])
    td = td.sort_values(["TEAM_ABBR", "GAME_DATE"])
    td["PREV_DATE"] = td.groupby("TEAM_ABBR")["GAME_DATE"].shift(1)
    td["IS_B2B"] = (td["GAME_DATE"] - td["PREV_DATE"]).dt.days == 1
    td["GAME_DATE"] = td["GAME_DATE"].dt.strftime("%Y-%m-%d")
    return td[["GAME_DATE", "TEAM_ABBR", "IS_B2B"]].reset_index(drop=True)


def run(settings: Settings, log: Optional[Logger] = None) -> str:
    log = log_to(log)
    require_nba_api()
    gl = fetch_team_game_log(settings.season, log, settings.nba_api_timeout)
    schedule = build_schedule(gl)
    if schedule.empty:
        raise RuntimeError("Raspored nije dostupan (prazan game log).")
    b2b = build_b2b_flags(schedule)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    sp = settings.primary_csv_path("schedule")
    bp = settings.primary_csv_path("b2b")
    schedule.to_csv(sp, index=False)
    b2b.to_csv(bp, index=False)
    return f"Snimljeno: {sp.name} ({len(schedule)} utakmica), {bp.name} ({int(b2b['IS_B2B'].sum())} B2B dana)"
