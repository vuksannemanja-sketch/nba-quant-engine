import pandas as pd

def add_vegas_blending(df_results, vegas_total=None):

    df_results = df_results.copy()

    if vegas_total is None:
        return df_results

    # Pretpostavka: prosjek NBA total ~ 228
    league_avg_total = 228

    total_factor = vegas_total / league_avg_total if league_avg_total else 1

    # Blending 70% model + 30% market
    for idx, row in df_results.iterrows():
        try:
            model_proj = row["Final Projection"]
            market_proj = model_proj * total_factor

            blended = (0.7 * model_proj) + (0.3 * market_proj)

            df_results.at[idx, "Final Projection"] = blended

        except:
            continue

    return df_results
