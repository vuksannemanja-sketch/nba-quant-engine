import json

import numpy as np
import pandas as pd
import pytest

from nba_engine.config import Settings
from nba_engine import v2
from nba_engine.v2 import (ResidualModel, build_calibration, build_universe, devig, fair_from_quotes, line_bucket,
                           load_quotes, model_weight_from_env, run_v2)


def _q(rows):
    return pd.DataFrame(rows, columns=["BOOK", "LINE", "OVER_ODDS", "UNDER_ODDS"]).assign(PLAYER="X")


def test_devig_removes_margin_and_rejects_bad_odds():
    assert devig(1.90, 1.90) == pytest.approx(0.5)
    assert devig(1.80, 2.10) > 0.5                       # kraća kvota na Over → vjerovatniji
    assert devig(1.0, 2.0) is None and devig("x", 1.9) is None and devig(float("nan"), 1.9) is None


def test_fair_prefers_pinnacle_and_uses_same_line_only():
    q = _q([("pinnacle", 20.5, 1.90, 1.90), ("draftkings", 20.5, 2.05, 1.80), ("fanduel", 21.5, 2.40, 1.55)])
    f = fair_from_quotes(q, 20.5)
    assert f.ok and f.source == "pinnacle" and f.p_over == pytest.approx(0.5)
    assert f.n_books == 2                                  # druga linija se ne miješa
    assert f.best_over == 2.05 and f.best_over_book == "draftkings"
    assert f.best_under == 1.90 and f.best_under_book == "pinnacle"


def test_fair_consensus_needs_three_books_without_pinnacle():
    two = _q([("fanduel", 10.5, 1.9, 1.9), ("betmgm", 10.5, 1.9, 1.9)])
    assert not fair_from_quotes(two, 10.5).ok and fair_from_quotes(two, 10.5).source == "nedovoljno"
    three = _q([("fanduel", 10.5, 1.8, 2.0), ("betmgm", 10.5, 1.9, 1.9), ("bovada", 10.5, 2.0, 1.8)])
    f = fair_from_quotes(three, 10.5)
    assert f.ok and f.source == "konsenzus" and f.p_over == pytest.approx(0.5, abs=0.01)
    assert not fair_from_quotes(pd.DataFrame(), 10.5).ok
    assert not fair_from_quotes(three, 33.5).ok            # nijedna kladionica nema tu liniju


def test_line_buckets():
    assert [line_bucket(x) for x in (4.5, 7.5, 8.5, 12.5, 13.5, 17.5, 18.5, 22.5, 23.5, 40.5)] == \
        ["<=7.5", "<=7.5", "8-12.5", "8-12.5", "13-17.5", "13-17.5", "18-22.5", "18-22.5", "23+", "23+"]


def test_residual_model_fallback_normal_and_empirical_skew():
    m = ResidualModel()                                    # bez kalibracije: normalna sa izmjerenom sigmom
    assert not m.calibrated
    assert m.p_over(20.5, 20.5) == pytest.approx(0.5, abs=0.02)
    assert m.p_over(25.0, 20.5) > 0.7 > 0.3 > m.p_over(16.0, 20.5)
    # empirijski: ostaci iskrivljeni udesno (medijan −1, dug desni rep) → p_over ispod 0.5 kad je projekcija = linija
    rng = np.random.default_rng(1)
    res = np.concatenate([rng.normal(-2.5, 3, 700), rng.normal(5, 4, 300)])
    em = ResidualModel({"13-17.5": res})
    assert em.calibrated
    p = em.p_over(15.5, 15.5)
    assert p == pytest.approx(float((res > 0).mean()), abs=0.02) and p < 0.45
    assert 0.03 <= em.p_over(100, 15.5) <= 0.97 and 0.03 <= em.p_over(-100, 15.5) <= 0.97   # ograničeno
    assert ResidualModel({"23+": [1, 2, 3]}).calibrated is False                             # premalo uzoraka


def test_build_calibration_and_roundtrip(tmp_path):
    rng = np.random.default_rng(0)
    n = 200
    settled = pd.DataFrame({"Line": rng.choice([5.5, 10.5, 15.5], n), "Calibrated Projection": 12.0,
                            "Actual Points": rng.normal(12, 5, n).round()})
    cal = build_calibration(settled, source="test")
    assert cal["n"] == n and set(cal["buckets"]) <= {"<=7.5", "8-12.5", "13-17.5"} and len(cal["buckets"]) == 3
    assert len(cal["buckets"]["8-12.5"]["q"]) == 101
    path = tmp_path / "cal.json"
    path.write_text(json.dumps(cal), encoding="utf-8")
    assert ResidualModel.load(path).calibrated
    assert not ResidualModel.load(tmp_path / "nema.json").calibrated
    path.write_text("{ne json", encoding="utf-8")
    assert not ResidualModel.load(path).calibrated


