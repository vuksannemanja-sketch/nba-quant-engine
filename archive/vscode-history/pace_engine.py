from nba_api.stats.endpoints import leaguedashteamstats

def add_pace_adjustment(df_results, season="2025-26"):

    try:
        team_stats = leaguedashteamstats.LeagueDashTeamStats(
            season=season
        ).get_data_frames()[0]

        team_stats = team_stats[["TEAM_ID", "PACE"]]

        for idx, row in df_results.iterrows():

            team_id = row.get("TEAM_ID")

            team_row = team_stats[team_stats["TEAM_ID"] == team_id]

            if team_row.empty:
                continue

            team_pace = team_row.iloc[0]["PACE"]

            pace_factor = team_pace / 100
            pace_factor = min(max(pace_factor, 0.92), 1.08)

            df_results.at[idx, "Final Projection"] *= pace_factor

        return df_results

    except:
        return df_results
