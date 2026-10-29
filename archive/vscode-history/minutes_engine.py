import numpy as np
import pandas as pd
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players


def add_minutes_projection(df_results, season="2025-26"):

    updated_rows = []

    for idx, row in df_results.iterrows():

        try:
            player_dict = players.find_players_by_full_name(row["Player"])
            if not player_dict:
                updated_rows.append(row)
                continue

            player_id = player_dict[0]["id"]

            gamelog = playergamelog.PlayerGameLog(
                player_id=player_id,
                season=season
            ).get_data_frames()[0]

            if gamelog.empty:
                updated_rows.append(row)
                continue

            gamelog = gamelog.sort_values("GAME_DATE")

            season_min = gamelog["MIN"].mean()

            recent = gamelog.tail(5)
            recent_min = recent["MIN"].mean()

            # Linear trend slope
            x = np.arange(len(gamelog))
            y = gamelog["MIN"].values
            if len(x) > 5:
                slope = np.polyfit(x, y, 1)[0]
            else:
                slope = 0

            trend_factor = 1 + (slope / 100)

            minute_factor = recent_min / season_min if season_min > 0 else 1
            minute_factor = min(max(minute_factor, 0.85), 1.25)

            projected_minutes = season_min * minute_factor * trend_factor

            projected_minutes = min(max(projected_minutes, 15), 42)

            row["Projected Minutes AI"] = round(projected_minutes, 1)

            # Adjust projection proportionally
            if season_min > 0:
                minutes_ratio = projected_minutes / season_min
                row["Final Projection"] *= minutes_ratio

        except:
            pass

        updated_rows.append(row)

    return pd.DataFrame(updated_rows)
