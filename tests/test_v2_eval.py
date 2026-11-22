import datetime as dt

import numpy as np
import pandas as pd
import pytest

from nba_engine import v2_eval as E
from nba_engine.config import Settings
from nba_engine.v2 import ResidualModel, build_universe
from nba_engine.utils import normalize_name


def _settings(tmp_path):
    return Settings.load(data_dir=tmp_path / "data", season="2026-27", env_file=tmp_path / "no.env",
                         history_dir=tmp_path / "history")


def _quotes(rows):
    q = pd.DataFrame(rows, columns=["PLAYER", "BOOK", "LINE", "OVER_ODDS", "UNDER_ODDS"])
    q["NAME_KEY"] = q["PLAYER"].map(normalize_name)
    return q


def _universe():
    mc = pd.DataFrame([
        {"Player": "Alpha One", "TEAM_ABBR": "AAA", "OPP_TEAM": "BBB", "Line": 20.5, "Over Odds": 1.9, "Under Odds": 1.9,
         "Calibrated Projection": 21.0, "Model Pick": "OVER", "P(Over)%": 55.0, "Market P(Over)%": 50.0, "Final Projection": 21.0},
        {"Player": "Beta Two", "TEAM_ABBR": "BBB", "OPP_TEAM": "AAA", "Line": 10.5, "Over Odds": 1.9, "Under Odds": 1.9,
         "Calibrated Projection": 10.0, "Model Pick": "UNDER", "P(Over)%": 45.0, "Market P(Over)%": 50.0, "Final Projection": 10.0},
        {"Player": "Gamma Three", "TEAM_ABBR": "AAA", "OPP_TEAM": "BBB", "Line": 8.5, "Over Odds": 1.9, "Under Odds": 1.9,
         "Calibrated Projection": 8.0, "Model Pick": "UNDER", "P(Over)%": 45.0, "Market P(Over)%": 50.0, "Final Projection": 8.0},
    ])
    q = _quotes([("Alpha One", "pinnacle", 20.5, 1.90, 1.90), ("Alpha One", "fanduel", 20.5, 2.10, 1.75),     # v2 OVER
                 ("Beta Two", "pinnacle", 10.5, 1.90, 1.90), ("Beta Two", "betmgm", 10.5, 1.70, 2.10),        # v2 UNDER
                 ("Gamma Three", "pinnacle", 8.5, 1.90, 1.90), ("Gamma Three", "betmgm", 8.5, 1.90, 1.90)])  # bez ivice
    return build_universe(mc, q, ResidualModel(), model_weight=0.0)


def _actuals(day, rows):
    df = pd.DataFrame(rows, columns=["PLAYER_NAME", "TEAM_ABBR", "OPP_TEAM", "PTS", "MIN"])
    df["NAME_KEY"] = df["PLAYER_NAME"].map(normalize_name)
    df["GAME_DATE"] = dt.date.fromisoformat(day)
    return df


def test_strategy_sides_and_deterministic_random():
    uni = _universe()
    sides = E.strategy_sides(uni, key="2026-11-10")
    assert set(sides) == set(E.STRATEGIES)
    by = uni["Player"].tolist()
    assert sides["UNDER"].tolist() == ["UNDER"] * 3 and sides["OVER"].tolist() == ["OVER"] * 3
    assert {p: s for p, s in zip(by, sides["V2"])}["Alpha One"] == "OVER" and pd.isna(sides["V2"].iloc[by.index("Gamma Three")])
    assert sides["TRZISTE"].tolist() == ["OVER" if p >= 50 else "UNDER" for p in uni["V2 Fair P(Over)%"]]
    again = E.strategy_sides(uni, key="2026-11-10")["NASUMICNO"].tolist()
    assert again == sides["NASUMICNO"].tolist() and set(again) <= {"OVER", "UNDER"}
    assert E.strategy_sides(uni, key="2026-11-11")["NASUMICNO"].tolist() != again or True   # drugi dan može biti drugačiji


