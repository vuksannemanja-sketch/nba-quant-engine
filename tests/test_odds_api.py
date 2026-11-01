import pandas as pd

from nba_engine.config import Settings
import datetime as dt

from nba_engine.odds_api import (OddsApiClient, OddsApiError, current_game_date, event_game_date,
                                 event_has_player_points, extract_player_props, fetch_daily_offer,
                                 find_player_team, order_bookmakers, props_to_frame, select_events_for_game_date)
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
        self.calls = []  # (sufiks URL-a, markets) — za brojanje API poziva

    def get(self, url, params=None, timeout=None):
        self.calls.append((url.rsplit("/sports/basketball_nba", 1)[-1], (params or {}).get("markets")))
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


def test_extract_props_best_odds_across_books_on_same_line():
    from nba_engine.odds_api import OFFER_COLUMNS, OFFER_DETAIL_COLUMNS
    data = _event_payload([("pinnacle", [("Cade Cunningham", 26.5, 1.90, 1.90)]),
                           ("draftkings", [("Cade Cunningham", 26.5, 2.00, 1.80), ("Jalen Williams", 20.5, 1.9, 1.9)]),
                           ("bet365", [("Cade Cunningham", 27.5, 2.30, 1.60)])])   # druga linija se ne miješa
    props = extract_player_props(data, "DET", "OKC", None, _players(), priority=("pinnacle", "draftkings", "bet365"))
    by = {p["PLAYER"]: p for p in props}
    cade = by["Cade Cunningham"]
    assert cade["LINE"] == 26.5 and cade["BOOKMAKER"] == "pinnacle"
    assert cade["OVER_ODDS"] == 2.00 and cade["OVER_BOOK"] == "draftkings"
    assert cade["UNDER_ODDS"] == 1.90 and cade["UNDER_BOOK"] == "pinnacle"
    assert cade["N_BOOKS"] == 3 and cade["N_BOOKS_SAME_LINE"] == 2
    assert by["Jalen Williams"]["BOOKMAKER"] == "draftkings" and by["Jalen Williams"]["OPP_TEAM"] == "DET"
    single = extract_player_props(data, "DET", "OKC", None, _players(), priority=("pinnacle",), best_odds=False)
    s_cade = {p["PLAYER"]: p for p in single}["Cade Cunningham"]
    assert s_cade["OVER_ODDS"] == 1.90 and s_cade["OVER_BOOK"] == "pinnacle" and s_cade["N_BOOKS"] == 3
    assert list(props_to_frame(props).columns) == OFFER_COLUMNS
    assert list(props_to_frame(props, detail=True).columns) == OFFER_DETAIL_COLUMNS


def test_fetch_daily_offer_closing_writes_only_closing_file(tmp_path):
    settings = Settings.load(data_dir=tmp_path, season="2025-26", env_file=tmp_path / "no.env")
    events = [{"id": "ev1", "home_team": "Detroit Pistons", "away_team": "Oklahoma City Thunder"}]
    routes = {"/events": events, "/events/ev1/odds": _event_payload([("pinnacle", [("Cade Cunningham", 27.5, 1.9, 1.85)])])}
    client = OddsApiClient("key", http=_FakeHttp(routes))
    res = fetch_daily_offer(settings, log=lambda s: None, players_df=_players(), client=client, closing=True)
    assert res.ok and len(res.paths) == 1 and res.paths[0].name.startswith("closing_")
    assert not (tmp_path / "offer_latest.csv").exists()
    closing = pd.read_csv(res.paths[0])
    assert {"PLAYER", "LINE", "OVER_ODDS", "UNDER_ODDS", "BOOKMAKER", "N_BOOKS"} <= set(closing.columns)
    res2 = fetch_daily_offer(settings, log=lambda s: None, players_df=_players(), client=client)
    assert res2.ok and (tmp_path / "offer_latest.csv").exists()
    assert any(p.name.startswith("offer_books_") for p in res2.paths)
    assert list(pd.read_csv(tmp_path / "offer_latest.csv").columns) == ["PLAYER", "PLAYER_TEAM", "LINE", "OVER_ODDS",
                                                                         "UNDER_ODDS", "OPP_TEAM", "TOTAL_MATCH"]


