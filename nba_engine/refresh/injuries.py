"""Izvještaj o ozljedama (ESPN) → ``injuries_*.csv`` sa kolonama PLAYER, TEAM_ABBR, STATUS, DESCRIPTION.

Prenesena logika ``refresh_injuries.py`` (oporavljena verzija). Ispravka u odnosu na original:
ESPN „bulk“ odgovor često nema kraticu tima, pa se ona izvodi iz punog imena tima, a ako i dalje
nedostaje, koristi se endpoint po timu (u originalu je zato kolona tima ostajala prazna).
"""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Dict, List, Optional

import pandas as pd
import requests

from ..config import Settings
from ..teams import ESPN_TEAM_IDS, TEAM_NAME_TO_ABBR, normalize_espn_abbr
from ._nba import Logger, log_to

REQUEST_TIMEOUT = 15
ESPN_BULK_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
ESPN_TEAM_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/injuries"
VALID_STATUSES = {"OUT", "QUESTIONABLE", "DOUBTFUL", "PROBABLE", "INACTIVE"}
OUTPUT_COLS = ["PLAYER", "TEAM_ABBR", "STATUS", "DESCRIPTION"]

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}


def _get(url: str, log: Logger, http=requests) -> Optional[dict]:
    for attempt in range(3):
        try:
            resp = http.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            code = getattr(e.response, "status_code", None)
            log(f"  HTTP {code} za {url}")
            if code in (429, 503):
                time.sleep(5 * (attempt + 1))
            else:
                break
        except requests.exceptions.RequestException as e:
            log(f"  Greška zahtjeva (pokušaj {attempt + 1}/3): {e}")
            time.sleep(2)
    return None


def normalize_status(raw: str) -> str:
    """Standardizuj status na OUT / QUESTIONABLE / DOUBTFUL / PROBABLE / INACTIVE."""
    s = str(raw or "").strip().upper()
    if s in VALID_STATUSES:
        return s
    aliases = {
        "OUT FOR SEASON": "OUT", "GAME TIME DECISION": "QUESTIONABLE", "DAY TO DAY": "QUESTIONABLE",
        "DAY-TO-DAY": "QUESTIONABLE", "GTD": "QUESTIONABLE", "INACTIVE": "INACTIVE",
        "DND": "OUT", "DID NOT DRESS": "OUT", "NOT WITH TEAM": "OUT",
    }
    for key, val in aliases.items():
        if key in s:
            return val
    if "OUT" in s:
        return "OUT"
    if "DOUBTFUL" in s:
        return "DOUBTFUL"
    if "QUESTIONABLE" in s:
        return "QUESTIONABLE"
    if "PROBABLE" in s:
        return "PROBABLE"
    return "QUESTIONABLE"  # konzervativni default


def _team_abbr_from_entry(team_info: dict, entry: dict) -> str:
    abbr = normalize_espn_abbr(team_info.get("abbreviation"))
    if abbr:
        return abbr
    for key in ("displayName", "name", "shortDisplayName"):
        name = str(team_info.get(key) or entry.get(key) or "").strip().lower()
        if name and name in TEAM_NAME_TO_ABBR:
            return TEAM_NAME_TO_ABBR[name]
    return ""


def parse_bulk_payload(data) -> List[Dict]:
    """Parsiraj ESPN bulk odgovor u redove (bez mrežnih poziva — pogodno za testove)."""
    rows: List[Dict] = []
    teams_data = data if isinstance(data, list) else (data or {}).get("injuries", [])
    if isinstance(data, dict) and "injuries" not in data:
        teams_data = list(data.values()) if data else []
    for entry in teams_data:
        if not isinstance(entry, dict):
            continue
        team_abbr = _team_abbr_from_entry(entry.get("team", {}) or {}, entry)
        for inj in entry.get("injuries", []):
            athlete = inj.get("athlete", {}) or {}
            name = athlete.get("displayName") or athlete.get("fullName", "")
            status = normalize_status(inj.get("status", ""))
            desc = inj.get("shortComment") or inj.get("longComment") or (inj.get("type", {}) or {}).get("description", "")
            if name and status:
                rows.append({"PLAYER": name, "TEAM_ABBR": team_abbr, "STATUS": status,
                             "DESCRIPTION": desc, "SOURCE": "ESPN"})
    return rows


