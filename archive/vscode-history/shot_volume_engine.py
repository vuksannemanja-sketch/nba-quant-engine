import pandas as pd
import numpy as np
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players


def add_shot_volume_adjustment(df_results, season="2025-26"):

    if df_results is None or df_results.empty:
        return df_results

    df_results = df_results.copy()

    for idx, row in df_results.iterrows():

        try:
            player_dict = players.find_players_by_full_name(row["Player"])
            if not player_dict:
                continue

            player_id = player_dict[0]["id"]

            gamelog = playergamelog.PlayerGameLog(
                player_id=player_id,
                season=season
            ).get_data_frames()[0]

            if gamelog.empty:
                continue

            # Season averages
            season_fga = gamelog["FGA"].mean()
            season_fta = gamelog["FTA"].mean()

            # Recent trend (Last 5)
            recent = gamelog.sort_values("GAME_DATE", ascending=False).head(5)

            recent_fga = recent["FGA"].mean()
            recent_fta = recent["FTA"].mean()

            # Trend factors
            fga_factor = 1
            fta_factor = 1

            if season_fga > 0:
                fga_factor = min(max(recent_fga / season_fga, 0.85), 1.20)

            if season_fta > 0:
                fta_factor = min(max(recent_fta / season_fta, 0.85), 1.20)

            volume_factor = (fga_factor + fta_factor) / 2

            # Adjust projection
            df_results.at[idx, "Final Projection"] *= volume_factor

        except:
            continue

    return df_results
