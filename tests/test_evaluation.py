import io

import pandas as pd
import pytest

from nba_engine.evaluation import (calculate_bet_profit, calculate_clv, compare_two_models, evaluate_engine,
                                   grade_engine, load_actual_results_csv, load_prediction_results_csv, settle_pick)


def test_settle_and_profit():
    assert settle_pick("OVER", 20.5, 25) == "WIN" and settle_pick("OVER", 20.5, 18) == "LOSS"
    assert settle_pick("UNDER", 20.5, 18) == "WIN" and settle_pick("UNDER", 20, 20) == "PUSH"
    assert settle_pick("NO VALUE", 20.5, 18) == "NO_BET" and settle_pick("OVER", 20.5, float("nan")) == "NO_BET"
    assert calculate_bet_profit("WIN", 1.9, 2.0) == pytest.approx(1.8)
    assert calculate_bet_profit("LOSS", 1.9, 2.0) == -2.0
    assert calculate_bet_profit("PUSH", 1.9) == 0.0 and calculate_bet_profit("WIN", float("nan")) == 0.0


def test_clv():
    assert calculate_clv(pd.Series({"Line": 20.5, "Closing Line": 22.5, "Model Pick": "OVER"})) == 2.0
    assert calculate_clv(pd.Series({"Line": 20.5, "Closing Line": 22.5, "Model Pick": "UNDER"})) == -2.0
    assert calculate_clv(pd.Series({"Line": 20.5, "Model Pick": "OVER"})) is None


def test_evaluate_engine_and_grade():
    pred = pd.DataFrame({
        "Player": ["A One", "B Two", "C Three", "D Four"],
        "Line": [20.5, 15.5, 10.5, 8.5], "Over Odds": [1.9, 1.85, 2.0, 1.8], "Under Odds": [1.9, 1.95, 1.8, 2.0],
        "Final Projection": [24.0, 13.0, 12.0, 9.0], "Model Pick": ["OVER", "UNDER", "OVER", "NO VALUE"],
        "Projection Edge": [3.5, -2.5, 1.5, 0.5],
    })
    actual = load_actual_results_csv(io.StringIO("player,actual points,closing line\nA One,26,21.5\nB Two,14,15.5\nC Three,9,10.5\nD Four,10,8.5\n"))
    merged, summary = evaluate_engine(pred, actual, stake=1.0, model_name="T")
    assert summary["Bets"] == 3 and summary["Wins"] == 2 and summary["Losses"] == 1
    assert summary["Accuracy %"] == pytest.approx(66.67, abs=0.01)
    assert summary["Profit"] == pytest.approx(0.9 + 0.95 - 1.0, abs=1e-6)
    assert summary["MAE"] is not None and summary["Avg CLV"] == pytest.approx(round((1.0 + 0.0 + 0.0) / 3, 3), abs=1e-6)
    assert grade_engine(summary) in "ABCDEF"
    assert grade_engine({"Accuracy %": 60, "ROI %": 10, "MAE": 2.5, "Avg CLV": 1.0}) == "A"
    assert grade_engine({"Accuracy %": 40, "ROI %": -10, "MAE": 9, "Avg CLV": -1}) == "F"


def test_compare_two_models():
    a = {"Model": "A", "ROI %": 5, "Accuracy %": 55, "MAE": 4}
    b = {"Model": "B", "ROI %": 5, "Accuracy %": 56, "MAE": 4}
    assert compare_two_models(a, b)[0] == "B"
    assert compare_two_models(a, dict(a))[0] == "TIE"


def test_prediction_csv_requires_columns():
    with pytest.raises(ValueError):
        load_prediction_results_csv(io.StringIO("player,line\nA,1\n"))
    df = load_prediction_results_csv(io.StringIO("player,line,over odds,under odds,projection,pick\nA,1,1.9,1.9,2,OVER\n"))
    assert list(df.columns)[:6] == ["Player", "Line", "Over Odds", "Under Odds", "Final Projection", "Model Pick"]
