def add_confidence_boost(df_results):

    if "Confidence" not in df_results.columns:
        return df_results

    if "Heat Status" not in df_results.columns:
        return df_results

    if "Model Pick" not in df_results.columns:
        return df_results

    boosted_confidence = []

    for _, row in df_results.iterrows():

        base_conf = row["Confidence"]
        heat = row["Heat Status"]
        pick = row["Model Pick"]

        new_conf = base_conf

        # Boost ako OVER + HOT
        if pick == "OVER" and heat == "HOT":
            new_conf = base_conf + 10

        # Boost ako UNDER + COLD
        if pick == "UNDER" and heat == "COLD":
            new_conf = base_conf + 10

        # Cap na 100
        new_conf = min(100, new_conf)

        boosted_confidence.append(round(new_conf, 1))

    df_results["Boosted Confidence"] = boosted_confidence

    return df_results