def fetch_espn_per_team(log: Logger, http=requests) -> List[Dict]:
    """ESPN endpoint po timu (30 poziva) — kratica tima je sigurno poznata."""
    rows: List[Dict] = []
    for abbr, team_id in ESPN_TEAM_IDS.items():
        data = _get(ESPN_TEAM_URL.format(team_id=team_id), log, http)
        if data is None:
            log(f"  ⚠️ {abbr}: nema odgovora")
            continue
        for inj in data.get("injuries", []):
            athlete = inj.get("athlete", {}) or {}
            name = athlete.get("displayName") or athlete.get("fullName", "")
            status = normalize_status(inj.get("status", ""))
            desc = inj.get("shortComment") or inj.get("longComment") or (inj.get("type", {}) or {}).get("description", "")
            if name and status:
                rows.append({"PLAYER": name, "TEAM_ABBR": abbr, "STATUS": status,
                             "DESCRIPTION": desc, "SOURCE": "ESPN"})
        time.sleep(0.15)
    log(f"  ESPN (po timu): {len(rows)} ozljeda")
    return rows


def fetch_espn(log: Logger, http=requests) -> List[Dict]:
    """ESPN bulk endpoint; ako nema tima za većinu igrača, prelazi na endpoint po timu."""
    log("📡 ESPN: povlačim injury report...")
    data = _get(ESPN_BULK_URL, log, http)
    rows = parse_bulk_payload(data) if data is not None else []
    if rows:
        missing = sum(1 for r in rows if not r["TEAM_ABBR"])
        log(f"  ESPN (bulk): {len(rows)} ozljeda, bez tima: {missing}")
        if missing <= len(rows) * 0.5:
            return rows
        log("  Previše redova bez tima — prelazim na endpoint po timu.")
    return fetch_espn_per_team(log, http)


def merge_injury_sources(*sources: List[Dict]) -> pd.DataFrame:
    """Spoji izvore; za istog igrača zadrži najstroži status (OUT > DOUBTFUL > QUESTIONABLE > PROBABLE)."""
    all_rows = [r for src in sources for r in (src or [])]
    if not all_rows:
        return pd.DataFrame(columns=OUTPUT_COLS)
    df = pd.DataFrame(all_rows)
    df["PLAYER"] = df["PLAYER"].astype(str).str.strip()
    df["TEAM_ABBR"] = df["TEAM_ABBR"].fillna("").astype(str).str.strip().str.upper()
    df["STATUS"] = df["STATUS"].astype(str).str.strip()
    df["DESCRIPTION"] = df["DESCRIPTION"].fillna("").astype(str)

    def _norm(s):
        s = str(s).lower().strip()
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
        s = re.sub(r"[^a-z0-9\s]", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    rank = {"OUT": 5, "INACTIVE": 5, "DOUBTFUL": 4, "QUESTIONABLE": 3, "PROBABLE": 2}
    df["_key"] = df["PLAYER"].map(_norm)
    df["_rank"] = df["STATUS"].map(lambda s: rank.get(s, 1))
    df = df.sort_values(["_key", "_rank"], ascending=[True, False]).drop_duplicates(subset=["_key"], keep="first")
    df = df.drop(columns=["_key", "_rank", "SOURCE"], errors="ignore")
    return df[OUTPUT_COLS].reset_index(drop=True)


def run(settings: Settings, log: Optional[Logger] = None, http=requests) -> str:
    log = log_to(log)
    rows = fetch_espn(log, http)
    out_path = settings.primary_csv_path("injuries")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise RuntimeError("ESPN nije vratio podatke o ozljedama.")
    df = merge_injury_sources(rows)
    df.to_csv(out_path, index=False)
    counts = df["STATUS"].value_counts().to_dict()
    with_team = int((df["TEAM_ABBR"] != "").sum())
    return f"Snimljeno {len(df)} ozljeda → {out_path.name} (sa timom: {with_team}; {counts})"
