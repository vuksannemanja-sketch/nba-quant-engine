import pandas as pd

from nba_engine.history import (DAILY_TAG, analysis_day, analysis_fingerprint, analysis_tag, find_same_fingerprint,
                                list_history, save_analysis)


def _df(proj=12.3):
    return pd.DataFrame({"Player": ["A", "B"], "Line": [10.5, 20.5], "Final Projection": [proj, 22.0],
                         "Model Pick": ["OVER", "UNDER"], "Best EV %": [5.0, 3.0], "True Score": [1.0, 0.5]})


def test_save_with_tag_and_name_parsing(tmp_path):
    p = save_analysis(_df(), tmp_path, "2026-11-01_22-30-05", tag=DAILY_TAG)
    q = save_analysis(_df(), tmp_path, "2026-11-01_19-13-52")
    assert p.name == "analysis_2026-11-01_22-30-05_daily.csv" and analysis_tag(p) == "daily" and analysis_tag(q) is None
    assert analysis_day(p) == "2026-11-01" and analysis_day("x.csv") is None
    assert [x.name for x in list_history(tmp_path)] == [q.name, p.name]


def test_find_same_fingerprint_only_same_day_and_same_result(tmp_path):
    df = _df()
    saved = save_analysis(df, tmp_path, "2026-11-01_19-13-52")
    assert analysis_fingerprint(pd.read_csv(saved)) == analysis_fingerprint(df)       # CSV ne mijenja otisak
    assert find_same_fingerprint(df, tmp_path, day="2026-11-01") == saved
    assert find_same_fingerprint(_df(proj=15.0), tmp_path, day="2026-11-01") is None  # drugi rezultat
    assert find_same_fingerprint(df, tmp_path, day="2026-11-02") is None             # drugi dan
    (tmp_path / "analysis_2026-11-01_20-00-00.csv").write_text("nije,csv\n1")        # oštećen fajl se preskače
    assert find_same_fingerprint(df, tmp_path, day="2026-11-01") == saved
