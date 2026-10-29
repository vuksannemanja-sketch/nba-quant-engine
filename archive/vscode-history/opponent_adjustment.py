import pandas as pd
import numpy as np
from nba_api.stats.endpoints import leaguedashteamstats, playergamelog
from nba_api.stats.static import players

def add_opponent_defense_adjustment(df_results, season="2025-26"):

    try:
        team_stats = leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            measure_type_detailed_defense="Advanced"
        ).get_data_frames()[0]

        league_avg_def = team_stats["DEF_RATING"].mean()

    except:
        return df_results

    adjusted_rows = []

    for _, row in df_results.iterrows():

        name = row["Player"]

        try:
            player_dict = players.find_players_by_full_name(name)
            if len(player_dict) == 0:
                adjusted_rows.append(row)
                continue

            player_id = player_dict[0]["id"]

            gamelog = playergamelog.PlayerGameLog(
                player_id=player_id,
                season=season
            ).get_data_frames()[0]

            if gamelog.empty:
                adjusted_rows.append(row)
                continue

            last_game = gamelog.sort_values("GAME_DATE", ascending=False).iloc[0]

            matchup = last_game["MATCHUP"]

            if "vs." in matchup:
                opponent_abbr = matchup.split("vs.")[-1].strip()
            elif "@" in matchup:
                opponent_abbr = matchup.split("@")[-1].strip()
            else:
                adjusted_rows.append(row)
                continue

            opponent_row = team_stats[team_stats["TEAM_ABBREVIATION"] == opponent_abbr]

            if opponent_row.empty:
                adjusted_rows.append(row)
                continue

            opponent_def = opponent_row["DEF_RATING"].values[0]

            defense_factor = opponent_def / league_avg_def

            adjusted_projection = row["Projection"] / defense_factor

            new_row = row.copy()
            new_row["Opponent DEF Rating"] = round(opponent_def, 2)
            new_row["Defense Adjustment Factor"] = round(defense_factor, 3)
            new_row["Projection vs Opp"] = round(adjusted_projection, 2)

            adjusted_rows.append(new_row)

        except:
            adjusted_rows.append(row)

    return pd.DataFrame(adjusted_rows)