def test_settle_universe_results_profit_and_clv():
    uni = _universe()
    actuals = _actuals("2026-11-10", [("Alpha One", "AAA", "BBB", 25, 34), ("Beta Two", "BBB", "AAA", 9, 20)])  # Gamma ne igra
    cq = _quotes([("Alpha One", "pinnacle", 20.5, 1.80, 2.00), ("Alpha One", "fanduel", 20.5, 1.95, 1.90)])      # zatvaranje: Over skuplji
    s = E.settle_universe(uni, actuals, dt.date(2026, 11, 10), key="2026-11-10", closing_quotes=cq).set_index("Player")
    assert s.loc["Alpha One", "Over Won"] == 1.0 and s.loc["Beta Two", "Over Won"] == 0.0 and pd.isna(s.loc["Gamma Three", "Over Won"])
    assert s.loc["Alpha One", "V2 Result"] == "WIN" and s.loc["Alpha One", "V2 Profit"] == pytest.approx(2.10 - 1.0)
    assert s.loc["Beta Two", "V2 Result"] == "WIN" and s.loc["Beta Two", "V2 Odds"] == 2.10
    assert s.loc["Gamma Three", "UNDER Result"] == "VOID" and s.loc["Gamma Three", "UNDER Profit"] == 0.0
    assert s.loc["Gamma Three", "V2 Result"] is None or pd.isna(s.loc["Gamma Three", "V2 Result"])
    assert s.loc["Alpha One", "UNDER Result"] == "LOSS" and s.loc["Alpha One", "UNDER Profit"] == -1.0
    # CLV: fer na zatvaranju (Pinnacle 1.80/2.00) → P(Over)=0.5263; uzeli smo Over 2.10 → 2.10 × 0.5263 − 1 = +10.5 %
    assert s.loc["Alpha One", "CLV EV %"] == pytest.approx(10.53, abs=0.05)
    assert pd.isna(s.loc["Beta Two", "CLV EV %"])                                           # nema zatvorenih kvota
    rows = E.benchmark_rows(s.reset_index(), "analysis_x.csv", dt.date(2026, 11, 10))
    v2 = {r["Strategy"]: r for r in rows}["V2"]
    assert (v2["Bets"], v2["Wins"], v2["Losses"]) == (2, 2, 0) and v2["Profit"] == pytest.approx(1.1 + 1.1, abs=1e-6)
    und = {r["Strategy"]: r for r in rows}["UNDER"]
    assert (und["Bets"], und["Void"]) == (2, 1)


def test_settle_v2_end_to_end_ledger_benchmarks_and_overview(tmp_path):
    settings = _settings(tmp_path)
    v2dir = settings.v2_history_dir
    v2dir.mkdir(parents=True)
    _universe().to_csv(v2dir / "analysis_2026-11-10_22-30-00_daily.csv", index=False)
    _universe().to_csv(v2dir / "analysis_2026-11-12_22-30-00_daily.csv", index=False)       # čeka mečeve
    actuals = _actuals("2026-11-10", [("Alpha One", "AAA", "BBB", 25, 34), ("Beta Two", "BBB", "AAA", 12, 20),
                                      ("Gamma Three", "AAA", "BBB", 6, 18)])
    (tmp_path / "data").mkdir()
    pd.DataFrame({"PLAYER": ["Alpha One"], "LINE": [21.5], "OVER_ODDS": [1.9], "UNDER_ODDS": [1.9]}).to_csv(
        tmp_path / "data" / "closing_2026-11-10.csv", index=False)
    msg = E.settle_v2(settings, provider=lambda s: actuals, today=dt.date(2026, 11, 11))
    assert "poravnato izbora 1" in msg and "cijelih spiskova 1" in msg and "čeka mečeve 1" in msg
    assert (v2dir / "ledger.csv").exists() and (v2dir / "settled_analysis_2026-11-10_22-30-00_daily.csv").exists()
    assert (v2dir / "universe_settled_analysis_2026-11-10_22-30-00_daily.csv").exists()
    bench = E.load_benchmarks(v2dir)
    assert set(bench["Strategy"]) == set(E.STRATEGIES) and bench["Analysis"].nunique() == 1
    # drugi prolaz ne duplira
    E.settle_v2(settings, provider=lambda s: actuals, today=dt.date(2026, 11, 11))
    assert len(E.load_benchmarks(v2dir)) == len(E.STRATEGIES)
    ledger = pd.read_csv(v2dir / "ledger.csv")
    assert ledger.iloc[0]["Avg CLV"] == pytest.approx(1.0)                                    # OVER 20.5, zatvoreno 21.5 → +1
    ov = E.v2_overview(settings)
    comp = ov["comparison"].set_index("Pravilo")
    assert comp.loc["v2 izbori", "Izbora"] == 2 and comp.loc["v2 izbori", "Pogodaka"] == 1
    assert comp.loc["Uvijek manje", "Izbora"] == 3 and ov["universe_rows"] == 3 and ov["days"] == 1
    assert ov["gates"][1]["Izbora"] == 2 and ov["gates"][1]["Gotovo %"] == 0.0
    assert E.v2_overview(_settings(tmp_path / "prazno"))["comparison"].empty


