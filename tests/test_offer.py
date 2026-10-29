import pandas as pd

from nba_engine.offer import (OfferRow, parse_injury_override, parse_offer_text, parse_recent_form_input,
                              parse_rest_days, parse_team_list)


def test_parse_offer_7_columns_with_header():
    txt = ("PLAYER,PLAYER_TEAM,LINE,OVER_ODDS,UNDER_ODDS,OPP_TEAM,TOTAL_MATCH\n"
           "Luka Doncic,LAL,32.5,2.00,1.78,DET,225.5\n"
           "Austin Reaves,LAL,21.5,2.02,1.77,DET,\n")
    rows, bad = parse_offer_text(txt)
    assert bad == []
    assert rows[0] == OfferRow("Luka Doncic", 32.5, 2.0, 1.78, "DET", 225.5)
    assert rows[1].total_match is None and rows[1].opp_team == "DET"


def test_parse_offer_4_5_6_columns():
    rows, bad = parse_offer_text("A B,10.5,1.9,1.9\nC D,11.5,1.8,2.0,BOS\nE F,12.5,1.7,2.1,220.5\nG H,13.5,1.6,2.2,MIA,230")
    assert bad == []
    assert rows[0].opp_team is None and rows[0].total_match is None
    assert rows[1].opp_team == "BOS" and rows[1].total_match is None
    assert rows[2].opp_team is None and rows[2].total_match == 220.5
    assert rows[3].opp_team == "MIA" and rows[3].total_match == 230.0


def test_parse_offer_delimiters_and_bad_rows():
    rows, bad = parse_offer_text("A B;10,5;1,9;1,9\nX Y\tz\t1\t2\t3\nbroken,row\n,10,1.9,1.9\nName,abc,1.9,1.9")
    assert rows[0].line == 10.5 and rows[0].over_odds == 1.9  # ; sa decimalnim zarezom
    reasons = [r for _, r in bad]
    assert any("Wrong number of columns" in r for r in reasons)
    assert any("Empty player name" in r for r in reasons)
    assert any("Cannot parse numeric" in r for r in reasons)


def test_parse_offer_invalid_opp_team_becomes_none():
    rows, _ = parse_offer_text("A B,10.5,1.9,1.9,XXX,210")
    assert rows[0].opp_team is None and rows[0].total_match == 210.0


def test_recent_form_and_team_lists():
    assert parse_recent_form_input("Gui Santos, 18.2\n# komentar\nbad line\nX Y, 0") == {"gui santos": 18.2}
    assert parse_team_list(" det, mem ,,LAL") == {"DET", "MEM", "LAL"}
    assert parse_team_list("") == set()
    assert parse_rest_days("OKC=3, MIN=2, bad, CLE=x") == {"OKC": 3, "MIN": 2}


def test_parse_injury_override_uses_players_team():
    players = pd.DataFrame({"NAME_KEY": ["joel embiid"], "TEAM_ABBR": ["PHI"]})
    df = parse_injury_override("Joel Embiid, OUT\nSomeone Else, ankle sprain questionable", players)
    assert df.iloc[0]["TEAM_ABBR"] == "PHI" and df.iloc[0]["STATUS"] == "OUT"
    assert df.iloc[1]["STATUS"] == "QUESTIONABLE" and pd.isna(df.iloc[1]["TEAM_ABBR"])
    assert parse_injury_override("", players).empty
