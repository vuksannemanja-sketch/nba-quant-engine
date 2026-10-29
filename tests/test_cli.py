import os
import subprocess
import sys

import pytest

from tests.conftest import DATA_SEASON, ROOT


def _run(*args, **env):
    e = {**os.environ, "NBA_SEASON": DATA_SEASON}
    for k in ("NBA_DATA_DIR", "NBA_HISTORY_DIR", "ODDS_API_KEY"):
        e.pop(k, None)
    e.update(env)
    return subprocess.run([sys.executable, "-m", "nba_engine", *args], cwd=ROOT, env=e,
                          capture_output=True, text=True, timeout=600)


def test_cli_help_lists_commands():
    r = _run("--help")
    assert r.returncode == 0
    for cmd in ("ui", "analyze", "fetch-offer", "refresh", "check"):
        assert cmd in r.stdout


def test_cli_check_runs():
    r = _run("check")
    assert r.returncode == 0 and "Podešavanja:" in r.stdout and "Igrači (glavni)" in r.stdout


def test_cli_analyze_on_real_data(real_data, tmp_path):
    offer = real_data.data_dir / "offer_latest.csv"
    if not offer.exists():
        pytest.skip("nema offer_latest.csv")
    out = tmp_path / "full.csv"
    r = _run("analyze", "--offer", str(offer), "--no-schedule", "--top", "5", "--out", str(out),
             "--history-dir", str(tmp_path / "hist"), "--mc-sims", "1000")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Model Pick" in r.stdout and out.exists()
    assert list((tmp_path / "hist").glob("analysis_*.csv"))


def test_cli_fetch_offer_without_key_fails_cleanly(tmp_path):
    r = _run("fetch-offer", "--data-dir", str(tmp_path), "--env-file", str(tmp_path / "no.env"), ODDS_API_KEY="")
    r_global = _run("--data-dir", str(tmp_path), "--env-file", str(tmp_path / "no.env"), "check", ODDS_API_KEY="")
    assert r_global.returncode == 0 and "❌ nema" in r_global.stdout
    assert r.returncode == 1 and "ODDS_API_KEY" in r.stdout
