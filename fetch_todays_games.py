import os, json, datetime, urllib.request, subprocess, sys, ssl

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

SEASON = "2025-26"

TEAM_MAP = {
        "ATL": "ATL", "BOS": "BOS", "BKN": "BKN", "CHA": "CHA", "CHI": "CHI",
        "CLE": "CLE", "DAL": "DAL, "DEN": "DEN", "DET": "DET", "GSW": "GSW",
        "HOU": "HOU", "IND": "IND", "LAC": "LAC", "LAL": "LAL", "MEM": "MEM",
        "MIA": "MIA", "MIL": "MIL", "MIN": "MIN", "NOP": "NOP", "NYK": "NYK",
        "ORL": "ORL", "PHI": "PHI", "PHX": "PHX", "POR": "POR", "SAC": "SAC",
        "SAS": "SAS", "OKC": "OKC", "TOR": "TOR", "UTA": "UTA", "WAS": "WAS",
        # Full names
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
        # Short aliases
        "NO": "NOP", "GS": "GSW", "SA": "SAS", "NY": "NYK",
        "BRK": "BKN", "BKN": "BKN", "NJN": "BKN",
        "NOH": "NOP", "NOK": "NOP",
        "SEA": "OKC", "VAN": "MEM",
        "NJ": "BKN", "GS": "GSW",
}

HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def hget(url, t=15):
        try:
                    req = urllib.request.Request(url, headers=HDR)
                    ctx = ssl._create_unverified_context()
                with urllib.request.urlopen(req, timeout=t, context=ctx) as r:
                                    return json.loads(r.read().decode())
        except Exception as e:
                    print(f"[fetch] {url}: {e}")
                    return None


def abbr(x):
        if not x:
                    return ""
                x = x.strip()
    return TEAM_MAP.get(x, TEAM_MAP.get(x.upper(), x.upper()[:3]))


def espn_games():
        d = datetime.date.today().strftime("%Y%m%d")
    data = hget(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}&limit=20")
    if not data:
                return []
            out = []
    for ev in data.get("events", []):
                comp = ev.get("competitions", [{}])[0]
                cps = comp.get("competitors", [])
                if len(cps) < 2:
                                continue
                            hm = aw = None
        for c in cps:
                        a = abbr(c.get("team", {}).get("abbreviation", ""))
                        if c.get("homeAway") == "home":
                                            hm = a
else:
                aw = a
        if hm and aw:
                        total = None
                        for o in comp.get("odds", []):
                                            v = o.get("overUnder") or o.get("total")
                                            if v:
                                                                    try:
                                                                                                total = float(v)
except Exception:
                        pass
                    break
            out.append({"home": hm, "away": aw, "total": total})
    return out


def nba_games():
        data = hget("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json", t=10)
    if not data:
                return []
    out = []
    for g in data.get("scoreboard", {}).get("games", []):
                h = abbr(g.get("homeTeam", {}).get("teamTricode", ""))
        a = abbr(g.get("awayTeam", {}).get("teamTricode", ""))
        if h and a:
                        out.append({"home": h, "away": a, "total": None})
                return out


def ensure_fresh_csv():
        """Osvjezi players CSV ako ne postoji ili je stariji od 20 sati."""
    csv_candidates = [
                os.path.join(DATA_DIR, f"players_{SEASON}.csv"),
                os.path.join(DATA_DIR, f"players_{SEASON}_base.csv"),
    ]
    refresh_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refresh_data.py")

    needs_refresh = True
    for csv_path in csv_candidates:
                if os.path.exists(csv_path):
                                age_h = (datetime.datetime.now() - datetime.datetime.fromtimestamp(
                                                    os.path.getmtime(csv_path))).total_seconds() / 3600
                                if age_h < 20:
                                                    needs_refresh = False
                                                    print(f"[fetch_todays_games] CSV svjez ({age_h:.1f}h star): {csv_path}")
                                                    break
    else:
                print(f"[fetch_todays_games] CSV zastario ({age_h:.1f}h): {csv_path}")

    if needs_refresh:
                if os.path.exists(refresh_py):
                                print(f"[fetch_todays_games] Pokrecemo refresh_data.py ...")
                                try:
                                                    result = subprocess.run(
                                                                            [sys.executable, refresh_py],
                                                                            timeout=120,
                                                                            capture_output=True,
                                                                            text=True
                                                    )
                                                    if result.returncode == 0:
                                                                            print(f"[fetch_todays_games] refresh_data.py OK")
                                else:
                                                        print(f"[fetch_todays_games] refresh_data.py greska: {result.stderr[:300]}")