def _mc(rows):
    base = {"Over Odds": 1.9, "Under Odds": 1.9, "Calibrated Projection": 20.0, "Line": 20.5, "Model Pick": "OVER",
            "TEAM_ABBR": "AAA", "OPP_TEAM": "BBB"}
    return pd.DataFrame([{**base, **r} for r in rows])


def _quotes(rows):
    return pd.DataFrame(rows).assign(NAME_KEY=lambda d: d["PLAYER"].str.lower().str.replace(" ", ""))


def test_build_universe_picks_only_positive_ev_over_fair_price():
    mc = _mc([{"Player": "Value Over", "Line": 20.5}, {"Player": "No Edge", "Line": 20.5},
              {"Player": "No Fair", "Line": 20.5}])
    quotes = pd.DataFrame([
        {"PLAYER": "Value Over", "BOOK": "pinnacle", "LINE": 20.5, "OVER_ODDS": 1.90, "UNDER_ODDS": 1.90},
        {"PLAYER": "Value Over", "BOOK": "fanduel", "LINE": 20.5, "OVER_ODDS": 2.04, "UNDER_ODDS": 1.78},
        {"PLAYER": "No Edge", "BOOK": "pinnacle", "LINE": 20.5, "OVER_ODDS": 1.90, "UNDER_ODDS": 1.90},
        {"PLAYER": "No Edge", "BOOK": "fanduel", "LINE": 20.5, "OVER_ODDS": 1.91, "UNDER_ODDS": 1.88},
        {"PLAYER": "No Fair", "BOOK": "fanduel", "LINE": 20.5, "OVER_ODDS": 2.2, "UNDER_ODDS": 1.7}])
    quotes["NAME_KEY"] = quotes["PLAYER"].map(lambda s: s.lower().replace(" ", ""))
    from nba_engine import utils
    quotes["NAME_KEY"] = quotes["PLAYER"].map(utils.normalize_name)
    uni = build_universe(mc, quotes, ResidualModel(), model_weight=0.0)
    by = uni.set_index("Player")
    assert by.loc["Value Over", "V2 Pick"] == "OVER" and by.loc["Value Over", "Model Pick"] == "OVER"
    assert by.loc["Value Over", "Over Odds"] == 2.04                      # najbolja kvota iz kladionica sa istom linijom
    assert by.loc["Value Over", "V2 EV %"] == pytest.approx(2.0, abs=0.05)  # 0.5 × 2.04 − 1
    assert by.loc["Value Over", "V2 Fair Source"] == "pinnacle"
    assert by.loc["No Edge", "V2 Pick"] == "NO VALUE"                      # EV 0.5 % < 1 %
    assert by.loc["No Fair", "V2 Pick"] == "NO VALUE" and "fer cijene" in by.loc["No Fair", "V2 Note"]
    assert by.loc["Value Over", "V1 Pick"] == "OVER"                       # v1 odluka ostaje za poređenje
    assert uni.iloc[0]["Player"] == "Value Over" and uni.iloc[0]["V2 Rank"] == 1


def test_model_weight_zero_ignores_model_and_positive_weight_uses_it():
    mc = _mc([{"Player": "A", "Calibrated Projection": 30.0}])             # model jako vjeruje u Over
    q = pd.DataFrame([{"PLAYER": "A", "BOOK": "pinnacle", "LINE": 20.5, "OVER_ODDS": 1.90, "UNDER_ODDS": 1.90}])
    from nba_engine import utils
    q["NAME_KEY"] = q["PLAYER"].map(utils.normalize_name)
    zero = build_universe(mc, q, ResidualModel(), model_weight=0.0).iloc[0]
    assert zero["V2 P(Over)%"] == pytest.approx(50.0) and zero["V2 Pick"] == "NO VALUE"
    half = build_universe(mc, q, ResidualModel(), model_weight=0.5).iloc[0]
    assert half["V2 P(Over)%"] > 60 and half["V2 Pick"] == "OVER"
    assert zero["V2 Model P(Over)%"] == half["V2 Model P(Over)%"] > 90      # model se uvijek bilježi, i s težinom 0


