import pandas as pd
import numpy as np
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players
from scipy.stats import linregress

def add_momentum_metrics(df_results, season="2023-24", last_n_games=10):

    weighted_projection = []
    trend_score = []
    heat_status = []

    for _, row in df_results.iterrows():

        name = row["Player"]
        line = row["Line"]

        try:
            player_dict = players.find_players_by_full_name(name)

            if len(player_dict) == 0:
                weighted_projection.append(None)
                trend_score.append(None)
                heat_status.append(None)
                continue

            player_id = player_dict[0]['id']
            gamelog = playergamelog.PlayerGameLog(player_id=player_id, season=season)
            df = gamelog.get_data_frames()[0]

            if df.empty:
                weighted_projection.append(None)
                trend_score.append(None)
                heat_status.append(None)
                continue

            df = df.sort_values("GAME_DATE", ascending=False).head(last_n_games)

            pts = df["PTS"].astype(float).values

            # Weighted average (zadnje 3 imaju veću težinu)
            weights = np.ones(len(pts))
            if len(pts) >= 3:
                weights[:3] = 2

            weighted_avg = np.average(pts, weights=weights)

            # Trend (linearna regresija)
            x = np.arange(len(pts))
            slope, _, _, _, _ = linregress(x, pts)

            # Heat status
            if slope > 0.5:
                status = "HOT"
            elif slope < -0.5:
                status = "COLD"
            else:
                status = "NEUTRAL"

            weighted_projection.append(round(weighted_avg, 2))
            trend_score.append(round(slope, 3))
            heat_status.append(status)

        except:
            weighted_projection.append(None)
            trend_score.append(None)
            heat_status.append(None)

    df_results["Weighted Projection"] = weighted_projection
    df_results["Trend Slope"] = trend_score
    df_results["Heat Status"] = heat_status

    return df_results
