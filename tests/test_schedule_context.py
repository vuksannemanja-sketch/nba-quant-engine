"""ESPN raspored → domaćin/gost, B2B, dani odmora, današnji parovi (bez mreže)."""
import datetime as dt

from nba_engine.schedule import (DEFAULT_DAYS_BACK, ScheduleContext, build_schedule_context,
                                 fetch_schedule_context, statuses_from_events)


def _ev(home, away, state="pre", detail="", date="2026-10-30T23:00Z"):
    return {"date": date, "status": {"type": {"state": state, "shortDetail": detail}},
            "competitions": [{"competitors": [{"homeAway": "home", "team": {"abbreviation": home}},
                                               {"homeAway": "away", "team": {"abbreviation": away}}]}]}


TODAY = dt.date(2026, 10, 30)


def test_context_home_away_b2b_rest_and_today_pairs():
    events = {
        "20261030": [_ev("LAL", "OKC"), _ev("BOS", "MIA", state="in", detail="Q2 5:00")],
        "20261029": [_ev("OKC", "DEN", state="post", detail="Final")],       # OKC igrao juče → B2B
        "20261027": [_ev("LAL", "PHX", state="post", detail="Final")],       # LAL prije 3 dana → 2 dana odmora
        "20261028": [_ev("BOS", "NYK", state="post", detail="Postponed")],   # odgođeno: ne računa se
        "20261031": [_ev("DEN", "UTA")],
    }
    ctx = build_schedule_context(events, TODAY)
    assert ctx.fetched
    assert set(ctx.games_today) == {("LAL", "OKC"), ("BOS", "MIA")}
    assert ctx.home_teams == {"LAL", "BOS"} and ctx.away_teams == {"OKC", "MIA"}
    assert ctx.opponent_today["OKC"] == "LAL"
    assert ctx.is_b2b("OKC") and ctx.rest_days("OKC") == 0
    assert not ctx.is_b2b("LAL") and ctx.rest_days("LAL") == 2
    assert ctx.rest_days("BOS") == DEFAULT_DAYS_BACK          # igra danas, u prozoru nije odigrao ništa
    assert ctx.rest_days("DEN") == 0 and ctx.rest_days("UTA") is None
    assert ctx.b2b_teams() == {"OKC"}
    assert ctx.pair_is_today("OKC", "LAL") and ctx.pair_is_today("lal", "okc")
    assert not ctx.pair_is_today("LAL", "DEN") and not ctx.pair_is_today("LAL", "")
    # statusi za preskakanje mečeva: danas + sutra, isti oblik kao ranije
    assert ctx.statuses["BOS"]["state"] == "in" and ctx.statuses["MIA"]["opponent"] == "BOS"
    assert ctx.statuses["DEN"]["date"] == "20261031" and "PHX" not in ctx.statuses
    assert "2 mečeva danas" in ctx.summary() and "OKC" in ctx.summary()


def test_context_without_today_data_is_unknown():
    ctx = build_schedule_context({"20261030": None, "20261029": [_ev("OKC", "DEN", "post", "Final")]}, TODAY)
    assert not ctx.fetched and ctx.games_today == [] and ctx.teams_today == set()
    assert ctx.rest_days("OKC") == 0            # zna se da je igrao juče
    assert ctx.rest_days("LAL") is None
    assert ctx.summary().startswith("ESPN raspored nije dostupan")


def test_event_without_home_away_flag_uses_order():
    ev = {"date": "x", "status": {"type": {"state": "pre"}},
          "competitions": [{"competitors": [{"team": {"abbreviation": "NYK"}}, {"team": {"abbreviation": "PHI"}}]}]}
    ctx = build_schedule_context({"20261030": [ev]}, TODAY)
    assert ctx.games_today == [("NYK", "PHI")]
    assert statuses_from_events({"20261030": [ev]})["PHI"]["opponent"] == "NYK"


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _FakeHTTP:
    def __init__(self, by_date, fail=()):
        self.by_date, self.fail, self.calls = by_date, set(fail), []

    def get(self, url, timeout=10):
        day = url.split("dates=")[1][:8]
        self.calls.append(day)
        if day in self.fail:
            raise ConnectionError("offline")
        return _Resp({"events": self.by_date.get(day, [])})


def test_fetch_schedule_context_window_and_failures():
    http = _FakeHTTP({"20261030": [_ev("LAL", "OKC")], "20261029": [_ev("OKC", "DEN", "post", "Final")]},
                     fail={"20261026"})
    ctx = fetch_schedule_context(today=TODAY, session=http)
    assert len(http.calls) == DEFAULT_DAYS_BACK + 2 and http.calls[0] == "20261024" and http.calls[-1] == "20261031"
    assert ctx.fetched and ctx.is_b2b("OKC") and ctx.rest_days("LAL") == DEFAULT_DAYS_BACK
    # kad ESPN ne radi za današnji dan → nepoznato
    ctx2 = fetch_schedule_context(today=TODAY, session=_FakeHTTP({}, fail={"20261030"}))
    assert not ctx2.fetched and isinstance(ctx2, ScheduleContext)


def test_espn_abbreviations_are_normalized_to_app_codes():
    """ESPN piše SA/NO/UTAH/GS/NY/WSH; aplikacija koristi SAS/NOP/UTA/GSW/NYK/WAS."""
    events = {"20261030": [_ev("SA", "UTAH"), _ev("NO", "GS"), _ev("NY", "WSH")],
              "20261029": [_ev("SA", "LAL", state="post", detail="Final")]}
    ctx = build_schedule_context(events, TODAY)
    assert set(ctx.games_today) == {("SAS", "UTA"), ("NOP", "GSW"), ("NYK", "WAS")}
    assert ctx.pair_is_today("UTA", "SAS") and ctx.is_b2b("SAS") and ctx.rest_days("UTA") == DEFAULT_DAYS_BACK
    assert "SA" not in ctx.teams_today and "UTAH" not in ctx.teams_today
    st = statuses_from_events({"20261030": events["20261030"]})
    assert {"SAS", "UTA", "NOP", "GSW", "NYK", "WAS"} <= set(st) and st["SAS"]["opponent"] == "UTA"