def test_selection_caps_picks_per_game_and_total_and_skips_suspicious_ev():
    rows, quotes = [], []
    for i in range(14):
        name = f"P{i:02d}"
        game = i % 5                                                       # 5 utakmica
        rows.append({"Player": name, "TEAM_ABBR": f"T{game}", "OPP_TEAM": f"U{game}"})
        edge = 2.02 + 0.01 * i                                             # sve veći EV (od +1 % naviše)
        quotes += [{"PLAYER": name, "BOOK": "pinnacle", "LINE": 20.5, "OVER_ODDS": 1.9, "UNDER_ODDS": 1.9},
                   {"PLAYER": name, "BOOK": "fanduel", "LINE": 20.5, "OVER_ODDS": edge, "UNDER_ODDS": 1.7}]
    rows.append({"Player": "Stale", "TEAM_ABBR": "T9", "OPP_TEAM": "U9"})
    quotes += [{"PLAYER": "Stale", "BOOK": "pinnacle", "LINE": 20.5, "OVER_ODDS": 1.9, "UNDER_ODDS": 1.9},
               {"PLAYER": "Stale", "BOOK": "fanduel", "LINE": 20.5, "OVER_ODDS": 2.6, "UNDER_ODDS": 1.5}]   # cijena +30 % iznad fer
    from nba_engine import utils
    q = pd.DataFrame(quotes)
    q["NAME_KEY"] = q["PLAYER"].map(utils.normalize_name)
    uni = build_universe(_mc(rows), q, ResidualModel(), model_weight=0.0, min_ev=0.01, max_picks=10, max_per_game=2)
    picks = uni[uni["V2 Pick"] == "OVER"]
    assert len(picks) == 10 and picks["V2 Rank"].tolist() == list(range(1, 11))
    assert picks.groupby(picks["TEAM_ABBR"]).size().max() <= 2             # najviše 2 po utakmici
    assert "Stale" not in set(picks["Player"])
    stale = uni[uni["Player"] == "Stale"].iloc[0]
    assert stale["V2 Pick"] == "NO VALUE" and "sumnjivo" in stale["V2 Note"] and stale["V2 Price Edge %"] > 15
    assert picks["V2 EV %"].is_monotonic_decreasing                        # rang po EV


def test_model_weight_from_env(monkeypatch):
    monkeypatch.delenv("V2_MODEL_WEIGHT", raising=False)
    assert model_weight_from_env() == 0.0
    monkeypatch.setenv("V2_MODEL_WEIGHT", "0.25")
    assert model_weight_from_env() == 0.25
    monkeypatch.setenv("V2_MODEL_WEIGHT", "7")
    assert model_weight_from_env() == 1.0
    monkeypatch.setenv("V2_MODEL_WEIGHT", "abc")
    assert model_weight_from_env() == 0.0


