import os
import json
import datetime
import urllib.request
import ssl
import csv

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

SEASON = "2025-26"

# The Odds API
ODDS_API_KEY = "cb0541c83972398497ab1e9add4fe94f"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# NBA bookmaker priority
BOOKMAKER_PRIORITY = ["pinnacle", "bet365", "fanduel", "draftkings", "betmgm", "betrivers", "betonlineag", "bovada"]

HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# =====================================================
# TEAM NAME MAPPING - Full name to abbreviation
# =====================================================
TEAM_NAME_TO_ABBR = {
    "atlanta hawks": "ATL",
    "boston celtics": "BOS",
    "brooklyn nets": "BKN",
    "charlotte hornets": "CHA",
    "chicago bulls": "CHI",
    "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL",
    "denver nuggets": "DEN",
    "detroit pistons": "DET",
    "golden state warriors": "GSW",
    "houston rockets": "HOU",
    "indiana pacers": "IND",
    "los angeles clippers": "LAC",
    "la clippers": "LAC",
    "los angeles lakers": "LAL",
    "la lakers": "LAL",
    "memphis grizzlies": "MEM",
    "miami heat": "MIA",
    "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN",
    "new orleans pelicans": "NOP",
    "new york knicks": "NYK",
    "orlando magic": "ORL",
    "philadelphia 76ers": "PHI",
    "phoenix suns": "PHX",
    "portland trail blazers": "POR",
    "sacramento kings": "SAC",
    "san antonio spurs": "SAS",
    "oklahoma city thunder": "OKC",
    "toronto raptors": "TOR",
    "utah jazz": "UTA",
    "washington wizards": "WAS",
}


def get_team_abbr(full_name):
    """Convert full team name to abbreviation."""
    if not full_name:
        return ""
    key = full_name.strip().lower()
    return TEAM_NAME_TO_ABBR.get(key, full_name[:3].upper())


def hget(url, t=20):
    """HTTP GET with JSON parsing."""
    try:
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers=HDR)
        with urllib.request.urlopen(req, timeout=t, context=ctx) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[fetch] {url[:80]}: {e}")
        return None


def fetch_game_totals(event_id):
    """Fetch match total (over/under) for a specific game."""
    totals_url = (
        f"{ODDS_API_BASE}/sports/basketball_nba/events/{event_id}/odds"
        f"?apiKey={ODDS_API_KEY}"
        f"&regions=eu,uk,us"
        f"&markets=totals"
        f"&oddsFormat=decimal"
        f"&bookmakers={','.join(BOOKMAKER_PRIORITY)}"
    )
    data = hget(totals_url)
    if not data:
        return None
    
    bookmakers = data.get("bookmakers", [])
    if not bookmakers:
        return None
    
    # Find best bookmaker
    chosen_bm = None
    for bm_key in BOOKMAKER_PRIORITY:
        for bm in bookmakers:
            if bm.get("key") == bm_key:
                chosen_bm = bm
                break
        if chosen_bm:
            break
    if not chosen_bm:
        chosen_bm = bookmakers[0]
    
    markets = chosen_bm.get("markets", [])
    for m in markets:
        if m.get("key") == "totals":
            outcomes = m.get("outcomes", [])
            for o in outcomes:
                if o.get("name", "").lower() == "over":
                    return o.get("point")
    return None


