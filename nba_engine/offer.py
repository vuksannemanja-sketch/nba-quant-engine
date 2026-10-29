"""Parsiranje dnevne ponude (CSV/TXT) i ručnih unosa iz aplikacije."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

import numpy as np
import pandas as pd

from .teams import normalize_team_abbr
from .utils import extract_injury_status, normalize_name, safe_float, smart_decode


class OfferRow(NamedTuple):
    """Jedan red ponude: igrač, linija, kvote, protivnik (opciono), total meča (opciono)."""
    name: str
    line: float
    over_odds: float
    under_odds: float
    opp_team: Optional[str]
    total_match: Optional[float]


_HEADER_NAME_WORDS = ("player", "ime", "igrac", "igrač")
_HEADER_VALUE_WORDS = ("line", "granica", "linija", "odds", "over", "under")


def _is_header_line(low: str) -> bool:
    return any(kw in low for kw in _HEADER_NAME_WORDS) and any(kw in low for kw in _HEADER_VALUE_WORDS)


def _detect_delimiter(line: str) -> str:
    if "\t" in line and line.count("\t") >= 3:
        return "\t"
    if line.count(";") >= 3:
        return ";"
    return ","


def parse_offer_text(txt: str) -> Tuple[List[OfferRow], List[Tuple[str, str]]]:
    """Parsiraj tekst ponude u redove.

    Podržani formati (kolone):
      4: ime, linija, over, under
      5: ime, linija, over, under, protivnik ILI total
      6: ime, linija, over, under, protivnik, total
      7: ime, tim_igrača, linija, over, under, protivnik, total  (format offer_latest.csv)

    Vraća (validni redovi, loši redovi sa razlogom).
    """
    rows: List[OfferRow] = []
    bad: List[Tuple[str, str]] = []

    for raw in txt.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if _is_header_line(low):
            continue

        parts = [p.strip() for p in line.split(_detect_delimiter(line))]
        name = line_val = over_odds = under_odds = None
        opp_team = None
        total_match = None

        if len(parts) == 4:
            name, line_val, over_odds, under_odds = parts
        elif len(parts) == 5:
            name, line_val, over_odds, under_odds, extra = parts
            n = safe_float(extra)
            if n is None:
                opp_team = normalize_team_abbr(extra)
            else:
                total_match = n
        elif len(parts) == 6:
            name, line_val, over_odds, under_odds = parts[:4]
            opp_team = normalize_team_abbr(parts[4])
            total_match = safe_float(parts[5])
        elif len(parts) == 7:
            # parts[1] = tim igrača; tim se uzima iz baze igrača, pa se ovdje ignoriše
            name = parts[0]
            line_val, over_odds, under_odds = parts[2], parts[3], parts[4]
            opp_team = normalize_team_abbr(parts[5])
            total_match = safe_float(parts[6])
        else:
            bad.append((raw, f"Wrong number of columns ({len(parts)})"))
            continue

        name = str(name).strip() if name else ""
        line_f, over_f, under_f = safe_float(line_val), safe_float(over_odds), safe_float(under_odds)
        if not name:
            bad.append((raw, "Empty player name"))
            continue
        if any(v is None for v in (line_f, over_f, under_f)):
            bad.append((raw, "Cannot parse numeric fields"))
            continue

        rows.append(OfferRow(
            name, float(line_f), float(over_f), float(under_f),
            opp_team if pd.notna(opp_team) else None,
            total_match,
        ))
    return rows, bad


def read_offer_file(path: os.PathLike) -> str:
    """Pročitaj fajl ponude kao tekst (automatski prepoznaje kodiranje)."""
    with open(path, "rb") as f:
        return smart_decode(f.read())


def offer_rows_to_frame(rows: List[OfferRow]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["name", "line", "over", "under", "opp_team", "total"])


# ---------------------------------------------------------------------------
# Ručni unosi iz bočne trake
# ---------------------------------------------------------------------------

def parse_recent_form_input(txt: str) -> Dict[str, float]:
    """'Ime, L5 prosjek' po redu → {ključ_imena: poeni}."""
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
    """'Ime, STATUS' po redu → tabela ozljeda (PLAYER, NAME_KEY, TEAM_ABBR, STATUS, DESCRIPTION)."""
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
        name_key = normalize_name(name_raw)
        pr = players_df[players_df["NAME_KEY"] == name_key] if "NAME_KEY" in players_df.columns else pd.DataFrame()
        team_abbr = str(pr["TEAM_ABBR"].iloc[0]) if not pr.empty and "TEAM_ABBR" in pr.columns else np.nan
        rows.append({"PLAYER": name_raw, "NAME_KEY": name_key, "TEAM_ABBR": team_abbr,
                     "STATUS": status, "DESCRIPTION": status_raw})
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def parse_team_list(txt: str) -> Set[str]:
    """'DET, MEM, LAL' → {'DET','MEM','LAL'} (kratice velikim slovima)."""
    out: Set[str] = set()
    if not txt or not txt.strip():
        return out
    for t in txt.split(","):
        t = t.strip().upper()
        if t:
            out.add(t)
    return out


def parse_rest_days(txt: str) -> Dict[str, int]:
    """'OKC=3, MIN=2' → {'OKC': 3, 'MIN': 2}; neispravni dijelovi se preskaču."""
    out: Dict[str, int] = {}
    if not txt or not txt.strip():
        return out
    for part in txt.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        try:
            abbr, days = part.split("=", 1)
            out[abbr.strip().upper()] = int(days.strip())
        except Exception:
            pass
    return out
