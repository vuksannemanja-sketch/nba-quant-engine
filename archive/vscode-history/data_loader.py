# data_loader.py
# ALL-IN-ONE offline refresh:
# - players base stats
# - players four factors
# - teams base stats
# - TODAY matchups (scoreboard)
# - injury report (if endpoint exists)
# - player game log last 10 (for every player from base list)
#
# Robust: retries + headers + backoff + debug dump on non-JSON

import os
import time
import random
import json
import importlib
from datetime import datetime, date

import pandas as pd

from nba_api.stats.endpoints import (
    leaguedashplayerstats,
    leaguedashteamstats,
    scoreboardv2,
    playergamelog,
)

# =========================
# CONFIG
# =========================
SEASON = os.environ.get("NBA_SEASON", "2025-26")
DATA_DIR = os.path.join(os.getcwd(), "data")
os.makedirs(DATA_DIR, exist_ok=True)

REQUEST_TIMEOUT = int(os.environ.get("NBA_REQUEST_TIMEOUT", "120"))
RETRIES = int(os.environ.get("NBA_RETRIES", "6"))
BASE_SLEEP = float(os.environ.get("NBA_BASE_SLEEP", "6.0"))  # seconds, with jitter

# Optional proxy: export NBA_PROXY="http://127.0.0.1:7890"
NBA_PROXY = os.environ.get("NBA_PROXY", None)

# NBA Stats picky headers
HEADERS = {
    "Host": "stats.nba.com",
    "Connection": "keep-alive",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}

# =========================
# HELPERS
# =========================
def _sleep_backoff(attempt: int):
    sleep_s = BASE_SLEEP * (1.35 ** max(0, attempt - 1))
    sleep_s += random.uniform(0.0, 2.5)
    print(f"[INFO] sleeping {sleep_s:.1f}s before retry...")
    time.sleep(sleep_s)


