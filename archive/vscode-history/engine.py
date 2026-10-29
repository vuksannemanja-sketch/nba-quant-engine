# ============================================
# QUANT ENGINE 3.0 – FULL TWO-SIDED PORTFOLIO
# ============================================

import pandas as pd
import numpy as np
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players
import warnings
warnings.filterwarnings("ignore")

print("=== ENGINE 3.0 – FULL PORTFOLIO (OVER & UNDER) ===")

# ==============================
# SETTINGS
# ==============================
bankroll = 1000
season = "2023-24"

# ==============================
# INPUT
# ==============================
portfolio_input = [
    ("Bruce Brown Jr", 7.5, 1.97, 1.77),
    ("Tim Hardaway Jr", 12.5, 1.77, 1.97),
    ("Nikola Jokic", 24.5, 1.80, 1.92),
    ("Jamal Murray", 22.5, 1.80, 1.92),
    ("Jalen Pickett", 4.5, 1.86, 1.86),
    ("Peyton Watson", 16.5, 1.83, 1.87),
    ("OG Anunoby", 17.5, 1.99, 1.73),
    ("Mikal Bridges", 14.5, 1.97, 1.77),
    ("Jalen Brunson", 25.5, 1.80, 1.92),
    ("Miles McBride", 10.5, 1.86, 1.86),
    ("Mitchell Robinson", 4.5, 1.86, 1.86),
    ("Landry Shamet", 8.5, 1.97, 1.77),
    ("Karl-Anthony Towns", 19.5, 1.97, 1.77)
]

results = []

# ==============================
# MAIN LOOP
# ==============================
for name, line, over_odds, under_odds in portfolio_input:
    
    try:
        player_dict = players.find_players_by_full_name(name)
        if len(player_dict) == 0:
            print(f"⚠️ Nije pronađen: {name}")
            continue

        player_id = player_dict[0]['id']
        gamelog = playergamelog.PlayerGameLog(player_id=player_id, season=season)
        df = gamelog.get_data_frames()[0]

        if df.empty:
            print(f"⚠️ Nema podataka za: {name}")
            continue

        df = df.sort_values("GAME_DATE", ascending=False)

        pts = df["PTS"]
        mu = pts.mean()
        sigma = pts.std()

        sims = np.random.normal(mu, sigma, 10000)

        p_over = np.mean(sims > line)
        p_under = 1 - p_over

        implied_over = 1 / over_odds
        implied_under = 1 / under_odds

        ev_over = (p_over * over_odds) - 1
        ev_under = (p_under * under_odds) - 1

        if ev_over > ev_under and ev_over > 0:
            model_pick = "OVER"
            best_prob = p_over
            best_odds = over_odds
            best_ev = ev_over
        elif ev_under > 0:
            model_pick = "UNDER"
            best_prob = p_under
            best_odds = under_odds
            best_ev = ev_under
        else:
            model_pick = "NO VALUE"
            best_prob = 0
            best_odds = 0
            best_ev = 0

        if best_odds > 1:
            b = best_odds - 1
            kelly = ((b * best_prob) - (1 - best_prob)) / b
            kelly = max(0, kelly)
        else:
            kelly = 0

        stake = bankroll * (kelly / 2)

        cv = sigma / mu if mu != 0 else 0
        confidence = max(0, min(100, (1 - cv) * 100))

        results.append({
            "Player": name,
            "Line": line,
            "Projection": round(mu,2),
            "Over Odds": over_odds,
            "Under Odds": under_odds,
            "P Over %": round(p_over*100,2),
            "P Under %": round(p_under*100,2),
            "Model Pick": model_pick,
            "Best EV %": round(best_ev*100,2),
            "Stake €": round(stake,2),
            "Confidence": round(confidence,1)
        })

    except Exception as e:
        print(f"⚠️ Greška za {name}: {e}")
        continue

# ==============================
# OUTPUT
# ==============================
if len(results) == 0:
    print("Nema validnih rezultata.")
else:
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values("Best EV %", ascending=False)

    # ==============================
    # ENHANCEMENT MODULE
    # ==============================

    def add_market_sharpness(df_results):
        sharp_scores = []
        for _, row in df_results.iterrows():
            over_odds = row["Over Odds"]
            under_odds = row["Under Odds"]
            implied_total = (1/over_odds) + (1/under_odds)
            vig = implied_total - 1
            sharpness = max(0, min(100, (1 - vig) * 100))
            sharp_scores.append(round(sharpness, 1))
        df_results["Market Sharpness"] = sharp_scores
        return df_results


    def portfolio_risk_control(df_results, bankroll=1000, max_portfolio_exposure=0.25):
        total_stake = df_results["Stake €"].sum()
        max_allowed = bankroll * max_portfolio_exposure
        if total_stake > max_allowed and total_stake > 0:
            scale_factor = max_allowed / total_stake
            df_results["Stake €"] = df_results["Stake €"] * scale_factor
        return df_results


    df_results = add_market_sharpness(df_results)
    df_results = portfolio_risk_control(df_results)

    print("\n==============================")
    print("ENHANCED INSTITUTIONAL PORTFOLIO")
    print("==============================")
    print(df_results)

    total_stake = df_results["Stake €"].sum()
    avg_ev = df_results["Best EV %"].mean()

    print("\n==============================")
    print("PORTFOLIO SUMMARY")
    print("==============================")
    print("Ukupan stake:", round(total_stake,2), "€")
    print("Prosječni Best EV:", round(avg_ev,2), "%")
from form_engine import add_recent_form

df_results = add_recent_form(df_results)

print("\n=== WITH RECENT FORM (10G) ===")
print(df_results)
from momentum_engine import add_momentum_metrics

df_results = add_momentum_metrics(df_results)

print("\n=== WITH MOMENTUM ANALYSIS ===")
print(df_results)
from smart_filter import filter_hot_overs

filtered_results = filter_hot_overs(df_results)

print("\n=== SMART FILTER: HOT OVERS ONLY ===")
print(filtered_results)
from confidence_boost import add_confidence_boost

df_results = add_confidence_boost(df_results)

print("\n=== WITH CONFIDENCE BOOST ===")
print(df_results)
from monte_carlo_engine import run_monte_carlo_portfolio

mc_results = run_monte_carlo_portfolio(df_results)

print("\n=== MONTE CARLO PORTFOLIO SIMULATION ===")
print(mc_results)
