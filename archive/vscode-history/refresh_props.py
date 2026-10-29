"""
refresh_props.py
Fetchuje NBA player props (points) s The Odds API i kreira:
  - data/offer_YYYY-MM-DD.csv  → direktan input za app.py upload
  - data/props_raw_YYYY-MM-DD.json → raw backup

Korištenje:
  python refresh_props.py
  python refresh_props.py --date 2026-03-14
  python refresh_props.py --bookmaker draftkings
  python refresh_props.py --best-line   (uzima best line od svih bookmakera)

Postavi API key:
  Windows: set ODDS_API_KEY=tvoj_key
  Linux:   export ODDS_API_KEY=tvoj_key
  Ili direktno u config ispod.
"""

import os
import sys
import json
import time
import argparse
import requests
import pandas as pd
from datetime import datetime, timezone

# =====================================================
# CONFIG — postavi svoj API key ovdje ili kroz env
# =====================================================

ODDS_API_KEY  = os.environ.get("ODDS_API_KEY", "cb0541c83972398497ab1e9add4fe94f")
SPORT         = "basketball_nba"
REGION        = "eu"          # eu = decimal kvote | us = american | uk = fractional
ODDS_FORMAT   = "decimal"     # decimal je bolji za naš model (već u tom formatu)
MARKET        = "player_points"
BASE_URL      = "https://api.the-odds-api.com/v4"

# Preferirani bookmakeri — uzimamo best line od ovih
PREFERRED_BOOKS = [
    "draftkings", "fanduel", "betmgm", "pointsbet", "caesars",
    "unibet_us", "bet365", "pinnacle", "williamhill_us",
    "betrivers", "betus", "bovada", "mybookieag",
]

DATA_DIR = os.path.join(os.getcwd(), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# =====================================================
# Helpers
# =====================================================

TEAM_NAME_TO_ABBR = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "LA Clippers": "LAC", "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM", "Miami Heat": "MIA", "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS", "Oklahoma City Thunder": "OKC",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}

def team_to_abbr(name: str) -> str:
    return TEAM_NAME_TO_ABBR.get(name, name[:3].upper())

def check_api_key():
    if not ODDS_API_KEY or ODDS_API_KEY == "YOUR_KEY_HERE":
        print("❌ API key nije postavljen!")
        print("   Registriraj se na https://the-odds-api.com (besplatno)")
        print("   Zatim: export ODDS_API_KEY=tvoj_key")
        sys.exit(1)

def get_remaining_requests(response):
    remaining = response.headers.get("x-requests-remaining", "?")
    used      = response.headers.get("x-requests-used", "?")
    last_cost = response.headers.get("x-requests-last", "?")
    return remaining, used, last_cost

# =====================================================
# Step 1: Dohvati listu događaja za danas
# =====================================================

def fetch_events(target_date: str = None) -> list:
    """
    Vraća listu NBA utakmica.
    target_date: "YYYY-MM-DD" — filtrira samo utakmice tog dana
    """
    url = f"{BASE_URL}/sports/{SPORT}/events"
    params = {"apiKey": ODDS_API_KEY}

    print(f"  Fetchujem listu utakmica...")
    resp = requests.get(url, params=params, timeout=30)

    if resp.status_code == 401:
        print("❌ Nevalidan API key.")
        sys.exit(1)
    if resp.status_code == 422:
        print("❌ API greška — provjeri sport key.")
        sys.exit(1)
    resp.raise_for_status()

    remaining, used, cost = get_remaining_requests(resp)
    print(f"  📊 API krediti: iskorišteno={used}, preostalo={remaining}, ovaj poziv={cost}")

    events = resp.json()
    print(f"  Pronađeno {len(events)} NBA događaja ukupno")

    if target_date:
        filtered = []
        for ev in events:
            ct = ev.get("commence_time", "")
            # commence_time je UTC — konvertiramo u datum
            try:
                dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                ev_date = dt.date().isoformat()
                if ev_date == target_date:
                    filtered.append(ev)
            except Exception:
                pass
        print(f"  Filtrirano za {target_date}: {len(filtered)} utakmica")
        return filtered

    return events

# =====================================================
# Step 2: Dohvati props za jedan event
# =====================================================

