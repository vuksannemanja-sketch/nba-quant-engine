#!/usr/bin/env python3
"""
refresh_injuries.py
-------------------
Fetchuje NBA injury report s ESPN API (primarni) i NBA Stats (fallback).
Sprema: data/injuries_2025-26.csv

Format outputa (kompatibilan s app.py load_injuries_csv):
    PLAYER, TEAM_ABBR, STATUS, DESCRIPTION

Pokretanje:
    python refresh_injuries.py
    python refresh_injuries.py --source espn
    python refresh_injuries.py --source nba
    python refresh_injuries.py --source both   # ESPN + NBA merge
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

# ── Konstante ────────────────────────────────────────────────
SEASON       = "2025-26"
SEASON_YEAR  = "2025"  # NBA Stats koristi samo godinu početka sezone

DATA_DIR_CANDIDATES = [
    os.path.join(os.getcwd(), "data"),
    "/mnt/data",
    os.getcwd(),
]
DATA_DIR = next((p for p in DATA_DIR_CANDIDATES if os.path.isdir(p)), os.getcwd())
OUT_PATH = os.path.join(DATA_DIR, f"injuries_{SEASON}.csv")

# Timeout za HTTP requeste (sekunde)
REQUEST_TIMEOUT = 15

# NBA team abbr ↔ ESPN team ID (potrebno za ESPN endpoint)
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

# NBA Stats Team ID → kratice
NBA_STATS_TEAM_IDS: Dict[int, str] = {
    1610612737: "ATL", 1610612738: "BOS", 1610612751: "BKN", 1610612766: "CHA",
    1610612741: "CHI", 1610612739: "CLE", 1610612742: "DAL", 1610612743: "DEN",
    1610612765: "DET", 1610612744: "GSW", 1610612745: "HOU", 1610612754: "IND",
    1610612746: "LAC", 1610612747: "LAL", 1610612763: "MEM", 1610612748: "MIA",
    1610612749: "MIL", 1610612750: "MIN", 1610612740: "NOP", 1610612752: "NYK",
    1610612753: "ORL", 1610612755: "PHI", 1610612756: "PHX", 1610612757: "POR",
    1610612758: "SAC", 1610612759: "SAS", 1610612760: "OKC", 1610612761: "TOR",
    1610612762: "UTA", 1610612764: "WAS",
}

VALID_STATUSES = {"OUT", "QUESTIONABLE", "DOUBTFUL", "PROBABLE", "INACTIVE"}

# ── HTTP helper ───────────────────────────────────────────────

def _get(url: str, headers: Optional[Dict] = None, params: Optional[Dict] = None) -> Optional[dict]:
    """GET request s retry logikom (3 pokušaja)."""
    _headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    if headers:
        _headers.update(headers)

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=_headers, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            print(f"  HTTP {e.response.status_code} za {url}")
            if e.response.status_code in (429, 503):
                wait = 5 * (attempt + 1)
                print(f"  Rate limit — čekam {wait}s...")
                time.sleep(wait)
            else:
                break
        except requests.exceptions.RequestException as e:
            print(f"  Request greška (pokušaj {attempt+1}/3): {e}")
            time.sleep(2)
    return None


def _normalize_status(raw: str) -> str:
    """Standardizuj status na jedan od VALID_STATUSES."""
    s = str(raw or "").strip().upper()
    if s in VALID_STATUSES:
        return s
    # Česti aliasi
    aliases = {
        "OUT FOR SEASON": "OUT",
        "GAME TIME DECISION": "QUESTIONABLE",
        "DAY TO DAY": "QUESTIONABLE",
        "DAY-TO-DAY": "QUESTIONABLE",
        "GTD": "QUESTIONABLE",
        "INACTIVE": "INACTIVE",
        "DND": "OUT",
        "DID NOT DRESS": "OUT",
        "NOT WITH TEAM": "OUT",
    }
    for key, val in aliases.items():
        if key in s:
            return val
    # Substring fallback
    if "OUT" in s:         return "OUT"
    if "DOUBTFUL" in s:    return "DOUBTFUL"
    if "QUESTIONABLE" in s: return "QUESTIONABLE"
    if "PROBABLE" in s:    return "PROBABLE"
    return "QUESTIONABLE"  # konzervativni default


# ── ESPN fetcher ──────────────────────────────────────────────

def fetch_espn_injuries() -> List[Dict]:
    """
    Fetchuje injury podatke s ESPN API.
    Endpoint: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{id}/injuries
    """
    print("📡 ESPN: fetchujem injury report...")
    rows: List[Dict] = []

    for abbr, team_id in ESPN_TEAM_IDS.items():
        url  = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/injuries"
        data = _get(url)
        if data is None:
            print(f"  ⚠️  {abbr}: nema odgovora")
            continue

        injuries = data.get("injuries", [])
        for inj in injuries:
            athlete = inj.get("athlete", {})
            name    = athlete.get("displayName") or athlete.get("fullName", "")
            status  = _normalize_status(inj.get("status", ""))
            desc    = inj.get("shortComment") or inj.get("longComment") or inj.get("type", {}).get("description", "")
            if name and status:
                rows.append({
                    "PLAYER":      name,
                    "TEAM_ABBR":   abbr,
                    "STATUS":      status,
                    "DESCRIPTION": desc,
                    "SOURCE":      "ESPN",
                })

        time.sleep(0.15)  # rate limit

    print(f"  ESPN: {len(rows)} ozljeda pronađeno")
    return rows


def fetch_espn_injuries_v2() -> List[Dict]:
    """
    Alternativni ESPN endpoint koji vraća sve timove odjednom.
    https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries
    """
    print("📡 ESPN v2 (bulk endpoint): fetchujem...")
    url  = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
    data = _get(url)
    if data is None:
        print("  ESPN v2: nema odgovora, fallback na per-team endpoint")
        return fetch_espn_injuries()

    rows: List[Dict] = []
    teams_data = data if isinstance(data, list) else data.get("injuries", [])

    # Struktura varira — pokušaj oba formata
    if isinstance(data, dict) and "injuries" not in data:
        # Može biti direktno lista timova
        teams_data = list(data.values()) if data else []

    for entry in teams_data:
        if not isinstance(entry, dict):
            continue
        team_abbr = ""
        team_info = entry.get("team", {})
        if team_info:
            abbr_raw  = team_info.get("abbreviation", "")
            team_abbr = abbr_raw.upper() if abbr_raw else ""

        for inj in entry.get("injuries", []):
            athlete = inj.get("athlete", {})
            name    = athlete.get("displayName") or athlete.get("fullName", "")
            status  = _normalize_status(inj.get("status", ""))
            desc    = inj.get("shortComment") or inj.get("type", {}).get("description", "")
            if name and status:
                rows.append({
                    "PLAYER":      name,
                    "TEAM_ABBR":   team_abbr,
                    "STATUS":      status,
                    "DESCRIPTION": desc,
                    "SOURCE":      "ESPN",
                })

    if rows:
        print(f"  ESPN v2: {len(rows)} ozljeda pronađeno")
        return rows

    # Fallback na per-team
    print("  ESPN v2: prazan odgovor, fallback na per-team endpoint")
    return fetch_espn_injuries()


# ── NBA Stats fetcher ─────────────────────────────────────────

def fetch_nba_stats_injuries() -> List[Dict]:
    """
    Fetchuje injury podatke s NBA Stats API.
    Endpoint: commonplayerinfo + leaguedashplayerstats za status
    Direktniji: injury report PDF/JSON s NBA.com
    """
    print("📡 NBA Stats: fetchujem injury report...")

    # NBA Stats nema direktan public injury JSON — koristimo
    # https://www.nba.com/injuries endpoint koji vraća JSON
    url = "https://www.nba.com/injuries"
    headers = {
        "Referer":    "https://www.nba.com/",
        "Origin":     "https://www.nba.com",
        "x-nba-stats-origin": "stats",
        "x-nba-stats-token":  "true",
    }

    # NBA.com injury page — parse inline JSON
    try:
        resp = requests.get(url, headers={
            **headers,
            "Accept": "text/html,application/xhtml+xml",
        }, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text

        # Traži __NEXT_DATA__ JSON koji sadrži injury info
        import re
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        if match:
            next_data = json.loads(match.group(1))
            return _parse_nba_next_data(next_data)
    except Exception as e:
        print(f"  NBA.com parse greška: {e}")

    # Fallback: NBA Stats API leaguedashplayerstats s injury filter
    return _fetch_nba_stats_api()


def _parse_nba_next_data(data: dict) -> List[Dict]:
    """Parsira __NEXT_DATA__ JSON s NBA.com/injuries stranice."""
    rows: List[Dict] = []
    try:
        # Navigiraj kroz nested strukturu
        props      = data.get("props", {})
        page_props = props.get("pageProps", {})
        injury_data = (
            page_props.get("injury", {})
            or page_props.get("injuries", {})
            or page_props.get("leagueInjuries", {})
        )

        # Struktura: {date, teams: [{teamName, teamAbbr, players: [{playerName, status, desc}]}]}
        for team_entry in injury_data.get("injuries", []):
            team_abbr = (
                team_entry.get("teamAbbr")
                or team_entry.get("teamTricode")
                or team_entry.get("teamAbbreviation", "")
            ).upper()

            for player in team_entry.get("players", []):
                name   = player.get("playerName") or player.get("name", "")
                status = _normalize_status(player.get("status", ""))
                desc   = player.get("reason") or player.get("description", "")
                if name:
                    rows.append({
                        "PLAYER":      name,
                        "TEAM_ABBR":   team_abbr,
                        "STATUS":      status,
                        "DESCRIPTION": desc,
                        "SOURCE":      "NBA",
                    })
    except Exception as e:
        print(f"  NBA next_data parse greška: {e}")

    print(f"  NBA.com: {len(rows)} ozljeda pronađeno")
    return rows


def _fetch_nba_stats_api() -> List[Dict]:
    """
    Fallback: NBA Stats API — dohvati listu igrača koji su inactive/injured
    koristeći leaguedashplayerstats endpoint s injury_filter.
    """
    print("  NBA Stats API fallback...")
    rows: List[Dict] = []

    url = "https://stats.nba.com/stats/leaguedashplayerstats"
    headers = {
        "Referer":            "https://www.nba.com/",
        "x-nba-stats-origin": "stats",
        "x-nba-stats-token":  "true",
    }
    params = {
        "LastNGames":       "0",
        "LeagueID":         "00",
        "MeasureType":      "Base",
        "Month":            "0",
        "OpponentTeamID":   "0",
        "PaceAdjust":       "N",
        "PerMode":          "PerGame",
        "Period":           "0",
        "PlusMinus":        "N",
        "Rank":             "N",
        "Season":           SEASON,
        "SeasonSegment":    "",
        "SeasonType":       "Regular Season",
        "TeamID":           "0",
        "TwoWay":           "0",
        "VsConference":     "",
        "VsDivision":       "",
    }

    data = _get(url, headers=headers, params=params)
    if data is None:
        print("  NBA Stats API: nema odgovora")
        return rows

    try:
        result_sets = data.get("resultSets", [])
        for rs in result_sets:
            if rs.get("name") == "LeagueDashPlayerStats":
                headers_list = rs["headers"]
                rows_data    = rs["rowSet"]
                # Nema direktnog injury statusa ovdje — preskačemo
                print(f"  NBA Stats API: {len(rows_data)} igrača u bazi (bez injury statusa)")
                break
    except Exception as e:
        print(f"  NBA Stats parse greška: {e}")

    return rows  # prazan — NBA Stats nema public injury endpoint


# ── Merge i dedup ─────────────────────────────────────────────

def merge_injury_sources(espn_rows: List[Dict], nba_rows: List[Dict]) -> pd.DataFrame:
    """
    Spoji ESPN i NBA podatke.
    Prioritet: OUT > DOUBTFUL > QUESTIONABLE > PROBABLE
    Ako isti igrač postoji u oba — uzmi stroži status.
    """
    all_rows = espn_rows + nba_rows
    if not all_rows:
        return pd.DataFrame(columns=["PLAYER", "TEAM_ABBR", "STATUS", "DESCRIPTION"])

    df = pd.DataFrame(all_rows)
    df["PLAYER"]      = df["PLAYER"].astype(str).str.strip()
    df["TEAM_ABBR"]   = df["TEAM_ABBR"].astype(str).str.strip().str.upper()
    df["STATUS"]      = df["STATUS"].astype(str).str.strip()
    df["DESCRIPTION"] = df["DESCRIPTION"].fillna("").astype(str)

    # Normalizuj naziv igrača za dedup ključ
    import unicodedata, re
    def _norm(s):
        s = str(s).lower().strip()
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
        s = re.sub(r"[^a-z0-9\s]", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    df["_key"] = df["PLAYER"].map(_norm)

    # Težina statusa za sorting (veći = ozbiljniji)
    status_rank = {"OUT": 5, "INACTIVE": 5, "DOUBTFUL": 4, "QUESTIONABLE": 3, "PROBABLE": 2}
    df["_rank"]  = df["STATUS"].map(lambda s: status_rank.get(s, 1))

    # Sortiraj: po igraču, po ranku (ozbiljniji status naprijed)
    df = df.sort_values(["_key", "_rank"], ascending=[True, False])

    # Drži samo najstrožiji status po igraču
    df = df.drop_duplicates(subset=["_key"], keep="first")
    df = df.drop(columns=["_key", "_rank", "SOURCE"], errors="ignore")

    return df.reset_index(drop=True)


# ── Main ──────────────────────────────────────────────────────

def main(source: str = "espn") -> None:
    print(f"\n{'='*55}")
    print(f"  NBA Injury Refresh — {datetime.date.today().isoformat()}")
    print(f"  Izvor: {source.upper()}")
    print(f"  Output: {OUT_PATH}")
    print(f"{'='*55}")

    espn_rows: List[Dict] = []
    nba_rows:  List[Dict] = []

    if source in ("espn", "both"):
        espn_rows = fetch_espn_injuries_v2()

    if source in ("nba", "both"):
        nba_rows = fetch_nba_stats_injuries()

    if not espn_rows and not nba_rows:
        print("\n❌ Nema podataka ni s jednog izvora.")
        sys.exit(1)

    df = merge_injury_sources(espn_rows, nba_rows)

    if df.empty:
        print("\n⚠️  Nema ozljeda pronađeno (možda je All-Star break ili slobodan dan).")
        # Snimi prazan fajl da app.py ne prikazuje stare podatke
        pd.DataFrame(columns=["PLAYER", "TEAM_ABBR", "STATUS", "DESCRIPTION"]).to_csv(OUT_PATH, index=False)
        print(f"  Snimljen prazan: {OUT_PATH}")
        return

    # Osiguraj ispravne kolone za app.py
    df = df[["PLAYER", "TEAM_ABBR", "STATUS", "DESCRIPTION"]]

    # Spremi
    os.makedirs(os.path.dirname(OUT_PATH) if os.path.dirname(OUT_PATH) else ".", exist_ok=True)
    df.to_csv(OUT_PATH, index=False)

    # Sažetak
    print(f"\n✅ Snimljeno: {OUT_PATH}")
    print(f"   Ukupno: {len(df)} igrača na injury reportu")
    print()
    for status in ("OUT", "DOUBTFUL", "QUESTIONABLE", "PROBABLE"):
        count = int((df["STATUS"] == status).sum())
        if count > 0:
            print(f"   {status:15s}: {count}")

    print("\n   Top OUT igrači:")
    out_df = df[df["STATUS"] == "OUT"][["PLAYER", "TEAM_ABBR", "DESCRIPTION"]].head(10)
    for _, row in out_df.iterrows():
        desc = f" — {row['DESCRIPTION'][:50]}" if row["DESCRIPTION"] else ""
        print(f"   • {row['PLAYER']} ({row['TEAM_ABBR']}){desc}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NBA Injury Report Refresh")
    parser.add_argument(
        "--source",
        choices=["espn", "nba", "both"],
        default="espn",
        help="Izvor podataka (default: espn)",
    )
    args = parser.parse_args()
    main(source=args.source)