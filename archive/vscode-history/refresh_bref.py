# refresh_bref.py
import os
import re
import sys
from io import StringIO

import pandas as pd
import requests

# =====================================================
# CONFIG
# =====================================================

SEASON = "2025-26"          # output naming
END_YEAR = 2026             # Basketball-Reference uses END YEAR in URL
DATA_DIR = os.path.join(os.getcwd(), "data")
PLAYERS_OUT = os.path.join(DATA_DIR, f"players_{SEASON}.csv")
TEAMS_OUT = os.path.join(DATA_DIR, f"teams_{SEASON}.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari",
}

# Team name -> abbrev map (Basketball-Reference canonical names)
TEAM_NAME_TO_ABBR = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BRK",
    "Charlotte Hornets": "CHO",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHO",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}


# =====================================================
# Helpers
# =====================================================

def http_get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    return r.text


def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            "_".join([str(x) for x in col if str(x) != "nan"]).strip()
            for col in df.columns
        ]
    df.columns = [str(c).strip() for c in df.columns]
    return df


def clean_player_table(df: pd.DataFrame, player_col_guess=("Player", "Player_")) -> pd.DataFrame:
    df = flatten_columns(df).copy()

    # remove repeated headers / separators
    if "Rk" in df.columns:
        df = df[df["Rk"].astype(str) != "Rk"]

    # find player column
    pcol = None
    for c in df.columns:
        if c == "Player" or c.startswith("Player"):
            pcol = c
            break
    if not pcol:
        raise ValueError("Could not detect Player column in players table.")

    # drop blank players
    df = df[df[pcol].notna()]
    df[pcol] = df[pcol].astype(str).str.strip()

    # remove summary rows
    df = df[~df[pcol].str.contains("League Average", na=False)]
    df = df[~df[pcol].str.contains("Player", na=False)]

    return df