def fetch_event_props(event_id: str, event_info: dict, bookmaker: str = None) -> dict:
    """
    Fetchuje player_points props za jedan event.
    Vraća dict: {player_name: {line, over_odds, under_odds, bookmaker}}
    """
    url = f"{BASE_URL}/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey":      ODDS_API_KEY,
        "regions":     REGION,
        "markets":     MARKET,
        "oddsFormat":  ODDS_FORMAT,
    }
    if bookmaker:
        params["bookmakers"] = bookmaker

    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 404:
            print(f"    ⚠️  Event {event_id} — props nisu dostupni")
            return {}
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    ❌ Greška za event {event_id}: {e}")
        return {}

    remaining, used, cost = get_remaining_requests(resp)
    data = resp.json()

    home = data.get("home_team", "")
    away = data.get("away_team", "")
    home_abbr = team_to_abbr(home)
    away_abbr = team_to_abbr(away)

    players = {}  # {player_name: {line, over_odds, under_odds, bookmaker, team, opp}}

    for book in data.get("bookmakers", []):
        book_key = book.get("key", "")
        for market in book.get("markets", []):
            if market.get("key") != MARKET:
                continue
            for outcome in market.get("outcomes", []):
                player  = outcome.get("description", "").strip()
                side    = outcome.get("name", "").strip()   # "Over" ili "Under"
                line    = outcome.get("point")
                price   = outcome.get("price")

                if not player or line is None or price is None:
                    continue

                if player not in players:
                    players[player] = {
                        "line":        None,
                        "over_odds":   None,
                        "under_odds":  None,
                        "bookmaker":   book_key,
                        "home_team":   home_abbr,
                        "away_team":   away_abbr,
                    }

                players[player]["line"] = line
                if side == "Over":
                    # Ako već imamo over kvotu, uzmi bolju (višu za kladača)
                    if players[player]["over_odds"] is None or price > players[player]["over_odds"]:
                        players[player]["over_odds"]  = price
                        players[player]["bookmaker"]  = book_key
                elif side == "Under":
                    if players[player]["under_odds"] is None or price > players[player]["under_odds"]:
                        players[player]["under_odds"] = price

    print(f"    ✅ {away_abbr} @ {home_abbr}: {len(players)} igrača  [krediti preostalo: {remaining}]")
    return players

# =====================================================
# Step 3: Odredi tim za svakog igrača
# =====================================================

def assign_teams(all_players: dict, events: list) -> list:
    """
    Pokušava odrediti koji je igrač na kojoj strani (home/away)
    na osnovu event info — vraća listu redova za CSV.
    """
    rows = []
    for player, info in all_players.items():
        if info["over_odds"] is None or info["under_odds"] is None:
            continue  # Nepotpun zapis — preskočimo

        home = info.get("home_team", "")
        away = info.get("away_team", "")

        # Opp team: ne znamo točno koji je igrač na kojoj strani
        # ali app.py to može odrediti iz players CSV (TEAM_ABBR kolona)
        # Ovdje dajemo oba tima kao info — app matchuje sam
        rows.append({
            "player":     player,
            "line":       info["line"],
            "over_odds":  round(float(info["over_odds"]), 3),
            "under_odds": round(float(info["under_odds"]), 3),
            "home_team":  home,
            "away_team":  away,
            "bookmaker":  info.get("bookmaker", ""),
        })

    return rows

# =====================================================
# Step 4: Kreiraj offer.csv u formatu koji app.py čita
# =====================================================

