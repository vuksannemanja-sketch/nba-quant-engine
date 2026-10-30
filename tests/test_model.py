import numpy as np
import pandas as pd
import pytest

from nba_engine.model import (build_player_context, compute_injury_boost_v2, compute_max_edge,
                              compute_per_player_bm_offset, estimate_match_total, find_team_row_by_abbr,
                              is_team_b2b, match_player_row)
from nba_engine.utils import normalize_name


def _players():
    names = ["LeBron James", "Luka Doncic", "Nikola Jokić", "Jalen Williams", "Jaylin Williams", "A.J. Lawson"]
    df = pd.DataFrame({
        "PLAYER_NAME": names, "TEAM_ABBR": ["LAL", "LAL", "DEN", "OKC", "OKC", "TOR"],
        "MIN": [34.0, 35.0, 33.0, 31.0, 20.0, 8.0], "GP": [50, 48, 52, 60, 55, 14],
        "PTS": [24.0, 29.0, 27.0, 20.0, 6.0, 3.5], "USG_PCT": [29.0, 33.0, 27.0, 25.0, 14.0, 12.0],
        "TS_PCT": [0.60, 0.59, 0.66, 0.57, 0.55, 0.50], "EFG_PCT": [0.56, 0.54, 0.62, 0.53, 0.52, 0.48],
        "FGA": [18.0, 21.0, 16.0, 15.0, 5.0, 2.9], "FTA": [6.0, 8.0, 6.0, 4.0, 1.0, 0.6], "FG3A": [5.0, 9.0, 3.0, 4.0, 2.0, 1.6],
        "PIE": [0.16, 0.18, 0.21, 0.12, 0.07, 0.05], "AST_RATIO": [22.0, 25.0, 30.0, 18.0, 10.0, 12.0], "AST_TO": [2.0, 2.2, 3.0, 1.8, 1.2, 1.0],
        "OFF_RATING": [116.0, 118.0, 122.0, 117.0, 110.0, 101.0], "NET_RATING": [3.0, 2.0, 8.0, 10.0, 9.0, -14.0],
        "PACE": [100.0, 101.0, 98.0, 99.0, 99.0, 98.0], "FG_PCT": [0.52, 0.47, 0.57, 0.49, 0.45, 0.39],
        "FG3_PCT": [0.38, 0.36, 0.40, 0.37, 0.33, 0.36], "FT_PCT": [0.75, 0.78, 0.82, 0.80, 0.70, 1.0],
    })
    df["NAME_KEY"] = df["PLAYER_NAME"].map(normalize_name)
    df["PPM"] = (df["PTS"] / df["MIN"]).clip(0.2, 1.25)
    df["FGA_PM"] = df["FGA"] / df["MIN"]
    df["FTA_PM"] = df["FTA"] / df["MIN"]
    df["FG3A_PM"] = df["FG3A"] / df["MIN"]
    return df


def _teams():
    return pd.DataFrame({
        "TEAM_ABBR": ["LAL", "DEN", "OKC", "TOR"],
        "OFF_RATING": [116.0, 120.0, 118.0, 108.0], "DEF_RATING": [113.0, 112.0, 106.0, 116.0],
        "NET_RATING": [3.0, 8.0, 12.0, -8.0], "PACE": [100.5, 98.0, 99.5, 101.0],
    })


def test_math_helpers_ranges_and_monotonicity():
    assert 0.2 <= compute_per_player_bm_offset(0) <= 3.5
    assert compute_per_player_bm_offset(30) > compute_per_player_bm_offset(10)
    assert compute_per_player_bm_offset(100) == 3.5
    assert 2.0 <= compute_max_edge(10.5) <= 8.5
    assert compute_max_edge(30.5, usg=32, sigma=8) > compute_max_edge(10.5, usg=15, sigma=4)
    assert compute_injury_boost_v2(0, 0, 20, False, 0) == 1.0
    assert compute_injury_boost_v2(40, 60, 18, True, 30, player_position_score=0.8) <= 1.10
    assert compute_injury_boost_v2(40, 60, 30, True, 30, player_position_score=0.8) <= 1.03
    assert compute_injury_boost_v2(40, 60, 18, False, 0, 0.8) > compute_injury_boost_v2(5, 5, 18, False, 0, 0.8)


