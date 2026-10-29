# =====================================================
# NBA Quant Engine – 2025-26
# =====================================================

from __future__ import annotations

import datetime
import difflib
import os
import re
import subprocess
import sys
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

# =====================================================
# CONFIG
# =====================================================

SEASON    = "2025-26"
TODAY     = datetime.date.today()
TODAY_ISO = TODAY.isoformat()

DATA_DIR_CANDIDATES = [
    os.path.join(os.getcwd(), "data"),
    "/mnt/data",
    os.getcwd(),
]
DATA_DIR = next((p for p in DATA_DIR_CANDIDATES if os.path.isdir(p)), os.getcwd())


def _first_existing(candidates: List[str]) -> Optional[str]:
    return next((p for p in candidates if os.path.exists(p)), None)


PLAYER_MAIN_CSV = _first_existing([
    os.path.join(DATA_DIR, "players_2025-26.csv"),
    os.path.join(DATA_DIR, f"players_{SEASON}.csv"),
])
PLAYER_BASE_CSV = _first_existing([
    os.path.join(DATA_DIR, "players_2025-26_base.csv"),
    os.path.join(DATA_DIR, f"players_{SEASON}_base.csv"),
])
PLAYER_ADV_CSV = _first_existing([
    os.path.join(DATA_DIR, "players_2025-26_advanced.csv"),
    os.path.join(DATA_DIR, f"players_{SEASON}_advanced.csv"),
])
PLAYER_MISC_CSV = _first_existing([
    os.path.join(DATA_DIR, "players_2025-26_misc.csv"),
    os.path.join(DATA_DIR, f"players_{SEASON}_misc.csv"),
])
TEAM_CSV = _first_existing([
    os.path.join(DATA_DIR, "teams_2025-26.csv"),
    os.path.join(DATA_DIR, f"teams_{SEASON}.csv"),
    os.path.join(DATA_DIR, "timovi_2025-26.csv"),
    os.path.join(DATA_DIR, f"timovi_{SEASON}.csv"),
])
INJ_CSV = _first_existing([
    os.path.join(DATA_DIR, "injuries_2025-26.csv"),
    os.path.join(DATA_DIR, f"injuries_{SEASON}.csv"),
    os.path.join(DATA_DIR, "injuries.csv"),
    os.path.join(DATA_DIR, "ozljede_2025-26.csv"),
    os.path.join(DATA_DIR, f"ozljede_{SEASON}.csv"),
    os.path.join(DATA_DIR, "ozljede.csv"),
])
H2H_CSV = _first_existing([
    os.path.join(DATA_DIR, "h2h_2025-26.csv"),
    os.path.join(DATA_DIR, f"h2h_{SEASON}.csv"),
])
L10_CSV = _first_existing([
    os.path.join(DATA_DIR, "form_l10_2025-26.csv"),
    os.path.join(DATA_DIR, f"form_l10_{SEASON}.csv"),
])
DEF_MATCHUP_CSV = _first_existing([
    os.path.join(DATA_DIR, "def_matchup_2025-26.csv"),
    os.path.join(DATA_DIR, f"def_matchup_{SEASON}.csv"),
])
OFF_MATCHUP_CSV = _first_existing([
    os.path.join(DATA_DIR, "off_matchup_2025-26.csv"),
    os.path.join(DATA_DIR, f"off_matchup_{SEASON}.csv"),
])
B2B_CSV = _first_existing([
    os.path.join(DATA_DIR, "b2b_2025-26.csv"),
    os.path.join(DATA_DIR, f"b2b_{SEASON}.csv"),
])

# Candidate lists (za _reload_csv_paths)
PLAYER_MAIN_CANDIDATES = [os.path.join(DATA_DIR, "players_2025-26.csv"), os.path.join(DATA_DIR, f"players_{SEASON}.csv")]
PLAYER_BASE_CANDIDATES = [os.path.join(DATA_DIR, "players_2025-26_base.csv"), os.path.join(DATA_DIR, f"players_{SEASON}_base.csv")]
PLAYER_ADV_CANDIDATES  = [os.path.join(DATA_DIR, "players_2025-26_advanced.csv"), os.path.join(DATA_DIR, f"players_{SEASON}_advanced.csv")]
PLAYER_MISC_CANDIDATES = [os.path.join(DATA_DIR, "players_2025-26_misc.csv"), os.path.join(DATA_DIR, f"players_{SEASON}_misc.csv")]
TEAM_CSV_CANDIDATES    = [os.path.join(DATA_DIR, "teams_2025-26.csv"), os.path.join(DATA_DIR, f"teams_{SEASON}.csv")]
INJ_CSV_CANDIDATES     = [os.path.join(DATA_DIR, "injuries_2025-26.csv"), os.path.join(DATA_DIR, f"injuries_{SEASON}.csv"), os.path.join(DATA_DIR, "injuries.csv")]
H2H_CSV_CANDIDATES     = [os.path.join(DATA_DIR, "h2h_2025-26.csv"), os.path.join(DATA_DIR, f"h2h_{SEASON}.csv")]
L10_CSV_CANDIDATES     = [os.path.join(DATA_DIR, "form_l10_2025-26.csv"), os.path.join(DATA_DIR, f"form_l10_{SEASON}.csv")]
DEF_MATCHUP_CANDIDATES = [os.path.join(DATA_DIR, "def_matchup_2025-26.csv"), os.path.join(DATA_DIR, f"def_matchup_{SEASON}.csv")]
OFF_MATCHUP_CANDIDATES = [os.path.join(DATA_DIR, "off_matchup_2025-26.csv"), os.path.join(DATA_DIR, f"off_matchup_{SEASON}.csv")]

TEAM_ID_TO_ABBR: Dict[int, str] = {
    1610612737: "ATL", 1610612738: "BOS", 1610612751: "BKN", 1610612766: "CHA",
    1610612741: "CHI", 1610612739: "CLE", 1610612742: "DAL", 1610612743: "DEN",
    1610612765: "DET", 1610612744: "GSW", 1610612745: "HOU", 1610612754: "IND",
    1610612746: "LAC", 1610612747: "LAL", 1610612763: "MEM", 1610612748: "MIA",
    1610612749: "MIL", 1610612750: "MIN", 1610612740: "NOP", 1610612752: "NYK",
    1610612753: "ORL", 1610612755: "PHI", 1610612756: "PHX", 1610612757: "POR",
    1610612758: "SAC", 1610612759: "SAS", 1610612760: "OKC", 1610612761: "TOR",
    1610612762: "UTA", 1610612764: "WAS",
}
ABBR_TO_TEAM_ID: Dict[str, int] = {v: k for k, v in TEAM_ID_TO_ABBR.items()}
TEAM_NAME_TO_ABBR: Dict[str, str] = {
    "atlanta hawks": "ATL",        "boston celtics": "BOS",
    "brooklyn nets": "BKN",        "charlotte hornets": "CHA",
    "chicago bulls": "CHI",        "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL",     "denver nuggets": "DEN",
    "detroit pistons": "DET",      "golden state warriors": "GSW",
    "houston rockets": "HOU",      "indiana pacers": "IND",
    "los angeles clippers": "LAC", "la clippers": "LAC",
    "los angeles lakers": "LAL",   "memphis grizzlies": "MEM",
    "miami heat": "MIA",           "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN","new orleans pelicans": "NOP",
    "new york knicks": "NYK",      "orlando magic": "ORL",
    "philadelphia 76ers": "PHI",   "philadelphia seventy sixers": "PHI",
    "phoenix suns": "PHX",         "portland trail blazers": "POR",
    "sacramento kings": "SAC",     "san antonio spurs": "SAS",
    "oklahoma city thunder": "OKC","toronto raptors": "TOR",
    "utah jazz": "UTA",            "washington wizards": "WAS",
}

# =====================================================
# Streamlit page setup
# =====================================================

st.set_page_config(page_title="NBA Quant Engine", layout="wide")
st.title("🏀 NBA Quant Engine – 2025-26")

st.markdown("---")
col_main1, col_main2, col_main3 = st.columns([2, 1, 1])
with col_main1:
    run_daily = st.button(
        f"🚀 POKRENI DNEVNU ANALIZU — {TODAY.strftime('%d.%m.%Y')}",
        type="primary", use_container_width=True,
    )
with col_main2:
    _offer_ok   = os.path.exists(os.path.join(DATA_DIR, "offer_latest.csv"))
    _players_ok = PLAYER_MAIN_CSV is not None
    if _offer_ok and _players_ok:
        st.success("✅ Podaci spremni")
    elif not _offer_ok:
        st.warning("⚠️ Nema offer_latest.csv")
    else:
        st.warning("⚠️ Nema players CSV")
with col_main3:
    _offer_path = os.path.join(DATA_DIR, "offer_latest.csv")
    if os.path.exists(_offer_path):
        _mtime = datetime.datetime.fromtimestamp(os.path.getmtime(_offer_path)).strftime("%H:%M:%S")
        st.info(f"📋 Offer ažuriran: {_mtime}")
    else:
        st.info("📋 Pokreni Refresh Props")

if run_daily:
    _refresh_all = os.path.join(os.getcwd(), "refresh_all.py")
    if os.path.exists(_refresh_all):
        with st.status("🔄 Refreshujem sve podatke...", expanded=True) as _status:
            try:
                st.write("▶️ Pokrećem refresh_all.py...")
                _result = subprocess.run([sys.executable, _refresh_all],
                    capture_output=True, text=True, timeout=300)
                if _result.returncode == 0:
                    st.write("✅ Svi podaci osvježeni!")
                    _status.update(label="✅ Refresh završen!", state="complete")
                else:
                    st.write("⚠️ Refresh završen s nekim greškama")
                    _status.update(label="⚠️ Refresh s greškama", state="error")
                with st.expander("📋 Refresh log"):
                    st.code(_result.stdout + _result.stderr)
                st.cache_data.clear()
                st.rerun()
            except subprocess.TimeoutExpired:
                st.error("❌ Timeout — refresh traje predugo (>5 min)")
                _status.update(label="❌ Timeout", state="error")
            except Exception as _e:
                st.error(f"❌ Greška: {_e}")
                _status.update(label="❌ Greška", state="error")
    else:
        _props_script = os.path.join(os.getcwd(), "refresh_props.py")
        if os.path.exists(_props_script):
            with st.spinner("Refreshujem props..."):
                subprocess.run([sys.executable, _props_script], capture_output=True)
                st.cache_data.clear()
                st.rerun()
        else:
            st.error("❌ refresh_all.py i refresh_props.py nisu pronađeni.")

st.markdown("---")

# =====================================================
# Utility helpers
# =====================================================

def normalize_name(s: Any) -> str:
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


def safe_float(x: Any) -> Optional[float]:
    try:
        s = str(x).strip().replace('"', "").replace(",", ".")
        return float(s) if s else None
    except Exception:
        return None


def smart_decode(b: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "utf-16", "utf-16le", "utf-16be", "cp1252", "latin-1"):
        try:
            s = b.decode(enc)
            if s and s.strip():
                return s
        except Exception:
            pass
    return b.decode("utf-8", errors="ignore")


def _get_float(obj: Any, col: str, default: Optional[float] = None) -> Optional[float]:
    try:
        v = obj.get(col, default) if hasattr(obj, "get") else default
        if pd.isna(v):
            return default
        v = float(v)
        return v if np.isfinite(v) else default
    except Exception:
        return default


