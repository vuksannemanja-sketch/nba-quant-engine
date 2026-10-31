"""Dnevni raspored na ovom računaru (macOS launchd): ``python -m nba_engine schedule``.

launchd je ugrađeni macOS servis koji pokreće posao svaki dan u zadato vrijeme. Ako je računar
u to vrijeme spavao, posao kreće odmah po buđenju; ako je bio ugašen, taj dan se preskače.
Podešavanje se čuva u ``~/Library/LaunchAgents/com.nba-engine.daily.plist``.

Na Linuxu se isto postiže cron linijom (vidi ``cron_line``).
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .config import PROJECT_ROOT

LABEL = "com.nba-engine.daily"
DEFAULT_HOUR = 18
DEFAULT_MINUTE = 0
LAUNCHD_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
Logger = Callable[[str], None]


def launch_agents_dir(home: Optional[Path] = None) -> Path:
    return Path(home or Path.home()) / "Library" / "LaunchAgents"


def plist_path(home: Optional[Path] = None) -> Path:
    return launch_agents_dir(home) / f"{LABEL}.plist"


def domain(uid: Optional[int] = None) -> str:
    return f"gui/{os.getuid() if uid is None else uid}"


def daily_args(push: bool = True, with_h2h: bool = False) -> List[str]:
    args = ["daily"]
    if push:
        args.append("--push")
    if with_h2h:
        args.append("--with-h2h")
    return args


def render_plist(python_exe: Path, project_root: Path, hour: int = DEFAULT_HOUR, minute: int = DEFAULT_MINUTE,
                 log_dir: Optional[Path] = None, extra_args: Sequence[str] = ("daily", "--push")) -> bytes:
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("sat mora biti 0–23, minut 0–59")
    log_dir = Path(log_dir or Path(project_root) / "logs")
    data = {
        "Label": LABEL,
        "ProgramArguments": [str(python_exe), "-m", "nba_engine", *extra_args],
        "WorkingDirectory": str(project_root),
        "StartCalendarInterval": {"Hour": int(hour), "Minute": int(minute)},
        "StandardOutPath": str(log_dir / "launchd.out.log"),
        "StandardErrorPath": str(log_dir / "launchd.err.log"),
        "EnvironmentVariables": {"PATH": LAUNCHD_PATH, "LANG": "en_US.UTF-8", "PYTHONUNBUFFERED": "1"},
        "RunAtLoad": False,
    }
    return plistlib.dumps(data, sort_keys=False)


def cron_line(python_exe: Path, project_root: Path, hour: int = DEFAULT_HOUR, minute: int = DEFAULT_MINUTE,
              extra_args: Sequence[str] = ("daily", "--push")) -> str:
    """Ista stvar za Linux (crontab -e)."""
    return (f"{minute} {hour} * * * cd {project_root} && {python_exe} -m nba_engine {' '.join(extra_args)} "
            f">> {project_root}/logs/cron.log 2>&1")


def _launchctl(args: Sequence[str], run=subprocess.run) -> subprocess.CompletedProcess:
    return run(["launchctl", *args], capture_output=True, text=True)


def install(hour: int = DEFAULT_HOUR, minute: int = DEFAULT_MINUTE, push: bool = True, with_h2h: bool = False,
            python_exe: Optional[Path] = None, project_root: Optional[Path] = None, home: Optional[Path] = None,
            run=subprocess.run, log: Logger = print, platform: Optional[str] = None) -> Path:
    """Upiši plist i registruj posao kod launchd-a (zamjenjuje postojeći)."""
    platform = platform or sys.platform
    if platform != "darwin":
        raise RuntimeError("launchd postoji samo na macOS-u; na Linuxu dodaj u crontab:\n  "
                           + cron_line(Path(python_exe or sys.executable), Path(project_root or PROJECT_ROOT),
                                       hour, minute, daily_args(push, with_h2h)))
    # NE koristiti .resolve() na python putanji: .venv/bin/python je simbolički link i resolve bi
    # vratio sistemski Python bez instaliranih biblioteka
    python_exe = Path(python_exe or sys.executable)
    project_root = Path(project_root or PROJECT_ROOT).resolve()
    (project_root / "logs").mkdir(parents=True, exist_ok=True)
    path = plist_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_plist(python_exe, project_root, hour, minute, project_root / "logs",
                                  daily_args(push, with_h2h)))
    log(f"📝 Upisano: {path}")
    _launchctl(["bootout", f"{domain()}/{LABEL}"], run)  # ako je već registrovan; greška je u redu
    res = _launchctl(["bootstrap", domain(), str(path)], run)
    if res.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap nije uspio: {res.stderr.strip() or res.stdout.strip()}")
    _launchctl(["enable", f"{domain()}/{LABEL}"], run)
    log(f"✅ Dnevni posao registrovan: svaki dan u {hour:02d}:{minute:02d} → "
        f"{python_exe} -m nba_engine {' '.join(daily_args(push, with_h2h))}")
    return path


def remove(home: Optional[Path] = None, run=subprocess.run, log: Logger = print) -> bool:
    """Odjavi posao kod launchd-a i obriši plist. Vraća True ako je nešto postojalo."""
    path = plist_path(home)
    existed = path.exists()
    _launchctl(["bootout", f"{domain()}/{LABEL}"], run)
    if existed:
        path.unlink()
        log(f"🗑️  Obrisano: {path}")
    log("✅ Dnevni posao više nije registrovan." if existed else "ℹ️  Dnevni posao nije ni bio registrovan.")
    return existed


def parse_launchctl_print(text: str) -> Dict[str, str]:
    """Izvuci state / last exit code / runs iz ``launchctl print`` izlaza."""
    info: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        for key in ("state", "last exit code", "runs", "pid", "program"):
            if line.startswith(key + " =") or line.startswith(key + " = "):
                info[key] = line.split("=", 1)[1].strip()
    return info


def status(home: Optional[Path] = None, run=subprocess.run) -> Dict[str, object]:
    path = plist_path(home)
    out: Dict[str, object] = {"plist": str(path), "installed": path.exists(), "loaded": False, "schedule": None}
    if path.exists():
        try:
            data = plistlib.loads(path.read_bytes())
            cal = data.get("StartCalendarInterval", {})
            out["schedule"] = f"{int(cal.get('Hour', 0)):02d}:{int(cal.get('Minute', 0)):02d}"
            out["command"] = " ".join(data.get("ProgramArguments", []))
        except Exception:  # noqa: BLE001
            pass
    res = _launchctl(["print", f"{domain()}/{LABEL}"], run)
    if res.returncode == 0:
        out["loaded"] = True
        out.update(parse_launchctl_print(res.stdout))
    return out


def status_lines(info: Dict[str, object]) -> List[str]:
    lines = []
    if not info.get("installed"):
        lines.append("❌ Dnevni posao NIJE podešen. Pokreni: python -m nba_engine schedule --install")
        return lines
    lines.append(f"📄 Podešavanje: {info['plist']}")
    lines.append(f"⏰ Vrijeme: svaki dan u {info.get('schedule') or '?'}  |  komanda: {info.get('command', '?')}")
    if info.get("loaded"):
        lines.append(f"✅ Registrovan kod launchd (state: {info.get('state', '?')}, "
                     f"zadnji izlazni kod: {info.get('last exit code', '?')}, pokretanja: {info.get('runs', '?')})")
    else:
        lines.append("⚠️  Plist postoji, ali posao nije registrovan kod launchd — pokreni --install ponovo")
    return lines
