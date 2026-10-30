"""Raspored i stanje mečeva sa javnog ESPN API-ja.

- ``fetch_game_statuses``: stanje mečeva danas i sutra (pre / in / post), za preskakanje mečeva koji su počeli.
- ``fetch_schedule_context``: uz to i ko je domaćin, ko je igrao juče (back-to-back), koliko dana odmora ima
  svaki tim i koji su parovi današnji mečevi (provjera da li je ponuda uopšte za danas).

Sve što ESPN ne zna ostaje ``None`` i model koristi stare podrazumijevane vrijednosti; ručni unos u aplikaciji
uvijek ima prednost.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import requests

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date}"
STATE_ICON = {"pre": "🕐", "in": "🔴 LIVE", "post": "✅ Final"}
DEFAULT_DAYS_BACK = 6  # faktor odmora se ne mijenja poslije 5 dana, pa je 6 dana unazad dovoljno
_NOT_PLAYED = ("postponed", "canceled", "cancelled", "suspended")


def _fetch_events(date_str: str, timeout: int, http) -> Optional[list]:
    """Lista ESPN događaja za dan (YYYYMMDD); ``None`` ako mreža ili API ne rade."""
    try:
        resp = http.get(ESPN_SCOREBOARD_URL.format(date=date_str), timeout=timeout)
        if resp.status_code != 200:
            return None
        return list(resp.json().get("events", []))
    except Exception:  # noqa: BLE001
        return None


def _event_teams(event: dict) -> Tuple[List[str], Optional[str], Optional[str]]:
    """(kratice, domaćin, gost) iz jednog ESPN događaja; bez ``homeAway`` polja prvi tim je domaćin."""
    comps = event.get("competitions", [{}])[0].get("competitors", [])
    abbrs: List[str] = []
    home = away = None
    for c in comps:
        abbr = str(c.get("team", {}).get("abbreviation", "")).upper()
        if not abbr:
            continue
        abbrs.append(abbr)
        if c.get("homeAway") == "home":
            home = abbr
        elif c.get("homeAway") == "away":
            away = abbr
    if len(abbrs) == 2 and (home is None or away is None):
        home, away = abbrs[0], abbrs[1]
    return abbrs, home, away


def statuses_from_events(events_by_date: Dict[str, Optional[list]]) -> Dict[str, dict]:
    """{kratica: {state, detail, start_time, opponent, date}} — oblik koji koristi preskakanje mečeva."""
    games: Dict[str, dict] = {}
    for date_str, events in events_by_date.items():
        for event in events or []:
            st_type = event.get("status", {}).get("type", {})
            abbrs, _, _ = _event_teams(event)
            for i, abbr in enumerate(abbrs):
                opp = abbrs[1 - i] if len(abbrs) == 2 else ""
                games[abbr] = {"state": st_type.get("state", "pre"), "detail": st_type.get("shortDetail", ""),
                               "start_time": event.get("date", ""), "opponent": opp, "date": date_str}
    return games


def fetch_game_statuses(today: Optional[_dt.date] = None, timeout: int = 10, session=None) -> Dict[str, dict]:
    """Vrati {kratica_tima: {state, detail, start_time, opponent, date}} za danas i sutra.

    ``state``: 'pre' (nije počeo), 'in' (u toku), 'post' (završen). Greške mreže vraćaju prazan dict.
    """
    today = today or _dt.date.today()
    http = session or requests
    events_by_date = {}
    for d in (today, today + _dt.timedelta(days=1)):
        ds = d.strftime("%Y%m%d")
        events_by_date[ds] = _fetch_events(ds, timeout, http) or []
    return statuses_from_events(events_by_date)


def games_for_date(statuses: Dict[str, dict], date_str: str) -> Dict[str, dict]:
    """Mečevi za dati datum (YYYYMMDD), svaki par timova samo jednom."""
    return {a: g for a, g in statuses.items() if g.get("date") == date_str and a < g.get("opponent", "")}


@dataclass
class ScheduleContext:
    """Šta ESPN raspored zna o današnjem danu. Sve je automatski; ručni unos u aplikaciji ima prednost."""
    today: _dt.date
    fetched: bool = False                                                # ESPN je odgovorio za današnji dan
    games_today: List[Tuple[str, str]] = field(default_factory=list)     # (domaćin, gost)
    home_teams: Set[str] = field(default_factory=set)
    away_teams: Set[str] = field(default_factory=set)
    opponent_today: Dict[str, str] = field(default_factory=dict)
    last_game_date: Dict[str, _dt.date] = field(default_factory=dict)   # zadnja odigrana utakmica prije danas
    days_back: int = DEFAULT_DAYS_BACK
    statuses: Dict[str, dict] = field(default_factory=dict)              # danas + sutra, za preskakanje mečeva

    @property
    def teams_today(self) -> Set[str]:
        return self.home_teams | self.away_teams

    def rest_days(self, team: str) -> Optional[int]:
        """Dani odmora prije današnjeg meča (0 = igrao juče). ``None`` kad se ne zna."""
        key = str(team or "").upper()
        last = self.last_game_date.get(key)
        if last is None:
            return self.days_back if key in self.teams_today else None
        return max((self.today - last).days - 1, 0)

    def is_b2b(self, team: str) -> bool:
        return self.rest_days(team) == 0

    def b2b_teams(self) -> Set[str]:
        return {t for t in self.teams_today if self.is_b2b(t)}

    def pair_is_today(self, team: str, opp: str) -> bool:
        t, o = str(team or "").upper(), str(opp or "").upper()
        return bool(t and o) and ((t, o) in self.games_today or (o, t) in self.games_today)

    def summary(self) -> str:
        if not self.fetched:
            return "ESPN raspored nije dostupan."
        b2b = ", ".join(sorted(self.b2b_teams())) or "—"
        return f"{len(self.games_today)} mečeva danas | gosti: {', '.join(sorted(self.away_teams)) or '—'} | B2B: {b2b}"


def build_schedule_context(events_by_date: Dict[str, Optional[list]], today: _dt.date,
                           days_back: int = DEFAULT_DAYS_BACK) -> ScheduleContext:
    """Čista funkcija: iz ESPN događaja po danu (YYYYMMDD → lista, None = nije dohvaćeno) napravi kontekst."""
    today_str = today.strftime("%Y%m%d")
    tomorrow_str = (today + _dt.timedelta(days=1)).strftime("%Y%m%d")
    ctx = ScheduleContext(today=today, fetched=events_by_date.get(today_str) is not None, days_back=days_back)

    for event in events_by_date.get(today_str) or []:
        _, home, away = _event_teams(event)
        if home and away:
            ctx.games_today.append((home, away))
            ctx.home_teams.add(home)
            ctx.away_teams.add(away)
            ctx.opponent_today[home] = away
            ctx.opponent_today[away] = home

    for date_str, events in events_by_date.items():
        if date_str >= today_str or not events:
            continue
        game_date = _dt.datetime.strptime(date_str, "%Y%m%d").date()
        for event in events:
            detail = str(event.get("status", {}).get("type", {}).get("shortDetail", "")).lower()
            if any(w in detail for w in _NOT_PLAYED):
                continue
            abbrs, _, _ = _event_teams(event)
            for abbr in abbrs:
                prev = ctx.last_game_date.get(abbr)
                if prev is None or game_date > prev:
                    ctx.last_game_date[abbr] = game_date

    ctx.statuses = statuses_from_events({d: events_by_date.get(d) for d in (today_str, tomorrow_str)})
    return ctx


def fetch_schedule_context(today: Optional[_dt.date] = None, days_back: int = DEFAULT_DAYS_BACK,
                           timeout: int = 10, session=None) -> ScheduleContext:
    """Dohvati ESPN raspored za (danas − days_back) … sutra i napravi :class:`ScheduleContext`."""
    today = today or _dt.date.today()
    http = session or requests
    events_by_date: Dict[str, Optional[list]] = {}
    for offset in range(-days_back, 2):
        ds = (today + _dt.timedelta(days=offset)).strftime("%Y%m%d")
        events_by_date[ds] = _fetch_events(ds, timeout, http)
    return build_schedule_context(events_by_date, today, days_back=days_back)
