import pandas as pd

from nba_engine.config import Settings
from nba_engine.odds_api import (OddsApiClient, OddsApiError, extract_player_props, fetch_daily_offer,
                                 find_player_team, order_bookmakers, props_to_frame)
from nba_engine.utils import normalize_name


def _players():
    df = pd.DataFrame({"PLAYER_NAME": ["Shai Gilgeous-Alexander", "Cade Cunningham", "Jalen Williams", "Jaylin Williams"],
                       "TEAM_ABBR": ["OKC", "DET", "OKC", "OKC"]})
    df["NAME_KEY"] = df["PLAYER_NAME"].map(normalize_name)
    return df


def _event_payload(bookies):
    def market(players):
        outcomes = []
        for name, line, over, under in players:
            outcomes.append({"name": "Over", "description": name, "price": over, "point": line})
            outcomes.append({"name": "Under", "description": name, "price": under, "point": line})
        return {"key": "player_points", "outcomes": outcomes}
    return {"bookmakers": [{"key": k, "markets": [market(p)]} for k, p in bookies]}


def test_find_player_team_strategies():
    p = _players()
    assert find_player_team("Shai Gilgeous-Alexander", p) == "OKC"
    assert find_player_team("C. Cunningham", p) == "DET"  # prezime + inicijal
    assert find_player_team("Jalen Williams", p) == "OKC"
    assert find_player_team("J. Williams", p) is None  # dvosmisleno
    assert find_player_team("Nobody", p) is None and find_player_team("X", None) is None


def test_extract_props_respects_bookmaker_priority():
    data = _event_payload([("draftkings", [("Cade Cunningham", 27.5, 1.9, 1.9)]),
                           ("pinnacle", [("Cade Cunningham", 26.5, 1.95, 1.85), ("Shai Gilgeous-Alexander", 30.5, 1.9, 1.9)])])
    props = extract_player_props(data, "DET", "OKC", 220.5, _players(), priority=("pinnacle", "bet365"))
    assert {p["BOOKMAKER"] for p in props} == {"pinnacle"}
    by_name = {p["PLAYER"]: p for p in props}
    assert by_name["Cade Cunningham"]["LINE"] == 26.5 and by_name["Cade Cunningham"]["OPP_TEAM"] == "OKC"
    assert by_name["Shai Gilgeous-Alexander"]["OPP_TEAM"] == "DET" and by_name["Shai Gilgeous-Alexander"]["TOTAL_MATCH"] == 220.5
    df = props_to_frame(props)
    assert list(df.columns) == ["PLAYER", "PLAYER_TEAM", "LINE", "OVER_ODDS", "UNDER_ODDS", "OPP_TEAM", "TOTAL_MATCH"]
    assert df["LINE"].is_monotonic_decreasing
    assert [b["key"] for b in order_bookmakers([{"key": "x"}, {"key": "pinnacle"}], ("pinnacle",))] == ["pinnacle", "x"]


def test_extract_props_skips_incomplete_and_empty():
    data = {"bookmakers": [{"key": "b", "markets": [{"key": "player_points", "outcomes": [
        {"name": "Over", "description": "Only Over", "price": 1.9, "point": 10.5}]}]}]}
    assert extract_player_props(data, "DET", "OKC", None, _players()) == []
    assert extract_player_props({}, "DET", "OKC", None, _players()) == []


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._payload, self.headers = status, payload, {"x-requests-remaining": "42"}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeHttp:
    def __init__(self, routes, status=200):
        self.routes, self.status = routes, status

    def get(self, url, params=None, timeout=None):
        # najduži ključ koji je sufiks URL-a (da /events ne uhvati /events/ev1/odds)
        for key in sorted(self.routes, key=len, reverse=True):
            if url.endswith(key):
                return _FakeResp(self.status, self.routes[key])
        return _FakeResp(404, {})


def test_fetch_daily_offer_writes_files(tmp_path, monkeypatch):
    for k in ("ODDS_API_KEY", "NBA_SEASON", "ODDS_BOOKMAKERS", "NBA_DATA_DIR", "NBA_HISTORY_DIR"):
        monkeypatch.delenv(k, raising=False)
    settings = Settings.load(data_dir=tmp_path, season="2025-26", env_file=tmp_path / "no.env")
    events = [{"id": "ev1", "home_team": "Detroit Pistons", "away_team": "Oklahoma City Thunder"}]
    routes = {"/events": events, "/events/ev1/odds": _event_payload([("pinnacle", [("Cade Cunningham", 27.5, 1.9, 1.85)])])}
    client = OddsApiClient("key", http=_FakeHttp(routes))
    res = fetch_daily_offer(settings, log=lambda m: None, players_df=_players(), client=client)
    assert res.ok, res.message
    assert (tmp_path / "offer_latest.csv").exists() and (tmp_path / "dnevna_ponuda.csv").exists()
    df = pd.read_csv(tmp_path / "offer_latest.csv")
    assert df.iloc[0]["PLAYER"] == "Cade Cunningham" and df.iloc[0]["OPP_TEAM"] == "OKC"
    assert "preostalo API zahtjeva: 42" in res.message


def test_fetch_daily_offer_reports_bad_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    settings = Settings.load(data_dir=tmp_path, season="2025-26", env_file=tmp_path / "no.env")
    res = fetch_daily_offer(settings, log=lambda m: None, players_df=_players(),
                            client=OddsApiClient("bad", http=_FakeHttp({"/events": []}, status=401)))
    assert not res.ok and "401" in res.message
    res2 = fetch_daily_offer(settings, log=lambda m: None, players_df=_players(), client=OddsApiClient(""))
    assert not res2.ok and "ODDS_API_KEY" in res2.message
