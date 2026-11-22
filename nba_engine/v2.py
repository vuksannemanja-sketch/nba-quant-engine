"""v2 (radi u sjeni, uporedo sa starim modelom): tržište kao osnova, model samo kao mala korekcija.

Zašto: pregled od 22.11.2026 (20 dana, 1.370 izbora) pokazao je da odstupanje modela od granice kladionice ne predviđa
ishod (nagib oko nule), da je raspon (sigma) preuzak za igrače sa niskom granicom i da rang po True Score nema veze
sa ishodom. v2 zato radi ovako:

1. **Fer vjerovatnoća** dolazi iz tržišta: bez marže ("devig") kvote Pinnacle-a na istoj liniji; ako Pinnacle nema tu
   liniju, prosjek najmanje tri kladionice sa istom linijom. Bez toga igrač ne ulazi u izbor.
2. **Model** (kalibrisana projekcija iz v1) daje svoju vjerovatnoću, ali sa ispravnim rasponom i iskrivljenom raspodjelom:
   stvarni ostaci (stvarni poeni minus projekcija) po grupi granice, umjesto normalne raspodjele sa preuskom sigmom.
3. **Konačna vjerovatnoća** = fer + težina × (model − fer). Težina je podrazumijevano **0** (V2_MODEL_WEIGHT u .env):
   podaci kažu da model ne zaslužuje težinu. Podiže se tek kad poravnata statistika (v2_eval.fit_model_weight) to dokaže.
4. **Cijena**: kvota je najbolja među kladionicama sa istom linijom (kao u v1). Izbor ima smisla samo ako je očekivana
   vrijednost (EV) najmanje ``MIN_EV``; ako je kvota više od ``MAX_EV`` iznad fer cijene, to je sumnjivo
   (zastarjela linija, pogrešna kvota) i izbor se preskače.
5. **Rang** po EV, najviše ``MAX_PICKS`` dnevno i ``MAX_PER_GAME`` po utakmici. Dan bez izbora je ispravan ishod.

v2 piše u ``history/v2/`` (ceo spisak igrača sa svim kolonama, ne samo izbore), pa su poređenja sa starim modelom i sa
jednostavnim pravilima ("uvijek manje", "strana koju tržište smatra vjerovatnijom") moguća na istim danima.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import ENV_V2_MODEL_WEIGHT
from .utils import normalize_name

Logger = Callable[[str], None]

SHARP_BOOK = "pinnacle"
MIN_BOOKS_CONSENSUS = 3          # bez Pinnacle-a: najmanje toliko kladionica sa istom linijom
MIN_EV = 0.01                    # izbor traži najmanje +1 % očekivane vrijednosti nad fer cijenom
MAX_EV = 0.15                    # kvota >15 % iznad fer cijene: gotovo sigurno zastarjela linija ili pogrešna kvota
MAX_PICKS = 10
MAX_PER_GAME = 3
PROB_CLAMP = (0.03, 0.97)
CALIBRATION_FILE = Path(__file__).with_name("v2_calibration.json")

LINE_BUCKETS: List[Tuple[str, float]] = [("<=7.5", 7.5), ("8-12.5", 12.5), ("13-17.5", 17.5), ("18-22.5", 22.5), ("23+", math.inf)]
# rezerva kad nema kalibracije: stvarno rasipanje (poeni minus granica) izmjereno 22.11.2026 na 1.370 izbora
DEFAULT_SIGMA = {"<=7.5": 4.8, "8-12.5": 6.3, "13-17.5": 6.8, "18-22.5": 7.4, "23+": 7.6}
FAIR_SOURCES_OK = ("pinnacle", "konsenzus")


# ---------------------------------------------------------------------------
# Fer vjerovatnoća i cijena iz kvota po kladionici
# ---------------------------------------------------------------------------

def devig(over_odds: float, under_odds: float) -> Optional[float]:
    """Vjerovatnoća Over bez marže (proporcionalno) iz kvota obje strane; None za neispravne kvote."""
    try:
        o, u = float(over_odds), float(under_odds)
    except (TypeError, ValueError):
        return None
    if not (o > 1.0 and u > 1.0) or math.isnan(o) or math.isnan(u):
        return None
    po, pu = 1.0 / o, 1.0 / u
    return po / (po + pu)


@dataclass
class Fair:
    p_over: Optional[float]
    source: str                 # "pinnacle" | "konsenzus" | "nedovoljno"
    n_books: int                # kladionica sa istom linijom
    best_over: Optional[float] = None
    best_over_book: str = ""
    best_under: Optional[float] = None
    best_under_book: str = ""

    @property
    def ok(self) -> bool:
        return self.p_over is not None and self.source in FAIR_SOURCES_OK


def fair_from_quotes(q: pd.DataFrame, line: float, sharp: str = SHARP_BOOK,
                     min_books: int = MIN_BOOKS_CONSENSUS) -> Fair:
    """Fer vjerovatnoća i najbolje kvote iz kvota jednog igrača (kolone BOOK, LINE, OVER_ODDS, UNDER_ODDS).
    Gleda se samo ista linija kao ona koju v1 koristi."""
    if q is None or q.empty:
        return Fair(None, "nedovoljno", 0)
    same = q[np.isclose(pd.to_numeric(q["LINE"], errors="coerce"), float(line))].copy()
    same["OVER_ODDS"] = pd.to_numeric(same["OVER_ODDS"], errors="coerce")
    same["UNDER_ODDS"] = pd.to_numeric(same["UNDER_ODDS"], errors="coerce")
    same = same.dropna(subset=["OVER_ODDS", "UNDER_ODDS"])
    if same.empty:
        return Fair(None, "nedovoljno", 0)
    same["P"] = [devig(o, u) for o, u in zip(same["OVER_ODDS"], same["UNDER_ODDS"])]
    same = same.dropna(subset=["P"])
    if same.empty:
        return Fair(None, "nedovoljno", 0)
    bo = same.loc[same["OVER_ODDS"].idxmax()]
    bu = same.loc[same["UNDER_ODDS"].idxmax()]
    kw = dict(n_books=len(same), best_over=float(bo["OVER_ODDS"]), best_over_book=str(bo["BOOK"]),
              best_under=float(bu["UNDER_ODDS"]), best_under_book=str(bu["BOOK"]))
    sharp_rows = same[same["BOOK"].astype(str).str.lower() == sharp]
    if not sharp_rows.empty:
        return Fair(float(sharp_rows["P"].iloc[0]), "pinnacle", **kw)
    if len(same) >= min_books:
        return Fair(float(same["P"].mean()), "konsenzus", **kw)
    return Fair(None, "nedovoljno", **kw)


def load_quotes(path) -> Optional[pd.DataFrame]:
    """quotes_<datum>.csv / closing_quotes_<datum>.csv → tabela sa NAME_KEY; None ako fajla nema ili je neispravan."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
    except Exception:  # noqa: BLE001
        return None
    need = {"PLAYER", "BOOK", "LINE", "OVER_ODDS", "UNDER_ODDS"}
    if not need <= set(df.columns):
        return None
    df["NAME_KEY"] = df["PLAYER"].astype(str).map(normalize_name)
    return df


