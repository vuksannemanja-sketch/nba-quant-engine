import os
import time
import pandas as pd

from nba_api.stats.endpoints import leaguedashplayerstats, leaguedashteamstats
from nba_api.library.http import NBAStatsHTTP

SEASON = "2025-26"
DATA_DIR = os.path.join(os.getcwd(), "data")
os.makedirs(DATA_DIR, exist_ok=True)

PLAYER_CSV = os.path.join(DATA_DIR, f"players_{SEASON}.csv")
TEAM_CSV = os.path.join(DATA_DIR, f"teams_{SEASON}.csv")

# NBA Stats zna da "zaglavi" — zato retry + veći timeout
RETRIES = 6
BASE_SLEEP = 4  # seconds

def fetch_with_retry(fetch_fn, label: str):
    last_err = None
    for i in range(RETRIES):
        try:
            return fetch_fn()
        except Exception as e:
            last_err = e
            wait = BASE_SLEEP * (i + 1)
            print(f"[WARN] {label} failed ({i+1}/{RETRIES}): {e} | retry in {wait}s")
            time.sleep(wait)
    raise last_err

def set_long_timeout(seconds: int = 120):
    # nba_api koristi NBAStatsHTTP().send_api_request(timeout=...)
    # endpoint konstruktori imaju parametar timeout, ali nije uvijek izložen na isti način.
    # Radi stabilno ako globalno povećamo default timeout u NBAStatsHTTP sessionu.
    # (Ovo je "soft" hack: i dalje koristimo retry)
    NBAStatsHTTP.DEFAULT_TIMEOUT = seconds  # radi u većini verzija nba_api

def main():
    print(f"[DATA] Refresh start for season {SEASON}")
    set_long_timeout(120)

    player_df = fetch_with_retry(
        lambda: leaguedashplayerstats.LeagueDashPlayerStats(season=SEASON).get_data_frames()[0],
        "LeagueDashPlayerStats"
    )
    team_df = fetch_with_retry(
        lambda: leaguedashteamstats.LeagueDashTeamStats(season=SEASON).get_data_frames()[0],
        "LeagueDashTeamStats"
    )

    # Atomic save (da app nikad ne uhvati polu-upisan fajl)
    tmp_players = PLAYER_CSV + ".tmp"
    tmp_teams = TEAM_CSV + ".tmp"

    player_df.to_csv(tmp_players, index=False)
    team_df.to_csv(tmp_teams, index=False)

    os.replace(tmp_players, PLAYER_CSV)
    os.replace(tmp_teams, TEAM_CSV)

    print(f"[OK] Saved: {PLAYER_CSV}")
    print(f"[OK] Saved: {TEAM_CSV}")
    print("[DONE] Refresh complete")

if __name__ == "__main__":
    main()