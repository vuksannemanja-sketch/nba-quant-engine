"""
refresh_h2h.py
Fetchuje H2H statistike — koliko svaki igrač prosječno skori
protiv specifičnih protivnika u zadnje 2-3 sezone.

Sprema:
  - data/h2h_2025-26.csv

Format: PLAYER_NAME, OPP_TEAM, H2H_PTS_AVG, H2H_GAMES, H2H_PTS_LAST

Pokretanje: python refresh_h2h.py
"""

import os
import time
import numpy as np
import pandas as pd
from datetime import datetime

# =====================================================
# CONFIG
# =====================================================

SEASONS  = ["2025-26", "2024-25", "2023-24"]  # zadnje 3 sezone za H2H
DATA_DIR = os.path.join(os.getcwd(), "data")
os.makedirs(DATA_DIR, exist_ok=True)

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

# =====================================================
# Fetchuj game log za sve sezone
# =====================================================

def fetch_all_game_logs(seasons: list) -> pd.DataFrame:
    """
    Fetchuje player game log za svaku sezonu i spaja ih.
    Svaki red = jedna utakmica jednog igrača.
    """
    from nba_api.stats.endpoints import leaguegamelog

    all_dfs = []
    for season in seasons:
        print(f"  Fetchujem game log {season}...")
        try:
            ep = leaguegamelog.LeagueGameLog(
                season=season,
                season_type_all_star="Regular Season",
                player_or_team_abbreviation="P",
                sorter="DATE",
                direction="DESC",
                timeout=90,
            )
            df = ep.get_data_frames()[0]
            df["SEASON"] = season
            all_dfs.append(df)
            print(f"  ✅ {season}: {len(df)} zapisa")
            time.sleep(2.0)
        except Exception as e:
            print(f"  ❌ {season} FAIL: {e}")

    if not all_dfs:
        return pd.DataFrame()

    return pd.concat(all_dfs, ignore_index=True)

# =====================================================
# Izvuci H2H iz game loga
# =====================================================

def extract_matchup_opponent(matchup_str: str, player_team: str) -> str:
    """
    Iz MATCHUP kolone (npr. "DET vs. MEM" ili "DET @ MEM")
    izvuci protivnički tim.
    """
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

    # Protivnik je onaj koji nije player_team
    if parts[0].strip() == p:
        return parts[1].strip()
    elif parts[1].strip() == p:
        return parts[0].strip()
    return ""

def compute_h2h(gl: pd.DataFrame) -> pd.DataFrame:
    """
    Iz game loga izračunava H2H prosjek za svakog igrača
    protiv svakog protivnika.
    """
    if gl.empty:
        return pd.DataFrame()

    # Normalizacija kolona
    rename = {}
    for c in gl.columns:
        cl = c.upper()
        if cl in ["PLAYER_NAME", "PLAYER"]:       rename[c] = "PLAYER_NAME"
        elif cl == "MATCHUP":                      rename[c] = "MATCHUP"
        elif cl in ["TEAM_ABBREVIATION", "TEAM"]: rename[c] = "TEAM_ABBR"
        elif cl == "PTS":                          rename[c] = "PTS"
        elif cl == "GAME_DATE":                    rename[c] = "GAME_DATE"
        elif cl == "SEASON":                       rename[c] = "SEASON"
    gl = gl.rename(columns=rename)

    needed = ["PLAYER_NAME", "MATCHUP", "TEAM_ABBR", "PTS", "GAME_DATE"]
    missing = [c for c in needed if c not in gl.columns]
    if missing:
        print(f"  ⚠️  H2H: nedostaju kolone: {missing}")
        return pd.DataFrame()

    gl["PTS"]       = pd.to_numeric(gl["PTS"], errors="coerce")
    gl["GAME_DATE"] = pd.to_datetime(gl["GAME_DATE"], errors="coerce")
    gl = gl.dropna(subset=["PTS", "GAME_DATE", "PLAYER_NAME"])

    # Izvuci protivnički tim
    gl["OPP_TEAM"] = gl.apply(
        lambda r: extract_matchup_opponent(r.get("MATCHUP", ""), r.get("TEAM_ABBR", "")),
        axis=1
    )
    gl = gl[gl["OPP_TEAM"] != ""]

    # Sortiraj po datumu (najnovije prvo)
    gl = gl.sort_values(["PLAYER_NAME", "OPP_TEAM", "GAME_DATE"], ascending=[True, True, False])

    # Agregiraj po igraču + protivnik
    h2h_rows = []
    for (player, opp), grp in gl.groupby(["PLAYER_NAME", "OPP_TEAM"]):
        pts_list = grp["PTS"].tolist()
        if len(pts_list) == 0:
            continue

        h2h_avg  = float(np.mean(pts_list))
        h2h_games= len(pts_list)
        h2h_last = float(pts_list[0])   # zadnja utakmica (najnovija)
        h2h_std  = float(np.std(pts_list)) if len(pts_list) > 1 else 0.0
        last_date= grp["GAME_DATE"].iloc[0].strftime("%Y-%m-%d")

        h2h_rows.append({
            "PLAYER_NAME":   player,
            "OPP_TEAM":      opp,
            "H2H_PTS_AVG":   round(h2h_avg,  2),
            "H2H_GAMES":     h2h_games,
            "H2H_PTS_LAST":  round(h2h_last, 2),
            "H2H_PTS_STD":   round(h2h_std,  2),
            "H2H_LAST_DATE": last_date,
        })

    h2h_df = pd.DataFrame(h2h_rows)
    return h2h_df

