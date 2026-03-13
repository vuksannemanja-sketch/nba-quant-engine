"""refresh_h2h.py - NBA H2H statistike (player game log vs opponent team)."""
import os, time
import pandas as pd
SEASON="2025-26"
DATA_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)),"data")
os.makedirs(DATA_DIR,exist_ok=True)
def get_players_df():
      from nba_api.stats.endpoints import leaguedashplayerstats
      time.sleep(1.0)
      ep=leaguedashplayerstats.LeagueDashPlayerStats(season=SEASON,measure_type_detailed_defense="Base",per_mode_simple="PerGame",timeout=60)
      return ep.get_data_frames()[0]
  def get_game_log(player_id):
        from nba_api.stats.endpoints import playergamelog
        time.sleep(0.7)
        ep=playergamelog.PlayerGameLog(player_id=player_id,season=SEASON,season_type_all_star="Regular Season",timeout=60)
        return ep.get_data_frames()[0]
    def extract_opp(s):
          s=str(s)
          if "vs." in s: return s.split("vs.")[-1].strip()
                if "@" in s: return s.split("@")[-1].strip()
                      return s.strip()
def main():
      print("[refresh_h2h] Start...")
    base=get_players_df()
    if base.empty:
              print("[refresh_h2h] Nema igraca"); return
          id_col=next((c for c in base.columns if c.upper()=="PLAYER_ID"),None)
    name_col=next((c for c in base.columns if c.upper() in["PLAYER_NAME","PLAYER"]),None)
    min_col=next((c for c in base.columns if c.upper()=="MIN"),None)
    if not id_col:
              print("[refresh_h2h] No PLAYER_ID col"); return
          if min_col:
                    base=base[pd.to_numeric(base[min_col],errors="coerce").fillna(0)>=15]
                id_to_name=dict(zip(base[id_col].astype(int),base[name_col].astype(str))) if name_col else {}
    pids=base[id_col].dropna().astype(int).tolist()
    print(f"[refresh_h2h] {len(pids)} igraca")
    rows=[]
    for i,pid in enumerate(pids):
              try:
                            gl=get_game_log(pid)
                            if gl.empty: continue
                                          matchup_col=next((c for c in gl.columns if c.upper()=="MATCHUP"),None)
                            pts_col=next((c for c in gl.columns if c.upper()=="PTS"),None)
                            if not matchup_col or not pts_col: continue
                                          gl["OPP_TEAM"]=gl[matchup_col].apply(extract_opp)
                            gl[pts_col]=pd.to_numeric(gl[pts_col],errors="coerce")
                            gl=gl.dropna(subset=[pts_col])
                            pname=id_to_name.get(pid,str(pid))
                            for opp,grp in gl.groupby("OPP_TEAM"):
                                              pts=grp[pts_col].tolist()
                                              rows.append({"PLAYER_NAME":pname,"OPP_TEAM":opp,"H2H_PTS_AVG":round(sum(pts)/len(pts),2),"H2H_GAMES":len(pts),"H2H_PTS_LAST":pts[0]})
              except Exception as e:
                            if i<3: print(f"[refresh_h2h] pid {pid}: {e}")
                                      if (i+1)%50==0: print(f"[refresh_h2h] {i+1}/{len(pids)}...")
                                            if not rows:
                                                      print("[refresh_h2h] Nema H2H podataka"); return
                                                  df=pd.DataFrame(rows)
                    p=os.path.join(DATA_DIR,f"h2h_{SEASON}.csv")
    df.to_csv(p,index=False)
    print(f"[refresh_h2h] Saved {len(df)} rows -> {p}")
if __name__=="__main__":
      main()
