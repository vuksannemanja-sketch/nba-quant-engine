def filter_hot_overs(df_results):

    if "Model Pick" not in df_results.columns:
        return df_results

    if "Heat Status" not in df_results.columns:
        return df_results

    filtered_df = df_results[
        (df_results["Model Pick"] == "OVER") &
        (df_results["Heat Status"] == "HOT")
    ].copy()

    return filtered_df