# ---------------------------------------------------------------------------
# Model sa stvarnim ostacima (ispravan raspon i oblik raspodjele)
# ---------------------------------------------------------------------------

def line_bucket(line: float) -> str:
    for label, hi in LINE_BUCKETS:
        if line <= hi:
            return label
    return LINE_BUCKETS[-1][0]


def _normal_over(center: float, line: float, sigma: float) -> float:
    z = (line - center) / max(sigma, 0.5)
    return 0.5 * math.erfc(z / math.sqrt(2.0))


class ResidualModel:
    """P(Over) = udio stvarnih ostataka (poeni minus projekcija) po grupi granice koji prelaze (granica − projekcija).
    Bez kalibracije koristi normalnu raspodjelu sa izmjerenom sigmom po grupi."""

    def __init__(self, buckets: Optional[Dict[str, np.ndarray]] = None, meta: Optional[dict] = None):
        self.buckets = {k: np.sort(np.asarray(v, dtype=float)) for k, v in (buckets or {}).items() if len(v) >= 20}
        self.meta = meta or {}

    @classmethod
    def load(cls, path=None) -> "ResidualModel":
        p = Path(path or CALIBRATION_FILE)
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return cls({k: v["q"] for k, v in data.get("buckets", {}).items()},
                       {k: data.get(k) for k in ("version", "built", "n", "source")})
        except (OSError, ValueError, KeyError, TypeError):
            return cls()

    @property
    def calibrated(self) -> bool:
        return bool(self.buckets)

    def p_over(self, center: float, line: float) -> float:
        b = line_bucket(line)
        q = self.buckets.get(b)
        if q is None:
            p = _normal_over(center, line, DEFAULT_SIGMA[b])
        else:
            t = line - center                         # ostatak mora biti veći od ovoga da bi poeni prešli granicu
            p = 1.0 - float(np.searchsorted(q, t, side="right")) / len(q)
        return float(min(max(p, PROB_CLAMP[0]), PROB_CLAMP[1]))