# =====================================================
# Filtriraj — samo relevantni H2H (min 2 utakmice)
# =====================================================

def filter_relevant_h2h(h2h_df: pd.DataFrame, min_games: int = 2) -> pd.DataFrame:
    if h2h_df.empty:
        return h2h_df
    filtered = h2h_df[h2h_df["H2H_GAMES"] >= min_games].copy()
    filtered = filtered.sort_values(
        ["PLAYER_NAME", "H2H_GAMES"],
        ascending=[True, False]
    ).reset_index(drop=True)
    return filtered

# =====================================================
# Main
# =====================================================

def main():
    print("=" * 55)
    print("  refresh_h2h.py — Head-to-Head Stats")
    print("=" * 55)

    try:
        import nba_api
    except ImportError:
        print("❌ nba_api nije instaliran: pip install nba_api")
        return

    # Fetchuj game logove
    gl = fetch_all_game_logs(SEASONS)

    if gl.empty:
        print("❌ Nema game log podataka.")
        return

    print(f"\n  Ukupno zapisa: {len(gl)}")
    print("  Računam H2H prosjeke...")

    # Izračunaj H2H
    h2h_df = compute_h2h(gl)

    if h2h_df.empty:
        print("❌ H2H izračun nije uspio.")
        return

    # Filtriraj
    h2h_filtered = filter_relevant_h2h(h2h_df, min_games=2)

    # Spremi
    season_main = SEASONS[0]
    out_path = os.path.join(DATA_DIR, f"h2h_{season_main}.csv")
    h2h_filtered.to_csv(out_path, index=False)

    print(f"\n  ✅ H2H snimljen: {len(h2h_filtered)} kombinacija → {os.path.basename(out_path)}")

    # Preview statistika
    print(f"\n  Distribucija H2H utakmica:")
    bins = h2h_filtered.groupby("H2H_GAMES").size()
    for games, count in bins.items():
        print(f"    {games} utakmica: {count} kombinacija")

    # Provjera: igrači s najviše H2H podataka
    top_players = (
        h2h_filtered.groupby("PLAYER_NAME")["H2H_GAMES"].sum()
        .sort_values(ascending=False)
        .head(5)
    )
    print(f"\n  Top 5 igrača s najviše H2H podataka:")
    for player, games in top_players.items():
        print(f"    {player}: {games} H2H utakmica")

    print("=" * 55)
    print("  refresh_h2h.py ZAVRŠEN")
    print("=" * 55)

if __name__ == "__main__":
    main()