import datetime
import os

from nba_engine.config import (Settings, detect_season_from_data, load_dotenv, parse_env_file, previous_season,
                               resolve_season, season_from_date, seasons_back)


def test_season_helpers():
    assert season_from_date(datetime.date(2026, 10, 29)) == "2026-27"
    assert season_from_date(datetime.date(2026, 3, 1)) == "2025-26"
    assert previous_season("2026-27") == "2025-26"
    assert seasons_back("2025-26", 3) == ["2025-26", "2024-25", "2023-24"]


def test_detect_season_from_data(tmp_path):
    assert detect_season_from_data(tmp_path) is None
    (tmp_path / "players_2024-25.csv").write_text("x")
    (tmp_path / "teams_2025-26.csv").write_text("x")
    assert detect_season_from_data(tmp_path) == "2025-26"


def test_resolve_season_priority(tmp_path, monkeypatch):
    (tmp_path / "players_2024-25.csv").write_text("x")
    monkeypatch.delenv("NBA_SEASON", raising=False)
    assert resolve_season(None, tmp_path) == ("2024-25", "data")
    assert resolve_season("2022-23", tmp_path) == ("2022-23", "argument")
    monkeypatch.setenv("NBA_SEASON", "2023-24")
    assert resolve_season(None, tmp_path) == ("2023-24", "env")
    assert resolve_season(None, tmp_path / "empty", today=datetime.date(2026, 11, 1))[0] == "2023-24"
    monkeypatch.delenv("NBA_SEASON")
    assert resolve_season(None, tmp_path / "empty", today=datetime.date(2026, 11, 1)) == ("2026-27", "datum")


def test_env_file_parsing_and_settings(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# komentar\nODDS_API_KEY="abc123"\nexport NBA_SEASON=2026-27\nODDS_BOOKMAKERS=bet365, pinnacle\nBAD LINE\n')
    assert parse_env_file(env) == {"ODDS_API_KEY": "abc123", "NBA_SEASON": "2026-27", "ODDS_BOOKMAKERS": "bet365, pinnacle"}
    for k in ("ODDS_API_KEY", "NBA_SEASON", "ODDS_BOOKMAKERS", "NBA_DATA_DIR", "NBA_HISTORY_DIR"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.load(data_dir=tmp_path / "data", env_file=env)
    assert s.odds_api_key == "abc123" and s.season == "2026-27" and s.season_source == "env"
    assert s.bookmaker_priority == ("bet365", "pinnacle")
    assert s.primary_csv_path("players_main").name == "players_2026-27.csv"
    assert s.csv_path("players_main") is None and s.find_offer() is None
    assert [r["exists"] for r in s.data_status()].count(True) == 0
    # load_dotenv ne gazi postojeće vrijednosti
    os.environ["ODDS_API_KEY"] = "keep"
    load_dotenv(env)
    assert os.environ["ODDS_API_KEY"] == "keep"
