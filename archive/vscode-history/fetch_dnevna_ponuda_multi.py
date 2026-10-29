#!/usr/bin/env python3
"""
NBA Daily Offer Fetcher - Player Points Props
Kompatibilno sa NBA Quant Engine (app.py)

FIXED VERSION 2 - Ispravljen pandas Series handling
"""

import os
import re
import unicodedata
import requests
import pandas as pd
import numpy as np
from datetime import datetime

# =============================================================================
# KONFIGURACIJA
# =============================================================================

ODDS_API_KEY = "7d1251f3e72d4bfeb2e83b5a43608dcc"
BASE_URL = "https://api.the-odds-api.com/v4"
DATA_DIR = os.path.join(os.getcwd(), "data")
SEASON = "2025-26"

TEAMS = {
    "atlanta hawks": "ATL", "boston celtics": "BOS", "brooklyn nets": "BKN",
    "charlotte hornets": "CHA", "chicago bulls": "CHI", "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL", "denver nuggets": "DEN", "detroit pistons": "DET",
    "golden state warriors": "GSW", "houston rockets": "HOU", "indiana pacers": "IND",
    "los angeles clippers": "LAC", "la clippers": "LAC", "los angeles lakers": "LAL",
    "memphis grizzlies": "MEM", "miami heat": "MIA", "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN", "new orleans pelicans": "NOP", "new york knicks": "NYK",
    "oklahoma city thunder": "OKC", "orlando magic": "ORL", "philadelphia 76ers": "PHI",
    "phoenix suns": "PHX", "portland trail blazers": "POR", "sacramento kings": "SAC",
    "san antonio spurs": "SAS", "toronto raptors": "TOR", "utah jazz": "UTA",
    "washington wizards": "WAS"
}

TEAM_ID_TO_ABBR = {
    1610612737: "ATL", 1610612738: "BOS", 1610612751: "BKN", 1610612766: "CHA",
    1610612741: "CHI", 1610612739: "CLE", 1610612742: "DAL", 1610612743: "DEN",
    1610612765: "DET", 1610612744: "GSW", 1610612745: "HOU", 1610612754: "IND",
    1610612746: "LAC", 1610612747: "LAL", 1610612763: "MEM", 1610612748: "MIA",
    1610612749: "MIL", 1610612750: "MIN", 1610612740: "NOP", 1610612752: "NYK",
    1610612753: "ORL", 1610612755: "PHI", 1610612756: "PHX", 1610612757: "POR",
    1610612758: "SAC", 1610612759: "SAS", 1610612760: "OKC", 1610612761: "TOR",
    1610612762: "UTA", 1610612764: "WAS",
}

# =============================================================================
# HELPERS
# =============================================================================

def normalize_name(s):
    if not s:
        return ""
    s = str(s).strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def get_abbr(team_name):
    if not team_name:
        return ""
    return TEAMS.get(team_name.lower().strip(), team_name[:3].upper())

def safe_get_scalar(value):
    """Sigurno izvuci skalarnu vrijednost iz pandas Series ili scalar"""
    if value is None:
        return None
    if isinstance(value, pd.Series):
        if len(value) == 0:
            return None
        return value.iloc[0]
    if isinstance(value, np.ndarray):
        if len(value) == 0:
            return None
        return value[0]
    return value

def safe_team_abbr(value):
    """Sigurno konvertuj vrijednost u team abbreviation"""
    val = safe_get_scalar(value)
    if val is None:
        return None
    if isinstance(val, float) and np.isnan(val):
        return None
    s = str(val).strip().upper()
    if not s or s == "NAN" or s == "NONE":
        return None
    if s in TEAM_ID_TO_ABBR.values():
        return s
    return None

