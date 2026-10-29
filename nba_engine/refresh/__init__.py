"""Osvježavanje podataka — svi koraci na jednom mjestu.

Koraci (redoslijed kao u nekadašnjem ``refresh_all.py``):
  offer     – dnevna ponuda sa The Odds API           → offer_latest.csv
  players   – statistika igrača i timova (NBA Stats)  → players_*.csv, teams_*.csv
  injuries  – izvještaj o ozljedama (ESPN)            → injuries_*.csv
  matchups  – DEF/OFF matchup + L10 forma             → def_matchup, off_matchup, form_l10
  schedule  – raspored i back-to-back oznake          → schedule_*.csv, b2b_*.csv
  h2h       – head-to-head (3 sezone, sporo)          → h2h_*.csv
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from ..config import Settings

Logger = Callable[[str], None]

STEP_LABELS: Dict[str, str] = {
    "offer":    "📋 Dnevna ponuda (The Odds API)",
    "players":  "📊 Statistika igrača i timova",
    "injuries": "🏥 Ozljede (ESPN)",
    "matchups": "🎯 DEF/OFF matchup + L10 forma",
    "schedule": "📅 Raspored + back-to-back",
    "h2h":      "🔗 Head-to-head (3 sezone, sporo)",
}
ALL_STEPS: List[str] = list(STEP_LABELS)
DEFAULT_STEPS: List[str] = ["offer", "players", "injuries", "matchups", "schedule"]  # h2h na zahtjev
NBA_STEPS = ("players", "matchups", "schedule", "h2h")


@dataclass
class StepResult:
    name: str
    ok: bool
    message: str
    seconds: float


@dataclass
class RefreshReport:
    results: List[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def failed(self) -> List[StepResult]:
        return [r for r in self.results if not r.ok]

    def summary_lines(self) -> List[str]:
        return [f"{'✅' if r.ok else '❌'} {STEP_LABELS.get(r.name, r.name)} — {r.message} ({r.seconds:.0f}s)"
                for r in self.results]


def _run_step(name: str, settings: Settings, log: Logger) -> str:
    if name == "offer":
        from ..odds_api import fetch_daily_offer
        res = fetch_daily_offer(settings, log=log)
        if not res.ok:
            raise RuntimeError(res.message)
        return res.message
    if name == "players":
        from . import players
        return players.run(settings, log)
    if name == "injuries":
        from . import injuries
        return injuries.run(settings, log)
    if name == "matchups":
        from . import matchups
        return matchups.run(settings, log)
    if name == "schedule":
        from . import schedule
        return schedule.run(settings, log)
    if name == "h2h":
        from . import h2h
        return h2h.run(settings, log)
    raise KeyError(f"Nepoznat korak: {name}")


def run_refresh(settings: Settings, steps: Optional[Sequence[str]] = None,
                skip_h2h: bool = True, log: Optional[Logger] = None) -> RefreshReport:
    """Pokreni odabrane korake redom; greška u jednom koraku ne zaustavlja ostale."""
    log = log or print
    chosen = list(steps) if steps else list(DEFAULT_STEPS if skip_h2h else ALL_STEPS)
    if skip_h2h and steps is None:
        chosen = [s for s in chosen if s != "h2h"]
    unknown = [s for s in chosen if s not in STEP_LABELS]
    if unknown:
        raise KeyError(f"Nepoznati koraci: {unknown}. Dozvoljeni: {ALL_STEPS}")

    report = RefreshReport()
    log(f"🔄 Osvježavanje podataka — sezona {settings.season}, folder {settings.data_dir}")
    for i, name in enumerate(chosen, 1):
        log(f"\n── Korak {i}/{len(chosen)}: {STEP_LABELS[name]}")
        t0 = time.time()
        try:
            msg = _run_step(name, settings, log)
            report.results.append(StepResult(name, True, msg, time.time() - t0))
            log(f"✅ {msg}")
        except Exception as e:  # noqa: BLE001
            report.results.append(StepResult(name, False, str(e), time.time() - t0))
            log(f"❌ {e}")
    log("\n📋 Rezime:")
    for line in report.summary_lines():
        log("  " + line)
    return report
