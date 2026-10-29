import os
import time
import json
import datetime as dt
import pandas as pd
import requests

SEASON = "2025-26"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

PLAYER_CSV = os.path.join(DATA_DIR, f"players_{SEASON}.csv")
TEAM_CSV   = os.path.join(DATA_DIR, f"teams_{SEASON}.csv")

# 1x dnevno cache marker
STAMP_FILE = os.path.join(DATA_DIR, f"last_refresh_{SEASON}.txt")

NBA_BASE = "https://stats.nba.com/stats"

HEADERS = {
    # NBA Stats zna da blokira bez "real browser" headera
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Connection": "keep-alive",
}

def is_fresh_24h(stamp_path: str) -> bool:
    if not os.path.exists(stamp_path):
        return False
    try:
        s = open(stamp_path, "r", encoding="utf-8").read().strip()
        last = dt.datetime.fromisoformat(s)
        return (dt.datetime.now() - last) < dt.timedelta(hours=24)
    except:
        return False

def write_stamp(stamp_path: str):
    with open(stamp_path, "w", encoding="utf-8") as f:
        f.write(dt.datetime.now().isoformat(timespec="seconds"))

def fetch_json(endpoint: str, params: dict, retries: int = 8, timeout_s: int = 120) -> dict:
    url = f"{NBA_BASE}/{endpoint}"

    last_err = None
    for i in range(1, retries + 1):
        try:
            with requests.Session() as s:
                s.headers.update(HEADERS)
                r = s.get(url, params=params, timeout=timeout_s)
                r.raise_for_status()
                return r.json()

        except Exception as e:
            last_err = e
            sleep_s = min(5 * i, 30)  # backoff do max 30s
            print(f"[WARN] {endpoint} attempt {i}/{retries} failed: {e} | sleeping {sleep_s}s")
            time.sleep(sleep_s)

    raise RuntimeError(f"Failed to fetch {endpoint} after {retries} retries. Last error: {last_err}")

def resultset_to_df(payload: dict) -> pd.DataFrame:
    # NBA Stats format: {"resultSets":[{"name":"...","headers":[...],"rowSet":[...]}]}
    if "resultSets" in payload and payload["resultSets"]:
        rs = payload["resultSets"][0]
        headers = rs.get("headers", [])
        rows = rs.get("rowSet", [])
        return pd.DataFrame(rows, columns=headers)

    # fallback: {"resultSet":{"headers":[...],"rowSet":[...]}}
    if "resultSet" in payload and payload["resultSet"]:
        rs = payload["resultSet"]
        headers = rs.get("headers", [])
        rows = rs.get("rowSet", [])
        return pd.DataFrame(rows, columns=headers)

    raise ValueError("Unknown NBA stats JSON structure")

def load_players_season(season: str) -> pd.DataFrame:
    # leaguedashplayerstats endpoint params (standard)
    params = {
        "Season": season,
        "SeasonType": "Regular Season",
        "PerMode": "PerGame",
        "LeagueID": "00",
        "MeasureType": "Base",
        "PlusMinus": "N",
        "PaceAdjust": "N",
        "Rank": "N",
        "Outcome": "",
        "Location": "",
        "Month": "0",
        "SeasonSegment": "",
        "DateFrom": "",
        "DateTo": "",
        "OpponentTeamID": "0",
        "VsConference": "",
        "VsDivision": "",
        "GameSegment": "",
        "Period": "0",
        "LastNGames": "0",
        "GameScope": "",
        "PlayerExperience": "",
        "PlayerPosition": "",
        "StarterBench": "",
        "DraftYear": "",
        "DraftPick": "",
        "College": "",
        "Country": "",
        "Height": "",
        "Weight": "",
        "TwoWay": "0",
    }

    payload = fetch_json("leaguedashplayerstats", params=params)
    df = resultset_to_df(payload)
    return df

def load_teams_season(season: str) -> pd.DataFrame:
    # leaguedashteamstats endpoint params (standard)
    params = {
        "Season": season,
        "SeasonType": "Regular Season",
        "PerMode": "PerGame",
        "LeagueID": "00",
        "MeasureType": "Base",
        "PlusMinus": "N",
        "PaceAdjust": "N",
        "Rank": "N",
        "Outcome": "",
        "Location": "",
        "Month": "0",
        "SeasonSegment": "",
        "DateFrom": "",
        "DateTo": "",
        "OpponentTeamID": "0",
        "VsConference": "",
        "VsDivision": "",
        "GameSegment": "",
        "Period": "0",
        "LastNGames": "0",
        "GameScope": "",
    }

    payload = fetch_json("leaguedashteamstats", params=params)
    df = resultset_to_df(payload)
    return df

def main(force: bool = False):
    if not force and is_fresh_24h(STAMP_FILE) and os.path.exists(PLAYER_CSV) and os.path.exists(TEAM_CSV):
        print("[OK] Data already fresh (<24h). Skipping download.")
        print(f" - {PLAYER_CSV}")
        print(f" - {TEAM_CSV}")
        return

    print(f"[DATA] Fetching NBA season data via JSON for {SEASON} ...")

    players_df = load_players_season(SEASON)
    teams_df = load_teams_season(SEASON)

    players_df.to_csv(PLAYER_CSV, index=False)
    teams_df.to_csv(TEAM_CSV, index=False)
    write_stamp(STAMP_FILE)

    print("[OK] Saved:")
    print(f" - {PLAYER_CSV} ({len(players_df)} rows)")
    print(f" - {TEAM_CSV}   ({len(teams_df)} rows)")
    print(f"[OK] Stamp: {STAMP_FILE}")

if __name__ == "__main__":
    # Ako hoćeš forsirano: python3 data_loader_json.py --force
    import sys
    force_flag = "--force" in sys.argv
    main(force=force_flag)