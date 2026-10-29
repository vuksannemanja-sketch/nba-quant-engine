#!/usr/bin/env python3
"""
NBA Daily Offer Fetcher
=======================
Povlači dnevnu ponudu NBA player points (over/under) props
putem The Odds API i sprema u CSV fajl.

Potrebno:
    pip install requests pandas

API Key:
    Registruj se na https://the-odds-api.com/ za besplatan API key
    (500 requesta mjesečno besplatno)
"""

import os
import csv
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
import pandas as pd

# ═══════════════════════════════════════════════════════════════════════════════
# KONFIGURACIJA
# ═══════════════════════════════════════════════════════════════════════════════

# API Key - postavi kao environment variable ili direktno ovdje
API_KEY = os.environ.get("ODDS_API_KEY", "b4466b49831e9d5e17fd53a270d2d96a")

# Output fajl
OUTPUT_DIR = os.path.join(os.getcwd(), "data")
OUTPUT_FILE = "dnevna_ponuda.csv"

# API endpoints
BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "basketball_nba"
MARKETS = "player_points"  # player points over/under
REGIONS = "us,eu,uk"       # regije za odds
ODDS_FORMAT = "decimal"    # decimal format (1.91 umjesto -110)

# Bookmakers prioritet (uzima se prvi dostupan)
BOOKMAKER_PRIORITY = [
    "fanduel",
    "draftkings",
    "betmgm",
    "pointsbetus",
    "williamhill_us",
    "betrivers",
    "unibet_us",
    "bovada",
    "betonlineag",
    "pinnacle",
    "bet365",
]

# Team abbreviations mapping
TEAM_NAME_TO_ABBR = {
    "atlanta hawks": "ATL", "boston celtics": "BOS", "brooklyn nets": "BKN",
    "charlotte hornets": "CHA", "chicago bulls": "CHI", "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL", "denver nuggets": "DEN", "detroit pistons": "DET",
    "golden state warriors": "GSW", "houston rockets": "HOU", "indiana pacers": "IND",
    "los angeles clippers": "LAC", "la clippers": "LAC", "los angeles lakers": "LAL",
    "memphis grizzlies": "MEM", "miami heat": "MIA", "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN", "new orleans pelicans": "NOP", "new york knicks": "NYK",
    "orlando magic": "ORL", "philadelphia 76ers": "PHI", "phoenix suns": "PHX",
    "portland trail blazers": "POR", "sacramento kings": "SAC", "san antonio spurs": "SAS",
    "oklahoma city thunder": "OKC", "toronto raptors": "TOR", "utah jazz": "UTA",
    "washington wizards": "WAS",
}

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_team_name(name: str) -> str:
    """Pretvara puno ime tima u kraticu (abbr)."""
    if not name:
        return ""
    name_lower = name.lower().strip()
    return TEAM_NAME_TO_ABBR.get(name_lower, name.upper()[:3])


def get_best_bookmaker_odds(
    outcomes: List[Dict], 
    bookmakers_data: List[Dict],
    market_key: str = "player_points"
) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    """
    Pronalazi najbolje odds od prioritetnih bookmakera.
    Returns: (line, over_odds, under_odds, bookmaker_name)
    """
    # Sortiraj bookmakers po prioritetu
    bookie_map = {bm["key"]: bm for bm in bookmakers_data}
    
    for bookie_key in BOOKMAKER_PRIORITY:
        if bookie_key not in bookie_map:
            continue
        
        bookie = bookie_map[bookie_key]
        for market in bookie.get("markets", []):
            if market.get("key") != market_key:
                continue
            
            outcomes = market.get("outcomes", [])
            over_outcome = next((o for o in outcomes if o.get("name") == "Over"), None)
            under_outcome = next((o for o in outcomes if o.get("name") == "Under"), None)
            
            if over_outcome and under_outcome:
                line = over_outcome.get("point")
                over_odds = over_outcome.get("price")
                under_odds = under_outcome.get("price")
                
                if all(v is not None for v in [line, over_odds, under_odds]):
                    return line, over_odds, under_odds, bookie_key
    
    # Fallback: uzmi bilo koji bookmaker koji ima podatke
    for bookie in bookmakers_data:
        for market in bookie.get("markets", []):
            if market.get("key") != market_key:
                continue
            
            outcomes = market.get("outcomes", [])
            over_outcome = next((o for o in outcomes if o.get("name") == "Over"), None)
            under_outcome = next((o for o in outcomes if o.get("name") == "Under"), None)
            
            if over_outcome and under_outcome:
                line = over_outcome.get("point")
                over_odds = over_outcome.get("price")
                under_odds = under_outcome.get("price")
                
                if all(v is not None for v in [line, over_odds, under_odds]):
                    return line, over_odds, under_odds, bookie.get("key", "unknown")
    
    return None, None, None, ""


