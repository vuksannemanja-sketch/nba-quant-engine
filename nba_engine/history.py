"""Snimanje rezultata analize i evaluacije u ``history/``."""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import List, Optional

import pandas as pd

_FINGERPRINT_COLS = ("Player", "Line", "Final Projection", "Model Pick", "Best EV %", "True Score")
DAILY_TAG = "daily"   # oznaka analize iz dnevnog posla (zvanična analiza dana za evaluaciju)
_NAME_RE = re.compile(r"^analysis_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})(?:_([A-Za-z0-9-]+))?\.csv$")


def timestamp_now() -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S")


def analysis_fingerprint(df: pd.DataFrame) -> str:
    """Kratki otisak rezultata — isti rezultat se ne snima dva puta u istoj sesiji."""
    cols = [c for c in _FINGERPRINT_COLS if c in df.columns]
    payload = df[cols].round(4).to_csv(index=False) if cols else df.to_csv(index=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def save_analysis(df: pd.DataFrame, history_dir: Path, timestamp: Optional[str] = None,
                  tag: Optional[str] = None) -> Path:
    """Snimi analizu kao ``analysis_<datum>_<vrijeme>[_<oznaka>].csv`` (oznaka ``daily`` = dnevni posao)."""
    history_dir = Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_{tag}" if tag else ""
    path = history_dir / f"analysis_{timestamp or timestamp_now()}{suffix}.csv"
    df.to_csv(path, index=False)
    return path


def analysis_tag(path) -> Optional[str]:
    """Oznaka iz imena fajla analize (npr. 'daily') ili None."""
    m = _NAME_RE.match(Path(path).name)
    return m.group(3) if m else None


def analysis_day(path) -> Optional[str]:
    """Datum (lokalni, iz imena fajla) kao 'YYYY-MM-DD' ili None."""
    m = _NAME_RE.match(Path(path).name)
    return m.group(1) if m else None


def find_same_fingerprint(df: pd.DataFrame, history_dir: Path, day: Optional[str] = None) -> Optional[Path]:
    """Već snimljena analiza istog dana sa istim rezultatom (da se identične kopije ne gomilaju)."""
    day = day or time.strftime("%Y-%m-%d")
    fp = analysis_fingerprint(df)
    for path in reversed(list_history(history_dir)):
        if analysis_day(path) != day:
            continue
        try:
            if analysis_fingerprint(pd.read_csv(path)) == fp:
                return path
        except Exception:  # noqa: BLE001 — oštećen fajl ne smije srušiti snimanje
            continue
    return None


def save_evaluation(df: pd.DataFrame, history_dir: Path, timestamp: Optional[str] = None) -> Path:
    history_dir = Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"evaluation_{timestamp or timestamp_now()}.csv"
    df.to_csv(path, index=False)
    return path


def list_history(history_dir: Path, prefix: str = "analysis_") -> List[Path]:
    history_dir = Path(history_dir)
    if not history_dir.is_dir():
        return []
    return sorted(history_dir.glob(f"{prefix}*.csv"))
