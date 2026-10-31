import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from nba_engine.config import Settings
from nba_engine.daily import (MAX_OFFER_AGE_HOURS, DailyReport, StageResult, changed_tracked_paths, is_data_csv,
                              load_last_report, offer_age_hours, prune_logs, push_data_to_git, run_daily,
                              stage_analyze, stage_offer)


def _settings(tmp_path):
    return Settings.load(data_dir=tmp_path / "data", season="2026-27", env_file=tmp_path / "no.env",
                         history_dir=tmp_path / "history")


def test_run_daily_runs_stages_in_order_and_isolates_failures(tmp_path, monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    calls = []

    def ok(name):
        def fn(settings, log, **kw):
            calls.append(name)
            log(f"radim {name}")
            return f"{name} gotovo"
        return fn

    def boom(settings, log, **kw):
        calls.append("settle")
        raise RuntimeError("NBA Stats ne odgovara")

    def skip(settings, log, **kw):
        calls.append("offer")
        return "SKIP: nema ključa"

    runners = {"refresh": ok("refresh"), "settle": boom, "offer": skip, "analyze": ok("analyze"), "push": ok("push")}
    lines = []
    report = run_daily(_settings(tmp_path), log=lines.append, runners=runners, log_dir=tmp_path / "logs")
    assert calls == ["refresh", "settle", "offer", "analyze"]  # push samo uz push=True
    assert [s.status for s in report.stages] == ["ok", "failed", "skipped", "ok"]
    assert report.stages[1].message == "NBA Stats ne odgovara"
    assert report.stages[2].message == "nema ključa"
    assert not report.ok and len(report.failed) == 1
    assert any("radim refresh" in l for l in lines) and any("Rezime" in l for l in lines)
    # log fajl i zadnji izvještaj
    assert Path(report.log_path).exists() and "NBA Stats ne odgovara" in Path(report.log_path).read_text()
    last = load_last_report(tmp_path / "logs")
    assert last["ok"] is False and [s["name"] for s in last["stages"]] == ["refresh", "settle", "offer", "analyze"]

    calls.clear()
    report2 = run_daily(_settings(tmp_path), runners=runners, push=True, stages=["refresh", "push"],
                        log_dir=tmp_path / "logs")
    assert calls == ["refresh", "push"] and report2.ok
    assert len(list((tmp_path / "logs").glob("daily_*.log"))) == 2


def test_run_daily_rejects_unknown_stage_and_prunes_logs(tmp_path):
    with pytest.raises(KeyError):
        run_daily(_settings(tmp_path), stages=["refresh", "nepostoji"], runners={}, write_logs=False)
    logs = tmp_path / "logs"
    logs.mkdir()
    for i in range(5):
        (logs / f"daily_2026-10-{i + 1:02d}_180000.log").write_text("x")
    assert prune_logs(logs, keep=3) == 2
    assert sorted(p.name for p in logs.glob("daily_*.log")) == ["daily_2026-10-03_180000.log",
                                                                "daily_2026-10-04_180000.log",
                                                                "daily_2026-10-05_180000.log"]
    assert load_last_report(logs) is None


def test_stage_offer_skips_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    msg = stage_offer(_settings(tmp_path), log=lambda m: None)
    assert msg.startswith("SKIP") and "ODDS_API_KEY" in msg


def test_report_summary_and_dict():
    rep = DailyReport(started="2026-10-31T18:00:00",
                      stages=[StageResult("refresh", "ok", "4 koraka", 61.2), StageResult("push", "failed", "nema mreže", 1)])
    lines = rep.summary_lines()
    assert lines[0].startswith("✅") and "Osvježavanje" in lines[0] and lines[1].startswith("❌")
    d = rep.to_dict()
    assert d["ok"] is False and d["stages"][1]["message"] == "nema mreže"
    json.dumps(d)  # serijalizabilno


def test_changed_paths_and_data_filter():
    out = " M data/players_2026-27.csv\n?? logs/x.log\n M nba_engine/model.py\nR  data/a.csv -> data/b.csv\nA  data/offer_2026-10-31.csv\n"
    paths = changed_tracked_paths(out)
    assert paths == ["data/players_2026-27.csv", "nba_engine/model.py", "data/b.csv", "data/offer_2026-10-31.csv"]
    assert is_data_csv("data/players_2026-27.csv") and not is_data_csv("nba_engine/model.py")
    assert not is_data_csv("data/sub/x.csv") and not is_data_csv("data/props.json")


class _FakeGit:
    """Simulira git komande; snima pozive."""

    def __init__(self, branch="main", status="", staged_changed=True, ahead="1", pull_rc=0, push_rc=0):
        self.branch, self.status, self.staged_changed = branch, status, staged_changed
        self.ahead, self.pull_rc, self.push_rc = ahead, pull_rc, push_rc
        self.calls = []

    def __call__(self, cmd, capture_output=True, text=True):
        args = cmd[3:]  # git -C repo ...
        self.calls.append(args)
        rc, out, err = 0, "", ""
        if args[0] == "rev-parse":
            out = self.branch + "\n"
        elif args[0] == "status":
            out = self.status
        elif args[0] == "diff":
            rc = 1 if self.staged_changed else 0
        elif args[0] == "rev-list":
            out = self.ahead + "\n"
        elif args[0] == "pull":
            rc, err = self.pull_rc, "CONFLICT" if self.pull_rc else ""
        elif args[0] == "push":
            rc, err = self.push_rc, "rejected" if self.push_rc else ""
        return subprocess.CompletedProcess(cmd, rc, out, err)


def test_push_data_commits_pulls_and_pushes(tmp_path):
    git = _FakeGit(status=" M data/players_2026-27.csv\n")
    msg = push_data_to_git(tmp_path, log=lambda m: None, run=git, today=dt.date(2026, 10, 31))
    names = [c[0] for c in git.calls]
    assert names == ["rev-parse", "status", "add", "diff", "commit", "rev-list", "pull", "push"]
    assert git.calls[2] == ["add", "--", "data/*.csv"]
    assert "data: daily refresh 2026-10-31" in git.calls[4]
    assert "--rebase" in git.calls[6] and "--strategy-option=theirs" in git.calls[6]
    assert msg.startswith("poslato na GitHub")


def test_push_data_guards(tmp_path):
    # ne na main
    git = _FakeGit(branch="feature/x")
    assert push_data_to_git(tmp_path, lambda m: None, run=git).startswith("SKIP: grana je 'feature/x'")
    assert [c[0] for c in git.calls] == ["rev-parse"]
    # izmijenjen i kod → ne šalje
    git = _FakeGit(status=" M data/players_2026-27.csv\n M nba_engine/model.py\n")
    msg = push_data_to_git(tmp_path, lambda m: None, run=git)
    assert msg.startswith("SKIP") and "nba_engine/model.py" in msg
    assert "add" not in [c[0] for c in git.calls]
    # ništa novo
    git = _FakeGit(status="", staged_changed=False, ahead="0")
    assert push_data_to_git(tmp_path, lambda m: None, run=git) == "nema novih izmjena podataka za slanje"
    # stari lokalni commit bez novih izmjena → ipak pokušaj push
    git = _FakeGit(status="", staged_changed=False, ahead="2")
    assert "2 commita" in push_data_to_git(tmp_path, lambda m: None, run=git)
    # pull pada → rebase --abort i greška
    git = _FakeGit(status=" M data/x.csv\n", pull_rc=1)
    with pytest.raises(RuntimeError, match="pull/rebase"):
        push_data_to_git(tmp_path, lambda m: None, run=git)
    assert ["rebase", "--abort"] in git.calls and "push" not in [c[0] for c in git.calls]
    # push pada → greška, commit ostaje
    git = _FakeGit(status=" M data/x.csv\n", push_rc=1)
    with pytest.raises(RuntimeError, match="push nije uspio"):
        push_data_to_git(tmp_path, lambda m: None, run=git)


def test_stage_analyze_skips_old_offer(tmp_path, monkeypatch):
    import os
    s = _settings(tmp_path)
    (tmp_path / "data").mkdir()
    offer = tmp_path / "data" / "offer_latest.csv"
    offer.write_text("PLAYER,LINE,OVER_ODDS,UNDER_ODDS\n")
    old = (dt.datetime.now() - dt.timedelta(hours=MAX_OFFER_AGE_HOURS + 5)).timestamp()
    os.utime(offer, (old, old))
    assert offer_age_hours(offer) > MAX_OFFER_AGE_HOURS
    msg = stage_analyze(s, log=lambda m: None)
    assert msg.startswith("SKIP") and "stara" in msg
    assert stage_analyze(_settings(tmp_path / "prazno"), log=lambda m: None).startswith("SKIP: nema fajla")
