"""Snimanje rezultata analize i evaluacije u ``history/``."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import List, Optional

import pandas as pd

_FINGERPRINT_COLS = ("Player", "Line", "Final Projection", "Model Pick", "Best EV %", "True Score")


def timestamp_now() -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S")


def analysis_fingerprint(df: pd.DataFrame) -> str:
    """Kratki otisak rezultata — isti rezultat se ne snima dva puta u istoj sesiji."""
    cols = [c for c in _FINGERPRINT_COLS if c in df.columns]
    payload = df[cols].round(4).to_csv(index=False) if cols else df.to_csv(index=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def save_analysis(df: pd.DataFrame, history_dir: Path, timestamp: Optional[str] = None) -> Path:
    history_dir = Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"analysis_{timestamp or timestamp_now()}.csv"
    df.to_csv(path, index=False)
    return path


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
