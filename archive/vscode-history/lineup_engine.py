import pandas as pd
from nba_api.stats.endpoints import playergamelog

def add_lineup_onoff_adjustment(df_results, season="2025-26"):

    df_results = df_results.copy()

    for idx, row in df_results.iterrows():

        try:
            player_id = row.get("PLAYER_ID", None)
            if not player_id:
                continue

            gamelog = playergamelog.PlayerGameLog(
                player_id=player_id,
                season=season
            ).get_data_frames()[0]

            if gamelog.empty:
                continue

            season_pts = gamelog["PTS"].mean()
            last10_pts = gamelog["PTS"].tail(10).mean()

            # Ako je zadnjih 10 znatno iznad sezone → usage shift real
            if season_pts > 0:
                shift = last10_pts / season_pts
                shift = min(max(shift, 0.9), 1.15)

                df_results.at[idx, "Final Projection"] *= shift

        except:
            continue

    return df_results