def test_match_player_row_strategies():
    players = _players()
    assert match_player_row(players, "Nikola Jokic")[2] == "EXACT"
    assert match_player_row(players, "Doncic, Luka")[2] == "LAST_FIRST"
    row, _, method = match_player_row(players, "L. James")
    assert method == "INITIAL_LAST" and row["PLAYER_NAME"] == "LeBron James"
    assert match_player_row(players, "Jalen Williams")[2] == "EXACT"
    assert match_player_row(players, "Lebron Jams")[2] == "DIFFLIB"
    assert match_player_row(players, "Totally Unknown")[0] is None
    assert match_player_row(players, "")[2] == "EMPTY_KEY"


def test_team_lookup_and_b2b():
    teams = _teams()
    assert find_team_row_by_abbr(teams, "den")["OFF_RATING"] == 120.0
    assert find_team_row_by_abbr(teams, "XXX") is None and find_team_row_by_abbr(teams, "") is None
    b2b = pd.DataFrame({"GAME_DATE": ["2026-01-10", "2026-01-11"], "TEAM_ABBR": ["LAL", "LAL"], "IS_B2B": [False, True]})
    assert is_team_b2b(b2b, "LAL", "2026-01-11") is True
    assert is_team_b2b(b2b, "LAL", "2026-01-10") is False
    assert is_team_b2b(b2b, "LAL", "2026-02-01") is False
    assert is_team_b2b(None, "LAL", "2026-01-11") is False


def test_estimate_match_total_in_range():
    teams = _teams()
    t = estimate_match_total(find_team_row_by_abbr(teams, "LAL"), find_team_row_by_abbr(teams, "DEN"), None, teams)
    assert 180.0 <= t <= 265.0
    assert estimate_match_total(None, None, None, teams) is None


def test_build_player_context_deterministic_and_bounded():
    players, teams = _players(), _teams()
    r0 = players[players["PLAYER_NAME"] == "Luka Doncic"].iloc[0]
    kwargs = dict(r0=r0, players_df=players, teams_df=teams,
                  team_row=find_team_row_by_abbr(teams, "LAL"), opp_row=find_team_row_by_abbr(teams, "DEN"),
                  inj_df=None, team_abbr="LAL", player_name_key="luka doncic", total_match_used=230.0,
                  opp_team_abbr="DEN", line_val=28.5)
    ctx1 = build_player_context(**kwargs)
    ctx2 = build_player_context(**kwargs)
    assert ctx1 == ctx2
    assert 28.5 * 0.55 <= ctx1["final_projection"] <= 28.5 * 1.45
    assert 8.0 <= ctx1["minutes_proj"] <= 40.0
    assert 2.0 <= ctx1["sigma"] <= 14.0
    assert ctx1["home_away_factor"] == 1.02 and ctx1["rest_factor"] == 1.0 and ctx1["b2b_factor"] == 1.0
    # gostovanje + B2B snižava faktore
    ctx_away_b2b = build_player_context(**{**kwargs, "is_home": False, "b2b_team": True, "rest_days": 0})
    assert ctx_away_b2b["home_away_factor"] == 0.975 and ctx_away_b2b["b2b_factor"] == 0.94
    assert ctx_away_b2b["final_projection"] <= ctx1["final_projection"]


def test_build_player_context_injury_effects():
    players, teams = _players(), _teams()
    r0 = players[players["PLAYER_NAME"] == "Luka Doncic"].iloc[0]
    inj = pd.DataFrame({"PLAYER": ["LeBron James"], "NAME_KEY": ["lebron james"], "TEAM_ABBR": ["LAL"], "STATUS": ["OUT"]})
    base = dict(r0=r0, players_df=players, teams_df=teams, team_row=find_team_row_by_abbr(teams, "LAL"),
                opp_row=find_team_row_by_abbr(teams, "DEN"), team_abbr="LAL", player_name_key="luka doncic",
                total_match_used=None, opp_team_abbr="DEN", line_val=28.5)
    with_inj = build_player_context(inj_df=inj, **base)
    without = build_player_context(inj_df=None, **base)
    assert with_inj["injury_boost"] >= 1.0 and with_inj["injured_minutes_lost"] > 0
    assert with_inj["final_projection"] >= without["final_projection"]
    # igrač koji je sam OUT → minuti padaju na minimum
    self_out = pd.DataFrame({"PLAYER": ["Luka Doncic"], "NAME_KEY": ["luka doncic"], "TEAM_ABBR": ["LAL"], "STATUS": ["OUT"]})
    ctx_out = build_player_context(inj_df=self_out, **base)
    assert ctx_out["direct_player_penalty"] == 0.0 and ctx_out["minutes_proj"] == 8.0


