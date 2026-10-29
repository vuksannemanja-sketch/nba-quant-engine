import pandas as pd

def add_spread_injury_minute_scaling(df_results, injury_map, season="2025-26"):

    df_results = df_results.copy()

    if "NET_RATING" not in df_results.columns:
        return df_results

    for idx, row in df_results.iterrows():
        try:
            net = abs(row.get("NET_RATING", 0))
            team_id = row.get("TEAM_ID", None)

            # Broj OUT igrača u ligi
            team_injuries = 0

            for name, status in injury_map.items():
                if "out" in status.lower():
                    team_injuries += 1

            # ===== Spread + Injury logika =====

            minute_factor = 1.0

            # Heavy favorite + injuries → blowout risk raste
            if net > 12 and team_injuries >= 1:
                minute_factor = 0.88

            # Favorite bez povreda
            elif net > 12:
                minute_factor = 0.92

            # Balanced game ali ima 2+ povrede → starter minute rastu
            elif net <= 6 and team_injuries >= 2:
                minute_factor = 1.05

            # Underdog sa povredama → pad efikasnosti
            elif net > 8 and team_injuries >= 2:
                minute_factor = 0.93

            df_results.at[idx, "Final Projection"] *= minute_factor

        except:
            continue

    return df_results
