"""
refresh_matchups.py
Fetchuje NBA matchup i forma podatke i sprema:
  - data/def_matchup_2025-26.csv    (defanzivni matchup po poziciji)
  - data/off_matchup_2025-26.csv    (ofanzivni matchup po timu)
  - data/form_l10_2025-26.csv       (L3/L5/L10 forma za svakog igrača)

Pokretanje: python refresh_matchups.py
"""

import os
import time
import numpy as np
import pandas as pd
from datetime import datetime

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

# =====================================================
# DEF Matchup — koliko bodova tim dopušta po poziciji
# =====================================================

def fetch_def_matchup():
    """
    Koristi leaguedashptdefend koji daje defensive matchup po poziciji.
    """
    print("  Fetchujem DEF matchup po poziciji...")
    try:
        from nba_api.stats.endpoints import leaguedashptdefend

        rows = []
        for defense_category in ["Overall", "3 Pointers", "2 Pointers", "Less Than 6Ft"]:
            try:
                ep = leaguedashptdefend.LeagueDashPtDefend(
                    season=SEASON,
                    defense_category=defense_category,
                    per_mode_simple="PerGame",
                    season_type_all_star="Regular Season",
                    timeout=60,
                )
                df = ep.get_data_frames()[0]
                df["DEFENSE_CATEGORY"] = defense_category
                rows.append(df)
                time.sleep(1.2)
            except Exception as e:
                print(f"    ⚠️  {defense_category}: {e}")

        if not rows:
            return None

        combined = pd.concat(rows, ignore_index=True)
        combined["TEAM_ABBR"] = pd.to_numeric(
            combined.get("TEAM_ID", pd.Series(dtype=float)), errors="coerce"
        ).map(TEAM_ID_TO_ABBR)

        out_path = os.path.join(DATA_DIR, f"def_matchup_{SEASON}.csv")
        combined.to_csv(out_path, index=False)
        print(f"  ✅ DEF matchup: {len(combined)} redova → {os.path.basename(out_path)}")
        return combined

    except ImportError:
        print("  ⚠️  nba_api nije dostupan")
        return None
    except Exception as e:
        print(f"  ❌ DEF matchup FAIL: {e}")
        return None

# =====================================================
# OFF Matchup — koliko bodova tim daje protivnicima
# =====================================================

def fetch_off_matchup():
    """
    Koristi leaguedashteamstats za ofanzivni matchup.
    Daje OFF_RATING, PACE, PTS po timu.
    """
    print("  Fetchujem OFF matchup po timu...")
    try:
        from nba_api.stats.endpoints import leaguedashteamstats

        ep = leaguedashteamstats.LeagueDashTeamStats(
            season=SEASON,
            measure_type_detailed_defense="Advanced",
            per_mode_detailed="PerGame",
            season_type_all_star="Regular Season",
            timeout=60,
        )
        df = ep.get_data_frames()[0]
        df["TEAM_ABBR"] = pd.to_numeric(df["TEAM_ID"], errors="coerce").map(TEAM_ID_TO_ABBR)

        out_path = os.path.join(DATA_DIR, f"off_matchup_{SEASON}.csv")
        df.to_csv(out_path, index=False)
        print(f"  ✅ OFF matchup: {len(df)} timova → {os.path.basename(out_path)}")
        return df

    except Exception as e:
        print(f"  ❌ OFF matchup FAIL: {e}")
        return None

# =====================================================
# L3 / L5 / L10 forma — zadnjih N utakmica za svakog igrača
# =====================================================

