"""Ispravke logike (grupa A): OUT igrači van rangiranja, domaćin/gost, B2B i odmor iz rasporeda, svježina ponude.

Koriste stvarne podatke iz data/ (sezona iz conftest) i ponudu offer_latest.csv.
"""
import datetime as dt

import pytest

from nba_engine.loaders import load_bundle
from nba_engine.offer import parse_injury_override, read_offer_file
from nba_engine.pipeline import AnalysisOptions, auto_context, format_auto_context, offer_freshness, run_analysis
from nba_engine.schedule import ScheduleContext

FAST = dict(mc_sims=500)


@pytest.fixture(scope="module")
def bundle(real_data):
    return load_bundle(real_data, fill_injury_team_from_players=True)


@pytest.fixture(scope="module")
def offer_text(real_data):
    p = real_data.data_dir / "offer_latest.csv"
    if not p.exists():
        pytest.skip("nema offer_latest.csv")
    return read_offer_file(p)


def test_out_players_are_excluded_from_ranking(bundle, offer_text):
    res = run_analysis(offer_text, bundle, AnalysisOptions(**FAST))
    assert res.ok
    assert (res.df["Direct Player Penalty"] > 0).all()
    assert all(e["Status"] in ("OUT", "INACTIVE") for e in res.excluded_out)
    assert {"Player", "Team", "Opp", "Line", "Status", "Napomena"} <= set(res.excluded_out[0]) if res.excluded_out else True
    # kad se isključivanje ugasi, isti igrači se vraćaju u projekcije (staro ponašanje)
    res_all = run_analysis(offer_text, bundle, AnalysisOptions(exclude_out=False, **FAST))
    assert len(res_all.projections) == len(res.projections) + len(res.excluded_out)
    assert not res_all.excluded_out


def test_manual_injury_override_out_excludes_player(bundle, offer_text):
    base = run_analysis(offer_text, bundle, AnalysisOptions(**FAST))
    name = base.df.iloc[0]["Player"]
    override = parse_injury_override(f"{name}, OUT", bundle.players)
    assert not override.empty
    res = run_analysis(offer_text, bundle, AnalysisOptions(injury_override=override, **FAST))
    assert name not in set(res.df["Player"])
    assert any(e["Player"] == name and e["Status"] == "OUT" for e in res.excluded_out)


def _ctx_for(team, opp, today, last_game_days_ago=None, team_is_home=False):
    home, away = (team, opp) if team_is_home else (opp, team)
    ctx = ScheduleContext(today=today, fetched=True, games_today=[(home, away)], home_teams={home}, away_teams={away},
                          opponent_today={team: opp, opp: team})
    if last_game_days_ago is not None:
        ctx.last_game_date[team] = today - dt.timedelta(days=last_game_days_ago)
    return ctx


