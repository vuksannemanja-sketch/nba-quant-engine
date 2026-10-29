"""Mape NBA timova (ID ↔ kratica ↔ puno ime) i normalizacija kratica."""
from __future__ import annotations

from typing import Any, Dict

import numpy as np

TEAM_ID_TO_ABBR: Dict[int, str] = {
    1610612737: "ATL", 1610612738: "BOS", 1610612751: "BKN", 1610612766: "CHA",
    1610612741: "CHI", 1610612739: "CLE", 1610612742: "DAL", 1610612743: "DEN",
    1610612765: "DET", 1610612744: "GSW", 1610612745: "HOU", 1610612754: "IND",
    1610612746: "LAC", 1610612747: "LAL", 1610612763: "MEM", 1610612748: "MIA",
    1610612749: "MIL", 1610612750: "MIN", 1610612740: "NOP", 1610612752: "NYK",
    1610612753: "ORL", 1610612755: "PHI", 1610612756: "PHX", 1610612757: "POR",
    1610612758: "SAC", 1610612759: "SAS", 1610612760: "OKC", 1610612761: "TOR",
    1610612762: "UTA", 1610612764: "WAS",
}
ABBR_TO_TEAM_ID: Dict[str, int] = {v: k for k, v in TEAM_ID_TO_ABBR.items()}
VALID_ABBRS = frozenset(ABBR_TO_TEAM_ID)

# Puna imena (mala slova) → kratica. Sadrži i varijante koje vraćaju razni API-ji.
TEAM_NAME_TO_ABBR: Dict[str, str] = {
    "atlanta hawks": "ATL",        "boston celtics": "BOS",
    "brooklyn nets": "BKN",        "charlotte hornets": "CHA",
    "chicago bulls": "CHI",        "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL",     "denver nuggets": "DEN",
    "detroit pistons": "DET",      "golden state warriors": "GSW",
    "houston rockets": "HOU",      "indiana pacers": "IND",
    "los angeles clippers": "LAC", "la clippers": "LAC",
    "los angeles lakers": "LAL",   "memphis grizzlies": "MEM",
    "miami heat": "MIA",           "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN", "new orleans pelicans": "NOP",
    "new york knicks": "NYK",      "orlando magic": "ORL",
    "philadelphia 76ers": "PHI",   "philadelphia seventy sixers": "PHI",
    "phoenix suns": "PHX",         "portland trail blazers": "POR",
    "sacramento kings": "SAC",     "san antonio spurs": "SAS",
    "oklahoma city thunder": "OKC", "toronto raptors": "TOR",
    "utah jazz": "UTA",            "washington wizards": "WAS",
}

# ESPN interni ID timova (za ESPN injuries endpoint po timu).
ESPN_TEAM_IDS: Dict[str, str] = {
    "ATL": "1",  "BOS": "2",  "BKN": "17", "CHA": "30",
    "CHI": "4",  "CLE": "5",  "DAL": "6",  "DEN": "7",
    "DET": "8",  "GSW": "9",  "HOU": "10", "IND": "11",
    "LAC": "12", "LAL": "13", "MEM": "29", "MIA": "14",
    "MIL": "15", "MIN": "16", "NOP": "3",  "NYK": "18",
    "ORL": "19", "PHI": "20", "PHX": "21", "POR": "22",
    "SAC": "23", "SAS": "24", "OKC": "25", "TOR": "28",
    "UTA": "26", "WAS": "27",
}


def normalize_team_abbr(val: Any) -> Any:
    """Vrati kraticu tima (npr. 'BOS') iz kratice, numeričkog ID-a ili punog imena; inače NaN."""
    try:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return np.nan
    except (TypeError, ValueError):
        return np.nan
    s = str(val).strip()
    if not s:
        return np.nan
    s_up = s.upper()
    if s_up in ABBR_TO_TEAM_ID:
        return s_up
    try:
        team_num = int(float(s))
        if team_num in TEAM_ID_TO_ABBR:
            return TEAM_ID_TO_ABBR[team_num]
    except (ValueError, OverflowError):
        pass
    return TEAM_NAME_TO_ABBR.get(s.lower(), np.nan)


def team_name_to_abbr(name: Any) -> str:
    """Puno ime tima → kratica; za nepoznato ime vrati prva 3 slova velikim (kao stari fetch)."""
    if not name:
        return ""
    s = str(name).strip()
    return TEAM_NAME_TO_ABBR.get(s.lower(), s[:3].upper())
