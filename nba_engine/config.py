"""Podešavanja aplikacije: putanje, sezona i API ključevi.

Prioritet izvora podešavanja:
  1. argumenti funkcije / komandne linije
  2. promjenljive okruženja (mogu doći iz ``.env`` fajla u korijenu projekta)
  3. automatsko prepoznavanje (sezona iz postojećih CSV fajlova u ``data/``)
  4. podrazumijevane vrijednosti
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_HISTORY_DIR = PROJECT_ROOT / "history"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

ENV_SEASON = "NBA_SEASON"
ENV_DATA_DIR = "NBA_DATA_DIR"
ENV_HISTORY_DIR = "NBA_HISTORY_DIR"
ENV_ODDS_KEY = "ODDS_API_KEY"
ENV_BOOKMAKERS = "ODDS_BOOKMAKERS"

# Redoslijed kladionica pri izboru linije (prva koja ima ponudu pobjeđuje).
DEFAULT_BOOKMAKER_PRIORITY: Tuple[str, ...] = (
    "pinnacle", "bet365", "fanduel", "draftkings", "betmgm",
    "betrivers", "betonlineag", "bovada",
)

# Imena CSV fajlova po vrsti podatka; ``{season}`` se zamjenjuje sezonom.
# Redoslijed = prioritet (zadržani su i stari srpski nazivi radi kompatibilnosti).
CSV_KINDS: Dict[str, List[str]] = {
    "players_main": ["players_{season}.csv"],
    "players_base": ["players_{season}_base.csv"],
    "players_adv":  ["players_{season}_advanced.csv"],
    "players_misc": ["players_{season}_misc.csv"],
    "teams":        ["teams_{season}.csv", "timovi_{season}.csv"],
    "injuries":     ["injuries_{season}.csv", "injuries.csv",
                     "ozljede_{season}.csv", "ozljede.csv"],
    "h2h":          ["h2h_{season}.csv"],
    "l10":          ["form_l10_{season}.csv"],
    "def_matchup":  ["def_matchup_{season}.csv"],
    "off_matchup":  ["off_matchup_{season}.csv"],
    "b2b":          ["b2b_{season}.csv"],
    "schedule":     ["schedule_{season}.csv"],
}

CSV_LABELS: Dict[str, str] = {
    "players_main": "Igrači (glavni)",
    "players_base": "Igrači (base)",
    "players_adv":  "Igrači (advanced)",
    "players_misc": "Igrači (misc)",
    "teams":        "Timovi",
    "injuries":     "Ozljede",
    "h2h":          "H2H",
    "l10":          "Forma L10",
    "def_matchup":  "DEF matchup",
    "off_matchup":  "OFF matchup",
    "b2b":          "Back-to-back",
    "schedule":     "Raspored",
}

# Fajlovi dnevne ponude, po prioritetu; ``{today}`` = ISO datum.
OFFER_FILES: List[str] = [
    "offer_latest.csv",
    "offer_{today}_upload.csv",
    "offer_{today}.csv",
    "dnevna_ponuda.csv",
]

_SEASON_RE = re.compile(r"^\d{4}-\d{2}$")
_SEASON_IN_NAME_RE = re.compile(r"_(\d{4}-\d{2})")


# ---------------------------------------------------------------------------
# .env
# ---------------------------------------------------------------------------

def parse_env_file(path: Path) -> Dict[str, str]:
    """Pročitaj ``KEY=VALUE`` redove iz fajla (bez spoljnih biblioteka)."""
    values: Dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key:
            values[key] = val
    return values


def load_dotenv(path: Optional[Path] = None, override: bool = False) -> Dict[str, str]:
    """Učitaj ``.env`` u ``os.environ``. Postojeće promjenljive se ne gaze (osim uz override)."""
    env_path = Path(path) if path else DEFAULT_ENV_FILE
    values = parse_env_file(env_path)
    for key, val in values.items():
        if override or key not in os.environ:
            os.environ[key] = val
    return values


# ---------------------------------------------------------------------------
# Sezona
# ---------------------------------------------------------------------------

def season_from_date(today: Optional[_dt.date] = None) -> str:
    """NBA sezona po datumu: od oktobra počinje nova (npr. 2026-10-29 → ``2026-27``)."""
    today = today or _dt.date.today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def previous_season(season: str) -> str:
    start = int(season[:4]) - 1
    return f"{start}-{(start + 1) % 100:02d}"


def seasons_back(season: str, count: int) -> List[str]:
    """Lista sezona unazad, počevši od date (npr. 3 → ['2025-26','2024-25','2023-24'])."""
    out = [season]
    while len(out) < count:
        out.append(previous_season(out[-1]))
    return out


def is_valid_season(season: Optional[str]) -> bool:
    return bool(season) and bool(_SEASON_RE.match(str(season)))


def detect_season_from_data(data_dir: Path) -> Optional[str]:
    """Najnovija sezona za koju postoje ``players_*.csv`` ili ``teams_*.csv`` fajlovi."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        return None
    found = set()
    for pattern in ("players_*.csv", "teams_*.csv"):
        for p in data_dir.glob(pattern):
            m = _SEASON_IN_NAME_RE.search(p.name)
            if m and is_valid_season(m.group(1)):
                found.add(m.group(1))
    return max(found) if found else None


