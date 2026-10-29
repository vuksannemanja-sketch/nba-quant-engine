"""
refresh_data.py
Povlaci aktuelne NBA player statistike (main, base, advanced, misc) za tekucu sezonu
i cuva ih kao CSV fajlove u /data folderu.
Pokrece se pritiskom na 'Refresh ALL CSV now' dugme u Streamlit sidebaru.
"""

import os
import time
import pandas as pd

SEASON = "2025-26"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

def get_nba_api():
    try:
        from nba_api.stats.endpoints import leaguedashplayerstats, leaguedashteamstats
        return leaguedashplayerstats, leaguedashteamstats
    except ImportError:
        raise ImportError("nba_api nije instaliran. Dodajte 'nba_api' u requirements.txt")

def fetch_players(measure_type="Base", per_mode="PerGame", season=SEASON):
    leaguedashplayerstats, _ = get_nba_api()
    time.sleep(1.2)
    endpoint = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season,
        measure_type_detailed_defense=measure_type,
        per_mode_simple=per_mode,
        timeout=60,
    )
    df = endpoint.get_data_frames()[0]
    return df

def fetch_teams(measure_type="Base", per_mode="PerGame", season=SEASON):
    _, leaguedashteamstats = get_nba_api()
    time.sleep(1.2)
    endpoint = leaguedashteamstats.LeagueDashTeamStats(
        season=season,
        measure_type_detailed_defense=measure_type,
        per_mode_simple=per_mode,
        timeout=60,
    )
    df = endpoint.get_data_frames()[0]
    return df

def save(df, fname):
    path = os.path.join(DATA_DIR, fname)
    df.to_csv(path, index=False)
    print(f"[refresh_data] Saved {len(df)} rows -> {path}")

def main():
    print("[refresh_data] Pocinje preuzimanje NBA statistika...")

    # --- PLAYERS BASE ---
    try:
        df_base = fetch_players(measure_type="Base")
        save(df_base, f"players_{SEASON}_base.csv")
    except Exception as e:
        print(f"[refresh_data] ERROR players base: {e}")

    # --- PLAYERS ADVANCED ---
    try:
        df_adv = fetch_players(measure_type="Advanced")
        save(df_adv, f"players_{SEASON}_advanced.csv")
    except Exception as e:
        print(f"[refresh_data] ERROR players advanced: {e}")

    # --- PLAYERS MISC ---
    try:
        df_misc = fetch_players(measure_type="Misc")
        save(df_misc, f"players_{SEASON}_misc.csv")
    except Exception as e:
        print(f"[refresh_data] ERROR players misc: {e}")

    # --- PLAYERS MAIN (merge base + advanced) ---
    try:
        base_path = os.path.join(DATA_DIR, f"players_{SEASON}_base.csv")
        adv_path = os.path.join(DATA_DIR, f"players_{SEASON}_advanced.csv")
        if os.path.exists(base_path) and os.path.exists(adv_path):
            df_main = pd.read_csv(base_path)
            df_adv2 = pd.read_csv(adv_path)
            adv_extra = [c for c in df_adv2.columns if c not in df_main.columns or c == "PLAYER_ID"]
            df_merged = df_main.merge(df_adv2[adv_extra].drop_duplicates("PLAYER_ID"), on="PLAYER_ID", how="left")
            save(df_merged, f"players_{SEASON}.csv")
        elif os.path.exists(base_path):
            import shutil
            shutil.copy(base_path, os.path.join(DATA_DIR, f"players_{SEASON}.csv"))
            print(f"[refresh_data] Kopiran base kao main CSV")
    except Exception as e:
        print(f"[refresh_data] ERROR merge main: {e}")

    # --- TEAMS ---
    try:
        df_teams = fetch_teams(measure_type="Advanced")
        save(df_teams, f"teams_{SEASON}.csv")
    except Exception as e:
        print(f"[refresh_data] ERROR teams: {e}")
        try:
            df_teams_base = fetch_teams(measure_type="Base")
            save(df_teams_base, f"teams_{SEASON}.csv")
        except Exception as e2:
            print(f"[refresh_data] ERROR teams base fallback: {e2}")

    print("[refresh_data] Gotovo!")

if __name__ == "__main__":
    main()
