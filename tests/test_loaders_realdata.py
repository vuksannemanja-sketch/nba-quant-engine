import numpy as np
import pandas as pd

from nba_engine.loaders import fill_injury_teams, load_bundle


def test_bundle_loads_real_csvs(bundle_legacy_mode):
    b = bundle_legacy_mode
    assert len(b.players) > 400 and "NAME_KEY" in b.players.columns and "PPM" in b.players.columns
    assert b.players["TEAM_ABBR"].notna().all()
    assert b.players["PPM"].between(0.2, 1.25).all()
    assert len(b.teams) == 30 and {"TEAM_ABBR", "NET_RATING", "OFF_RATING", "DEF_RATING", "PACE"} <= set(b.teams.columns)
    assert b.teams["TEAM_ABBR"].nunique() == 30
    assert b.h2h is not None and {"NAME_KEY", "OPP_TEAM", "H2H_PTS_AVG"} <= set(b.h2h.columns)
    assert b.l10 is not None and {"NAME_KEY", "L10_PTS", "L5_PTS", "TREND_SLOPE"} <= set(b.l10.columns)
    assert b.b2b is not None and b.b2b["IS_B2B"].dtype == bool
    assert b.injuries is not None and {"NAME_KEY", "STATUS", "TEAM_ABBR"} <= set(b.injuries.columns)
    assert b.league_pts_std > 0


def test_fill_injury_teams_from_players(real_data, bundle_legacy_mode):
    legacy = bundle_legacy_mode
    filled_df, n = fill_injury_teams(legacy.injuries, legacy.players)
    if legacy.injuries["TEAM_ABBR"].isna().all():
        assert n > 0 and filled_df["TEAM_ABBR"].notna().sum() == n
    full = load_bundle(real_data, fill_injury_team_from_players=True)
    assert full.injuries["TEAM_ABBR"].notna().sum() >= legacy.injuries["TEAM_ABBR"].notna().sum()


def test_fill_injury_teams_handles_missing_inputs():
    assert fill_injury_teams(None, pd.DataFrame()) == (None, 0)
    inj = pd.DataFrame({"NAME_KEY": ["a b"], "TEAM_ABBR": [np.nan]})
    players = pd.DataFrame({"NAME_KEY": ["a b"], "TEAM_ABBR": ["BOS"]})
    out, n = fill_injury_teams(inj, players)
    assert n == 1 and out["TEAM_ABBR"].iloc[0] == "BOS"
