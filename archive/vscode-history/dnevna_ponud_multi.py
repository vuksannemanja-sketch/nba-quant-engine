#!/usr/bin/env python3
import os
import re
import logging
from datetime import datetime
from typing import Dict, List, Tuple

import requests
import pandas as pd

ODDS_API_KEY = "b4466b49831e9d5e17fd53a270d2d96a"
DATA_DIR = os.path.join(os.getcwd(), "data")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "basketball_nba"

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

def normalize_team(name: str) -> str:
    if not name:
        return ""
    clean = name.lower().strip()
    if clean in TEAM_NAME_TO_ABBR:
        return TEAM_NAME_TO_ABBR[clean]
    for key, abbr in TEAM_NAME_TO_ABBR.items():
        if key in clean or clean in key:
            return abbr
    return name.upper()[:3]

def normalize_player_name(name: str) -> str:
    if not name:
        return ""
    name = re.sub(r'\s+(Jr\.?|Sr\.?|III|II|IV)$', '', name, flags=re.IGNORECASE)
    return name.strip()

def fetch_events() -> List[Dict]:
    url = f"{ODDS_API_BASE}/sports/{SPORT}/events"
    params = {"apiKey": ODDS_API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 401:
            log.error("API key invalid or quota exceeded!")
            return []
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"Error: {e}")
        return []

def fetch_player_props(event_id: str) -> Dict:
    url = f"{ODDS_API_BASE}/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu,uk",
        "markets": "player_points",
        "oddsFormat": "decimal",
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning(f"Props error: {e}")
        return {}

def run() -> Tuple[bool, pd.DataFrame, str]:
    log.info("=" * 60)
    log.info("NBA DAILY OFFER FETCHER")
    log.info(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)
    
    events = fetch_events()
    if not events:
        return False, pd.DataFrame(), "No NBA games today"
    
    log.info(f"Found {len(events)} games")
    
    all_props = []
    
    for event in events:
        event_id = event.get("id", "")
        home_team = event.get("home_team", "")
        away_team = event.get("away_team", "")
        home_abbr = normalize_team(home_team)
        away_abbr = normalize_team(away_team)
        
        log.info(f"{away_abbr} @ {home_abbr}")
        
        props_data = fetch_player_props(event_id)
        if not props_data:
            continue
        
        bookmakers = props_data.get("bookmakers", [])
        if not bookmakers:
            continue
        
        players_processed = set()
        
        for bookie in bookmakers:
            bookie_key = bookie.get("key", "")
            
            for market in bookie.get("markets", []):
                if market.get("key") != "player_points":
                    continue
                
                outcomes = market.get("outcomes", [])
                player_outcomes = {}
                
                for o in outcomes:
                    player = o.get("description", "")
                    if not player:
                        continue
                    if player not in player_outcomes:
                        player_outcomes[player] = {}
                    player_outcomes[player][o.get("name")] = o
                
                for player, sides in player_outcomes.items():
                    if player in players_processed:
                        continue
                    
                    over = sides.get("Over")
                    under = sides.get("Under")
                    
                    if not over or not under:
                        continue
                    
                    line = over.get("point")
                    over_odds = over.get("price")
                    under_odds = under.get("price")
                    
                    if None in (line, over_odds, under_odds):
                        continue
                    
                    players_processed.add(player)
                    
                    all_props.append({
                        "PLAYER": normalize_player_name(player),
                        "LINE": round(float(line), 1),
                        "OVER_ODDS": round(float(over_odds), 2),
                        "UNDER_ODDS": round(float(under_odds), 2),
                        "OPP_TEAM": "",
                        "TOTAL_MATCH": None,
                        "HOME_TEAM": home_abbr,
                        "AWAY_TEAM": away_abbr,
                        "MATCHUP": f"{away_abbr}@{home_abbr}",
                        "BOOKMAKER": bookie_key,
                    })
        
        count = len([p for p in all_props if p['MATCHUP'] == f'{away_abbr}@{home_abbr}'])
        log.info(f"   {count} players")
    
    if not all_props:
        return False, pd.DataFrame(), "No player points props found"
    
    df = pd.DataFrame(all_props)
    df = df.drop_duplicates(subset=["PLAYER", "LINE"])
    df = df.sort_values("LINE", ascending=False)
    
    os.makedirs(DATA_DIR, exist_ok=True)
    
    export_cols = ["PLAYER", "LINE", "OVER_ODDS", "UNDER_ODDS", "OPP_TEAM", "TOTAL_MATCH"]
    export_df = df[export_cols].copy()
    
    export_df.to_csv(os.path.join(DATA_DIR, "dnevna_ponuda.csv"), index=False)
    export_df.to_csv(os.path.join(DATA_DIR, "offer_latest.csv"), index=False)
    
    log.info(f"Saved: data/dnevna_ponuda.csv and data/offer_latest.csv")
    log.info(f"Total players: {len(df)}")
    
    return True, df, f"Fetched {len(df)} player props!"

if __name__ == "__main__":
    success, df, msg = run()
    print(f"\n{msg}")
    if success and not df.empty:
        print(f"\nPreview (top 15):\n")
        print(df[["PLAYER", "LINE", "OVER_ODDS", "UNDER_ODDS", "MATCHUP"]].head(15).to_string(index=False))
    exit(0 if success else 1)