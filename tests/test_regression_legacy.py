"""Regresija: nova aplikacija mora dati ISTE brojke kao stari app.py na stvarnim podacima.

Zlatni fajl tests/fixtures/legacy_full_portfolio.csv napravljen je pokretanjem originalnog app.py
(commit a52f8d2) bez mreže, sa podrazumijevanim kontrolama (5000 simulacija, min EV 0).
Ponovno generisanje: python tests/tools/make_legacy_baseline.py <repo> <out_dir>
"""
import pathlib

import numpy as np
import pandas as pd
import pytest

from nba_engine.offer import read_offer_file
from nba_engine.pipeline import AnalysisOptions, run_analysis

GOLD = pathlib.Path(__file__).parent / "fixtures" / "legacy_full_portfolio.csv"


# Stari app.py: bez dopune prošlom sezonom (conftest) i bez L10 ulaza za minute/rasipanje
LEGACY = dict(use_l10_minutes=False, use_l10_sigma=False)

@pytest.fixture(scope="module")
def result(real_data, bundle_legacy_mode):
    offer = real_data.data_dir / "offer_latest.csv"
    if not offer.exists():
        pytest.skip("nema data/offer_latest.csv")
    return run_analysis(read_offer_file(offer), bundle_legacy_mode, AnalysisOptions(**LEGACY))


def test_matches_legacy_golden_output(result):
    gold = pd.read_csv(GOLD)
    new = result.df.reset_index(drop=True)
    # Novi kod smije dodati kolone (npr. Minutes Base, Prior Weight); zlatne kolone moraju postojati i biti iste
    missing = [c for c in gold.columns if c not in new.columns]
    assert not missing, f"nedostaju kolone iz zlatnog izlaza: {missing}"
    assert len(new) == len(gold)
    new = new[gold.columns]
    assert set(new.columns) == set(gold.columns)
    assert new["Player"].tolist() == gold["Player"].tolist()
    for c in gold.columns:
        g, n = gold[c], new[c]
        if pd.api.types.is_numeric_dtype(g) and not pd.api.types.is_bool_dtype(g):
            gv = g.to_numpy(dtype=float)
            nv = pd.to_numeric(n, errors="coerce").to_numpy(dtype=float)
            both_nan = np.isnan(gv) & np.isnan(nv)
            assert np.all(both_nan | (np.abs(gv - nv) <= 1e-6)), f"kolona {c!r} se razlikuje"
        else:
            assert g.fillna("__na__").astype(str).tolist() == n.fillna("__na__").astype(str).tolist(), f"kolona {c!r}"


def test_summary_counts(result):
    assert result.ok and len(result.offer_rows) == 62 and result.bad_lines == []
    assert result.not_found == [] and result.skipped_active == []
    assert result.bm_offset == pytest.approx(1.91, abs=0.005)
    assert len(result.concentration.teams) == 7


def test_filters_and_options_change_output(real_data, bundle_legacy_mode):
    offer = real_data.data_dir / "offer_latest.csv"
    txt = read_offer_file(offer)
    strict = run_analysis(txt, bundle_legacy_mode, AnalysisOptions(min_ev=10.0, only_positive=True, mc_sims=500, **LEGACY))
    # filter Min EV se primjenjuje PRIJE kazne za koncentraciju (kao u originalu), pa se dijeli kaznom
    penalty = strict.df["Conc Penalty"] if "Conc Penalty" in strict.df.columns else 1.0
    assert strict.ok and (strict.df["Best EV %"] / penalty >= 10.0 - 1e-6).all()
    skipped = run_analysis(txt, bundle_legacy_mode, AnalysisOptions(game_statuses={"MIN": {"state": "in", "detail": "Q3"}}, **LEGACY))
    assert skipped.skipped_active and all(s["Team"] == "MIN" or s["Opp"] == "MIN" for s in skipped.skipped_active)
    override = run_analysis(txt, bundle_legacy_mode, AnalysisOptions(recent_form_override={"anthony edwards": 40.0}, **LEGACY))
    assert override.recent_form_count == 1
    assert run_analysis("", bundle_legacy_mode).ok is False
    assert run_analysis("Nobody Here,20.5,1.9,1.9", bundle_legacy_mode).message.startswith("Nijedan igrač")
