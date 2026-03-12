import os
import re
import time
import subprocess
import sys
import difflib
import unicodedata
import numpy as np
import pandas as pd
import streamlit as st

SEASON = "2025-26"
DATA_DIR_CANDIDATES = [
    os.path.join(os.getcwd(), "data"),
    "/mnt/data",
    os.getcwd(),
]
DATA_DIR = next((p for p in DATA_DIR_CANDIDATES if os.path.isdir(p)), os.getcwd())

PLAYER_MAIN_CANDIDATES = [os.path.join(DATA_DIR, "players_2025-26.csv"), os.path.join(DATA_DIR, f"players_{SEASON}.csv")]
PLAYER_BASE_CANDIDATES = [os.path.join(DATA_DIR, "players_2025-26_base.csv"), os.path.join(DATA_DIR, f"players_{SEASON}_base.csv")]
PLAYER_ADV_CANDIDATES  = [os.path.join(DATA_DIR, "players_2025-26_advanced.csv"), os.path.join(DATA_DIR, f"players_{SEASON}_advanced.csv")]
PLAYER_MISC_CANDIDATES = [os.path.join(DATA_DIR, "players_2025-26_misc.csv"), os.path.join(DATA_DIR, f"players_{SEASON}_misc.csv")]
TEAM_CSV_CANDIDATES    = [os.path.join(DATA_DIR, "teams_2025-26.csv"), os.path.join(DATA_DIR, f"teams_{SEASON}.csv"), os.path.join(DATA_DIR, "timovi_2025-26.csv")]
INJ_CSV_CANDIDATES     = [os.path.join(DATA_DIR, "injuries_2025-26.csv"), os.path.join(DATA_DIR, f"injuries_{SEASON}.csv"), os.path.join(DATA_DIR, "injuries.csv"), os.path.join(DATA_DIR, "ozljede.csv")]
PLAYER_MAIN_CSV = next((p for p in PLAYER_MAIN_CANDIDATES if os.path.exists(p)), None)
PLAYER_BASE_CSV = next((p for p in PLAYER_BASE_CANDIDATES if os.path.exists(p)), None)
PLAYER_ADV_CSV  = next((p for p in PLAYER_ADV_CANDIDATES  if os.path.exists(p)), None)
PLAYER_MISC_CSV = next((p for p in PLAYER_MISC_CANDIDATES if os.path.exists(p)), None)
TEAM_CSV        = next((p for p in TEAM_CSV_CANDIDATES    if os.path.exists(p)), None)
INJ_CSV         = next((p for p in INJ_CSV_CANDIDATES     if os.path.exists(p)), None)
H2H_CSV         = next((p for p in [os.path.join(DATA_DIR, "h2h_2025-26.csv"), os.path.join(DATA_DIR, f"h2h_{SEASON}.csv")] if os.path.exists(p)), None)
L10_CSV         = next((p for p in [os.path.join(DATA_DIR, "form_l10_2025-26.csv"), os.path.join(DATA_DIR, f"form_l10_{SEASON}.csv")] if os.path.exists(p)), None)
DEF_MATCHUP_CSV = next((p for p in [os.path.join(DATA_DIR, "def_matchup_2025-26.csv"), os.path.join(DATA_DIR, f"def_matchup_{SEASON}.csv")] if os.path.exists(p)), None)
OFF_MATCHUP_CSV = next((p for p in [os.path.join(DATA_DIR, "off_matchup_2025-26.csv"), os.path.join(DATA_DIR, f"off_matchup_{SEASON}.csv")] if os.path.exists(p)), None)

TEAM_ID_TO_ABBR = {
    1610612737: "ATL", 1610612738: "BOS", 1610612751: "BKN", 1610612766: "CHA",
    1610612741: "CHI", 1610612739: "CLE", 1610612742: "DAL", 1610612743: "DEN",
    1610612765: "DET", 1610612744: "GSW", 1610612745: "HOU", 1610612754: "IND",
    1610612746: "LAC", 1610612747: "LAL", 1610612763: "MEM", 1610612748: "MIA",
    1610612749: "MIL", 1610612750: "MIN", 1610612740: "NOP", 1610612752: "NYK",
    1610612753: "ORL", 1610612755: "PHI", 1610612756: "PHX", 1610612757: "POR",
    1610612758: "SAC", 1610612759: "SAS", 1610612760: "OKC", 1610612761: "TOR",
    1610612762: "UTA", 1610612764: "WAS",
}
ABBR_TO_TEAM_ID = {v: k for k, v in TEAM_ID_TO_ABBR.items()}
TEAM_NAME_TO_ABBR = {
    "atlanta hawks": "ATL", "boston celtics": "BOS", "brooklyn nets": "BKN",
    "charlotte hornets": "CHA", "chicago bulls": "CHI", "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL", "denver nuggets": "DEN", "detroit pistons": "DET",
    "golden state warriors": "GSW", "houston rockets": "HOU", "indiana pacers": "IND",
    "los angeles clippers": "LAC", "la clippers": "LAC", "los angeles lakers": "LAL",
    "memphis grizzlies": "MEM", "miami heat": "MIA", "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN", "new orleans pelicans": "NOP",
    "new york knicks": "NYK", "orlando magic": "ORL", "philadelphia 76ers": "PHI",
    "phoenix suns": "PHX", "portland trail blazers": "POR", "sacramento kings": "SAC",
    "san antonio spurs": "SAS", "oklahoma city thunder": "OKC",
    "toronto raptors": "TOR", "utah jazz": "UTA", "washington wizards": "WAS",
}

st.set_page_config(page_title="NBA Quant Engine", layout="wide")
st.title("🏀 NBA Quant Engine – 2025-26")

def normalize_name(s: str) -> str:
    if s is None:
        return ""
    s = str(s).strip().strip('"').strip("'").replace("\xa0", " ")
    if any(x in s for x in ("Ã", "Ä", "Å", "Ð", "Þ", "â", "€", "™")):
        try:
            s2 = s.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
            if s2.strip():
                s = s2
        except Exception:
            pass
    s = s.lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def safe_float(x):
    try:
        s = str(x).strip().replace('"', "").replace(",", ".")
        if s == "":
            return None
        return float(s)
    except Exception:
        return None

