"""Rana sezona: dopuna statistike ove sezone prošlom sezonom, srazmjerno broju odigranih utakmica.

Na početku sezone igrač ima 1–5 utakmica i svi prosjeci su nepouzdani. Ovdje se svaka statistika
koju model koristi računa kao ponderisani prosjek ove i prošle sezone:

    težina ove sezone  = min(1, GP / FULL_WEIGHT_GP)          (sa 20 utakmica prošla sezona nestaje)
    snaga prošle       = min(1, GP_prošla / PRIOR_MIN_GP)      (prošla sezona sa <10 utakmica vrijedi manje)
    težina prošle      = (1 − težina ove) × snaga prošle

Igrač bez prošle sezone (rookie, povratnik) ostaje netaknut. Isto pravilo važi za timske ratinge.
Izvedene kolone po minuti (PPM, FGA_PM...) se računaju ponovo iz dopunjenih vrijednosti.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

import numpy as np
import pandas as pd

FULL_WEIGHT_GP = 20
PRIOR_MIN_GP = 10

PLAYER_BLEND_COLS: Tuple[str, ...] = (
    "PTS", "MIN", "FGA", "FGM", "FTA", "FG3A", "FG_PCT", "FT_PCT", "FG3_PCT",
    "USG_PCT", "TS_PCT", "EFG_PCT", "TOV_PCT", "TM_TOV_PCT", "PIE", "AST_RATIO", "AST_TO", "AST_PCT",
    "NET_RATING", "PLUS_MINUS", "PTS_PAINT", "PTS_FB", "PTS_2ND_CHANCE", "PTS_OFF_TOV",
    "OPP_PTS_PAINT", "OPP_PTS_FB", "OPP_PTS_2ND_CHANCE", "OPP_PTS_OFF_TOV", "PFD", "POSS",
)
TEAM_BLEND_COLS: Tuple[str, ...] = ("OFF_RATING", "DEF_RATING", "NET_RATING", "PACE", "PTS", "OPP_PTS")
PER_MINUTE_DERIVED: Dict[str, str] = {"PPM": "PTS", "FGA_PM": "FGA", "FTA_PM": "FTA",
                                      "FG3A_PM": "FG3A", "PFD_PM": "PFD", "POSS_PM": "POSS"}


def current_weight(gp_now: float, gp_prior: float,
                   full_gp: int = FULL_WEIGHT_GP, prior_min_gp: int = PRIOR_MIN_GP) -> float:
    """Težina OVE sezone (1.0 = prošla sezona se ne koristi)."""
    gp_now = float(gp_now) if gp_now is not None and np.isfinite(gp_now) else 0.0
    gp_prior = float(gp_prior) if gp_prior is not None and np.isfinite(gp_prior) else 0.0
    w_cur = min(1.0, max(0.0, gp_now) / float(full_gp))
    prior_strength = min(1.0, max(0.0, gp_prior) / float(prior_min_gp))
    return float(1.0 - (1.0 - w_cur) * prior_strength)


def _blend_frame(current: pd.DataFrame, prior: pd.DataFrame, key: str, cols: Iterable[str],
                 gp_col: str = "GP") -> Tuple[pd.DataFrame, Dict]:
    out = current.copy()
    out["PRIOR_WEIGHT"] = 0.0
    out["GP_PRIOR"] = np.nan
    info = {"rows": int(len(out)), "blended": 0, "mean_prior_weight": 0.0}
    if prior is None or prior.empty or key not in out.columns or key not in prior.columns or gp_col not in out.columns:
        return out, info
    pr = prior.copy()
    if gp_col in pr.columns:
        pr = pr.sort_values(gp_col, ascending=False)
    pr = pr.drop_duplicates(key).set_index(key)
    gp_prior_s = pd.to_numeric(pr[gp_col], errors="coerce") if gp_col in pr.columns else pd.Series(82.0, index=pr.index)
    gp_now = pd.to_numeric(out[gp_col], errors="coerce").fillna(0.0)
    keys = out[key]
    has_prior = keys.isin(pr.index)
    w_cur = pd.Series(1.0, index=out.index)
    for i in out.index[has_prior]:
        w_cur.at[i] = current_weight(gp_now.at[i], gp_prior_s.get(keys.at[i], 0.0))
    w_prior = 1.0 - w_cur
    use = w_prior > 0
    if not bool(use.any()):
        return out, info
    for col in cols:
        if col not in out.columns or col not in pr.columns:
            continue
        cur = pd.to_numeric(out[col], errors="coerce")
        prev = pd.to_numeric(keys.map(pr[col]), errors="coerce")
        blended = cur * w_cur + prev * w_prior
        blended = blended.where(cur.notna() | prev.isna(), prev)       # nema ove sezone → prošla
        blended = blended.where(prev.notna() | cur.isna(), cur)        # nema prošle → ova
        out[col] = blended.where(use, cur)
    out.loc[use, "PRIOR_WEIGHT"] = w_prior[use].round(4)
    out.loc[has_prior, "GP_PRIOR"] = keys[has_prior].map(gp_prior_s).to_numpy()
    info.update({"blended": int(use.sum()), "mean_prior_weight": round(float(w_prior[use].mean()), 3)})
    return out, info


def blend_players(current: pd.DataFrame, prior: Optional[pd.DataFrame], key: str = "NAME_KEY") -> Tuple[pd.DataFrame, Dict]:
    """Dopuni statistiku igrača prošlom sezonom i ponovo izračunaj kolone po minuti."""
    out, info = _blend_frame(current, prior, key, PLAYER_BLEND_COLS)
    if info["blended"] and "MIN" in out.columns:
        mask = out["PRIOR_WEIGHT"] > 0
        min_safe = pd.to_numeric(out["MIN"], errors="coerce").replace(0, np.nan)
        for derived, base in PER_MINUTE_DERIVED.items():
            if base in out.columns:
                fresh = (pd.to_numeric(out[base], errors="coerce") / min_safe).replace([np.inf, -np.inf], np.nan)
                if derived == "PPM":
                    fresh = fresh.fillna(0.55).clip(0.20, 1.25)
                if derived in out.columns:
                    out[derived] = pd.to_numeric(out[derived], errors="coerce").where(~mask, fresh)
                else:
                    out[derived] = fresh.where(mask)
    return out, info


def blend_teams(current: pd.DataFrame, prior: Optional[pd.DataFrame], key: str = "TEAM_ABBR") -> Tuple[pd.DataFrame, Dict]:
    """Dopuni timske ratinge i tempo prošlom sezonom (isto pravilo po broju utakmica tima)."""
    out, info = _blend_frame(current, prior, key, TEAM_BLEND_COLS)
    if info["blended"] and {"OFF_RATING", "DEF_RATING"} <= set(out.columns):
        out["NET_RATING"] = pd.to_numeric(out["OFF_RATING"], errors="coerce") - pd.to_numeric(out["DEF_RATING"], errors="coerce")
    return out, info
