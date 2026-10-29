import math

import numpy as np
import pandas as pd
import pytest

from nba_engine.teams import ABBR_TO_TEAM_ID, TEAM_ID_TO_ABBR, normalize_team_abbr, team_name_to_abbr
from nba_engine.utils import (clamp, extract_injury_status, fix_usg_scale, get_float, normalize_name,
                              safe_float, smart_decode, status_weight, zscore)


@pytest.mark.parametrize("raw,expected", [
    ("Nikola Jokić", "nikola jokic"),
    ("  LeBron James  ", "lebron james"),
    ("Jaren Jackson Jr.", "jaren jackson"),
    ("Gary Trent Jr", "gary trent"),
    ("Robert Williams III", "robert williams"),
    ("De'Aaron Fox", "de aaron fox"),
    ("Kristaps Porziņģis", "kristaps porzingis"),
    ('"Shai Gilgeous-Alexander"', "shai gilgeous alexander"),
    ("Joki\xc4\x87", "jokic"),  # UTF-8 bajtovi pročitani kao latin-1 (pogrešno dekodirano ime)
    (None, ""),
    ("", ""),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("1.95", 1.95), ("1,95", 1.95), (' "2.10" ', 2.10), (3, 3.0),
    ("", None), (None, None), ("abc", None), ("nan", None), (float("nan"), None), (float("inf"), None),
])
def test_safe_float(raw, expected):
    assert safe_float(raw) == expected


def test_smart_decode_handles_utf16_and_cp1252():
    assert smart_decode("Jokić,25.5".encode("utf-16")) == "Jokić,25.5"
    assert "Jokic" in smart_decode("Jokic,25.5".encode("cp1252"))


def test_get_float_and_clamp():
    row = pd.Series({"A": "3.5", "B": np.nan, "C": np.inf})
    assert get_float(row, "A") == 3.5
    assert get_float(row, "B", 7.0) == 7.0
    assert get_float(row, "C", 1.0) == 1.0
    assert get_float(row, "missing", 9.0) == 9.0
    assert clamp(15, 0, 10) == 10 and clamp(-1, 0, 10) == 0 and clamp("x", 0, 10) == 5


def test_zscore_is_centered():
    z = zscore(pd.Series([1.0, 2.0, 3.0, 4.0]))
    assert abs(z.mean()) < 1e-9 and z.iloc[-1] > 0 > z.iloc[0]


@pytest.mark.parametrize("desc,status", [
    ("Bailey (concussion) has been ruled out for Sunday's game", "OUT"),
    ("Out for season", "OUT"), ("questionable (ankle)", "QUESTIONABLE"), ("Doubtful", "DOUBTFUL"),
    ("day-to-day", "QUESTIONABLE"), ("inactive", "INACTIVE"), ("probable", "PROBABLE"), ("", "UNKNOWN"),
])
def test_extract_injury_status(desc, status):
    assert extract_injury_status(desc) == status


def test_status_weight():
    assert status_weight("OUT") == 1.0 and status_weight("questionable") == 0.40 and status_weight("x") == 0.0


def test_fix_usg_scale_only_when_decimal():
    df = pd.DataFrame({"USG_PCT": [0.25, 0.18]})
    assert fix_usg_scale(df)["USG_PCT"].tolist() == [25.0, 18.0]
    df2 = pd.DataFrame({"USG_PCT": [25.0, 18.0]})
    assert fix_usg_scale(df2)["USG_PCT"].tolist() == [25.0, 18.0]


@pytest.mark.parametrize("raw,expected", [
    ("BOS", "BOS"), (" bos ", "BOS"), (1610612738, "BOS"), ("1610612738.0", "BOS"),
    ("Boston Celtics", "BOS"), ("LA Clippers", "LAC"), ("Philadelphia 76ers", "PHI"),
])
def test_normalize_team_abbr_valid(raw, expected):
    assert normalize_team_abbr(raw) == expected


@pytest.mark.parametrize("raw", [None, float("nan"), "", "XYZ", "nan", 12345])
def test_normalize_team_abbr_invalid(raw):
    out = normalize_team_abbr(raw)
    assert isinstance(out, float) and math.isnan(out)


def test_team_maps_consistent():
    assert len(TEAM_ID_TO_ABBR) == 30 and len(ABBR_TO_TEAM_ID) == 30
    assert team_name_to_abbr("Oklahoma City Thunder") == "OKC"
    assert team_name_to_abbr("Unknown Team") == "UNK"
    assert team_name_to_abbr("") == ""