def test_build_player_context_uses_form_and_h2h():
    players, teams = _players(), _teams()
    r0 = players[players["PLAYER_NAME"] == "Luka Doncic"].iloc[0]
    l10 = pd.DataFrame({"NAME_KEY": ["luka doncic"], "L10_PTS": [36.0], "L5_PTS": [38.0], "L3_PTS": [39.0], "TREND_SLOPE": [1.2]})
    h2h = pd.DataFrame({"NAME_KEY": ["luka doncic"], "OPP_TEAM": ["DEN"], "H2H_PTS_AVG": [35.0], "H2H_GAMES": [4], "H2H_PTS_LAST": [40.0]})
    base = dict(r0=r0, players_df=players, teams_df=teams, team_row=find_team_row_by_abbr(teams, "LAL"),
                opp_row=find_team_row_by_abbr(teams, "DEN"), inj_df=None, team_abbr="LAL",
                player_name_key="luka doncic", total_match_used=None, opp_team_abbr="DEN", line_val=30.5)
    hot = build_player_context(l10_df=l10, h2h_df=h2h, **base)
    plain = build_player_context(**base)
    assert hot["l10_pts"] == 36.0 and hot["l5_pts"] == 38.0 and hot["h2h_games"] == 4
    assert hot["final_projection"] > plain["final_projection"]
    assert plain["h2h_pts"] == 29.0  # bez H2H prikazuje sezonski prosjek


def test_l10_minutes_and_sigma_inputs_are_opt_in():
    players, teams = _players(), _teams()
    r0 = players[players["PLAYER_NAME"] == "Luka Doncic"].iloc[0]
    season_min = float(r0["MIN"])
    l10 = pd.DataFrame({"NAME_KEY": ["luka doncic"], "L10_PTS": [float(r0["PTS"])], "L5_PTS": [float(r0["PTS"])],
                        "L3_PTS": [float(r0["PTS"])], "TREND_SLOPE": [0.0], "L10_MIN": [season_min + 8.0],
                        "L10_STD": [3.0], "GAMES_PLAYED": [10]})
    kwargs = dict(r0=r0, players_df=players, teams_df=teams,
                  team_row=find_team_row_by_abbr(teams, "LAL"), opp_row=find_team_row_by_abbr(teams, "DEN"),
                  inj_df=None, team_abbr="LAL", player_name_key="luka doncic", total_match_used=230.0,
                  opp_team_abbr="DEN", line_val=28.5, l10_df=l10)
    base = build_player_context(**kwargs)
    assert base["minutes_base"] == base["season_min"] and base["l10_min_weight"] == 0.0 and base["sigma_l10_weight"] == 0.0

    with_min = build_player_context(**{**kwargs, "use_l10_minutes": True})
    assert abs(with_min["l10_min_weight"] - 0.6) < 1e-9
    assert abs(with_min["minutes_base"] - (0.4 * season_min + 0.6 * (season_min + 8.0))) < 1e-9
    assert with_min["minutes_proj"] > base["minutes_proj"]
    assert with_min["final_projection"] >= base["final_projection"]

    with_sig = build_player_context(**{**kwargs, "use_l10_sigma": True})
    assert abs(with_sig["sigma_l10_weight"] - 0.5) < 1e-9 and with_sig["sigma"] <= base["sigma"]
    assert with_sig["minutes_proj"] == base["minutes_proj"]            # sigma ulaz ne dira minute

    # manje utakmica u formi → manja težina
    few = l10.assign(GAMES_PLAYED=[3])
    ctx_few = build_player_context(**{**kwargs, "l10_df": few, "use_l10_minutes": True, "use_l10_sigma": True})
    assert abs(ctx_few["l10_min_weight"] - 0.36) < 1e-9 and abs(ctx_few["sigma_l10_weight"] - 0.3) < 1e-9
    # bez L10 tabele: uključeni ulazi nemaju šta da koriste → identično kao bez L10 tabele i bez ulaza
    no_l10 = build_player_context(**{**kwargs, "l10_df": None})
    ctx_none = build_player_context(**{**kwargs, "l10_df": None, "use_l10_minutes": True, "use_l10_sigma": True})
    assert ctx_none == no_l10 and ctx_none["minutes_base"] == no_l10["season_min"]