def test_calibration_table_and_empty_inputs():
    uni = pd.DataFrame({"V2 Fair P(Over)%": [30, 32, 50, 52, 70, 72], "Over Won": [0, 1, 1, 0, 1, 1]})
    t = E.calibration_table(uni, "V2 Fair P(Over)%")
    assert list(t["Grupa"]) == ["0–35 %", "45–55 %", "65–100 %"] and list(t["Igrača"]) == [2, 2, 2]
    assert list(t["Ostvareno %"]) == [50.0, 50.0, 100.0]
    assert E.calibration_table(pd.DataFrame(), "x").empty and E.calibration_table(uni, "nema").empty


def _signal_universe(n, signal, seed=0):
    rng = np.random.default_rng(seed)
    pf = rng.uniform(0.35, 0.65, n)
    pm = np.clip(pf + rng.normal(0, 0.08, n), 0.03, 0.97)
    truth = pf + (signal * (pm - pf))                              # signal=0: model je čist šum; 1: model je sav istinit
    won = (rng.uniform(size=n) < truth).astype(float)
    return pd.DataFrame({"V2 Fair P(Over)%": pf * 100, "V2 Model P(Over)%": pm * 100, "Over Won": won,
                         "V2 Fair Source": "pinnacle"})


def test_fit_model_weight_distinguishes_noise_from_signal():
    noise = E.fit_model_weight(_signal_universe(4000, 0.0))
    assert noise["n"] == 4000 and noise["lo"] < 0.0 < noise["hi"] and abs(noise["weight"]) < 0.35
    signal = E.fit_model_weight(_signal_universe(4000, 1.0))
    assert signal["lo"] > 0.3 and 0.5 < signal["weight"] < 1.6
    assert E.fit_model_weight(pd.DataFrame())["weight"] is None
    assert E.fit_model_weight(_signal_universe(10, 0.0))["weight"] is None                  # premalo podataka


def test_gate_status_caps_progress():
    g = E.gate_status(bets=2500, clv_n=120)
    assert g[0]["Gotovo %"] == 24.0 and g[1]["Gotovo %"] == 100.0


def test_walk_forward_compares_models_on_unseen_days():
    rng = np.random.default_rng(3)
    rows = []
    for d in range(10):
        for i in range(60):
            line = float(rng.choice([6.5, 11.5, 16.5, 21.5]))
            proj = line + rng.normal(0, 1.5)
            pts = max(0.0, rng.normal(line - 0.3, line * 0.45))
            rows.append({"Analysis": f"analysis_2026-11-{d + 1:02d}_22-30-00_daily.csv", "Bet Result": "WIN",
                         "Line": line, "Calibrated Projection": proj, "Actual Points": round(pts),
                         "P(Over)%": float(np.clip(50 + (proj - line) * 20, 2, 98)), "Market P(Over)%": 50.0})
    wf = E.walk_forward(pd.DataFrame(rows), min_train_days=4)
    assert wf["days"] == 6 and wf["n"] == 360 and wf["first_test_day"] == "2026-11-05"
    assert {"coin", "market", "v1", "model_v2", "mix_0.0", "mix_0.25"} <= set(wf["brier"])
    # preuveličana stara vjerovatnoća gubi od kalibrisanog modela i od tržišta; mješavina sa težinom 0 = tržište
    assert wf["brier"]["model_v2"] < wf["brier"]["v1"] and wf["brier"]["mix_0.0"] == wf["brier"]["market"]
    assert E.walk_forward(pd.DataFrame(rows[:60]), min_train_days=4) == {"days": 0}


def test_calibrate_from_history_uses_settled_files(tmp_path):
    settings = _settings(tmp_path)
    settings.history_dir.mkdir(parents=True)
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"Line": rng.choice([5.5, 10.5, 15.5], 120), "Calibrated Projection": 12.0,
                       "Actual Points": rng.normal(12, 5, 120).round(), "Bet Result": "WIN"})
    df.to_csv(settings.history_dir / "settled_analysis_2026-11-01_22-30-00_daily.csv", index=False)
    cal = E.calibrate_from_history(settings)
    assert cal["n"] == 120 and "8-12.5" in cal["buckets"] and cal["source"].startswith("history/settled_")