def resolve_season(explicit: Optional[str] = None,
                   data_dir: Optional[Path] = None,
                   today: Optional[_dt.date] = None) -> Tuple[str, str]:
    """Vrati (sezona, izvor). Izvor je 'argument', 'env', 'data' ili 'datum'."""
    if is_valid_season(explicit):
        return str(explicit), "argument"
    env_val = os.environ.get(ENV_SEASON, "").strip()
    if is_valid_season(env_val):
        return env_val, "env"
    if data_dir is not None:
        detected = detect_season_from_data(data_dir)
        if detected:
            return detected, "data"
    return season_from_date(today), "datum"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    season: str
    data_dir: Path
    history_dir: Path
    odds_api_key: str = ""
    bookmaker_priority: Tuple[str, ...] = DEFAULT_BOOKMAKER_PRIORITY
    season_source: str = "default"
    env_file: Optional[Path] = None
    odds_api_base: str = "https://api.the-odds-api.com/v4"
    nba_api_timeout: int = 60

    # -- konstrukcija ---------------------------------------------------------
    @classmethod
    def load(cls, data_dir: Optional[os.PathLike] = None, season: Optional[str] = None,
             env_file: Optional[os.PathLike] = None, history_dir: Optional[os.PathLike] = None,
             today: Optional[_dt.date] = None) -> "Settings":
        env_path = Path(env_file) if env_file else DEFAULT_ENV_FILE
        load_dotenv(env_path)

        ddir = Path(data_dir or os.environ.get(ENV_DATA_DIR) or DEFAULT_DATA_DIR).expanduser()
        hdir = Path(history_dir or os.environ.get(ENV_HISTORY_DIR) or DEFAULT_HISTORY_DIR).expanduser()
        resolved_season, source = resolve_season(season, ddir, today)

        books_env = os.environ.get(ENV_BOOKMAKERS, "").strip()
        books = tuple(b.strip().lower() for b in books_env.split(",") if b.strip()) \
            if books_env else DEFAULT_BOOKMAKER_PRIORITY

        return cls(
            season=resolved_season,
            data_dir=ddir,
            history_dir=hdir,
            odds_api_key=os.environ.get(ENV_ODDS_KEY, "").strip(),
            bookmaker_priority=books,
            season_source=source,
            env_file=env_path if env_path.exists() else None,
        )

    # -- putanje --------------------------------------------------------------
    def csv_candidates(self, kind: str) -> List[Path]:
        if kind not in CSV_KINDS:
            raise KeyError(f"Nepoznata vrsta CSV fajla: {kind}")
        return [self.data_dir / name.format(season=self.season) for name in CSV_KINDS[kind]]

    def csv_path(self, kind: str) -> Optional[Path]:
        """Prvi postojeći fajl za datu vrstu podatka ili None."""
        return next((p for p in self.csv_candidates(kind) if p.exists()), None)

    def primary_csv_path(self, kind: str) -> Path:
        """Putanja na koju se piše (prvi kandidat), postojala ili ne."""
        return self.csv_candidates(kind)[0]

    def all_csv_paths(self) -> Dict[str, Optional[Path]]:
        return {kind: self.csv_path(kind) for kind in CSV_KINDS}

    def offer_candidates(self, today: Optional[_dt.date] = None) -> List[Path]:
        today_iso = (today or _dt.date.today()).isoformat()
        return [self.data_dir / name.format(today=today_iso) for name in OFFER_FILES]

    def find_offer(self, today: Optional[_dt.date] = None) -> Optional[Path]:
        return next((p for p in self.offer_candidates(today) if p.exists()), None)

    def offer_latest_path(self) -> Path:
        return self.data_dir / "offer_latest.csv"

    # -- status ---------------------------------------------------------------
    def data_status(self) -> List[Dict[str, object]]:
        """Pregled fajlova: vrsta, naziv, da li postoji, veličina, starost."""
        rows = []
        now = _dt.datetime.now()
        for kind in CSV_KINDS:
            p = self.csv_path(kind)
            row: Dict[str, object] = {"kind": kind, "label": CSV_LABELS.get(kind, kind),
                                      "path": p, "exists": p is not None}
            if p is not None:
                st = p.stat()
                row["size_kb"] = st.st_size // 1024
                row["modified"] = _dt.datetime.fromtimestamp(st.st_mtime)
                row["age_hours"] = (now - row["modified"]).total_seconds() / 3600.0
            rows.append(row)
        return rows

    def describe(self) -> str:
        key_state = "postavljen" if self.odds_api_key else "NIJE postavljen"
        return (f"sezona={self.season} ({self.season_source}), data={self.data_dir}, "
                f"history={self.history_dir}, ODDS_API_KEY {key_state}")