def _save_debug(label: str, attempt: int, raw_text: str):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(DATA_DIR, f"_debug_{label}_a{attempt}_{ts}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw_text or "")
        print(f"[DEBUG] saved non-JSON/blocked response to: {path}")
    except Exception:
        pass


def _endpoint_raw_text(endpoint) -> str:
    # nba_api sometimes exposes response string like this
    try:
        resp = getattr(endpoint, "nba_response", None)
        if resp is None:
            return ""
        get_string = getattr(resp, "get_string", None)
        if callable(get_string):
            return get_string() or ""
    except Exception:
        return ""
    return ""


def fetch_with_retry(make_call, label: str):
    """
    make_call -> returns an endpoint instance.
    returns: list[pd.DataFrame] from endpoint.get_data_frames()
    """
    last_err = None
    endpoint_obj = None

    for attempt in range(1, RETRIES + 1):
        try:
            print(f"[DATA] Fetching {label} ({attempt}/{RETRIES}) ...")
            endpoint_obj = make_call()
            dfs = endpoint_obj.get_data_frames()

            if not dfs or len(dfs) == 0:
                raise RuntimeError("No data frames returned")
            if dfs[0] is None or dfs[0].empty:
                raise RuntimeError("Empty dataframe returned")

            return dfs

        except json.JSONDecodeError as e:
            last_err = e
            raw = _endpoint_raw_text(endpoint_obj) if endpoint_obj else ""
            _save_debug(label, attempt, raw or f"JSONDecodeError: {e}")
            print(f"[WARN] {label} non-JSON response. attempt {attempt}/{RETRIES}: {e}")
            _sleep_backoff(attempt)

        except Exception as e:
            last_err = e
            raw = _endpoint_raw_text(endpoint_obj) if endpoint_obj else ""
            if raw and ("<html" in raw.lower() or "cloudflare" in raw.lower() or "access denied" in raw.lower()):
                _save_debug(label, attempt, raw)
            print(f"[WARN] {label} failed attempt {attempt}/{RETRIES}: {e}")
            _sleep_backoff(attempt)

    raise RuntimeError(f"{label} failed after {RETRIES} retries. Last error: {last_err}")


def save_csv(df: pd.DataFrame, filename: str):
    out_path = os.path.join(DATA_DIR, filename)
    df.to_csv(out_path, index=False, encoding="utf-8")
    print(f"[OK] Saved: {out_path}")


def save_multi_csv(dfs, filenames):
    for df, fn in zip(dfs, filenames):
        if df is None:
            continue
        save_csv(df, fn)


# =========================
# LOADERS
# =========================
def load_players_base() -> pd.DataFrame:
    def _call():
        return leaguedashplayerstats.LeagueDashPlayerStats(
            season=SEASON,
            timeout=REQUEST_TIMEOUT,
            headers=HEADERS,
            proxy=NBA_PROXY,
        )

    dfs = fetch_with_retry(_call, "players(Base)")
    df = dfs[0]
    save_csv(df, f"players_{SEASON}_base.csv")
    return df


def load_players_four_factors() -> pd.DataFrame:
    # Support both param styles depending on nba_api version
    def _call_primary():
        return leaguedashplayerstats.LeagueDashPlayerStats(
            season=SEASON,
            measure_type_detailed="Four Factors",
            timeout=REQUEST_TIMEOUT,
            headers=HEADERS,
            proxy=NBA_PROXY,
        )

    def _call_fallback():
        return leaguedashplayerstats.LeagueDashPlayerStats(
            season=SEASON,
            measure_type="Four Factors",
            timeout=REQUEST_TIMEOUT,
            headers=HEADERS,
            proxy=NBA_PROXY,
        )

    try:
        dfs = fetch_with_retry(_call_primary, "players(Four Factors)")
    except Exception as e:
        print(f"[WARN] primary Four Factors param failed, trying fallback. reason: {e}")
        dfs = fetch_with_retry(_call_fallback, "players(Four Factors)")

    df = dfs[0]
    save_csv(df, f"players_{SEASON}_four_factors.csv")
    return df


def load_teams_base() -> pd.DataFrame:
    def _call():
        return leaguedashteamstats.LeagueDashTeamStats(
            season=SEASON,
            timeout=REQUEST_TIMEOUT,
            headers=HEADERS,
            proxy=NBA_PROXY,
        )

    dfs = fetch_with_retry(_call, "teams(Base)")
    df = dfs[0]
    save_csv(df, f"teams_{SEASON}_base.csv")
    return df


def load_today_matchups() -> None:
    # ScoreboardV2 gives today's games + linescore etc
    game_date = date.today().strftime("%m/%d/%Y")  # scoreboardv2 expects MM/DD/YYYY
    def _call():
        return scoreboardv2.ScoreboardV2(
            game_date=game_date,
            timeout=REQUEST_TIMEOUT,
            headers=HEADERS,
            proxy=NBA_PROXY,
        )

    dfs = fetch_with_retry(_call, f"matchups(scoreboard {game_date})")

    # Usually dfs[0]=GameHeader, dfs[1]=LineScore, others can exist
    # Save what exists safely
    names = []
    for i in range(len(dfs)):
        if i == 0:
            names.append(f"matchups_{SEASON}_gameheader_{date.today().isoformat()}.csv")
        elif i == 1:
            names.append(f"matchups_{SEASON}_linescore_{date.today().isoformat()}.csv")
        else:
            names.append(f"matchups_{SEASON}_extra{i}_{date.today().isoformat()}.csv")
    save_multi_csv(dfs, names)


def load_injury_report() -> None:
    """
    nba_api may or may not have this endpoint depending on version.
    We'll try to import dynamically. If missing, we create an empty CSV (so app doesn't break).
    """
    try:
        mod = importlib.import_module("nba_api.stats.endpoints")
        # common name in some versions: leagueinjuryreport
        injury_cls = getattr(mod, "leagueinjuryreport", None)
        if injury_cls is None:
            raise ImportError("leagueinjuryreport not found in nba_api.stats.endpoints")

        # injury_cls is a module, class inside might be LeagueInjuryReport
        LeagueInjuryReport = getattr(injury_cls, "LeagueInjuryReport", None)
        if LeagueInjuryReport is None:
            # sometimes class name equals module name
            LeagueInjuryReport = getattr(injury_cls, "LeagueInjuryReport", None)

        if LeagueInjuryReport is None:
            raise ImportError("LeagueInjuryReport class not found")

        def _call():
            return LeagueInjuryReport(
                timeout=REQUEST_TIMEOUT,
                headers=HEADERS,
                proxy=NBA_PROXY,
            )

        dfs = fetch_with_retry(_call, "injury_report")
        # Save first table
        save_csv(dfs[0], f"injuries_{SEASON}_{date.today().isoformat()}.csv")
        return

    except Exception as e:
        print(f"[WARN] Injury report endpoint not available or blocked: {e}")
        # create empty placeholder to keep offline pipeline consistent
        placeholder = pd.DataFrame(columns=["NOTE"])
        placeholder.loc[0, "NOTE"] = f"Injury report not available via nba_api on this setup. ({e})"
        save_csv(placeholder, f"injuries_{SEASON}_{date.today().isoformat()}.csv")


def load_player_gamelog_last10(players_df: pd.DataFrame) -> None:
    """
    Pull last 10 games for each PLAYER_ID from base list.
    This is heavier, so we throttle between calls.
    """
    if players_df is None or players_df.empty or "PLAYER_ID" not in players_df.columns:
        print("[WARN] players_df missing PLAYER_ID, skip player_gamelog_last10")
        return

    player_ids = players_df["PLAYER_ID"].dropna().astype(int).unique().tolist()
    print(f"[INFO] Pulling last10 gamelog for {len(player_ids)} players (throttled) ...")

    all_rows = []
    failed = 0

    for idx, pid in enumerate(player_ids, start=1):
        label = f"playergamelog_last10(pid={pid})"

        def _call(pid=pid):
            return playergamelog.PlayerGameLog(
                player_id=pid,
                season=SEASON,
                last_n_games=10,
                timeout=REQUEST_TIMEOUT,
                headers=HEADERS,
                proxy=NBA_PROXY,
            )

        try:
            dfs = fetch_with_retry(_call, label)
            df = dfs[0].copy()
            df["PULL_PLAYER_ID"] = pid
            all_rows.append(df)
        except Exception as e:
            failed += 1
            print(f"[WARN] gamelog failed for player_id={pid}: {e}")

        # small throttle every call (and extra every 25)
        time.sleep(0.75 + random.uniform(0.0, 0.75))
        if idx % 25 == 0:
            time.sleep(2.5 + random.uniform(0.0, 2.5))
            print(f"[INFO] progress {idx}/{len(player_ids)} | failed={failed}")

    if all_rows:
        out = pd.concat(all_rows, ignore_index=True)
        save_csv(out, f"player_gamelog_last10_{SEASON}_{date.today().isoformat()}.csv")
    else:
        placeholder = pd.DataFrame(columns=["NOTE"])
        placeholder.loc[0, "NOTE"] = "No gamelog rows collected (blocked?)."
        save_csv(placeholder, f"player_gamelog_last10_{SEASON}_{date.today().isoformat()}.csv")


# =========================
# MAIN
# =========================
def main():
    print(f"[INFO] SEASON={SEASON}")
    print(f"[INFO] DATA_DIR={DATA_DIR}")
    print(f"[INFO] TIMEOUT={REQUEST_TIMEOUT}s RETRIES={RETRIES}")
    if NBA_PROXY:
        print(f"[INFO] Using proxy: {NBA_PROXY}")

    # 1) Core stats
    players_df = load_players_base()
    load_players_four_factors()
    load_teams_base()

    # 2) One-shot daily data
    load_today_matchups()
    load_injury_report()

    # 3) Player last 10 game logs (heavier)
    load_player_gamelog_last10(players_df)

    print("[DONE] ALL offline CSV refreshed ✅")


if __name__ == "__main__":
    main()