def build_offer_csv(rows: list, output_path: str, players_csv_path: str = None):
    """
    Format koji app.py parse_offer_text() čita:
    player, line, over_odds, under_odds, opp_team

    Logika za OPP_TEAM:
    - Učitamo players CSV da znamo kojoj ekipi pripada igrač
    - Ako je igrač home tim → opp = away tim
    - Ako je igrač away tim → opp = home tim
    - Ako ne možemo odrediti → ostavimo oba tima, app ignorira
    """
    # Pokušaj učitati players CSV za team lookup
    player_team_map = {}  # {normalize(ime): team_abbr}
    if players_csv_path is None:
        # Traži automatski u data/ folderu
        candidates = [
            os.path.join(DATA_DIR, "players_2025-26.csv"),
            os.path.join(DATA_DIR, "players_2025-26_base.csv"),
        ]
        players_csv_path = next((p for p in candidates if os.path.exists(p)), None)

    if players_csv_path and os.path.exists(players_csv_path):
        try:
            pdf = pd.read_csv(players_csv_path)
            # Nađi name i team kolone
            name_col = next((c for c in pdf.columns if c.upper() in
                             ["PLAYER_NAME", "PLAYER", "NAME"]), None)
            team_col = next((c for c in pdf.columns if c.upper() in
                             ["TEAM_ABBREVIATION", "TEAM_ABBR", "TEAM"]), None)
            if name_col and team_col:
                for _, row in pdf.iterrows():
                    raw_name = str(row[name_col]).strip().lower()
                    # Normalizacija: ukloni dijakritike, posebne znakove
                    import unicodedata, re
                    norm = unicodedata.normalize("NFKD", raw_name)
                    norm = "".join(ch for ch in norm if not unicodedata.combining(ch))
                    norm = re.sub(r"[^a-z0-9\s]", " ", norm)
                    norm = re.sub(r"\s+", " ", norm).strip()
                    team = str(row[team_col]).strip().upper()
                    player_team_map[norm] = team
            print(f"  Team lookup: {len(player_team_map)} igrača učitano iz players CSV")
        except Exception as e:
            print(f"  ⚠️  Team lookup fail: {e}")

    def normalize_player(name):
        import unicodedata, re
        n = str(name).strip().lower()
        n = unicodedata.normalize("NFKD", n)
        n = "".join(ch for ch in n if not unicodedata.combining(ch))
        n = re.sub(r"[^a-z0-9\s]", " ", n)
        return re.sub(r"\s+", " ", n).strip()

    offer_rows = []
    resolved = 0
    unresolved = 0

    for r in rows:
        home = r.get("home_team", "")
        away = r.get("away_team", "")
        player_name = r["player"]
        norm_name = normalize_player(player_name)

        # Pokušaj odrediti tim igrača iz players CSV
        player_team = player_team_map.get(norm_name, None)

        # Fuzzy fallback: provjeri djelomično poklapanje
        if not player_team and player_team_map:
            parts = norm_name.split()
            if len(parts) >= 2:
                last = parts[-1]
                matches = [(k, v) for k, v in player_team_map.items() if last in k]
                if len(matches) == 1:
                    player_team = matches[0][1]

        # Odredi protivnika na osnovu tima igrača
        if player_team:
            if player_team == home:
                opp = away   # igrač je domaćin → protivnik je gost
            elif player_team == away:
                opp = home   # igrač je gost → protivnik je domaćin
            else:
                # Tim nije ni home ni away — vjerojatno trades mid-season
                # Stavi oba kao fallback, app ignoriše
                opp = away if away != player_team else home
            resolved += 1
        else:
            # Nema info o timu — stavi away kao default
            opp = away
            unresolved += 1

        offer_rows.append({
            "Player":     player_name,
            "Line":       r["line"],
            "Over Odds":  r["over_odds"],
            "Under Odds": r["under_odds"],
            "OPP_TEAM":   opp,
            "Player_Team": player_team or "",
            "Home":       home,
            "Away":       away,
            "Bookmaker":  r.get("bookmaker", ""),
        })

    print(f"  OPP_TEAM resolved: {resolved} igrača, unresolved: {unresolved}")

    df = pd.DataFrame(offer_rows)

    # Sortiraj po imenu
    df = df.sort_values("Player").reset_index(drop=True)

    # Spremi puni CSV (s metapodacima) za debug
    df.to_csv(output_path, index=False)

    # Spremi i "čisti" offer format koji app direktno uploaduje
    clean_path = output_path.replace(".csv", "_upload.csv")
    clean_df = df[["Player", "Line", "Over Odds", "Under Odds", "OPP_TEAM"]].copy()
    clean_df.to_csv(clean_path, index=False, header=False)

    return df, clean_path

# =====================================================
# Main
# =====================================================

