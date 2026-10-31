"""Dnevni posao (``python -m nba_engine daily``): sve što treba uraditi jednom dnevno, redom.

Faze (greška u jednoj ne zaustavlja ostale):
  refresh   osvježi CSV podatke sa NBA Stats i ESPN (igrači/timovi, ozljede, matchup+forma, raspored)
  settle    poravnaj ranije snimljene analize sa stvarnim poenima (automatska evaluacija)
  offer     povuci današnju ponudu sa The Odds API (preskače se ako ODDS_API_KEY nije postavljen)
  analyze   analiziraj ponudu i snimi rezultat u history/ (samo ako je ponuda za današnje mečeve)
  push      (opcija ``--push``) commit-uj izmijenjene CSV podatke i pošalji ih na GitHub (grana main)

Svaki run piše log u ``logs/daily_<datum>_<vrijeme>.log`` i rezime u ``logs/daily_last_report.json``,
pa se u aplikaciji vidi kad je posao zadnji put radio i da li je sve prošlo.
"""
from __future__ import annotations

import datetime as _dt
import json
import subprocess
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .config import PROJECT_ROOT, Settings

Logger = Callable[[str], None]

DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
LAST_REPORT_NAME = "daily_last_report.json"
KEEP_LOGS = 60  # koliko zadnjih log fajlova čuvati

STAGES: List[str] = ["refresh", "settle", "offer", "analyze", "push"]
STAGE_LABELS: Dict[str, str] = {
    "refresh": "🔄 Osvježavanje podataka",
    "settle":  "📒 Poravnanje analiza (evaluacija)",
    "offer":   "📋 Današnja ponuda (The Odds API)",
    "analyze": "🧮 Analiza i snimanje u history/",
    "push":    "☁️ Slanje podataka na GitHub",
}
# fajlovi koje git faza smije da commit-uje (sve ostalo zaustavlja slanje)
DATA_PATHSPEC = "data/*.csv"
MAX_OFFER_AGE_HOURS = 20  # dnevni posao analizira samo ponudu povučenu istog dana


def offer_age_hours(path: Path, now: Optional[_dt.datetime] = None) -> float:
    mtime = _dt.datetime.fromtimestamp(Path(path).stat().st_mtime)
    return ((now or _dt.datetime.now()) - mtime).total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# izvještaj i log
# ---------------------------------------------------------------------------

@dataclass
class StageResult:
    name: str
    status: str  # "ok" | "skipped" | "failed"
    message: str
    seconds: float = 0.0

    @property
    def icon(self) -> str:
        return {"ok": "✅", "skipped": "⏭️", "failed": "❌"}.get(self.status, "❔")


@dataclass
class DailyReport:
    started: str
    stages: List[StageResult] = field(default_factory=list)
    log_path: Optional[str] = None
    finished: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not any(s.status == "failed" for s in self.stages)

    @property
    def failed(self) -> List[StageResult]:
        return [s for s in self.stages if s.status == "failed"]

    def summary_lines(self) -> List[str]:
        return [f"{s.icon} {STAGE_LABELS.get(s.name, s.name)} — {s.message} ({s.seconds:.0f}s)" for s in self.stages]

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d


class RunLog:
    """Piše u log fajl i prosljeđuje poruke dalje (ekran / Streamlit)."""

    def __init__(self, path: Optional[Path], forward: Optional[Logger] = None):
        self.path = path
        self.forward = forward
        self._fh = open(path, "a", encoding="utf-8") if path else None

    def __call__(self, msg: str) -> None:
        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        if self._fh:
            self._fh.write(f"[{stamp}] {msg}\n")
            self._fh.flush()
        if self.forward:
            self.forward(msg)

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


def load_last_report(log_dir: Optional[Path] = None) -> Optional[Dict]:
    path = Path(log_dir or DEFAULT_LOG_DIR) / LAST_REPORT_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def prune_logs(log_dir: Path, keep: int = KEEP_LOGS) -> int:
    logs = sorted(Path(log_dir).glob("daily_*.log"))
    removed = 0
    for p in logs[:-keep] if keep > 0 else logs:
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------------------
# faze
# ---------------------------------------------------------------------------

def stage_refresh(settings: Settings, log: Logger, with_h2h: bool = False) -> str:
    from .refresh import run_refresh
    steps = ["players", "injuries", "matchups", "schedule"] + (["h2h"] if with_h2h else [])
    report = run_refresh(settings, steps=steps, log=log)
    if not report.ok:
        failed = ", ".join(f"{r.name}: {r.message}" for r in report.failed)
        raise RuntimeError(f"nisu uspjeli koraci — {failed}")
    return f"osvježeno {len(report.results)} koraka ({', '.join(r.name for r in report.results)})"


def stage_settle(settings: Settings, log: Logger) -> str:
    from .settle import settle_history
    events = settle_history(settings.history_dir, log=log, closing_dir=settings.data_dir)
    n = {k: sum(1 for e in events if e["status"] == k) for k in ("settled", "pending", "no_data", "error")}
    errors = [e for e in events if e["status"] == "error"]
    if errors and n["settled"] == 0 and len(errors) == len(events):
        raise RuntimeError("; ".join(str(e.get("detail", "")) for e in errors[:3]))
    return (f"poravnato {n['settled']}, čeka mečeve {n['pending']}, bez game log-a {n['no_data']}, "
            f"greške {n['error']}")


