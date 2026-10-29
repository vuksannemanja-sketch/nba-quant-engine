def rank_top_picks(df_results, top_n=3):

    if "Boosted Confidence" not in df_results.columns:
        return df_results

    if "Best EV %" not in df_results.columns:
        return df_results

    ranking_df = df_results.copy()

    # Normalizacija EV (da bude 0-100 skala)
    max_ev = ranking_df["Best EV %"].max()
    min_ev = ranking_df["Best EV %"].min()

    if max_ev != min_ev:
        ranking_df["EV Score"] = (
            (ranking_df["Best EV %"] - min_ev) /
            (max_ev - min_ev)
        ) * 100
    else:
        ranking_df["EV Score"] = 50

    # Institutional Score kombinacija
    ranking_df["Institutional Score"] = (
        0.6 * ranking_df["Boosted Confidence"] +
        0.4 * ranking_df["EV Score"]
    )

    ranking_df = ranking_df.sort_values(
        "Institutional Score",
        ascending=False
    )

    top_picks = ranking_df.head(top_n)

    return top_picks