def to_num(df: pd.DataFrame, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def prefer_tot_then_max_mp(df: pd.DataFrame) -> pd.DataFrame:
    """
    Basketball-Reference has rows per team + TOT for traded players.
    We keep:
      - TOT row if exists for that player
      - else the row with max MP
    """
    if "Player" not in df.columns:
        # fallback: try detect
        for c in df.columns:
            if c.startswith("Player"):
                df = df.rename(columns={c: "Player"})
                break

    if "Tm" not in df.columns:
        df["Tm"] = "UNK"

    if "MP" not in df.columns:
        df["MP"] = pd.NA

    def pick_group(g):
        g = g.copy()
        if (g["Tm"].astype(str) == "TOT").any():
            return g[g["Tm"].astype(str) == "TOT"].head(1)
        # else max MP
        g["MP_num"] = pd.to_numeric(g["MP"], errors="coerce")
        g = g.sort_values("MP_num", ascending=False)
        return g.head(1)

    out = df.groupby("Player", as_index=False, group_keys=False).apply(pick_group)
    if "MP_num" in out.columns:
        out = out.drop(columns=["MP_num"])
    return out.reset_index(drop=True)


# =====================================================
# Fetch: Players (Per Game + Advanced)
# =====================================================

def fetch_players_per_game() -> pd.DataFrame:
    url = f"https://www.basketball-reference.com/leagues/NBA_{END_YEAR}_per_game.html"
    print(f"[INFO] Fetching players per_game: {url}")
    html = http_get(url)

    tables = pd.read_html(StringIO(html))
    # find table with Player + MP + PTS
    target = None
    for t in tables:
        t = flatten_columns(t)
        cols = set(t.columns.astype(str))
        if ("Player" in cols or any(c.startswith("Player") for c in cols)) and ("MP" in cols) and ("PTS" in cols):
            target = t
            break
    if target is None:
        raise ValueError("Could not find per_game players table.")

    df = clean_player_table(target)

    # normalize player column name
    if "Player" not in df.columns:
        for c in df.columns:
            if c.startswith("Player"):
                df = df.rename(columns={c: "Player"})
                break

    keep = ["Player", "Pos", "Age", "Tm", "G", "GS", "MP", "PTS", "FGA", "3PA", "FTA"]
    # some pages use "3PA" as "3PA" already; if not, try variants
    cols = df.columns.tolist()
    if "3PA" not in cols:
        for c in cols:
            if c.replace(" ", "") in ("3PA", "3PAtt", "3P_Att"):
                df = df.rename(columns={c: "3PA"})
                break

    for c in keep:
        if c not in df.columns:
            df[c] = pd.NA

    df = df[keep].copy()
    df = to_num(df, ["Age", "G", "GS", "MP", "PTS", "FGA", "3PA", "FTA"])

    df = prefer_tot_then_max_mp(df)
    print(f"[OK] players per_game rows: {len(df)}")
    return df


def fetch_players_advanced() -> pd.DataFrame:
    url = f"https://www.basketball-reference.com/leagues/NBA_{END_YEAR}_advanced.html"
    print(f"[INFO] Fetching players advanced: {url}")
    html = http_get(url)

    tables = pd.read_html(StringIO(html))
    target = None
    for t in tables:
        t = flatten_columns(t)
        cols = set(t.columns.astype(str))
        # We want USG%, TS%, TOV%, 3PAr, FTr ideally
        if ("Player" in cols or any(c.startswith("Player") for c in cols)) and any("USG" in c for c in cols) and any("TS" in c for c in cols):
            target = t
            break
    if target is None:
        raise ValueError("Could not find advanced players table.")

    df = clean_player_table(target)

    if "Player" not in df.columns:
        for c in df.columns:
            if c.startswith("Player"):
                df = df.rename(columns={c: "Player"})
                break

    # Column names on bref: "USG%", "TS%", "eFG%", "TOV%", "3PAr", "FTr"
    # Keep only what we need for PTS projection factors
    wanted = ["Player", "Tm", "USG%", "TS%", "eFG%", "TOV%", "3PAr", "FTr"]
    for c in wanted:
        if c not in df.columns:
            df[c] = pd.NA

    df = df[wanted].copy()
    df = to_num(df, ["USG%", "TS%", "eFG%", "TOV%", "3PAr", "FTr"])

    df = prefer_tot_then_max_mp(df)
    print(f"[OK] players advanced rows: {len(df)}")
    return df


def build_players_csv() -> pd.DataFrame:
    per_game = fetch_players_per_game()
    adv = fetch_players_advanced()

    # merge primarily on Player; keep Tm from per_game (TOT selection already)
    df = per_game.merge(
        adv.drop(columns=["Tm"], errors="ignore"),
        how="left",
        on="Player",
        suffixes=("", "_ADV"),
    )

    # Rename to app-friendly names (your app expects PLAYER_NAME, PTS, MIN, TEAM_ID, USG_PCT...)
    out = pd.DataFrame({
        "PLAYER_NAME": df["Player"].astype(str),
        "TEAM_ID": df["Tm"].astype(str),      # TEAM ABBR (ATL, BOS, ...)
        "MIN": df["MP"],
        "PTS": df["PTS"],
        "FGA": df["FGA"],
        "3PA": df["3PA"],
        "FTA": df["FTA"],
        "USG_PCT": df.get("USG%", pd.NA),
        "TS_PCT": df.get("TS%", pd.NA),
        "EFG_PCT": df.get("eFG%", pd.NA),
        "TOV_PCT": df.get("TOV%", pd.NA),
        "TPAR": df.get("3PAr", pd.NA),        # 3PA rate
        "FTR": df.get("FTr", pd.NA),          # FT rate
    })

    # basic cleaning
    out["PLAYER_NAME"] = out["PLAYER_NAME"].str.replace(r"\*", "", regex=True).str.strip()
    out = to_num(out, ["MIN", "PTS", "FGA", "3PA", "FTA", "USG_PCT", "TS_PCT", "EFG_PCT", "TOV_PCT", "TPAR", "FTR"])

    # drop obvious non-players (just in case)
    out = out[out["PLAYER_NAME"].notna()]
    out = out[out["PLAYER_NAME"].astype(str).str.len() > 2]

    return out.reset_index(drop=True)


# =====================================================
# Fetch: Teams (Season summary)
# =====================================================

def fetch_teams_season():
    """
    Robust fetch of team offensive/defensive rating table from league summary page.
    Handles MultiIndex headers and column name variations.
    """
    url = f"https://www.basketball-reference.com/leagues/NBA_{END_YEAR}.html"
    print(f"[INFO] Fetching teams from {url}")

    html = http_get(url)
    tables = pd.read_html(StringIO(html))

    # find table that contains Off/Def ratings
    target = None
    for t in tables:
        t = flatten_columns(t)
        cols = [str(c) for c in t.columns]
        if any("Off" in c for c in cols) and any("Def" in c for c in cols):
            # this is usually "Team Miscellaneous Stats" or similar
            target = t.copy()
            break

    if target is None:
        raise ValueError("Could not find team ratings table.")

    target = flatten_columns(target)
    target.columns = [str(c) for c in target.columns]

    team_col = None
    off_col = None
    def_col = None
    pace_col = None

    for c in target.columns:
        if team_col is None and "Team" in c:
            team_col = c
        if off_col is None and ("Off" in c or "ORtg" in c or "Off_Rtg" in c):
            off_col = c
        if def_col is None and ("Def" in c or "DRtg" in c or "Def_Rtg" in c):
            def_col = c
        if pace_col is None and "Pace" in c:
            pace_col = c

    if not team_col or not off_col or not def_col:
        raise ValueError(f"Could not detect Team/Off/Def columns. Found: {target.columns.tolist()}")

    df = pd.DataFrame({
        "TEAM_NAME": target[team_col].astype(str),
        "OFF_RATING": pd.to_numeric(target[off_col], errors="coerce"),
        "DEF_RATING": pd.to_numeric(target[def_col], errors="coerce"),
    })

    if pace_col:
        df["PACE"] = pd.to_numeric(target[pace_col], errors="coerce")
    else:
        df["PACE"] = pd.NA

    df["NET_RATING"] = df["OFF_RATING"] - df["DEF_RATING"]

    # remove league rows if present
    df = df[~df["TEAM_NAME"].str.contains("League", na=False)]
    df["TEAM_NAME"] = df["TEAM_NAME"].str.strip()

    # add TEAM_ID abbreviation for joining with players TEAM_ID (Tm)
    df["TEAM_ID"] = df["TEAM_NAME"].map(TEAM_NAME_TO_ABBR)

    print(f"[OK] Teams fetched: {len(df)} rows")
    return df.reset_index(drop=True)


# =====================================================
# Main
# =====================================================

def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Players
    players = build_players_csv()
    players.to_csv(PLAYERS_OUT, index=False)
    print(f"[OK] Saved: {PLAYERS_OUT} ({len(players)} rows)")

    # Teams
    teams = fetch_teams_season()
    teams.to_csv(TEAMS_OUT, index=False)
    print(f"[OK] Saved: {TEAMS_OUT} ({len(teams)} rows)")

    print("\n[DONE] Refresh complete ✅")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[ERROR] Refresh failed: {e}", file=sys.stderr)
        raise