def fetch_player_props():
    """Fetch NBA player props (points over/under) from The Odds API."""
    
    # Step 1: Get NBA events
    events_url = (
        f"{ODDS_API_BASE}/sports/basketball_nba/events"
        f"?apiKey={ODDS_API_KEY}&dateFormat=iso"
    )
    print(f"[fetch_todays_games] Dohvatam NBA meceve sa The Odds API...")
    events = hget(events_url)
    if not events:
        print("[fetch_todays_games] GRESKA: Ne mogu dohvatiti meceve sa The Odds API")
        return [], []

    # Filter today's games (with timezone flexibility)
    today = datetime.date.today().isoformat()
    now = datetime.datetime.utcnow()
    cutoff = now + datetime.timedelta(hours=28)  # Extended window
    
    todays_events = []
    for ev in events:
        commence = ev.get("commence_time", "")
        try:
            dt = datetime.datetime.strptime(commence[:19], "%Y-%m-%dT%H:%M:%S")
            # Include games starting today or within next 28 hours
            if commence.startswith(today) or (now <= dt <= cutoff):
                todays_events.append(ev)
        except Exception:
            if commence.startswith(today):
                todays_events.append(ev)

    # Remove duplicates
    seen_ids = set()
    unique_events = []
    for ev in todays_events:
        eid = ev.get("id", "")
        if eid not in seen_ids:
            seen_ids.add(eid)
            unique_events.append(ev)
    todays_events = unique_events

    print(f"[fetch_todays_games] Nasao {len(todays_events)} meceva za danas ({today})")

    if not todays_events:
        return [], []

    # Build games summary with totals
    games_summary = []
    game_totals = {}  # event_id -> total
    
    for ev in todays_events:
        event_id = ev.get("id", "")
        home = ev.get("home_team", "")
        away = ev.get("away_team", "")
        home_abbr = get_team_abbr(home)
        away_abbr = get_team_abbr(away)
        
        print(f"  - {away_abbr} @ {home_abbr}")
        
        # Fetch match total
        total = fetch_game_totals(event_id)
        if total:
            game_totals[event_id] = total
            print(f"    Total: {total}")
        
        games_summary.append({
            "home": home,
            "away": away,
            "home_abbr": home_abbr,
            "away_abbr": away_abbr,
            "event_id": event_id,
            "total": total
        })

    # Step 2: Fetch player props for each event
    rows = []
    
    for ev in todays_events:
        event_id = ev.get("id", "")
        home_team = ev.get("home_team", "")
        away_team = ev.get("away_team", "")
        home_abbr = get_team_abbr(home_team)
        away_abbr = get_team_abbr(away_team)
        match_total = game_totals.get(event_id)

        props_url = (
            f"{ODDS_API_BASE}/sports/basketball_nba/events/{event_id}/odds"
            f"?apiKey={ODDS_API_KEY}"
            f"&regions=eu,uk,us"
            f"&markets=player_points"
            f"&oddsFormat=decimal"
            f"&bookmakers={','.join(BOOKMAKER_PRIORITY)}"
        )
        print(f"[fetch_todays_games] Dohvatam props za {away_abbr}@{home_abbr}...")
        data = hget(props_url)
        if not data:
            print(f"  GRESKA: nema podataka za {away_abbr}@{home_abbr}")
            continue

        bookmakers = data.get("bookmakers", [])
        if not bookmakers:
            print(f"  Nema kladionica za {away_abbr}@{home_abbr}")
            continue

        # Find best bookmaker (priority order)
        chosen_bm = None
        for bm_key in BOOKMAKER_PRIORITY:
            for bm in bookmakers:
                if bm.get("key") == bm_key:
                    chosen_bm = bm
                    break
            if chosen_bm:
                break
        if not chosen_bm:
            chosen_bm = bookmakers[0]

        bm_name = chosen_bm.get("title", chosen_bm.get("key", "?"))
        print(f"  Koristim: {bm_name}")

        # Extract player points markets
        markets = chosen_bm.get("markets", [])
        player_points_market = None
        for m in markets:
            if m.get("key") == "player_points":
                player_points_market = m
                break

        if not player_points_market:
            print(f"  Nema player_points marketa za {away_abbr}@{home_abbr}")
            continue

        outcomes = player_points_market.get("outcomes", [])
        
        # Group by player name
        players = {}
        for outcome in outcomes:
            name = outcome.get("description") or outcome.get("name", "")
            otype = outcome.get("name", "").lower()  # "Over" or "Under"
            price = outcome.get("price", 0)
            point = outcome.get("point", 0)

            if not name or name.lower() in ("over", "under"):
                continue

            if name not in players:
                players[name] = {"over": None, "under": None, "line": point}
            
            if "over" in otype:
                players[name]["over"] = price
                players[name]["line"] = point
            elif "under" in otype:
                players[name]["under"] = price

        # Create rows for each player
        for player_name, odds in players.items():
            if not player_name:
                continue
            
            line = odds.get("line", 0)
            over = odds.get("over")
            under = odds.get("under")
            
            # Skip if missing critical data
            if not line or line <= 0:
                continue
            if not over or not under:
                continue
            
            # Format: Player,Line,Over,Under,OppTeam,Total
            opp_info = f"{away_abbr}@{home_abbr}"
            
            row = {
                "player": player_name,
                "line": round(line, 1),
                "over": round(over, 3),
                "under": round(under, 3),
                "matchup": opp_info,
                "total": round(match_total, 1) if match_total else "",
                "home_abbr": home_abbr,
                "away_abbr": away_abbr
            }
            rows.append(row)

        print(f"  {len(players)} igraca za {away_abbr}@{home_abbr}")

    return rows, games_summary