def residual_quantiles(residuals: pd.Series, n_points: int = 101) -> List[float]:
    r = pd.to_numeric(residuals, errors="coerce").dropna().to_numpy()
    return [round(float(x), 3) for x in np.quantile(r, np.linspace(0, 1, n_points))]


def build_calibration(settled: pd.DataFrame, source: str = "") -> dict:
    """JSON kalibracija iz poravnatih analiza: ostatak = stvarni poeni − kalibrisana projekcija, po grupi granice."""
    df = settled.copy()
    for c in ("Actual Points", "Calibrated Projection", "Line"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    df = df.dropna(subset=["Actual Points", "Calibrated Projection", "Line"])
    df["B"] = df["Line"].map(line_bucket)
    out = {}
    for label, _ in LINE_BUCKETS:
        g = df[df["B"] == label]
        if len(g) >= 30:
            res = g["Actual Points"] - g["Calibrated Projection"]
            out[label] = {"n": int(len(g)), "mean": round(float(res.mean()), 3), "std": round(float(res.std()), 3),
                          "q": residual_quantiles(res)}
    return {"version": 1, "built": pd.Timestamp.now().date().isoformat(), "n": int(len(df)), "source": source,
            "buckets": out}


# ---------------------------------------------------------------------------
# Univerzum, izbor i snimanje
# ---------------------------------------------------------------------------

def model_weight_from_env(default: float = 0.0) -> float:
    raw = os.environ.get(ENV_V2_MODEL_WEIGHT, "").strip()
    try:
        w = float(raw) if raw else default
    except ValueError:
        w = default
    return float(min(max(w, 0.0), 1.0))


def _game_key(team: str, opp: str) -> str:
    return "-".join(sorted([str(team), str(opp)]))


def build_universe(mc: pd.DataFrame, quotes: Optional[pd.DataFrame], residual_model: ResidualModel,
                   model_weight: float = 0.0, min_ev: float = MIN_EV, max_ev: float = MAX_EV,
                   max_picks: int = MAX_PICKS, max_per_game: int = MAX_PER_GAME) -> pd.DataFrame:
    """Svi igrači iz v1 Monte Carlo tabele (``mc``, prije filtera) sa v2 kolonama i izborom.

    Izlaz zadržava sve v1 kolone i dodaje: V1 Pick, V2 Fair P(Over)%, V2 Fair Source, V2 Books Same Line,
    V2 Model P(Over)%, V2 P(Over)%, V2 EV Over %, V2 EV Under %, V2 EV %, V2 Note, V2 Pick. Kolona ``Model Pick``
    je v2 izbor (OVER/UNDER/NO VALUE), pa ga poravnanje i ledger čitaju isto kao v1."""
    df = mc.copy().reset_index(drop=True)
    df["V1 Pick"] = df["Model Pick"]
    by_player: Dict[str, pd.DataFrame] = {}
    if quotes is not None and not quotes.empty:
        by_player = {k: g for k, g in quotes.groupby("NAME_KEY")}
    cols: Dict[str, list] = {c: [] for c in ("V2 Fair P(Over)%", "V2 Fair Source", "V2 Books Same Line",
                                             "V2 Model P(Over)%", "V2 P(Over)%", "V2 EV Over %", "V2 EV Under %",
                                             "V2 EV %", "V2 Price Edge %", "V2 Note", "V2 Side", "Over Odds", "Under Odds",
                                             "V2 Over Book", "V2 Under Book")}
    for _, r in df.iterrows():
        line = float(r["Line"])
        center = float(r["Calibrated Projection"])
        p_model = residual_model.p_over(center, line)
        fair = fair_from_quotes(by_player.get(normalize_name(r["Player"])), line)
        over_odds, under_odds = float(r["Over Odds"]), float(r["Under Odds"])
        note = ""
        if fair.best_over is not None:
            over_odds, under_odds = fair.best_over, fair.best_under
        if fair.ok:
            p_fair = float(fair.p_over)
            p = p_fair + model_weight * (p_model - p_fair)
            p = float(min(max(p, PROB_CLAMP[0]), PROB_CLAMP[1]))
        else:
            p_fair, p = np.nan, np.nan
            note = "nema pouzdane fer cijene (potrebna Pinnacle ili tri kladionice sa istom linijom)"
        price_edge = np.nan
        if np.isnan(p):
            ev_o = ev_u = np.nan
            side, ev = "NO VALUE", np.nan
        else:
            ev_o, ev_u = p * over_odds - 1.0, (1.0 - p) * under_odds - 1.0
            side, ev = ("OVER", ev_o) if ev_o >= ev_u else ("UNDER", ev_u)
            # razlika cijene naspram fer cijene za izabranu stranu (nezavisno od težine modela): ovo štiti od zastarjelih linija
            price_edge = (p_fair * over_odds - 1.0) if side == "OVER" else ((1.0 - p_fair) * under_odds - 1.0)
        cols["V2 Fair P(Over)%"].append(round(p_fair * 100, 2) if not np.isnan(p_fair) else np.nan)
        cols["V2 Fair Source"].append(fair.source)
        cols["V2 Books Same Line"].append(fair.n_books)
        cols["V2 Model P(Over)%"].append(round(p_model * 100, 2))
        cols["V2 P(Over)%"].append(round(p * 100, 2) if not np.isnan(p) else np.nan)
        cols["V2 EV Over %"].append(round(ev_o * 100, 2) if not np.isnan(ev_o) else np.nan)
        cols["V2 EV Under %"].append(round(ev_u * 100, 2) if not np.isnan(ev_u) else np.nan)
        cols["V2 EV %"].append(round(ev * 100, 2) if not np.isnan(ev) else np.nan)
        cols["V2 Price Edge %"].append(round(price_edge * 100, 2) if not np.isnan(price_edge) else np.nan)
        cols["V2 Note"].append(note)
        cols["V2 Side"].append(side)
        cols["Over Odds"].append(over_odds)
        cols["Under Odds"].append(under_odds)
        cols["V2 Over Book"].append(fair.best_over_book)
        cols["V2 Under Book"].append(fair.best_under_book)
    for k, v in cols.items():
        df[k] = v
    df["V2 Pick"] = "NO VALUE"
    ev = pd.to_numeric(df["V2 EV %"], errors="coerce") / 100.0
    price_edge = pd.to_numeric(df["V2 Price Edge %"], errors="coerce") / 100.0
    suspect = price_edge > max_ev
    df.loc[suspect, "V2 Note"] = "sumnjivo velika razlika cijene naspram fer cijene (zastarjela linija ili pogrešna kvota) — preskočeno"
    eligible = df["V2 Side"].isin(["OVER", "UNDER"]) & (ev >= min_ev) & ~suspect
    order = df[eligible].assign(_ev=ev[eligible]).sort_values("_ev", ascending=False)
    per_game: Dict[str, int] = {}
    chosen: List[int] = []
    for idx, r in order.iterrows():
        g = _game_key(r.get("TEAM_ABBR", ""), r.get("OPP_TEAM", ""))
        if per_game.get(g, 0) >= max_per_game:
            continue
        per_game[g] = per_game.get(g, 0) + 1
        chosen.append(idx)
        if len(chosen) >= max_picks:
            break
    df.loc[chosen, "V2 Pick"] = df.loc[chosen, "V2 Side"]
    df["V2 Rank"] = np.nan
    for rank, idx in enumerate(chosen, 1):
        df.at[idx, "V2 Rank"] = rank
    df["Model Pick"] = df["V2 Pick"]
    p_side = np.where(df["V2 Pick"] == "OVER", df["V2 P(Over)%"], 100.0 - df["V2 P(Over)%"])
    df["Pick Confidence %"] = np.where(df["V2 Pick"].isin(["OVER", "UNDER"]), np.round(p_side, 2), np.nan)
    df["Best EV %"] = np.where(df["V2 Pick"].isin(["OVER", "UNDER"]), df["V2 EV %"], np.nan)
    return df.sort_values(["V2 Rank", "V2 EV %"], ascending=[True, False], na_position="last").reset_index(drop=True)


@dataclass
class V2Result:
    ok: bool
    message: str
    path: Optional[Path] = None
    universe: pd.DataFrame = field(default_factory=pd.DataFrame)


def run_v2(projections: pd.DataFrame, settings, log: Logger = print, quotes_path=None,
           model_weight: Optional[float] = None, mc_sims: int = 5000, league_pts_std: float = 6.0, seed: int = 42,
           tag: Optional[str] = None, save: bool = True) -> V2Result:
    """v2 nad istim ulazom kao v1 (``AnalysisResult.projections``): računa v1 Monte Carlo za SVE igrače (zbog kolona i
    poređenja), pa v2 izbor. Snima ceo spisak u ``history/v2/``; ništa u v1 se ne mijenja."""
    from .history import DAILY_TAG, save_analysis
    from .pipeline import run_monte_carlo
    if projections is None or projections.empty:
        return V2Result(False, "SKIP: nema projekcija za v2")
    import datetime as _dt
    qpath = Path(quotes_path) if quotes_path else settings.data_dir / f"quotes_{_dt.date.today().isoformat()}.csv"
    quotes = load_quotes(qpath)
    if quotes is None:
        log(f"⚠️ v2: nema fajla kvota po kladionici ({qpath.name}) — nijedan izbor neće imati pouzdanu fer cijenu.")
    mc = run_monte_carlo(projections, mc_sims, league_pts_std, seed=seed)
    rm = ResidualModel.load()
    w = model_weight_from_env() if model_weight is None else model_weight
    uni = build_universe(mc, quotes, rm, model_weight=w)
    n_pick = int(uni["V2 Pick"].isin(["OVER", "UNDER"]).sum())
    n_fair = int(uni["V2 Fair Source"].isin(FAIR_SOURCES_OK).sum())
    path = save_analysis(uni, settings.v2_history_dir, tag=tag if tag is not None else DAILY_TAG) if save else None
    cal = "kalibracija iz podataka" if rm.calibrated else "rezervna sigma (nema kalibracije)"
    msg = (f"v2: {len(uni)} igrača, fer cijena za {n_fair}, izbora {n_pick} (težina modela {w:.2f}, {cal})"
           + (f", snimljeno u {path.name}" if path else ""))
    return V2Result(True, msg, path, uni)
