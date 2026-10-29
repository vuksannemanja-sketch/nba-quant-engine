import pandas as pd
from nba_api.stats.endpoints import leaguedashteamstats

def add_dvp_adjustment(df_results, season="2025-26"):

    try:
        team_stats = leaguedashteamstats.LeagueDashTeamStats(
            season=season
        ).get_data_frames()[0]

        # koristimo DEF_RATING kao proxy za defense vs position
        league_def = team_stats["DEF_RATING"].mean()

        df_results = df_results.copy()

        dvp_factors = []

        for idx, row in df_results.iterrows():

            team_id = row.get("TEAM_ID")

            team_row = team_stats[team_stats["TEAM_ID"] == team_id]

            if team_row.empty:
                dvp_factors.append(1.0)
                continue

            team_def = team_row.iloc[0]["DEF_RATING"]

            # Bolja odbrana → smanjuje projekciju
            factor = league_def / team_def

            # Ograničenje da ne poludi model
            factor = min(max(factor, 0.90), 1.10)

            dvp_factors.append(factor)

        df_results["DVP Factor"] = dvp_factors
        df_results["Final Projection"] = df_results["Final Projection"] * df_results["DVP Factor"]

    except:
        pass

    return df_results