except subprocess.TimeoutExpired:
                print("[fetch_todays_games] refresh_data.py timeout (120s)")
except Exception as e:
                print(f"[fetch_todays_games] refresh_data.py exception: {e}")
else:
            print(f"[fetch_todays_games] refresh_data.py nije pronadjen: {refresh_py}")


def players_for(home, away):
        """Vraca listu igraca za dvije ekipe iz lokalnog CSV-a."""
    import pandas as pd

    home_u = home.strip().upper()
    away_u = away.strip().upper()

    csv_candidates = [
                os.path.join(DATA_DIR, f"players_{SEASON}.csv"),
                os.path.join(DATA_DIR, f"players_{SEASON}_base.csv"),
    ]

    for fn in csv_candidates:
                if not os.path.exists(fn):
                                print(f"[fetch_todays_games] players_for: CSV ne postoji: {fn}")
                                continue

        try:
                        df = pd.read_csv(fn)
except Exception as e:
            print(f"[fetch_todays_games] players_for: greska citanja {fn}: {e}")
            continue

        # Normalizuj nazive kolona
        cm = {}
        for c in df.columns:
                        cu = c.upper().strip()
                        if cu in ("PLAYER_NAME", "PLAYER"):
                                            cm[c] = "PLAYER_NAME"
elif cu in ("TEAM_ABBREVIATION", "TEAM_ABBR"):
                cm[c] = "TEAM_ABBR"
elif cu == "MIN":
                cm[c] = "MIN"
elif cu == "PTS":
                cm[c] = "PTS"
        df = df.rename(columns=cm)
        df = df.loc[:, ~df.columns.duplicated()]

        if "TEAM_ABBR" not in df.columns:
                        print(f"[fetch_todays_games] players_for: nema TEAM_ABBR u {fn}")
                        continue

        df["TEAM_ABBR"] = df["TEAM_ABBR"].astype(str).str.strip().str.upper()

        # DEBUG: prikazi koje ekipe su u CSV-u za ovaj par
        teams_in_csv = set(df["TEAM_ABBR"].unique())
        print(f"[fetch_todays_games] players_for {home_u}@{away_u}: trazim u {len(df)} redova, dostupne ekipe (uzorak): {sorted(teams_in_csv)[:10]}")

        mask = df["TEAM_ABBR"].isin([home_u, away_u])
        filtered = df[mask].copy()

        if filtered.empty:
                        # Pokusaj fuzzy match - mozda je skracenica malo drugacija
                        alt_home = TEAM_MAP.get(home_u, home_u)
                        alt_away = TEAM_MAP.get(away_u, away_u)
                        mask2 = df["TEAM_ABBR"].isin([alt_home, alt_away])
                        filtered = df[mask2].copy()
                        if not filtered.empty:
                                            print(f"[fetch_todays_games] players_for: fuzzy match {home_u}->{alt_home}, {away_u}->{alt_away}")

                    if filtered.empty:
                                    print(f"[fetch_todays_games] players_for: nema igrace za {home_u}/{away_u} u {fn}")
                                    continue

        if "MIN" in filtered.columns:
                        filtered["MIN"] = pd.to_numeric(filtered["MIN"], errors="coerce").fillna(0)
                        filtered = filtered[filtered["MIN"] >= 15]

        if "PTS" in filtered.columns:
                        filtered["PTS"] = pd.to_numeric(filtered["PTS"], errors="coerce").fillna(0)
                        filtered = filtered.sort_values("PTS", ascending=False)

        result = [
                        {
                                            "name": str(r.get("PLAYER_NAME", "")).strip(),
                                            "pts": float(r.get("PTS", 0) or 0),
                                            "team": str(r.get("TEAM_ABBR", "")).upper().strip(),
                        }
                        for _, r in filtered.iterrows()
                        if str(r.get("PLAYER_NAME", "")).strip() and float(r.get("PTS", 0) or 0) > 0
        ]

        print(f"[fetch_todays_games] players_for {home_u}@{away_u}: pronadeno {len(result)} igraca")
        return result

    print(f"[fetch_todays_games] players_for {home_u}@{away_u}: nema CSV-a s igracima!")
    return []


