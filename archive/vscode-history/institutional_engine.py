import pandas as pd
import numpy as np
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players

def add_institutional_layer(df_results, season="2025-26"):

    enhanced_rows = []

    for _, row in df_results.iterrows():

        name = row["Player"]

        try:
            player_dict = players.find_players_by_full_name(name)

            if len(player_dict) == 0:
                enhanced_rows.append(row)
                continue

            player_id = player_dict[0]["id"]

            gamelog = playergamelog.PlayerGameLog(
                player_id=player_id,
                season=season
            ).get_data_frames()[0]

            if gamelog.empty:
                enhanced_rows.append(row)
                continue

            gamelog = gamelog.sort_values("GAME_DATE", ascending=False)

            # LAST 5 WEIGHTED
            last5 = gamelog.head(5)
            pts_last5 = last5["PTS"].values

            weights = np.array([2, 2, 1.5, 1, 1])[:len(pts_last5)]
            weighted_form = np.average(pts_last5, weights=weights)

            # MINUTE STABILITY
            minutes = last5["MIN"].astype(float)
            minute_cv = minutes.std() / minutes.mean() if minutes.mean() != 0 else 1
            minute_stability = max(0, 100 * (1 - minute_cv))

            # USAGE PROXY
            usage_proxy = last5["FGA"].mean() + last5["FTA"].mean()

            institutional_score = (
                0.4 * weighted_form +
                0.2 * row["Projection"] +
                0.2 * minute_stability +
                0.1 * usage_proxy +
                0.1 * row["Best EV %"]
            )

            new_row = row.copy()
            new_row["Weighted Form"] = round(weighted_form, 2)
            new_row["Minute Stability"] = round(minute_stability, 1)
            new_row["Usage Proxy"] = round(usage_proxy, 1)
            new_row["Institutional Advanced Score"] = round(institutional_score, 2)

            enhan^ced_rows.append(new_row)

        except:
            enhanced_rows.append(row)

    return pd.DataFrame(enhanced_rows)
