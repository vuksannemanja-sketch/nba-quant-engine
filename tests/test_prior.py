"""Rana sezona: dopuna prošlom sezonom po broju utakmica (bez podataka sa diska)."""
import numpy as np
import pandas as pd
import pytest

from nba_engine.prior import FULL_WEIGHT_GP, blend_players, blend_teams, current_weight


def test_current_weight_rules():
    assert current_weight(0, 82) == 0.0                 # nije igrao → samo prošla sezona
    assert current_weight(5, 82) == pytest.approx(0.25)
    assert current_weight(10, 82) == pytest.approx(0.5)
    assert current_weight(FULL_WEIGHT_GP, 82) == 1.0 and current_weight(60, 82) == 1.0
    assert current_weight(5, 0) == 1.0                  # prošle sezone nema → ova sezona
    assert current_weight(5, 5) == pytest.approx(1 - 0.75 * 0.5)   # slaba prošla sezona vrijedi upola
    assert current_weight(float("nan"), 82) == 0.0


def _cur():
    return pd.DataFrame({
        "NAME_KEY": ["a", "b", "rookie", "d"], "GP": [5, 20, 3, 4],
        "PTS": [10.0, 20.0, 8.0, np.nan], "MIN": [20.0, 30.0, 16.0, 24.0], "FGA": [8.0, 15.0, 7.0, 10.0],
        "USG_PCT": [18.0, 28.0, 15.0, 20.0], "PPM": [0.5, 0.667, 0.5, 0.55], "FGA_PM": [0.4, 0.5, 0.4375, 0.4167],
    })


def _prev():
    return pd.DataFrame({
        "NAME_KEY": ["a", "b", "d", "d"], "GP": [70, 60, 4, 2],
        "PTS": [20.0, 10.0, 12.0, 1.0], "MIN": [30.0, 20.0, 24.0, 5.0], "FGA": [16.0, 8.0, 10.0, 1.0],
        "USG_PCT": [26.0, 20.0, 22.0, 9.0],
    })


def test_blend_players_weights_and_derived_columns():
    out, info = blend_players(_cur(), _prev())
    a = out.set_index("NAME_KEY").loc["a"]
    assert a["PRIOR_WEIGHT"] == pytest.approx(0.75) and a["GP_PRIOR"] == 70
    assert a["PTS"] == pytest.approx(0.25 * 10 + 0.75 * 20) and a["MIN"] == pytest.approx(0.25 * 20 + 0.75 * 30)
    assert a["PPM"] == pytest.approx(a["PTS"] / a["MIN"]) and a["FGA_PM"] == pytest.approx(a["FGA"] / a["MIN"])
    b = out.set_index("NAME_KEY").loc["b"]
    assert b["PRIOR_WEIGHT"] == 0.0 and b["PTS"] == 20.0 and b["PPM"] == 0.667         # 20 utakmica → netaknut
    r = out.set_index("NAME_KEY").loc["rookie"]
    assert r["PRIOR_WEIGHT"] == 0.0 and r["PTS"] == 8.0 and np.isnan(r["GP_PRIOR"])
    d = out.set_index("NAME_KEY").loc["d"]
    assert d["GP_PRIOR"] == 4                                                           # duplikat: uzima se red sa više utakmica
    assert d["PRIOR_WEIGHT"] == pytest.approx((1 - 0.2) * 0.4)
    assert d["PTS"] == 12.0                                                             # ove sezone nema PTS → prošla
    assert info["blended"] == 2 and 0 < info["mean_prior_weight"] < 1
    assert "GP" in out.columns and out["GP"].tolist() == [5, 20, 3, 4]                  # GP se ne miješa


def test_blend_players_without_prior_is_identity():
    cur = _cur()
    out, info = blend_players(cur, None)
    assert info["blended"] == 0 and (out["PRIOR_WEIGHT"] == 0).all()
    pd.testing.assert_frame_equal(out.drop(columns=["PRIOR_WEIGHT", "GP_PRIOR"]), cur)
    out2, info2 = blend_players(cur, pd.DataFrame({"NAME_KEY": ["zzz"], "GP": [80], "PTS": [30.0]}))
    assert info2["blended"] == 0


def test_blend_teams_recomputes_net_rating():
    cur = pd.DataFrame({"TEAM_ABBR": ["LAL", "BOS"], "GP": [4, 20], "OFF_RATING": [120.0, 110.0],
                        "DEF_RATING": [100.0, 112.0], "NET_RATING": [20.0, -2.0], "PACE": [104.0, 98.0]})
    prev = pd.DataFrame({"TEAM_ABBR": ["LAL", "BOS"], "GP": [82, 82], "OFF_RATING": [112.0, 118.0],
                         "DEF_RATING": [112.0, 108.0], "NET_RATING": [0.0, 10.0], "PACE": [100.0, 100.0]})
    out, info = blend_teams(cur, prev)
    lal = out.set_index("TEAM_ABBR").loc["LAL"]
    assert lal["PRIOR_WEIGHT"] == pytest.approx(0.8)
    assert lal["OFF_RATING"] == pytest.approx(0.2 * 120 + 0.8 * 112) and lal["PACE"] == pytest.approx(0.2 * 104 + 0.8 * 100)
    assert lal["NET_RATING"] == pytest.approx(lal["OFF_RATING"] - lal["DEF_RATING"])
    bos = out.set_index("TEAM_ABBR").loc["BOS"]
    assert bos["PRIOR_WEIGHT"] == 0.0 and bos["OFF_RATING"] == 110.0 and info["blended"] == 1
