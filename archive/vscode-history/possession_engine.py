import numpy as np
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players


def add_possession_projection(df_results, season="2025-26"):

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

            # Approx possessions formula
            gamelog["EST_POS"] = (
                gamelog["FGA"]
                + 0.44 * gamelog["FTA"]
                + gamelog["TOV"]
            )

            season_pos = gamelog["EST_POS"].mean()
            season_pts = gamelog["PTS"].mean()

            if season_pos <= 0:
                continue

            # Points per possession
            ppp = season_pts / season_pos

            # Recent trend
            recent = gamelog.sort_values("GAME_DATE", ascending=False).head(5)

            recent_pos = (
                recent["FGA"]
                + 0.44 * recent["FTA"]
                + recent["TOV"]
            ).mean()

            pos_factor = 1

            if season_pos > 0:
                pos_factor = min(max(recent_pos / season_pos, 0.85), 1.20)

            # New projection
            projected_pos = season_pos * pos_factor
            new_projection = projected_pos * ppp

            # Blend sa postojećim projection (anti-overfit)
            df_results.at[idx, "Final Projection"] = (
                df_results.at[idx, "Final Projection"] * 0.6
                + new_projection * 0.4
            )

        except:
            continue

    return df_results
