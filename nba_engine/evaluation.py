"""Ocjena modela: poređenje predikcija sa stvarnim rezultatima, profit, ocjena A–F, poređenje dva modela."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .utils import normalize_name


def load_actual_results_csv(uploaded_file: Any) -> Optional[pd.DataFrame]:
    """CSV stvarnih rezultata: kolone Player i Actual Points (opciono Closing Line / Odds)."""
    if uploaded_file is None:
        return None
    df = pd.read_csv(uploaded_file)
    rename_map: Dict[str, str] = {}
    for c in df.columns:
        cl = c.lower().strip()
        if cl in ("player", "player_name", "name"):
            rename_map[c] = "Player"
        elif cl in ("actual points", "actual", "pts", "points"):
            rename_map[c] = "Actual Points"
        elif cl in ("closing line", "close line", "line close"):
            rename_map[c] = "Closing Line"
        elif cl in ("closing over odds", "close over odds"):
            rename_map[c] = "Closing Over Odds"
        elif cl in ("closing under odds", "close under odds"):
            rename_map[c] = "Closing Under Odds"
    df = df.rename(columns=rename_map)
    if "Player" not in df.columns or "Actual Points" not in df.columns:
        raise ValueError("Results CSV mora imati kolone Player i Actual Points.")
    df["NAME_KEY"] = df["Player"].astype(str).map(normalize_name)
    df["Actual Points"] = pd.to_numeric(df["Actual Points"], errors="coerce")
    for c in ("Closing Line", "Closing Over Odds", "Closing Under Odds"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def load_prediction_results_csv(uploaded_file: Any) -> Optional[pd.DataFrame]:
    """CSV predikcija drugog modela (Player, Line, Over Odds, Under Odds, Final Projection, Model Pick)."""
    if uploaded_file is None:
        return None
    df = pd.read_csv(uploaded_file)
    rename_map: Dict[str, str] = {}
    for c in df.columns:
        cl = c.lower().strip()
        if cl in ("player", "player_name", "name"):
            rename_map[c] = "Player"
        elif cl in ("line", "market line", "prop line"):
            rename_map[c] = "Line"
        elif cl in ("over odds", "overodds", "odds_over"):
            rename_map[c] = "Over Odds"
        elif cl in ("under odds", "underodds", "odds_under"):
            rename_map[c] = "Under Odds"
        elif cl in ("final projection", "projection", "proj"):
            rename_map[c] = "Final Projection"
        elif cl in ("model pick", "pick", "bet", "side"):
            rename_map[c] = "Model Pick"
        elif cl in ("projection edge", "edge"):
            rename_map[c] = "Projection Edge"
    df = df.rename(columns=rename_map)
    required = ("Player", "Line", "Over Odds", "Under Odds", "Final Projection", "Model Pick")
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Second model CSV missing columns: {missing}")
    return df


def settle_pick(model_pick: str, line_val: float, actual_pts: float) -> str:
    if pd.isna(actual_pts) or pd.isna(line_val):
        return "NO_BET"
    if model_pick == "OVER":
        return "WIN" if actual_pts > line_val else ("LOSS" if actual_pts < line_val else "PUSH")
    if model_pick == "UNDER":
        return "WIN" if actual_pts < line_val else ("LOSS" if actual_pts > line_val else "PUSH")
    return "NO_BET"


def calculate_bet_profit(result: str, odds: float, stake: float = 1.0) -> float:
    if pd.isna(odds):
        return 0.0
    if result == "WIN":
        return stake * (float(odds) - 1.0)
    if result == "LOSS":
        return -stake
    return 0.0


def calculate_clv(row: Any) -> Optional[float]:
    """Closing line value: koliko se linija pomjerila u korist našeg izbora."""
    if "Closing Line" not in row or pd.isna(row.get("Closing Line")):
        return None
    open_line = row.get("Line", np.nan)
    close_line = row.get("Closing Line", np.nan)
    pick = row.get("Model Pick", "")
    if pd.isna(open_line) or pd.isna(close_line):
        return None
    if pick == "OVER":
        return float(close_line - open_line)
    if pick == "UNDER":
        return float(open_line - close_line)
    return None


def evaluate_engine(pred_df: pd.DataFrame, actual_df: pd.DataFrame, stake: float = 1.0,
                    model_name: str = "Model") -> Tuple[pd.DataFrame, Dict]:
    pred = pred_df.copy()
    pred["NAME_KEY"] = pred["Player"].astype(str).map(normalize_name)
    merged = pred.merge(actual_df, on="NAME_KEY", how="left", suffixes=("", "_ACT"))
    merged["Bet Result"] = merged.apply(
        lambda r: settle_pick(r.get("Model Pick", ""), r.get("Line"), r.get("Actual Points")), axis=1)
    merged["Used Odds"] = merged.apply(
        lambda r: r.get("Over Odds") if r.get("Model Pick") == "OVER"
        else (r.get("Under Odds") if r.get("Model Pick") == "UNDER" else np.nan), axis=1)
    merged["Profit"] = merged.apply(
        lambda r: calculate_bet_profit(r.get("Bet Result", ""), r.get("Used Odds", np.nan), stake), axis=1)
    proj = pd.to_numeric(merged["Final Projection"], errors="coerce")
    actual = pd.to_numeric(merged["Actual Points"], errors="coerce")
    merged["Abs Error"] = (proj - actual).abs()
    merged["Sq Error"] = (proj - actual) ** 2
    merged["CLV"] = merged.apply(calculate_clv, axis=1)
    graded = merged[merged["Model Pick"].isin(("OVER", "UNDER"))].copy()
    graded_non_push = graded[graded["Bet Result"].isin(("WIN", "LOSS"))].copy()
    total_bets = len(graded_non_push)
    wins = int((graded_non_push["Bet Result"] == "WIN").sum())
    losses = int((graded_non_push["Bet Result"] == "LOSS").sum())
    pushes = int((graded["Bet Result"] == "PUSH").sum())
    accuracy = wins / total_bets * 100.0 if total_bets > 0 else 0.0
    total_profit = float(graded["Profit"].sum())
    total_staked = float(total_bets * stake)
    roi = total_profit / total_staked * 100.0 if total_staked > 0 else 0.0

    def _sm(s):
        d = s.dropna()
        return float(d.mean()) if not d.empty else None

    mae = _sm(graded["Abs Error"])
    sq_vals = graded["Sq Error"].dropna()
    rmse = float(np.sqrt(sq_vals.mean())) if not sq_vals.empty else None
    avg_edge = _sm(graded["Projection Edge"]) if "Projection Edge" in graded.columns else None
    avg_clv = _sm(graded["CLV"])
    summary = {
        "Model": model_name, "Bets": total_bets, "Wins": wins, "Losses": losses, "Pushes": pushes,
        "Accuracy %": round(accuracy, 2), "Profit": round(total_profit, 2), "ROI %": round(roi, 2),
        "MAE": round(mae, 3) if mae is not None else None,
        "RMSE": round(rmse, 3) if rmse is not None else None,
        "Avg Projection Edge": round(avg_edge, 3) if avg_edge is not None else None,
        "Avg CLV": round(avg_clv, 3) if avg_clv is not None else None,
    }
    return merged, summary


def grade_engine(summary: Dict) -> str:
    acc = float(summary.get("Accuracy %", 0) or 0)
    roi = float(summary.get("ROI %", 0) or 0)
    mae = float(summary.get("MAE", 999) or 999)
    clv = float(summary.get("Avg CLV", 0) or 0)
    score = 0
    if acc >= 57:
        score += 4
    elif acc >= 54:
        score += 3
    elif acc >= 51:
        score += 2
    elif acc >= 48:
        score += 1
    if roi >= 8:
        score += 4
    elif roi >= 5:
        score += 3
    elif roi >= 2:
        score += 2
    elif roi > 0:
        score += 1
    if mae <= 3.0:
        score += 4
    elif mae <= 4.0:
        score += 3
    elif mae <= 5.0:
        score += 2
    elif mae <= 6.0:
        score += 1
    if clv >= 0.75:
        score += 3
    elif clv >= 0.30:
        score += 2
    elif clv > 0:
        score += 1
    if score >= 13:
        return "A"
    if score >= 10:
        return "B"
    if score >= 7:
        return "C"
    if score >= 4:
        return "D"
    return "F"


def compare_two_models(summary_a: Dict, summary_b: Dict) -> Tuple[str, pd.DataFrame]:
    def _f(d, k, fb):
        return float(d.get(k, fb) or fb)
    roi_a, roi_b = _f(summary_a, "ROI %", 0), _f(summary_b, "ROI %", 0)
    acc_a, acc_b = _f(summary_a, "Accuracy %", 0), _f(summary_b, "Accuracy %", 0)
    mae_a, mae_b = _f(summary_a, "MAE", 999), _f(summary_b, "MAE", 999)
    if roi_a > roi_b:
        winner = summary_a["Model"]
    elif roi_b > roi_a:
        winner = summary_b["Model"]
    elif acc_a > acc_b:
        winner = summary_a["Model"]
    elif acc_b > acc_a:
        winner = summary_b["Model"]
    elif mae_a < mae_b:
        winner = summary_a["Model"]
    elif mae_b < mae_a:
        winner = summary_b["Model"]
    else:
        winner = "TIE"
    return winner, pd.DataFrame([summary_a, summary_b])
