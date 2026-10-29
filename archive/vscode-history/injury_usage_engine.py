import streamlit as st
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os

from nba_api.stats.endpoints import (
    playergamelog,
    leaguedashplayerstats,
    leaguedashteamstats
)
from nba_api.stats.static import players

from momentum_engine import add_momentum_metrics
from confidence_boost import add_confidence_boost
from ranking_engine import rank_top_picks
from monte_carlo_engine import run_monte_carlo_portfolio
from institutional_engine import add_institutional_layer
from opponent_adjustment import add_opponent_defense_adjustment

st.set_page_config(page_title="NBA Quant Engine", layout="wide")
st.title("🏀 NBA Quant Engine Dashboard")

season = "2025-26"

# =====================================================
# ADVANCED HISTORY CENTER
# =====================================================

history_folder = os.path.join(os.getcwd(), "history")
os.makedirs(history_folder, exist_ok=True)

st.markdown("## 📂 History Center")

txt_files = sorted(
    [f for f in os.listdir(history_folder) if f.endswith(".txt")],
    reverse=True
)

if txt_files:
    selected_file = st.selectbox("Select saved analysis file:", txt_files)
    if selected_file:
        file_path = os.path.join(history_folder, selected_file)
        with open(file_path, "r", encoding="utf-8") as f:
            st.text_area("File Content", f.read(), height=350)
else:
    st.info("No saved TXT history files yet.")

# =====================================================
# CACHE
# =====================================================

@st.cache_data(ttl=300)
def get_player_gamelog_cached(player_id, season):
    return playergamelog.PlayerGameLog(
        player_id=player_id,
        season=season
    ).get_data_frames()[0]

@st.cache_data(ttl=300)
def get_full_gamelog(player_id, season):
    return playergamelog.PlayerGameLog(
        player_id=player_id,
        season=season
    ).get_data_frames()[0]

@st.cache_data(ttl=300)
def get_injury_data():
    injury_map = {}
    try:
        url = "https://www.espn.com/nba/injuries"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cols = row.find_all("td")
                if len(cols) >= 3:
                    injury_map[cols[0].get_text(strip=True).lower()] = cols[2].get_text(strip=True).lower()
    except:
        pass
    return injury_map

@st.cache_data(ttl=600)
def get_team_stats(season):
    df = leaguedashteamstats.LeagueDashTeamStats(
        season=season
    ).get_data_frames()[0]
    df["NET_RATING"] = df["OFF_RATING"] - df["DEF_RATING"]
    return df[["TEAM_ID", "NET_RATING"]]

@st.cache_data(ttl=600)
def get_player_advanced_stats(season):
    df = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season
    ).get_data_frames()[0]

    df["POINTS_PER_MIN"] = df["PTS"] / df["MIN"].replace(0, np.nan)

    return df[[
        "PLAYER_ID",
        "MIN",
        "USG_PCT",
        "POINTS_PER_MIN"
    ]]

# =====================================================
# FILE UPLOAD
# =====================================================

st.subheader("📂 Upload Offer (.txt)")
uploaded_txt = st.file_uploader("Upload TXT file", type=["txt"])

df_results = None

if uploaded_txt:

    content = uploaded_txt.read().decode("utf-8")
    lines = content.strip().split("\n")

    portfolio_input = []

    for line in lines:
        parts = line.split(",")
        if len(parts) == 4:
            portfolio_input.append((
                parts[0].strip(),
                float(parts[1]),
                float(parts[2]),
                float(parts[3])
            ))

    results = []

    for name, line, over_odds, under_odds in portfolio_input:

        try:
            player_dict = players.find_players_by_full_name(name)
            if not player_dict:
                continue

            player_id = player_dict[0]["id"]
            gamelog = get_player_gamelog_cached(player_id, season)

            if gamelog.empty:
                continue

            mu = gamelog["PTS"].mean()
            sigma = gamelog["PTS"].std() or 1

            sims = np.random.normal(mu, sigma, 5000)

            p_over = np.mean(sims > line)
            p_under = 1 - p_over

            ev_over = (p_over * over_odds) - 1
            ev_under = (p_under * under_odds) - 1

            if ev_over > ev_under and ev_over > 0:
                pick = "OVER"
                best_ev = ev_over
            elif ev_under > 0:
                pick = "UNDER"
                best_ev = ev_under
            else:
                pick = "NO VALUE"
                best_ev = 0

            results.append({
                "Player": name,
                "Line": line,
                "Projection": mu,
                "Model Pick": pick,
                "Best EV %": best_ev * 100,
            })

        except:
            continue

    df_results = pd.DataFrame(results)

# =====================================================
# ADVANCED ENGINE
# =====================================================

