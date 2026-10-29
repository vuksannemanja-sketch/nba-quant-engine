import pandas as pd
import numpy as np
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players

def add_recent_form(df_results, season="2023-24", last_n_games=10):

    recent_projection = []
    recent_hit_rate = []

    for _, row in df_results.iterrows():

        name = row["Player"]
        line = row["Line"]

        try:
            player_dict = players.find_players_by_full_name(name)

            if len(player_dict) == 0:
                recent_projection.append(None)
                recent_hit_rate.append(None)
                continue

            player_id = player_dict[0]['id']
            gamelog = playergamelog.PlayerGameLog(player_id=player_id, season=season)
            df = gamelog.get_data_frames()[0]

            if df.empty:
                recent_projection.append(None)
                recent_hit_rate.append(None)
                continue

            df = df.sort_values("GAME_DATE", ascending=False).head(last_n_games)

            pts = df["PTS"].astype(float)

            mu_recent = pts.mean()
            hit_rate = np.mean(pts > line)

            recent_projection.append(round(mu_recent, 2))
            recent_hit_rate.append(round(hit_rate * 100, 1))

        except:
            recent_projection.append(None)
            recent_hit_rate.append(None)

    df_results["Recent Projection (10G)"] = recent_projection
    df_results["Recent Hit % (10G)"] = recent_hit_rate

    return df_results
