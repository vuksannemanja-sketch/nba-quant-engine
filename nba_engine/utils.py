"""Opšte pomoćne funkcije: imena igrača, brojevi, kodiranje teksta, status ozljeda."""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Optional

import numpy as np
import pandas as pd


def normalize_name(s: Any) -> str:
    """Ključ imena igrača: mala slova, bez dijakritika, bez Jr/Sr/II/III, bez interpunkcije."""
    if s is None:
        return ""
    s = str(s).strip().strip('"').strip("'").replace("\xa0", " ")
    # Popravka pogrešno dekodiranog UTF-8 teksta (npr. "JokiÄ‡" → "Jokić")
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
    """Pretvori u float; zarez prihvata kao decimalni znak; None/prazno/NaN → None."""
    if x is None:
        return None
    try:
        s = str(x).strip().replace('"', "").replace(",", ".")
        if not s or s.upper() == "NAN":
            return None
        v = float(s)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def smart_decode(b: bytes) -> str:
    """Dekodiraj bajtove isprobavajući uobičajena kodiranja (UTF-8, UTF-16, cp1252...)."""
    for enc in ("utf-8", "utf-8-sig", "utf-16", "utf-16le", "utf-16be", "cp1252", "latin-1"):
        try:
            s = b.decode(enc)
            if s and s.strip():
                return s
        except Exception:
            pass
    return b.decode("utf-8", errors="ignore")


def get_float(obj: Any, col: str, default: Optional[float] = None) -> Optional[float]:
    """Sigurno pročitaj numeričku vrijednost iz reda (Series/dict); NaN/inf → default."""
    try:
        v = obj.get(col, default) if hasattr(obj, "get") else default
        if pd.isna(v):
            return default
        v = float(v)
        return v if np.isfinite(v) else default
    except Exception:
        return default


def clamp(x: Any, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except Exception:
        return (lo + hi) / 2.0


def zscore(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    return (s - s.mean()) / (s.std() + 1e-6)


def extract_injury_status(desc: str) -> str:
    """Iz opisa ozljede izvuci status: OUT / QUESTIONABLE / DOUBTFUL / INACTIVE / PROBABLE / UNKNOWN."""
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


def status_weight(s: str) -> float:
    """Težina statusa ozljede za računanje izgubljenih minuta/usage-a saigrača."""
    s = (s or "").strip().upper()
    return {"OUT": 1.0, "INACTIVE": 1.0, "DOUBTFUL": 0.75, "QUESTIONABLE": 0.40, "PROBABLE": 0.15}.get(s, 0.0)


def fix_usg_scale(df: pd.DataFrame) -> pd.DataFrame:
    """USG_PCT u procentima (0–100); ako je u decimalnom obliku (0–1), pomnoži sa 100."""
    if "USG_PCT" not in df.columns:
        return df
    mean_usg = pd.to_numeric(df["USG_PCT"], errors="coerce").dropna().mean()
    if pd.notna(mean_usg) and mean_usg < 2.0:
        df = df.copy()
        df["USG_PCT"] = pd.to_numeric(df["USG_PCT"], errors="coerce") * 100.0
    return df
