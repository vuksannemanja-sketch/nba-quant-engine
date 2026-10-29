"""Statistika igrača i timova za sezonu (NBA Stats → ``players_*.csv``, ``teams_*.csv``).

Prenesena logika ``refresh_data.py`` (oporavljena verzija): base/advanced/misc tabele igrača,
bio podaci spojeni u glavnu tabelu, te base + advanced statistika timova.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..config import Settings
from ._nba import Logger, add_team_abbr, call_with_retry, log_to, require_nba_api, sleep

BIO_COLS = ["PLAYER_ID", "PLAYER_HEIGHT_INCHES", "PLAYER_WEIGHT",
            "COLLEGE", "COUNTRY", "DRAFT_YEAR", "DRAFT_ROUND", "DRAFT_NUMBER"]
TEAM_ADV_COLS = ["TEAM_ID", "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE", "PIE"]


def fetch_player_table(season: str, measure_type: str, timeout: int = 60) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguedashplayerstats
    ep = call_with_retry(leaguedashplayerstats.LeagueDashPlayerStats,
                         season=season, season_type_all_star="Regular Season",
                         per_mode_detailed="PerGame", measure_type_detailed_defense=measure_type,
                         timeout=timeout)
    return add_team_abbr(ep.get_data_frames()[0])


def fetch_bio_table(season: str, timeout: int = 60) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguedashplayerbiostats
    ep = call_with_retry(leaguedashplayerbiostats.LeagueDashPlayerBioStats, season=season, timeout=timeout)
    return add_team_abbr(ep.get_data_frames()[0])


def merge_bio(base_df: pd.DataFrame, bio_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Glavna tabela igrača = base + bio kolone (visina, težina, draft) ako postoje."""
    if bio_df is None or bio_df.empty or "PLAYER_ID" not in base_df.columns:
        return base_df
    cols = [c for c in BIO_COLS if c in bio_df.columns]
    if len(cols) <= 1:
        return base_df
    return base_df.merge(bio_df[cols].drop_duplicates("PLAYER_ID"), on="PLAYER_ID", how="left")


def fetch_team_table(season: str, measure_type: str, timeout: int = 60) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguedashteamstats
    ep = call_with_retry(leaguedashteamstats.LeagueDashTeamStats,
                         season=season, measure_type_detailed_defense=measure_type,
                         per_mode_detailed="PerGame", timeout=timeout)
    return ep.get_data_frames()[0]


def build_teams(base: pd.DataFrame, adv: pd.DataFrame) -> pd.DataFrame:
    tdf = add_team_abbr(base.copy())
    adv_cols = [c for c in TEAM_ADV_COLS if c in adv.columns]
    if "TEAM_ID" in tdf.columns and len(adv_cols) > 1:
        tdf = tdf.merge(adv[adv_cols].drop_duplicates("TEAM_ID"), on="TEAM_ID", how="left")
    return tdf


def run(settings: Settings, log: Optional[Logger] = None) -> str:
    log = log_to(log)
    require_nba_api()
    season, t = settings.season, settings.nba_api_timeout
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    written = []

    base = None
    for label, measure, kind in (("Base", "Base", "players_base"),
                                 ("Advanced", "Advanced", "players_adv"),
                                 ("Misc", "Misc", "players_misc")):
        log(f"  📥 Igrači {label}...")
        df = fetch_player_table(season, measure, t)
        path = settings.primary_csv_path(kind)
        df.to_csv(path, index=False)
        written.append(f"{path.name} ({len(df)})")
        if measure == "Base":
            base = df
        sleep(2.0)

    log("  📥 Bio podaci igrača...")
    try:
        bio = fetch_bio_table(season, t)
    except Exception as e:  # noqa: BLE001
        log(f"  ⚠️ Bio podaci nisu dostupni ({e}); glavna tabela = base.")
        bio = None
    main_df = merge_bio(base, bio)
    main_path = settings.primary_csv_path("players_main")
    main_df.to_csv(main_path, index=False)
    written.append(f"{main_path.name} ({len(main_df)})")
    sleep(1.5)

    log("  📥 Timovi (Base + Advanced)...")
    team_base = fetch_team_table(season, "Base", t)
    sleep(1.5)
    team_adv = fetch_team_table(season, "Advanced", t)
    teams = build_teams(team_base, team_adv)
    teams_path = settings.primary_csv_path("teams")
    teams.to_csv(teams_path, index=False)
    written.append(f"{teams_path.name} ({len(teams)})")

    return "Snimljeno: " + ", ".join(written)
