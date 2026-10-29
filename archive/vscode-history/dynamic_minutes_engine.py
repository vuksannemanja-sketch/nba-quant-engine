import numpy as np
from nba_api.stats.endpoints import playergamelog

def add_dynamic_minutes(df_results, season="2025-26"):

    df_results = df_results.copy()

    for idx, row in df_results.iterrows():
        try:
            from nba_api.stats.static import players
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

            last5 = gamelog.sort_values("GAME_DATE", ascending=False).head(5)

            projected_minutes = last5["MIN"].mean()

            season_minutes = gamelog["MIN"].mean()

            minute_factor = projected_minutes / season_minutes if season_minutes else 1
            minute_factor = min(max(minute_factor, 0.85), 1.25)

            df_results.at[idx, "Final Projection"] *= minute_factor

        except:
            continue

    return df_results
