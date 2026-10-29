"""Dnevna ponuda (player points props) sa The Odds API.

Logika je prenesena iz ``fetch_dnevna_ponuda_multi.py``; ključ se čita iz podešavanja (.env),
a kladionice se biraju po prioritetu iz podešavanja (Pinnacle prvi) umjesto po slučajnom redoslijedu odgovora.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import requests

from .config import Settings
from .teams import VALID_ABBRS, normalize_team_abbr, team_name_to_abbr
from .utils import normalize_name

OFFER_COLUMNS = ["PLAYER", "PLAYER_TEAM", "LINE", "OVER_ODDS", "UNDER_ODDS", "OPP_TEAM", "TOTAL_MATCH"]
SPORT_KEY = "basketball_nba"

Logger = Callable[[str], None]


class OddsApiError(RuntimeError):
    pass


@dataclass
class OddsApiClient:
    api_key: str
    base_url: str = "https://api.the-odds-api.com/v4"
    timeout: int = 30
    http: object = requests
    last_remaining: Optional[str] = None

    def _get(self, path: str, params: Dict[str, str]) -> object:
        if not self.api_key:
            raise OddsApiError("ODDS_API_KEY nije postavljen (upiši ga u .env fajl).")
        url = f"{self.base_url}{path}"
        resp = self.http.get(url, params={"apiKey": self.api_key, **params}, timeout=self.timeout)
        if resp.status_code == 401:
            raise OddsApiError("The Odds API: ključ nije važeći (401 Unauthorized).")
        if resp.status_code == 429:
            raise OddsApiError("The Odds API: potrošena kvota zahtjeva (429).")
        resp.raise_for_status()
        try:
            self.last_remaining = resp.headers.get("x-requests-remaining")
        except Exception:
            pass
        return resp.json()

    def fetch_events(self) -> List[dict]:
        data = self._get(f"/sports/{SPORT_KEY}/events", {})
        return data if isinstance(data, list) else []

    def fetch_game_totals(self, event_id: str) -> Optional[float]:
        """Linija ukupnih poena meča (prva 'Over' linija bilo koje kladionice)."""
        try:
            data = self._get(f"/sports/{SPORT_KEY}/events/{event_id}/odds",
                             {"regions": "us", "markets": "totals", "oddsFormat": "decimal"})
        except OddsApiError:
            raise
        except Exception:
            return None
        for bookie in data.get("bookmakers", []):
            for market in bookie.get("markets", []):
                if market.get("key") == "totals":
                    for outcome in market.get("outcomes", []):
                        if outcome.get("name") == "Over":
                            return outcome.get("point")
        return None

    def fetch_event_player_points(self, event_id: str) -> dict:
        return self._get(f"/sports/{SPORT_KEY}/events/{event_id}/odds",
                         {"regions": "us,eu,uk", "markets": "player_points", "oddsFormat": "decimal"})


# ---------------------------------------------------------------------------
# Tim igrača iz baze igrača
# ---------------------------------------------------------------------------

def load_players_for_lookup(settings: Settings) -> Optional[pd.DataFrame]:
    """Minimalna tabela igrača (NAME_KEY, TEAM_ABBR) za određivanje tima i protivnika."""
    path = settings.csv_path("players_main") or settings.csv_path("players_base")
    if path is None:
        return None
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    df = df.loc[:, ~df.columns.duplicated()]
    rename = {}
    for col in df.columns:
        cu = col.upper().strip()
        if cu in ("PLAYER_NAME", "PLAYER", "NAME"):
            rename[col] = "PLAYER_NAME"
        elif cu in ("TEAM_ABBR", "TEAM_ABBREVIATION"):
            rename[col] = "TEAM_ABBR"
        elif cu == "TEAM_ID":
            rename[col] = "TEAM_ID"
    df = df.rename(columns=rename)
    df = df.loc[:, ~df.columns.duplicated()]
    if "PLAYER_NAME" not in df.columns:
        return None
    if "TEAM_ABBR" not in df.columns and "TEAM_ID" in df.columns:
        df["TEAM_ABBR"] = df["TEAM_ID"]
    if "TEAM_ABBR" not in df.columns:
        return None
    df["TEAM_ABBR"] = df["TEAM_ABBR"].map(normalize_team_abbr)
    df["NAME_KEY"] = df["PLAYER_NAME"].astype(str).map(normalize_name)
    return df[["PLAYER_NAME", "NAME_KEY", "TEAM_ABBR"]]


def _clean_team(val) -> Optional[str]:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    s = str(val).strip().upper()
    return s if s in VALID_ABBRS else None


def find_player_team(player_name: str, players_df: Optional[pd.DataFrame]) -> Optional[str]:
    """Tim igrača: tačno ime → prezime + početno slovo → samo duže prezime (ako je jedinstveno)."""
    if players_df is None or "NAME_KEY" not in players_df.columns or "TEAM_ABBR" not in players_df.columns:
        return None
    name_key = normalize_name(player_name)
    match = players_df[players_df["NAME_KEY"] == name_key]
    if not match.empty:
        team = _clean_team(match["TEAM_ABBR"].iloc[0])
        if team:
            return team
    tokens = name_key.split()
    if len(tokens) >= 2:
        last_name = re.escape(tokens[-1])
        first_init = tokens[0][:1]
        mask = players_df["NAME_KEY"].str.contains(last_name, na=False, regex=True)
        if first_init:
            mask &= players_df["NAME_KEY"].str.startswith(first_init, na=False)
        matches = players_df[mask]
        if len(matches) == 1:
            team = _clean_team(matches["TEAM_ABBR"].iloc[0])
            if team:
                return team
    if tokens and len(tokens[-1]) >= 5:
        mask = players_df["NAME_KEY"].str.contains(re.escape(tokens[-1]), na=False, regex=True)
        matches = players_df[mask]
        if len(matches) == 1:
            team = _clean_team(matches["TEAM_ABBR"].iloc[0])
            if team:
                return team
    return None


# ---------------------------------------------------------------------------
# Izvlačenje props-a iz odgovora API-ja
# ---------------------------------------------------------------------------

def order_bookmakers(bookmakers: List[dict], priority: Sequence[str]) -> List[dict]:
    """Kladionice po prioritetu; nepoznate idu na kraj u originalnom redoslijedu."""
    prio = {b.lower(): i for i, b in enumerate(priority)}
    return sorted(bookmakers, key=lambda b: (prio.get(str(b.get("key", "")).lower(), len(prio)), 0))


def extract_player_props(data: dict, home_abbr: str, away_abbr: str, total_match: Optional[float],
                         players_df: Optional[pd.DataFrame], priority: Sequence[str] = (),
                         log: Optional[Logger] = None) -> List[dict]:
    """Iz odgovora za jedan meč napravi redove ponude. Uzima se prva kladionica (po prioritetu)
    koja ima player_points tržište; po igraču se uzima prvi par Over/Under."""
    bookmakers = data.get("bookmakers", []) if isinstance(data, dict) else []
    if not bookmakers:
        return []
    props: List[dict] = []
    seen = set()
    for bookie in order_bookmakers(bookmakers, priority):
        for market in bookie.get("markets", []):
            if market.get("key") != "player_points":
                continue
            players: Dict[str, Dict[str, dict]] = {}
            for o in market.get("outcomes", []):
                player = o.get("description", "")
                if player:
                    players.setdefault(player, {})[o.get("name")] = o
            for player, sides in players.items():
                if player in seen:
                    continue
                over, under = sides.get("Over"), sides.get("Under")
                if not over or not under:
                    continue
                seen.add(player)
                player_team = find_player_team(player, players_df)
                opp_team = None
                if player_team:
                    if player_team == (home_abbr or "").upper():
                        opp_team = away_abbr
                    elif player_team == (away_abbr or "").upper():
                        opp_team = home_abbr
                    elif log:
                        log(f"    ⚠️ {player}: tim {player_team} ne odgovara meču {away_abbr}@{home_abbr}")
                elif log:
                    log(f"    ⚠️ {player}: nije pronađen u bazi igrača")
                props.append({
                    "PLAYER": player,
                    "PLAYER_TEAM": player_team or "",
                    "LINE": over.get("point"),
                    "OVER_ODDS": over.get("price"),
                    "UNDER_ODDS": under.get("price"),
                    "OPP_TEAM": opp_team or "",
                    "TOTAL_MATCH": total_match if total_match else "",
                    "BOOKMAKER": bookie.get("key", ""),
                })
        if props:
            break
    return props


def props_to_frame(all_props: List[dict]) -> pd.DataFrame:
    df = pd.DataFrame(all_props)
    if df.empty:
        return df
    df = df.sort_values("LINE", ascending=False)
    return df[[c for c in OFFER_COLUMNS if c in df.columns]]


# ---------------------------------------------------------------------------
# Glavna funkcija
# ---------------------------------------------------------------------------

@dataclass
class FetchResult:
    ok: bool
    df: pd.DataFrame
    message: str
    paths: List[Path] = field(default_factory=list)
    events: int = 0


def fetch_daily_offer(settings: Settings, log: Logger = print, players_df: Optional[pd.DataFrame] = None,
                      client: Optional[OddsApiClient] = None, today: Optional[_dt.date] = None) -> FetchResult:
    """Povuci današnju ponudu i snimi je u ``offer_latest.csv`` (+ kopije ``dnevna_ponuda.csv`` i datirana)."""
    client = client or OddsApiClient(settings.odds_api_key, settings.odds_api_base)
    try:
        if players_df is None:
            players_df = load_players_for_lookup(settings)
        if players_df is None:
            log("⚠️ Baza igrača nije pronađena — PLAYER_TEAM/OPP_TEAM neće biti popunjeni.")
        else:
            log(f"📂 Baza igrača: {len(players_df)} igrača za mapiranje timova.")

        events = client.fetch_events()
        if not events:
            return FetchResult(False, pd.DataFrame(), "Nema utakmica u ponudi.")
        log(f"📅 Utakmica u ponudi: {len(events)}")

        all_props: List[dict] = []
        for event in events:
            event_id = event.get("id")
            home_abbr = team_name_to_abbr(event.get("home_team", ""))
            away_abbr = team_name_to_abbr(event.get("away_team", ""))
            total_match = client.fetch_game_totals(event_id)
            data = client.fetch_event_player_points(event_id)
            props = extract_player_props(data, home_abbr, away_abbr, total_match, players_df,
                                         settings.bookmaker_priority, log=log)
            log(f"🏀 {away_abbr} @ {home_abbr}: total={total_match}, igrača={len(props)}")
            all_props.extend(props)

        if not all_props:
            return FetchResult(False, pd.DataFrame(), "Nema player props ponude.", events=len(events))

        df = props_to_frame(all_props)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        today_iso = (today or _dt.date.today()).isoformat()
        paths = [settings.offer_latest_path(),
                 settings.data_dir / "dnevna_ponuda.csv",
                 settings.data_dir / f"offer_{today_iso}.csv"]
        for p in paths:
            df.to_csv(p, index=False)
        opp_filled = int((df["OPP_TEAM"].astype(str) != "").sum())
        msg = f"OK: {len(df)} props, OPP_TEAM popunjen {opp_filled}/{len(df)}"
        if client.last_remaining is not None:
            msg += f", preostalo API zahtjeva: {client.last_remaining}"
        log("✅ " + msg)
        return FetchResult(True, df, msg, paths, events=len(events))
    except OddsApiError as e:
        return FetchResult(False, pd.DataFrame(), str(e))
    except Exception as e:
        import traceback
        return FetchResult(False, pd.DataFrame(), f"{e}\n{traceback.format_exc()[-800:]}")
