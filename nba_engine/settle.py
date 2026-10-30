"""Automatska evaluacija: poravnanje snimljenih analiza (``history/analysis_*.csv``) sa stvarnim poenima.

Stvarni poeni dolaze iz NBA Stats game loga igrača (isti izvor kao forma i H2H). Svaka analiza se
poravnava jednom: po pick-u u ``history/settled_<ime analize>.csv``, zbirno (jedan red po analizi) u
``history/ledger.csv``. Ocjene su iz ``evaluation.py`` (settle_pick, profit, evaluate_engine, grade_engine);
ovdje se ništa ne računa drugačije nego kod ručnog upload-a rezultata.

Pravila poravnanja:
- Gleda se samo pick OVER/UNDER (NO VALUE se ne kladi). Push vraća ulog.
- Datum meča je datum analize; analiza snimljena prije 06:00 po lokalnom vremenu pripada prethodnom
  (američkom) danu. Stvarni meč se traži ±1 dan, po protivniku iz analize.
- Igrač bez utakmice tog dana (nije igrao) = VOID: opklada bi bila poništena, ne računa se.
- Ako game log još nema nijedan meč za taj datum, analiza se preskače i pokuša sljedeći put.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import season_from_date
from .evaluation import evaluate_engine, grade_engine
from .history import list_history
from .utils import normalize_name

LEDGER_NAME = "ledger.csv"
SETTLED_PREFIX = "settled_"
US_DAY_CUTOFF_HOUR = 6          # analiza prije 06:00 lokalno → mečevi prethodnog američkog dana
_ANALYSIS_RE = re.compile(r"analysis_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})\.csv$")
_MATCHUP_RE = re.compile(r"^\s*([A-Z]{2,4})\s*(vs\.?|@)\s*([A-Z]{2,4})\s*$", re.IGNORECASE)

ActualsProvider = Callable[[str], pd.DataFrame]   # sezona → tabela stvarnih poena

LEDGER_COLUMNS = ["Analysis", "Game Date", "Picks", "Settled", "Wins", "Losses", "Pushes", "Void",
                  "Accuracy %", "Staked", "Profit", "ROI %", "MAE", "Avg CLV", "Grade", "Settled At"]


# ---------------------------------------------------------------------------
# Datumi
# ---------------------------------------------------------------------------

def analysis_datetime(path) -> Optional[_dt.datetime]:
    m = _ANALYSIS_RE.search(Path(path).name)
    if not m:
        return None
    d, hh, mm, ss = m.groups()
    return _dt.datetime.strptime(f"{d} {hh}:{mm}:{ss}", "%Y-%m-%d %H:%M:%S")


def game_date_for(path) -> Optional[_dt.date]:
    """Američki datum mečeva na koje se analiza odnosi."""
    ts = analysis_datetime(path)
    if ts is None:
        return None
    return (ts - _dt.timedelta(days=1)).date() if ts.hour < US_DAY_CUTOFF_HOUR else ts.date()


# ---------------------------------------------------------------------------
# Stvarni poeni iz game loga
# ---------------------------------------------------------------------------

def opponent_from_matchup(matchup: str, team: str) -> str:
    """'LAL vs. OKC' / 'LAL @ OKC' → protivnik tima ``team``."""
    m = _MATCHUP_RE.match(str(matchup or ""))
    if not m:
        return ""
    a, _, b = m.groups()
    a, b = a.upper(), b.upper()
    team = str(team or "").upper()
    return b if a == team else a if b == team else b


def actuals_from_game_log(gl: pd.DataFrame) -> pd.DataFrame:
    """LeagueGameLog (igrači) → NAME_KEY, PLAYER_NAME, TEAM_ABBR, OPP_TEAM, GAME_DATE (date), PTS, MIN."""
    if gl is None or gl.empty:
        return pd.DataFrame(columns=["NAME_KEY", "PLAYER_NAME", "TEAM_ABBR", "OPP_TEAM", "GAME_DATE", "PTS", "MIN"])
    df = gl.copy()
    df.columns = [str(c).upper() for c in df.columns]
    if "TEAM_ABBR" not in df.columns and "TEAM_ABBREVIATION" in df.columns:
        df["TEAM_ABBR"] = df["TEAM_ABBREVIATION"]
    needed = ["PLAYER_NAME", "TEAM_ABBR", "GAME_DATE", "PTS"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"Game log nema kolone: {missing}")
    out = pd.DataFrame({
        "PLAYER_NAME": df["PLAYER_NAME"].astype(str),
        "TEAM_ABBR": df["TEAM_ABBR"].astype(str).str.upper(),
        "GAME_DATE": pd.to_datetime(df["GAME_DATE"], errors="coerce").dt.date,
        "PTS": pd.to_numeric(df["PTS"], errors="coerce"),
        "MIN": pd.to_numeric(df["MIN"], errors="coerce") if "MIN" in df.columns else np.nan,
    })
    out["NAME_KEY"] = out["PLAYER_NAME"].map(normalize_name)
    out["OPP_TEAM"] = [opponent_from_matchup(m, t) for m, t in zip(df.get("MATCHUP", pd.Series([""] * len(df))), out["TEAM_ABBR"])]
    return out.dropna(subset=["GAME_DATE", "PTS"]).reset_index(drop=True)


def fetch_actuals(season: str, timeout: int = 90) -> pd.DataFrame:
    """Stvarni poeni za cijelu sezonu sa NBA Stats (mreža)."""
    from .refresh._nba import require_nba_api
    from .refresh.matchups import fetch_player_game_log
    require_nba_api()
    return actuals_from_game_log(fetch_player_game_log(season, timeout=timeout))


def cached_provider(fetch: ActualsProvider = fetch_actuals) -> ActualsProvider:
    cache: Dict[str, pd.DataFrame] = {}

    def _get(season: str) -> pd.DataFrame:
        if season not in cache:
            cache[season] = fetch(season)
        return cache[season]
    return _get


# ---------------------------------------------------------------------------
# Poravnanje jedne analize
# ---------------------------------------------------------------------------

def find_actual(actuals: pd.DataFrame, name_key: str, opp: Optional[str], game_date: _dt.date) -> Optional[pd.Series]:
    """Meč igrača oko datuma analize (±1 dan); kad je protivnik poznat, mora se poklopiti."""
    if actuals is None or actuals.empty:
        return None
    cand = actuals[actuals["NAME_KEY"] == name_key]
    if cand.empty:
        return None
    lo, hi = game_date - _dt.timedelta(days=1), game_date + _dt.timedelta(days=1)
    cand = cand[(cand["GAME_DATE"] >= lo) & (cand["GAME_DATE"] <= hi)]
    opp = str(opp or "").upper().strip()
    if opp and opp != "NAN":
        cand = cand[cand["OPP_TEAM"] == opp]
    else:
        cand = cand[cand["GAME_DATE"] == game_date]
    if cand.empty:
        return None
    cand = cand.assign(_dist=[abs((d - game_date).days) for d in cand["GAME_DATE"]]).sort_values("_dist")
    return cand.iloc[0]


def settle_analysis(analysis: pd.DataFrame, actuals: pd.DataFrame, game_date: _dt.date,
                    stake: float = 1.0) -> Tuple[pd.DataFrame, Dict]:
    """Poravnaj jednu snimljenu analizu. Vraća (tabela po pick-u, zbirni red za ledger bez imena fajla)."""
    picks = analysis[analysis["Model Pick"].isin(("OVER", "UNDER"))].copy()
    picks["NAME_KEY"] = picks["Player"].astype(str).map(normalize_name)
    rows = []
    for _, r in picks.iterrows():
        hit = find_actual(actuals, r["NAME_KEY"], r.get("OPP_TEAM"), game_date)
        rows.append({"NAME_KEY": r["NAME_KEY"],
                     "Actual Points": float(hit["PTS"]) if hit is not None else np.nan,
                     "Actual MIN": float(hit["MIN"]) if hit is not None and pd.notna(hit.get("MIN")) else np.nan,
                     "Actual Date": hit["GAME_DATE"].isoformat() if hit is not None else None,
                     "Actual Opp": hit["OPP_TEAM"] if hit is not None else None})
    actual_df = pd.DataFrame(rows, columns=["NAME_KEY", "Actual Points", "Actual MIN", "Actual Date", "Actual Opp"])
    actual_df = actual_df.drop_duplicates("NAME_KEY")
    if picks.empty:
        settled = picks.assign(**{"Actual Points": np.nan, "Bet Result": pd.Series(dtype=str), "Profit": 0.0})
        summary = {"Bets": 0, "Wins": 0, "Losses": 0, "Pushes": 0, "Accuracy %": 0.0, "Profit": 0.0, "ROI %": 0.0,
                   "MAE": None, "RMSE": None, "Avg Projection Edge": None, "Avg CLV": None, "Model": "Engine"}
    else:
        settled, summary = evaluate_engine(picks.drop(columns=["NAME_KEY"]), actual_df, stake=stake, model_name="Engine")
    if "Bet Result" in settled.columns:
        settled.loc[settled["Actual Points"].isna(), "Bet Result"] = "VOID"
    void = int(settled["Actual Points"].isna().sum()) if "Actual Points" in settled.columns else len(picks)
    out = {
        "Game Date": game_date.isoformat(), "Picks": int(len(picks)), "Settled": int(summary["Bets"]),
        "Wins": int(summary["Wins"]), "Losses": int(summary["Losses"]), "Pushes": int(summary["Pushes"]), "Void": void,
        "Accuracy %": summary["Accuracy %"], "Staked": round(float(summary["Bets"]) * stake, 2),
        "Profit": summary["Profit"], "ROI %": summary["ROI %"], "MAE": summary["MAE"], "Avg CLV": summary["Avg CLV"],
        "Grade": grade_engine(summary) if summary["Bets"] > 0 else "-",
    }
    return settled, out


# ---------------------------------------------------------------------------
# Ledger i prolaz kroz history/
# ---------------------------------------------------------------------------

def load_ledger(history_dir) -> pd.DataFrame:
    p = Path(history_dir) / LEDGER_NAME
    if not p.exists():
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    df = pd.read_csv(p)
    for c in LEDGER_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    return df[LEDGER_COLUMNS]


def _append_ledger(history_dir, row: Dict) -> None:
    p = Path(history_dir) / LEDGER_NAME
    ledger = load_ledger(history_dir)
    ledger = ledger[ledger["Analysis"] != row["Analysis"]]
    ledger = pd.concat([ledger, pd.DataFrame([row], columns=LEDGER_COLUMNS)], ignore_index=True)
    ledger.sort_values(["Game Date", "Analysis"]).to_csv(p, index=False)


def settle_history(history_dir, provider: Optional[ActualsProvider] = None, today: Optional[_dt.date] = None,
                   stake: float = 1.0, force: bool = False, log: Optional[Callable[[str], None]] = None) -> List[Dict]:
    """Poravnaj sve još neporavnate analize čiji su mečevi završeni. Vraća listu događaja (status po fajlu)."""
    history_dir = Path(history_dir)
    today = today or _dt.date.today()
    provider = provider or cached_provider()
    ledger = load_ledger(history_dir)
    done = set(ledger["Analysis"].astype(str)) if not ledger.empty else set()
    say = log or (lambda s: None)
    events: List[Dict] = []

    for path in list_history(history_dir):
        name = path.name
        gdate = game_date_for(path)
        if gdate is None:
            continue
        if name in done and not force:
            continue
        if gdate >= today:
            events.append({"Analysis": name, "status": "pending", "detail": "mečevi još nisu završeni"})
            continue
        season = season_from_date(gdate)
        try:
            actuals = provider(season)
        except Exception as e:  # noqa: BLE001
            events.append({"Analysis": name, "status": "error", "detail": f"stvarni rezultati nedostupni: {e}"})
            say(f"❌ {name}: stvarni rezultati nedostupni ({e})")
            continue
        if actuals.empty or not bool((actuals["GAME_DATE"] == gdate).any()):
            events.append({"Analysis": name, "status": "no_data", "detail": f"game log još nema mečeve za {gdate}"})
            say(f"⏳ {name}: game log još nema mečeve za {gdate}, pokušaj kasnije")
            continue
        try:
            analysis = pd.read_csv(path)
        except Exception as e:  # noqa: BLE001
            events.append({"Analysis": name, "status": "error", "detail": f"ne mogu pročitati analizu: {e}"})
            continue
        settled, row = settle_analysis(analysis, actuals, gdate, stake=stake)
        row = {"Analysis": name, **row, "Settled At": _dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
        settled.to_csv(history_dir / f"{SETTLED_PREFIX}{name}", index=False)
        _append_ledger(history_dir, row)
        events.append({"Analysis": name, "status": "settled", **row})
        say(f"✅ {name}: {row['Picks']} pickova, {row['Wins']}-{row['Losses']}-{row['Pushes']} (void {row['Void']}), "
            f"ROI {row['ROI %']:+.1f} %, MAE {row['MAE'] if row['MAE'] is not None else '-'}, ocjena {row['Grade']}")
    return events


def load_all_settled(history_dir) -> pd.DataFrame:
    frames = [pd.read_csv(p).assign(Analysis=p.name[len(SETTLED_PREFIX):]) for p in list_history(history_dir, SETTLED_PREFIX)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def overall_summary(settled_all: pd.DataFrame, stake: float = 1.0) -> Dict:
    """Zbir preko svih poravnatih pickova (isti pojmovi kao u evaluate_engine)."""
    if settled_all is None or settled_all.empty or "Bet Result" not in settled_all.columns:
        return {"Bets": 0, "Wins": 0, "Losses": 0, "Pushes": 0, "Void": 0, "Accuracy %": 0.0, "Profit": 0.0,
                "ROI %": 0.0, "MAE": None, "Avg CLV": None, "Grade": "-", "Days": 0}
    res = settled_all["Bet Result"].astype(str)
    wins, losses, pushes, void = int((res == "WIN").sum()), int((res == "LOSS").sum()), int((res == "PUSH").sum()), int((res == "VOID").sum())
    bets = wins + losses
    profit = float(pd.to_numeric(settled_all.get("Profit", 0.0), errors="coerce").fillna(0.0).sum())
    mae_s = pd.to_numeric(settled_all.get("Abs Error", pd.Series(dtype=float)), errors="coerce").dropna()
    clv_s = pd.to_numeric(settled_all.get("CLV", pd.Series(dtype=float)), errors="coerce").dropna()
    summary = {"Bets": bets, "Wins": wins, "Losses": losses, "Pushes": pushes, "Void": void,
               "Accuracy %": round(wins / bets * 100.0, 2) if bets else 0.0,
               "Profit": round(profit, 2), "ROI %": round(profit / (bets * stake) * 100.0, 2) if bets else 0.0,
               "MAE": round(float(mae_s.mean()), 3) if not mae_s.empty else None,
               "Avg CLV": round(float(clv_s.mean()), 3) if not clv_s.empty else None,
               "Days": int(settled_all["Analysis"].nunique()) if "Analysis" in settled_all.columns else 0}
    summary["Grade"] = grade_engine(summary) if bets else "-"
    return summary