def to_line(pts):
        if pts <= 0:
                    return None
                return max(round(pts * 2) / 2.0, 0.5)


def fetch_and_save():
        today = datetime.date.today().strftime("%Y-%m-%d")
    print(f"[fetch_todays_games] Datum: {today}")

    # Korak 1: Osvjezi CSV s igracima ako je potrebno
    ensure_fresh_csv()

    # Korak 2: Dohvati danasnje utakmice
    games = espn_games()
    if games:
                print(f"[fetch_todays_games] ESPN: {len(games)} utakmica")
else:
        print("[fetch_todays_games] ESPN nije vratio utakmice, probavam NBA CDN...")
        games = nba_games()
        if games:
                        print(f"[fetch_todays_games] NBA CDN: {len(games)} utakmica")

    # Sacuvaj utakmice u JSON
    games_path = os.path.join(DATA_DIR, "todays_games.json")
    with open(games_path, "w", encoding="utf-8") as f:
                json.dump({"date": today, "games": games}, f, indent=2)

    if not games:
                print("[fetch_todays_games] Nema meceva danas")
        offer_path = os.path.join(DATA_DIR, "todays_offer.txt")
        with open(offer_path, "w", encoding="utf-8") as f:
                        f.write(f"# Nema meceva {today}\n")
                    return 0, []

    print(f"[fetch_todays_games] Ukupno utakmica: {len(games)}")
    for g in games:
                print(f"  - {g['away']}@{g['home']} (total: {g.get('total')})")

    # Korak 3: Generiraj ponudu za svakog igraca
    rows = []
    for g in games:
                ps = players_for(g["home"], g["away"])
        if not ps:
                        print(f"[fetch_todays_games] UPOZORENJE: nema igraca za {g['away']}@{g['home']}")
                        continue
                    for p2 in ps:
                                    ln = to_line(p2["pts"])
                                    if ln is None:
                                                        continue
                                                    opp = g["home"] if p2["team"] == g["away"] else g["away"]
            ts = f",{g['total']:.1f}" if g.get("total") else ""
            rows.append(f"{p2['name']},{ln},1.909,1.909,{opp}{ts}")

    # Korak 4: Zapisi offer fajl
    offer_path = os.path.join(DATA_DIR, "todays_offer.txt")
    hdr = f"# NBA ponuda {today} | " + (", ".join(f"{g['away']}@{g['home']}" for g in games))
    with open(offer_path, "w", encoding="utf-8") as f:
                f.write(hdr + "\n")
        for r in rows:
                        f.write(r + "\n")

    print(f"[fetch_todays_games] {len(rows)} redova -> {offer_path}")

    if len(rows) == 0:
                print("[fetch_todays_games] KRITICAN PROBLEM: 0 redova generisano!")
        print("[fetch_todays_games] Provjerite da li players_2025-26.csv postoji u data/ folderu")
        print(f"[fetch_todays_games] DATA_DIR = {DATA_DIR}")
        csv_check = os.path.join(DATA_DIR, f"players_{SEASON}.csv")
        if os.path.exists(csv_check):
                        import pandas as pd
            df = pd.read_csv(csv_check)
            print(f"[fetch_todays_games] CSV postoji, {len(df)} redova, kolone: {list(df.columns)}")
            if "TEAM_ABBREVIATION" in df.columns or "TEAM_ABBR" in df.columns:
                                col = "TEAM_ABBREVIATION" if "TEAM_ABBREVIATION" in df.columns else "TEAM_ABBR"
                print(f"[fetch_todays_games] Timovi u CSV-u: {sorted(df[col].unique().tolist())}")
else:
            print(f"[fetch_todays_games] CSV NE POSTOJI: {csv_check}")

    return len(rows), games


if __name__ == "__main__":
        c, g = fetch_and_save()
    print(f"[fetch_todays_games] Gotovo! {c} redova, {len(g)} meceva.")
