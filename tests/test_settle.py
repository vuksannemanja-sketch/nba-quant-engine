"""Automatska evaluacija (settle): datumi, stvarni poeni iz game loga, poravnanje, ledger. Sve bez mreže."""
import datetime as dt

import pandas as pd
import pytest

from nba_engine import settle as S


def test_game_date_from_filename_with_us_day_cutoff():
    assert S.game_date_for("history/analysis_2026-10-30_19-05-00.csv") == dt.date(2026, 10, 30)
    assert S.game_date_for("analysis_2026-10-31_01-20-00.csv") == dt.date(2026, 10, 30)   # poslije ponoći → prethodni US dan
    assert S.game_date_for("analysis_2026-10-31_06-00-00.csv") == dt.date(2026, 10, 31)
    assert S.game_date_for("settled_analysis_2026-10-31_06-00-00.csv") == dt.date(2026, 10, 31)
    assert S.game_date_for("nesto.csv") is None


def test_opponent_from_matchup():
    assert S.opponent_from_matchup("LAL vs. OKC", "LAL") == "OKC"
    assert S.opponent_from_matchup("LAL @ OKC", "OKC") == "LAL"
    assert S.opponent_from_matchup("", "LAL") == ""


def _game_log():
    return pd.DataFrame({
        "PLAYER_NAME": ["Luka Doncic", "Luka Doncic", "Jaxson Hayes", "Mike Conley", "Rui Hachimura"],
        "TEAM_ABBREVIATION": ["LAL", "LAL", "UTA", "BOS", "LAL"],
        "GAME_DATE": ["2026-10-29", "2026-10-30", "2026-10-30", "2026-10-30", "2026-10-28"],
        "MATCHUP": ["LAL @ DEN", "LAL vs. OKC", "UTA vs. OKC", "BOS @ SAS", "LAL vs. PHX"],
        "PTS": [31, 24, 4.5, 9, 12], "MIN": [36.0, 35.0, 20.0, 22.0, 30.0],
    })


def test_actuals_from_game_log_and_find_actual():
    a = S.actuals_from_game_log(_game_log())
    assert set(a.columns) >= {"NAME_KEY", "TEAM_ABBR", "OPP_TEAM", "GAME_DATE", "PTS", "MIN"}
    assert a[a["NAME_KEY"] == "luka doncic"]["OPP_TEAM"].tolist() == ["DEN", "OKC"]
    d = dt.date(2026, 10, 30)
    # B2B: po protivniku se bira pravi meč, i kad je dan ranije
    assert S.find_actual(a, "luka doncic", "DEN", d)["PTS"] == 31
    assert S.find_actual(a, "luka doncic", "OKC", d)["PTS"] == 24
    assert S.find_actual(a, "luka doncic", "BOS", d) is None            # taj meč nije odigran
    assert S.find_actual(a, "mike conley", None, d)["PTS"] == 9          # bez protivnika: tačan datum
    assert S.find_actual(a, "rui hachimura", None, d) is None            # igrao 2 dana ranije, nije u ±1
    assert S.find_actual(a, "nepoznat igrac", "OKC", d) is None


def _analysis():
    return pd.DataFrame({
        "Player": ["Luka Doncic", "Jaxson Hayes", "Mike Conley", "Rui Hachimura", "Ayo Dosunmu"],
        "TEAM_ABBR": ["LAL", "UTA", "BOS", "LAL", "MIN"], "OPP_TEAM": ["OKC", "OKC", "SAS", "OKC", "SAS"],
        "Line": [27.5, 4.5, 10.5, 11.5, 9.5], "Over Odds": [1.9, 2.07, 1.85, 1.9, 1.9], "Under Odds": [1.9, 1.74, 1.95, 1.9, 1.9],
        "Final Projection": [25.0, 6.5, 12.0, 13.0, 13.7], "Projection Edge": [-2.5, 2.0, 1.5, 1.5, 4.2],
        "Model Pick": ["UNDER", "OVER", "OVER", "OVER", "NO VALUE"], "Best EV %": [12.0, 35.0, 8.0, 5.0, -1.0],
    })


