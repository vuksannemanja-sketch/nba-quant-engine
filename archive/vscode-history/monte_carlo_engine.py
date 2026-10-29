import numpy as np

def run_monte_carlo_portfolio(df_results, simulations=10000):

    if "Stake €" not in df_results.columns:
        return None

    profits = []

    for _ in range(simulations):

        total_profit = 0

        for _, row in df_results.iterrows():

            stake = row["Stake €"]
            prob_over = row["P Over %"] / 100
            prob_under = row["P Under %"] / 100
            pick = row["Model Pick"]

            if stake == 0 or pick == "NO VALUE":
                continue

            if pick == "OVER":
                win = np.random.rand() < prob_over
                odds = row["Over Odds"]
            else:
                win = np.random.rand() < prob_under
                odds = row["Under Odds"]

            if win:
                total_profit += stake * (odds - 1)
            else:
                total_profit -= stake

        profits.append(total_profit)

    profits = np.array(profits)

    expected_profit = profits.mean()
    risk_std = profits.std()
    prob_positive = np.mean(profits > 0) * 100

    return {
        "Expected Profit": round(expected_profit, 2),
        "Risk (Std Dev)": round(risk_std, 2),
        "Probability Profit %": round(prob_positive, 2)
    }
