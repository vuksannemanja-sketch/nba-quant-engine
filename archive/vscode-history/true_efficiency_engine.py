import numpy as np
from nba_api.stats.endpoints import leaguedashplayerstats

def add_true_efficiency(df_results, season="2025-26"):

    df_results = df_results.copy()

    season_stats = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season
    ).get_data_frames()[0]

    for idx, row in df_results.iterrows():
        try:
            player_id = row.get("PLAYER_ID", None)

            if player_id is None:
                continue

            player_row = season_stats[season_stats["PLAYER_ID"] == player_id]

            if player_row.empty:
                continue

            usg = player_row.iloc[0].get("USG_PCT", 20)
            ts = player_row.iloc[0].get("TS_PCT", 0.55)

            efficiency_factor = (usg / 20) * (ts / 0.55)

            df_results.at[idx, "Final Projection"] *= efficiency_factor

        except:
            continue

    return df_results
