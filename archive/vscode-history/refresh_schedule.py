"""
refresh_schedule.py
Fetchuje NBA 2025-26 raspored s NBA API i sprema u data/schedule_2025-26.csv
Pokreni: python refresh_schedule.py
"""

import os
import time
import pandas as pd
from datetime import datetime, timedelta

# ── NBA API import ────────────────────────────────────────────
try:
    from nba_api.stats.endpoints import leaguegamelog
    from nba_api.stats.static import teams as nba_teams_static
    NBA_API_OK = True
except ImportError:
    NBA_API_OK = False

# ── Config ────────────────────────────────────────────────────
SEASON      = "2025-26"
DATA_DIR    = os.path.join(os.getcwd(), "data")
OUT_PATH    = os.path.join(DATA_DIR, f"schedule_{SEASON}.csv")
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

def fetch_via_nba_api():
    """Fetchuje game log za sezonu i rekonstruira raspored."""
    print("Fetchujem game log s NBA API...")

    all_rows = []
    for season_type in ["Regular Season", "Playoffs"]:
        try:
            gl = leaguegamelog.LeagueGameLog(
                season=SEASON,
                season_type_all_star=season_type,
                league_id="00",
                timeout=60,
            )
            df = gl.get_data_frames()[0]
            all_rows.append(df)
            print(f"  ✅ {season_type}: {len(df)} redova")
            time.sleep(1.5)
        except Exception as e:
            print(f"  ⚠️  {season_type} fetch fail: {e}")

    if not all_rows:
        return None

    df = pd.concat(all_rows, ignore_index=True)

    # Normalizacija
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["TEAM_ABBR"] = pd.to_numeric(df["TEAM_ID"], errors="coerce").map(TEAM_ID_TO_ABBR)

    # Odvojimo HOME i AWAY po MATCHUP koloni (npr. "DET vs. MEM" ili "DET @ MEM")
    df["IS_HOME"] = df["MATCHUP"].str.contains(" vs\\. ", na=False)

    home = df[df["IS_HOME"]][["GAME_ID", "GAME_DATE", "TEAM_ABBR"]].rename(
        columns={"TEAM_ABBR": "HOME_TEAM_ABBR"}
    )
    away = df[~df["IS_HOME"]][["GAME_ID", "TEAM_ABBR"]].rename(
        columns={"TEAM_ABBR": "AWAY_TEAM_ABBR"}
    )

    schedule = home.merge(away, on="GAME_ID", how="inner")
    schedule = schedule[["GAME_DATE", "HOME_TEAM_ABBR", "AWAY_TEAM_ABBR", "GAME_ID"]]
    schedule = schedule.drop_duplicates("GAME_ID").sort_values("GAME_DATE")

    return schedule


def build_b2b_flags(schedule: pd.DataFrame) -> pd.DataFrame:
    """
    Dodaje B2B flag za svaki tim po datumu.
    Output kolone: GAME_DATE, TEAM_ABBR, IS_B2B (bool)
    """
    rows = []
    # Svaki red rasporeda → 2 tima
    for _, row in schedule.iterrows():
        for team_col in ["HOME_TEAM_ABBR", "AWAY_TEAM_ABBR"]:
            team = row.get(team_col)
            if pd.notna(team):
                rows.append({"GAME_DATE": row["GAME_DATE"], "TEAM_ABBR": team})

    team_dates = pd.DataFrame(rows).drop_duplicates()
    team_dates["GAME_DATE"] = pd.to_datetime(team_dates["GAME_DATE"])
    team_dates = team_dates.sort_values(["TEAM_ABBR", "GAME_DATE"])

    # B2B = tim je igrao i jučer
    team_dates["PREV_DATE"] = team_dates.groupby("TEAM_ABBR")["GAME_DATE"].shift(1)
    team_dates["IS_B2B"] = (
        (team_dates["GAME_DATE"] - team_dates["PREV_DATE"]).dt.days == 1
    )
    team_dates["GAME_DATE"] = team_dates["GAME_DATE"].dt.strftime("%Y-%m-%d")
    return team_dates[["GAME_DATE", "TEAM_ABBR", "IS_B2B"]]


def main():
    if not NBA_API_OK:
        print("❌ nba_api nije instaliran. Pokreni: pip install nba_api")
        print("   Generišem primjer CSV s praznim podacima...")
        # Generiraj prazan template
        schedule = pd.DataFrame(columns=["GAME_DATE", "HOME_TEAM_ABBR", "AWAY_TEAM_ABBR", "GAME_ID"])
        b2b = pd.DataFrame(columns=["GAME_DATE", "TEAM_ABBR", "IS_B2B"])
    else:
        schedule = fetch_via_nba_api()
        if schedule is None or schedule.empty:
            print("❌ Nije moguće fetchovati raspored.")
            return
        b2b = build_b2b_flags(schedule)

    # Spremi oba fajla
    schedule_path = os.path.join(DATA_DIR, f"schedule_{SEASON}.csv")
    b2b_path      = os.path.join(DATA_DIR, f"b2b_{SEASON}.csv")

    schedule.to_csv(schedule_path, index=False)
    b2b.to_csv(b2b_path, index=False)

    print(f"\n✅ Raspored snimljen: {schedule_path}  ({len(schedule)} utakmica)")
    print(f"✅ B2B flags snimljeni: {b2b_path}  ({len(b2b)} redova)")

    if not b2b.empty:
        b2b_count = b2b["IS_B2B"].sum()
        print(f"   B2B situacija: {b2b_count} team-dana")


if __name__ == "__main__":
    main()