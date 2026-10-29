# Add these helper functions after your existing load functions

@st.cache_data(ttl=3600)
def calculate_implied_points(game_total: float, line: float) -> tuple:
    """Calculate implied team points from Vegas total and spread."""
    # line is the spread (positive = favored team)
    # game_total is the over/under
    favored_points = (game_total + abs(line)) / 2
    underdog_points = (game_total - abs(line)) / 2
    return favored_points, underdog_points

def load_usage_distribution(players_df: pd.DataFrame, team_id: str) -> dict:
    """Calculate team usage distribution."""
    team_players = players_df[players_df["TEAM_ID"] == team_id]
    if team_players.empty:
        return {}
    
    total_usg = team_players["USG_PCT"].sum()
    usage_dist = {}
    for _, player in team_players.iterrows():
        player_name = player.get("PLAYER_NAME", "Unknown")
        usg_pct = _get_float(player, "USG_PCT", 0)
        usage_dist[player_name] = (usg_pct / total_usg * 100) if total_usg > 0 else 0
    
    return usage_dist

def calculate_shot_share(player_row: dict, team_usage_dist: dict) -> float:
    """Calculate player's shot share on team."""
    player_name = player_row.get("PLAYER_NAME", "Unknown")
    player_min = _get_float(player_row, "MIN", 10)
    team_avg_min = 30  # Average NBA starter minutes
    
    # Base shot share from usage distribution
    base_share = team_usage_dist.get(player_name, 0)
    
    # Adjust by minutes played vs team average
    min_adjustment = (player_min / team_avg_min) if team_avg_min > 0 else 1.0
    
    return base_share * min_adjustment

# ... existing code ...

# Enhanced projection calculation with new metrics

for (name, line_val, over_odds, under_odds, opp_from_txt, game_total) in rows:
    player_key = normalize_name(name)
    
    player_matches = players_df[players_df["NAME_KEY"] == player_key]
    if player_matches.empty:
        not_found.append(name)
        continue
    
    player_row = player_matches.iloc[0].to_dict()
    player_name = player_row.get("PLAYER_NAME", name)
    player_pts = _get_float(player_row, "PTS", 0)
    player_min = _get_float(player_row, "MIN", 10)
    player_usg = _get_float(player_row, "USG_PCT", league_avg_usg)
    player_team = str(player_row.get("TEAM_ID", "")).upper()
    
    # 1️⃣ IMPLIED TEAM POINTS (Vegas)
    if game_total and game_total > 0:
        favored_pts, underdog_pts = calculate_implied_points(game_total, 0)  # Adjust line as needed
        team_implied_pts = favored_pts if favored_pts > 0 else game_total / 2
    else:
        team_implied_pts = 110  # Default
    
    # 2️⃣ TEAM USAGE DISTRIBUTION
    team_usage_dist = load_usage_distribution(players_df, player_team)
    
    # 3️⃣ PLAYER SHOT SHARE
    shot_share = calculate_shot_share(player_row, team_usage_dist)
    
    # Check injuries
    is_injured = False
    if player_team in inj_by_team:
        is_injured = player_key in inj_by_team[player_team]
    
    # Find opponent stats
    team_row = _find_team_row_by_abbr(opp_from_txt) if opp_from_txt else None
    opp_def_rating = None
    opp_pace = None
    opp_net_rating = None
    
    if team_row:
        opp_def_rating = _get_float(team_row, "DEF_RATING", league_def)
        opp_pace = _get_float(team_row, "PACE", league_pace)
        opp_net_rating = _get_float(team_row, "NET_RATING", 0)
    
    # Market factors
    market_total_factor = game_total / 210.0 if game_total and game_total > 0 else 1.0
    
    # Base projection
    projection = player_pts * (player_min / 36.0) if player_min > 0 else player_pts
    
    # Apply adjustments
    if opp_def_rating and league_def:
        def_factor = (league_def / opp_def_rating) if opp_def_rating > 0 else 1.0
        projection *= def_factor
    
    if player_usg and league_avg_usg:
        usg_factor = player_usg / league_avg_usg
        projection *= usg_factor
    
    if opp_pace and league_pace:
        pace_factor = opp_pace / league_pace if league_pace > 0 else 1.0
        projection *= pace_factor
    
    # Shot share adjustment (higher share = more scoring opportunity)
    shot_share_factor = 1.0 + (shot_share / 100 - 0.15) * 0.3  # Normalize around 15% average
    projection *= shot_share_factor
    
    # Team pace/points adjustment
    if team_implied_pts > 0:
        projected_team_pts = team_row.get("PTS", 110) if team_row else 110
        team_pace_factor = team_implied_pts / projected_team_pts if projected_team_pts > 0 else 1.0
        projection *= team_pace_factor
    
    if is_injured:
        projection *= 0.7
    
    projection *= market_total_factor
    
    # Calculate expected value
    ev_over = (projection / line_val - 1.0) * 100 if line_val > 0 else 0
    ev_under = (1.0 - projection / line_val) * 100 if line_val > 0 else 0
    
    results.append({
        "Player": player_name,
        "Line": line_val,
        "Projection": round(projection, 2),
        "EV_Over": round(ev_over, 1),
        "EV_Under": round(ev_under, 1),
        "Over_Odds": over_odds,
        "Under_Odds": under_odds,
        "Opp": opp_from_txt or "?",
        "USG%": round(player_usg, 1),
        "Shot_Share%": round(shot_share, 1),
        "Team_Pts_Implied": round(team_implied_pts, 1),
        "Min_Played": round(player_min, 1),
        "Injured": "⚠️" if is_injured else "✅",
    })