# ═══════════════════════════════════════════════════════════════════════════════
# API FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_nba_events() -> List[Dict]:
    """Dohvaća listu današnjih/sutrašnjih NBA utakmica."""
    url = f"{BASE_URL}/sports/{SPORT}/events"
    params = {"apiKey": API_KEY}
    
    log.info("📅 Dohvaćam NBA raspored...")
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        events = resp.json()
        log.info(f"   Pronađeno {len(events)} utakmica")
        return events
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 401:
            log.error("❌ API key nije validan ili je istekla kvota!")
        else:
            log.error(f"❌ HTTP greška: {e}")
        return []
    except Exception as e:
        log.error(f"❌ Greška pri dohvaćanju rasporeda: {e}")
        return []


def fetch_player_props(event_id: str) -> Dict:
    """Dohvaća player props za specifičnu utakmicu."""
    url = f"{BASE_URL}/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
    }
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 404:
            log.warning(f"   ⚠️ Nema props za event {event_id}")
        else:
            log.error(f"   ❌ HTTP greška za {event_id}: {e}")
        return {}
    except Exception as e:
        log.error(f"   ❌ Greška za {event_id}: {e}")
        return {}


def check_api_quota() -> Dict:
    """Provjerava preostalu API kvotu."""
    url = f"{BASE_URL}/sports"
    params = {"apiKey": API_KEY}
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        return {"remaining": remaining, "used": used, "ok": resp.status_code == 200}
    except Exception:
        return {"remaining": "?", "used": "?", "ok": False}


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

def process_event_props(event: Dict, props_data: Dict) -> List[Dict]:
    """Procesira props podatke za jednu utakmicu."""
    rows = []
    
    home_team = event.get("home_team", "")
    away_team = event.get("away_team", "")
    home_abbr = normalize_team_name(home_team)
    away_abbr = normalize_team_name(away_team)
    
    # Game total (ako je dostupan)
    game_total = None  # Može se dohvatiti odvojenim API pozivom
    
    bookmakers = props_data.get("bookmakers", [])
    if not bookmakers:
        return rows
    
    # Skupi sve igrače iz svih bookmakera
    players_seen = set()
    
    for bookie in bookmakers:
        for market in bookie.get("markets", []):
            if market.get("key") != "player_points":
                continue
            
            for outcome in market.get("outcomes", []):
                player_name = outcome.get("description", "")
                if not player_name or player_name in players_seen:
                    continue
                
                players_seen.add(player_name)
                
                # Pronađi tim igrača (pretpostavljamo home ili away)
                # API ne daje direktno tim, pa ćemo ostaviti prazno ili pokušati matchirati
                player_team = ""
                opp_team = ""
                
                # Dohvati najbolje odds za ovog igrača
                line, over_odds, under_odds, bookie_used = get_best_bookmaker_odds(
                    outcomes=[],  # ne koristimo
                    bookmakers_data=bookmakers,
                    market_key="player_points"
                )
                
                # Moramo pronaći odds specifično za ovog igrača
                for bm in bookmakers:
                    for mkt in bm.get("markets", []):
                        if mkt.get("key") != "player_points":
                            continue
                        
                        player_outcomes = [o for o in mkt.get("outcomes", []) 
                                          if o.get("description") == player_name]
                        
                        over_o = next((o for o in player_outcomes if o.get("name") == "Over"), None)
                        under_o = next((o for o in player_outcomes if o.get("name") == "Under"), None)
                        
                        if over_o and under_o:
                            line = over_o.get("point")
                            over_odds = over_o.get("price")
                            under_odds = under_o.get("price")
                            bookie_used = bm.get("key", "")
                            break
                    
                    if line is not None:
                        break
                
                if line is None or over_odds is None or under_odds is None:
                    continue
                
                # Matchup info
                matchup = f"{away_abbr}@{home_abbr}"
                
                rows.append({
                    "PLAYER": player_name,
                    "LINE": round(float(line), 1),
                    "OVER_ODDS": round(float(over_odds), 2),
                    "UNDER_ODDS": round(float(under_odds), 2),
                    "OPP_TEAM": opp_team,  # Prazno - teško odrediti bez dodatnog matchiranja
                    "TOTAL_MATCH": game_total,
                    "MATCHUP": matchup,
                    "BOOKMAKER": bookie_used,
                    "HOME_TEAM": home_abbr,
                    "AWAY_TEAM": away_abbr,
                })
    
    return rows