def load_players_df():
    """Učitaj players CSV za mapiranje igrač -> tim - FIXED VERSION"""
    candidates = [
        os.path.join(DATA_DIR, f"players_{SEASON}.csv"),
        os.path.join(DATA_DIR, "players_2025-26.csv"),
        os.path.join(DATA_DIR, "players.csv"),
    ]
    
    for path in candidates:
        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                
                # KRITIČNO: Ukloni duplikat kolone PRIJE bilo čega
                df = df.loc[:, ~df.columns.duplicated()]
                
                # Standardiziraj imena kolona
                rename_map = {}
                for col in df.columns:
                    cu = col.upper().strip()
                    if cu in ("PLAYER_NAME", "PLAYER", "NAME"):
                        rename_map[col] = "PLAYER_NAME"
                    elif cu in ("TEAM_ABBR", "TEAM_ABBREVIATION"):
                        rename_map[col] = "TEAM_ABBR"
                    elif cu == "TEAM_ID":
                        rename_map[col] = "TEAM_ID"
                    elif cu == "TEAM":
                        rename_map[col] = "TEAM"
                
                df = df.rename(columns=rename_map)
                
                # Ponovo ukloni duplikate nakon rename
                df = df.loc[:, ~df.columns.duplicated()]
                
                # Ako nema TEAM_ABBR, pokušaj kreirati iz TEAM_ID
                if "TEAM_ABBR" not in df.columns:
                    if "TEAM_ID" in df.columns:
                        print("  📝 Kreiram TEAM_ABBR iz TEAM_ID...")
                        df["TEAM_ABBR"] = df["TEAM_ID"].apply(
                            lambda x: TEAM_ID_TO_ABBR.get(int(float(x))) if pd.notna(x) else None
                        )
                    elif "TEAM" in df.columns:
                        print("  📝 Kreiram TEAM_ABBR iz TEAM...")
                        df["TEAM_ABBR"] = df["TEAM"].apply(
                            lambda x: TEAMS.get(str(x).lower().strip()) if pd.notna(x) else None
                        )
                    else:
                        print("  ⚠️ Nema TEAM_ABBR, TEAM_ID, niti TEAM kolone!")
                        continue
                
                # Osiguraj da TEAM_ABBR nije Series nego skalarne vrijednosti
                if "TEAM_ABBR" in df.columns:
                    # Eksplicitno konvertuj u string i očisti
                    df["TEAM_ABBR"] = df["TEAM_ABBR"].apply(safe_team_abbr)
                
                # Kreiraj NAME_KEY
                if "PLAYER_NAME" in df.columns:
                    df["NAME_KEY"] = df["PLAYER_NAME"].astype(str).apply(normalize_name)
                    
                    # Debug info
                    valid_teams = df["TEAM_ABBR"].notna().sum()
                    print(f"  ✅ Učitan: {path}")
                    print(f"     Igrača: {len(df)}")
                    print(f"     TEAM_ABBR popunjen: {valid_teams}/{len(df)}")
                    
                    # Pokaži sample
                    if valid_teams > 0:
                        sample = df[df["TEAM_ABBR"].notna()][["PLAYER_NAME", "TEAM_ABBR"]].head(5)
                        print(f"     Sample: {sample.to_dict('records')}")
                    
                    return df
                else:
                    print(f"  ⚠️ {path}: nema PLAYER_NAME kolonu")
                    
            except Exception as e:
                import traceback
                print(f"  ⚠️ Greška pri učitavanju {path}: {e}")
                print(f"     {traceback.format_exc()[-500:]}")
    
    print("  ❌ UPOZORENJE: Nije pronađen validan players CSV")
    return None

def find_player_team(player_name, players_df):
    """Pronađi tim igrača iz players CSV - FIXED VERSION"""
    if players_df is None:
        return None
    if "NAME_KEY" not in players_df.columns:
        return None
    if "TEAM_ABBR" not in players_df.columns:
        return None
    
    name_key = normalize_name(player_name)
    
    # 1. Exact match
    match = players_df[players_df["NAME_KEY"] == name_key]
    if not match.empty:
        team = safe_get_scalar(match["TEAM_ABBR"].iloc[0])
        if team and str(team).strip().upper() not in ("", "NAN", "NONE"):
            return str(team).strip().upper()
    
    # 2. Token match - prezime + prvi inicijal
    tokens = name_key.split()
    if len(tokens) >= 2:
        last_name = tokens[-1]
        first_init = tokens[0][:2] if tokens[0] else ""
        
        # Escape special regex characters
        last_name_escaped = re.escape(last_name)
        
        mask = players_df["NAME_KEY"].str.contains(last_name_escaped, na=False, regex=True)
        if first_init:
            mask &= players_df["NAME_KEY"].str.startswith(first_init[:1], na=False)
        
        matches = players_df[mask]
        if len(matches) == 1:
            team = safe_get_scalar(matches["TEAM_ABBR"].iloc[0])
            if team and str(team).strip().upper() not in ("", "NAN", "NONE"):
                return str(team).strip().upper()
    
    # 3. Samo prezime (za jedinstvena prezimena)
    if tokens:
        last_name = tokens[-1]
        if len(last_name) >= 5:  # Samo za duža prezimena
            last_name_escaped = re.escape(last_name)
            mask = players_df["NAME_KEY"].str.contains(last_name_escaped, na=False, regex=True)
            matches = players_df[mask]
            if len(matches) == 1:
                team = safe_get_scalar(matches["TEAM_ABBR"].iloc[0])
                if team and str(team).strip().upper() not in ("", "NAN", "NONE"):
                    return str(team).strip().upper()
    
    return None

