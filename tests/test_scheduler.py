import plistlib
import subprocess
from pathlib import Path

import pytest

from nba_engine import scheduler


def test_render_plist_contents():
    raw = scheduler.render_plist(Path("/p/.venv/bin/python"), Path("/p"), 18, 30)
    data = plistlib.loads(raw)
    assert data["Label"] == "com.nba-engine.daily"
    assert data["ProgramArguments"] == ["/p/.venv/bin/python", "-m", "nba_engine", "daily", "--push"]
    assert data["StartCalendarInterval"] == {"Hour": 18, "Minute": 30}
    assert data["WorkingDirectory"] == "/p" and data["StandardOutPath"] == "/p/logs/launchd.out.log"
    assert data["RunAtLoad"] is False and "PATH" in data["EnvironmentVariables"]
    with pytest.raises(ValueError):
        scheduler.render_plist(Path("/p/python"), Path("/p"), 24, 0)
    assert scheduler.daily_args(push=False, with_h2h=True) == ["daily", "--with-h2h"]
    assert scheduler.cron_line(Path("/p/python"), Path("/p"), 7, 5).startswith("5 7 * * * cd /p && /p/python -m nba_engine daily --push")


class _FakeLaunchctl:
    def __init__(self, print_rc=0):
        self.calls, self.print_rc = [], print_rc

    def __call__(self, cmd, capture_output=True, text=True):
        self.calls.append(cmd[1:])
        if cmd[1] == "print":
            out = "\tstate = waiting\n\tlast exit code = 0\n\truns = 3\n" if self.print_rc == 0 else ""
            return subprocess.CompletedProcess(cmd, self.print_rc, out, "" if self.print_rc == 0 else "Could not find service")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def test_install_status_remove_roundtrip(tmp_path):
    home, proj = tmp_path / "home", tmp_path / "proj"
    proj.mkdir()
    (proj / ".venv" / "bin").mkdir(parents=True)
    py = proj / ".venv" / "bin" / "python"
    lc = _FakeLaunchctl()
    path = scheduler.install(hour=7, minute=15, push=False, python_exe=py, project_root=proj, home=home, run=lc,
                             log=lambda m: None, platform="darwin")
    assert path == home / "Library" / "LaunchAgents" / "com.nba-engine.daily.plist" and path.exists()
    assert (proj / "logs").is_dir()
    data = plistlib.loads(path.read_bytes())
    assert data["ProgramArguments"][-1] == "daily" and data["ProgramArguments"][0] == str(py)  # bez resolve()
    assert [c[0] for c in lc.calls] == ["bootout", "bootstrap", "enable"]
    assert lc.calls[1][2] == str(path)

    info = scheduler.status(home=home, run=lc)
    assert info["installed"] and info["loaded"] and info["schedule"] == "07:15"
    assert info["state"] == "waiting" and info["last exit code"] == "0" and info["runs"] == "3"
    lines = scheduler.status_lines(info)
    assert any("07:15" in l for l in lines) and any("Registrovan" in l for l in lines)

    assert scheduler.remove(home=home, run=lc, log=lambda m: None) is True
    assert not path.exists()
    assert scheduler.remove(home=home, run=lc, log=lambda m: None) is False
    info2 = scheduler.status(home=home, run=_FakeLaunchctl(print_rc=113))
    assert not info2["installed"] and "NIJE podešen" in scheduler.status_lines(info2)[0]


def test_install_refuses_non_mac(tmp_path):
    with pytest.raises(RuntimeError, match="crontab"):
        scheduler.install(python_exe=tmp_path / "py", project_root=tmp_path, home=tmp_path, run=_FakeLaunchctl(),
                          log=lambda m: None, platform="linux")


def test_parse_launchctl_print():
    txt = "com.nba-engine.daily = {\n\tactive count = 0\n\tpath = /x\n\tstate = waiting\n\tprogram = /p/python\n\tlast exit code = 1\n}"
    info = scheduler.parse_launchctl_print(txt)
    assert info == {"state": "waiting", "program": "/p/python", "last exit code": "1"}