def stage_offer(settings: Settings, log: Logger) -> str:
    from .odds_api import fetch_daily_offer
    if not settings.odds_api_key:
        return "SKIP: ODDS_API_KEY nije postavljen u .env — ponuda se ne povlači"
    res = fetch_daily_offer(settings, log=log)
    if not res.ok:
        raise RuntimeError(res.message)
    return res.message


def stage_analyze(settings: Settings, log: Logger, top: int = 10) -> str:
    from .history import save_analysis
    from .loaders import load_bundle
    from .offer import read_offer_file
    from .pipeline import AnalysisOptions, format_auto_context, run_analysis, summary_table
    from .schedule import fetch_schedule_context

    offer_path = settings.find_offer()
    if offer_path is None:
        return "SKIP: nema fajla ponude (data/offer_latest.csv)"
    age_h = offer_age_hours(offer_path)
    if age_h > MAX_OFFER_AGE_HOURS:
        return (f"SKIP: ponuda {offer_path.name} je stara {age_h:.0f} h (nije povučena danas) — "
                f"analiza bi bila besmislena, istorija se ne snima")
    bundle = load_bundle(settings)
    for note in bundle.notes:
        log(f"ℹ️  {note}")
    schedule_ctx = fetch_schedule_context()
    options = AnalysisOptions(game_statuses=schedule_ctx.statuses if schedule_ctx else {}, schedule=schedule_ctx)
    result = run_analysis(read_offer_file(offer_path), bundle, options)
    log(f"Ponuda {offer_path.name}: redova {len(result.offer_rows)}, nije nađeno {len(result.not_found)}, "
        f"preskočeno (meč u toku/završen) {len(result.skipped_active)}, isključeno OUT {len(result.excluded_out)}")
    if result.auto_context:
        log("🏠 " + format_auto_context(result.auto_context))
    if result.offer_is_today is False:
        return (f"SKIP: ponuda nije za današnje mečeve (0 od {result.offer_matched_rows} parova u ESPN rasporedu) "
                f"— istorija nije snimljena")
    if not result.ok:
        raise RuntimeError(result.message)
    log("\n" + summary_table(result.df, top).to_string(index=False) + "\n")
    path = save_analysis(result.df, settings.history_dir)
    fresh = "" if result.offer_is_today else " (ESPN raspored nedostupan — svježina ponude nije provjerena)"
    return f"{len(result.df)} pickova snimljeno u {path.name}{fresh}"


# ---------------------------------------------------------------------------
# git: slanje podataka na GitHub
# ---------------------------------------------------------------------------

def _git(repo: Path, args: Sequence[str], run=subprocess.run) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def changed_tracked_paths(status_output: str) -> List[str]:
    """Putanje iz ``git status --porcelain`` (bez netrackovanih fajlova)."""
    paths = []
    for line in status_output.splitlines():
        if len(line) < 4 or line.startswith("??"):
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip('"'))
    return paths


def is_data_csv(path: str) -> bool:
    return path.startswith("data/") and path.endswith(".csv") and path.count("/") == 1


def push_data_to_git(repo: Path, log: Logger, run=subprocess.run, today: Optional[_dt.date] = None,
                     branch: str = "main", remote: str = "origin") -> str:
    """Commit-uj izmijenjene ``data/*.csv`` fajlove i pošalji ih na GitHub.

    Zaštite: radi samo na grani ``main``; odbija ako su u radnom folderu izmijenjeni i drugi fajlovi
    (kod); pri sukobu sa GitHub-om zadržava lokalne podatke (noviji su); ako pull/push ne uspije,
    commit ostaje lokalno i pokušava se sutra.
    """
    cur = _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"], run)
    if cur.returncode != 0:
        raise RuntimeError(f"git nije dostupan: {cur.stderr.strip() or cur.stdout.strip()}")
    current = cur.stdout.strip()
    if current != branch:
        return f"SKIP: grana je '{current}', a slanje radi samo sa grane '{branch}'"

    status = _git(repo, ["status", "--porcelain", "--untracked-files=no"], run)
    others = [p for p in changed_tracked_paths(status.stdout) if not is_data_csv(p)]
    if others:
        return ("SKIP: osim podataka izmijenjeni su i drugi fajlovi (" + ", ".join(others[:5])
                + ("..." if len(others) > 5 else "") + ") — commit-uj ih ručno pa će slanje raditi")

    _git(repo, ["add", "--", DATA_PATHSPEC], run)
    staged = _git(repo, ["diff", "--cached", "--quiet"], run)
    committed = False
    if staged.returncode == 1:
        day = (today or _dt.date.today()).isoformat()
        res = _git(repo, ["commit", "-q", "-m", f"data: daily refresh {day}"], run)
        if res.returncode != 0:
            raise RuntimeError(f"commit nije uspio: {res.stderr.strip() or res.stdout.strip()}")
        committed = True
        log(f"git: commit 'data: daily refresh {day}'")
    elif staged.returncode not in (0, 1):
        raise RuntimeError(f"git diff nije uspio: {staged.stderr.strip()}")

    ahead = _git(repo, ["rev-list", "--count", f"{remote}/{branch}..HEAD"], run)
    pending = int(ahead.stdout.strip() or 0) if ahead.returncode == 0 else (1 if committed else 0)
    if not committed and pending == 0:
        return "nema novih izmjena podataka za slanje"

    pull = _git(repo, ["pull", "--rebase", "--strategy-option=theirs", "-q", remote, branch], run)
    if pull.returncode != 0:
        _git(repo, ["rebase", "--abort"], run)
        raise RuntimeError(f"pull/rebase nije uspio (commit ostaje lokalno): {pull.stderr.strip()[:300]}")
    push = _git(repo, ["push", "-q", remote, branch], run)
    if push.returncode != 0:
        raise RuntimeError(f"push nije uspio (commit ostaje lokalno): {push.stderr.strip()[:300]}")
    return f"poslato na GitHub ({pending} commit{'a' if pending != 1 else ''}, grana {branch})"