def smart_decode(b: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig"):
        try:
            s = b.decode(enc)
            if s and s.strip():
                return s
        except Exception:
            pass
    for enc in ("utf-16", "utf-16le", "utf-16be", "cp1252", "latin-1"):
        try:
            s = b.decode(enc)
            if s and s.strip():
                return s
        except Exception:
            pass
    return b.decode("utf-8", errors="ignore")

def getfloat(obj, col, default=None):
    try:
        v = obj.get(col, default) if hasattr(obj, "get") else default
        if pd.isna(v):
            return default
        v = float(v)
        if not np.isfinite(v):
            return default
        return v
    except Exception:
        return default

def _clamp(x, lo, hi):
    try:
        return max(lo, min(hi, float(x)))
    except Exception:
        return (lo + hi) / 2.0

def zscore(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    return (s - s.mean()) / (s.std() + 1e-6)

def normalize_team_abbr(val):
    if pd.isna(val):
        return np.nan
    s = str(val).strip()
    if not s:
        return np.nan
    s_up = s.upper()
    if s_up in ABBR_TO_TEAM_ID:
        return s_up
    try:
        team_num = int(float(s))
        if team_num in TEAM_ID_TO_ABBR:
            return TEAM_ID_TO_ABBR[team_num]
    except Exception:
        pass
    s_key = s.lower().strip()
    if s_key in TEAM_NAME_TO_ABBR:
        return TEAM_NAME_TO_ABBR[s_key]
    return np.nan

def extract_injury_status(desc: str) -> str:
    s = str(desc or "").strip().lower()
    if "out for season" in s:
        return "OUT"
    if re.search(r"\bout\b", s):
        return "OUT"
    if "questionable" in s:
        return "QUESTIONABLE"
    if "doubtful" in s:
        return "DOUBTFUL"
    if "day to day" in s or "day-to-day" in s:
        return "QUESTIONABLE"
    if "inactive" in s:
        return "INACTIVE"
    if "probable" in s:
        return "PROBABLE"
    return "UNKNOWN"

def statusweight(s: str) -> float:
    s = (s or "").strip().upper()
    if s in ("OUT", "INACTIVE"):
        return 1.0
    if s == "DOUBTFUL":
        return 0.75
    if s == "QUESTIONABLE":
        return 0.40
    if s == "PROBABLE":
        return 0.15
    return 0.0

def fix_usg_scale(df: pd.DataFrame) -> pd.DataFrame:
    if "USG_PCT" not in df.columns:
        return df
    mean_usg = pd.to_numeric(df["USG_PCT"], errors="coerce").dropna().mean()
    if pd.notna(mean_usg) and mean_usg < 2.0:
        df = df.copy()
        df["USG_PCT"] = pd.to_numeric(df["USG_PCT"], errors="coerce") * 100.0
    return df

def compute_per_player_bm_offset(season_pts: float) -> float:
    league_avg = 9.0
    base_offset = season_pts * 0.05
    regression_factor = 1.0 - 0.3 * max(0.0, (season_pts - league_avg) / max(season_pts, 1.0))
    return float(np.clip(base_offset * regression_factor, 0.2, 3.5))

def compute_max_edge(line_val: float, usg: float = 20.0, sigma: float = 6.0) -> float:
    base = np.clip(line_val * 0.16, 2.0, 7.0)
    usg_mult   = np.clip(1.0 + 0.015 * (usg   - 20.0), 0.85, 1.25)
    sigma_mult = np.clip(sigma / 6.0,                   0.90, 1.20)
    return float(np.clip(base * usg_mult * sigma_mult, 2.0, 8.5))

def compute_injury_boost_v2(injured_usage_lost, injured_minutes_lost, player_usg, has_star_out, star_usg_lost):
    base = 1.0 + 0.0022 * injured_usage_lost + 0.0012 * injured_minutes_lost
    if has_star_out and star_usg_lost >= 25:
        base += 0.0003 * star_usg_lost
    if player_usg >= 28:
        return float(np.clip(base, 1.0, 1.03))
    elif player_usg >= 22:
        return float(np.clip(base, 1.0, 1.05))
    else:
        return float(np.clip(base, 1.0, 1.07))

def parse_recent_form_input(txt: str) -> dict:
    result = {}
    if not txt or not txt.strip():
        return result
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.rsplit(',', 1)
        if len(parts) != 2:
            continue
        name_raw = parts[0].strip()
        val = safe_float(parts[1].strip())
        if val is None or val <= 0:
            continue
        result[normalize_name(name_raw)] = float(val)
    return result

def parse_offer_text(txt: str):
    rows, bad = [], []
    for raw in txt.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if ("player" in low or "ime" in low) and ("line" in low or "granica" in low):
            continue
        if "\t" in line and line.count("\t") >= 3:
            delim = "\t"
        elif line.count(";") >= 3:
            delim = ";"
        else:
            delim = ","
        parts = [p.strip() for p in line.split(delim)]
        if delim == "," and len(parts) > 6:
            if ";" in line and line.count(";") >= 3:
                parts = [p.strip() for p in line.split(";")]
            elif "\t" in line and line.count("\t") >= 3:
                parts = [p.strip() for p in line.split("\t")]
        if len(parts) not in (4, 5, 6):
            bad.append((raw, f"Wrong number of columns ({len(parts)})"))
            continue
        name = parts[0].strip()
        line_val   = safe_float(parts[1])
        over_odds  = safe_float(parts[2])
        under_odds = safe_float(parts[3])
        if not name or line_val is None or over_odds is None or under_odds is None:
            bad.append((raw, "Cannot parse numeric fields"))
            continue
        opp_team, total_match = None, None
        if len(parts) == 5:
            x = parts[4].strip()
            n = safe_float(x)
            if n is None:
                opp_team = normalize_team_abbr(x)
            else:
                total_match = n
        if len(parts) == 6:
            opp_team    = normalize_team_abbr(parts[4].strip())
            total_match = safe_float(parts[5])
        rows.append((name, float(line_val), float(over_odds), float(under_odds), opp_team, total_match))
    return rows, bad

def load_prediction_results_csv(uploaded_file):
    if uploaded_file is None:
        return None
    pdf = pd.read_csv(uploaded_file)
    rename_map = {}
    for c in pdf.columns:
        cl = c.lower().strip()
        if cl in ["player", "player_name", "name"]:                 rename_map[c] = "Player"
        elif cl in ["line", "market line", "prop line"]:             rename_map[c] = "Line"
        elif cl in ["over odds", "overodds", "odds_over"]:           rename_map[c] = "Over Odds"
        elif cl in ["under odds", "underodds", "odds_under"]:        rename_map[c] = "Under Odds"
        elif cl in ["final projection", "projection", "proj"]:       rename_map[c] = "Final Projection"
        elif cl in ["model pick", "pick", "bet", "side"]:            rename_map[c] = "Model Pick"
        elif cl in ["projection edge", "edge"]:                      rename_map[c] = "Projection Edge"
    pdf = pdf.rename(columns=rename_map)
    required = ["Player", "Line", "Over Odds", "Under Odds", "Final Projection", "Model Pick"]
    missing = [c for c in required if c not in pdf.columns]
    if missing:
        raise ValueError(f"Second model CSV missing columns: {missing}")
    return pdf

def load_actual_results_csv(uploaded_file):
    if uploaded_file is None:
        return None
    actual_df = pd.read_csv(uploaded_file)
    rename_map = {}
    for c in actual_df.columns:
        cl = c.lower().strip()
        if cl in ["player", "player_name", "name"]:                         rename_map[c] = "Player"
        elif cl in ["actual points", "actual", "pts", "points"]:            rename_map[c] = "Actual Points"
        elif cl in ["closing line", "close line", "line close"]:            rename_map[c] = "Closing Line"
        elif cl in ["closing over odds", "close over odds"]:                rename_map[c] = "Closing Over Odds"
        elif cl in ["closing under odds", "close under odds"]:              rename_map[c] = "Closing Under Odds"
    actual_df = actual_df.rename(columns=rename_map)
    if "Player" not in actual_df.columns or "Actual Points" not in actual_df.columns:
        raise ValueError("Results CSV mora imati kolone Player i Actual Points.")
    actual_df["NAME_KEY"] = actual_df["Player"].astype(str).map(normalize_name)
    actual_df["Actual Points"] = pd.to_numeric(actual_df["Actual Points"], errors="coerce")
    for c in ["Closing Line", "Closing Over Odds", "Closing Under Odds"]:
        if c in actual_df.columns:
            actual_df[c] = pd.to_numeric(actual_df[c], errors="coerce")
    return actual_df

def settle_pick(model_pick, line_val, actual_pts):
    if pd.isna(actual_pts) or pd.isna(line_val):
        return "NO_BET"
    if model_pick == "OVER":
        return "WIN" if actual_pts > line_val else "LOSS" if actual_pts < line_val else "PUSH"
    if model_pick == "UNDER":
        return "WIN" if actual_pts < line_val else "LOSS" if actual_pts > line_val else "PUSH"
    return "NO_BET"

def calculate_bet_profit(settle, odds, stake=1.0):
    if pd.isna(odds):
        return 0.0
    if settle == "WIN":
        return stake * (float(odds) - 1.0)
    if settle == "LOSS":
        return -stake
    return 0.0

def calculate_clv(row):
    if "Closing Line" not in row or pd.isna(row.get("Closing Line")):
        return None
    open_line  = row.get("Line", np.nan)
    close_line = row.get("Closing Line", np.nan)
    pick       = row.get("Model Pick", "")
    if pd.isna(open_line) or pd.isna(close_line):
        return None
    if pick == "OVER":
        return float(close_line - open_line)
    if pick == "UNDER":
        return float(open_line - close_line)
    return None

def pick_odds(r):
    if r.get("Model Pick") == "OVER":  return r.get("Over Odds", np.nan)
    if r.get("Model Pick") == "UNDER": return r.get("Under Odds", np.nan)
    return np.nan

def evaluate_engine(pred_df, actual_df, stake=1.0, model_name="Model"):
    pred = pred_df.copy()
    pred["NAME_KEY"] = pred["Player"].astype(str).map(normalize_name)
    merged = pred.merge(actual_df, on="NAME_KEY", how="left", suffixes=("", "_ACT"))
    merged["Bet Result"] = merged.apply(
        lambda r: settle_pick(r.get("Model Pick"), r.get("Line"), r.get("Actual Points")), axis=1
    )
    merged["Used Odds"] = merged.apply(pick_odds, axis=1)
    merged["Profit"]    = merged.apply(
        lambda r: calculate_bet_profit(r.get("Bet Result"), r.get("Used Odds"), stake=stake), axis=1
    )
    merged["Abs Error"] = (
        pd.to_numeric(merged["Final Projection"], errors="coerce") -
        pd.to_numeric(merged["Actual Points"],    errors="coerce")
    ).abs()
    merged["Sq Error"] = (
        pd.to_numeric(merged["Final Projection"], errors="coerce") -
        pd.to_numeric(merged["Actual Points"],    errors="coerce")
    ) ** 2
    merged["CLV"] = merged.apply(calculate_clv, axis=1)
    graded          = merged[merged["Model Pick"].isin(["OVER", "UNDER"])].copy()
    graded_non_push = graded[graded["Bet Result"].isin(["WIN", "LOSS"])].copy()
    total_bets   = len(graded_non_push)
    wins         = int((graded_non_push["Bet Result"] == "WIN").sum())
    losses       = int((graded_non_push["Bet Result"] == "LOSS").sum())
    pushes       = int((graded["Bet Result"] == "PUSH").sum())
    accuracy     = wins / total_bets * 100.0 if total_bets > 0 else 0.0
    total_profit = float(graded["Profit"].sum())
    total_staked = float(len(graded_non_push) * stake)
    roi          = total_profit / total_staked * 100.0 if total_staked > 0 else 0.0
    mae          = float(graded["Abs Error"].dropna().mean()) if not graded["Abs Error"].dropna().empty else np.nan
    rmse         = float(np.sqrt(graded["Sq Error"].dropna().mean())) if not graded["Sq Error"].dropna().empty else np.nan
    avg_edge     = float(graded["Projection Edge"].dropna().mean()) if "Projection Edge" in graded.columns and not graded["Projection Edge"].dropna().empty else np.nan
    avg_clv      = float(graded["CLV"].dropna().mean()) if not graded["CLV"].dropna().empty else np.nan
    summary = {
        "Model": model_name, "Bets": total_bets, "Wins": wins, "Losses": losses,
        "Pushes": pushes, "Accuracy %": round(accuracy, 2), "Profit": round(total_profit, 2),
        "ROI %": round(roi, 2),
        "MAE":  round(mae,  3) if pd.notna(mae)      else None,
        "RMSE": round(rmse, 3) if pd.notna(rmse)     else None,
        "Avg Projection Edge": round(avg_edge, 3) if pd.notna(avg_edge) else None,
        "Avg CLV":             round(avg_clv,  3) if pd.notna(avg_clv)  else None,
    }
    return merged, summary

def grade_engine(summary_dict):
    acc  = float(summary_dict.get("Accuracy %", 0) or 0)
    roi  = float(summary_dict.get("ROI %",       0) or 0)
    mae  = float(summary_dict.get("MAE",        999) or 999)
    clv  = float(summary_dict.get("Avg CLV",     0) or 0)
    score = 0
    if   acc >= 57: score += 4
    elif acc >= 54: score += 3
    elif acc >= 51: score += 2
    elif acc >= 48: score += 1
    if   roi >= 8:  score += 4
    elif roi >= 5:  score += 3
    elif roi >= 2:  score += 2
    elif roi > 0:   score += 1
    if   mae <= 3.0: score += 4
    elif mae <= 4.0: score += 3
    elif mae <= 5.0: score += 2
    elif mae <= 6.0: score += 1
    if   clv >= 0.75: score += 3
    elif clv >= 0.30: score += 2
    elif clv > 0:     score += 1
    if score >= 13: return "A"
    if score >= 10: return "B"
    if score >= 7:  return "C"
    if score >= 4:  return "D"
    return "F"

def compare_two_models(summary_a, summary_b):
    roi_a = float(summary_a.get("ROI %", 0) or 0)
    roi_b = float(summary_b.get("ROI %", 0) or 0)
    acc_a = float(summary_a.get("Accuracy %", 0) or 0)
    acc_b = float(summary_b.get("Accuracy %", 0) or 0)
    mae_a = float(summary_a.get("MAE", 999) or 999)
    mae_b = float(summary_b.get("MAE", 999) or 999)
    if   roi_a > roi_b: winner = summary_a["Model"]
    elif roi_b > roi_a: winner = summary_b["Model"]
    elif acc_a > acc_b: winner = summary_a["Model"]
    elif acc_b > acc_a: winner = summary_b["Model"]
    elif mae_a < mae_b: winner = summary_a["Model"]
    elif mae_b < mae_a: winner = summary_b["Model"]
    else:               winner = "TIE"
    return winner, pd.DataFrame([summary_a, summary_b])

def stdrename(df):
    rename_map = {}
    for c in df.columns:
        cl = c.strip().upper()
        if   cl in ["PLAYER", "PLAYER_NAME", "NAME"]:              rename_map[c] = "PLAYER_NAME"
        elif cl in ["TEAM_ABBR", "TEAM_ABBREVIATION", "TM"]:       rename_map[c] = "TEAM_ABBR"
        elif cl in ["TEAM", "TEAM_NAME"]:                           rename_map[c] = "TEAM"
        elif cl == "TEAM_ID":                                       rename_map[c] = "TEAM_ID"
    df = df.rename(columns=rename_map)
    if "TEAM_ID" in df.columns:
        if "TEAM_ABBR" not in df.columns or df["TEAM_ABBR"].isna().mean() > 0.5:
            df["TEAM_ABBR"] = pd.to_numeric(df["TEAM_ID"], errors="coerce").map(TEAM_ID_TO_ABBR)
    return df

def dedupecols(df):
    return df.loc[:, ~df.columns.duplicated()]

@st.cache_data(ttl=3600)
def load_teams_csv(path: str):
    df = pd.read_csv(path)
    rename_map = {}
    for c in df.columns:
        cl = c.strip().upper()
        if   cl in ["TEAM", "TEAM_NAME", "NAME"]: rename_map[c] = "TEAM_NAME"
        elif cl == "TEAM_ID":                      rename_map[c] = "TEAM_ID"
        elif cl in ["TEAM_ABBR", "TEAM_ABBREVIATION"]: rename_map[c] = "TEAM_ABBR"
    df = df.rename(columns=rename_map)
    for c in ["OFF_RATING", "DEF_RATING", "PACE", "NET_RATING", "PTS", "OPP_PTS"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "TEAM_ID" in df.columns:
        sample_vals = df["TEAM_ID"].dropna().astype(str).str.strip().head(10)
        if len(sample_vals) and sample_vals.str.fullmatch(r"[A-Z]{2,4}").all():
            df["TEAM_ABBR"] = df["TEAM_ID"].astype(str).str.strip().str.upper()
            df["TEAM_NUMERIC_ID"] = df["TEAM_ABBR"].map(ABBR_TO_TEAM_ID)
        else:
            if "TEAM_ABBR" in df.columns:
                df["TEAM_ABBR"] = df["TEAM_ABBR"].map(normalize_team_abbr)
            elif "TEAM_NAME" in df.columns:
                df["TEAM_ABBR"] = df["TEAM_NAME"].map(normalize_team_abbr)
            else:
                df["TEAM_ABBR"] = df["TEAM_ID"].map(normalize_team_abbr)
            df["TEAM_NUMERIC_ID"] = pd.to_numeric(df["TEAM_ID"], errors="coerce").fillna(
                df["TEAM_ABBR"].map(ABBR_TO_TEAM_ID)
            )
    else:
        if "TEAM_ABBR" in df.columns:
            df["TEAM_ABBR"] = df["TEAM_ABBR"].map(normalize_team_abbr)
        elif "TEAM_NAME" in df.columns:
            df["TEAM_ABBR"] = df["TEAM_NAME"].map(normalize_team_abbr)
        else:
            df["TEAM_ABBR"] = np.nan
        df["TEAM_NUMERIC_ID"] = df["TEAM_ABBR"].map(ABBR_TO_TEAM_ID)
    if "NET_RATING" not in df.columns:
        if "OFF_RATING" in df.columns and "DEF_RATING" in df.columns:
            df["NET_RATING"] = df["OFF_RATING"] - df["DEF_RATING"]
        elif "PTS" in df.columns and "OPP_PTS" in df.columns:
            df["NET_RATING"] = df["PTS"] - df["OPP_PTS"]
        else:
            df["NET_RATING"] = 0.0
    return df

@st.cache_data(ttl=3600)
def load_players_merged(main_path, base_path=None, adv_path=None, misc_path=None):
    if main_path is None or not os.path.exists(main_path):
        raise ValueError("Glavni players CSV nije pronađen.")
    def prepare(path, label):
        if path is None or not os.path.exists(path):
            return None
        df = pd.read_csv(path)
        df = stdrename(df)
        df = fix_usg_scale(df)
        df["SRC_" + label] = 1
        if "PLAYER_NAME" not in df.columns:
            return None
        df["NAME_KEY"] = df["PLAYER_NAME"].astype(str).map(normalize_name)
        if "TEAM_ABBR" in df.columns:
            df["TEAM_ABBR"] = df["TEAM_ABBR"].map(normalize_team_abbr)
        elif "TEAM" in df.columns:
            df["TEAM_ABBR"] = df["TEAM"].map(normalize_team_abbr)
        elif "TEAM_ID" in df.columns:
            df["TEAM_ABBR"] = df["TEAM_ID"].map(normalize_team_abbr)
        else:
            df["TEAM_ABBR"] = np.nan
        if "TEAM_ID" in df.columns:
            df["TEAM_NUMERIC_ID"] = pd.to_numeric(df["TEAM_ID"], errors="coerce")
        else:
            df["TEAM_NUMERIC_ID"] = np.nan
        df["TEAM_NUMERIC_ID"] = df["TEAM_NUMERIC_ID"].fillna(df["TEAM_ABBR"].map(ABBR_TO_TEAM_ID))
        return df
    main = prepare(main_path, "MAIN")
    base = prepare(base_path, "BASE")
    adv  = prepare(adv_path,  "ADV")
    misc = prepare(misc_path, "MISC")
    merged = main.copy()
    for extra in [base, adv, misc]:
        if extra is None:
            continue
        join_cols = [c for c in ["NAME_KEY", "PLAYER_ID"] if c in merged.columns and c in extra.columns]
        key = ["PLAYER_ID"] if "PLAYER_ID" in join_cols else ["NAME_KEY"]
        extra = extra.sort_values(key).drop_duplicates(key)
        extra_cols = [c for c in extra.columns if c not in merged.columns or c in [
            "TEAM_ABBR", "TEAM_NUMERIC_ID", "GP", "USG_PCT", "TS_PCT", "EFG_PCT", "FG3A",
            "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE", "PIE",
            "PTS_PAINT", "PTS_FB", "PTS_2ND_CHANCE", "PTS_OFF_TOV", "PFD", "PLUS_MINUS",
            "OPP_PTS_OFF_TOV", "OPP_PTS_2ND_CHANCE", "OPP_PTS_FB", "OPP_PTS_PAINT",
            "AST_RATIO", "AST_TO", "AST_PCT", "TOV_PCT", "FG_PCT", "FG3_PCT", "FT_PCT",
        ]]
        extra_slim = extra[key + [c for c in extra_cols if c not in key]].copy()
        merged = merged.merge(extra_slim, on=key, how="left", suffixes=("", "__X"))
        for c in list(merged.columns):
            if c.endswith("__X"):
                base_col = c[:-3]
                if base_col in merged.columns:
                    merged[base_col] = merged[base_col].combine_first(merged[c])
                    merged.drop(columns=[c], inplace=True)
                else:
                    merged.rename(columns={c: base_col}, inplace=True)
    merged = dedupecols(merged)
    if "PLAYER_NAME" not in merged.columns:
        raise ValueError("players csv missing PLAYER_NAME column.")
    if "MIN" not in merged.columns:
        raise ValueError("players csv missing MIN column.")
    numeric_candidates = [
        "MIN", "PTS", "FGA", "FGM", "FG_PCT", "FG3A", "FG3_PCT", "FTA", "FT_PCT",
        "USG_PCT", "TS_PCT", "EFG_PCT", "TOV_PCT", "TM_TOV_PCT", "TPAR", "FTR",
        "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE", "PIE", "POSS", "AST_PCT",
        "AST_RATIO", "AST_TO", "REB_PCT", "OREB_PCT", "DREB_PCT", "PTS_PAINT",
        "PTS_FB", "PTS_2ND_CHANCE", "PTS_OFF_TOV", "PFD", "PF", "BLK", "BLKA",
        "OPP_PTS_OFF_TOV", "OPP_PTS_2ND_CHANCE", "OPP_PTS_FB", "OPP_PTS_PAINT",
        "PLUS_MINUS", "NBA_FANTASY_PTS", "GP", "W_PCT",
    ]
    for c in numeric_candidates:
        if c in merged.columns:
            merged[c] = pd.to_numeric(merged[c], errors="coerce")
    merged = fix_usg_scale(merged)
    if "FG3A" not in merged.columns or merged["FG3A"].isna().mean() > 0.5:
        if "3PA" in merged.columns:
            merged["FG3A"] = merged.get("FG3A", pd.Series(dtype=float))
            merged["FG3A"] = merged["FG3A"].combine_first(pd.to_numeric(merged["3PA"], errors="coerce"))
        else:
            merged["FG3A"] = np.nan
    merged["TEAM_ABBR"]       = merged["TEAM_ABBR"].map(normalize_team_abbr)
    merged["TEAM_NUMERIC_ID"] = pd.to_numeric(merged["TEAM_NUMERIC_ID"], errors="coerce").fillna(
        merged["TEAM_ABBR"].map(ABBR_TO_TEAM_ID)
    )
    min_safe = pd.to_numeric(merged["MIN"], errors="coerce").replace(0, np.nan)
    merged["PPM"]     = (pd.to_numeric(merged.get("PTS"),  errors="coerce") / min_safe).replace([np.inf, -np.inf], np.nan)
    merged["FGA_PM"]  = (pd.to_numeric(merged.get("FGA"),  errors="coerce") / min_safe).replace([np.inf, -np.inf], np.nan)
    merged["FTA_PM"]  = (pd.to_numeric(merged.get("FTA"),  errors="coerce") / min_safe).replace([np.inf, -np.inf], np.nan)
    merged["FG3A_PM"] = (pd.to_numeric(merged.get("FG3A"), errors="coerce") / min_safe).replace([np.inf, -np.inf], np.nan)
    merged["PFD_PM"]  = (pd.to_numeric(merged.get("PFD"),  errors="coerce") / min_safe).replace([np.inf, -np.inf], np.nan)
    merged["POSS_PM"] = (pd.to_numeric(merged.get("POSS"), errors="coerce") / min_safe).replace([np.inf, -np.inf], np.nan)
    merged["PPM"]     = merged["PPM"].fillna(0.55).clip(0.20, 1.25)
    return merged

def load_injuries_csv(path: str):
    if path is None or not os.path.exists(path):
        return None
    inj_df = pd.read_csv(path)
    rename_map = {}
    for c in inj_df.columns:
        cl = c.strip().upper()
        if   cl in ["PLAYER", "PLAYER_NAME", "NAME"]:      rename_map[c] = "PLAYER"
        elif cl in ["TEAM", "TEAM_NAME"]:                   rename_map[c] = "TEAM"
        elif cl in ["TEAM_ABBR", "TEAM_ABBREVIATION"]:     rename_map[c] = "TEAM_ABBR"
        elif cl in ["DESCRIPTION", "STATUS_NOTE", "NOTE"]: rename_map[c] = "DESCRIPTION"
    inj_df = inj_df.rename(columns=rename_map)
    if "TEAM_ABBR" in inj_df.columns:
        inj_df["TEAM_ABBR"] = inj_df["TEAM_ABBR"].map(normalize_team_abbr)
    elif "TEAM" in inj_df.columns:
        inj_df["TEAM_ABBR"] = inj_df["TEAM"].map(normalize_team_abbr)
    else:
        inj_df["TEAM_ABBR"] = np.nan
    if "STATUS" not in inj_df.columns:
        if "DESCRIPTION" in inj_df.columns:
            inj_df["STATUS"] = inj_df["DESCRIPTION"].astype(str).map(extract_injury_status)
        else:
            inj_df["STATUS"] = "UNKNOWN"
    if "PLAYER" in inj_df.columns:
        inj_df["NAME_KEY"] = inj_df["PLAYER"].astype(str).map(normalize_name)
    return inj_df

def load_l10_csv(path: str):
    if path is None or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        rename = {}
        for c in df.columns:
            cl = c.strip().upper()
            if cl in ["PLAYER_NAME","PLAYER","NAME"]: rename[c] = "PLAYER_NAME"
            elif cl == "L10_PTS":  rename[c] = "L10_PTS"
            elif cl == "L5_PTS":   rename[c] = "L5_PTS"
            elif cl == "L3_PTS":   rename[c] = "L3_PTS"
            elif cl == "L10_MIN":  rename[c] = "L10_MIN"
            elif cl == "L10_STD":  rename[c] = "L10_STD"
            elif cl == "TREND_SLOPE": rename[c] = "TREND_SLOPE"
            elif cl == "LAST_PTS": rename[c] = "LAST_PTS"
        df = df.rename(columns=rename)
        for col in ["L10_PTS","L5_PTS","L3_PTS","L10_MIN","L10_STD","TREND_SLOPE","LAST_PTS"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "PLAYER_NAME" in df.columns:
            df["NAME_KEY"] = df["PLAYER_NAME"].astype(str).map(normalize_name)
        return df
    except Exception:
        return None

def load_def_matchup_csv(path: str):
    if path is None or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if "TEAM_ABBREVIATION" in df.columns:
            df = df.rename(columns={"TEAM_ABBREVIATION": "TEAM_ABBR"})
        if "TEAM_ID" in df.columns and "TEAM_ABBR" not in df.columns:
            df["TEAM_ABBR"] = df["TEAM_ID"].map(TEAM_ID_TO_ABBR)
        for col in df.columns:
            if col not in ["TEAM_ABBR","TEAM_NAME","POSITION","TEAM_ID"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception:
        return None

def load_off_matchup_csv(path: str):
    if path is None or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if "TEAM_ABBREVIATION" in df.columns:
            df = df.rename(columns={"TEAM_ABBREVIATION": "TEAM_ABBR"})
        if "TEAM_ID" in df.columns and "TEAM_ABBR" not in df.columns:
            df["TEAM_ABBR"] = df["TEAM_ID"].map(TEAM_ID_TO_ABBR)
        for col in df.columns:
            if col not in ["TEAM_ABBR","TEAM_NAME","TEAM_ID"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception:
        return None

def load_h2h_csv(path: str):
    if path is None or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        rename_map = {}
        for c in df.columns:
            cl = c.strip().upper()
            if cl in ["PLAYER_NAME", "PLAYER", "NAME"]: rename_map[c] = "PLAYER_NAME"
            elif cl == "OPP_TEAM":                       rename_map[c] = "OPP_TEAM"
            elif cl == "H2H_PTS_AVG":                    rename_map[c] = "H2H_PTS_AVG"
            elif cl == "H2H_GAMES":                      rename_map[c] = "H2H_GAMES"
            elif cl == "H2H_PTS_LAST":                   rename_map[c] = "H2H_PTS_LAST"
        df = df.rename(columns=rename_map)
        for col in ["H2H_PTS_AVG", "H2H_PTS_LAST", "H2H_GAMES"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "PLAYER_NAME" in df.columns:
            df["NAME_KEY"] = df["PLAYER_NAME"].astype(str).map(normalize_name)
        return df
    except Exception:
        return None

def findteam_row_by_abbr(teams_df, abbr: str):
    if not abbr or teams_df is None or teams_df.empty:
        return None
    abbr = str(abbr).strip().upper()
    if "TEAM_ABBR" in teams_df.columns:
        tr = teams_df[teams_df["TEAM_ABBR"].astype(str).str.upper() == abbr]
        if not tr.empty:
            return tr.iloc[0]
    return None

def estimate_match_total(team_row, opp_row, pace_game, teams_df):
    if team_row is None or opp_row is None:
        return None
    league_off = float(pd.to_numeric(teams_df.get("OFF_RATING", pd.Series([115.0])), errors="coerce").dropna().mean() or 115.0)
    league_def = float(pd.to_numeric(teams_df.get("DEF_RATING", pd.Series([115.0])), errors="coerce").dropna().mean() or 115.0)
    if pace_game is None:
        team_pace = getfloat(team_row, "PACE", 99.0)
        opp_pace  = getfloat(opp_row,  "PACE", 99.0)
        pace_game = (team_pace + opp_pace) / 2.0
    team_off = getfloat(team_row, "OFF_RATING", league_off)
    opp_off  = getfloat(opp_row,  "OFF_RATING", league_off)
    team_def = getfloat(team_row, "DEF_RATING", league_def)
    opp_def  = getfloat(opp_row,  "DEF_RATING", league_def)
    base_team_pts = team_off * pace_game / 100.0
    base_opp_pts  = opp_off  * pace_game / 100.0
    team_adj = _clamp(league_def / max(opp_def,  1e-6), 0.92, 1.08)
    opp_adj  = _clamp(league_def / max(team_def, 1e-6), 0.92, 1.08)
    return float(_clamp(base_team_pts * team_adj + base_opp_pts * opp_adj, 180.0, 265.0))

def match_player_row(players_df, offer_name: str):
    name_raw = str(offer_name or "").strip()
    key = normalize_name(name_raw)
    if not key:
        return None, key, "EMPTY_KEY"
    pr = players_df[players_df["NAME_KEY"] == key]
    if not pr.empty:
        pr = pr.sort_values(["MIN", "GP"], ascending=False, na_position="last")
        return pr.iloc[0], key, "EXACT"
    if "," in name_raw:
        nm   = " ".join([p.strip() for p in name_raw.split(",")[::-1]])
        key2 = normalize_name(nm)
        pr   = players_df[players_df["NAME_KEY"] == key2]
        if not pr.empty:
            pr = pr.sort_values(["MIN", "GP"], ascending=False, na_position="last")
            return pr.iloc[0], key2, "LAST_FIRST"
    toks = key.split()
    if len(toks) == 2 and len(toks[0]) == 1:
        fi, ln = toks[0], toks[1]
        pr = players_df[
            players_df["NAME_KEY"].str.contains(rf"\b{re.escape(ln)}\b", na=False) &
            players_df["NAME_KEY"].str.contains(rf"\b{re.escape(fi)}",    na=False)
        ]
        if not pr.empty:
            pr = pr.sort_values(["MIN", "GP"], ascending=False, na_position="last")
            return pr.iloc[0], key, "INITIAL_LAST"
    toks = [t for t in key.split() if len(t) >= 3]
    if toks:
        mask = np.ones(len(players_df), dtype=bool)
        for t in toks:
            mask &= players_df["NAME_KEY"].str.contains(re.escape(t), na=False)
        pr = players_df[mask]
        if not pr.empty:
            pr = pr.sort_values(["MIN", "GP"], ascending=False, na_position="last")
            return pr.iloc[0], key, "TOKENS"
    all_keys = players_df["NAME_KEY"].dropna().astype(str).tolist()
    best = difflib.get_close_matches(key, all_keys, n=1, cutoff=0.86)
    if best:
        pr = players_df[players_df["NAME_KEY"] == best[0]]
        if not pr.empty:
            pr = pr.sort_values(["MIN", "GP"], ascending=False, na_position="last")
            return pr.iloc[0], best[0], "DIFFLIB"
    return None, key, "NOT_FOUND"

def build_player_context(r0, players_df, teams_df, team_row, opp_row, inj_df,
                         team_abbr, player_name_key, total_match_used,
                         recent_form_override=None, h2h_df=None, opp_team_abbr=None,
                         l10_df=None, def_matchup_df=None, off_matchup_df=None,
                         line_val=0.0):
    if recent_form_override is None:
        recent_form_override = {}

    season_pts = float(getfloat(r0, "PTS", 0.0) or 0.0)
    season_min = float(getfloat(r0, "MIN", 0.0) or 0.0)
    usg        = float(getfloat(r0, "USG_PCT", np.nan) or np.nan)
    ppm        = float(getfloat(r0, "PPM", np.nan) or np.nan)
    if not np.isfinite(ppm) or ppm <= 0:
        ppm = season_pts / max(season_min, 1.0)

    if season_min < 20 and np.isfinite(ppm) and ppm > 0.60:
        conservative_ppm = 0.55
        ppm = 0.60 * ppm + 0.40 * conservative_ppm

    league_pace        = float(pd.to_numeric(teams_df.get("PACE",       pd.Series([99.0])),  errors="coerce").dropna().mean() or 99.0)
    league_def         = float(pd.to_numeric(teams_df.get("DEF_RATING", pd.Series([115.0])), errors="coerce").dropna().mean() or 115.0)
    league_off         = float(pd.to_numeric(teams_df.get("OFF_RATING", pd.Series([115.0])), errors="coerce").dropna().mean() or 115.0)
    league_total_proxy = float(pd.to_numeric(teams_df.get("OFF_RATING", pd.Series([115.0])), errors="coerce").dropna().mean() * 2.0 or 230.0)
    league_ts          = float(pd.to_numeric(players_df.get("TS_PCT",   pd.Series([0.56])),  errors="coerce").dropna().mean() or 0.56)
    league_efg         = float(pd.to_numeric(players_df.get("EFG_PCT",  pd.Series([0.54])),  errors="coerce").dropna().mean() or 0.54)
    league_usg         = float(pd.to_numeric(players_df.get("USG_PCT",  pd.Series([20.0])),  errors="coerce").dropna().mean() or 20.0)
    league_fga_pm      = float(pd.to_numeric(players_df.get("FGA_PM",   pd.Series([0.35])),  errors="coerce").dropna().mean() or 0.35)
    league_fta_pm      = float(pd.to_numeric(players_df.get("FTA_PM",   pd.Series([0.12])),  errors="coerce").dropna().mean() or 0.12)
    if league_usg < 5.0:
        league_usg *= 100.0

    team_pace   = getfloat(team_row, "PACE", league_pace) if team_row is not None else league_pace
    opp_pace    = getfloat(opp_row,  "PACE", league_pace) if opp_row  is not None else league_pace
    pace_game   = (team_pace + opp_pace) / 2.0 if opp_row is not None else team_pace
    pace_factor = _clamp(1.0 + 0.08 * ((pace_game / league_pace) - 1.0), 0.94, 1.07)

    team_off         = getfloat(team_row, "OFF_RATING", league_off) if team_row is not None else league_off
    opp_def          = getfloat(opp_row,  "DEF_RATING", league_def) if opp_row  is not None else league_def
    team_eff_matchup = _clamp((team_off / league_off) * (league_def / max(opp_def, 1e-6)), 0.94, 1.08)

    total_factor = 1.0
    if total_match_used is not None and np.isfinite(total_match_used):
        total_factor = _clamp(1.0 + 0.12 * ((float(total_match_used) / league_total_proxy) - 1.0), 0.92, 1.10)

    gp           = getfloat(r0, "GP", 20.0)
    reliability  = _clamp(gp / 25.0, 0.65, 1.0) if gp is not None else 0.8
    minutes_proj = season_min * reliability + season_min * (1.0 - reliability)

    team_net = getfloat(team_row, "NET_RATING", 0.0) if team_row is not None else 0.0
    opp_net  = getfloat(opp_row,  "NET_RATING", 0.0) if opp_row  is not None else 0.0
    mins_context = 1.0
    if team_net is not None and opp_net is not None:
        mins_context = _clamp(1.0 - 0.012 * abs(team_net - opp_net) / 10.0, 0.97, 1.02)

    injury_boost          = 1.0
    direct_player_penalty = 1.0
    injured_usage_lost    = 0.0
    injured_minutes_lost  = 0.0

    if inj_df is not None and team_abbr:
        team_inj = inj_df[inj_df["TEAM_ABBR"].astype(str).str.upper() == str(team_abbr).upper()].copy()
        if not team_inj.empty:
            team_inj["W"] = team_inj["STATUS"].astype(str).map(statusweight).fillna(0.0)
            if "NAME_KEY" in team_inj.columns:
                self_row = team_inj[team_inj["NAME_KEY"] == player_name_key]
                if not self_row.empty:
                    self_w = float(self_row["W"].max())
                    direct_player_penalty = _clamp(1.0 - 0.55 * self_w, 0.35, 1.0)
            teammate_inj = team_inj[team_inj["NAME_KEY"] != player_name_key] if "NAME_KEY" in team_inj.columns else team_inj
            if not teammate_inj.empty and "NAME_KEY" in teammate_inj.columns:
                teammate_pool = players_df[players_df["NAME_KEY"].isin(teammate_inj["NAME_KEY"])]
                if not teammate_pool.empty:
                    temp = teammate_pool[["NAME_KEY", "USG_PCT", "MIN"]].copy()
                    temp = temp.merge(teammate_inj[["NAME_KEY", "W"]], on="NAME_KEY", how="left")
                    injured_usage_lost   = float((temp["USG_PCT"].fillna(0) * temp["W"].fillna(0)).sum())
                    injured_minutes_lost = float((temp["MIN"].fillna(0)     * temp["W"].fillna(0)).sum())
                    if injured_minutes_lost > 200:
                        gp_avg = pd.to_numeric(players_df.get("GP", pd.Series([40])), errors="coerce").dropna().mean() or 40
                        injured_minutes_lost = injured_minutes_lost / max(gp_avg, 1)
                        injured_minutes_lost = float(min(injured_minutes_lost, 190))
                    if injured_usage_lost > 150:
                        injured_usage_lost = float(min(injured_usage_lost, 80))
                    out_mask = team_inj["STATUS"].astype(str).str.upper() == "OUT"
                    out_inj  = team_inj[out_mask]
                    has_star_out  = False
                    star_usg_lost = 0.0
                    if not out_inj.empty and "NAME_KEY" in out_inj.columns:
                        star_pool = players_df[
                            players_df["NAME_KEY"].isin(out_inj["NAME_KEY"]) &
                            (pd.to_numeric(players_df["USG_PCT"], errors="coerce") >= 28)
                        ]
                        if not star_pool.empty:
                            has_star_out  = True
                            star_usg_lost = float(star_pool["USG_PCT"].sum())
                    injury_boost = compute_injury_boost_v2(
                        injured_usage_lost, injured_minutes_lost,
                        usg if np.isfinite(usg) else 20.0,
                        has_star_out, star_usg_lost,
                    )

    minutes_proj = minutes_proj * mins_context * pace_factor
    minutes_proj = minutes_proj * direct_player_penalty
    minutes_proj = minutes_proj * _clamp(1.0 + 0.0004 * injured_minutes_lost, 0.99, 1.04)
    minutes_proj = _clamp(minutes_proj, 8.0, 40.0)
    if season_min >= 34:
        minutes_proj = min(minutes_proj, season_min * 1.02)
    elif season_min >= 28:
        minutes_proj = min(minutes_proj, season_min * 1.04)
    elif season_min >= 20:
        minutes_proj = min(minutes_proj, season_min * 1.06)
    else:
        minutes_proj = min(minutes_proj, season_min * 1.10)
    minutes_proj = _clamp(minutes_proj, 8.0, 40.0)

    if np.isfinite(usg) and league_usg > 0:
        usg_rel   = (usg - league_usg) / league_usg
        usage_adj = _clamp(1.0 + 0.15 * usg_rel, 0.88, 1.15)
    else:
        usage_adj = 1.0
    usage_factor = _clamp(usage_adj, 0.85, 1.15)

    ts        = getfloat(r0, "TS_PCT",    league_ts)
    efg       = getfloat(r0, "EFG_PCT",   league_efg)
    fg_pct    = getfloat(r0, "FG_PCT",    0.46)
    ft_pct    = getfloat(r0, "FT_PCT",    0.76)
    fg3_pct   = getfloat(r0, "FG3_PCT",   0.36)
    fg3a_raw  = getfloat(r0, "FG3A",      None)
    fg3a_pm   = getfloat(r0, "FG3A_PM",   None)
    if fg3a_pm is None or not np.isfinite(fg3a_pm):
        if fg3a_raw is not None and np.isfinite(fg3a_raw) and season_min > 0:
            fg3a_pm = fg3a_raw / season_min
        else:
            fg3a_pm = 0.12
    fga_pm    = getfloat(r0, "FGA_PM",    league_fga_pm)
    fta_pm    = getfloat(r0, "FTA_PM",    league_fta_pm)
    pie       = getfloat(r0, "PIE",       0.08)
    ast_ratio = getfloat(r0, "AST_RATIO", 15.0)
    ast_to    = getfloat(r0, "AST_TO",    1.5)
    tov_pct   = getfloat(r0, "TOV_PCT",   getfloat(r0, "TM_TOV_PCT", 12.0))
    pfd_pm    = getfloat(r0, "PFD_PM",    0.08)
    net_rating_player = getfloat(r0, "NET_RATING", 0.0)
    plus_minus = getfloat(r0, "PLUS_MINUS", 0.0)

    pts_paint   = getfloat(r0, "PTS_PAINT",      None)
    pts_fb      = getfloat(r0, "PTS_FB",         None)
    pts_2nd     = getfloat(r0, "PTS_2ND_CHANCE", None)
    pts_off_tov = getfloat(r0, "PTS_OFF_TOV",    None)
    opp_pts_off_tov_player = getfloat(r0, "OPP_PTS_OFF_TOV",    None)
    opp_pts_2nd_player     = getfloat(r0, "OPP_PTS_2ND_CHANCE", None)
    opp_pts_fb_player      = getfloat(r0, "OPP_PTS_FB",         None)
    opp_pts_paint_player   = getfloat(r0, "OPP_PTS_PAINT",      None)

    league_pts_paint     = float(pd.to_numeric(players_df.get("PTS_PAINT",          pd.Series([4.5])), errors="coerce").dropna().mean() or 4.5)
    league_pts_fb        = float(pd.to_numeric(players_df.get("PTS_FB",             pd.Series([1.5])), errors="coerce").dropna().mean() or 1.5)
    league_pts_2nd       = float(pd.to_numeric(players_df.get("PTS_2ND_CHANCE",     pd.Series([1.2])), errors="coerce").dropna().mean() or 1.2)
    league_pts_off_tov   = float(pd.to_numeric(players_df.get("PTS_OFF_TOV",        pd.Series([2.5])), errors="coerce").dropna().mean() or 2.5)
    league_opp_pts_paint = float(pd.to_numeric(players_df.get("OPP_PTS_PAINT",      pd.Series([4.5])), errors="coerce").dropna().mean() or 4.5)
    league_opp_pts_fb    = float(pd.to_numeric(players_df.get("OPP_PTS_FB",         pd.Series([1.5])), errors="coerce").dropna().mean() or 1.5)
    league_opp_pts_2nd   = float(pd.to_numeric(players_df.get("OPP_PTS_2ND_CHANCE", pd.Series([1.2])), errors="coerce").dropna().mean() or 1.2)

    opp_fg_pct = None; opp_fg3_pct = None; opp_fta_rate = None
    if def_matchup_df is not None and opp_team_abbr is not None:
        try:
            dm = def_matchup_df[def_matchup_df["TEAM_ABBR"].astype(str).str.upper() == str(opp_team_abbr).upper()]
            if not dm.empty:
                opp_fg_pct   = float(dm["OPP_FG_PCT"].iloc[0])  if "OPP_FG_PCT"  in dm.columns else None
                opp_fg3_pct  = float(dm["OPP_FG3_PCT"].iloc[0]) if "OPP_FG3_PCT" in dm.columns else None
                opp_fta_rate = float(dm["OPP_FTA"].iloc[0])      if "OPP_FTA"     in dm.columns else None
        except Exception:
            pass

    shot_factor = _clamp(1.0 + 0.10 * ((fga_pm - league_fga_pm) / max(league_fga_pm, 1e-6)), 0.92, 1.10)
    ft_pct_adj  = _clamp((ft_pct - 0.76) * 0.05, -0.03, 0.05) if ft_pct and np.isfinite(ft_pct) else 0.0
    ft_factor   = _clamp(1.0 + 0.08 * ((fta_pm - league_fta_pm) / max(league_fta_pm, 1e-6)) + ft_pct_adj, 0.94, 1.10)
    fg3_adj = _clamp((fg3_pct - 0.36) * 0.08, -0.03, 0.04) if fg3_pct and np.isfinite(fg3_pct) else 0.0
    efficiency_factor = _clamp(
        1.0
        + 0.10 * ((ts  - league_ts)  / max(league_ts,  1e-6))
        + 0.06 * ((efg - league_efg) / max(league_efg, 1e-6))
        + 0.02 * (fg_pct - 0.46)
        + fg3_adj,
        0.92, 1.12
    )
    playmaking_factor = _clamp(1.0 + 0.012 * ((ast_ratio - 15.0) / 5.0) + 0.008 * ((ast_to - 1.5) / 1.0), 0.97, 1.04)
    turnover_factor   = _clamp(1.0 - 0.035 * ((tov_pct - 12.0) / 12.0), 0.95, 1.04)
    net_adj    = _clamp(net_rating_player / 10.0, -0.03, 0.03) if net_rating_player and np.isfinite(net_rating_player) else _clamp(plus_minus / 40.0, -0.02, 0.02)
    role_factor = _clamp(1.0 + 0.15 * (pie - 0.08) + net_adj, 0.93, 1.07)

    paint_adj = 0.0
    if pts_paint is not None and np.isfinite(pts_paint) and league_pts_paint > 0:
        paint_adj = _clamp(0.015 * ((pts_paint - league_pts_paint) / league_pts_paint), -0.02, 0.02)
    fb_adj = 0.0
    if pts_fb is not None and np.isfinite(pts_fb) and league_pts_fb > 0:
        fb_adj = _clamp(0.010 * ((pts_fb - league_pts_fb) / league_pts_fb), -0.01, 0.015)
    snd_adj = 0.0
    if pts_2nd is not None and np.isfinite(pts_2nd) and league_pts_2nd > 0:
        snd_adj = _clamp(0.008 * ((pts_2nd - league_pts_2nd) / league_pts_2nd), -0.01, 0.012)
    tov_scorer_adj = 0.0
    if pts_off_tov is not None and np.isfinite(pts_off_tov) and league_pts_off_tov > 0:
        tov_scorer_adj = _clamp(0.007 * ((pts_off_tov - league_pts_off_tov) / league_pts_off_tov), -0.01, 0.010)
    style_factor = _clamp(
        1.0 + 0.012 * ((fg3a_pm - 0.12) / 0.10) + paint_adj + fb_adj + snd_adj + tov_scorer_adj,
        0.95, 1.06
    )

    opp_shooting_adj = 1.0
    if opp_fg_pct is not None:
        opp_shooting_adj = _clamp(1.0 + 0.05 * ((opp_fg_pct - 0.470) / 0.470), 0.97, 1.03)
    if opp_fg3_pct is not None:
        opp_shooting_adj = _clamp(1.0 + 0.03 * ((opp_fg3_pct - 0.360) / 0.360), 0.98, 1.02)

    opp_style_matchup = 1.0
    if (pts_paint is not None and np.isfinite(pts_paint) and pts_paint > 0
            and opp_pts_paint_player is not None and np.isfinite(opp_pts_paint_player)
            and league_opp_pts_paint > 0):
        player_paint_rel = (pts_paint - league_pts_paint) / max(league_pts_paint, 1e-6)
        opp_paint_rel    = (opp_pts_paint_player - league_opp_pts_paint) / max(league_opp_pts_paint, 1e-6)
        opp_style_matchup += _clamp(0.015 * player_paint_rel * np.sign(opp_paint_rel), -0.015, 0.015)
    if (pts_fb is not None and np.isfinite(pts_fb) and pts_fb > 0
            and opp_pts_fb_player is not None and np.isfinite(opp_pts_fb_player)
            and league_opp_pts_fb > 0):
        player_fb_rel = (pts_fb - league_pts_fb) / max(league_pts_fb, 1e-6)
        opp_fb_rel    = (opp_pts_fb_player - league_opp_pts_fb) / max(league_opp_pts_fb, 1e-6)
        opp_style_matchup += _clamp(0.010 * player_fb_rel * np.sign(opp_fb_rel), -0.010, 0.010)
    if (pts_2nd is not None and np.isfinite(pts_2nd) and pts_2nd > 0
            and opp_pts_2nd_player is not None and np.isfinite(opp_pts_2nd_player)
            and league_opp_pts_2nd > 0):
        player_2nd_rel = (pts_2nd - league_pts_2nd) / max(league_pts_2nd, 1e-6)
        opp_2nd_rel    = (opp_pts_2nd_player - league_opp_pts_2nd) / max(league_opp_pts_2nd, 1e-6)
        opp_style_matchup += _clamp(0.008 * player_2nd_rel * np.sign(opp_2nd_rel), -0.008, 0.008)
    opp_style_matchup = _clamp(opp_style_matchup, 0.96, 1.04)

    base_raw      = ppm * minutes_proj
    season_anchor = season_pts * (minutes_proj / max(season_min, 1.0)) if season_min > 0 else base_raw
    star_w = _clamp((usg - 24.0) / 20.0 if np.isfinite(usg) else 0.0, 0.0, 0.40)
    anchored_projection = (1.0 - star_w) * base_raw + star_w * season_anchor
    if season_pts > 0:
        anchored_projection = _clamp(anchored_projection, season_pts * 0.70, season_pts * 1.30)

    l10_pts = None; l5_pts = None; l10_trend = None; l10_std = None; def_matchup_factor = 1.0
    if l10_df is not None and "NAME_KEY" in l10_df.columns:
        l10_row = l10_df[l10_df["NAME_KEY"] == player_name_key]
        if not l10_row.empty:
            l10_pts   = float(getfloat(l10_row.iloc[0], "L10_PTS",    None) or 0) or None
            l5_pts    = float(getfloat(l10_row.iloc[0], "L5_PTS",     None) or 0) or None
            l10_trend = float(getfloat(l10_row.iloc[0], "TREND_SLOPE",None) or 0)
            l10_std   = float(getfloat(l10_row.iloc[0], "L10_STD",    None) or 0) or None

    if l10_pts is not None and l10_pts > 0:
        effective_form = l10_pts
        if l5_pts is not None and l5_pts > 0:
            l5_diff = abs(l5_pts - l10_pts)
            effective_form = 0.65 * l5_pts + 0.35 * l10_pts if l5_diff > 2.0 else l10_pts
        form_diff = abs(effective_form - season_pts)
        if form_diff > 5.0:
            form_weight = 0.82
        elif form_diff > 3.0:
            form_weight = 0.72
        else:
            form_weight = 0.60
        form_anchor = effective_form * (minutes_proj / max(season_min, 1.0))
        anchored_projection = (1.0 - form_weight) * anchored_projection + form_weight * form_anchor
        if l10_trend is not None and abs(l10_trend) > 0.3:
            trend_adj = _clamp(1.0 + 0.015 * l10_trend, 0.95, 1.06)
            anchored_projection *= trend_adj

    if def_matchup_df is not None and opp_team_abbr is not None:
        try:
            pts_col = "OPP_PTS" if "OPP_PTS" in def_matchup_df.columns else "PTS"
            if "TEAM_ABBR" in def_matchup_df.columns and pts_col in def_matchup_df.columns:
                dm = def_matchup_df[def_matchup_df["TEAM_ABBR"].astype(str).str.upper() == str(opp_team_abbr).upper()]
                if not dm.empty:
                    opp_pts_allowed = float(dm[pts_col].iloc[0])
                    league_pts_avg  = float(def_matchup_df[pts_col].mean())
                    if league_pts_avg > 0:
                        def_matchup_factor = _clamp(opp_pts_allowed / league_pts_avg, 0.90, 1.12)
        except Exception:
            pass
    anchored_projection = anchored_projection * def_matchup_factor

    recent_pts = recent_form_override.get(player_name_key, None)
    if recent_pts is not None and recent_pts > 0:
        recent_anchor = recent_pts * (minutes_proj / max(season_min, 1.0))
        diff = abs(recent_pts - season_pts)
        recent_weight = 0.85 if diff > 5 else 0.75
        anchored_projection = (1.0 - recent_weight) * anchored_projection + recent_weight * recent_anchor

    h2h_pts = None; h2h_games = 0; h2h_pts_last = None; h2h_sigma_boost = 1.0
    if h2h_df is not None and opp_team_abbr is not None:
        mask = (
            (h2h_df["NAME_KEY"] == player_name_key) &
            (h2h_df["OPP_TEAM"].astype(str).str.upper() == str(opp_team_abbr).upper())
        )
        h2h_row = h2h_df[mask]
        if not h2h_row.empty:
            h2h_pts      = float(getfloat(h2h_row.iloc[0], "H2H_PTS_AVG",  None) or 0) or None
            h2h_games    = int(getfloat(h2h_row.iloc[0],   "H2H_GAMES",    0)    or 0)
            h2h_pts_last = float(getfloat(h2h_row.iloc[0], "H2H_PTS_LAST", None) or 0) or None

    if h2h_pts is not None and h2h_pts > 0 and h2h_games >= 2:
        h2h_anchor = h2h_pts * (minutes_proj / max(season_min, 1.0))
        h2h_diff   = abs(h2h_pts - season_pts)
        h2h_weight = _clamp(0.10 + 0.04 * h2h_games, 0.20, 0.35)
        if recent_pts is None:
            h2h_weight = _clamp(h2h_weight * 1.5, 0.20, 0.45)
        if season_pts > 0:
            h2h_ratio = h2h_pts / max(season_pts, 1.0)
            if h2h_ratio > 2.5:
                h2h_weight = 0.0
            elif h2h_ratio > 1.8:
                h2h_weight = min(h2h_weight, 0.08)
            elif h2h_ratio > 1.4:
                h2h_weight = min(h2h_weight, 0.15)
            elif h2h_ratio < 0.4:
                h2h_weight = min(h2h_weight, 0.08)
            elif h2h_ratio < 0.6:
                h2h_weight = min(h2h_weight, 0.15)
        if h2h_weight > 0:
            anchored_projection = (1.0 - h2h_weight) * anchored_projection + h2h_weight * h2h_anchor
        h2h_sigma_boost = 1.08 if h2h_diff > 6 else 1.0

    mult = (
        1.0
        + 0.22 * (team_eff_matchup  - 1.0)
        + 0.16 * (total_factor      - 1.0)
        + 0.14 * (usage_factor      - 1.0)
        + 0.10 * (injury_boost      - 1.0)
        + 0.13 * (shot_factor       - 1.0)
        + 0.10 * (ft_factor         - 1.0)
        + 0.13 * (efficiency_factor - 1.0)
        + 0.05 * (playmaking_factor - 1.0)
        + 0.07 * (turnover_factor   - 1.0)
        + 0.07 * (role_factor       - 1.0)
        + 0.04 * (style_factor      - 1.0)
        + 0.05 * (opp_shooting_adj  - 1.0)
        + 0.04 * (opp_style_matchup - 1.0)
    )
    mult = _clamp(mult, 0.90, 1.10)
    final_projection = float(_clamp(anchored_projection * mult, 0.0, 70.0))
    if line_val > 0:
        final_projection = float(_clamp(final_projection, line_val * 0.55, line_val * 1.45))

    cv_base = 0.38
    if np.isfinite(usg):
        cv_base = _clamp(0.38 - 0.004 * (usg - 20.0), 0.30, 0.46)
    sigma = float(final_projection) * cv_base
    sigma += 0.5 * _clamp(abs(minutes_proj - season_min) / max(season_min, 8.0), 0.0, 1.0)
    if line_val > 0:
        sigma = min(sigma, line_val * 0.48)
    sigma_floor = float(max(line_val * 0.28, 2.0)) if line_val > 0 else 2.0
    sigma = float(_clamp(sigma, sigma_floor, 13.0))
    if h2h_sigma_boost > 1.0:
        sigma = float(_clamp(sigma * h2h_sigma_boost, 5.0, 14.0))
    if recent_pts is not None:
        sigma = float(_clamp(sigma * 0.90, 4.0, 10.0))

    return {
        "season_pts": season_pts, "season_min": season_min, "usg": usg, "ppm": ppm,
        "minutes_proj": minutes_proj, "pace_game": pace_game,
        "team_eff_matchup": team_eff_matchup, "opp_def": opp_def,
        "total_factor": total_factor, "injury_boost": injury_boost,
        "direct_player_penalty": direct_player_penalty,
        "usage_factor": usage_factor, "shot_factor": shot_factor,
        "ft_factor": ft_factor, "efficiency_factor": efficiency_factor,
        "playmaking_factor": playmaking_factor, "turnover_factor": turnover_factor,
        "role_factor": role_factor, "style_factor": style_factor,
        "star_w": star_w, "season_anchor": season_anchor,
        "base_projection": anchored_projection,
        "final_projection": final_projection, "sigma": sigma,
        "injured_usage_lost": injured_usage_lost, "injured_minutes_lost": injured_minutes_lost,
        "pie": pie, "ast_ratio": ast_ratio,
        "recent_form_used": recent_pts,
        "h2h_pts": h2h_pts, "h2h_games": h2h_games, "h2h_pts_last": h2h_pts_last,
        "l10_pts": l10_pts, "l5_pts": l5_pts, "l10_trend": l10_trend,
        "def_matchup_factor": def_matchup_factor, "opp_style_matchup": opp_style_matchup,
    }

def run_refresh_scripts():
    scripts = ["refresh_data.py", "refresh_injuries.py", "refresh_matchups.py"]
    ran, missing, failed = [], [], []
    for sname in scripts:
        spath = os.path.join(os.getcwd(), sname)
        if not os.path.exists(spath):
            missing.append(sname)
            continue
        try:
            subprocess.check_call([sys.executable, sname])
            ran.append(sname)
        except Exception as e:
            failed.append((sname, str(e)))
    return ran, missing, failed

st.sidebar.header("⚙️ Controls")
mc_sims            = st.sidebar.selectbox("Monte Carlo sims", [500, 1000, 3000, 5000], index=3)
min_ev             = st.sidebar.slider("Min EV %", -10, 25, 0)
show_only_positive = st.sidebar.checkbox("Only EV > 0", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("📈 Recent Form Override")
recent_form_txt = st.sidebar.text_area(
    "Format: Ime, L5 prosjek (jedan po retku)", height=160,
    placeholder="Gui Santos, 18.2\nDe'Anthony Melton, 21.0\nQuentin Grimes, 22.1",
)
recent_form_override = parse_recent_form_input(recent_form_txt)
if recent_form_override:
    st.sidebar.success(f"✅ {len(recent_form_override)} recent form override(s) aktivan")
    with st.sidebar.expander("Pregled overridea"):
        for k, v in recent_form_override.items():
            st.sidebar.write(f"• {k}: {v} pts")

st.sidebar.markdown("---")
st.sidebar.button("▶️ Pokreni / Osvježi analizu", type="primary", use_container_width=True)

st.sidebar.markdown("---")
st.sidebar.subheader("🔄 One-click refresh (optional)")
if st.sidebar.button("📊 Refresh H2H CSV"):
    with st.spinner("Fetchujem H2H podatke s NBA API..."):
        h2h_script = os.path.join(os.getcwd(), "refresh_h2h.py")
        if os.path.exists(h2h_script):
            try:
                subprocess.check_call([sys.executable, h2h_script])
                st.cache_data.clear()
                st.sidebar.success("✅ H2H refresh OK")
            except Exception as e:
                st.sidebar.error(f"❌ H2H refresh failed: {e}")
        else:
            st.sidebar.error("❌ refresh_h2h.py nije pronađen")

if st.sidebar.button("🔄 Refresh ALL CSV now"):
    with st.spinner("Refreshing…"):
        ran, missing, failed = run_refresh_scripts()
        st.cache_data.clear()
    if ran:     st.sidebar.success("✅ Refresh OK: " + ", ".join(ran))
    if missing: st.sidebar.info("ℹ️ Preskočeno: " + ", ".join(missing))
    if failed:
        st.sidebar.error("❌ Fail:")
        for sname, err in failed:
            st.sidebar.write(f"- {sname}: {err}")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📦 Data status")
st.sidebar.write(f"Players main: {'✅' if PLAYER_MAIN_CSV else '❌'} → {os.path.basename(PLAYER_MAIN_CSV) if PLAYER_MAIN_CSV else 'None'}")
st.sidebar.write(f"Players base: {'✅' if PLAYER_BASE_CSV else '❌'} → {os.path.basename(PLAYER_BASE_CSV) if PLAYER_BASE_CSV else 'None'}")
st.sidebar.write(f"Players adv:  {'✅' if PLAYER_ADV_CSV  else '❌'} → {os.path.basename(PLAYER_ADV_CSV)  if PLAYER_ADV_CSV  else 'None'}")
st.sidebar.write(f"Players misc: {'✅' if PLAYER_MISC_CSV else '❌'} → {os.path.basename(PLAYER_MISC_CSV) if PLAYER_MISC_CSV else 'None'}")
st.sidebar.write(f"Teams CSV:    {'✅' if TEAM_CSV        else '❌'} → {os.path.basename(TEAM_CSV)        if TEAM_CSV        else 'None'}")
st.sidebar.write(f"Injuries CSV: {'✅' if INJ_CSV         else '❌'} → {os.path.basename(INJ_CSV)         if INJ_CSV         else 'None'}")
st.sidebar.write(f"L10 CSV:      {'✅' if L10_CSV         else '❌'} → {os.path.basename(L10_CSV)         if L10_CSV         else 'None'}")
st.sidebar.write(f"DEF Matchup:  {'✅' if DEF_MATCHUP_CSV else '❌'} → {os.path.basename(DEF_MATCHUP_CSV) if DEF_MATCHUP_CSV else 'None'}")
st.sidebar.write(f"OFF Matchup:  {'✅' if OFF_MATCHUP_CSV else '❌'} → {os.path.basename(OFF_MATCHUP_CSV) if OFF_MATCHUP_CSV else 'None'}")

if not PLAYER_MAIN_CSV or not TEAM_CSV:
    st.error("Nedostaje glavni players CSV ili teams CSV.")
    st.stop()

players_df     = load_players_merged(PLAYER_MAIN_CSV, PLAYER_BASE_CSV, PLAYER_ADV_CSV, PLAYER_MISC_CSV)
teams_df       = load_teams_csv(TEAM_CSV)
inj_df         = load_injuries_csv(INJ_CSV)
h2h_df         = load_h2h_csv(H2H_CSV)
l10_df         = load_l10_csv(L10_CSV)
def_matchup_df = load_def_matchup_csv(DEF_MATCHUP_CSV)
off_matchup_df = load_off_matchup_csv(OFF_MATCHUP_CSV)
league_pts_std = float(pd.to_numeric(players_df["PTS"], errors="coerce").dropna().std() or 6.0)

with st.expander("DEBUG DATA"):
    st.write("DATA_DIR:", DATA_DIR)
    st.write("players_df rows:", len(players_df), "cols:", len(players_df.columns))
    st.write("teams_df rows:",   len(teams_df))
    st.write("inj_df rows:",     0 if inj_df is None else len(inj_df))
    cols = [c for c in ["PLAYER_NAME", "TEAM_ABBR", "TEAM_NUMERIC_ID", "MIN", "PTS", "USG_PCT", "TS_PCT", "PIE", "PTS_PAINT", "PACE"] if c in players_df.columns]
    st.dataframe(players_df[cols].head(20), use_container_width=True)

st.subheader("📂 Upload Offer (.txt / .csv)")
uploaded = st.file_uploader(
    "Format: ime, granica, kvota over, kvota under, protivnički tim, total. Delimiter: , ili ; ili TAB",
    type=["txt", "csv"]
)
actual_uploaded = st.file_uploader(
    "Upload results CSV za evaluaciju: Player, Actual Points",
    type=["csv"], key="actual_results_upload"
)
second_model_uploaded = st.file_uploader(
    "Optional: Upload second model prediction CSV",
    type=["csv"], key="second_model_upload"
)

if not uploaded:
    st.info("Uploaduj TXT/CSV ponudu da startuje analiza.")
    st.stop()

txt = smart_decode(uploaded.getvalue())
rows, bad_lines = parse_offer_text(txt)
st.caption(f"Parsed rows: {len(rows)} | Skipped lines: {len(bad_lines)}")
with st.expander("🧾 Debug parsed rows"):
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=["name", "line", "over", "under", "opp_team", "total"]), use_container_width=True)
    if bad_lines:
        st.dataframe(pd.DataFrame(bad_lines, columns=["raw", "reason"]), use_container_width=True)

if len(rows) == 0:
    st.error("Nema validnih redova u fajlu.")
    st.stop()

results, not_found = [], []
for (name, line_val, over_odds, under_odds, opp_from_txt, total_from_txt) in rows:
    r0, used_key, method = match_player_row(players_df, name)
    if r0 is None:
        not_found.append({"offer_name": name, "norm": normalize_name(name), "method": method})
        continue
    team_abbr     = normalize_team_abbr(r0.get("TEAM_ABBR"))
    team_row      = findteam_row_by_abbr(teams_df, team_abbr) if pd.notna(team_abbr) else None
    opp_team_abbr = normalize_team_abbr(opp_from_txt) if opp_from_txt else None
    opp_row       = findteam_row_by_abbr(teams_df, opp_team_abbr) if opp_team_abbr else None
    total_match_model = estimate_match_total(team_row, opp_row, None, teams_df) if team_row is not None and opp_row is not None else None
    total_match_used  = total_from_txt if (total_from_txt is not None and np.isfinite(total_from_txt)) else total_match_model
    ctx = build_player_context(
        r0=r0, players_df=players_df, teams_df=teams_df,
        team_row=team_row, opp_row=opp_row, inj_df=inj_df,
        team_abbr=team_abbr, player_name_key=used_key,
        total_match_used=total_match_used,
        recent_form_override=recent_form_override,
        h2h_df=h2h_df, opp_team_abbr=opp_team_abbr,
        l10_df=l10_df, def_matchup_df=def_matchup_df, off_matchup_df=off_matchup_df,
        line_val=float(line_val),
    )
    results.append({
        "Player":               str(r0.get("PLAYER_NAME", name)),
        "Matched By":           method,
        "TEAM_ABBR":            team_abbr,
        "OPP_TEAM":             opp_team_abbr,
        "NET_RATING":           getfloat(team_row, "NET_RATING", 0.0) if team_row is not None else 0.0,
        "OPP_DEF":              ctx["opp_def"],
        "PACE_GAME":            round(float(ctx["pace_game"]), 3),
        "TOTAL_MATCH_OFFER":    float(total_from_txt) if (total_from_txt is not None and np.isfinite(total_from_txt)) else None,
        "TOTAL_MATCH_MODEL":    round(float(total_match_model), 2) if total_match_model is not None else None,
        "TOTAL_MATCH_USED":     round(float(total_match_used),  2) if total_match_used  is not None else None,
        "Line":                 float(line_val),
        "Over Odds":            float(over_odds),
        "Under Odds":           float(under_odds),
        "PPM":                  round(float(ctx["ppm"]), 4),
        "Minutes":              round(float(ctx["minutes_proj"]), 2),
        "Usage %":              round(float(ctx["usg"]), 2) if np.isfinite(ctx["usg"]) else None,
        "PIE":                  round(float(ctx["pie"]), 3) if np.isfinite(ctx["pie"]) else None,
        "AST_RATIO":            round(float(ctx["ast_ratio"]), 2) if np.isfinite(ctx["ast_ratio"]) else None,
        "Recent Form":          round(float(ctx["recent_form_used"]), 1) if ctx.get("recent_form_used") is not None else None,
        "H2H PTS Avg":          round(float(ctx["h2h_pts"]),      1) if ctx.get("h2h_pts")      else None,
        "H2H Games":            int(ctx["h2h_games"])                if ctx.get("h2h_games")     else None,
        "H2H PTS Last":         round(float(ctx["h2h_pts_last"]), 1) if ctx.get("h2h_pts_last")  else None,
        "L10 PTS":              round(float(ctx["l10_pts"]),      1) if ctx.get("l10_pts")       else None,
        "L5 PTS":               round(float(ctx["l5_pts"]),       1) if ctx.get("l5_pts")        else None,
        "L10 Trend":            round(float(ctx["l10_trend"]),    2) if ctx.get("l10_trend") is not None else None,
        "DEF Factor":           round(float(ctx["def_matchup_factor"]), 3) if ctx.get("def_matchup_factor") else None,
        "OPP Style Matchup":    round(float(ctx["opp_style_matchup"]), 3) if ctx.get("opp_style_matchup") is not None else None,
        "Injury Boost":         round(float(ctx["injury_boost"]), 3),
        "Direct Player Penalty": round(float(ctx["direct_player_penalty"]), 3),
        "Injured Usage Lost":   round(float(ctx["injured_usage_lost"]), 2),
        "Injured Minutes Lost": round(float(ctx["injured_minutes_lost"]), 2),
        "Usage Factor":         round(float(ctx["usage_factor"]), 3),
        "Team Matchup Factor":  round(float(ctx["team_eff_matchup"]), 3),
        "Shot Factor":          round(float(ctx["shot_factor"]), 3),
        "FT Factor":            round(float(ctx["ft_factor"]), 3),
        "Efficiency Factor":    round(float(ctx["efficiency_factor"]), 3),
        "Playmaking Factor":    round(float(ctx["playmaking_factor"]), 3),
        "Turnover Factor":      round(float(ctx["turnover_factor"]), 3),
        "Role Factor":          round(float(ctx["role_factor"]), 3),
        "Style Factor":         round(float(ctx["style_factor"]), 3),
        "Total Factor":         round(float(ctx["total_factor"]), 3),
        "StarWeight":           round(float(ctx["star_w"]), 3),
        "SeasonAnchor":         round(float(ctx["season_anchor"]), 2),
        "Base Projection":      round(float(ctx["base_projection"]), 2),
        "Final Projection":     round(float(ctx["final_projection"]), 2),
        "Sigma":                round(float(ctx["sigma"]), 2),
    })

df = pd.DataFrame(results)
if df.empty:
    st.error("Nijedan igrač nije matchovan u sezonskoj bazi.")
    if not_found:
        st.dataframe(pd.DataFrame(not_found), use_container_width=True)
    st.stop()

with st.expander("🔎 Debug players not found"):
    if not_found:
        st.dataframe(pd.DataFrame(not_found), use_container_width=True)
    else:
        st.write("All players matched ✅")

anchors = pd.to_numeric(df["SeasonAnchor"], errors="coerce").dropna()
lines   = pd.to_numeric(df["Line"],         errors="coerce").dropna()
common  = anchors.index.intersection(lines.index)
if len(common) >= 3:
    bm_offset = float((anchors[common] - lines[common]).mean())
    bm_offset = _clamp(bm_offset, -2.0, 4.0)
else:
    bm_offset = 1.5
st.caption(f"Bookmaker offset: {bm_offset:.2f}")

rng = np.random.default_rng(42)
updated = []
for _, row in df.iterrows():
    proj_raw   = float(row["Final Projection"])
    line_val   = float(row["Line"])
    over_odds  = float(row["Over Odds"])
    under_odds = float(row["Under Odds"])
    season_pts = float(row.get("SeasonAnchor", proj_raw))
    usg_val    = row.get("Usage %", 20.0)
    usg_val    = float(usg_val) if usg_val is not None and not pd.isna(usg_val) else 20.0
    sigma_val  = float(row.get("Sigma", league_pts_std))

    player_bm_offset = compute_per_player_bm_offset(season_pts)
    proj_devigged    = proj_raw - player_bm_offset

    p_over_mkt_raw  = 1.0 / over_odds
    p_under_mkt_raw = 1.0 / under_odds
    total_mkt       = p_over_mkt_raw + p_under_mkt_raw
    p_over_mkt  = p_over_mkt_raw  / total_mkt
    p_under_mkt = p_under_mkt_raw / total_mkt

    edge_raw = proj_devigged - line_val
    abs_edge = abs(edge_raw)
    if abs_edge < 1.5:
        market_blend = 0.55
    elif abs_edge < 3.0:
        market_blend = 0.45
    elif abs_edge < 5.0:
        market_blend = 0.35
    else:
        market_blend = 0.25

    proj = (1 - market_blend) * proj_devigged + market_blend * line_val
    max_allowed_edge = compute_max_edge(line_val, usg_val, sigma_val)
    proj = min(proj, line_val + max_allowed_edge)
    proj = max(proj, line_val - max_allowed_edge)

    sigma = float(row.get("Sigma", league_pts_std))
    sigma_floor_mc = float(max(line_val * 0.28, 2.0))
    sigma = _clamp(sigma, sigma_floor_mc, 9.5)

    sims          = rng.normal(proj, sigma, int(mc_sims))
    sims          = np.clip(sims, 0.0, 80.0)
    p_over_model  = float(np.mean(sims > line_val))
    p_under_model = 1.0 - p_over_model

    ev_over  = (p_over_model  * over_odds)  - 1.0
    ev_under = (p_under_model * under_odds) - 1.0

    MIN_EDGE_THRESHOLD = 0.04
    if abs(p_over_model - p_over_mkt) < MIN_EDGE_THRESHOLD:
        ev_over  = min(ev_over,  0.0)
        ev_under = min(ev_under, 0.0)

    ev_over  = _clamp(ev_over,  -0.99, 0.35)
    ev_under = _clamp(ev_under, -0.99, 0.35)

    if ev_over > ev_under and ev_over > 0:
        pick, best_ev, p_pick = "OVER",     ev_over,  p_over_model
    elif ev_under > 0:
        pick, best_ev, p_pick = "UNDER",    ev_under, p_under_model
    else:
        pick, best_ev, p_pick = "NO VALUE", max(ev_over, ev_under), max(p_over_model, p_under_model)

    updated.append({
        **row.to_dict(),
        "Calibrated Projection": round(proj, 2),
        "BM Offset Applied":     round(player_bm_offset, 2),
        "Proj De-vigged":        round(proj_devigged, 2),
        "Market P(Over)%":       round(p_over_mkt  * 100.0, 2),
        "Market P(Under)%":      round(p_under_mkt * 100.0, 2),
        "Model Pick":            pick,
        "Pick Confidence %":     round(p_pick * 100.0, 2),
        "Best EV %":             round(best_ev      * 100.0, 2),
        "Projection Edge":       round(proj - line_val, 2),
        "P(Over)%":              round(p_over_model  * 100.0, 2),
        "P(Under)%":             round(p_under_model * 100.0, 2),
    })

df = pd.DataFrame(updated)

def zscore(s):
    s = pd.to_numeric(s, errors="coerce")
    return (s - s.mean()) / (s.std() + 1e-6)

df["EV_z"]    = zscore(df["Best EV %"])
df["EDGE_z"]  = zscore(df["Projection Edge"])
df["HIT_z"]   = zscore(df["Pick Confidence %"])
df["True Score"] = 0.50 * df["EV_z"] + 0.30 * df["EDGE_z"] + 0.20 * df["HIT_z"]
df = df.sort_values("True Score", ascending=False)
df = df[df["Best EV %"] >= min_ev]
if show_only_positive:
    df = df[df["Best EV %"] > 0]

over_df = df[df["Model Pick"] == "OVER"].copy()
team_over_counts = over_df.groupby("TEAM_ABBR").size()
concentrated_teams = team_over_counts[team_over_counts >= 3].index.tolist()

if concentrated_teams:
    team_usg_sums = (over_df[over_df["TEAM_ABBR"].isin(concentrated_teams)].groupby("TEAM_ABBR")["Usage %"].sum())
    penalty_map = {}
    for team in concentrated_teams:
        team_over_players = df[(df["TEAM_ABBR"] == team) & (df["Model Pick"] == "OVER")].index.tolist()
        for rank, idx in enumerate(team_over_players):
            if rank == 2:    penalty_map[idx] = 0.85
            elif rank >= 3:  penalty_map[idx] = 0.55
    if penalty_map:
        df["Conc Penalty"] = 1.0
        for idx, mult in penalty_map.items():
            if idx in df.index:
                df.at[idx, "Conc Penalty"] = mult
        df["Best EV %"] = (df["Best EV %"] * df["Conc Penalty"]).round(2)
        df["EV_z"]       = zscore(df["Best EV %"])
        df["EDGE_z"]     = zscore(df["Projection Edge"])
        df["HIT_z"]      = zscore(df["Pick Confidence %"])
        df["True Score"] = 0.50 * df["EV_z"] + 0.30 * df["EDGE_z"] + 0.20 * df["HIT_z"]
        df = df.sort_values("True Score", ascending=False)
    st.markdown("---")
    st.warning(f"⚠️ Team Concentration Warning — {len(concentrated_teams)} tim(a) ima 3+ OVER pickova")
    for team in concentrated_teams:
        count   = int(team_over_counts[team])
        usg_sum = float(team_usg_sums.get(team, 0))
        players = over_df[over_df["TEAM_ABBR"] == team]["Player"].tolist()
        penalized = [df.at[idx, "Player"] for idx, mult in penalty_map.items() if mult < 1.0 and idx in df.index and df.at[idx, "TEAM_ABBR"] == team]
        col1, col2, col3 = st.columns(3)
        col1.metric(f"🏀 {team} OVER pickovi", count)
        col2.metric("Ukupni USG%", f"{usg_sum:.0f}%", delta="⚠️ Visoko" if usg_sum > 85 else "OK", delta_color="inverse" if usg_sum > 85 else "normal")
        col3.metric("EV penalty primijenjen", f"{len(penalized)} igrač(a)")
        st.caption(f"Igrači: {', '.join(players)}")
        if penalized:
            st.caption(f"🔻 Penalizirani: {', '.join(penalized)}")
    st.markdown("---")

if recent_form_override:
    rf_players = set(recent_form_override.keys())
    rf_mask = df["Player"].apply(lambda x: normalize_name(x) in rf_players)
    if int(rf_mask.sum()) > 0:
        st.info(f"📈 {int(rf_mask.sum())} igrač(a) ima aktivan Recent Form override")

st.subheader("📊 Full Portfolio")
st.dataframe(df, use_container_width=True)
st.subheader("🔥 TOP 3")
st.dataframe(df.head(3), use_container_width=True)

st.markdown("---")
st.subheader("✅ Engine Evaluation / Grading")
stake_size        = st.number_input("Stake per bet", min_value=0.1, value=1.0, step=0.1)
actual_results_df = None
evaluated_df      = None

if actual_uploaded is not None:
    try:
        actual_results_df = load_actual_results_csv(actual_uploaded)
    except Exception as e:
        st.error(f"Greška pri učitavanju results CSV: {e}")

if actual_results_df is not None:
    try:
        evaluated_df, eval_summary = evaluate_engine(df, actual_results_df, stake=stake_size, model_name="Engine 1")
        engine_grade = grade_engine(eval_summary)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Accuracy",  f"{eval_summary['Accuracy %']}%")
        c2.metric("ROI",       f"{eval_summary['ROI %']}%")
        c3.metric("Profit",    f"{eval_summary['Profit']}")
        c4.metric("MAE",       f"{eval_summary['MAE']}")
        c5.metric("Grade",     engine_grade)
        st.dataframe(pd.DataFrame([eval_summary]), use_container_width=True)
        eval_cols = [c for c in ["Player", "Model Pick", "Line", "Final Projection", "Actual Points", "Bet Result", "Used Odds", "Profit", "Projection Edge", "CLV"] if c in evaluated_df.columns]
        st.dataframe(evaluated_df[eval_cols], use_container_width=True)
    except Exception as e:
        st.error(f"Greška u engine evaluaciji: {e}")

if actual_results_df is not None and second_model_uploaded is not None:
    st.markdown("---")
    st.subheader("⚔️ Compare Two Models")
    try:
        second_model_df = load_prediction_results_csv(second_model_uploaded)
        _, summary1 = evaluate_engine(df,              actual_results_df, stake=stake_size, model_name="Engine 1")
        _, summary2 = evaluate_engine(second_model_df, actual_results_df, stake=stake_size, model_name="Engine 2")
        summary1["Grade"] = grade_engine(summary1)
        summary2["Grade"] = grade_engine(summary2)
        winner, compare_df_out = compare_two_models(summary1, summary2)
        if winner == "TIE":
            st.info("Rezultat poređenja: TIE")
        else:
            st.success(f"Winner: {winner}")
        st.dataframe(compare_df_out, use_container_width=True)
    except Exception as e:
        st.error(f"Greška u compare modulu: {e}")

history_folder = os.path.join(os.getcwd(), "history")
os.makedirs(history_folder, exist_ok=True)
timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
out_path  = os.path.join(history_folder, f"analysis_{timestamp}.csv")
try:
    df.to_csv(out_path, index=False)
    st.caption(f"Saved history: {out_path}")
except Exception as e:
    st.warning(f"Could not save history csv: {e}")

if actual_results_df is not None and evaluated_df is not None:
    try:
        eval_out_path = os.path.join(history_folder, f"evaluation_{timestamp}.csv")
        evaluated_df.to_csv(eval_out_path, index=False)
        st.caption(f"Saved evaluation CSV: {eval_out_path}")
    except Exception as e:
        st.warning(f"Could not save evaluation csv: {e}")