def _clamp(x: Any, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except Exception:
        return (lo + hi) / 2.0


def zscore(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    return (s - s.mean()) / (s.std() + 1e-6)


def normalize_team_abbr(val: Any) -> Any:
    try:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return np.nan
    except (TypeError, ValueError):
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
    except (ValueError, OverflowError):
        pass
    return TEAM_NAME_TO_ABBR.get(s.lower(), np.nan)


def extract_injury_status(desc: str) -> str:
    s = str(desc or "").strip().lower()
    if "out for season" in s:          return "OUT"
    if re.search(r"\bout\b", s):       return "OUT"
    if "questionable" in s:            return "QUESTIONABLE"
    if "doubtful" in s:                return "DOUBTFUL"
    if "day to day" in s or "day-to-day" in s: return "QUESTIONABLE"
    if "inactive" in s:                return "INACTIVE"
    if "probable" in s:                return "PROBABLE"
    return "UNKNOWN"


def _status_weight(s: str) -> float:
    s = (s or "").strip().upper()
    return {"OUT": 1.0, "INACTIVE": 1.0, "DOUBTFUL": 0.75, "QUESTIONABLE": 0.40, "PROBABLE": 0.15}.get(s, 0.0)


def fix_usg_scale(df: pd.DataFrame) -> pd.DataFrame:
    if "USG_PCT" not in df.columns:
        return df
    mean_usg = pd.to_numeric(df["USG_PCT"], errors="coerce").dropna().mean()
    if pd.notna(mean_usg) and mean_usg < 2.0:
        df = df.copy()
        df["USG_PCT"] = pd.to_numeric(df["USG_PCT"], errors="coerce") * 100.0
    return df


# =====================================================
# Model math helpers
# =====================================================

def compute_per_player_bm_offset(season_pts: float) -> float:
    league_avg        = 9.0
    base_offset       = season_pts * 0.05
    regression_factor = 1.0 - 0.3 * max(0.0, (season_pts - league_avg) / max(season_pts, 1.0))
    return float(np.clip(base_offset * regression_factor, 0.2, 3.5))


def compute_max_edge(line_val: float, usg: float = 20.0, sigma: float = 6.0) -> float:
    base       = np.clip(line_val * 0.16, 2.0, 7.0)
    usg_mult   = np.clip(1.0 + 0.015 * (usg   - 20.0), 0.85, 1.25)
    sigma_mult = np.clip(sigma / 6.0,                   0.90, 1.20)
    return float(np.clip(base * usg_mult * sigma_mult, 2.0, 8.5))


def compute_injury_boost_v2(
    injured_usage_lost: float,
    injured_minutes_lost: float,
    player_usg: float,
    has_star_out: bool,
    star_usg_lost: float,
    player_position_score: float = 0.0,
    n_active_teammates: int = 8,
) -> float:
    base = 1.0 + 0.0025 * injured_usage_lost + 0.0014 * injured_minutes_lost
    if player_position_score > 0.5:
        base = 1.0 + (base - 1.0) * (1.0 + 0.30 * player_position_score)
    elif player_position_score > 0.0:
        base = 1.0 + (base - 1.0) * (1.0 + 0.10 * player_position_score)
    else:
        base = 1.0 + (base - 1.0) * 0.40
    if has_star_out and star_usg_lost >= 25 and player_position_score > 0.3:
        base += 0.0004 * star_usg_lost * player_position_score
    if player_usg >= 28:
        return float(np.clip(base, 1.0, 1.03))
    if player_usg >= 22:
        return float(np.clip(base, 1.0, 1.06))
    return float(np.clip(base, 1.0, 1.10))


# =====================================================
# Input parsers
# =====================================================

def parse_recent_form_input(txt: str) -> Dict[str, float]:
    result: Dict[str, float] = {}
    if not txt or not txt.strip():
        return result
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.rsplit(",", 1)
        if len(parts) != 2:
            continue
        val = safe_float(parts[1].strip())
        if val is not None and val > 0:
            result[normalize_name(parts[0].strip())] = float(val)
    return result


def parse_injury_override(txt: str, players_df: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict] = []
    if not txt or not txt.strip():
        return pd.DataFrame()
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.rsplit(",", 1)]
        if len(parts) != 2:
            continue
        name_raw, status_raw = parts
        s = status_raw.strip().upper()
        status = s if s in ("OUT", "QUESTIONABLE", "DOUBTFUL", "PROBABLE", "INACTIVE") \
                   else extract_injury_status(status_raw)
        name_key  = normalize_name(name_raw)
        pr        = players_df[players_df["NAME_KEY"] == name_key] if "NAME_KEY" in players_df.columns else pd.DataFrame()
        team_abbr = str(pr["TEAM_ABBR"].iloc[0]) if not pr.empty and "TEAM_ABBR" in pr.columns else np.nan
        rows.append({"PLAYER": name_raw, "NAME_KEY": name_key, "TEAM_ABBR": team_abbr,
                     "STATUS": status, "DESCRIPTION": status_raw})
    return pd.DataFrame(rows) if rows else pd.DataFrame()


"""
═══════════════════════════════════════════════════════════════════════════════
NBA ENGINE - PARSE_OFFER_TEXT FIX ZA 7-KOLONSKI FORMAT
═══════════════════════════════════════════════════════════════════════════════

PROBLEM: app.py koristi parse_offer_text() koji očekuje 6 kolona:
    PLAYER, LINE, OVER_ODDS, UNDER_ODDS, OPP_TEAM, TOTAL_MATCH

Ali novi offer_latest.csv ima 7 kolona:
    PLAYER, PLAYER_TEAM, LINE, OVER_ODDS, UNDER_ODDS, OPP_TEAM, TOTAL_MATCH

RJEŠENJE: Zamijeni parse_offer_text() u app.py sa ovom verzijom.

═══════════════════════════════════════════════════════════════════════════════
"""

from typing import List, Tuple
import numpy as np
import pandas as pd


def safe_float(x):
    """Sigurno konvertuj u float"""
    if x is None:
        return None
    try:
        s = str(x).strip().replace('"', "").replace(",", ".")
        if not s or s.upper() == "NAN":
            return None
        return float(s)
    except:
        return None


def normalize_team_abbr(val):
    """Normaliziraj team abbreviation"""
    VALID_ABBRS = {
        "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
        "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
        "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"
    }
    if val is None:
        return np.nan
    if isinstance(val, float) and np.isnan(val):
        return np.nan
    s = str(val).strip().upper()
    if not s or s == "NAN" or s == "NONE" or s == "":
        return np.nan
    if s in VALID_ABBRS:
        return s
    return np.nan


def parse_offer_text(txt: str) -> Tuple[List[Tuple], List[Tuple]]:
    """
    Parsira offer CSV/TXT u listu tuples.
    
    Podržava formate:
    - 4 kolone: name, line, over, under
    - 5 kolona: name, line, over, under, opp_team/total
    - 6 kolona: name, line, over, under, opp_team, total
    - 7 kolona: name, player_team, line, over, under, opp_team, total (NOVO)
    
    Returns:
        Tuple[List[Tuple], List[Tuple]]: (valid_rows, bad_rows)
        
    Svaki valid row je tuple:
        (name, line_val, over_odds, under_odds, opp_team, total_match)
    """
    rows: List[Tuple] = []
    bad:  List[Tuple] = []
    
    for raw in txt.splitlines():
        line = raw.strip()
        if not line:
            continue
        
        low = line.lower()
        
        # Skip header - proširen za razne varijante
        if any(kw in low for kw in ["player", "ime", "igrac", "igrač"]):
            if any(kw in low for kw in ["line", "granica", "linija", "odds", "over", "under"]):
                continue
        
        # Detect delimiter
        if "\t" in line and line.count("\t") >= 3:
            delim = "\t"
        elif line.count(";") >= 3:
            delim = ";"
        else:
            delim = ","
        
        parts = [p.strip() for p in line.split(delim)]
        
        # Handle different column counts
        name = None
        line_val = None
        over_odds = None
        under_odds = None
        opp_team = None
        total_match = None
        
        if len(parts) == 4:
            # name, line, over, under
            name, line_val, over_odds, under_odds = parts
            
        elif len(parts) == 5:
            # name, line, over, under, opp_team OR total
            name = parts[0]
            line_val = parts[1]
            over_odds = parts[2]
            under_odds = parts[3]
            x = parts[4]
            n = safe_float(x)
            if n is None:
                # Nije broj, tretira se kao team abbr
                opp_team = normalize_team_abbr(x)
            else:
                # Jeste broj, tretira se kao total
                total_match = n
                
        elif len(parts) == 6:
            # name, line, over, under, opp_team, total
            name = parts[0]
            line_val = parts[1]
            over_odds = parts[2]
            under_odds = parts[3]
            opp_team = normalize_team_abbr(parts[4])
            total_match = safe_float(parts[5])
            
        elif len(parts) == 7:
            # ═══════════════════════════════════════════════════════════════
            # NOVO: name, player_team, line, over, under, opp_team, total
            # ═══════════════════════════════════════════════════════════════
            name = parts[0]
            # parts[1] = player_team - ignorišemo jer koristimo iz players_df
            line_val = parts[2]
            over_odds = parts[3]
            under_odds = parts[4]
            opp_team = normalize_team_abbr(parts[5])
            total_match = safe_float(parts[6])
            # ═══════════════════════════════════════════════════════════════
            
        else:
            bad.append((raw, f"Wrong number of columns ({len(parts)})"))
            continue
        
        # Parse values
        name = str(name).strip() if name else ""
        line_val_f = safe_float(line_val)
        over_odds_f = safe_float(over_odds)
        under_odds_f = safe_float(under_odds)
        
        if not name:
            bad.append((raw, "Empty player name"))
            continue
            
        if any(v is None for v in (line_val_f, over_odds_f, under_odds_f)):
            bad.append((raw, "Cannot parse numeric fields"))
            continue
        
        rows.append((
            name,
            float(line_val_f),
            float(over_odds_f),
            float(under_odds_f),
            opp_team if pd.notna(opp_team) else None,
            total_match
        ))
    
    return rows, bad


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test sa 7-kolonskim formatom
    test_7col = """PLAYER,PLAYER_TEAM,LINE,OVER_ODDS,UNDER_ODDS,OPP_TEAM,TOTAL_MATCH
Luka Doncic,LAL,32.5,2.00,1.78,DET,225.5
Austin Reaves,LAL,21.5,2.02,1.77,DET,225.5
Victor Wembanyama,SAS,26.5,1.88,1.88,MIA,243.5
Shai Gilgeous-Alexander,OKC,29.5,2.04,1.76,PHI,226.5"""

    # Test sa 6-kolonskim formatom (stari)
    test_6col = """PLAYER,LINE,OVER_ODDS,UNDER_ODDS,OPP_TEAM,TOTAL_MATCH
Luka Doncic,32.5,2.00,1.78,DET,225.5
Austin Reaves,21.5,2.02,1.77,DET,225.5"""

    print("=" * 60)
    print("TEST 7-KOLONSKI FORMAT")
    print("=" * 60)
    rows, bad = parse_offer_text(test_7col)
    print(f"Parsed: {len(rows)} rows, Bad: {len(bad)} rows")
    for r in rows:
        print(f"  {r[0]}: Line={r[1]}, Over={r[2]}, Under={r[3]}, OPP={r[4]}, Total={r[5]}")
    
    print()
    print("=" * 60)
    print("TEST 6-KOLONSKI FORMAT (backward compatible)")
    print("=" * 60)
    rows, bad = parse_offer_text(test_6col)
    print(f"Parsed: {len(rows)} rows, Bad: {len(bad)} rows")
    for r in rows:
        print(f"  {r[0]}: Line={r[1]}, Over={r[2]}, Under={r[3]}, OPP={r[4]}, Total={r[5]}")
    
    print()
    print("=" * 60)
    print("INSTRUKCIJE ZA APP.PY")
    print("=" * 60)
    print("""
1. Pronađi funkciju parse_offer_text() u app.py
2. Zamijeni CIJELU funkciju sa ovom verzijom
3. Pokreni app ponovo: streamlit run app.py
""")
# =====================================================
# Evaluation / Grading / Model compare
# =====================================================

def load_actual_results_csv(uploaded_file: Any) -> Optional[pd.DataFrame]:
    if uploaded_file is None:
        return None
    df = pd.read_csv(uploaded_file)
    rename_map: Dict[str, str] = {}
    for c in df.columns:
        cl = c.lower().strip()
        if   cl in ("player", "player_name", "name"):                rename_map[c] = "Player"
        elif cl in ("actual points", "actual", "pts", "points"):     rename_map[c] = "Actual Points"
        elif cl in ("closing line", "close line", "line close"):     rename_map[c] = "Closing Line"
        elif cl in ("closing over odds", "close over odds"):         rename_map[c] = "Closing Over Odds"
        elif cl in ("closing under odds", "close under odds"):       rename_map[c] = "Closing Under Odds"
    df = df.rename(columns=rename_map)
    if "Player" not in df.columns or "Actual Points" not in df.columns:
        raise ValueError("Results CSV mora imati kolone Player i Actual Points.")
    df["NAME_KEY"]      = df["Player"].astype(str).map(normalize_name)
    df["Actual Points"] = pd.to_numeric(df["Actual Points"], errors="coerce")
    for c in ("Closing Line", "Closing Over Odds", "Closing Under Odds"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def load_prediction_results_csv(uploaded_file: Any) -> Optional[pd.DataFrame]:
    if uploaded_file is None:
        return None
    df = pd.read_csv(uploaded_file)
    rename_map: Dict[str, str] = {}
    for c in df.columns:
        cl = c.lower().strip()
        if   cl in ("player", "player_name", "name"):                rename_map[c] = "Player"
        elif cl in ("line", "market line", "prop line"):              rename_map[c] = "Line"
        elif cl in ("over odds", "overodds", "odds_over"):            rename_map[c] = "Over Odds"
        elif cl in ("under odds", "underodds", "odds_under"):         rename_map[c] = "Under Odds"
        elif cl in ("final projection", "projection", "proj"):        rename_map[c] = "Final Projection"
        elif cl in ("model pick", "pick", "bet", "side"):             rename_map[c] = "Model Pick"
        elif cl in ("projection edge", "edge"):                       rename_map[c] = "Projection Edge"
    df = df.rename(columns=rename_map)
    required = ("Player", "Line", "Over Odds", "Under Odds", "Final Projection", "Model Pick")
    missing  = [c for c in required if c not in df.columns]
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
    if "Closing Line" not in row or pd.isna(row.get("Closing Line")):
        return None
    open_line  = row.get("Line", np.nan)
    close_line = row.get("Closing Line", np.nan)
    pick       = row.get("Model Pick", "")
    if pd.isna(open_line) or pd.isna(close_line):
        return None
    if pick == "OVER":  return float(close_line - open_line)
    if pick == "UNDER": return float(open_line  - close_line)
    return None


def evaluate_engine(pred_df, actual_df, stake=1.0, model_name="Model"):
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
    proj   = pd.to_numeric(merged["Final Projection"], errors="coerce")
    actual = pd.to_numeric(merged["Actual Points"],    errors="coerce")
    merged["Abs Error"] = (proj - actual).abs()
    merged["Sq Error"]  = (proj - actual) ** 2
    merged["CLV"]       = merged.apply(calculate_clv, axis=1)
    graded          = merged[merged["Model Pick"].isin(("OVER", "UNDER"))].copy()
    graded_non_push = graded[graded["Bet Result"].isin(("WIN", "LOSS"))].copy()
    total_bets   = len(graded_non_push)
    wins         = int((graded_non_push["Bet Result"] == "WIN").sum())
    losses       = int((graded_non_push["Bet Result"] == "LOSS").sum())
    pushes       = int((graded["Bet Result"] == "PUSH").sum())
    accuracy     = wins / total_bets * 100.0 if total_bets > 0 else 0.0
    total_profit = float(graded["Profit"].sum())
    total_staked = float(total_bets * stake)
    roi          = total_profit / total_staked * 100.0 if total_staked > 0 else 0.0
    def _sm(s):
        d = s.dropna(); return float(d.mean()) if not d.empty else None
    mae      = _sm(graded["Abs Error"])
    sq_vals  = graded["Sq Error"].dropna()
    rmse     = float(np.sqrt(sq_vals.mean())) if not sq_vals.empty else None
    avg_edge = _sm(graded["Projection Edge"]) if "Projection Edge" in graded.columns else None
    avg_clv  = _sm(graded["CLV"])
    summary  = {
        "Model": model_name, "Bets": total_bets, "Wins": wins, "Losses": losses, "Pushes": pushes,
        "Accuracy %": round(accuracy, 2), "Profit": round(total_profit, 2), "ROI %": round(roi, 2),
        "MAE":  round(mae,      3) if mae      is not None else None,
        "RMSE": round(rmse,     3) if rmse     is not None else None,
        "Avg Projection Edge": round(avg_edge, 3) if avg_edge is not None else None,
        "Avg CLV":             round(avg_clv,  3) if avg_clv  is not None else None,
    }
    return merged, summary


def grade_engine(summary: Dict) -> str:
    acc = float(summary.get("Accuracy %", 0) or 0)
    roi = float(summary.get("ROI %",       0) or 0)
    mae = float(summary.get("MAE",       999) or 999)
    clv = float(summary.get("Avg CLV",     0) or 0)
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


def compare_two_models(summary_a: Dict, summary_b: Dict) -> Tuple[str, pd.DataFrame]:
    def _f(d, k, fb): return float(d.get(k, fb) or fb)
    roi_a, roi_b = _f(summary_a, "ROI %", 0), _f(summary_b, "ROI %", 0)
    acc_a, acc_b = _f(summary_a, "Accuracy %", 0), _f(summary_b, "Accuracy %", 0)
    mae_a, mae_b = _f(summary_a, "MAE", 999), _f(summary_b, "MAE", 999)
    if   roi_a > roi_b: winner = summary_a["Model"]
    elif roi_b > roi_a: winner = summary_b["Model"]
    elif acc_a > acc_b: winner = summary_a["Model"]
    elif acc_b > acc_a: winner = summary_b["Model"]
    elif mae_a < mae_b: winner = summary_a["Model"]
    elif mae_b < mae_a: winner = summary_b["Model"]
    else:               winner = "TIE"
    return winner, pd.DataFrame([summary_a, summary_b])

# =====================================================
# CSV loaders  (Python 3.14 safe – no .map(dict))
# =====================================================

def _s1d(df: pd.DataFrame, col: str) -> pd.Series:
    """Garantiraj 1D Series bez obzira na duplikat kolona."""
    v = df[col]
    return (v.iloc[:, 0] if isinstance(v, pd.DataFrame) else v).reset_index(drop=True)


def _std_rename(df: pd.DataFrame) -> pd.DataFrame:
    rename_map: Dict[str, str] = {}
    for c in df.columns:
        cl = c.strip().upper()
        if   cl in ("PLAYER", "PLAYER_NAME", "NAME"):          rename_map[c] = "PLAYER_NAME"
        elif cl in ("TEAM_ABBR", "TEAM_ABBREVIATION", "TM"):   rename_map[c] = "TEAM_ABBR"
        elif cl in ("TEAM", "TEAM_NAME"):                       rename_map[c] = "TEAM"
        elif cl == "TEAM_ID":                                   rename_map[c] = "TEAM_ID"
    df = df.rename(columns=rename_map)
    if "TEAM_ID" in df.columns:
        _has_abbr      = "TEAM_ABBR" in df.columns
        _abbr_mostly_na = False
        if _has_abbr:
            _col = df["TEAM_ABBR"]
            if isinstance(_col, pd.DataFrame):
                _col = _col.iloc[:, 0]
            _na_mean = _col.isna().mean()
            _abbr_mostly_na = bool(float(_na_mean) > 0.5)
        if not _has_abbr or _abbr_mostly_na:
            df["TEAM_ABBR"] = pd.to_numeric(df["TEAM_ID"], errors="coerce").apply(
                lambda x: TEAM_ID_TO_ABBR.get(int(x)) if pd.notna(x) else None)
    return df


def _dedupe_cols(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[:, ~df.columns.duplicated()]


@st.cache_data(ttl=3600)
def load_teams_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    rename_map: Dict[str, str] = {}
    for c in df.columns:
        cl = c.strip().upper()
        if   cl in ("TEAM", "TEAM_NAME", "NAME"):        rename_map[c] = "TEAM_NAME"
        elif cl == "TEAM_ID":                             rename_map[c] = "TEAM_ID"
        elif cl in ("TEAM_ABBR", "TEAM_ABBREVIATION"):   rename_map[c] = "TEAM_ABBR"
    df = df.rename(columns=rename_map)
    for c in ("OFF_RATING", "DEF_RATING", "PACE", "NET_RATING", "PTS", "OPP_PTS"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "TEAM_ID" in df.columns:
        sample = df["TEAM_ID"].dropna().astype(str).str.strip().head(10)
        if len(sample) and sample.str.fullmatch(r"[A-Z]{2,4}").all():
            df["TEAM_ABBR"]       = df["TEAM_ID"].astype(str).str.strip().str.upper()
            df["TEAM_NUMERIC_ID"] = df["TEAM_ABBR"].apply(
                lambda x: ABBR_TO_TEAM_ID.get(str(x).strip().upper()) if pd.notna(x) else None)
        else:
            if "TEAM_ABBR" in df.columns:
                df["TEAM_ABBR"] = df["TEAM_ABBR"].map(normalize_team_abbr)
            elif "TEAM_NAME" in df.columns:
                df["TEAM_ABBR"] = df["TEAM_NAME"].map(normalize_team_abbr)
            else:
                df["TEAM_ABBR"] = df["TEAM_ID"].map(normalize_team_abbr)
            df["TEAM_NUMERIC_ID"] = pd.to_numeric(df["TEAM_ID"], errors="coerce").fillna(
                pd.Series(df["TEAM_ABBR"].apply(
                    lambda x: ABBR_TO_TEAM_ID.get(str(x).upper()) if pd.notna(x) else None
                ), dtype=object))
    else:
        if "TEAM_ABBR" in df.columns:
            df["TEAM_ABBR"] = df["TEAM_ABBR"].map(normalize_team_abbr)
        elif "TEAM_NAME" in df.columns:
            df["TEAM_ABBR"] = df["TEAM_NAME"].map(normalize_team_abbr)
        else:
            df["TEAM_ABBR"] = np.nan
        df["TEAM_NUMERIC_ID"] = _s1d(df, "TEAM_ABBR").apply(
            lambda x: ABBR_TO_TEAM_ID.get(str(x).strip().upper()) if pd.notna(x) else None)
    if "NET_RATING" not in df.columns:
        if "OFF_RATING" in df.columns and "DEF_RATING" in df.columns:
            df["NET_RATING"] = df["OFF_RATING"] - df["DEF_RATING"]
        elif "PTS" in df.columns and "OPP_PTS" in df.columns:
            df["NET_RATING"] = df["PTS"] - df["OPP_PTS"]
        else:
            df["NET_RATING"] = 0.0
    return df


@st.cache_data(ttl=3600)
def load_players_merged(
    main_path: str,
    base_path: Optional[str] = None,
    adv_path:  Optional[str] = None,
    misc_path: Optional[str] = None,
) -> pd.DataFrame:
    if main_path is None or not os.path.exists(main_path):
        raise ValueError("Glavni players CSV nije pronađen.")

    def _prepare(path: Optional[str], label: str) -> Optional[pd.DataFrame]:
        if path is None or not os.path.exists(path):
            return None
        df = pd.read_csv(path).reset_index(drop=True)
        df = _dedupe_cols(df)
        df = _std_rename(df)
        df = fix_usg_scale(df)
        df[f"SRC_{label}"] = 1
        if "PLAYER_NAME" not in df.columns:
            return None
        df["NAME_KEY"] = df["PLAYER_NAME"].astype(str).map(normalize_name)

        if "TEAM_ABBR" in df.columns:
            df["TEAM_ABBR"] = _s1d(df, "TEAM_ABBR").map(normalize_team_abbr)
        elif "TEAM" in df.columns:
            df["TEAM_ABBR"] = _s1d(df, "TEAM").map(normalize_team_abbr)
        elif "TEAM_ID" in df.columns:
            df["TEAM_ABBR"] = _s1d(df, "TEAM_ID").map(normalize_team_abbr)
        else:
            df["TEAM_ABBR"] = np.nan

        _tid_raw = df.get("TEAM_ID", pd.Series(dtype=float))
        if isinstance(_tid_raw, pd.DataFrame):
            _tid_raw = _tid_raw.iloc[:, 0]
        df["TEAM_NUMERIC_ID"] = pd.to_numeric(_tid_raw, errors="coerce").reset_index(drop=True)

        _abbr_s = _s1d(df, "TEAM_ABBR")
        _mapped = _abbr_s.apply(
            lambda x: ABBR_TO_TEAM_ID.get(str(x).strip().upper()) if pd.notna(x) else None)
        _num    = pd.to_numeric(df["TEAM_NUMERIC_ID"], errors="coerce").reset_index(drop=True)
        df["TEAM_NUMERIC_ID"] = _num.where(_num.notna(), _mapped)
        return df

    main   = _prepare(main_path, "MAIN")
    merged = main.copy()

    update_cols = {
        "TEAM_ABBR", "TEAM_NUMERIC_ID", "GP", "USG_PCT", "TS_PCT", "EFG_PCT",
        "FG3A", "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE", "PIE",
        "PTS_PAINT", "PTS_FB", "PTS_2ND_CHANCE", "PTS_OFF_TOV", "PFD", "PLUS_MINUS",
        "OPP_PTS_OFF_TOV", "OPP_PTS_2ND_CHANCE", "OPP_PTS_FB", "OPP_PTS_PAINT",
        "AST_RATIO", "AST_TO", "AST_PCT", "TOV_PCT", "FG_PCT", "FG3_PCT", "FT_PCT",
    }

    for path, label in ((base_path, "BASE"), (adv_path, "ADV"), (misc_path, "MISC")):
        extra_df = _prepare(path, label)
        if extra_df is None:
            continue
        join_cols = [c for c in ("NAME_KEY", "PLAYER_ID") if c in merged.columns and c in extra_df.columns]
        key       = ["PLAYER_ID"] if "PLAYER_ID" in join_cols else ["NAME_KEY"]
        extra_df  = extra_df.sort_values(key).drop_duplicates(key)
        extra_cols = [c for c in extra_df.columns if c not in merged.columns or c in update_cols]
        extra_slim = extra_df[key + [c for c in extra_cols if c not in key]].copy()
        merged     = merged.merge(extra_slim, on=key, how="left", suffixes=("", "__X"))

        seen_x: set = set()
        for c in list(merged.columns):
            if not c.endswith("__X") or c in seen_x or c not in merged.columns:
                continue
            seen_x.add(c)
            base_col = c[:-3]
            col_x    = _s1d(merged, c)
            if base_col in merged.columns:
                merged[base_col] = _s1d(merged, base_col).combine_first(col_x)
            else:
                merged[base_col] = col_x
            merged = merged.drop(columns=[cc for cc in merged.columns if cc == c], errors="ignore")
            merged = _dedupe_cols(merged)

        merged = _dedupe_cols(merged)

    merged = _dedupe_cols(merged)

    if "PLAYER_NAME" not in merged.columns:
        raise ValueError("players csv missing PLAYER_NAME column.")
    if "MIN" not in merged.columns:
        raise ValueError("players csv missing MIN column.")

    for c in ("MIN","PTS","FGA","FGM","FG_PCT","FG3A","FG3_PCT","FTA","FT_PCT",
              "USG_PCT","TS_PCT","EFG_PCT","TOV_PCT","TM_TOV_PCT","TPAR","FTR",
              "OFF_RATING","DEF_RATING","NET_RATING","PACE","PIE","POSS","AST_PCT",
              "AST_RATIO","AST_TO","REB_PCT","OREB_PCT","DREB_PCT","PTS_PAINT",
              "PTS_FB","PTS_2ND_CHANCE","PTS_OFF_TOV","PFD","PF","BLK","BLKA",
              "OPP_PTS_OFF_TOV","OPP_PTS_2ND_CHANCE","OPP_PTS_FB","OPP_PTS_PAINT",
              "PLUS_MINUS","NBA_FANTASY_PTS","GP","W_PCT"):
        if c in merged.columns:
            merged[c] = pd.to_numeric(merged[c], errors="coerce")

    merged = fix_usg_scale(merged)

    if "FG3A" not in merged.columns or merged["FG3A"].isna().mean() > 0.5:
        if "3PA" in merged.columns:
            fg3a_ex = merged.get("FG3A", pd.Series(dtype=float))
            merged["FG3A"] = fg3a_ex.combine_first(pd.to_numeric(merged["3PA"], errors="coerce"))
        else:
            merged["FG3A"] = np.nan

    merged["TEAM_ABBR"]       = merged["TEAM_ABBR"].map(normalize_team_abbr)
    merged["TEAM_NUMERIC_ID"] = pd.to_numeric(merged["TEAM_NUMERIC_ID"], errors="coerce").fillna(
        merged["TEAM_ABBR"].apply(lambda x: ABBR_TO_TEAM_ID.get(x) if pd.notna(x) else None))

    min_safe          = pd.to_numeric(merged["MIN"], errors="coerce").replace(0, np.nan)
    merged["PPM"]     = (pd.to_numeric(merged.get("PTS"),  errors="coerce") / min_safe).replace([np.inf,-np.inf], np.nan)
    merged["FGA_PM"]  = (pd.to_numeric(merged.get("FGA"),  errors="coerce") / min_safe).replace([np.inf,-np.inf], np.nan)
    merged["FTA_PM"]  = (pd.to_numeric(merged.get("FTA"),  errors="coerce") / min_safe).replace([np.inf,-np.inf], np.nan)
    merged["FG3A_PM"] = (pd.to_numeric(merged.get("FG3A"), errors="coerce") / min_safe).replace([np.inf,-np.inf], np.nan)
    merged["PFD_PM"]  = (pd.to_numeric(merged.get("PFD"),  errors="coerce") / min_safe).replace([np.inf,-np.inf], np.nan)
    merged["POSS_PM"] = (pd.to_numeric(merged.get("POSS"), errors="coerce") / min_safe).replace([np.inf,-np.inf], np.nan)
    merged["PPM"]     = merged["PPM"].fillna(0.55).clip(0.20, 1.25)
    return merged


def load_injuries_csv(path: Optional[str]) -> Optional[pd.DataFrame]:
    if path is None or not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    rename_map: Dict[str, str] = {}
    for c in df.columns:
        cl = c.strip().upper()
        if   cl in ("PLAYER", "PLAYER_NAME", "NAME"):      rename_map[c] = "PLAYER"
        elif cl in ("TEAM", "TEAM_NAME"):                   rename_map[c] = "TEAM"
        elif cl in ("TEAM_ABBR", "TEAM_ABBREVIATION"):      rename_map[c] = "TEAM_ABBR"
        elif cl in ("DESCRIPTION", "STATUS_NOTE", "NOTE"):  rename_map[c] = "DESCRIPTION"
    df = df.rename(columns=rename_map)
    if "TEAM_ABBR" in df.columns:
        df["TEAM_ABBR"] = df["TEAM_ABBR"].map(normalize_team_abbr)
    elif "TEAM" in df.columns:
        df["TEAM_ABBR"] = df["TEAM"].map(normalize_team_abbr)
    else:
        df["TEAM_ABBR"] = np.nan
    if "STATUS" not in df.columns:
        df["STATUS"] = df["DESCRIPTION"].astype(str).map(extract_injury_status) \
                       if "DESCRIPTION" in df.columns else "UNKNOWN"
    if "PLAYER" in df.columns:
        df["NAME_KEY"] = df["PLAYER"].astype(str).map(normalize_name)
    return df


def load_l10_csv(path: Optional[str]) -> Optional[pd.DataFrame]:
    if path is None or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        rename: Dict[str, str] = {}
        for c in df.columns:
            cl = c.strip().upper()
            if   cl in ("PLAYER_NAME","PLAYER","NAME","IME_IGRAČA","IME_IGRACA"): rename[c] = "PLAYER_NAME"
            elif cl in ("L10_PTS","L10_BODOVI"):   rename[c] = "L10_PTS"
            elif cl in ("L5_PTS","L5_BODOVI"):     rename[c] = "L5_PTS"
            elif cl in ("L3_PTS","L3_BODOVI"):     rename[c] = "L3_PTS"
            elif cl == "L10_MIN":                  rename[c] = "L10_MIN"
            elif cl == "L10_STD":                  rename[c] = "L10_STD"
            elif cl in ("TREND_SLOPE","NAGIB_TRENDA"): rename[c] = "TREND_SLOPE"
            elif cl in ("LAST_PTS","ZADNJE_BODOVI"): rename[c] = "LAST_PTS"
            elif cl in ("NAME_KEY","KLJUČ_IMENA","KLJUC_IMENA"): rename[c] = "NAME_KEY"
        df = df.rename(columns=rename)
        for col in ("L10_PTS","L5_PTS","L3_PTS","L10_MIN","L10_STD","TREND_SLOPE","LAST_PTS"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "NAME_KEY" not in df.columns or df["NAME_KEY"].isna().all():
            if "PLAYER_NAME" in df.columns:
                df["NAME_KEY"] = df["PLAYER_NAME"].astype(str).map(normalize_name)
        return df
    except Exception:
        return None


def _load_matchup_csv(path: Optional[str], skip_cols: Tuple[str, ...]) -> Optional[pd.DataFrame]:
    if path is None or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if "TEAM_ABBREVIATION" in df.columns:
            df = df.rename(columns={"TEAM_ABBREVIATION": "TEAM_ABBR"})
        if "TEAM_ID" in df.columns and "TEAM_ABBR" not in df.columns:
            df["TEAM_ABBR"] = df["TEAM_ID"].apply(lambda x: TEAM_ID_TO_ABBR.get(x))
        for col in df.columns:
            if col not in skip_cols:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception:
        return None


def load_def_matchup_csv(path: Optional[str]) -> Optional[pd.DataFrame]:
    return _load_matchup_csv(path, skip_cols=("TEAM_ABBR","TEAM_NAME","POSITION","TEAM_ID"))


def load_off_matchup_csv(path: Optional[str]) -> Optional[pd.DataFrame]:
    return _load_matchup_csv(path, skip_cols=("TEAM_ABBR","TEAM_NAME","TEAM_ID"))


def load_h2h_csv(path: Optional[str]) -> Optional[pd.DataFrame]:
    if path is None or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        rename_map: Dict[str, str] = {}
        for c in df.columns:
            cl = c.strip().upper()
            if   cl in ("PLAYER_NAME","PLAYER","NAME","IME_IGRAČA","IME_IGRACA"): rename_map[c] = "PLAYER_NAME"
            elif cl in ("OPP_TEAM","OPP_TIM","PROTIVNIK","OPPONENT"): rename_map[c] = "OPP_TEAM"
            elif cl in ("H2H_PTS_AVG","PROSJEK_BODOVA_U_H2H"): rename_map[c] = "H2H_PTS_AVG"
            elif cl in ("H2H_GAMES","U_H2H_IGRAMA"):            rename_map[c] = "H2H_GAMES"
            elif cl in ("H2H_PTS_LAST","POSLJEDNJI_BOD_U_H2H"): rename_map[c] = "H2H_PTS_LAST"
            elif cl in ("NAME_KEY","KLJUČ_IMENA","KLJUC_IMENA"): rename_map[c] = "NAME_KEY"
        df = df.rename(columns=rename_map)
        for col in ("H2H_PTS_AVG","H2H_PTS_LAST","H2H_GAMES"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "NAME_KEY" not in df.columns or df["NAME_KEY"].isna().all():
            if "PLAYER_NAME" in df.columns:
                df["NAME_KEY"] = df["PLAYER_NAME"].astype(str).map(normalize_name)
        return df
    except Exception:
        return None


def load_b2b_csv(path: Optional[str]) -> Optional[pd.DataFrame]:
    if path is None or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        rename: Dict[str, str] = {}
        for c in df.columns:
            cl = c.strip().upper()
            if cl == "GAME_DATE": rename[c] = "GAME_DATE"
            elif cl == "TEAM_ABBR": rename[c] = "TEAM_ABBR"
            elif cl == "IS_B2B":    rename[c] = "IS_B2B"
        df = df.rename(columns=rename)
        if "GAME_DATE" not in df.columns or "TEAM_ABBR" not in df.columns:
            return None
        df["IS_B2B"]    = df["IS_B2B"].astype(str).str.lower().isin(("true","1","yes"))
        df["GAME_DATE"] = df["GAME_DATE"].astype(str).str.strip()
        df["TEAM_ABBR"] = df["TEAM_ABBR"].astype(str).str.strip().str.upper()
        return df
    except Exception:
        return None

# =====================================================
# Team / player lookup helpers
# =====================================================

def is_team_b2b(b2b_df: Optional[pd.DataFrame], team_abbr: str, game_date: str) -> bool:
    if b2b_df is None or not team_abbr or not game_date:
        return False
    mask = ((b2b_df["TEAM_ABBR"] == str(team_abbr).strip().upper()) &
            (b2b_df["GAME_DATE"] == str(game_date).strip()))
    row = b2b_df[mask]
    return bool(row["IS_B2B"].iloc[0]) if not row.empty else False


def _find_team_row_by_abbr(teams_df: pd.DataFrame, abbr: str) -> Optional[pd.Series]:
    if not abbr or teams_df is None or teams_df.empty:
        return None
    abbr = str(abbr).strip().upper()
    if "TEAM_ABBR" in teams_df.columns:
        tr = teams_df[teams_df["TEAM_ABBR"].astype(str).str.upper() == abbr]
        if not tr.empty:
            return tr.iloc[0]
    return None


def estimate_match_total(
    team_row: Optional[pd.Series], opp_row: Optional[pd.Series],
    pace_game: Optional[float], teams_df: pd.DataFrame,
) -> Optional[float]:
    if team_row is None or opp_row is None:
        return None
    league_off = float(pd.to_numeric(teams_df.get("OFF_RATING", pd.Series([115.0])), errors="coerce").dropna().mean() or 115.0)
    league_def = float(pd.to_numeric(teams_df.get("DEF_RATING", pd.Series([115.0])), errors="coerce").dropna().mean() or 115.0)
    if pace_game is None:
        pace_game = (_get_float(team_row,"PACE",99.0) + _get_float(opp_row,"PACE",99.0)) / 2.0
    team_off = _get_float(team_row, "OFF_RATING", league_off)
    opp_off  = _get_float(opp_row,  "OFF_RATING", league_off)
    team_def = _get_float(team_row, "DEF_RATING", league_def)
    opp_def  = _get_float(opp_row,  "DEF_RATING", league_def)
    team_pts = team_off * pace_game / 100.0 * _clamp(league_def / max(opp_def,  1e-6), 0.92, 1.08)
    opp_pts  = opp_off  * pace_game / 100.0 * _clamp(league_def / max(team_def, 1e-6), 0.92, 1.08)
    return float(_clamp(team_pts + opp_pts, 180.0, 265.0))


def match_player_row(players_df: pd.DataFrame, offer_name: str) -> Tuple[Optional[pd.Series], str, str]:
    name_raw = str(offer_name or "").strip()
    key      = normalize_name(name_raw)
    if not key:
        return None, key, "EMPTY_KEY"
    pr = players_df[players_df["NAME_KEY"] == key]
    if not pr.empty:
        return pr.sort_values(["MIN","GP"], ascending=False, na_position="last").iloc[0], key, "EXACT"
    if "," in name_raw:
        key2 = normalize_name(" ".join(p.strip() for p in name_raw.split(",")[::-1]))
        pr   = players_df[players_df["NAME_KEY"] == key2]
        if not pr.empty:
            return pr.sort_values(["MIN","GP"], ascending=False, na_position="last").iloc[0], key2, "LAST_FIRST"
    toks = key.split()
    if len(toks) == 2 and len(toks[0]) == 1:
        fi, ln = toks
        pr = players_df[
            players_df["NAME_KEY"].str.contains(rf"\b{re.escape(ln)}\b", na=False) &
            players_df["NAME_KEY"].str.contains(rf"\b{re.escape(fi)}",   na=False)]
        if not pr.empty:
            return pr.sort_values(["MIN","GP"], ascending=False, na_position="last").iloc[0], key, "INITIAL_LAST"
    toks = [t for t in key.split() if len(t) >= 3]
    if toks:
        mask = np.ones(len(players_df), dtype=bool)
        for t in toks:
            mask &= players_df["NAME_KEY"].str.contains(re.escape(t), na=False)
        pr = players_df[mask]
        if not pr.empty:
            return pr.sort_values(["MIN","GP"], ascending=False, na_position="last").iloc[0], key, "TOKENS"
    all_keys = players_df["NAME_KEY"].dropna().astype(str).tolist()
    best     = difflib.get_close_matches(key, all_keys, n=1, cutoff=0.86)
    if best:
        pr = players_df[players_df["NAME_KEY"] == best[0]]
        if not pr.empty:
            return pr.sort_values(["MIN","GP"], ascending=False, na_position="last").iloc[0], best[0], "DIFFLIB"
    return None, key, "NOT_FOUND"

# =====================================================
# Core projection engine  (from doc 3 – with B2B/Home/Away/Rest)
# =====================================================

def build_player_context(
    r0:                   pd.Series,
    players_df:           pd.DataFrame,
    teams_df:             pd.DataFrame,
    team_row:             Optional[pd.Series],
    opp_row:              Optional[pd.Series],
    inj_df:               Optional[pd.DataFrame],
    team_abbr:            Any,
    player_name_key:      str,
    total_match_used:     Optional[float],
    recent_form_override: Optional[Dict[str, float]] = None,
    h2h_df:               Optional[pd.DataFrame]     = None,
    opp_team_abbr:        Optional[str]               = None,
    l10_df:               Optional[pd.DataFrame]      = None,
    def_matchup_df:       Optional[pd.DataFrame]      = None,
    off_matchup_df:       Optional[pd.DataFrame]      = None,
    line_val:             float                        = 0.0,
    b2b_team:             bool                         = False,
    b2b_opp:              bool                         = False,
    is_home:              bool                         = True,
    rest_days:            int                          = 2,
    opp_rest_days:        int                          = 2,
) -> Dict[str, Any]:
    if recent_form_override is None:
        recent_form_override = {}

    season_pts = float(_get_float(r0, "PTS", 0.0) or 0.0)
    season_min = float(_get_float(r0, "MIN", 0.0) or 0.0)
    usg        = float(_get_float(r0, "USG_PCT", np.nan) or np.nan)
    ppm        = float(_get_float(r0, "PPM", np.nan) or np.nan)
    if not np.isfinite(ppm) or ppm <= 0:
        ppm = season_pts / max(season_min, 1.0)
    if season_min < 20 and np.isfinite(ppm) and ppm > 0.60:
        ppm = 0.60 * ppm + 0.40 * 0.55

    def _league(df, col, fb):
        return float(pd.to_numeric(df.get(col, pd.Series([fb])), errors="coerce").dropna().mean() or fb)

    league_pace        = _league(teams_df,   "PACE",        99.0)
    league_def         = _league(teams_df,   "DEF_RATING",  115.0)
    league_off         = _league(teams_df,   "OFF_RATING",  115.0)
    league_total_proxy = league_off * 2.0
    league_ts          = _league(players_df, "TS_PCT",       0.56)
    league_efg         = _league(players_df, "EFG_PCT",      0.54)
    league_usg         = _league(players_df, "USG_PCT",     20.0)
    league_fga_pm      = _league(players_df, "FGA_PM",       0.35)
    league_fta_pm      = _league(players_df, "FTA_PM",       0.12)
    if league_usg < 5.0:
        league_usg *= 100.0

    team_pace   = _get_float(team_row, "PACE", league_pace) if team_row is not None else league_pace
    opp_pace    = _get_float(opp_row,  "PACE", league_pace) if opp_row  is not None else league_pace
    pace_game   = (team_pace + opp_pace) / 2.0 if opp_row is not None else team_pace
    pace_factor = _clamp(1.0 + 0.08 * (pace_game / league_pace - 1.0), 0.94, 1.07)

    team_off         = _get_float(team_row, "OFF_RATING", league_off) if team_row is not None else league_off
    opp_def          = _get_float(opp_row,  "DEF_RATING", league_def) if opp_row  is not None else league_def
    team_eff_matchup = _clamp((team_off / league_off) * (league_def / max(opp_def, 1e-6)), 0.94, 1.08)

    total_factor = 1.0
    if total_match_used is not None and np.isfinite(total_match_used):
        total_factor = _clamp(1.0 + 0.25 * (float(total_match_used) / league_total_proxy - 1.0), 0.90, 1.12)

    gp           = _get_float(r0, "GP", 20.0)
    minutes_proj = season_min

    team_net     = _get_float(team_row, "NET_RATING", 0.0) if team_row is not None else 0.0
    opp_net      = _get_float(opp_row,  "NET_RATING", 0.0) if opp_row  is not None else 0.0
    mins_context = _clamp(1.0 - 0.012 * abs((team_net or 0) - (opp_net or 0)) / 10.0, 0.97, 1.02)

    injury_boost = direct_player_penalty = 1.0
    injured_usage_lost = injured_minutes_lost = 0.0

    if inj_df is not None and team_abbr:
        team_inj = inj_df[inj_df["TEAM_ABBR"].astype(str).str.upper() == str(team_abbr).upper()].copy()
        if not team_inj.empty:
            team_inj["W"] = team_inj["STATUS"].astype(str).map(_status_weight).fillna(0.0)
            if "NAME_KEY" in team_inj.columns:
                self_row = team_inj[team_inj["NAME_KEY"] == player_name_key]
                if not self_row.empty:
                    self_status = str(self_row["STATUS"].iloc[0]).upper().strip()
                    direct_player_penalty = {
                        "OUT": 0.0, "INACTIVE": 0.0, "DOUBTFUL": 0.75,
                        "QUESTIONABLE": 0.92, "PROBABLE": 0.97,
                    }.get(self_status, 1.0)
            teammate_inj = team_inj[team_inj["NAME_KEY"] != player_name_key] \
                           if "NAME_KEY" in team_inj.columns else team_inj
            if not teammate_inj.empty and "NAME_KEY" in teammate_inj.columns:
                teammate_pool = players_df[players_df["NAME_KEY"].isin(teammate_inj["NAME_KEY"])]
                if not teammate_pool.empty:
                    temp = teammate_pool[["NAME_KEY","USG_PCT","MIN"]].copy().merge(
                        teammate_inj[["NAME_KEY","W"]], on="NAME_KEY", how="left")
                    injured_usage_lost   = float((temp["USG_PCT"].fillna(0)*temp["W"].fillna(0)).sum())
                    injured_minutes_lost = float((temp["MIN"].fillna(0)*temp["W"].fillna(0)).sum())
                    if injured_minutes_lost > 200:
                        gp_avg = pd.to_numeric(players_df.get("GP", pd.Series([40])), errors="coerce").dropna().mean() or 40
                        injured_minutes_lost /= max(gp_avg, 1)
                    injured_minutes_lost = min(injured_minutes_lost, 95.0)
                    injured_usage_lost   = min(injured_usage_lost,   62.0)

                    out_inj      = team_inj[team_inj["STATUS"].astype(str).str.upper() == "OUT"]
                    has_star_out = False; star_usg_lost = 0.0
                    if not out_inj.empty and "NAME_KEY" in out_inj.columns:
                        star_pool = players_df[
                            players_df["NAME_KEY"].isin(out_inj["NAME_KEY"]) &
                            (pd.to_numeric(players_df["USG_PCT"], errors="coerce") >= 28)]
                        if not star_pool.empty:
                            has_star_out  = True
                            star_usg_lost = float(star_pool["USG_PCT"].sum())

                    player_position_score = 0.0
                    if not out_inj.empty and "NAME_KEY" in out_inj.columns:
                        out_players = players_df[players_df["NAME_KEY"].isin(out_inj["NAME_KEY"])].copy()
                        cur_usg = usg if np.isfinite(usg) else 20.0
                        for _, op in out_players.iterrows():
                            out_usg = float(_get_float(op,"USG_PCT",0) or 0)
                            out_min = float(_get_float(op,"MIN",    0) or 0)
                            usg_sim = max(0.0, 1.0 - abs(cur_usg-out_usg)/max(out_usg,1.0))
                            min_sim = max(0.0, 1.0 - abs(season_min-out_min)/max(out_min,1.0))
                            player_position_score = max(player_position_score, 0.65*usg_sim+0.35*min_sim)
                        player_position_score = float(np.clip(player_position_score, 0.0, 1.0))

                    injury_boost = compute_injury_boost_v2(
                        injured_usage_lost, injured_minutes_lost,
                        usg if np.isfinite(usg) else 20.0,
                        has_star_out, star_usg_lost,
                        player_position_score=player_position_score,
                        n_active_teammates=max(1, 8-len(out_inj)),
                    )

    minutes_proj  = minutes_proj * mins_context * pace_factor * direct_player_penalty
    minutes_proj *= _clamp(1.0 + 0.0004 * injured_minutes_lost, 0.99, 1.04)
    minutes_proj  = _clamp(minutes_proj, 8.0, 40.0)
    cap_pct = {34: 1.02, 28: 1.04, 20: 1.06}
    for threshold, cap in cap_pct.items():
        if season_min >= threshold:
            minutes_proj = min(minutes_proj, season_min * cap); break
    else:
        minutes_proj = min(minutes_proj, season_min * 1.10)
    minutes_proj = _clamp(minutes_proj, 8.0, 40.0)

    usage_factor = _clamp(
        1.0 + 0.15 * ((usg - league_usg) / league_usg) if np.isfinite(usg) and league_usg > 0 else 1.0,
        0.85, 1.15)

    ts        = _get_float(r0, "TS_PCT",    league_ts)
    efg       = _get_float(r0, "EFG_PCT",   league_efg)
    fg_pct    = _get_float(r0, "FG_PCT",    0.46)
    ft_pct    = _get_float(r0, "FT_PCT",    0.76)
    fg3_pct   = _get_float(r0, "FG3_PCT",   0.36)
    fga_pm    = _get_float(r0, "FGA_PM",    league_fga_pm)
    fta_pm    = _get_float(r0, "FTA_PM",    league_fta_pm)
    pie       = _get_float(r0, "PIE",       0.08)
    ast_ratio = _get_float(r0, "AST_RATIO", 15.0)
    ast_to    = _get_float(r0, "AST_TO",    1.5)
    tov_pct   = _get_float(r0, "TOV_PCT",   _get_float(r0, "TM_TOV_PCT", 12.0))
    net_rating_player = _get_float(r0, "NET_RATING",  0.0)
    plus_minus        = _get_float(r0, "PLUS_MINUS",  0.0)
    fg3a_raw  = _get_float(r0, "FG3A",    None)
    fg3a_pm   = _get_float(r0, "FG3A_PM", None)
    if fg3a_pm is None or not np.isfinite(fg3a_pm):
        fg3a_pm = (fg3a_raw/season_min) if (fg3a_raw and np.isfinite(fg3a_raw) and season_min > 0) else 0.12

    shot_factor = _clamp(1.0 + 0.10*((fga_pm-league_fga_pm)/max(league_fga_pm,1e-6)), 0.92, 1.10)
    ft_pct_adj  = _clamp((ft_pct-0.76)*0.05,-0.03,0.05) if ft_pct and np.isfinite(ft_pct) else 0.0
    ft_factor   = _clamp(1.0 + 0.08*((fta_pm-league_fta_pm)/max(league_fta_pm,1e-6))+ft_pct_adj, 0.94, 1.10)
    fg3_adj     = _clamp((fg3_pct-0.36)*0.08,-0.03,0.04) if fg3_pct and np.isfinite(fg3_pct) else 0.0
    efficiency_factor = _clamp(
        1.0 + 0.10*((ts-league_ts)/max(league_ts,1e-6))
            + 0.06*((efg-league_efg)/max(league_efg,1e-6))
            + 0.02*(fg_pct-0.46) + fg3_adj, 0.92, 1.12)
    playmaking_factor = _clamp(1.0+0.012*((ast_ratio-15.0)/5.0)+0.008*(ast_to-1.5), 0.97, 1.04)
    turnover_factor   = _clamp(1.0-0.035*((tov_pct-12.0)/12.0), 0.95, 1.04)
    net_adj           = _clamp(net_rating_player/10.0,-0.03,0.03) if net_rating_player and np.isfinite(net_rating_player) \
                        else _clamp(plus_minus/40.0,-0.02,0.02)
    role_factor       = _clamp(1.0+0.15*(pie-0.08)+net_adj, 0.93, 1.07)

    pts_paint = _get_float(r0,"PTS_PAINT",None); pts_fb = _get_float(r0,"PTS_FB",None)
    pts_2nd   = _get_float(r0,"PTS_2ND_CHANCE",None); pts_off_tov = _get_float(r0,"PTS_OFF_TOV",None)
    league_pts_paint   = _league(players_df,"PTS_PAINT",      4.5)
    league_pts_fb      = _league(players_df,"PTS_FB",         1.5)
    league_pts_2nd     = _league(players_df,"PTS_2ND_CHANCE", 1.2)
    league_pts_off_tov = _league(players_df,"PTS_OFF_TOV",    2.5)

    def _rel_adj(val, lg, w, lo, hi):
        return _clamp(w*((val-lg)/lg), lo, hi) if val is not None and np.isfinite(val) and lg > 0 else 0.0

    style_factor = _clamp(
        1.0 + 0.012*((fg3a_pm-0.12)/0.10)
        + _rel_adj(pts_paint,   league_pts_paint,   0.015,-0.02,0.02)
        + _rel_adj(pts_fb,      league_pts_fb,      0.010,-0.01,0.015)
        + _rel_adj(pts_2nd,     league_pts_2nd,     0.008,-0.01,0.012)
        + _rel_adj(pts_off_tov, league_pts_off_tov, 0.007,-0.01,0.010), 0.95, 1.06)

    opp_shooting_adj = 1.0; opp_fg_pct = opp_fg3_pct = None
    if def_matchup_df is not None and opp_team_abbr is not None:
        try:
            dm = def_matchup_df[def_matchup_df["TEAM_ABBR"].astype(str).str.upper() == str(opp_team_abbr).upper()]
            if not dm.empty:
                opp_fg_pct  = float(dm["OPP_FG_PCT"].iloc[0])  if "OPP_FG_PCT"  in dm.columns else None
                opp_fg3_pct = float(dm["OPP_FG3_PCT"].iloc[0]) if "OPP_FG3_PCT" in dm.columns else None
        except Exception:
            pass
    if opp_fg_pct  is not None: opp_shooting_adj *= _clamp(1.0+0.05*((opp_fg_pct -0.470)/0.470),0.97,1.03)
    if opp_fg3_pct is not None: opp_shooting_adj *= _clamp(1.0+0.03*((opp_fg3_pct-0.360)/0.360),0.98,1.02)

    opp_pts_off_tov_p = _get_float(r0,"OPP_PTS_OFF_TOV",None)
    opp_pts_2nd_p     = _get_float(r0,"OPP_PTS_2ND_CHANCE",None)
    opp_pts_fb_p      = _get_float(r0,"OPP_PTS_FB",None)
    opp_pts_paint_p   = _get_float(r0,"OPP_PTS_PAINT",None)
    league_opp_pts_paint = _league(players_df,"OPP_PTS_PAINT",     4.5)
    league_opp_pts_fb    = _league(players_df,"OPP_PTS_FB",        1.5)
    league_opp_pts_2nd   = _league(players_df,"OPP_PTS_2ND_CHANCE",1.2)

    def _sma(pv, pl, ov, ol, w, lo, hi):
        if pv is not None and np.isfinite(pv) and pv > 0 and ov is not None and np.isfinite(ov) and ol > 0:
            return _clamp(w*((pv-pl)/max(pl,1e-6))*np.sign((ov-ol)/max(ol,1e-6)), lo, hi)
        return 0.0

    opp_style_matchup = _clamp(
        1.0 + _sma(pts_paint,league_pts_paint,opp_pts_paint_p,league_opp_pts_paint,0.015,-0.015,0.015)
            + _sma(pts_fb,   league_pts_fb,   opp_pts_fb_p,   league_opp_pts_fb,   0.010,-0.010,0.010)
            + _sma(pts_2nd,  league_pts_2nd,  opp_pts_2nd_p,  league_opp_pts_2nd,  0.008,-0.008,0.008),
        0.96, 1.04)

    base_raw      = ppm * minutes_proj
    season_anchor = season_pts * (minutes_proj / max(season_min, 1.0)) if season_min > 0 else base_raw
    star_w        = _clamp((usg-24.0)/16.0 if np.isfinite(usg) else 0.15, 0.12, 0.40)
    anchored_projection = (1.0-star_w)*base_raw + star_w*season_anchor
    if season_pts > 0:
        anchored_projection = _clamp(anchored_projection, season_pts*0.70, season_pts*1.30)

    # DEF matchup blok 1
    def_factor_b1 = 1.0
    if def_matchup_df is not None and opp_team_abbr is not None:
        try:
            pts_col = next((c for c in ("OPP_PTS","PTS","FREQ_PTS") if c in def_matchup_df.columns), None)
            if "TEAM_ABBR" in def_matchup_df.columns and pts_col:
                dm = def_matchup_df[def_matchup_df["TEAM_ABBR"].astype(str).str.upper() == str(opp_team_abbr).upper()]
                if not dm.empty:
                    opp_pts_a = float(dm[pts_col].iloc[0]); lg_avg = float(def_matchup_df[pts_col].mean())
                    if lg_avg > 0: def_factor_b1 = _clamp(opp_pts_a/lg_avg, 0.90, 1.12)
        except Exception:
            pass
    if def_factor_b1 == 1.0 and opp_def is not None and np.isfinite(opp_def) and league_def > 0:
        def_factor_b1 = 1.0 + 0.60 * (_clamp(opp_def/league_def, 0.92, 1.10) - 1.0)
    anchored_projection *= def_factor_b1

    # L10/L5/L3 forma
    l10_pts = l10_trend = l5_pts = l3_pts = None
    if l10_df is not None and "NAME_KEY" in l10_df.columns:
        l10_row = l10_df[l10_df["NAME_KEY"] == player_name_key]
        if not l10_row.empty:
            r = l10_row.iloc[0]
            l10_pts   = float(_get_float(r,"L10_PTS",None) or 0) or None
            l5_pts    = float(_get_float(r,"L5_PTS", None) or 0) or None
            l3_pts    = float(_get_float(r,"L3_PTS", None) or 0) or None
            l10_trend = float(_get_float(r,"TREND_SLOPE",None) or 0.0)

    if l10_pts is not None and l10_pts > 0:
        if l3_pts and l3_pts > 0:
            d35 = abs(l3_pts-(l5_pts or l10_pts))
            effective_form = (0.50*l3_pts+0.35*(l5_pts or l10_pts)+0.15*l10_pts if d35 < 4.0
                              else 0.30*l3_pts+0.50*(l5_pts or l10_pts)+0.20*l10_pts)
        elif l5_pts and l5_pts > 0:
            d = abs(l5_pts-l10_pts)
            effective_form = (0.72*l5_pts+0.28*l10_pts if d > 4.0 else
                              0.65*l5_pts+0.35*l10_pts if d > 2.0 else 0.55*l5_pts+0.45*l10_pts)
        else:
            effective_form = l10_pts
        form_diff    = abs(effective_form-season_pts)
        form_consist = (l5_pts is not None and l10_pts is not None and (
            (l5_pts>season_pts and l10_pts>season_pts) or (l5_pts<season_pts and l10_pts<season_pts)))
        if   form_diff > 6.0: fw = 0.88 if form_consist else 0.82
        elif form_diff > 4.0: fw = 0.80 if form_consist else 0.74
        elif form_diff > 2.0: fw = 0.70 if form_consist else 0.64
        else:                 fw = 0.58
        form_anchor = effective_form*(minutes_proj/max(season_min,1.0))
        anchored_projection = (1.0-fw)*anchored_projection + fw*form_anchor
        if l10_trend is not None and abs(l10_trend) > 0.50:
            trend_adj = _clamp(1.0+0.018*l10_trend, 0.93 if form_consist else 0.95, 1.07 if form_consist else 1.05)
            anchored_projection *= trend_adj

    if (l5_pts and l10_pts and line_val > 0 and direct_player_penalty > 0.5
            and l5_pts > line_val*1.05 and l10_pts > line_val*1.05):
        floor_p = line_val*0.85
        if anchored_projection < floor_p:
            anchored_projection = (anchored_projection+floor_p)/2.0

    # DEF matchup blok 2
    def_factor_b2 = 1.0
    if def_matchup_df is not None and opp_team_abbr is not None:
        try:
            pos_col  = next((c for c in ("POSITION","PLAYER_POSITION","POS") if c in def_matchup_df.columns), None)
            pts_col2 = next((c for c in ("FREQ_PTS","PTS_PCT","PTS","FGA")  if c in def_matchup_df.columns), None)
            if pos_col and pts_col2 and "TEAM_ABBR" in def_matchup_df.columns:
                pg = ("Guard" if np.isfinite(usg) and usg >= 30 else
                      "Forward" if np.isfinite(usg) and usg >= 26 else
                      "Forward" if season_min >= 28 else "Center")
                dm = def_matchup_df[
                    (def_matchup_df["TEAM_ABBR"].astype(str).str.upper() == str(opp_team_abbr).upper()) &
                    (def_matchup_df[pos_col].astype(str).str.contains(pg, case=False, na=False))]
                if not dm.empty:
                    val = float(dm[pts_col2].iloc[0])
                    avg = float(def_matchup_df[def_matchup_df[pos_col].astype(str).str.contains(pg,case=False,na=False)][pts_col2].mean()) or val
                    if avg > 0: def_factor_b2 = _clamp(val/avg, 0.88, 1.14)
            if def_factor_b2 == 1.0 and "TEAM_ABBR" in def_matchup_df.columns:
                efg_col = next((c for c in ("EFG_PCT","FG_PCT","FG2_PCT") if c in def_matchup_df.columns), None)
                if efg_col:
                    dm = def_matchup_df[def_matchup_df["TEAM_ABBR"].astype(str).str.upper() == str(opp_team_abbr).upper()]
                    if not dm.empty:
                        oe = float(dm[efg_col].mean()); le = float(def_matchup_df[efg_col].mean())
                        if le > 0 and oe > 0: def_factor_b2 = _clamp(oe/le, 0.92, 1.10)
        except Exception:
            pass
    anchored_projection *= _clamp(def_factor_b2, 0.90, 1.10)
    def_matchup_factor   = round(_clamp(def_factor_b1*def_factor_b2, 0.85, 1.20), 4)

    # Recent Form
    recent_pts   = recent_form_override.get(player_name_key)
    is_auto_form = False
    if recent_pts is None and l5_pts and l5_pts > 0:
        recent_pts = l5_pts; is_auto_form = True
    if recent_pts and recent_pts > 0:
        diff = abs(recent_pts-season_pts)
        rw   = (0.18 if diff>5 else 0.10) if is_auto_form else (0.85 if diff>5 else 0.75)
        anchored_projection = (1.0-rw)*anchored_projection + rw*recent_pts*(minutes_proj/max(season_min,1.0))

    # H2H
    h2h_pts = h2h_pts_last = None; h2h_games = 0; h2h_sigma_boost = 1.0
    if h2h_df is not None and opp_team_abbr is not None:
        mask    = (h2h_df["NAME_KEY"] == player_name_key) & \
                  (h2h_df["OPP_TEAM"].astype(str).str.upper() == str(opp_team_abbr).upper())
        h2h_row = h2h_df[mask]
        if not h2h_row.empty:
            h2h_pts      = float(_get_float(h2h_row.iloc[0],"H2H_PTS_AVG", None) or 0) or None
            h2h_games    = int(_get_float(h2h_row.iloc[0],  "H2H_GAMES",   0)    or 0)
            h2h_pts_last = float(_get_float(h2h_row.iloc[0],"H2H_PTS_LAST",None) or 0) or None
    h2h_display_pts = h2h_pts if (h2h_pts and h2h_games > 0) else (round(season_pts,1) if season_pts>0 else None)
    if h2h_pts and h2h_pts > 0 and h2h_games >= 2:
        h2h_anchor = h2h_pts*(minutes_proj/max(season_min,1.0))
        h2h_diff   = abs(h2h_pts-season_pts)
        h2h_weight = _clamp(0.15+0.06*h2h_games, 0.25, 0.45)
        if recent_pts is None or is_auto_form:
            h2h_weight = _clamp(h2h_weight*1.4, 0.25, 0.55)
        if season_pts > 0:
            hr = h2h_pts/max(season_pts,1.0)
            if   hr > 2.0: h2h_weight = 0.0
            elif hr > 1.5: h2h_weight = min(h2h_weight,0.08)
            elif hr > 1.3: h2h_weight = min(h2h_weight,0.15)
            elif hr < 0.5: h2h_weight = min(h2h_weight,0.08)
            elif hr < 0.7: h2h_weight = min(h2h_weight,0.15)
        if l5_pts and l5_pts>0 and h2h_weight>0 and abs(h2h_pts-l5_pts)<3.0:
            h2h_weight = min(h2h_weight*1.2, 0.55)
        if h2h_weight > 0:
            anchored_projection = (1.0-h2h_weight)*anchored_projection + h2h_weight*h2h_anchor
        h2h_sigma_boost = 1.08 if h2h_diff > 6 else 1.0

    # B2B faktor
    b2b_factor = 1.0
    if b2b_team:
        cur_usg = usg if np.isfinite(usg) else 20.0
        if cur_usg >= 28:    minutes_proj *= 0.94; b2b_factor = 0.94
        elif cur_usg >= 22:  minutes_proj *= 0.97; b2b_factor = 0.97
        else:
            if not is_home:  minutes_proj *= 0.99; b2b_factor = 0.99
            else:            minutes_proj *= 1.02; b2b_factor = 1.02
        minutes_proj = _clamp(minutes_proj, 8.0, 40.0)
    if b2b_opp:
        b2b_factor = _clamp(b2b_factor*1.02, 0.90, 1.10)

    # Home/Away faktor
    if is_home:
        home_away_factor = 1.02
    else:
        home_away_factor = 0.975 if b2b_team else 0.985

    # Rest Days faktor
    rest_factor = 1.0
    if rest_days == 1:
        rest_factor = 0.98 if (usg if np.isfinite(usg) else 20.0) >= 25 else 1.0
    elif rest_days >= 3:
        rest_factor = _clamp(1.0+0.005*min(rest_days-2,3), 1.0, 1.015)
    opp_rest_factor = (1.02 if opp_rest_days == 0 else 1.01 if opp_rest_days == 1 else 1.0)

    mult = _clamp(
        1.0
        + 0.22*(team_eff_matchup  - 1.0)
        + 0.16*(total_factor      - 1.0)
        + 0.14*(usage_factor      - 1.0)
        + 0.10*(injury_boost      - 1.0)
        + 0.13*(shot_factor       - 1.0)
        + 0.10*(ft_factor         - 1.0)
        + 0.13*(efficiency_factor - 1.0)
        + 0.05*(playmaking_factor - 1.0)
        + 0.07*(turnover_factor   - 1.0)
        + 0.07*(role_factor       - 1.0)
        + 0.04*(style_factor      - 1.0)
        + 0.05*(opp_shooting_adj  - 1.0)
        + 0.04*(opp_style_matchup - 1.0)
        + 0.08*(b2b_factor        - 1.0)
        + 0.06*(home_away_factor  - 1.0)
        + 0.04*(rest_factor       - 1.0)
        + 0.03*(opp_rest_factor   - 1.0),
        0.88, 1.12)

    final_projection = float(_clamp(anchored_projection*mult, 0.0, 70.0))
    if line_val > 0:
        final_projection = float(_clamp(final_projection, line_val*0.55, line_val*1.45))

    cv_base = _clamp(0.38-0.004*(usg-20.0), 0.30, 0.46) if np.isfinite(usg) else 0.38
    sigma   = float(final_projection)*cv_base
    sigma  += 0.5*_clamp(abs(minutes_proj-season_min)/max(season_min,8.0), 0.0, 1.0)
    if line_val > 0:
        sigma = min(sigma, line_val*(0.52 if np.isfinite(usg) and usg >= 28 else 0.48))
    sigma = float(_clamp(sigma, max(line_val*0.28,2.0) if line_val > 0 else 2.0, 13.0))
    if h2h_sigma_boost > 1.0:
        sigma = float(_clamp(sigma*h2h_sigma_boost, 5.0, 14.0))
    if recent_pts is not None and not is_auto_form:
        sigma = float(_clamp(sigma*0.90, 4.0, 10.0))

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
        "recent_form_used": None if is_auto_form else recent_pts,
        "h2h_pts": h2h_display_pts, "h2h_games": h2h_games, "h2h_pts_last": h2h_pts_last,
        "l10_pts": l10_pts, "l5_pts": l5_pts, "l10_trend": l10_trend,
        "def_matchup_factor": def_matchup_factor, "opp_style_matchup": opp_style_matchup,
        "b2b_factor": b2b_factor, "home_away_factor": home_away_factor,
        "rest_factor": rest_factor, "opp_rest_factor": opp_rest_factor,
        "is_home": is_home, "rest_days": rest_days,
    }

# =====================================================
# Pipeline / Refresh functions  (from doc 4)
# =====================================================

def _reload_csv_paths():
    global PLAYER_MAIN_CSV, PLAYER_BASE_CSV, PLAYER_ADV_CSV, PLAYER_MISC_CSV
    global TEAM_CSV, INJ_CSV, H2H_CSV, L10_CSV, DEF_MATCHUP_CSV, OFF_MATCHUP_CSV
    PLAYER_MAIN_CSV = next((p for p in PLAYER_MAIN_CANDIDATES if os.path.exists(p)), None)
    PLAYER_BASE_CSV = next((p for p in PLAYER_BASE_CANDIDATES if os.path.exists(p)), None)
    PLAYER_ADV_CSV  = next((p for p in PLAYER_ADV_CANDIDATES  if os.path.exists(p)), None)
    PLAYER_MISC_CSV = next((p for p in PLAYER_MISC_CANDIDATES if os.path.exists(p)), None)
    TEAM_CSV        = next((p for p in TEAM_CSV_CANDIDATES    if os.path.exists(p)), None)
    INJ_CSV         = next((p for p in INJ_CSV_CANDIDATES     if os.path.exists(p)), None)
    H2H_CSV         = next((p for p in H2H_CSV_CANDIDATES     if os.path.exists(p)), None)
    L10_CSV         = next((p for p in L10_CSV_CANDIDATES     if os.path.exists(p)), None)
    DEF_MATCHUP_CSV = next((p for p in DEF_MATCHUP_CANDIDATES if os.path.exists(p)), None)
    OFF_MATCHUP_CSV = next((p for p in OFF_MATCHUP_CANDIDATES if os.path.exists(p)), None)


def _run_script_subprocess(script_name: str, log_fn, timeout: int = 600):
    root = os.getcwd()
    script_path = os.path.join(root, script_name)
    if not os.path.exists(script_path):
        return False, f"❌ {script_name} nije pronađen."
    try:
        result = subprocess.run([sys.executable, script_path],
            capture_output=True, text=True, timeout=timeout, cwd=root)
        for line in (result.stdout or "").strip().splitlines()[-20:]:
            log_fn(line)
        if result.returncode == 0:
            return True, f"✅ {script_name} završen."
        else:
            return False, f"⚠️ {script_name} exit {result.returncode}: {(result.stderr or '')[:300]}"
    except subprocess.TimeoutExpired:
        return False, f"⚠️ {script_name} timeout (>{timeout//60} min)."
    except Exception as e:
        return False, f"❌ {script_name} greška: {e}"


def _run_script_importlib(script_name: str, log_fn, fn_name: str = "run", fn_kwargs: dict = None):
    import importlib.util, traceback as _tb
    root = os.getcwd()
    script_path = os.path.join(root, script_name)
    if not os.path.exists(script_path):
        return False, f"❌ {script_name} nije pronađen."
    fn_kwargs = fn_kwargs or {}
    try:
        spec   = importlib.util.spec_from_file_location(script_name.replace(".py",""), script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, fn_name):
            result = getattr(module, fn_name)(**fn_kwargs)
            return True, result
        return True, f"✅ {script_name} izvršen (no {fn_name}())."
    except Exception as e:
        log_fn(f"  ⚠️ importlib greška: {e}")
        log_fn(_tb.format_exc()[-600:])
        return False, f"❌ {script_name}: {e}"


def run_full_refresh_pipeline(skip_h2h: bool = False, status_box=None, log_box=None):
    log_lines: list = []
    def _log(msg: str):
        log_lines.append(str(msg))
        if log_box is not None:
            log_box.code("\n".join(log_lines[-40:]), language="")
    def _status(msg: str):
        if status_box is not None:
            status_box.info(msg)
        _log(f"\n{'─'*50}\n{msg}\n{'─'*50}")

    pipeline_errors: list = []; pipeline_ok = True; report: dict = {}

    _status("📋 Korak 1/6 — Povlačenje dnevne ponude (fetch_daily_offer.py)...")
    ok1, msg1 = _run_script_subprocess("fetch_daily_offer.py", _log, timeout=120)
    _log(msg1); report["korak1_ponuda"] = "OK" if ok1 else f"WARN: {msg1}"
    if not ok1: pipeline_errors.append(f"Korak 1: {msg1}")

    _status("🔄 Korak 2/6 — refresh_all.py...")
    ok2, msg2 = _run_script_subprocess("refresh_all.py", _log, timeout=300)
    _log(msg2); report["korak2_refresh_all"] = "OK" if ok2 else f"WARN: {msg2}"
    if not ok2: pipeline_errors.append(f"Korak 2: {msg2}")

    _status("📊 Korak 3/6 — L10 forma i player stats (refresh_daily.py)...")
    ok3, result3 = _run_script_importlib("refresh_daily.py", _log, fn_name="run",
        fn_kwargs={"data_dir": DATA_DIR, "log_fn": _log, "skip_h2h": True})
    if ok3 and isinstance(result3, dict):
        s3 = result3.get("status","?")
        if s3 == "NO_GAMES":
            _log("ℹ️  Danas nema NBA mečeva."); report["korak3_daily"] = "NO_GAMES"
        elif s3 == "ERROR":
            for e in result3.get("errors",[]): pipeline_errors.append(f"Korak 3: {e}")
            pipeline_ok = False; report["korak3_daily"] = "ERROR"
        else:
            for fname, cnt in result3.get("counts",{}).items(): _log(f"  ✅ {fname}: {cnt} rows")
            report["korak3_daily"] = f"OK ({len(result3.get('counts',{}))} fajlova)"
    elif ok3:
        _log(str(result3)); report["korak3_daily"] = "OK"
    else:
        pipeline_errors.append(f"Korak 3: {result3}"); pipeline_ok = False
        report["korak3_daily"] = f"ERROR: {result3}"

    _status("🔗 Korak 4/6 — Osvježavanje H2H podataka (refresh_h2h.py)...")
    ok4, msg4 = _run_script_subprocess("refresh_h2h.py", _log, timeout=900)
    _log(msg4); report["korak4_h2h"] = "OK" if ok4 else f"WARN: {msg4}"
    if not ok4: pipeline_errors.append(f"Korak 4: {msg4}")

    _status("🏥 Korak 5/6 — Osvježavanje ozljeda (refresh_injuries.py)...")
    ok5, msg5 = _run_script_subprocess("refresh_injuries.py", _log, timeout=120)
    _log(msg5); report["korak5_injuries"] = "OK" if ok5 else f"WARN: {msg5}"
    if not ok5: pipeline_errors.append(f"Korak 5: {msg5}")

    _status("🔄 Korak 6/6 — Reload CSV fajlova i čišćenje cache-a...")
    try:
        st.cache_data.clear(); _reload_csv_paths()
        _log("✅ CSV putanje ažurirane, cache obrisan."); report["reload"] = "OK"
    except Exception as e:
        _log(f"⚠️ Reload greška: {e}"); pipeline_errors.append(f"Reload: {e}")

    _log("\n" + "═"*50 + "\n📋 REFRESH SUMMARY\n" + "═"*50)
    for k, v in report.items():
        _log(f"  {'✅' if 'OK' in str(v) else '⚠️'} {k}: {v}")
    if pipeline_errors:
        _log(f"\n⚠️  {len(pipeline_errors)} warning(s):")
        for e in pipeline_errors: _log(f"   • {e}")
    else:
        _log("\n🎉 Sve OK — podaci su svježi!")
    return pipeline_ok, report, pipeline_errors


def run_refresh_scripts() -> Tuple[List[str], List[str], List[Tuple[str, str]]]:
    scripts = ["refresh_data.py","refresh_injuries.py","refresh_matchups.py",
               "refresh_h2h.py","refresh_schedule.py","refresh_props.py"]
    ran, missing, failed = [], [], []
    for sname in scripts:
        spath = os.path.join(os.getcwd(), sname)
        if not os.path.exists(spath):
            missing.append(sname); continue
        try:
            subprocess.check_call([sys.executable, spath]); ran.append(sname)
        except Exception as e:
            failed.append((sname, str(e)))
    return ran, missing, failed


# =====================================================
# Game Status / Schedule  (ESPN API)
# =====================================================

import requests as _req_module

@st.cache_data(ttl=300)
def fetch_game_statuses() -> dict:
    """Fetchuje NBA raspored za DANAS + SUTRA. state: pre/in/post"""
    _today    = datetime.date.today()
    _tomorrow = _today + datetime.timedelta(days=1)
    dates     = [_today.strftime("%Y%m%d"), _tomorrow.strftime("%Y%m%d")]
    games: dict = {}
    for date_str in dates:
        try:
            url  = (f"https://site.api.espn.com/apis/site/v2/sports/"
                    f"basketball/nba/scoreboard?dates={date_str}")
            resp = _req_module.get(url, timeout=10)
            if resp.status_code != 200:
                continue
            for event in resp.json().get("events", []):
                st_type = event.get("status", {}).get("type", {})
                state   = st_type.get("state", "pre")
                detail  = st_type.get("shortDetail", "")
                start   = event.get("date", "")
                comps   = event.get("competitions", [{}])[0].get("competitors", [])
                abbrs   = [c.get("team", {}).get("abbreviation", "").upper()
                           for c in comps if c.get("team", {}).get("abbreviation")]
                for i, abbr in enumerate(abbrs):
                    opp = abbrs[1-i] if len(abbrs) == 2 else ""
                    games[abbr] = {"state": state, "detail": detail,
                                   "start_time": start, "opponent": opp, "date": date_str}
        except Exception:
            pass
    return games

# =====================================================
# Sidebar controls  (from doc 3 – full featured)
# =====================================================

st.sidebar.header("⚙️ Controls")
mc_sims            = st.sidebar.selectbox("Monte Carlo sims", [500, 1000, 3000, 5000], index=3)
min_ev             = st.sidebar.slider("Min EV %", -10, 25, 0)
show_only_positive = st.sidebar.checkbox("Only EV > 0", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("📈 Recent Form Override")
recent_form_txt = st.sidebar.text_area(
    "Format: Ime, L5 prosjek (jedan po retku)", height=160,
    placeholder="Gui Santos, 18.2\nQuentin Grimes, 22.1")
recent_form_override = parse_recent_form_input(recent_form_txt)
if recent_form_override:
    st.sidebar.success(f"✅ {len(recent_form_override)} recent form override(s) aktivan")
    with st.sidebar.expander("Pregled overridea"):
        for k, v in recent_form_override.items():
            st.sidebar.write(f"• {k}: {v} pts")

st.sidebar.markdown("---")
st.sidebar.subheader("🔁 Back-to-Back")
st.sidebar.caption("Upiši kratice timova koji igraju B2B danas (odvojeno zarezom)")
b2b_input_txt  = st.sidebar.text_input("B2B timovi (npr. DET, MEM, LAL)", placeholder="DET, BOS")
b2b_teams_manual: set = set()
if b2b_input_txt.strip():
    for _t in b2b_input_txt.split(","):
        _t = _t.strip().upper()
        if _t: b2b_teams_manual.add(_t)
    st.sidebar.success(f"✅ B2B: {', '.join(sorted(b2b_teams_manual))}")
b2b_date_input = st.sidebar.text_input("Datum utakmice (YYYY-MM-DD)", value=TODAY_ISO)

st.sidebar.markdown("---")
st.sidebar.subheader("🏠 Home / Away & Rest Days")
st.sidebar.caption("Upiši timove koji igraju na gostovanju (odvojeno zarezom)")
away_teams_txt = st.sidebar.text_input("Away timovi danas (npr. DET, PHI)", placeholder="DET, PHI", key="away_teams_input")
away_teams_manual: set = set()
if away_teams_txt.strip():
    for _t in away_teams_txt.split(","):
        _t = _t.strip().upper()
        if _t: away_teams_manual.add(_t)
    st.sidebar.success(f"✅ Away: {', '.join(sorted(away_teams_manual))}")
st.sidebar.caption("Rest Days — dani odmora po timu (format: TIM=DANI, npr. OKC=3, MIN=2)")
rest_days_txt = st.sidebar.text_input("Rest days po timu", placeholder="OKC=3, MIN=2, CLE=1", key="rest_days_input")
rest_days_map: dict = {}
if rest_days_txt.strip():
    for part in rest_days_txt.split(","):
        part = part.strip()
        if "=" in part:
            try:
                abbr_rd, days_rd = part.split("=",1)
                rest_days_map[abbr_rd.strip().upper()] = int(days_rd.strip())
            except Exception:
                pass
    if rest_days_map: st.sidebar.success(f"✅ Rest: {rest_days_map}")

st.sidebar.markdown("---")
st.sidebar.subheader("🏥 Injury Override")
st.sidebar.caption("Format: Ime, Status  |  Statusi: OUT, QUESTIONABLE, DOUBTFUL, PROBABLE")
injury_override_txt = st.sidebar.text_area(
    "Manualni injury override", height=110,
    placeholder="Joel Embiid, OUT\nDamian Lillard, QUESTIONABLE", key="injury_override")

st.sidebar.markdown("---")
st.sidebar.button("▶️ Pokreni / Osvježi analizu", type="primary", use_container_width=True)
st.sidebar.caption("Klikni nakon što uneseš Recent Form, B2B i Injury podatke")

# ── Dnevni Refresh Pipeline ──────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("🗓️ Dnevni Refresh")

_nba_api_ok = False
try:
    import nba_api as _nba_api_check; _nba_api_ok = True  # noqa
except ImportError:
    pass
if not _nba_api_ok:
    st.sidebar.warning("⚠️ `nba_api` nije instaliran.")
    st.sidebar.code("pip install nba_api requests", language="bash")

_skip_h2h_toggle = st.sidebar.checkbox(
    "⚡ Preskoči H2H (brže)", value=True,
    help="H2H refresh traje 10–20 min. Isključi samo kada trebaš svježe H2H podatke.")

with st.sidebar.expander("ℹ️ Šta radi Refresh?", expanded=False):
    st.markdown(
        "**1.** 📋 `fetch_daily_offer.py` — povlači dnevnu ponudu\n\n"
        "**2.** 🔄 `refresh_all.py` — osvježava sve podatke\n\n"
        "**3.** 📊 `refresh_daily.py` — player stats, L10 forma, matchup\n\n"
        "**4.** 🔗 `refresh_h2h.py` — H2H history po protivniku\n\n"
        "**5.** 🏥 `refresh_injuries.py` — ažurira ozljede\n\n"
        "**6.** 🔄 Reload CSV putanja + čišćenje Streamlit cache-a")

_last_refresh_file = os.path.join(DATA_DIR, f"players_{SEASON}.csv")
if os.path.exists(_last_refresh_file):
    _mtime_r   = datetime.datetime.fromtimestamp(os.path.getmtime(_last_refresh_file))
    _age_h     = (datetime.datetime.now() - _mtime_r).total_seconds() / 3600
    _age_str   = f"{int(_age_h*60)} min" if _age_h < 1 else f"{_age_h:.1f}h"
    _fc        = "🟢" if _age_h < 6 else ("🟡" if _age_h < 24 else "🔴")
    st.sidebar.caption(f"{_fc} Podaci stari: **{_age_str}**")
else:
    st.sidebar.caption("⚪ Nema podataka — pokreni Refresh")

_today_label = TODAY.strftime("%d.%m.%Y")
_refresh_btn = st.sidebar.button(
    f"🔄 Pokreni Refresh  ({_today_label})",
    key="full_refresh_pipeline_btn", type="primary",
    use_container_width=True, disabled=not _nba_api_ok)

if _refresh_btn:
    _status_box = st.sidebar.empty(); _log_box = st.sidebar.empty()
    with st.spinner(f"⏳ Dnevni refresh u toku ({_today_label})..."):
        _pipeline_ok, _pipeline_report, _pipeline_errors = run_full_refresh_pipeline(
            skip_h2h=_skip_h2h_toggle, status_box=_status_box, log_box=_log_box)
    _status_box.empty()
    if _pipeline_ok and not _pipeline_errors:
        st.sidebar.success(f"🎉 Refresh završen uspješno! ({_today_label})")
    elif _pipeline_ok:
        st.sidebar.warning(f"⚠️ Refresh s {len(_pipeline_errors)} warning(s):\n" +
            "\n".join(f"• {e}" for e in _pipeline_errors))
    else:
        st.sidebar.error("❌ Refresh greška:\n" + "\n".join(f"• {e}" for e in _pipeline_errors))
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### 📦 Data status")
for _lbl, _pth in [
    ("Players main", PLAYER_MAIN_CSV), ("Players base", PLAYER_BASE_CSV),
    ("Players adv",  PLAYER_ADV_CSV),  ("Players misc", PLAYER_MISC_CSV),
    ("Teams CSV",    TEAM_CSV),         ("Injuries CSV", INJ_CSV),
    ("L10 CSV",      L10_CSV),          ("DEF Matchup",  DEF_MATCHUP_CSV),
    ("OFF Matchup",  OFF_MATCHUP_CSV),  ("B2B CSV",      B2B_CSV),
]:
    _ok   = "✅" if _pth else "❌"
    _name = os.path.basename(_pth) if _pth else "None"
    st.sidebar.write(f"{_lbl}: {_ok} → {_name}")

if not PLAYER_MAIN_CSV or not TEAM_CSV:
    st.error("Nedostaje glavni players CSV ili teams CSV.")
    st.stop()


# =====================================================
# Load core data
# =====================================================

players_df     = load_players_merged(PLAYER_MAIN_CSV, PLAYER_BASE_CSV, PLAYER_ADV_CSV, PLAYER_MISC_CSV)
teams_df       = load_teams_csv(TEAM_CSV)
inj_df         = load_injuries_csv(INJ_CSV)
h2h_df         = load_h2h_csv(H2H_CSV)
l10_df         = load_l10_csv(L10_CSV)
def_matchup_df = load_def_matchup_csv(DEF_MATCHUP_CSV)
off_matchup_df = load_off_matchup_csv(OFF_MATCHUP_CSV)
b2b_df         = load_b2b_csv(B2B_CSV)

# Injury override merge
if injury_override_txt and injury_override_txt.strip():
    _inj_override = parse_injury_override(injury_override_txt, players_df)
    if not _inj_override.empty:
        if inj_df is not None and "NAME_KEY" in inj_df.columns:
            inj_df = pd.concat([inj_df[~inj_df["NAME_KEY"].isin(_inj_override["NAME_KEY"])],
                                 _inj_override], ignore_index=True)
        else:
            inj_df = _inj_override
        st.sidebar.success(f"🏥 {len(_inj_override)} injury override(s) aktivno")
        with st.sidebar.expander("Pregled injury overridea"):
            for _, _ir in _inj_override.iterrows():
                _abbr_ir = _ir["TEAM_ABBR"] if pd.notna(_ir["TEAM_ABBR"]) else "?"
                st.sidebar.write(f"• {_ir['PLAYER']} ({_abbr_ir}): **{_ir['STATUS']}**")

# Injury override merge – prioritet nad CSV-om
if injury_override_txt and injury_override_txt.strip():
    _inj_override = parse_injury_override(injury_override_txt, players_df)
    if not _inj_override.empty:
        if inj_df is not None and "NAME_KEY" in inj_df.columns:
            _inj_base = inj_df[~inj_df["NAME_KEY"].isin(_inj_override["NAME_KEY"])]
            inj_df    = pd.concat([_inj_base, _inj_override], ignore_index=True)
        else:
            inj_df = _inj_override
        st.sidebar.success(f"🏥 {len(_inj_override)} injury override(s) aktivno")
        with st.sidebar.expander("Pregled injury overridea"):
            for _, _ir in _inj_override.iterrows():
                _abbr = _ir["TEAM_ABBR"] if pd.notna(_ir["TEAM_ABBR"]) else "?"
                st.sidebar.write(f"• {_ir['PLAYER']} ({_abbr}): **{_ir['STATUS']}**")

league_pts_std = float(pd.to_numeric(players_df["PTS"], errors="coerce").dropna().std() or 6.0)

with st.expander("🔍 DEBUG DATA — status svih izvora"):
    def _file_status(path, label):
        if path is None or not os.path.exists(path):
            return f"❌ {label}: fajl ne postoji"
        size  = os.path.getsize(path)
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d.%m %H:%M")
        try:
            tmp = pd.read_csv(path)
            return f"✅ {label}: {len(tmp)} rows, {size//1024}KB, zadnji update: {mtime}"
        except Exception as e:
            return f"⚠️ {label}: fajl postoji ali greška: {e}"
    st.markdown("**📁 CSV fajlovi na disku:**")
    for lbl, path in [
        ("players main", PLAYER_MAIN_CSV), 
        ("players adv",  PLAYER_ADV_CSV),  ("players misc", PLAYER_MISC_CSV),
        ("teams",        TEAM_CSV),         ("injuries",     INJ_CSV),
        ("L10 forma",    L10_CSV),          ("H2H",          H2H_CSV),
        ("def_matchup",  DEF_MATCHUP_CSV),  ("off_matchup",  OFF_MATCHUP_CSV),
    ]:
        st.write(_file_status(path, lbl))
    st.markdown("---")
    st.markdown("**📊 Učitani DataFrameovi:**")
    st.write(f"players_df: {len(players_df)} rows, {len(players_df.columns)} cols")
    st.write(f"teams_df:   {len(teams_df)} rows")
    st.write(f"inj_df:     {0 if inj_df is None else len(inj_df)} rows")
    if l10_df is not None and not l10_df.empty:
        st.write(f"l10_df:     ✅ {len(l10_df)} rows — kolone: {list(l10_df.columns)}")
        st.dataframe(l10_df.head(5), use_container_width=True)
    else:
        st.write("l10_df:     ❌ None ili prazan")
    if h2h_df is not None and not h2h_df.empty:
        st.write(f"h2h_df:     ✅ {len(h2h_df)} rows — kolone: {list(h2h_df.columns)}")
        st.dataframe(h2h_df.head(5), use_container_width=True)
    else:
        st.write("h2h_df:     ❌ None ili prazan")
    st.markdown("---")
    st.markdown("**🔑 NAME_KEY matching:**")
    if l10_df is not None and not l10_df.empty and "NAME_KEY" in l10_df.columns:
        pk   = set(players_df["NAME_KEY"].dropna().tolist()) if "NAME_KEY" in players_df.columns else set()
        lk   = set(l10_df["NAME_KEY"].dropna().tolist())
        st.write(f"L10 NAME_KEY match: {len(pk&lk)}/{len(lk)} igrača matchovano")
        unm = lk-pk
        if unm: st.write(f"  ⚠️ L10 bez matcha: {sorted(list(unm))[:10]}")
    if h2h_df is not None and not h2h_df.empty and "NAME_KEY" in h2h_df.columns:
        pk   = set(players_df["NAME_KEY"].dropna().tolist()) if "NAME_KEY" in players_df.columns else set()
        hk   = set(h2h_df["NAME_KEY"].dropna().tolist())
        st.write(f"H2H NAME_KEY match: {len(pk&hk)}/{len(hk)} igrača matchovano")
    st.markdown("---")
    _debug_cols = [c for c in ("PLAYER_NAME","TEAM_ABBR","TEAM_NUMERIC_ID","MIN","PTS","USG_PCT","TS_PCT","PIE","PTS_PAINT","PACE") if c in players_df.columns]
    st.dataframe(players_df[_debug_cols].head(20), use_container_width=True)


# =====================================================
# NBA Schedule — today + tomorrow
# =====================================================

_game_statuses = fetch_game_statuses()

if _game_statuses:
    _today_str    = TODAY.strftime("%Y%m%d")
    _tomorrow_str = (TODAY + datetime.timedelta(days=1)).strftime("%Y%m%d")
    _today_games    = {a: g for a,g in _game_statuses.items() if g["date"]==_today_str    and a<g["opponent"]}
    _tomorrow_games = {a: g for a,g in _game_statuses.items() if g["date"]==_tomorrow_str and a<g["opponent"]}
    _state_icon = {"pre": "🕐", "in": "🔴 LIVE", "post": "✅ Final"}
    with st.expander(f"📅 NBA Raspored — Danas ({len(_today_games)}) + Sutra ({len(_tomorrow_games)})"):
        if _today_games:
            st.markdown("**Danas:**")
            _cols = st.columns(min(4, max(1, len(_today_games))))
            for _ci, (_abbr, _g) in enumerate(_today_games.items()):
                with _cols[_ci % len(_cols)]:
                    st.markdown(f"**{_abbr} vs {_g['opponent']}**")
                    st.caption(f"{_state_icon.get(_g['state'],'🕐')} {_g['detail']}")
        if _tomorrow_games:
            st.markdown("**Sutra:**")
            _cols2 = st.columns(min(4, max(1, len(_tomorrow_games))))
            for _ci, (_abbr, _g) in enumerate(_tomorrow_games.items()):
                with _cols2[_ci % len(_cols2)]:
                    st.markdown(f"**{_abbr} vs {_g['opponent']}**")
                    st.caption(f"🕐 {_g['detail']}")
else:
    _game_statuses = {}

_games_in_progress = {a for a,g in _game_statuses.items() if g["state"] == "in"}
_games_finished    = {a for a,g in _game_statuses.items() if g["state"] == "post"}


# =====================================================
# Offer — automatski ili manual upload
# =====================================================

st.subheader("📂 Offer — automatski ili manual upload")
OFFER_AUTO_PATHS = [
    os.path.join(DATA_DIR, "offer_latest.csv"),
    os.path.join(DATA_DIR, f"offer_{TODAY_ISO}_upload.csv"),
    os.path.join(DATA_DIR, f"offer_{TODAY_ISO}.csv"),
]
auto_offer_path = _first_existing(OFFER_AUTO_PATHS)
col_src1, col_src2 = st.columns([3,1])
with col_src1:
    uploaded = st.file_uploader(
        "Manual upload (opcionalno — ako ne uploaduješ, koristi se automatski offer)",
        type=["txt","csv"])
with col_src2:
    st.markdown("&nbsp;", unsafe_allow_html=True)
    if auto_offer_path:
        _mtime2 = datetime.datetime.fromtimestamp(os.path.getmtime(auto_offer_path)).strftime("%H:%M:%S")
        st.success(f"✅ Auto offer\n{os.path.basename(auto_offer_path)}\nažuriran: {_mtime2}")
    else:
        st.warning("⚠️ offer_latest.csv nije pronađen.")

actual_uploaded = st.file_uploader(
    "Upload results CSV za evaluaciju: Player, Actual Points, (optional: Closing Line…)",
    type=["csv"], key="actual_results_upload")
second_model_uploaded = st.file_uploader(
    "Optional: Upload second model prediction CSV", type=["csv"], key="second_model_upload")

if uploaded is not None:
    txt = smart_decode(uploaded.getvalue()); offer_source = f"📤 Manual upload: {uploaded.name}"
elif auto_offer_path is not None:
    with open(auto_offer_path, "rb") as _f: txt = smart_decode(_f.read())
    offer_source = f"🤖 Auto-load: {os.path.basename(auto_offer_path)}"
else:
    st.error("❌ Nema offer podataka. Pokreni **📋 Refresh Props** ili uploaduj ručno.")
    st.stop()

st.caption(f"Izvor ponude: {offer_source}")
rows, bad_lines = parse_offer_text(txt)
st.caption(f"Parsed rows: {len(rows)} | Skipped lines: {len(bad_lines)}")
with st.expander("🧾 Debug parsed rows"):
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=["name","line","over","under","opp_team","total"]),
                     use_container_width=True)
    if bad_lines:
        st.dataframe(pd.DataFrame(bad_lines, columns=["raw","reason"]), use_container_width=True)
if not rows:
    st.error("Nema validnih redova u fajlu."); st.stop()

# =====================================================
# Core projection loop
# =====================================================

results:        List[Dict] = []
not_found:      List[Dict] = []
_skipped_active: List[Dict] = []

for name, line_val, over_odds, under_odds, opp_from_txt, total_from_txt in rows:
    r0, used_key, method = match_player_row(players_df, name)
    if r0 is None:
        not_found.append({"offer_name": name, "norm": normalize_name(name), "method": method})
        continue

    team_abbr     = normalize_team_abbr(r0.get("TEAM_ABBR"))
    team_row      = _find_team_row_by_abbr(teams_df, team_abbr) if pd.notna(team_abbr) else None
    
    # ═══════════════════════════════════════════════════════════════════════
    # FIX: OPP_TEAM VALIDACIJA
    # Ako je OPP_TEAM jednak TEAM_ABBR igrača, to je greška iz offer CSV-a
    # ═══════════════════════════════════════════════════════════════════════
    opp_team_abbr = None
    if opp_from_txt:
        _opp_candidate = normalize_team_abbr(opp_from_txt)
        if pd.notna(_opp_candidate):
            # Provjeri da OPP nije jednak timu igrača
            if pd.isna(team_abbr) or str(_opp_candidate).upper() != str(team_abbr).upper():
                opp_team_abbr = _opp_candidate
            # else: OPP je jednak timu igrača - ignoriši (opp_team_abbr ostaje None)
    # ═══════════════════════════════════════════════════════════════════════
    
    opp_row       = _find_team_row_by_abbr(teams_df, opp_team_abbr) if opp_team_abbr else None

    # ── Provjera: meč već počeo ili završio? ──────────────────
    _team_str = str(team_abbr).upper()     if pd.notna(team_abbr)                              else ""
    _opp_str  = str(opp_team_abbr).upper() if opp_team_abbr and pd.notna(opp_team_abbr) else ""
    _game_state = None
    for _chk in (_team_str, _opp_str):
        if _chk and _chk in _game_statuses:
            _game_state = _game_statuses[_chk]["state"]; break
    if _game_state in ("in", "post"):
        _gs_detail = _game_statuses.get(_team_str or _opp_str, {}).get("detail", "")
        _skipped_active.append({"Player": name, "Team": _team_str or "?", "Opp": _opp_str or "?",
            "Status": "🔴 LIVE" if _game_state == "in" else "✅ Final", "Detail": _gs_detail})
        continue
    # ──────────────────────────────────────────────────────────

    total_match_model = estimate_match_total(team_row, opp_row, None, teams_df) \
                        if team_row is not None and opp_row is not None else None
    total_match_used  = float(total_from_txt) \
                        if total_from_txt is not None and np.isfinite(total_from_txt) else total_match_model

    team_abbr_str  = str(team_abbr).upper()     if pd.notna(team_abbr)                              else ""
    opp_abbr_str   = str(opp_team_abbr).upper() if opp_team_abbr and pd.notna(opp_team_abbr) else ""
    b2b_team       = is_team_b2b(b2b_df, team_abbr_str, b2b_date_input) or (team_abbr_str in b2b_teams_manual)
    b2b_opp        = is_team_b2b(b2b_df, opp_abbr_str,  b2b_date_input) or (opp_abbr_str  in b2b_teams_manual)
    _is_home       = team_abbr_str not in away_teams_manual
    _rest_days     = rest_days_map.get(team_abbr_str, 2)
    _opp_rest_days = rest_days_map.get(opp_abbr_str,  2)
    if b2b_team: _rest_days     = 0
    if b2b_opp:  _opp_rest_days = 0

    ctx = build_player_context(
        r0=r0, players_df=players_df, teams_df=teams_df,
        team_row=team_row, opp_row=opp_row, inj_df=inj_df,
        team_abbr=team_abbr, player_name_key=used_key,
        total_match_used=total_match_used,
        recent_form_override=recent_form_override,
        h2h_df=h2h_df, opp_team_abbr=opp_team_abbr, l10_df=l10_df,
        def_matchup_df=def_matchup_df, off_matchup_df=off_matchup_df,
        line_val=float(line_val), b2b_team=b2b_team, b2b_opp=b2b_opp,
        is_home=_is_home, rest_days=_rest_days, opp_rest_days=_opp_rest_days,
    )

    results.append({
        "Player":               str(r0.get("PLAYER_NAME", name)),
        "Matched By":           method,
        "TEAM_ABBR":            team_abbr,
        "OPP_TEAM":             opp_team_abbr,
        "NET_RATING":           _get_float(team_row, "NET_RATING", 0.0) if team_row is not None else 0.0,
        "OPP_DEF":              ctx["opp_def"],
        "PACE_GAME":            round(float(ctx["pace_game"]), 3),
        "TOTAL_MATCH_OFFER":    float(total_from_txt) if total_from_txt is not None and np.isfinite(total_from_txt) else None,
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
        "B2B Team":             b2b_team,
        "B2B Opp":              b2b_opp,
        "B2B Factor":           round(float(ctx.get("b2b_factor", 1.0)), 3),
        "Is Home":              ctx.get("is_home", True),
        "Rest Days":            ctx.get("rest_days", 2),
        "Home/Away Factor":     round(float(ctx.get("home_away_factor", 1.0)), 3),
        "Rest Factor":          round(float(ctx.get("rest_factor", 1.0)), 3),
        "Opp Rest Factor":      round(float(ctx.get("opp_rest_factor", 1.0)), 3),
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

# Prikaz preskočenih mečeva
if _skipped_active:
    _skip_df  = pd.DataFrame(_skipped_active)
    _in_live  = int((_skip_df["Status"] == "🔴 LIVE").sum())
    _in_final = int((_skip_df["Status"] == "✅ Final").sum())
    _msg = []
    if _in_live:  _msg.append(f"{_in_live} igrača (meč u toku)")
    if _in_final: _msg.append(f"{_in_final} igrača (meč završen)")
    st.warning(f"⏭️ Preskočeno {len(_skipped_active)} igrača — " + ", ".join(_msg))
    with st.expander("📋 Preskočeni igrači (meč počeo ili završio)"):
        st.dataframe(_skip_df, use_container_width=True)

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

_anchors  = pd.to_numeric(df["SeasonAnchor"], errors="coerce").dropna()
_lines    = pd.to_numeric(df["Line"],         errors="coerce").dropna()
_common   = _anchors.index.intersection(_lines.index)
_bm_offset = float(_clamp((_anchors[_common]-_lines[_common]).mean(), -2.0, 4.0)) if len(_common) >= 3 else 1.5
st.caption(f"Bookmaker offset: **{_bm_offset:.2f}**")


# =====================================================
# Monte Carlo
# =====================================================

rng = np.random.default_rng(42)
updated = []

for _, row in df.iterrows():
    proj_raw   = float(row["Final Projection"])
    line_val   = float(row["Line"])
    over_odds  = float(row["Over Odds"])
    under_odds = float(row["Under Odds"])
    season_pts = float(row.get("SeasonAnchor", proj_raw))
    usg_val    = float(row["Usage %"]) if row.get("Usage %") is not None and not pd.isna(row.get("Usage %")) else 20.0
    sigma_val  = float(row.get("Sigma", league_pts_std))

    player_bm_offset = compute_per_player_bm_offset(season_pts)
    proj_devigged    = proj_raw - player_bm_offset

    p_over_mkt_raw  = 1.0 / over_odds
    p_under_mkt_raw = 1.0 / under_odds
    total_mkt       = p_over_mkt_raw + p_under_mkt_raw
    p_over_mkt      = p_over_mkt_raw  / total_mkt
    p_under_mkt     = p_under_mkt_raw / total_mkt

    abs_edge = abs(proj_devigged - line_val)
    market_blend = (0.55 if abs_edge < 1.5 else 0.45 if abs_edge < 3.0 else 0.35 if abs_edge < 5.0 else 0.25)
    proj     = (1.0 - market_blend) * proj_devigged + market_blend * line_val
    max_edge = compute_max_edge(line_val, usg_val, sigma_val)
    proj     = _clamp(proj, line_val - max_edge, line_val + max_edge)

    sigma = _clamp(float(row.get("Sigma", league_pts_std)), max(line_val * 0.28, 2.0), 9.5)

    sims          = np.clip(rng.normal(proj, sigma, int(mc_sims)), 0.0, 80.0)
    p_over_model  = float(np.mean(sims > line_val))
    p_under_model = 1.0 - p_over_model

    ev_over  = (p_over_model  * over_odds)  - 1.0
    ev_under = (p_under_model * under_odds) - 1.0

    _total_impl = (1.0/over_odds) + (1.0/under_odds)
    if _total_impl < 1.0:
        ev_over = ev_under = 0.0

    if abs(p_over_model - p_over_mkt) < 0.025:
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
        "Market P(Over)%":       round(p_over_mkt   * 100.0, 2),
        "Market P(Under)%":      round(p_under_mkt  * 100.0, 2),
        "Model Pick":            pick,
        "Pick Confidence %":     round(p_pick        * 100.0, 2),
        "Best EV %":             round(best_ev       * 100.0, 2),
        "Projection Edge":       round(proj - line_val, 2),
        "P(Over)%":              round(p_over_model  * 100.0, 2),
        "P(Under)%":             round(p_under_model * 100.0, 2),
    })

df = pd.DataFrame(updated)


# =====================================================
# Ranking
# =====================================================

df["EV_z"]      = zscore(df["Best EV %"])
df["EDGE_z"]    = zscore(df["Projection Edge"])
df["HIT_z"]     = zscore(df["Pick Confidence %"])
df["True Score"] = 0.50*df["EV_z"] + 0.30*df["EDGE_z"] + 0.20*df["HIT_z"]
df = df.sort_values("True Score", ascending=False)
df = df[df["Best EV %"] >= min_ev]
if show_only_positive:
    df = df[df["Best EV %"] > 0]


# =====================================================
# Team Concentration Warning + EV Penalty
# =====================================================

over_df          = df[df["Model Pick"] == "OVER"].copy()
team_over_counts = over_df.groupby("TEAM_ABBR").size()
concentrated_teams = team_over_counts[team_over_counts >= 3].index.tolist()

if concentrated_teams:
    team_usg_sums = (over_df[over_df["TEAM_ABBR"].isin(concentrated_teams)]
                     .groupby("TEAM_ABBR")["Usage %"].sum())
    penalty_map: Dict[Any, float] = {}
    for team in concentrated_teams:
        for rank, idx in enumerate(df[(df["TEAM_ABBR"]==team)&(df["Model Pick"]=="OVER")].index.tolist()):
            if rank == 2:   penalty_map[idx] = 0.85
            elif rank >= 3: penalty_map[idx] = 0.55
    if penalty_map:
        df["Conc Penalty"] = 1.0
        for idx, mult in penalty_map.items():
            if idx in df.index: df.at[idx, "Conc Penalty"] = mult
        df["Best EV %"]  = (df["Best EV %"]*df["Conc Penalty"]).round(2)
        df["EV_z"]       = zscore(df["Best EV %"]); df["EDGE_z"] = zscore(df["Projection Edge"])
        df["HIT_z"]      = zscore(df["Pick Confidence %"])
        df["True Score"] = 0.50*df["EV_z"]+0.30*df["EDGE_z"]+0.20*df["HIT_z"]
        df = df.sort_values("True Score", ascending=False)
    st.markdown("---")
    st.warning(f"⚠️ **Team Concentration Warning** — {len(concentrated_teams)} tim(a) ima 3+ OVER pickova")
    for team in concentrated_teams:
        count   = int(team_over_counts[team]); usg_sum = float(team_usg_sums.get(team,0))
        players = over_df[over_df["TEAM_ABBR"]==team]["Player"].tolist()
        penalized = [df.at[i,"Player"] for i,m in penalty_map.items()
                     if m<1.0 and i in df.index and df.at[i,"TEAM_ABBR"]==team]
        c1,c2,c3 = st.columns(3)
        c1.metric(f"🏀 {team} OVER pickovi", count)
        c2.metric("Ukupni USG%", f"{usg_sum:.0f}%",
            delta="⚠️ Visoko" if usg_sum>85 else "OK",
            delta_color="inverse" if usg_sum>85 else "normal")
        c3.metric("EV penalty primijenjen", f"{len(penalized)} igrač(a)")
        st.caption(f"Igrači: {', '.join(players)}")
        if penalized: st.caption(f"🔻 Penalizirani: {', '.join(penalized)}")
    st.markdown("---")

if recent_form_override:
    rf_set   = set(recent_form_override.keys())
    rf_count = int(df["Player"].apply(lambda x: normalize_name(x) in rf_set).sum())
    if rf_count > 0: st.info(f"📈 {rf_count} igrač(a) ima aktivan Recent Form override")

st.subheader("📊 Full Portfolio")
st.dataframe(df, use_container_width=True)
st.subheader("🔥 TOP 3")
st.dataframe(df.head(3), use_container_width=True)


# =====================================================
# Evaluation / Compare
# =====================================================

st.markdown("---")
st.subheader("✅ Engine Evaluation / Grading")
stake_size        = st.number_input("Stake per bet", min_value=0.1, value=1.0, step=0.1)
actual_results_df: Optional[pd.DataFrame] = None
evaluated_df:      Optional[pd.DataFrame] = None

if actual_uploaded is not None:
    try:
        actual_results_df = load_actual_results_csv(actual_uploaded)
    except Exception as e:
        st.error(f"Greška pri učitavanju results CSV: {e}")

if actual_results_df is not None:
    try:
        evaluated_df, eval_summary = evaluate_engine(df, actual_results_df, stake=stake_size, model_name="Engine 1")
        grade = grade_engine(eval_summary)
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Accuracy", f"{eval_summary['Accuracy %']}%")
        c2.metric("ROI",      f"{eval_summary['ROI %']}%")
        c3.metric("Profit",   f"{eval_summary['Profit']}")
        c4.metric("MAE",      f"{eval_summary['MAE']}")
        c5.metric("Grade",    grade)
        st.dataframe(pd.DataFrame([eval_summary]), use_container_width=True)
        eval_cols = [c for c in ("Player","Model Pick","Line","Final Projection","Actual Points",
                                 "Bet Result","Used Odds","Profit","Projection Edge","CLV")
                     if c in evaluated_df.columns]
        st.dataframe(evaluated_df[eval_cols], use_container_width=True)
    except Exception as e:
        st.error(f"Greška u engine evaluaciji: {e}")

if actual_results_df is not None and second_model_uploaded is not None:
    st.markdown("---")
    st.subheader("⚔️ Compare Two Models")
    try:
        second_model_df = load_prediction_results_csv(second_model_uploaded)
        _, summary_1 = evaluate_engine(df,              actual_results_df, stake=stake_size, model_name="Engine 1")
        _, summary_2 = evaluate_engine(second_model_df, actual_results_df, stake=stake_size, model_name="Engine 2")
        summary_1["Grade"] = grade_engine(summary_1); summary_2["Grade"] = grade_engine(summary_2)
        winner, compare_df = compare_two_models(summary_1, summary_2)
        st.info("Rezultat poređenja: TIE") if winner == "TIE" else st.success(f"Winner: {winner}")
        st.dataframe(compare_df, use_container_width=True)
    except Exception as e:
        st.error(f"Greška u compare modulu: {e}")


# =====================================================
# Save history
# =====================================================

history_folder = os.path.join(os.getcwd(), "history")
os.makedirs(history_folder, exist_ok=True)
timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
try:
    df.to_csv(os.path.join(history_folder, f"analysis_{timestamp}.csv"), index=False)
    st.caption(f"Saved history: analysis_{timestamp}.csv")
except Exception as e:
    st.warning(f"Could not save history csv: {e}")

if actual_results_df is not None and evaluated_df is not None:
    try:
        evaluated_df.to_csv(os.path.join(history_folder, f"evaluation_{timestamp}.csv"), index=False)
        st.caption(f"Saved evaluation CSV: evaluation_{timestamp}.csv")
    except Exception as e:
        st.warning(f"Could not save evaluation csv: {e}")