def test_schedule_context_drives_home_away_b2b_and_rest(bundle, offer_text):
    base = run_analysis(offer_text, bundle, AnalysisOptions(**FAST))
    row = base.df.iloc[0]
    team, opp, player = row["TEAM_ABBR"], row["OPP_TEAM"], row["Player"]
    assert row["Is Home"] and row["Rest Days"] == 2 and not row["B2B Team"]   # bez rasporeda: stare podrazumijevane
    today = dt.date.today()

    # gost + igrao juče → gost, B2B, 0 dana odmora
    res = run_analysis(offer_text, bundle, AnalysisOptions(schedule=_ctx_for(team, opp, today, 1), **FAST))
    r = res.df[res.df["Player"] == player].iloc[0]
    assert not r["Is Home"] and r["B2B Team"] and r["Rest Days"] == 0
    assert r["Home/Away Factor"] == 0.975 and r["B2B Factor"] < 1.0
    # samo jedan meč iz ponude je „danas“ → ponuda kao cjelina nije svježa (pravilo polovine), ali raspored važi
    assert res.offer_today_matches >= 1 and res.offer_is_today is (res.offer_today_matches * 2 >= res.offer_matched_rows)
    assert team in res.auto_context["away"] and team in res.auto_context["b2b"]
    full = _ctx_for(team, opp, today, 1)
    for t, o in zip(base.df["TEAM_ABBR"], base.df["OPP_TEAM"]):
        if t and o and t not in full.opponent_today and o not in full.opponent_today:
            full.games_today.append((o, t)); full.home_teams.add(o); full.away_teams.add(t)
            full.opponent_today.update({t: o, o: t})
    res_full = run_analysis(offer_text, bundle, AnalysisOptions(schedule=full, **FAST))
    assert res_full.offer_is_today is True and res_full.offer_today_matches == res_full.offer_matched_rows
    assert "B2B" in format_auto_context(res.auto_context)

    # domaćin + igrao prije 3 dana → 2 dana odmora
    res2 = run_analysis(offer_text, bundle, AnalysisOptions(schedule=_ctx_for(team, opp, today, 3, team_is_home=True), **FAST))
    r2 = res2.df[res2.df["Player"] == player].iloc[0]
    assert r2["Is Home"] and not r2["B2B Team"] and r2["Rest Days"] == 2

    # ručni unos ima prednost: raspored kaže domaćin / 2 dana, ručno gost / 4 dana
    res3 = run_analysis(offer_text, bundle, AnalysisOptions(
        schedule=_ctx_for(team, opp, today, 3, team_is_home=True), away_teams_manual={team},
        rest_days_map={team: 4}, **FAST))
    r3 = res3.df[res3.df["Player"] == player].iloc[0]
    assert not r3["Is Home"] and r3["Rest Days"] == 4


def test_offer_freshness_flags_stale_offer(bundle, offer_text):
    today = dt.date.today()
    stale = ScheduleContext(today=today, fetched=True, games_today=[("AAA", "BBB")], home_teams={"AAA"}, away_teams={"BBB"})
    res = run_analysis(offer_text, bundle, AnalysisOptions(schedule=stale, **FAST))
    assert res.offer_is_today is False and res.offer_today_matches == 0 and res.offer_matched_rows > 0
    assert res.auto_context == {"games_today": 1, "away": [], "b2b": [], "rest": {}}
    # bez rasporeda ili kad ESPN ne radi → nepoznato, bez upozorenja
    assert run_analysis(offer_text, bundle, AnalysisOptions(**FAST)).offer_is_today is None
    assert run_analysis(offer_text, bundle, AnalysisOptions(schedule=ScheduleContext(today=today), **FAST)).offer_is_today is None


def test_offer_freshness_helpers_pure():
    today = dt.date(2026, 10, 30)
    ctx = ScheduleContext(today=today, fetched=True, games_today=[("LAL", "OKC")], home_teams={"LAL"}, away_teams={"OKC"})
    assert offer_freshness([("OKC", "LAL"), ("BOS", "MIA")], ctx) == (True, 1)
    assert offer_freshness([("BOS", "MIA")], ctx) == (False, 0)
    assert offer_freshness([("OKC", ""), ("BOS", "")], ctx) == (True, 1)      # ponuda bez protivnika: tim igra danas
    # slučajno poklapanje jednog para u staroj ponudi nije dovoljno (traži se bar polovina parova)
    assert offer_freshness([("OKC", "LAL"), ("BOS", "MIA"), ("DET", "CHI"), ("PHX", "DEN")], ctx) == (False, 1)
    assert offer_freshness([("OKC", "LAL"), ("BOS", "MIA"), ("DET", "CHI")], ctx, min_share=0.3) == (True, 1)
    assert offer_freshness([], ctx) == (None, 0) and offer_freshness([("OKC", "LAL")], None) == (None, 0)
    assert auto_context([("OKC", "LAL")], ctx)["away"] == ["OKC"] and format_auto_context({}) == ""
