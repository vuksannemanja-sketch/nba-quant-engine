"""Raspored i stanje mečeva (danas + sutra) sa javnog ESPN API-ja."""
from __future__ import annotations

import datetime as _dt
from typing import Dict, Optional

import requests

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date}"
STATE_ICON = {"pre": "🕐", "in": "🔴 LIVE", "post": "✅ Final"}


def fetch_game_statuses(today: Optional[_dt.date] = None, timeout: int = 10, session=None) -> Dict[str, dict]:
    """Vrati {kratica_tima: {state, detail, start_time, opponent, date}} za danas i sutra.

    ``state``: 'pre' (nije počeo), 'in' (u toku), 'post' (završen). Greške mreže vraćaju prazan dict.
    """
    today = today or _dt.date.today()
    tomorrow = today + _dt.timedelta(days=1)
    dates = [today.strftime("%Y%m%d"), tomorrow.strftime("%Y%m%d")]
    http = session or requests
    games: Dict[str, dict] = {}
    for date_str in dates:
        try:
            resp = http.get(ESPN_SCOREBOARD_URL.format(date=date_str), timeout=timeout)
            if resp.status_code != 200:
                continue
            for event in resp.json().get("events", []):
                st_type = event.get("status", {}).get("type", {})
                state = st_type.get("state", "pre")
                detail = st_type.get("shortDetail", "")
                start = event.get("date", "")
                comps = event.get("competitions", [{}])[0].get("competitors", [])
                abbrs = [c.get("team", {}).get("abbreviation", "").upper()
                         for c in comps if c.get("team", {}).get("abbreviation")]
                for i, abbr in enumerate(abbrs):
                    opp = abbrs[1 - i] if len(abbrs) == 2 else ""
                    games[abbr] = {"state": state, "detail": detail,
                                   "start_time": start, "opponent": opp, "date": date_str}
        except Exception:
            pass
    return games


def games_for_date(statuses: Dict[str, dict], date_str: str) -> Dict[str, dict]:
    """Mečevi za dati datum (YYYYMMDD), svaki par timova samo jednom."""
    return {a: g for a, g in statuses.items() if g.get("date") == date_str and a < g.get("opponent", "")}