def stage_push(settings: Settings, log: Logger, repo: Optional[Path] = None, run=subprocess.run) -> str:
    return push_data_to_git(repo or PROJECT_ROOT, log, run=run)


# ---------------------------------------------------------------------------
# orkestracija
# ---------------------------------------------------------------------------

DEFAULT_RUNNERS: Dict[str, Callable[[Settings, Logger], str]] = {
    "refresh": stage_refresh,
    "settle": stage_settle,
    "offer": stage_offer,
    "analyze": stage_analyze,
    "push": stage_push,
}


def run_daily(settings: Settings, log: Optional[Logger] = None, stages: Optional[Sequence[str]] = None,
              push: bool = False, with_h2h: bool = False, log_dir: Optional[Path] = None,
              runners: Optional[Dict[str, Callable]] = None, write_logs: bool = True) -> DailyReport:
    """Pokreni faze redom. ``stages`` bira faze (podrazumijevano sve osim push; push uz ``push=True``)."""
    chosen = list(stages) if stages else [s for s in STAGES if s != "push"]
    if push and "push" not in chosen:
        chosen.append("push")
    unknown = [s for s in chosen if s not in STAGE_LABELS]
    if unknown:
        raise KeyError(f"Nepoznate faze: {unknown}. Dozvoljene: {STAGES}")
    runners = {**DEFAULT_RUNNERS, **(runners or {})}

    started = _dt.datetime.now()
    ldir = Path(log_dir or DEFAULT_LOG_DIR)
    log_path: Optional[Path] = None
    if write_logs:
        ldir.mkdir(parents=True, exist_ok=True)
        log_path = ldir / f"daily_{started.strftime('%Y-%m-%d_%H%M%S')}.log"
        n = 2
        while log_path.exists():  # dva pokretanja u istoj sekundi ne dijele log
            log_path = ldir / f"daily_{started.strftime('%Y-%m-%d_%H%M%S')}_{n}.log"
            n += 1
    rlog = RunLog(log_path, forward=log)
    report = DailyReport(started=started.isoformat(timespec="seconds"), log_path=str(log_path) if log_path else None)

    rlog(f"🗓️  Dnevni posao {started.strftime('%d.%m.%Y %H:%M')} — sezona {settings.season}, podaci {settings.data_dir}")
    rlog(f"Faze: {', '.join(chosen)}")
    for i, name in enumerate(chosen, 1):
        rlog(f"\n══ Faza {i}/{len(chosen)}: {STAGE_LABELS[name]}")
        t0 = time.time()
        try:
            fn = runners[name]
            msg = fn(settings, rlog, with_h2h=with_h2h) if name == "refresh" else fn(settings, rlog)
            status = "skipped" if str(msg).startswith("SKIP") else "ok"
            msg = str(msg)[6:].strip() if status == "skipped" else str(msg)
            report.stages.append(StageResult(name, status, msg, time.time() - t0))
            rlog(f"{'⏭️ ' if status == 'skipped' else '✅'} {msg}")
        except Exception as e:  # noqa: BLE001 — jedna faza ne smije srušiti ostale
            report.stages.append(StageResult(name, "failed", str(e) or e.__class__.__name__, time.time() - t0))
            rlog(f"❌ {e}")
            rlog(traceback.format_exc().rstrip())

    report.finished = _dt.datetime.now().isoformat(timespec="seconds")
    rlog("\n📋 Rezime dnevnog posla:")
    for line in report.summary_lines():
        rlog("  " + line)
    rlog("✅ Sve faze prošle." if report.ok else f"⚠️  Neuspjelih faza: {len(report.failed)}")
    rlog.close()
    if write_logs:
        (ldir / LAST_REPORT_NAME).write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                                             encoding="utf-8")
        prune_logs(ldir)
    return report
