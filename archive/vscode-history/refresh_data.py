"""
refresh_data.py
Fetchuje NBA player statistike za sezonu 2025-26 s NBA API i sprema CSV-ove:
  - data/players_2025-26.csv          (general stats)
  - data/players_2025-26_base.csv     (base stats)
  - data/players_2025-26_advanced.csv (advanced stats)
  - data/players_2025-26_misc.csv     (misc stats)

Pokretanje: python refresh_data.py
"""

import os
import time
import pandas as pd
from nba_api.stats.endpoints import (
    leaguedashplayerstats,
    leaguedashplayerbiostats,
)

# =====================================================
# CONFIG
# =====================================================

SEASON   = "2025-26"
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

def add_team_abbr(df):
    if "TEAM_ID" in df.columns:
        df["TEAM_ABBR"] = pd.to_numeric(df["TEAM_ID"], errors="coerce").map(TEAM_ID_TO_ABBR)
    return df

def fetch_and_save(label, endpoint_fn, out_path, measure_type=None, per_mode="PerGame"):
    print(f"  Fetchujem {label}...")
    try:
        kwargs = dict(
            season=SEASON,
            season_type_all_star="Regular Season",
            per_mode_detailed=per_mode,
            timeout=60,
        )
        if measure_type:
            kwargs["measure_type_detailed_defense"] = measure_type

        ep  = endpoint_fn(**kwargs)
        df  = ep.get_data_frames()[0]
        df  = add_team_abbr(df)
        df.to_csv(out_path, index=False)
        print(f"  ✅ {label}: {len(df)} igrača → {os.path.basename(out_path)}")
        return df
    except Exception as e:
        print(f"  ❌ {label} FAIL: {e}")
        return None

def main():
    print("=" * 55)
    print("  refresh_data.py — NBA Player Stats")
    print("=" * 55)

    # 1. Base stats (PTS, REB, AST, MIN, GP, FG%, FT%, 3P%)
    fetch_and_save(
        label        = "Base Stats",
        endpoint_fn  = leaguedashplayerstats.LeagueDashPlayerStats,
        out_path     = os.path.join(DATA_DIR, f"players_{SEASON}_base.csv"),
        measure_type = "Base",
    )
    time.sleep(2)

    # 2. Advanced stats (USG%, TS%, PIE, NET_RATING, OFF_RATING, DEF_RATING)
    fetch_and_save(
        label        = "Advanced Stats",
        endpoint_fn  = leaguedashplayerstats.LeagueDashPlayerStats,
        out_path     = os.path.join(DATA_DIR, f"players_{SEASON}_advanced.csv"),
        measure_type = "Advanced",
    )
    time.sleep(2)

    # 3. Misc stats (PTS_PAINT, PTS_FB, PTS_2ND_CHANCE, PTS_OFF_TOV)
    fetch_and_save(
        label        = "Misc Stats",
        endpoint_fn  = leaguedashplayerstats.LeagueDashPlayerStats,
        out_path     = os.path.join(DATA_DIR, f"players_{SEASON}_misc.csv"),
        measure_type = "Misc",
    )
    time.sleep(2)

    # 4. Bio stats (HEIGHT, WEIGHT, DRAFT info) — korisno za poziciju
    print("  Fetchujem Bio Stats...")
    try:
        bio = leaguedashplayerbiostats.LeagueDashPlayerBioStats(
            season=SEASON,
            timeout=60,
        )
        bio_df = bio.get_data_frames()[0]
        bio_df = add_team_abbr(bio_df)

        # Spoji bio i base u main players CSV
        base_path = os.path.join(DATA_DIR, f"players_{SEASON}_base.csv")
        if os.path.exists(base_path):
            base_df = pd.read_csv(base_path)
            # Dodaj HEIGHT/WEIGHT ako postoje
            bio_cols = ["PLAYER_ID", "PLAYER_HEIGHT_INCHES", "PLAYER_WEIGHT",
                        "COLLEGE", "COUNTRY", "DRAFT_YEAR", "DRAFT_ROUND", "DRAFT_NUMBER"]
            bio_cols = [c for c in bio_cols if c in bio_df.columns]
            merged   = base_df.merge(bio_df[bio_cols], on="PLAYER_ID", how="left") if "PLAYER_ID" in base_df.columns else base_df
        else:
            merged = bio_df

        main_path = os.path.join(DATA_DIR, f"players_{SEASON}.csv")
        merged.to_csv(main_path, index=False)
        print(f"  ✅ Bio + Main: {len(merged)} igrača → {os.path.basename(main_path)}")
    except Exception as e:
        print(f"  ❌ Bio Stats FAIL: {e}")
        # Fallback: kopiraj base kao main
        base_path = os.path.join(DATA_DIR, f"players_{SEASON}_base.csv")
        main_path = os.path.join(DATA_DIR, f"players_{SEASON}.csv")
        if os.path.exists(base_path) and not os.path.exists(main_path):
            import shutil
            shutil.copy(base_path, main_path)
            print(f"  ℹ️  Koristim base kao main: {os.path.basename(main_path)}")

    # 5. Team stats
    print("  Fetchujem Team Stats...")
    try:
        from nba_api.stats.endpoints import leaguedashteamstats
        time.sleep(1.5)
        team_base = leaguedashteamstats.LeagueDashTeamStats(
            season=SEASON,
            measure_type_detailed_defense="Base",
            per_mode_detailed="PerGame",
            timeout=60,
        )
        tdf = team_base.get_data_frames()[0]
        tdf["TEAM_ABBR"] = pd.to_numeric(tdf["TEAM_ID"], errors="coerce").map(TEAM_ID_TO_ABBR)
        time.sleep(1.5)

        team_adv = leaguedashteamstats.LeagueDashTeamStats(
            season=SEASON,
            measure_type_detailed_defense="Advanced",
            per_mode_detailed="PerGame",
            timeout=60,
        )
        tadv = team_adv.get_data_frames()[0]
        adv_cols = [c for c in ["TEAM_ID", "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE", "PIE"]
                    if c in tadv.columns]
        tdf = tdf.merge(tadv[adv_cols], on="TEAM_ID", how="left") if "TEAM_ID" in tdf.columns else tdf

        team_path = os.path.join(DATA_DIR, f"teams_{SEASON}.csv")
        tdf.to_csv(team_path, index=False)
        print(f"  ✅ Teams: {len(tdf)} timova → {os.path.basename(team_path)}")
    except Exception as e:
        print(f"  ❌ Team Stats FAIL: {e}")

    print("=" * 55)
    print("  refresh_data.py ZAVRŠEN")
    print("=" * 55)

if __name__ == "__main__":
    main()