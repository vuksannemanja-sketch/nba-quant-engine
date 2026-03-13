import os,json,datetime,urllib.request
DATA_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)),"data")
os.makedirs(DATA_DIR,exist_ok=True)
TEAM_MAP={"ATL":"ATL","BOS":"BOS","BKN":"BKN","CHA":"CHA","CHI":"CHI","CLE":"CLE","DAL":"DAL","DEN":"DEN","DET":"DET","GSW":"GSW","HOU":"HOU","IND":"IND","LAC":"LAC","LAL":"LAL","MEM":"MEM","MIA":"MIA","MIL":"MIL","MIN":"MIN","NOP":"NOP","NYK":"NYK","ORL":"ORL","PHI":"PHI","PHX":"PHX","POR":"POR","SAC":"SAC","SAS":"SAS","OKC":"OKC","TOR":"TOR","UTA":"UTA","WAS":"WAS","Atlanta Hawks":"ATL","Boston Celtics":"BOS","Brooklyn Nets":"BKN","Charlotte Hornets":"CHA","Chicago Bulls":"CHI","Cleveland Cavaliers":"CLE","Dallas Mavericks":"DAL","Denver Nuggets":"DEN","Detroit Pistons":"DET","Golden State Warriors":"GSW","Houston Rockets":"HOU","Indiana Pacers":"IND","Los Angeles Clippers":"LAC","LA Clippers":"LAC","Los Angeles Lakers":"LAL","Memphis Grizzlies":"MEM","Miami Heat":"MIA","Milwaukee Bucks":"MIL","Minnesota Timberwolves":"MIN","New Orleans Pelicans":"NOP","New York Knicks":"NYK","Orlando Magic":"ORL","Philadelphia 76ers":"PHI","Phoenix Suns":"PHX","Portland Trail Blazers":"POR","Sacramento Kings":"SAC","San Antonio Spurs":"SAS","Oklahoma City Thunder":"OKC","Toronto Raptors":"TOR","Utah Jazz":"UTA","Washington Wizards":"WAS","NO":"NOP","GS":"GSW","SA":"SAS","NY":"NYK"}
HDR={"User-Agent":"Mozilla/5.0","Accept":"application/json"}
def hget(url,t=15):
    try:
        req=urllib.request.Request(url,headers=HDR)
        with urllib.request.urlopen(req,timeout=t) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[fetch] {url}: {e}");return None
def abbr(x):
    return TEAM_MAP.get(x,TEAM_MAP.get(x.strip(),x.strip().upper()[:3]))
def espn_games():
    d=datetime.date.today().strftime("%Y%m%d")
    data=hget(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}&limit=20")
    if not data:return[]
    out=[]
    for ev in data.get("events",[]):
        comp=ev.get("competitions",[{}])[0]
        cps=comp.get("competitors",[])
        if len(cps)<2:continue
        hm=aw=None
        for c in cps:
            a=abbr(c.get("team",{}).get("abbreviation",""))
            if c.get("homeAway")=="home":hm=a
            else:aw=a
        if hm and aw:
            total=None
            for o in comp.get("odds",[]):
                v=o.get("overUnder") or o.get("total")
                if v:
                    try:total=float(v)
                    except:pass
                    break
            out.append({"home":hm,"away":aw,"total":total})
    return out
def nba_games():
    data=hget("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json",t=10)
    if not data:return[]
    out=[]
    for g in data.get("scoreboard",{}).get("games",[]):
        h=abbr(g.get("homeTeam",{}).get("teamTricode",""))
        a=abbr(g.get("awayTeam",{}).get("teamTricode",""))
        if h and a:out.append({"home":h,"away":a,"total":None})
    return out
def players_for(home,away):
    import pandas as pd
    s="2025-26"
    for fn in[f"players_{s}.csv",f"players_{s}_base.csv"]:
        p=os.path.join(DATA_DIR,fn)
        if os.path.exists(p):
            df=pd.read_csv(p)
            cm={}
            for c in df.columns:
                cu=c.upper()
                if cu in["PLAYER_NAME","PLAYER"]:cm[c]="PLAYER_NAME"
                elif cu in["TEAM_ABBREVIATION","TEAM_ABBR"]:cm[c]="TEAM_ABBR"
                elif cu=="MIN":cm[c]="MIN"
                elif cu=="PTS":cm[c]="PTS"
            df=df.rename(columns=cm)
            if "TEAM_ABBR" not in df.columns:continue
            df["TEAM_ABBR"]=df["TEAM_ABBR"].astype(str).str.upper()
            df=df[df["TEAM_ABBR"].isin([home.upper(),away.upper()])].copy()
            if "MIN" in df.columns:
                df["MIN"]=pd.to_numeric(df["MIN"],errors="coerce").fillna(0)
                df=df[df["MIN"]>=15]
            if "PTS" in df.columns:
                df["PTS"]=pd.to_numeric(df["PTS"],errors="coerce").fillna(0)
                df=df.sort_values("PTS",ascending=False)
            return[{"name":str(r.get("PLAYER_NAME","")).strip(),"pts":float(r.get("PTS",0) or 0),"team":str(r.get("TEAM_ABBR","")).upper()} for _,r in df.iterrows() if str(r.get("PLAYER_NAME","")).strip() and float(r.get("PTS",0) or 0)>0]
    return[]
def to_line(pts):
    if pts<=0:return None
    return max(round(pts*2)/2.0,0.5)
def fetch_and_save():
    today=datetime.date.today().strftime("%Y-%m-%d")
    print(f"[fetch_todays_games] {today}")
    games=espn_games() or nba_games()
    p=os.path.join(DATA_DIR,"todays_games.json")
    with open(p,"w") as f:
        json.dump({"date":today,"games":games},f,indent=2)
    if not games:
        print("[fetch_todays_games] Nema meceva")
        with open(os.path.join(DATA_DIR,"todays_offer.txt"),"w") as f:
            f.write(f"# Nema meceva {today}\n")
        return 0,[]
    print(f"[fetch_todays_games] {len(games)} meceva")
    rows=[]
    for g in games:
        ps=players_for(g["home"],g["away"])
        for p2 in ps:
            ln=to_line(p2["pts"])
            if ln is None:continue
            opp=g["home"] if p2["team"]==g["away"] else g["away"]
            ts=f",{g['total']:.1f}" if g.get("total") else ""
            rows.append(f"{p2['name']},{ln},1.909,1.909,{opp}{ts}")
    out_path=os.path.join(DATA_DIR,"todays_offer.txt")
    hdr=f"# NBA ponuda {today} | "+(", ".join(f"{g['away']}@{g['home']}" for g in games))
    with open(out_path,"w",encoding="utf-8") as f:
        f.write(hdr+"\n")
        for r in rows:
            f.write(r+"\n")
    print(f"[fetch_todays_games] {len(rows)} redova -> {out_path}")
    return len(rows),games
if __name__=="__main__":
    c,g=fetch_and_save()
    print(f"[fetch_todays_games] Gotovo! {c} redova, {len(g)} meceva.")
