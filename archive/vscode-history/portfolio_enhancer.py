def add_market_sharpness(df_results):
    sharp_scores = []

    for _, row in df_results.iterrows():
        over_odds = row.get("Over Odds", None)
        under_odds = row.get("Under Odds", None)

        if not over_odds or not under_odds:
            sharp_scores.append(0)
            continue

        implied_total = (1/over_odds) + (1/under_odds)
        vig = implied_total - 1

        sharpness = max(0, min(100, (1 - vig) * 100))
        sharp_scores.append(round(sharpness, 1))

    df_results["Market Sharpness"] = sharp_scores
    return df_results


def portfolio_risk_control(df_results, bankroll=1000, max_portfolio_exposure=0.25):
    total_stake = df_results["Stake €"].sum()

    if total_stake == 0:
        return df_results

    max_allowed = bankroll * max_portfolio_exposure

    if total_stake > max_allowed:
        scale_factor = max_allowed / total_stake
        df_results["Stake €"] = df_results["Stake €"] * scale_factor

    return df_results
from portfolio_enhancer import add_market_sharpness, portfolio_risk_control
import pandas as pd

# Initialize df_results with your data before calling the functions
df_results = pd.read_csv('your_file.csv')  # Load your data here

if df_results is not None and len(df_results) > 0:
    df_results = add_market_sharpness(df_results)
    df_results = portfolio_risk_control(df_results)

    print("\n=== ENHANCED PORTFOLIO ===")
    print(df_results)
else:
    print("Error: df_results is not defined or empty. Please load your data first.")