def save_offer(rows, games_summary):
    """Save offer in multiple formats for compatibility."""
    today = datetime.date.today().strftime("%Y-%m-%d")
    
    # === 1. Save games to JSON ===
    games_path = os.path.join(DATA_DIR, "todays_games.json")
    with open(games_path, "w", encoding="utf-8") as f:
        json.dump({"date": today, "games": games_summary}, f, indent=2, ensure_ascii=False)
    print(f"[save] {games_path}")

    if not rows:
        print("[fetch_todays_games] Nema ponude za danas")
        # Create empty files
        for path in [
            os.path.join(DATA_DIR, "offer_latest.csv"),
            os.path.join(DATA_DIR, "todays_offer.txt"),
        ]:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# Nema ponude {today}\n")
        return 0

    # === 2. Save as offer_latest.csv (PRIMARY - for engine) ===
    offer_csv_path = os.path.join(DATA_DIR, "offer_latest.csv")
    with open(offer_csv_path, "w", encoding="utf-8", newline="") as f:
        for r in rows:
            total_str = str(r["total"]) if r["total"] else ""
            line = f'{r["player"]},{r["line"]},{r["over"]},{r["under"]},{r["matchup"]},{total_str}'
            f.write(line + "\n")
    print(f"[save] {offer_csv_path} ({len(rows)} rows)")

    # === 3. Save as dated CSV backup ===
    dated_csv_path = os.path.join(DATA_DIR, f"offer_{today}.csv")
    with open(dated_csv_path, "w", encoding="utf-8", newline="") as f:
        for r in rows:
            total_str = str(r["total"]) if r["total"] else ""
            line = f'{r["player"]},{r["line"]},{r["over"]},{r["under"]},{r["matchup"]},{total_str}'
            f.write(line + "\n")
    print(f"[save] {dated_csv_path}")

    # === 4. Save as todays_offer.txt (legacy format) ===
    offer_txt_path = os.path.join(DATA_DIR, "todays_offer.txt")
    game_labels = ", ".join(f"{g['away_abbr']}@{g['home_abbr']}" for g in games_summary)
    with open(offer_txt_path, "w", encoding="utf-8") as f:
        f.write(f"# NBA ponuda {today} | {game_labels}\n")
        for r in rows:
            total_str = str(r["total"]) if r["total"] else ""
            line = f'{r["player"]},{r["line"]},{r["over"]},{r["under"]},{r["matchup"]},{total_str}'
            f.write(line + "\n")
    print(f"[save] {offer_txt_path}")

    # === 5. Save detailed JSON for debugging ===
    offer_json_path = os.path.join(DATA_DIR, "offer_latest.json")
    with open(offer_json_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": today,
            "generated_at": datetime.datetime.now().isoformat(),
            "games": games_summary,
            "player_count": len(rows),
            "players": rows
        }, f, indent=2, ensure_ascii=False)
    print(f"[save] {offer_json_path}")

    return len(rows)


def fetch_and_save():
    """Main function - fetch and save all data."""
    today = datetime.date.today().strftime("%Y-%m-%d")
    print("=" * 60)
    print(f"[fetch_todays_games] NBA Player Props Fetcher")
    print(f"[fetch_todays_games] Datum: {today}")
    print("=" * 60)

    rows, games = fetch_player_props()
    count = save_offer(rows, games)

    print("=" * 60)
    print(f"[fetch_todays_games] GOTOVO!")
    print(f"  - Meceva: {len(games)}")
    print(f"  - Igraca: {count}")
    print("=" * 60)

    return count, games


# =====================================================
# BONUS: Fetch B2B teams for today
# =====================================================
def fetch_b2b_teams():
    """
    Fetch which teams are on back-to-back.
    Returns set of team abbreviations playing B2B today.
    """
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    today = datetime.date.today().isoformat()
    
    events_url = (
        f"{ODDS_API_BASE}/sports/basketball_nba/events"
        f"?apiKey={ODDS_API_KEY}&dateFormat=iso"
    )
    events = hget(events_url)
    if not events:
        return set()
    
    yesterday_teams = set()
    today_teams = set()
    
    for ev in events:
        commence = ev.get("commence_time", "")[:10]
        home = get_team_abbr(ev.get("home_team", ""))
        away = get_team_abbr(ev.get("away_team", ""))
        
        if commence == yesterday:
            yesterday_teams.add(home)
            yesterday_teams.add(away)
        elif commence == today:
            today_teams.add(home)
            today_teams.add(away)
    
    b2b_teams = yesterday_teams & today_teams
    
    if b2b_teams:
        b2b_path = os.path.join(DATA_DIR, f"b2b_{today}.txt")
        with open(b2b_path, "w") as f:
            f.write(",".join(sorted(b2b_teams)))
        print(f"[B2B] Teams on back-to-back: {', '.join(sorted(b2b_teams))}")
    
    return b2b_teams


if __name__ == "__main__":
    # Fetch player props
    count, games = fetch_and_save()
    
    # Also check for B2B teams
    b2b = fetch_b2b_teams()
    
    print(f"\n✅ Spremno za NBA Quant Engine!")
    print(f"   Pokreni: streamlit run nba_quant_engine.py")