def fetch_player_form():
    """
    Koristi playergamelogs za zadnjih 10 utakmica svakog igrača.
    Računa L3, L5, L10 prosjek, std i trend slope.
    """
    print("  Fetchujem L10 formu igrača (game logs)...")
    try:
        from nba_api.stats.endpoints import leaguegamelog

        ep = leaguegamelog.LeagueGameLog(
            season=SEASON,
            season_type_all_star="Regular Season",
            player_or_team_abbreviation="P",  # Player
            sorter="DATE",
            direction="DESC",
            timeout=90,
        )
        gl = ep.get_data_frames()[0]
        print(f"  Game log: {len(gl)} zapisa")

        if gl.empty:
            return None

        # Kolone koje trebamo
        needed = ["PLAYER_NAME", "PLAYER_ID", "GAME_DATE", "PTS", "MIN", "TEAM_ABBREVIATION"]
        existing = [c for c in needed if c in gl.columns]
        gl = gl[existing].copy()

        if "PLAYER_NAME" not in gl.columns and "PLAYER_ID" in gl.columns:
            gl["PLAYER_NAME"] = gl["PLAYER_ID"].astype(str)

        gl["GAME_DATE"] = pd.to_datetime(gl["GAME_DATE"], errors="coerce")
        gl["PTS"]       = pd.to_numeric(gl["PTS"], errors="coerce")
        gl["MIN"]       = pd.to_numeric(
            gl["MIN"].astype(str).str.replace(":", ".").str.split(".").str[0],
            errors="coerce"
        )

        # Sortiraj po igraču i datumu (najnovije prvo)
        gl = gl.sort_values(["PLAYER_NAME", "GAME_DATE"], ascending=[True, False])

        form_rows = []
        for player_name, grp in gl.groupby("PLAYER_NAME"):
            grp = grp.reset_index(drop=True)

            pts_list = grp["PTS"].dropna().tolist()
            min_list = grp["MIN"].dropna().tolist()

            if len(pts_list) == 0:
                continue

            l3  = float(np.mean(pts_list[:3]))  if len(pts_list) >= 3  else float(np.mean(pts_list))
            l5  = float(np.mean(pts_list[:5]))  if len(pts_list) >= 5  else float(np.mean(pts_list))
            l10 = float(np.mean(pts_list[:10])) if len(pts_list) >= 10 else float(np.mean(pts_list))
            l10_std  = float(np.std(pts_list[:10]))  if len(pts_list) >= 3  else 0.0
            last_pts = float(pts_list[0])        if len(pts_list) >= 1  else 0.0
            l10_min  = float(np.mean(min_list[:10])) if len(min_list) >= 3  else 0.0

            # Trend slope — linearna regresija na zadnjih 10 utakmica
            # Pozitivan = igrač raste, negativan = pada
            trend_slope = 0.0
            pts_for_trend = pts_list[:10]
            if len(pts_for_trend) >= 3:
                try:
                    x = np.arange(len(pts_for_trend))
                    # Obrnuti redoslijed: zadnja utakmica je zadnja točka
                    y = np.array(pts_for_trend[::-1], dtype=float)
                    coeffs = np.polyfit(x, y, 1)
                    trend_slope = float(coeffs[0])
                except Exception:
                    pass

            team_abbr = grp["TEAM_ABBREVIATION"].iloc[0] if "TEAM_ABBREVIATION" in grp.columns else ""

            form_rows.append({
                "PLAYER_NAME":  player_name,
                "TEAM_ABBR":    str(team_abbr).strip(),
                "L3_PTS":       round(l3, 2),
                "L5_PTS":       round(l5, 2),
                "L10_PTS":      round(l10, 2),
                "L10_STD":      round(l10_std, 2),
                "L10_MIN":      round(l10_min, 2),
                "LAST_PTS":     round(last_pts, 2),
                "TREND_SLOPE":  round(trend_slope, 3),
                "GAMES_PLAYED": len(pts_list),
                "LAST_DATE":    grp["GAME_DATE"].iloc[0].strftime("%Y-%m-%d") if not pd.isna(grp["GAME_DATE"].iloc[0]) else "",
            })

        form_df = pd.DataFrame(form_rows).sort_values("PLAYER_NAME").reset_index(drop=True)
        out_path = os.path.join(DATA_DIR, f"form_l10_{SEASON}.csv")
        form_df.to_csv(out_path, index=False)
        print(f"  ✅ L10 forma: {len(form_df)} igrača → {os.path.basename(out_path)}")
        return form_df

    except Exception as e:
        print(f"  ❌ L10 forma FAIL: {e}")
        return None

# =====================================================
# Main
# =====================================================

def main():
    print("=" * 55)
    print("  refresh_matchups.py — DEF/OFF Matchup + L10 Forma")
    print("=" * 55)

    fetch_def_matchup()
    time.sleep(2)

    fetch_off_matchup()
    time.sleep(2)

    fetch_player_form()

    print("=" * 55)
    print("  refresh_matchups.py ZAVRŠEN")
    print("=" * 55)

if __name__ == "__main__":
    main()