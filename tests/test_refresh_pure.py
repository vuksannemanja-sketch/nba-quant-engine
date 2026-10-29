"""Testovi čistih funkcija osvježavanja (bez mreže)."""
import pandas as pd

from nba_engine.refresh import ALL_STEPS, DEFAULT_STEPS, STEP_LABELS
from nba_engine.refresh.h2h import compute_h2h, extract_matchup_opponent, filter_relevant_h2h
from nba_engine.refresh.injuries import merge_injury_sources, normalize_status, parse_bulk_payload
from nba_engine.refresh.matchups import compute_form_table
from nba_engine.refresh.players import build_teams, merge_bio
from nba_engine.refresh.schedule import build_b2b_flags, build_schedule


def test_steps_registry():
    assert ALL_STEPS == ["offer", "players", "injuries", "matchups", "schedule", "h2h"]
    assert "h2h" not in DEFAULT_STEPS and all(s in STEP_LABELS for s in DEFAULT_STEPS)


def test_matchup_opponent():
    assert extract_matchup_opponent("DET vs. MEM", "DET") == "MEM"
    assert extract_matchup_opponent("DET @ MEM", "MEM") == "DET"
    assert extract_matchup_opponent("DET @ MEM", "BOS") == "" and extract_matchup_opponent("", "DET") == ""


def test_compute_h2h_from_game_log():
    gl = pd.DataFrame({
        "PLAYER_NAME": ["A"] * 3 + ["B"], "TEAM_ABBREVIATION": ["DET"] * 3 + ["BOS"],
        "MATCHUP": ["DET vs. MEM", "DET @ MEM", "DET vs. BOS", "BOS @ DET"],
        "PTS": [20, 30, 10, 15], "GAME_DATE": ["2026-01-01", "2026-02-01", "2026-03-01", "2026-03-01"],
    })
    h2h = compute_h2h(gl)
    row = h2h[(h2h["PLAYER_NAME"] == "A") & (h2h["OPP_TEAM"] == "MEM")].iloc[0]
    assert row["H2H_GAMES"] == 2 and row["H2H_PTS_AVG"] == 25.0 and row["H2H_PTS_LAST"] == 30.0
    assert row["H2H_LAST_DATE"] == "2026-02-01" and row["H2H_PTS_STD"] == 5.0
    assert len(filter_relevant_h2h(h2h, 2)) == 1
    assert compute_h2h(pd.DataFrame()).empty


def test_compute_form_table():
    dates = pd.date_range("2026-01-01", periods=12).strftime("%Y-%m-%d")
    gl = pd.DataFrame({"PLAYER_NAME": ["A"] * 12, "PLAYER_ID": [1] * 12, "GAME_DATE": dates,
                       "PTS": list(range(10, 22)), "MIN": ["30:15"] * 12, "TEAM_ABBREVIATION": ["DET"] * 12})
    form = compute_form_table(gl)
    r = form.iloc[0]
    assert r["GAMES_PLAYED"] == 12 and r["LAST_PTS"] == 21 and r["L3_PTS"] == 20.0 and r["L10_PTS"] == 16.5
    assert r["TREND_SLOPE"] > 0 and r["L10_MIN"] == 30.0 and r["LAST_DATE"] == dates[-1]
    assert compute_form_table(pd.DataFrame(columns=["PLAYER_NAME"])).empty


def test_schedule_and_b2b():
    gl = pd.DataFrame({
        "GAME_ID": ["g1", "g1", "g2", "g2"], "GAME_DATE": ["2026-01-10"] * 2 + ["2026-01-11"] * 2,
        "TEAM_ID": [1610612765, 1610612763, 1610612765, 1610612738],
        "MATCHUP": ["DET vs. MEM", "MEM @ DET", "DET @ BOS", "BOS vs. DET"],
    })
    sch = build_schedule(gl)
    assert sch.iloc[0].tolist() == ["2026-01-10", "DET", "MEM", "g1"] and len(sch) == 2
    b2b = build_b2b_flags(sch)
    det = b2b[b2b["TEAM_ABBR"] == "DET"].set_index("GAME_DATE")["IS_B2B"]
    assert det["2026-01-10"] == False and det["2026-01-11"] == True  # noqa: E712
    assert build_schedule(pd.DataFrame()).empty and build_b2b_flags(build_schedule(pd.DataFrame())).empty


def test_injury_parsing_and_merge():
    assert normalize_status("Out") == "OUT" and normalize_status("Game Time Decision") == "QUESTIONABLE"
    assert normalize_status("weird") == "QUESTIONABLE"
    payload = {"injuries": [
        {"team": {"displayName": "Boston Celtics"}, "injuries": [
            {"athlete": {"displayName": "Al Horford"}, "status": "Out", "shortComment": "calf"}]},
        {"team": {"abbreviation": "det"}, "injuries": [
            {"athlete": {"fullName": "Cade Cunningham"}, "status": "Questionable", "type": {"description": "ankle"}}]},
    ]}
    rows = parse_bulk_payload(payload)
    assert [(r["PLAYER"], r["TEAM_ABBR"], r["STATUS"]) for r in rows] == [
        ("Al Horford", "BOS", "OUT"), ("Cade Cunningham", "DET", "QUESTIONABLE")]
    merged = merge_injury_sources(rows, [{"PLAYER": "Al Horford", "TEAM_ABBR": "BOS", "STATUS": "PROBABLE", "DESCRIPTION": ""}])
    assert len(merged) == 2 and merged[merged["PLAYER"] == "Al Horford"]["STATUS"].iloc[0] == "OUT"
    assert list(merge_injury_sources([]).columns) == ["PLAYER", "TEAM_ABBR", "STATUS", "DESCRIPTION"]


def test_players_helpers():
    base = pd.DataFrame({"PLAYER_ID": [1, 2], "PTS": [10, 20]})
    bio = pd.DataFrame({"PLAYER_ID": [1], "PLAYER_HEIGHT_INCHES": [80], "COLLEGE": ["X"]})
    merged = merge_bio(base, bio)
    assert "PLAYER_HEIGHT_INCHES" in merged.columns and merged.loc[1, "PLAYER_HEIGHT_INCHES"] != merged.loc[0, "PLAYER_HEIGHT_INCHES"]
    assert merge_bio(base, None).equals(base)
    teams = build_teams(pd.DataFrame({"TEAM_ID": [1610612738], "PTS": [115.0]}),
                        pd.DataFrame({"TEAM_ID": [1610612738], "OFF_RATING": [118.0], "PACE": [99.0]}))
    assert teams.iloc[0]["TEAM_ABBR"] == "BOS" and teams.iloc[0]["OFF_RATING"] == 118.0