def fetch_all_props() -> pd.DataFrame:
    """Glavna funkcija - dohvaća sve player points props za danas."""
    
    # Provjeri API kvotu
    quota = check_api_quota()
    if not quota["ok"]:
        log.error("❌ API nije dostupan ili key nije validan!")
        return pd.DataFrame()
    
    log.info(f"📊 API kvota: {quota['remaining']} preostalo, {quota['used']} iskorišteno")
    
    # Dohvati utakmice
    events = fetch_nba_events()
    if not events:
        log.warning("⚠️ Nema NBA utakmica danas.")
        return pd.DataFrame()
    
    all_rows = []
    
    for i, event in enumerate(events, 1):
        event_id = event.get("id", "")
        home = event.get("home_team", "?")
        away = event.get("away_team", "?")
        commence = event.get("commence_time", "")
        
        log.info(f"🏀 [{i}/{len(events)}] {away} @ {home}")
        
        # Dohvati props za ovu utakmicu
        props_data = fetch_player_props(event_id)
        
        if props_data:
            rows = process_event_props(event, props_data)
            all_rows.extend(rows)
            log.info(f"   ✅ Pronađeno {len(rows)} igrača s points propovima")
        else:
            log.info(f"   ⏭️ Nema props podataka")
    
    if not all_rows:
        log.warning("⚠️ Nije pronađen nijedan player points prop!")
        return pd.DataFrame()
    
    df = pd.DataFrame(all_rows)
    
    # Sortiraj po liniji (highest scorers first)
    df = df.sort_values("LINE", ascending=False)
    
    return df


def save_to_csv(df: pd.DataFrame, filepath: str) -> bool:
    """Sprema DataFrame u CSV."""
    try:
        # Osiguraj da direktorij postoji
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Spremi CSV
        df.to_csv(filepath, index=False)
        log.info(f"💾 Spremljeno {len(df)} redova u {filepath}")
        return True
    except Exception as e:
        log.error(f"❌ Greška pri spremanju: {e}")
        return False


def run(
    output_path: Optional[str] = None,
    api_key: Optional[str] = None
) -> Tuple[bool, pd.DataFrame, str]:
    """
    Glavna funkcija za pokretanje fetcha.
    
    Returns:
        (success, dataframe, message)
    """
    global API_KEY
    
    if api_key:
        API_KEY = api_key
    
    if not API_KEY:
        msg = "❌ API key nije postavljen! Provjeri konfiguraciju."
        log.error(msg)
        return False, pd.DataFrame(), msg
    
    if output_path is None:
        output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    
    log.info("=" * 60)
    log.info("🏀 NBA DAILY OFFER FETCHER")
    log.info(f"📅 Datum: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)
    
    # Dohvati sve props
    df = fetch_all_props()
    
    if df.empty:
        msg = "⚠️ Nema podataka za danas."
        log.warning(msg)
        return False, df, msg
    
    # Spremi CSV
    if save_to_csv(df, output_path):
        msg = f"✅ Uspješno dohvaćeno {len(df)} player props!"
        log.info(msg)
        return True, df, msg
    else:
        msg = "❌ Greška pri spremanju CSV-a."
        return False, df, msg


# ═══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="NBA Daily Offer Fetcher - povlači player points props"
    )
    parser.add_argument(
        "--api-key", "-k",
        help="The Odds API key (ili postavi ODDS_API_KEY env var)"
    )
    parser.add_argument(
        "--output", "-o",
        help=f"Output CSV putanja (default: {os.path.join(OUTPUT_DIR, OUTPUT_FILE)})"
    )
    parser.add_argument(
        "--check-quota", "-q",
        action="store_true",
        help="Samo provjeri API kvotu"
    )
    
    args = parser.parse_args()
    
    if args.api_key:
        API_KEY = args.api_key
    
    if args.check_quota:
        quota = check_api_quota()
        print(f"API Quota: {quota['remaining']} remaining, {quota['used']} used")
        exit(0)
    
    success, df, msg = run(output_path=args.output)
    
    if success:
        print(f"\n✅ {msg}")
        print(f"\n📊 Preview (prvih 10 redova):\n")
        print(df.head(10).to_string(index=False))
    else:
        print(f"\n❌ {msg}")
        exit(1)