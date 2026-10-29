"""Zajedničke pomoćne funkcije za pozive NBA Stats API-ja (preko biblioteke ``nba_api``)."""
from __future__ import annotations

import time
from typing import Callable, Optional

import pandas as pd

from ..teams import TEAM_ID_TO_ABBR

Logger = Callable[[str], None]
NBA_SLEEP = 1.2  # pauza između poziva (zaštita od rate-limita)


class NbaApiMissing(RuntimeError):
    pass


def require_nba_api() -> None:
    try:
        import nba_api  # noqa: F401
    except ImportError as e:
        raise NbaApiMissing("Biblioteka nba_api nije instalirana. Pokreni: pip install nba_api") from e


def sleep(seconds: float = NBA_SLEEP) -> None:
    time.sleep(seconds)


def call_with_retry(endpoint_cls, attempts: int = 3, pause: float = 2.0, **kwargs):
    """Pozovi nba_api endpoint uz ponavljanje (NBA Stats zna povremeno odbiti zahtjev)."""
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            return endpoint_cls(**kwargs)
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < attempts - 1:
                time.sleep(pause + attempt * pause)
    raise last  # type: ignore[misc]


def add_team_abbr(df: pd.DataFrame, id_col: str = "TEAM_ID") -> pd.DataFrame:
    """Dodaj kolonu TEAM_ABBR iz numeričkog ID-a tima."""
    if id_col in df.columns:
        df["TEAM_ABBR"] = pd.to_numeric(df[id_col], errors="coerce").map(TEAM_ID_TO_ABBR)
    return df


def log_to(log: Optional[Logger]) -> Logger:
    return log if log is not None else print
