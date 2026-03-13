"""refresh_matchups.py - NBA def/off matchup CSV refresh."""
import os, time, pandas as pd
SEASON="2025-26"
DATA_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)),"data")
os.makedirs(DATA_DIR,exist_ok=True)
TEAM_ID_TO_ABBR={1610612737:"ATL",1610612738:"BOS",1610612751:"BKN",1610612766:"CHA",1610612741:"CHI",1610612739:"CLE",1610612742:"DAL",1610612743:"DEN",1610612765:"DET",1610612744:"GSW",1610612745:"HOU",1610612754:"IND",1610612746:"LAC",1610612747:"LAL",1610612763:"MEM",1610612748:"MIA",1610612749:"MIL",1610612750:"MIN",1610612740:"NOP",1610612752:"NYK",1610612753:"ORL",1610612755:"PHI",1610612756:"PHX",1610612757:"POR",1610612758:"SAC",1610612759:"SAS",1610612760:"OKC",1610612761:"TOR",1610612762:"UTA",1610612764:"WAS"}
def get_team_df(measure,prefix=""):
      from nba_api.stats.endpoints import leaguedashteamstats
      time.sleep(1.2)
      ep=leaguedashteamstats.LeagueDashTeamStats(season=SEASON,measure_type_detailed_defense=measure,per_mode_simple="PerGame",timeout=60)
      df=ep.get_data_frames()[0]
      if df.empty: return None
            r={}
    for c in df.columns:
              cu=c.upper()
              if cu in["TEAM_ABBREVIATION","TEAM_ABBR"]: r[c]="TEAM_ABBR"
elif cu=="TEAM_ID": r[c]="TEAM_ID"
elif cu=="TEAM_NAME": r[c]="TEAM_NAME"
    df=df.rename(columns=r)
    if "TEAM_ABBR" not in df.columns and "TEAM_ID" in df.columns:
              df["TEAM_ABBR"]=pd.to_numeric(df["TEAM_ID"],errors="coerce").map(TEAM_ID_TO_ABBR)
          if prefix:
                    pr={}
                    for c in df.columns:
                                  if c not in["TEAM_ABBR","TEAM_NAME","TEAM_ID"]: pr[c]=prefix+c
                                            df=df.rename(columns=pr)
                          return df
def main():
      print("[refresh_matchups] Start...")
    try:
              df=get_team_df("Opponent","OPP_")
        if df is not None:
                      p=os.path.join(DATA_DIR,f"def_matchup_{SEASON}.csv")
                      df.to_csv(p,index=False)
                      print(f"[refresh_matchups] DEF saved {len(df)} -> {p}")
except Exception as e:
        print(f"[refresh_matchups] DEF error: {e}")
    try:
              df=get_team_df("Base")
        if df is not None:
                      p=os.path.join(DATA_DIR,f"off_matchup_{SEASON}.csv")
                      df.to_csv(p,index=False)
                      print(f"[refresh_matchups] OFF saved {len(df)} -> {p}")
except Exception as e:
        print(f"[refresh_matchups] OFF error: {e}")
    print("[refresh_matchups] Gotovo!")
if __name__=="__main__":
      main()