def test_settle_analysis_results_profit_void_and_grade():
    actuals = S.actuals_from_game_log(_game_log())
    settled, row = S.settle_analysis(_analysis(), actuals, dt.date(2026, 10, 30), stake=1.0)
    by = settled.set_index("Player")["Bet Result"].to_dict()
    assert by == {"Luka Doncic": "WIN", "Jaxson Hayes": "PUSH", "Mike Conley": "LOSS", "Rui Hachimura": "VOID"}
    assert "Ayo Dosunmu" not in by                                     # NO VALUE se ne kladi
    assert row["Picks"] == 4 and row["Settled"] == 2 and row["Wins"] == 1 and row["Losses"] == 1
    assert row["Pushes"] == 1 and row["Void"] == 1 and row["Accuracy %"] == 50.0
    assert row["Profit"] == round(0.9 - 1.0, 2) and row["Staked"] == 2.0 and row["ROI %"] == -5.0
    assert row["MAE"] == pytest.approx((abs(25 - 24) + abs(6.5 - 4.5) + abs(12 - 9)) / 3, abs=1e-3)
    assert row["Grade"] in "ABCDF" and row["Game Date"] == "2026-10-30"
    assert settled.loc[settled["Player"] == "Luka Doncic", "Actual Opp"].iloc[0] == "OKC"


def test_settle_analysis_without_picks():
    df = _analysis().assign(**{"Model Pick": "NO VALUE"})
    settled, row = S.settle_analysis(df, S.actuals_from_game_log(_game_log()), dt.date(2026, 10, 30))
    assert settled.empty and row["Picks"] == 0 and row["Settled"] == 0 and row["Grade"] == "-"


def test_settle_history_ledger_pending_no_data_and_skip(tmp_path):
    hist = tmp_path / "history"
    hist.mkdir()
    _analysis().to_csv(hist / "analysis_2026-10-30_19-00-00.csv", index=False)   # mečevi 30.10. → završeni
    _analysis().to_csv(hist / "analysis_2026-11-02_19-00-00.csv", index=False)   # game log još nema 2.11.
    _analysis().to_csv(hist / "analysis_2026-11-03_19-00-00.csv", index=False)   # danas → pending
    calls = []

    def provider(season):
        calls.append(season)
        return S.actuals_from_game_log(_game_log())

    today = dt.date(2026, 11, 3)
    msgs = []
    events = S.settle_history(hist, provider=provider, today=today, log=msgs.append)
    status = {e["Analysis"]: e["status"] for e in events}
    assert status == {"analysis_2026-10-30_19-00-00.csv": "settled",
                      "analysis_2026-11-02_19-00-00.csv": "no_data",
                      "analysis_2026-11-03_19-00-00.csv": "pending"}
    assert calls == ["2026-27", "2026-27"]
    assert (hist / "settled_analysis_2026-10-30_19-00-00.csv").exists()
    ledger = S.load_ledger(hist)
    assert len(ledger) == 1 and ledger.iloc[0]["Wins"] == 1 and ledger.iloc[0]["Void"] == 1
    assert any("ocjena" in m for m in msgs)

    # drugi prolaz: poravnato se preskače, ostalo isto
    events2 = S.settle_history(hist, provider=provider, today=today)
    assert [e["status"] for e in events2] == ["no_data", "pending"]
    assert len(S.load_ledger(hist)) == 1
    # force → ponovo poravna, bez dupliranja u ledgeru
    events3 = S.settle_history(hist, provider=provider, today=today, force=True)
    assert events3[0]["status"] == "settled" and len(S.load_ledger(hist)) == 1

    overall = S.overall_summary(S.load_all_settled(hist))
    assert overall["Bets"] == 2 and overall["Wins"] == 1 and overall["Void"] == 1 and overall["Days"] == 1
    assert overall["Accuracy %"] == 50.0 and overall["ROI %"] == -5.0 and overall["Grade"] in "ABCDF"
    assert S.overall_summary(pd.DataFrame())["Bets"] == 0


def test_settle_history_provider_error_is_reported(tmp_path):
    hist = tmp_path / "h"
    hist.mkdir()
    _analysis().to_csv(hist / "analysis_2026-10-30_19-00-00.csv", index=False)

    def broken(season):
        raise ConnectionError("offline")
    events = S.settle_history(hist, provider=broken, today=dt.date(2026, 11, 3))
    assert events[0]["status"] == "error" and "offline" in events[0]["detail"]
    assert S.load_ledger(hist).empty
