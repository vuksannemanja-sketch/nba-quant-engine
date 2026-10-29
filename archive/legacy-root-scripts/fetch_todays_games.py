import os, json, datetime, urllib.request, subprocess, sys, ssl

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

SEASON = "2025-26"

# The Odds API
ODDS_API_KEY = "cb0541c83972398497ab1e9add4fe94f"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# NBA bookmaker priority: bet365 first, then others as fallback
BOOKMAKER_PRIORITY = ["pinnacle", "bet365", "fanduel", "draftkings", "betmgm", "betrivers", "betonlineag", "bovada"]

HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def hget(url, t=20):
    try:
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers=HDR)
        with urllib.request.urlopen(req, timeout=t, context=ctx) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[fetch] {url[:80]}: {e}")
        return None


def fetch_player_props():
    """Dohvata NBA player props (points over/under) sa The Odds API."""
    # Step 1: Get today's NBA events
    events_url = (
        f"{ODDS_API_BASE}/sports/basketball_nba/events"
        f"?apiKey={ODDS_API_KEY}&dateFormat=iso"
    )
    print(f"[fetch_todays_games] Dohvatam NBA meceve sa The Odds API...")
    events = hget(events_url)
    if not events:
        print("[fetch_todays_games] GRESKA: Ne mogu dohvatiti meceve sa The Odds API")
        return [], []

    # Filter today's games
    today = datetime.date.today().isoformat()
    todays_events = []
    for ev in events:
        commence = ev.get("commence_time", "")
        if commence.startswith(today):
            todays_events.append(ev)

    print(f"[fetch_todays_games] Nasao {len(todays_events)} meceva za danas ({today})")
    if not todays_events:
        # Maybe games are in different timezone - take all events within next 24h
        now = datetime.datetime.utcnow()
        cutoff = now + datetime.timedelta(hours=24)
        for ev in events:
            commence = ev.get("commence_time", "")
            try:
                # Parse ISO format: 2026-03-18T23:00:00Z
                dt = datetime.datetime.strptime(commence[:19], "%Y-%m-%dT%H:%M:%S")
                if now <= dt <= cutoff:
                    todays_events.append(ev)
            except Exception:
                pass
        print(f"[fetch_todays_games] (fallback 24h) Nasao {len(todays_events)} meceva")

    if not todays_events:
        return [], []

    # Save games summary
    games_summary = []
    for ev in todays_events:
        home = ev.get("home_team", "")
        away = ev.get("away_team", "")
        games_summary.append({"home": home, "away": away, "event_id": ev.get("id", "")})
        print(f"  - {away} @ {home}")

    # Step 2: Fetch player props for each event
    rows = []
    for ev in todays_events:
        event_id = ev.get("id", "")
        home_team = ev.get("home_team", "")
        away_team = ev.get("away_team", "")

        props_url = (
            f"{ODDS_API_BASE}/sports/basketball_nba/events/{event_id}/odds"
            f"?apiKey={ODDS_API_KEY}"
            f"&regions=eu,uk,us"
            f"&markets=player_points"
            f"&oddsFormat=decimal"
            f"&bookmakers={','.join(BOOKMAKER_PRIORITY)}"
        )
        print(f"[fetch_todays_games] Dohvatam props za {away_team}@{home_team}...")
        data = hget(props_url)
        if not data:
            print(f"  GRESKA: nema podataka za {away_team}@{home_team}")
            continue

        bookmakers = data.get("bookmakers", [])
        if not bookmakers:
            print(f"  Nema kladionica za {away_team}@{home_team}")
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
            print(f"  Nema player_points marketa za {away_team}@{home_team}")
            continue

        outcomes = player_points_market.get("outcomes", [])
        # Group by player name
        players = {}
        for outcome in outcomes:
            name = outcome.get("description") or outcome.get("name", "")
            otype = outcome.get("name", "").lower()  # "Over" or "Under"
            price = outcome.get("price", 0)
            point = outcome.get("point", 0)

            if name not in players:
                players[name] = {"over": None, "under": None, "line": point}
            if "over" in otype:
                players[name]["over"] = price
                players[name]["line"] = point
            elif "under" in otype:
                players[name]["under"] = price

        # Determine opponent for each player
        # We don't know team per player from this API, so we list both teams
        matchup = f"{away_team}@{home_team}"

        for player_name, odds in players.items():
            if not player_name:
                continue
            line = odds.get("line", 0)
            over = odds.get("over") or 1.909
            under = odds.get("under") or 1.909
            if line and line > 0:
                rows.append(f"{player_name},{line},{over},{under},{matchup}")

        print(f"  {len(players)} igraca za {away_team}@{home_team}")

    return rows, games_summary


def fetch_and_save():
    today = datetime.date.today().strftime("%Y-%m-%d")
    print(f"[fetch_todays_games] Datum: {today}")

    rows, games = fetch_player_props()

    # Save games to JSON
    games_path = os.path.join(DATA_DIR, "todays_games.json")
    with open(games_path, "w", encoding="utf-8") as f:
        json.dump({"date": today, "games": games}, f, indent=2)

    offer_path = os.path.join(DATA_DIR, "todays_offer.txt")

    if not rows:
        print("[fetch_todays_games] Nema ponude za danas")
        with open(offer_path, "w", encoding="utf-8") as f:
            f.write(f"# Nema ponude {today}\n")
        return 0, games

    # Write offer file
    game_labels = ", ".join(f"{g['away']}@{g['home']}" for g in games)
    hdr_line = f"# NBA ponuda {today} | {game_labels}"
    with open(offer_path, "w", encoding="utf-8") as f:
        f.write(hdr_line + "\n")
        for r in rows:
            f.write(r + "\n")

    print(f"[fetch_todays_games] {len(rows)} redova -> {offer_path}")
    return len(rows), games


if __name__ == "__main__":
    c, g = fetch_and_save()
    print(f"[fetch_todays_games] Gotovo! {c} redova, {len(g)} meceva.")