def main():
    parser = argparse.ArgumentParser(description="Fetchuj NBA player props")
    parser.add_argument("--date",        default=None,   help="YYYY-MM-DD (default: danas)")
    parser.add_argument("--bookmaker",   default=None,   help="Specifični bookmaker key (npr. draftkings)")
    parser.add_argument("--best-line",   action="store_true", help="Uzmi best line od svih bookmakera")
    parser.add_argument("--min-line",    type=float, default=4.5, help="Minimalna linija za filtriranje (default 4.5)")
    parser.add_argument("--delay",       type=float, default=1.2, help="Pauza između poziva u sekundama")
    args = parser.parse_args()

    check_api_key()

    today = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\n{'='*55}")
    print(f"  NBA Props Refresh — {today}")
    print(f"{'='*55}")

    # Step 1: Events
    events = fetch_events(target_date=today)
    if not events:
        print(f"\n⚠️  Nema NBA utakmica za {today}")
        sys.exit(0)

    print(f"\n  Utakmice za {today}:")
    for ev in events:
        home = team_to_abbr(ev.get("home_team", "?"))
        away = team_to_abbr(ev.get("away_team", "?"))
        ct   = ev.get("commence_time", "")
        print(f"    {away} @ {home}  [{ct}]")

    # Step 2: Props za svaki event
    print(f"\n  Fetchujem props ({len(events)} utakmica)...")
    all_players = {}
    raw_data    = []

    for i, ev in enumerate(events):
        event_id = ev["id"]
        print(f"  [{i+1}/{len(events)}] ", end="")
        props = fetch_event_props(
            event_id  = event_id,
            event_info= ev,
            bookmaker = args.bookmaker if not args.best_line else None,
        )

        # Merge — ako igrač već postoji, uzmi bolju liniju
        for player, info in props.items():
            if player not in all_players:
                all_players[player] = info
            else:
                # Uzmi bolju over i under kvotu
                existing = all_players[player]
                if info["over_odds"] and (not existing["over_odds"] or info["over_odds"] > existing["over_odds"]):
                    existing["over_odds"] = info["over_odds"]
                if info["under_odds"] and (not existing["under_odds"] or info["under_odds"] > existing["under_odds"]):
                    existing["under_odds"] = info["under_odds"]

        raw_data.append({"event_id": event_id, "data": ev, "props": props})

        if i < len(events) - 1:
            time.sleep(args.delay)

    # Filtriraj po minimalnoj liniji
    before = len(all_players)
    all_players = {
        p: info for p, info in all_players.items()
        if info.get("line") is not None and float(info["line"]) >= args.min_line
    }
    print(f"\n  Filtrirano {before - len(all_players)} igrača (linija < {args.min_line})")
    print(f"  Ukupno igrača s propsom: {len(all_players)}")

    if not all_players:
        print("⚠️  Nema props podataka za danas.")
        sys.exit(0)

    # Step 3: Assign teams
    rows = assign_teams(all_players, events)

    # Step 4: Spremi CSV
    out_full  = os.path.join(DATA_DIR, f"offer_{today}.csv")
    df, clean_path = build_offer_csv(rows, out_full)

    # Spremi raw JSON za backup
    raw_path = os.path.join(DATA_DIR, f"props_raw_{today}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, ensure_ascii=False)

    # Kopiraj clean offer u standardni naziv koji app uvijek gleda
    latest_path = os.path.join(DATA_DIR, "offer_latest.csv")
    import shutil
    shutil.copy(clean_path, latest_path)

    print(f"\n{'='*55}")
    print(f"  ✅ Props snimljeni!")
    print(f"  📄 Full CSV:    {out_full}")
    print(f"  📄 Upload CSV:  {clean_path}")
    print(f"  📄 Latest:      {latest_path}")
    print(f"  📄 Raw JSON:    {raw_path}")
    print(f"  👥 Igrača:      {len(df)}")
    print(f"\n  Preview (prvih 10):")
    print(f"  {'Igrač':<28} {'Linija':>7} {'Over':>7} {'Under':>7}  Meč")
    print(f"  {'-'*60}")
    for _, row in df.head(10).iterrows():
        matchup = f"{row.get('Away','?')} @ {row.get('Home','?')}"
        print(f"  {row['Player']:<28} {row['Line']:>7.1f} {row['Over Odds']:>7.3f} {row['Under Odds']:>7.3f}  {matchup}")
    if len(df) > 10:
        print(f"  ... i još {len(df)-10} igrača")
    print(f"{'='*55}")
    print(f"\n  ➡️  Uploaduj {os.path.basename(clean_path)} u app.py")

if __name__ == "__main__":
    main()