if df_results is not None and not df_results.empty:

    df_results = add_momentum_metrics(df_results)
    df_results = add_confidence_boost(df_results)
    df_results = add_institutional_layer(df_results, season=season)
    df_results = add_opponent_defense_adjustment(df_results, season=season)

    injury_map = get_injury_data()
    df_results["Final Projection"] = df_results["Projection"]

    # =====================================================
    # MINUTES / USAGE / EFFICIENCY ENGINE
    # =====================================================

    try:

        adv_stats = get_player_advanced_stats(season)

        for idx, row in df_results.iterrows():

            player_dict = players.find_players_by_full_name(row["Player"])
            if not player_dict:
                continue

            player_id = player_dict[0]["id"]
            player_row = adv_stats[adv_stats["PLAYER_ID"] == player_id]

            if player_row.empty:
                continue

            season_min = player_row.iloc[0]["MIN"]
            season_usage = player_row.iloc[0]["USG_PCT"]
            ppm = player_row.iloc[0]["POINTS_PER_MIN"]

            gamelog = get_player_gamelog_cached(player_id, season)
            recent = gamelog.sort_values("GAME_DATE", ascending=False).head(5)

            if not recent.empty and season_min > 0:
                recent_min = recent["MIN"].mean()
                minute_factor = min(max(recent_min / season_min, 0.85), 1.25)
            else:
                minute_factor = 1

            usage_factor = 1 + ((season_usage - 20) / 200)

            projected_minutes = season_min * minute_factor
            component_projection = projected_minutes * ppm * usage_factor

            df_results.at[idx, "Projected Minutes"] = round(projected_minutes, 1)
            df_results.at[idx, "Usage %"] = round(season_usage, 1)
            df_results.at[idx, "Points/Min"] = round(ppm, 3)
            df_results.at[idx, "Final Projection"] = component_projection

    except:
        pass

    # =====================================================
    # 🔥 TEammate USAGE BOOST ENGINE (NOVO)
    # =====================================================

    try:

        for injured_name, status in injury_map.items():

            if "out" not in status.lower():
                continue

            injured_dict = players.find_players_by_full_name(injured_name)
            if not injured_dict:
                continue

            injured_id = injured_dict[0]["id"]
            injured_log = get_full_gamelog(injured_id, season)

            if injured_log.empty:
                continue

            injured_log["MIN"] = injured_log["MIN"].fillna(0)
            games_missed = injured_log[
                injured_log["MIN"] == 0
            ]["GAME_DATE"].unique()

            if len(games_missed) < 5:
                continue

            for idx, row in df_results.iterrows():

                teammate_dict = players.find_players_by_full_name(row["Player"])
                if not teammate_dict:
                    continue

                teammate_id = teammate_dict[0]["id"]
                teammate_log = get_full_gamelog(teammate_id, season)

                if teammate_log.empty:
                    continue

                without_games = teammate_log[
                    teammate_log["GAME_DATE"].isin(games_missed)
                ]

                if len(without_games) < 3:
                    continue

                season_min = teammate_log["MIN"].mean()
                season_pts = teammate_log["PTS"].mean()

                min_without = without_games["MIN"].mean()
                pts_without = without_games["PTS"].mean()

                if season_min <= 0 or season_pts <= 0:
                    continue

                minute_factor = min(max(min_without / season_min, 0.85), 1.30)
                scoring_factor = min(max(pts_without / season_pts, 0.85), 1.35)

                df_results.at[idx, "Final Projection"] *= minute_factor
                df_results.at[idx, "Final Projection"] *= scoring_factor

                df_results.at[idx, "Injury Minute Boost"] = round(minute_factor, 2)
                df_results.at[idx, "Injury Usage Boost"] = round(scoring_factor, 2)

    except:
        pass

    # =====================================================
    # TRUE SCORE
    # =====================================================

    def z(series):
        return (series - series.mean()) / (series.std() + 1e-6)

    df_results["EV_z"] = z(df_results["Best EV %"])
    df_results["Vol"] = abs(df_results["Final Projection"] - df_results["Line"])
    df_results["Vol_z"] = z(df_results["Vol"])

    df_results["True Score"] = 0.6 * df_results["EV_z"] - 0.2 * df_results["Vol_z"]
    df_results = df_results.sort_values("True Score", ascending=False)

    st.subheader("📊 Full Portfolio")
    st.dataframe(df_results)

    st.subheader("🔥 TOP 3")
    st.dataframe(df_results.head(3))

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filepath = os.path.join(history_folder, f"analysis_{timestamp}.txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(df_results.to_string())

else:
    st.info("Upload a file to start analysis.")
