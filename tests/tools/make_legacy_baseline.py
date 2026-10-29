"""Run the LEGACY app.py headlessly (streamlit AppTest) with network disabled and dump its tables."""
import os, sys, pathlib, shutil, subprocess, tempfile
from unittest import mock
import pandas as pd

REPO = pathlib.Path(sys.argv[1]); OUT = pathlib.Path(sys.argv[2]); REF = sys.argv[3] if len(sys.argv) > 3 else "local/desktop-2026-10"
OUT.mkdir(parents=True, exist_ok=True)
work = pathlib.Path(tempfile.mkdtemp(prefix="legacy_app_"))
src = subprocess.check_output(["git", "-C", str(REPO), "show", f"{REF}:app.py"], text=True)
(work / "app.py").write_text(src, encoding="utf-8")
os.symlink(REPO / "data", work / "data")
os.chdir(work)

import requests
def _offline(*a, **k):
    raise requests.ConnectionError("network disabled for baseline")

from streamlit.testing.v1 import AppTest
with mock.patch.object(requests, "get", _offline):
    at = AppTest.from_file(str(work / "app.py"), default_timeout=600)
    at.run()

print("exceptions:", len(at.exception))
for e in at.exception:
    print("EXC:", str(e.value)[:500]); print(str(e.stack_trace)[-1500:] if hasattr(e, 'stack_trace') else "")
print("errors:", [str(x.value)[:200] for x in at.error])
print("warnings:", [str(x.value)[:200] for x in at.warning][:10])
print("captions:", [str(x.value)[:120] for x in at.caption][:12])
print("dataframes:", len(at.dataframe))
best = None
for i, d in enumerate(at.dataframe):
    v = d.value
    print(f"  [{i}] shape={v.shape} cols={list(v.columns)[:6]}...")
    if "True Score" in v.columns and (best is None or len(v) > len(best)):
        best = v
if best is None:
    print("NO portfolio dataframe found"); sys.exit(2)
best.to_csv(OUT / "legacy_full_portfolio.csv", index=False)
print("saved", OUT / "legacy_full_portfolio.csv", best.shape)
# also history file written by legacy app
hist = sorted((work / "history").glob("analysis_*.csv"))
print("legacy history files:", [h.name for h in hist])
if hist:
    shutil.copy(hist[-1], OUT / "legacy_history_analysis.csv")
shutil.rmtree(work, ignore_errors=True)