def test_load_quotes_validates_file(tmp_path):
    assert load_quotes(tmp_path / "nema.csv") is None
    (tmp_path / "bad.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert load_quotes(tmp_path / "bad.csv") is None
    pd.DataFrame([{"PLAYER": "Jalen Williams", "BOOK": "pinnacle", "LINE": 20.5, "OVER_ODDS": 1.9,
                   "UNDER_ODDS": 1.9}]).to_csv(tmp_path / "ok.csv", index=False)
    assert list(load_quotes(tmp_path / "ok.csv")["NAME_KEY"]) == ["jalen williams"]


def test_run_v2_saves_full_universe_in_v2_history_and_does_not_touch_v1(tmp_path):
    settings = Settings.load(data_dir=tmp_path / "data", season="2026-27", env_file=tmp_path / "no.env",
                             history_dir=tmp_path / "history")
    proj = pd.DataFrame([{"Player": "Alpha One", "TEAM_ABBR": "AAA", "OPP_TEAM": "BBB", "Line": 20.5,
                          "Over Odds": 1.9, "Under Odds": 1.9, "Final Projection": 22.0, "SeasonAnchor": 21.0,
                          "Usage %": 25.0, "Sigma": 6.0}])
    (tmp_path / "data").mkdir()
    pd.DataFrame([{"PLAYER": "Alpha One", "BOOK": "pinnacle", "LINE": 20.5, "OVER_ODDS": 1.9, "UNDER_ODDS": 1.9},
                  {"PLAYER": "Alpha One", "BOOK": "fanduel", "LINE": 20.5, "OVER_ODDS": 2.1, "UNDER_ODDS": 1.7}]
                 ).to_csv(tmp_path / "data" / "q.csv", index=False)
    res = run_v2(proj, settings, log=lambda m: None, quotes_path=tmp_path / "data" / "q.csv", model_weight=0.0)
    assert res.ok and res.path is not None and res.path.parent == settings.v2_history_dir
    assert res.path.name.endswith("_daily.csv")
    saved = pd.read_csv(res.path)
    assert len(saved) == 1 and saved.iloc[0]["Model Pick"] == "OVER" and saved.iloc[0]["V1 Pick"] in ("OVER", "UNDER", "NO VALUE")
    assert not (tmp_path / "history" / "analysis_x").exists() and not list(settings.history_dir.glob("analysis_*.csv"))
    # bez fajla kvota: nema izbora, ali spisak se ipak snima
    res2 = run_v2(proj, settings, log=lambda m: None, quotes_path=tmp_path / "data" / "nema.csv", save=False)
    assert res2.ok and (res2.universe["V2 Pick"] == "NO VALUE").all() and res2.path is None
    assert not run_v2(pd.DataFrame(), settings, log=lambda m: None).ok


def _edge_quotes(names, odds=2.10):
    rows = []
    for n in names:
        rows += [{"PLAYER": n, "BOOK": "pinnacle", "LINE": 20.5, "OVER_ODDS": 1.9, "UNDER_ODDS": 1.9},
                 {"PLAYER": n, "BOOK": "fanduel", "LINE": 20.5, "OVER_ODDS": odds, "UNDER_ODDS": 1.7}]
    q = pd.DataFrame(rows)
    from nba_engine import utils
    q["NAME_KEY"] = q["PLAYER"].map(utils.normalize_name)
    return q


def test_per_game_cap_binds_when_many_picks_come_from_one_game():
    names = [f"G{i}" for i in range(6)]
    mc = _mc([{"Player": n, "TEAM_ABBR": "AAA", "OPP_TEAM": "BBB"} for n in names])
    uni = build_universe(mc, _edge_quotes(names), ResidualModel(), model_weight=0.0, max_picks=10, max_per_game=3)
    assert (uni["V2 Pick"] == "OVER").sum() == 3                             # svih 6 ima ivicu, ali utakmica dozvoljava 3
    capped = uni[uni["V2 Pick"] == "NO VALUE"]
    assert len(capped) == 3 and capped["V2 Note"].str.contains("ograničenja").all()
    # protivnik nepoznat: ograničenje ipak važi po timu
    mc2 = _mc([{"Player": n, "TEAM_ABBR": "AAA", "OPP_TEAM": ""} for n in names])
    uni2 = build_universe(mc2, _edge_quotes(names), ResidualModel(), model_weight=0.0, max_picks=10, max_per_game=3)
    assert (uni2["V2 Pick"] == "OVER").sum() == 3


def test_weight_zero_ignores_model_even_when_it_is_nan_and_notes_explain_skips():
    mc = _mc([{"Player": "A", "Calibrated Projection": float("nan")}, {"Player": "B"}])
    q = _edge_quotes(["A"], odds=1.91)                                       # A: EV < 1 %
    q = pd.concat([q, _edge_quotes(["B"], odds=2.10)], ignore_index=True)
    uni = build_universe(mc, q, ResidualModel(), model_weight=0.0).set_index("Player")
    assert uni.loc["A", "V2 P(Over)%"] == pytest.approx(50.0) and uni.loc["A", "V2 Pick"] == "NO VALUE"
    assert "ispod praga" in uni.loc["A", "V2 Note"] and uni.loc["B", "V2 Pick"] == "OVER" and uni.loc["B", "V2 Note"] == ""


def test_shift_p_over_moves_fair_probability_with_the_line():
    from nba_engine.v2 import shift_p_over
    assert shift_p_over(0.55, 20.5, 20.5) == pytest.approx(0.55)
    up = shift_p_over(0.50, 20.5, 21.5)                                      # naša linija viša → Over teže
    down = shift_p_over(0.50, 20.5, 19.5)
    assert up < 0.5 < down and up == pytest.approx(1 - down, abs=1e-9)
    assert shift_p_over(0.5, 10.5, 11.5) < shift_p_over(0.5, 30.5, 31.5)     # pomak od 1 poena je veći za niske granice
    assert 0 < shift_p_over(0.9999, 20.5, 30.5) < shift_p_over(0.9999, 20.5, 20.5)
