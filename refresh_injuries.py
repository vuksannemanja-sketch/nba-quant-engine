"""
refresh_injuries.py - Povlaci NBA povrede i cuva kao CSV.
"""
import os, time, pandas as pd

SEASON = "2025-26"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

TEAM_ID_TO_ABBR = {
      1610612737:"ATL",1610612738:"BOS",1610612751:"BKN",1610612766:"CHA",
      1610612741:"CHI",1610612739:"CLE",1610612742:"DAL",1610612743:"DEN",
      1610612765:"DET",1610612744:"GSW",1610612745:"HOU",1610612754:"IND",
      1610612746:"LAC",1610612747:"LAL",1610612763:"MEM",1610612748:"MIA",
      1610612749:"MIL",1610612750:"MIN",1610612740:"NOP",1610612752:"NYK",
      1610612753:"ORL",1610612755:"PHI",1610612756:"PHX",1610612757:"POR",
      1610612758:"SAC",1610612759:"SAS",1610612760:"OKC",1610612761:"TOR",
      1610612762:"UTA",1610612764:"WAS",
}

def fetch_injuries_nba_api():
      try:
                from nba_api.stats.endpoints import playerstatus
                time.sleep(1.0)
                ep = playerstatus.PlayerStatus(season_year=SEASON, league_id="00", timeout=60)
                df = ep.get_data_frames()[0]
                if df.empty:
                              return None
                          rename = {}
                for c in df.columns:
                              cu = c.upper()
                              if cu in ["PLAYER_NAME","DISPLAY_FIRST_LAST"]: rename[c] = "PLAYER"
elif cu == "TEAM_ID": rename[c] = "TEAM_ID"
elif cu in ["TEAM_ABBREVIATION","TEAM_ABBR"]: rename[c] = "TEAM_ABBR"
elif cu in ["INJURY_STATUS","GAME_STATUS_TEXT","STATUS","COMMENT"]: rename[c] = "DESCRIPTION"
        df = df.rename(columns=rename)
        if "TEAM_ABBR" not in df.columns and "TEAM_ID" in df.columns:
                      df["TEAM_ABBR"] = pd.to_numeric(df["TEAM_ID"], errors="coerce").map(TEAM_ID_TO_ABBR)
                  if "PLAYER" not in df.columns:
                                return None
                            if "DESCRIPTION" in df.columns:
                                          df = df[df["DESCRIPTION"].astype(str).str.strip() != ""].copy()
                                      cols = [c for c in ["PLAYER","TEAM_ABBR","DESCRIPTION"] if c in df.columns]
        return df[cols].copy()
except Exception as e:
        print(f"[refresh_injuries] NBA API error: {e}")
        return None

def fetch_injuries_espn():
      try:
                import urllib.request, json
                url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
                req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                              data = json.loads(r.read().decode())
                          rows = []
                for t in data.get("injuries", []):
                              abbr = t.get("team", {}).get("abbreviation", "")
                              for inj in t.get("injuries", []):
                                                name = inj.get("athlete", {}).get("displayName", "")
                                                status = inj.get("status", "")
                                                desc = inj.get("type", {}).get("description", status)
                                                comment = inj.get("longComment", "")
                                                full = f"{desc} - {comment}".strip(" -") if comment else desc
                                                rows.append({"PLAYER": name, "TEAM_ABBR": abbr, "DESCRIPTION": full})
                                        return pd.DataFrame(rows) if rows else None
      except Exception as e:
                print(f"[refresh_injuries] ESPN error: {e}")
                return None

  def main():
        print("[refresh_injuries] Start...")
        df = fetch_injuries_nba_api()
        if df is None or df.empty:
                  print("[refresh_injuries] Fallback na ESPN...")
                  df = fetch_injuries_espn()
              if df is None or df.empty:
                        print("[refresh_injuries] Nema podataka.")
                        return
                    path = os.path.join(DATA_DIR, f"injuries_{SEASON}.csv")
    df.to_csv(path, index=False)
    print(f"[refresh_injuries] Saved {len(df)} rows -> {path}")

if __name__ == "__main__":
      main()