def test_event_game_date_uses_us_eastern_day():
    # 02:30 UTC 2. novembra = 21:30 istočno 1. novembra → američki dan je 1. novembar
    assert event_game_date({"commence_time": "2026-11-02T02:30:00Z"}) == dt.date(2026, 11, 1)
    assert event_game_date({"commence_time": "2026-11-01T17:00:00Z"}) == dt.date(2026, 11, 1)
    assert event_game_date({"commence_time": "2026-11-02T23:00:00Z"}) == dt.date(2026, 11, 2)
    assert event_game_date({}) is None and event_game_date({"commence_time": "nije datum"}) is None
    # 02:00 po srednjoevropskom (01:00 UTC) je još prethodni američki dan
    assert current_game_date(dt.datetime(2026, 11, 2, 1, 0, tzinfo=dt.timezone.utc)) == dt.date(2026, 11, 1)
    assert current_game_date(dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.timezone.utc)) == dt.date(2026, 11, 2)
    events = [{"id": "a", "commence_time": "2026-11-01T23:00:00Z"}, {"id": "b", "commence_time": "2026-11-02T23:00:00Z"},
              {"id": "c"}]
    kept, skipped = select_events_for_game_date(events, dt.date(2026, 11, 1))
    assert [e["id"] for e in kept] == ["a", "c"] and [e["id"] for e in skipped] == ["b"]  # bez vremena: zadržan
    assert event_has_player_points(_event_payload([("pinnacle", [("Cade Cunningham", 27.5, 1.9, 1.85)])]))
    assert not event_has_player_points({"bookmakers": [{"key": "x", "markets": [{"key": "player_points", "outcomes": []}]}]})
    assert not event_has_player_points([]) and not event_has_player_points({})


def test_fetch_daily_offer_skips_other_days_and_totals_without_props(tmp_path):
    settings = Settings.load(data_dir=tmp_path, season="2025-26", env_file=tmp_path / "no.env")
    events = [{"id": "ev1", "home_team": "Detroit Pistons", "away_team": "Oklahoma City Thunder",
               "commence_time": "2026-11-01T23:00:00Z"},
              {"id": "ev2", "home_team": "Boston Celtics", "away_team": "Miami Heat",
               "commence_time": "2026-11-02T23:30:00Z"},          # sutra → ne povlači se
              {"id": "ev3", "home_team": "Los Angeles Lakers", "away_team": "Toronto Raptors",
               "commence_time": "2026-11-02T03:00:00Z"}]         # 22:00 istočno 1.11. → danas, ali bez props linija
    routes = {"/events": events,
              "/events/ev1/odds": _event_payload([("pinnacle", [("Cade Cunningham", 27.5, 1.9, 1.85)])]),
              "/events/ev2/odds": _event_payload([("pinnacle", [("Shai Gilgeous-Alexander", 30.5, 1.9, 1.9)])]),
              "/events/ev3/odds": {"bookmakers": []}}
    http = _FakeHttp(routes)
    lines = []
    res = fetch_daily_offer(settings, log=lines.append, players_df=_players(), client=OddsApiClient("key", http=http),
                            game_date=dt.date(2026, 11, 1))
    assert res.ok, res.message
    assert res.events == 2 and res.events_skipped == 1
    assert list(res.df["PLAYER"]) == ["Cade Cunningham"]
    urls = [u for u, _ in http.calls]
    assert "/events/ev2/odds" not in urls                                   # sutrašnji meč: nijedan poziv
    assert ("/events/ev3/odds", "player_points") in http.calls
    assert ("/events/ev3/odds", "totals") not in http.calls                  # bez props linija: total se ne traži
    assert ("/events/ev1/odds", "totals") in http.calls
    assert any("preskočeno radi štednje" in l for l in lines)
    # bez filtera: i sutrašnji meč ulazi
    http2 = _FakeHttp(routes)
    res2 = fetch_daily_offer(settings, log=lambda m: None, players_df=_players(), client=OddsApiClient("key", http=http2),
                             only_today=False)
    assert res2.events == 3 and res2.events_skipped == 0 and len(res2.df) == 2
    # danas nema mečeva → jasna poruka, bez poziva za kvote
    http3 = _FakeHttp(routes)
    res3 = fetch_daily_offer(settings, log=lambda m: None, players_df=_players(), client=OddsApiClient("key", http=http3),
                             game_date=dt.date(2026, 11, 5))
    assert not res3.ok and "nema mečeva" in res3.message and res3.events_skipped == 3
    assert [u for u, _ in http3.calls] == ["/events"]
