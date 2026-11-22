"""Poravnanje i poređenje v2 sa starim modelom i jednostavnim pravilima.

Stari ``settle_history`` poravnava samo izbore (OVER/UNDER). Za pošteno poređenje v2 poravnava i CEO spisak igrača
(``history/v2/universe_settled_<analiza>.csv``), pa se na istim igračima i istim danima mogu mjeriti:

- ``V2``         izbori v2 modela
- ``UNDER``      uvijek "manje" (najbolja kvota na istoj liniji)
- ``OVER``       uvijek "više"
- ``TRZISTE``    strana koju tržište smatra vjerovatnijom (fer vjerovatnoća ≥ 50 %)
- ``NASUMICNO``  nasumična strana (deterministički, po imenu igrača i datumu)

Zbirne vrijednosti po danu idu u ``history/v2/benchmarks.csv``. Isti fajlovi daju tabelu "obećano naspram ostvareno"
(kalibracija), procjenu težine koju model zaslužuje iznad tržišta i napredak do pregleda na 500 i 2.000 izbora.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import math
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .evaluation import calculate_bet_profit, settle_pick
from .history import list_history
from .settle import (ActualsProvider, cached_provider, find_actual, game_date_for, load_all_settled, load_ledger,
                     official_analyses, settle_history)
from .utils import normalize_name
from .v2 import FAIR_SOURCES_OK, ResidualModel, build_calibration, fair_from_quotes, load_quotes, shift_p_over

UNI_PREFIX = "universe_settled_"
BENCH_NAME = "benchmarks.csv"
BENCH_COLUMNS = ["Analysis", "Game Date", "Strategy", "Bets", "Wins", "Losses", "Void", "Staked", "Profit", "Avg Odds"]
STRATEGIES = ["V2", "UNDER", "OVER", "TRZISTE", "NASUMICNO"]
STRATEGY_LABELS = {"V2": "v2 izbori", "UNDER": "Uvijek manje", "OVER": "Uvijek više",
                   "TRZISTE": "Strana koju tržište smatra vjerovatnijom", "NASUMICNO": "Nasumična strana",
                   "V1": "Stari model (v1)", "AI": "AI izbori"}
GATE_CLV_BETS = 500          # prvi pregled: završna linija (CLV)
GATE_RESULT_BETS = 2000      # drugi pregled: pogodak i ROI
BREAK_EVEN_NOTE = "prag rentabilnosti ≈ 1 / prosječna kvota"


# ---------------------------------------------------------------------------
# Strane po strategijama
# ---------------------------------------------------------------------------

def _random_side(player: str, key: str) -> str:
    h = hashlib.sha1(f"{key}|{normalize_name(player)}".encode("utf-8")).digest()[0]
    return "OVER" if h % 2 == 0 else "UNDER"


def strategy_sides(df: pd.DataFrame, key: str = "") -> Dict[str, pd.Series]:
    """Strana (OVER/UNDER ili NaN) po strategiji za svaki red spiska. Svi koriste najbolje kvote na istoj liniji."""
    n = len(df)
    has_odds = pd.to_numeric(df["Over Odds"], errors="coerce").gt(1.0) & pd.to_numeric(df["Under Odds"], errors="coerce").gt(1.0)
    fair = pd.to_numeric(df.get("V2 Fair P(Over)%"), errors="coerce")
    fallback = pd.to_numeric(df.get("Market P(Over)%"), errors="coerce")
    p_mkt = fair.fillna(fallback)
    idx = df.index
    out = {
        "V2": df["V2 Pick"].where(df["V2 Pick"].isin(["OVER", "UNDER"])) if "V2 Pick" in df.columns else pd.Series(np.nan, index=idx),
        "UNDER": pd.Series(np.where(has_odds, "UNDER", None), index=idx),
        "OVER": pd.Series(np.where(has_odds, "OVER", None), index=idx),
        "TRZISTE": pd.Series(np.where(has_odds & p_mkt.notna(), np.where(p_mkt >= 50.0, "OVER", "UNDER"), None), index=idx),
        "NASUMICNO": pd.Series([_random_side(p, key) if h else None for p, h in zip(df["Player"], has_odds)], index=idx),
    }
    return {k: v.astype(object) for k, v in out.items()}


# ---------------------------------------------------------------------------
# Poravnanje cijelog spiska
# ---------------------------------------------------------------------------

def closing_fair_for(closing_quotes: Optional[pd.DataFrame], player: str, line: float):
    """Fer vjerovatnoća Over na zatvaranju za NAŠU liniju ili None. Kad se linija pomjerila, uzima se najbliža linija koja
    ima pouzdanu fer cijenu i preračuna se na našu (``shift_p_over``): izbori sa pomjerenom linijom su najinformativniji."""
    if closing_quotes is None or closing_quotes.empty:
        return None
    g = closing_quotes[closing_quotes["NAME_KEY"] == normalize_name(player)]
    if g.empty:
        return None
    lines = sorted({float(x) for x in pd.to_numeric(g["LINE"], errors="coerce").dropna()}, key=lambda l: abs(l - line))
    for l in lines:
        f = fair_from_quotes(g, l)
        if f.ok:
            return shift_p_over(float(f.p_over), l, line)
    return None


def settle_universe(analysis: pd.DataFrame, actuals: pd.DataFrame, game_date: _dt.date, key: str = "",
                    closing_quotes: Optional[pd.DataFrame] = None, stake: float = 1.0) -> pd.DataFrame:
    """Jedan red po igraču: stvarni poeni, da li je prošlo Over, i ishod/profit za svaku strategiju."""
    df = analysis.copy().reset_index(drop=True)
    sides = strategy_sides(df, key=key)
    rows = []
    for i, r in df.iterrows():
        nk = normalize_name(r["Player"])
        hit = find_actual(actuals, nk, r.get("OPP_TEAM"), game_date)
        pts = float(hit["PTS"]) if hit is not None else np.nan
        mins = float(hit["MIN"]) if hit is not None and pd.notna(hit.get("MIN")) else np.nan
        line = float(r["Line"])
        row = {"Player": r["Player"], "NAME_KEY": nk, "TEAM_ABBR": r.get("TEAM_ABBR"), "OPP_TEAM": r.get("OPP_TEAM"),
               "Line": line, "Over Odds": r["Over Odds"], "Under Odds": r["Under Odds"],
               "Calibrated Projection": r.get("Calibrated Projection"),
               "V2 Fair P(Over)%": r.get("V2 Fair P(Over)%"), "V2 Fair Source": r.get("V2 Fair Source"),
               "V2 Model P(Over)%": r.get("V2 Model P(Over)%"), "V2 P(Over)%": r.get("V2 P(Over)%"),
               "V1 P(Over)%": r.get("P(Over)%"), "V1 Pick": r.get("V1 Pick"), "V2 Pick": r.get("V2 Pick"),
               "Market P(Over)%": r.get("Market P(Over)%"), "V2 EV %": r.get("V2 EV %"),
               "Actual Points": pts, "Actual MIN": mins,
               "Over Won": (np.nan if math.isnan(pts) or pts == line else (1.0 if pts > line else 0.0))}   # push se ne broji
        for s in STRATEGIES:
            side = sides[s].iloc[i]
            if side not in ("OVER", "UNDER"):
                row[f"{s} Side"], row[f"{s} Result"], row[f"{s} Profit"], row[f"{s} Odds"] = None, None, 0.0, np.nan
                continue
            odds = float(r["Over Odds"] if side == "OVER" else r["Under Odds"])
            res = "VOID" if math.isnan(pts) else settle_pick(side, line, pts)
            row[f"{s} Side"], row[f"{s} Result"], row[f"{s} Odds"] = side, res, odds
            row[f"{s} Profit"] = calculate_bet_profit(res, odds, stake)
        # završna vrijednost za v2 izbore: kvota koju smo uzeli × fer vjerovatnoća strane na zatvaranju − 1
        row["CLV EV %"] = np.nan
        if row["V2 Side"] in ("OVER", "UNDER"):
            p_close = closing_fair_for(closing_quotes, r["Player"], line)
            if p_close is not None:
                p_side = p_close if row["V2 Side"] == "OVER" else 1.0 - p_close
                row["CLV EV %"] = round((row["V2 Odds"] * p_side - 1.0) * 100.0, 2)
                row["Closing Fair P(Over)%"] = round(p_close * 100.0, 2)
        rows.append(row)
    return pd.DataFrame(rows)


def benchmark_rows(uni: pd.DataFrame, analysis_name: str, game_date: _dt.date) -> List[Dict]:
    out = []
    for s in STRATEGIES:
        res = uni[f"{s} Result"]
        wins, losses = int((res == "WIN").sum()), int((res == "LOSS").sum())
        void = int((res == "VOID").sum())
        graded = uni[res.isin(["WIN", "LOSS", "PUSH"])]
        out.append({"Analysis": analysis_name, "Game Date": game_date.isoformat(), "Strategy": s,
                    "Bets": wins + losses, "Wins": wins, "Losses": losses, "Void": void,
                    "Staked": float(wins + losses), "Profit": round(float(uni[f"{s} Profit"].sum()), 4),
                    "Avg Odds": round(float(graded[f"{s} Odds"].mean()), 4) if len(graded) else np.nan})
    return out


def load_benchmarks(v2_dir) -> pd.DataFrame:
    p = Path(v2_dir) / BENCH_NAME
    if not p.exists():
        return pd.DataFrame(columns=BENCH_COLUMNS)
    df = pd.read_csv(p)
    for c in BENCH_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    return df[BENCH_COLUMNS]


def settle_v2_universe(v2_dir, provider: Optional[ActualsProvider] = None, today: Optional[_dt.date] = None,
                       closing_dir=None, force: bool = False, log: Optional[Callable[[str], None]] = None) -> List[Dict]:
    """Poravnaj ceo spisak za svaku zvaničnu v2 analizu čiji su mečevi završeni."""
    from .config import season_from_date
    v2_dir = Path(v2_dir)
    today = today or _dt.date.today()
    provider = provider or cached_provider()
    say = log or (lambda s: None)
    bench = load_benchmarks(v2_dir)
    done = set(bench["Analysis"].astype(str))
    events: List[Dict] = []
    paths = list_history(v2_dir)
    official = official_analyses(paths)
    for path in paths:
        name = path.name
        gdate = game_date_for(path)
        if gdate is None or official.get(gdate) != path:
            continue
        if name in done and not force:
            continue
        if gdate >= today:
            events.append({"Analysis": name, "status": "pending", "detail": "mečevi još nisu završeni"})
            continue
        try:
            actuals = provider(season_from_date(gdate))
        except Exception as e:  # noqa: BLE001
            events.append({"Analysis": name, "status": "error", "detail": f"stvarni rezultati nedostupni: {e}"})
            say(f"❌ v2 {name}: stvarni rezultati nedostupni ({e})")
            continue
        if actuals.empty or not bool((actuals["GAME_DATE"] == gdate).any()):
            events.append({"Analysis": name, "status": "no_data", "detail": f"game log još nema mečeve za {gdate}"})
            continue
        try:
            analysis = pd.read_csv(path)
        except Exception as e:  # noqa: BLE001 — oštećena analiza ne smije zaustaviti poravnanje kasnijih dana
            events.append({"Analysis": name, "status": "error", "detail": f"ne mogu pročitati analizu: {e}"})
            say(f"❌ v2 {name}: ne mogu pročitati analizu ({e})")
            continue
        cq = load_quotes(Path(closing_dir) / f"closing_quotes_{gdate.isoformat()}.csv") if closing_dir else None
        uni = settle_universe(analysis, actuals, gdate, key=gdate.isoformat(), closing_quotes=cq)
        uni.to_csv(v2_dir / f"{UNI_PREFIX}{name}", index=False)
        bench = bench[bench["Analysis"] != name]
        bench = pd.concat([bench, pd.DataFrame(benchmark_rows(uni, name, gdate), columns=BENCH_COLUMNS)], ignore_index=True)
        bench.sort_values(["Game Date", "Strategy"]).to_csv(v2_dir / BENCH_NAME, index=False)
        v2row = [r for r in benchmark_rows(uni, name, gdate) if r["Strategy"] == "V2"][0]
        events.append({"Analysis": name, "status": "settled", **v2row})
        say(f"✅ v2 {name}: {len(uni)} igrača poravnato, v2 izbora {v2row['Bets']} ({v2row['Wins']}-{v2row['Losses']})")
    return events


def settle_v2(settings, provider: Optional[ActualsProvider] = None, today: Optional[_dt.date] = None,
              log: Optional[Callable[[str], None]] = None) -> str:
    """Poravnanje izbora v2 (ledger kao i kod v1, uz CLV iz zatvorenih linija) + cijelog spiska i poređenja."""
    v2_dir = settings.v2_history_dir
    if not v2_dir.is_dir():
        return "v2: još nema analiza"
    provider = provider or cached_provider()
    ev = settle_history(v2_dir, provider=provider, today=today, closing_dir=settings.data_dir,
                        log=(lambda m: log("v2 — " + m)) if log else None)
    ev2 = settle_v2_universe(v2_dir, provider=provider, today=today, closing_dir=settings.data_dir, log=log)
    n1 = sum(1 for e in ev if e["status"] == "settled")
    n2 = sum(1 for e in ev2 if e["status"] == "settled")
    wait = sum(1 for e in ev2 if e["status"] in ("pending", "no_data"))
    return f"v2: poravnato izbora {n1}, cijelih spiskova {n2}, čeka mečeve {wait}"


# ---------------------------------------------------------------------------
# Pregled: poređenje, kalibracija, težina modela, pragovi
# ---------------------------------------------------------------------------

def load_universe_settled(v2_dir) -> pd.DataFrame:
    frames = [pd.read_csv(p).assign(Analysis=p.name[len(UNI_PREFIX):]) for p in list_history(v2_dir, UNI_PREFIX)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _strategy_line(label: str, bets: int, wins: int, profit: float, void: int, days: int, odds: float) -> Dict:
    hit = wins / bets * 100.0 if bets else np.nan
    return {"Pravilo": label, "Dana": days, "Izbora": bets, "Pogodaka": wins, "Pogodak %": round(hit, 1) if bets else np.nan,
            "ROI %": round(profit / bets * 100.0, 1) if bets else np.nan, "Prosj. kvota": round(odds, 3) if odds == odds else np.nan,
            "Prag %": round(100.0 / odds, 1) if odds == odds and odds else np.nan, "Poništeno": void}


def comparison_table(settings) -> pd.DataFrame:
    """v2, jednostavna pravila, stari model i AI izbori — samo za dane koje v2 pokriva."""
    bench = load_benchmarks(settings.v2_history_dir)
    if bench.empty:
        return pd.DataFrame()
    days = set(bench["Game Date"].astype(str))
    rows = []
    for s in STRATEGIES:
        b = bench[bench["Strategy"] == s]
        bets, wins = int(b["Bets"].sum()), int(b["Wins"].sum())
        odds = float((b["Avg Odds"] * b["Bets"]).sum() / b["Bets"].sum()) if bets else float("nan")
        rows.append(_strategy_line(STRATEGY_LABELS[s], bets, wins, float(b["Profit"].sum()), int(b["Void"].sum()),
                                   b["Game Date"].nunique(), odds))
    for label, hdir in (("V1", settings.history_dir), ("AI", settings.ai_history_dir)):
        led = load_ledger(hdir)
        led = led[led["Game Date"].astype(str).isin(days)] if not led.empty else led
        if led.empty:
            continue
        bets, wins = int(led["Wins"].sum() + led["Losses"].sum()), int(led["Wins"].sum())
        settled = load_all_settled(hdir)
        if not settled.empty and "Used Odds" in settled.columns:
            keep = set(led["Analysis"].astype(str))
            s2 = settled[settled["Analysis"].isin(keep) & settled["Bet Result"].isin(["WIN", "LOSS"])]
            odds = float(pd.to_numeric(s2["Used Odds"], errors="coerce").mean()) if len(s2) else float("nan")
        else:
            odds = float("nan")
        rows.append(_strategy_line(STRATEGY_LABELS[label], bets, wins, float(led["Profit"].sum()), int(led["Void"].sum()),
                                   led["Game Date"].nunique(), odds))
    return pd.DataFrame(rows)


def calibration_table(uni: pd.DataFrame, col: str, edges=(0, 35, 45, 55, 65, 100)) -> pd.DataFrame:
    """Obećana vjerovatnoća Over (kolona ``col``, u %) naspram stvarnog udjela Over, po grupama."""
    if uni is None or uni.empty or col not in uni.columns:
        return pd.DataFrame(columns=["Grupa", "Igrača", "Obećano %", "Ostvareno %"])
    d = uni[[col, "Over Won"]].apply(pd.to_numeric, errors="coerce").dropna()
    if d.empty:
        return pd.DataFrame(columns=["Grupa", "Igrača", "Obećano %", "Ostvareno %"])
    d["g"] = pd.cut(d[col], list(edges), include_lowest=True)
    rows = []
    for g, x in d.groupby("g", observed=True):
        rows.append({"Grupa": f"{int(g.left)}–{int(g.right)} %", "Igrača": int(len(x)),
                     "Obećano %": round(float(x[col].mean()), 1), "Ostvareno %": round(float(x["Over Won"].mean() * 100.0), 1)})
    return pd.DataFrame(rows)


def fit_model_weight(uni: pd.DataFrame) -> Dict:
    """Koliko težine model zaslužuje iznad tržišta: nagib stvarnog ishoda (Over) na razliku (model − fer).
    0 = model ne dodaje ništa, 1 = model je bolji nego što tržište priznaje. Vraća i 95 % raspon."""
    out = {"n": 0, "weight": None, "lo": None, "hi": None, "market_coef": None}
    if uni is None or uni.empty:
        return out
    d = uni[uni["V2 Fair Source"].isin(FAIR_SOURCES_OK)][["V2 Fair P(Over)%", "V2 Model P(Over)%", "Over Won"]]
    d = d.apply(pd.to_numeric, errors="coerce").dropna()
    n = len(d)
    out["n"] = n
    if n < 30:
        return out
    pf, pm, y = d["V2 Fair P(Over)%"].to_numpy() / 100.0, d["V2 Model P(Over)%"].to_numpy() / 100.0, d["Over Won"].to_numpy()
    X = np.column_stack([np.ones(n), pf - 0.5, pm - pf])
    try:
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        r = y - X @ b
        cov = (r @ r / (n - 3)) * np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        return out
    se = float(np.sqrt(cov[2, 2]))
    out.update(weight=round(float(b[2]), 3), lo=round(float(b[2] - 1.96 * se), 3), hi=round(float(b[2] + 1.96 * se), 3),
               market_coef=round(float(b[1]), 3))
    return out


def gate_status(bets: int, clv_n: int) -> List[Dict]:
    """Napredak do unaprijed zadatih pregleda: ne tvrdi se da prednost postoji prije toga."""
    return [{"Pregled": f"{GATE_CLV_BETS} izbora (završna linija, CLV)", "Cilj": GATE_CLV_BETS, "Izbora": clv_n,
             "Gotovo %": round(min(clv_n / GATE_CLV_BETS, 1.0) * 100.0, 0)},
            {"Pregled": f"{GATE_RESULT_BETS} izbora (pogodak i ROI)", "Cilj": GATE_RESULT_BETS, "Izbora": bets,
             "Gotovo %": round(min(bets / GATE_RESULT_BETS, 1.0) * 100.0, 0)}]


def v2_overview(settings) -> Dict:
    """Sve za izvještaj i aplikaciju jednim pozivom (bez izuzetaka kad nema podataka)."""
    uni = load_universe_settled(settings.v2_history_dir) if settings.v2_history_dir.is_dir() else pd.DataFrame()
    comp = comparison_table(settings)
    bets = int(comp.loc[comp["Pravilo"] == STRATEGY_LABELS["V2"], "Izbora"].sum()) if not comp.empty else 0
    clv = pd.to_numeric(uni.get("CLV EV %"), errors="coerce").dropna() if not uni.empty and "CLV EV %" in uni.columns else pd.Series(dtype=float)
    return {
        "comparison": comp,
        "calibration": {c: calibration_table(uni, c) for c in ("V2 Fair P(Over)%", "V1 P(Over)%", "V2 Model P(Over)%")},
        "weight": fit_model_weight(uni),
        "clv": {"n": int(len(clv)), "mean": round(float(clv.mean()), 2) if len(clv) else None,
                "positive_share": round(float((clv > 0).mean() * 100.0), 1) if len(clv) else None},
        "gates": gate_status(bets, int(len(clv))),
        "universe_rows": int(len(uni)),
        "days": int(uni["Analysis"].nunique()) if not uni.empty else 0,
    }


def latest_v2_picks(settings) -> Tuple[Optional[str], pd.DataFrame, int]:
    """(ime fajla, izbori sa rangom, broj igrača u spisku) za zadnju v2 analizu; zvanična (daily) ima prednost."""
    from .history import DAILY_TAG, analysis_tag
    paths = list_history(settings.v2_history_dir)
    if not paths:
        return None, pd.DataFrame(), 0
    daily = [p for p in paths if analysis_tag(p) == DAILY_TAG]
    path = (daily or paths)[-1]
    df = pd.read_csv(path)
    picks = df[df["V2 Pick"].isin(["OVER", "UNDER"])].sort_values("V2 Rank")
    cols = ["V2 Rank", "Player", "TEAM_ABBR", "OPP_TEAM", "V2 Pick", "Line", "Over Odds", "Under Odds",
            "V2 Fair P(Over)%", "V2 P(Over)%", "V2 EV %", "V2 Fair Source", "V2 Over Book", "V2 Under Book"]
    return path.name, picks[[c for c in cols if c in picks.columns]], len(df)


# ---------------------------------------------------------------------------
# Kalibracija iz podataka i provjera unazad (hodajući prozor)
# ---------------------------------------------------------------------------

def _day_of(analysis_name: pd.Series) -> pd.Series:
    return analysis_name.astype(str).str.extract(r"analysis_(\d{4}-\d{2}-\d{2})")[0]


def calibrate_from_history(settings, extra_universe: bool = True) -> dict:
    """Kalibracija ostataka iz poravnatih v1 izbora; za dane koje pokriva cijeli v2 spisak uzima se spisak (nepristrasan,
    svi igrači), a v1 izbori tih dana se ne broje dva puta."""
    v1 = load_all_settled(settings.history_dir)
    src = "history/settled_*"
    frames = []
    uni = pd.DataFrame()
    if extra_universe and settings.v2_history_dir.is_dir():
        uni = load_universe_settled(settings.v2_history_dir)
        if not uni.empty and "Calibrated Projection" not in uni.columns:
            uni = pd.DataFrame()
    if not v1.empty:
        if not uni.empty:
            v1 = v1[~_day_of(v1["Analysis"]).isin(set(_day_of(uni["Analysis"])))]
        frames.append(v1)
    if not uni.empty:
        frames.append(uni)
        src += " + history/v2/universe_settled_*"
    frames = [f for f in frames if not f.empty]
    if not frames:
        return {"version": 1, "built": pd.Timestamp.now().date().isoformat(), "n": 0, "source": src, "buckets": {}}
    return build_calibration(pd.concat(frames, ignore_index=True), source=src)


def walk_forward(settled: pd.DataFrame, min_train_days: int = 6, weights=(0.0, 0.25, 0.5, 1.0)) -> Dict:
    """Za svaki dan: kalibracija iz ranijih dana → vjerovatnoće za taj dan → mjera greške (Brier) naspram ishoda.
    Poredi: stara vjerovatnoća modela (v1), tržište (Market P iz v1), model sa ispravnim rasponom i mješavine."""
    need = {"Bet Result", "Actual Points", "Calibrated Projection", "Line", "P(Over)%", "Market P(Over)%", "Analysis"}
    if settled is None or settled.empty or not need <= set(settled.columns):
        return {"days": 0}
    d = settled.copy()
    d = d[d["Bet Result"].isin(["WIN", "LOSS"])].copy()
    for c in ("Actual Points", "Calibrated Projection", "Line", "P(Over)%", "Market P(Over)%"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["Actual Points", "Calibrated Projection", "Line", "P(Over)%", "Market P(Over)%"])
    d["day"] = d["Analysis"].astype(str).str.extract(r"analysis_(\d{4}-\d{2}-\d{2})")[0]
    days = sorted(d["day"].unique())
    d["y"] = (d["Actual Points"] > d["Line"]).astype(float)
    rows = []
    for i, day in enumerate(days):
        if i < min_train_days:
            continue
        train, test = d[d["day"].isin(days[:i])], d[d["day"] == day]
        rm = ResidualModel({k: v["q"] for k, v in build_calibration(train)["buckets"].items()})
        pm = np.array([rm.p_over(c, l) for c, l in zip(test["Calibrated Projection"], test["Line"])])
        pf = test["Market P(Over)%"].to_numpy() / 100.0
        row = {"day": day, "n": len(test), "y": test["y"].to_numpy(), "v1": test["P(Over)%"].to_numpy() / 100.0,
               "market": pf, "coin": np.full(len(test), 0.5), "model_v2": pm}
        for w in weights:
            row[f"mix_{w}"] = pf + w * (pm - pf)
        rows.append(row)
    if not rows:
        return {"days": 0}
    y = np.concatenate([r["y"] for r in rows])
    keys = ["coin", "market", "v1", "model_v2"] + [f"mix_{w}" for w in weights]
    out = {"days": len(rows), "n": int(len(y)), "first_test_day": rows[0]["day"], "brier": {}, "logloss": {}}
    for k in keys:
        p = np.clip(np.concatenate([r[k] for r in rows]), 0.01, 0.99)
        out["brier"][k] = round(float(np.mean((p - y) ** 2)), 4)
        out["logloss"][k] = round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4)
    # obećano naspram ostvareno za stari i novi model (samo vjerovatnoće ≥ 60 % za Over, kao najvidljivija greška)
    for k in ("v1", "model_v2"):
        p = np.concatenate([r[k] for r in rows])
        hi = p >= 0.60
        out[f"{k}_over_ge60"] = {"n": int(hi.sum()), "promised": round(float(p[hi].mean() * 100), 1) if hi.any() else None,
                                 "actual": round(float(y[hi].mean() * 100), 1) if hi.any() else None}
    return out


# ---------------------------------------------------------------------------
# Tekstualni ispis (komandna linija)
# ---------------------------------------------------------------------------

def render_overview(ov: Dict) -> str:
    out = ["📊 v2 (u sjeni) — poređenje na istim danima", ""]
    comp = ov.get("comparison")
    if comp is None or comp.empty:
        out.append("Još nema poravnatih v2 dana (v2 počinje poslije prvog dnevnog posla; poravnanje dolazi dan kasnije).")
    else:
        out.append(comp.to_string(index=False))
        out.append(f"({BREAK_EVEN_NOTE})")
    w = ov.get("weight", {})
    out += ["", "⚖️ Težina koju model zaslužuje iznad tržišta (0 = ništa, 1 = bolji nego što tržište priznaje):"]
    if w.get("weight") is None:
        out.append(f"   premalo podataka ({w.get('n', 0)} igrača; treba najmanje 30)")
    else:
        out.append(f"   {w['weight']:+.2f}  (95 % raspon {w['lo']:+.2f} do {w['hi']:+.2f}, igrača {w['n']})")
    clv = ov.get("clv", {})
    out += ["", "📐 Završna vrijednost (CLV): " + (
        f"srednje {clv['mean']:+.2f} % očekivane vrijednosti naspram fer cijene na zatvaranju, izbora {clv['n']}, "
        f"pozitivno u {clv['positive_share']} % izbora" if clv.get("n") else "još nema zatvorenih linija (uključi: schedule --install-closing)")]
    out += ["", "🎯 Pregledi unaprijed:"]
    for g in ov.get("gates", []):
        out.append(f"   {g['Pregled']}: {g['Izbora']}/{g['Cilj']} ({g['Gotovo %']:.0f} %)")
    for col, t in (ov.get("calibration") or {}).items():
        if t is not None and not t.empty:
            out += ["", f"Obećano naspram ostvareno — {col}:", t.to_string(index=False)]
    return "\n".join(out)


def render_walk_forward(wf: Dict) -> str:
    if not wf.get("days"):
        return "Premalo dana za provjeru unazad (treba više od 6 poravnatih dana)."
    names = {"coin": "bacanje novčića 50 %", "market": "tržište (Market P iz v1)", "v1": "stari model (v1)",
             "model_v2": "model sa ispravnim rasponom"}
    out = [f"🔙 Provjera unazad: {wf['days']} dana, {wf['n']} izbora, prvi testni dan {wf['first_test_day']} "
           f"(kalibracija se svaki dan uči samo iz ranijih dana)", "",
           f"{'vjerovatnoća':40s} {'Brier':>8s} {'log-gubitak':>12s}   (manje = bolje)"]
    for k, b in wf["brier"].items():
        label = names.get(k) or (f"tržište + {k.split('_')[1]} × (model − tržište)")
        out.append(f"{label:40s} {b:8.4f} {wf['logloss'][k]:12.4f}")
    for k, label in (("v1", "stari model"), ("model_v2", "model sa ispravnim rasponom")):
        d = wf.get(f"{k}_over_ge60")
        if d and d["n"]:
            out.append(f"Kad {label} daje Over ≥ 60 %: obećano {d['promised']} %, ostvareno {d['actual']} % ({d['n']} izbora)")
    return "\n".join(out)