# =============================================================================
# API FUNCTIONS
# =============================================================================

def fetch_events():
    url = f"{BASE_URL}/sports/basketball_nba/events"
    resp = requests.get(url, params={"apiKey": ODDS_API_KEY}, timeout=30)
    resp.raise_for_status()
    return resp.json()

def fetch_game_totals(event_id):
    url = f"{BASE_URL}/sports/basketball_nba/events/{event_id}/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "us", "markets": "totals", "oddsFormat": "decimal"}
    try:
        resp = requests.get(url, params=params, timeout=30)
        data = resp.json()
        for bookie in data.get("bookmakers", []):
            for market in bookie.get("markets", []):
                if market.get("key") == "totals":
                    for outcome in market.get("outcomes", []):
                        if outcome.get("name") == "Over":
                            return outcome.get("point")
    except:
        pass
    return None

def fetch_player_props(event_id, home_abbr, away_abbr, total_match, players_df):
    """
    FIXED: Poboljšana logika za OPP_TEAM
    """
    url = f"{BASE_URL}/sports/basketball_nba/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu,uk",
        "markets": "player_points",
        "oddsFormat": "decimal"
    }
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        data = resp.json()
    except Exception as e:
        print(f"    ⚠️ API greška: {e}")
        return []
    
    bookmakers = data.get("bookmakers", [])
    if not bookmakers:
        return []
    
    props = []
    seen = set()
    
    for bookie in bookmakers:
        for market in bookie.get("markets", []):
            if market.get("key") != "player_points":
                continue
            
            outcomes = market.get("outcomes", [])
            
            # Grupiraj po igraču
            players = {}
            for o in outcomes:
                player = o.get("description", "")
                if player:
                    if player not in players:
                        players[player] = {}
                    players[player][o.get("name")] = o
            
            # Izvuci Over/Under
            for player, sides in players.items():
                if player in seen:
                    continue
                
                over = sides.get("Over")
                under = sides.get("Under")
                
                if not over or not under:
                    continue
                
                seen.add(player)
                
                # ═══════════════════════════════════════════════════════════
                # OPP_TEAM LOGIKA
                # ═══════════════════════════════════════════════════════════
                
                player_team = find_player_team(player, players_df)
                opp_team = None
                
                if player_team:
                    player_team_upper = player_team.upper()
                    home_upper = home_abbr.upper() if home_abbr else ""
                    away_upper = away_abbr.upper() if away_abbr else ""
                    
                    if player_team_upper == home_upper:
                        opp_team = away_abbr
                    elif player_team_upper == away_upper:
                        opp_team = home_abbr
                    else:
                        print(f"    ⚠️ {player}: tim {player_team} ne odgovara meču {away_abbr}@{home_abbr}")
                        opp_team = None
                else:
                    print(f"    ⚠️ {player}: nije pronađen u players_df")
                    opp_team = None
                
                # ═══════════════════════════════════════════════════════════
                
                props.append({
                    "PLAYER": player,
                    "PLAYER_TEAM": player_team if player_team else "",
                    "LINE": over.get("point"),
                    "OVER_ODDS": over.get("price"),
                    "UNDER_ODDS": under.get("price"),
                    "OPP_TEAM": opp_team if opp_team else "",
                    "TOTAL_MATCH": total_match if total_match else ""
                })
        
        if props:
            break
    
    return props

# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("NBA DAILY OFFER FETCHER (FIXED V2)")
    print(f"Vrijeme: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    print("\n📂 Učitavam players bazu za mapiranje timova...")
    players_df = load_players_df()
    
    if players_df is None:
        print("\n⚠️ NASTAVAK BEZ PLAYERS_DF - OPP_TEAM neće biti popunjen!")
    
    print("\n📅 Dohvaćam današnje utakmice...")
    events = fetch_events()
    
    if not events:
        print("❌ Nema utakmica danas!")
        return
    
    print(f"✅ Pronađeno {len(events)} utakmica\n")
    
    all_props = []
    
    for event in events:
        event_id = event.get("id")
        home_abbr = get_abbr(event.get("home_team", ""))
        away_abbr = get_abbr(event.get("away_team", ""))
        
        print(f"🏀 {away_abbr} @ {home_abbr}")
        
        total_match = fetch_game_totals(event_id)
        if total_match:
            print(f"   Total: {total_match}")
        
        props = fetch_player_props(event_id, home_abbr, away_abbr, total_match, players_df)
        print(f"   Igrači: {len(props)}")
        
        all_props.extend(props)
    
    print(f"\n{'=' * 60}")
    print(f"UKUPNO: {len(all_props)} player props")
    print("=" * 60)
    
    if not all_props:
        print("\n❌ Nisu pronađeni props!")
        return
    
    df = pd.DataFrame(all_props)
    df = df.sort_values("LINE", ascending=False)
    
    output_cols = ["PLAYER", "PLAYER_TEAM", "LINE", "OVER_ODDS", "UNDER_ODDS", "OPP_TEAM", "TOTAL_MATCH"]
    df = df[[c for c in output_cols if c in df.columns]]
    
    os.makedirs(DATA_DIR, exist_ok=True)
    
    output_path = os.path.join(DATA_DIR, "offer_latest.csv")
    backup_path = os.path.join(DATA_DIR, "dnevna_ponuda.csv")
    
    df.to_csv(output_path, index=False)
    df.to_csv(backup_path, index=False)
    
    print(f"\n✅ Spremljeno: {output_path}")
    print(f"✅ Spremljeno: {backup_path}")
    
    # Stats
    team_filled = (df.get("PLAYER_TEAM", pd.Series([""])) != "").sum()
    opp_filled = (df["OPP_TEAM"] != "").sum()
    print(f"\n📊 PLAYER_TEAM popunjen: {team_filled}/{len(df)}")
    print(f"📊 OPP_TEAM popunjen: {opp_filled}/{len(df)}")
    
    if opp_filled < len(df) * 0.5:
        print(f"\n⚠️ UPOZORENJE: OPP_TEAM nije popunjen za {len(df) - opp_filled} igrača!")
        print("   Provjeri players CSV i TEAM_ABBR kolonu.")
    
    print(f"\n📋 Preview (top 20):\n")
    print(df.head(20).to_string(index=False))


def run(output_path=None):
    """Za poziv iz app.py"""
    try:
        players_df = load_players_df()
        events = fetch_events()
        
        if not events:
            return False, pd.DataFrame(), "Nema utakmica"
        
        all_props = []
        for event in events:
            event_id = event.get("id")
            home_abbr = get_abbr(event.get("home_team", ""))
            away_abbr = get_abbr(event.get("away_team", ""))
            total_match = fetch_game_totals(event_id)
            props = fetch_player_props(event_id, home_abbr, away_abbr, total_match, players_df)
            all_props.extend(props)
        
        if not all_props:
            return False, pd.DataFrame(), "Nema props"
        
        df = pd.DataFrame(all_props)
        df = df.sort_values("LINE", ascending=False)
        
        output_cols = ["PLAYER", "PLAYER_TEAM", "LINE", "OVER_ODDS", "UNDER_ODDS", "OPP_TEAM", "TOTAL_MATCH"]
        df = df[[c for c in output_cols if c in df.columns]]
        
        os.makedirs(DATA_DIR, exist_ok=True)
        if output_path is None:
            output_path = os.path.join(DATA_DIR, "offer_latest.csv")
        df.to_csv(output_path, index=False)
        df.to_csv(os.path.join(DATA_DIR, "dnevna_ponuda.csv"), index=False)
        
        opp_filled = (df["OPP_TEAM"] != "").sum()
        return True, df, f"OK: {len(df)} props, OPP_TEAM: {opp_filled}/{len(df)}"
    except Exception as e:
        import traceback
        return False, pd.DataFrame(), f"{str(e)}\n{traceback.format_exc()}"


if __name__ == "__main__":
    main()