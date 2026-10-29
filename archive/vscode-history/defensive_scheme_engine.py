import numpy as np

def add_defensive_scheme_adjustment(df_results):

    df_results = df_results.copy()

    if "NET_RATING" not in df_results.columns:
        return df_results

    for idx, row in df_results.iterrows():
        try:
            net = abs(row.get("NET_RATING", 0))

            if net > 10:
                df_results.at[idx, "Final Projection"] *= 0.95
            elif net < -5:
                df_results.at[idx, "Final Projection"] *= 1.05

        except:
            continue

    return df_results
