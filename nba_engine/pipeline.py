"""Kompletna dnevna analiza: ponuda → projekcije → Monte Carlo → rangiranje → kontrola koncentracije.

Redoslijed koraka i sve formule odgovaraju originalnom ``app.py``; ovdje su samo odvojeni od prikaza
tako da ista logika radi iz Streamlit aplikacije, komandne linije i testova.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from .loaders import DataBundle
from .model import (build_player_context, estimate_match_total, find_team_row_by_abbr,
                    is_team_b2b, match_player_row, compute_max_edge, compute_per_player_bm_offset)
from .offer import OfferRow, parse_offer_text
from .schedule import ScheduleContext
from .teams import normalize_team_abbr
from .utils import clamp, get_float, normalize_name, zscore

MC_SIMS_CHOICES = (500, 1000, 3000, 5000)


@dataclass
class AnalysisOptions:
    """Podešavanja jedne analize (odgovaraju kontrolama u bočnoj traci)."""
    mc_sims: int = 5000
    min_ev: float = 0.0
    only_positive: bool = False
    recent_form_override: Dict[str, float] = field(default_factory=dict)
    b2b_teams_manual: Set[str] = field(default_factory=set)
    b2b_date: str = field(default_factory=lambda: _dt.date.today().isoformat())
    away_teams_manual: Set[str] = field(default_factory=set)
    rest_days_map: Dict[str, int] = field(default_factory=dict)
    injury_override: Optional[pd.DataFrame] = None
    game_statuses: Dict[str, dict] = field(default_factory=dict)
    schedule: Optional[ScheduleContext] = None   # ESPN: domaćin/gost, B2B, odmor i današnji mečevi (automatski)
    exclude_out: bool = True                     # igrači sa statusom OUT/INACTIVE ne ulaze u rangiranje
    use_l10_minutes: bool = True                 # minute dopunjene minutama iz zadnjih 10 utakmica (L10_MIN)
    use_l10_sigma: bool = True                   # rasipanje dopunjeno stvarnim rasipanjem iz zadnjih 10 (L10_STD)
    seed: int = 42


@dataclass
class ConcentrationInfo:
    """Timovi sa 3+ OVER pickova i primijenjene EV kazne."""
    teams: List[str] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    usg_sums: Dict[str, float] = field(default_factory=dict)
    players: Dict[str, List[str]] = field(default_factory=dict)
    penalized: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    df: pd.DataFrame
    projections: pd.DataFrame
    offer_rows: List[OfferRow]
    bad_lines: List[Tuple[str, str]]
    not_found: List[Dict[str, Any]]
    skipped_active: List[Dict[str, Any]]
    bm_offset: Optional[float]
    concentration: ConcentrationInfo
    recent_form_count: int = 0
    injuries_used: Optional[pd.DataFrame] = None
    message: str = ""
    excluded_out: List[Dict[str, Any]] = field(default_factory=list)   # OUT igrači, opklada bi bila poništena
    offer_is_today: Optional[bool] = None    # None = raspored nije dostupan, svježina ponude nije provjerena
    offer_today_matches: int = 0
    offer_matched_rows: int = 0
    auto_context: Dict[str, Any] = field(default_factory=dict)         # šta je uzeto iz ESPN rasporeda

    @property
    def ok(self) -> bool:
        return not self.df.empty


# ---------------------------------------------------------------------------
# Ozljede: ručni unos ima prednost nad CSV-om
# ---------------------------------------------------------------------------

def merge_injury_override(inj_df: Optional[pd.DataFrame], override: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if override is None or override.empty:
        return inj_df
    if inj_df is not None and "NAME_KEY" in inj_df.columns:
        base = inj_df[~inj_df["NAME_KEY"].isin(override["NAME_KEY"])]
        return pd.concat([base, override], ignore_index=True)
    return override


# ---------------------------------------------------------------------------
# Korak 1: projekcije po igraču
# ---------------------------------------------------------------------------

def build_projections(rows: List[OfferRow], bundle: DataBundle, options: AnalysisOptions,
                      inj_df: Optional[pd.DataFrame]
                      ) -> Tuple[pd.DataFrame, List[Dict], List[Dict], List[Dict], List[Tuple[str, str]]]:
    """Vraća (projekcije, nije nađeno, preskočeni mečevi u toku, isključeni OUT, parovi tim-protivnik)."""
    players_df, teams_df = bundle.players, bundle.teams
    statuses = options.game_statuses or {}
    sched = options.schedule
    results: List[Dict] = []
    not_found: List[Dict] = []
    skipped_active: List[Dict] = []
    excluded_out: List[Dict] = []
    matched_pairs: List[Tuple[str, str]] = []

    for name, line_val, over_odds, under_odds, opp_from_txt, total_from_txt in rows:
        r0, used_key, method = match_player_row(players_df, name)
        if r0 is None:
            not_found.append({"offer_name": name, "norm": normalize_name(name), "method": method})
            continue

        team_abbr = normalize_team_abbr(r0.get("TEAM_ABBR"))
        team_row = find_team_row_by_abbr(teams_df, team_abbr) if pd.notna(team_abbr) else None

        # Protivnik iz ponude; ako je jednak timu igrača, to je greška u ponudi → ignoriši
        opp_team_abbr = None
        if opp_from_txt:
            opp_candidate = normalize_team_abbr(opp_from_txt)
            if pd.notna(opp_candidate):
                if pd.isna(team_abbr) or str(opp_candidate).upper() != str(team_abbr).upper():
                    opp_team_abbr = opp_candidate
        opp_row = find_team_row_by_abbr(teams_df, opp_team_abbr) if opp_team_abbr else None

        # Meč već počeo ili završio? → preskoči
        team_str = str(team_abbr).upper() if pd.notna(team_abbr) else ""
        opp_str = str(opp_team_abbr).upper() if opp_team_abbr and pd.notna(opp_team_abbr) else ""
        if team_str:
            matched_pairs.append((team_str, opp_str))
        game_state = None
        for chk in (team_str, opp_str):
            if chk and chk in statuses:
                game_state = statuses[chk]["state"]
                break
        if game_state in ("in", "post"):
            detail = statuses.get(team_str or opp_str, {}).get("detail", "")
            skipped_active.append({"Player": name, "Team": team_str or "?", "Opp": opp_str or "?",
                                   "Status": "🔴 LIVE" if game_state == "in" else "✅ Final", "Detail": detail})
            continue

        total_match_model = estimate_match_total(team_row, opp_row, None, teams_df) \
            if team_row is not None and opp_row is not None else None
        total_match_used = float(total_from_txt) \
            if total_from_txt is not None and np.isfinite(total_from_txt) else total_match_model

        # B2B, domaćin/gost i odmor: fajl odigranih mečeva + ESPN raspored za danas; ručni unos ima prednost
        b2b_team = (is_team_b2b(bundle.b2b, team_str, options.b2b_date) or (team_str in options.b2b_teams_manual)
                    or (sched is not None and sched.is_b2b(team_str)))
        b2b_opp = (is_team_b2b(bundle.b2b, opp_str, options.b2b_date) or (opp_str in options.b2b_teams_manual)
                   or (sched is not None and sched.is_b2b(opp_str)))
        is_home = team_str not in options.away_teams_manual and not (sched is not None and team_str in sched.away_teams)
        rest_days = _resolve_rest_days(team_str, options)
        opp_rest_days = _resolve_rest_days(opp_str, options)
        if b2b_team:
            rest_days = 0
        if b2b_opp:
            opp_rest_days = 0

        ctx = build_player_context(
            r0=r0, players_df=players_df, teams_df=teams_df,
            team_row=team_row, opp_row=opp_row, inj_df=inj_df,
            team_abbr=team_abbr, player_name_key=used_key,
            total_match_used=total_match_used,
            recent_form_override=options.recent_form_override,
            h2h_df=bundle.h2h, opp_team_abbr=opp_team_abbr, l10_df=bundle.l10,
            def_matchup_df=bundle.def_matchup, off_matchup_df=bundle.off_matchup,
            line_val=float(line_val), b2b_team=b2b_team, b2b_opp=b2b_opp,
            is_home=is_home, rest_days=rest_days, opp_rest_days=opp_rest_days,
            use_l10_minutes=options.use_l10_minutes, use_l10_sigma=options.use_l10_sigma,
        )

        # Igrač koji je OUT ne igra: kladionica takvu opkladu poništava, pa ne ulazi u rangiranje
        if options.exclude_out and ctx.get("injury_status") in ("OUT", "INACTIVE"):
            excluded_out.append({"Player": str(r0.get("PLAYER_NAME", name)), "Team": team_str or "?",
                                 "Opp": opp_str or "?", "Line": float(line_val), "Status": ctx["injury_status"],
                                 "Napomena": "ne igra — opklada bi bila poništena"})
            continue

        results.append({
            "Player":               str(r0.get("PLAYER_NAME", name)),
            "Matched By":           method,
            "TEAM_ABBR":            team_abbr,
            "OPP_TEAM":             opp_team_abbr,
            "NET_RATING":           get_float(team_row, "NET_RATING", 0.0) if team_row is not None else 0.0,
            "OPP_DEF":              ctx["opp_def"],
            "PACE_GAME":            round(float(ctx["pace_game"]), 3),
            "TOTAL_MATCH_OFFER":    float(total_from_txt) if total_from_txt is not None and np.isfinite(total_from_txt) else None,
            "TOTAL_MATCH_MODEL":    round(float(total_match_model), 2) if total_match_model is not None else None,
            "TOTAL_MATCH_USED":     round(float(total_match_used), 2) if total_match_used is not None else None,
            "Line":                 float(line_val),
            "Over Odds":            float(over_odds),
            "Under Odds":           float(under_odds),
            "PPM":                  round(float(ctx["ppm"]), 4),
            "Minutes":              round(float(ctx["minutes_proj"]), 2),
            "Minutes Base":         round(float(ctx.get("minutes_base", ctx["minutes_proj"])), 2),
            "L10 MIN":              round(float(ctx["l10_min"]), 2) if ctx.get("l10_min") is not None and np.isfinite(ctx["l10_min"]) else None,
            "L10 STD":              round(float(ctx["l10_std"]), 2) if ctx.get("l10_std") is not None and np.isfinite(ctx["l10_std"]) else None,
            "Prior Weight":         round(float(get_float(r0, "PRIOR_WEIGHT", 0.0) or 0.0), 3),
            "Usage %":              round(float(ctx["usg"]), 2) if np.isfinite(ctx["usg"]) else None,
            "PIE":                  round(float(ctx["pie"]), 3) if np.isfinite(ctx["pie"]) else None,
            "AST_RATIO":            round(float(ctx["ast_ratio"]), 2) if np.isfinite(ctx["ast_ratio"]) else None,
            "Recent Form":          round(float(ctx["recent_form_used"]), 1) if ctx.get("recent_form_used") is not None else None,
            "H2H PTS Avg":          round(float(ctx["h2h_pts"]), 1) if ctx.get("h2h_pts") else None,
            "H2H Games":            int(ctx["h2h_games"]) if ctx.get("h2h_games") else None,
            "H2H PTS Last":         round(float(ctx["h2h_pts_last"]), 1) if ctx.get("h2h_pts_last") else None,
            "L10 PTS":              round(float(ctx["l10_pts"]), 1) if ctx.get("l10_pts") else None,
            "L5 PTS":               round(float(ctx["l5_pts"]), 1) if ctx.get("l5_pts") else None,
            "L10 Trend":            round(float(ctx["l10_trend"]), 2) if ctx.get("l10_trend") is not None else None,
            "DEF Factor":           round(float(ctx["def_matchup_factor"]), 3) if ctx.get("def_matchup_factor") else None,
            "OPP Style Matchup":    round(float(ctx["opp_style_matchup"]), 3) if ctx.get("opp_style_matchup") is not None else None,
            "B2B Team":             b2b_team,
            "B2B Opp":              b2b_opp,
            "B2B Factor":           round(float(ctx.get("b2b_factor", 1.0)), 3),
            "Is Home":              ctx.get("is_home", True),
            "Rest Days":            ctx.get("rest_days", 2),
            "Home/Away Factor":     round(float(ctx.get("home_away_factor", 1.0)), 3),
            "Rest Factor":          round(float(ctx.get("rest_factor", 1.0)), 3),
            "Opp Rest Factor":      round(float(ctx.get("opp_rest_factor", 1.0)), 3),
            "Injury Boost":         round(float(ctx["injury_boost"]), 3),
            "Direct Player Penalty": round(float(ctx["direct_player_penalty"]), 3),
            "Injured Usage Lost":   round(float(ctx["injured_usage_lost"]), 2),
            "Injured Minutes Lost": round(float(ctx["injured_minutes_lost"]), 2),
            "Usage Factor":         round(float(ctx["usage_factor"]), 3),
            "Team Matchup Factor":  round(float(ctx["team_eff_matchup"]), 3),
            "Shot Factor":          round(float(ctx["shot_factor"]), 3),
            "FT Factor":            round(float(ctx["ft_factor"]), 3),
            "Efficiency Factor":    round(float(ctx["efficiency_factor"]), 3),
            "Playmaking Factor":    round(float(ctx["playmaking_factor"]), 3),
            "Turnover Factor":      round(float(ctx["turnover_factor"]), 3),
            "Role Factor":          round(float(ctx["role_factor"]), 3),
            "Style Factor":         round(float(ctx["style_factor"]), 3),
            "Total Factor":         round(float(ctx["total_factor"]), 3),
            "StarWeight":           round(float(ctx["star_w"]), 3),
            "SeasonAnchor":         round(float(ctx["season_anchor"]), 2),
            "Base Projection":      round(float(ctx["base_projection"]), 2),
            "Final Projection":     round(float(ctx["final_projection"]), 2),
            "Sigma":                round(float(ctx["sigma"]), 2),
        })

    return pd.DataFrame(results), not_found, skipped_active, excluded_out, matched_pairs


def _resolve_rest_days(team: str, options: AnalysisOptions) -> int:
    """Dani odmora: ručni unos → ESPN raspored → podrazumijevano 2 (kao u originalu)."""
    if team in options.rest_days_map:
        return int(options.rest_days_map[team])
    if options.schedule is not None:
        auto = options.schedule.rest_days(team)
        if auto is not None:
            return int(auto)
    return 2


FRESH_OFFER_MIN_SHARE = 0.5  # ponuda je „za danas“ ako je bar polovina njenih parova među današnjim mečevima


def offer_freshness(pairs: List[Tuple[str, str]], sched: Optional[ScheduleContext],
                    min_share: float = FRESH_OFFER_MIN_SHARE) -> Tuple[Optional[bool], int]:
    """(da li je ponuda za danas, broj parova koji su današnji mečevi). None kad raspored nije dostupan.

    Stara ponuda se zna slučajno poklopiti u jednom-dva para (isti timovi igraju opet), zato jedan pogodak
    nije dovoljan: traži se udio od bar ``min_share`` (podrazumijevano polovina) parova.
    """
    if sched is None or not sched.fetched or not pairs:
        return None, 0
    if any(o for _, o in pairs):
        matches = sum(1 for t, o in pairs if sched.pair_is_today(t, o))
    else:  # ponuda bez kolone protivnika: dovoljno je da tim igra danas
        matches = sum(1 for t, _ in pairs if t in sched.teams_today)
    return matches / len(pairs) >= min_share, matches


def auto_context(pairs: List[Tuple[str, str]], sched: Optional[ScheduleContext]) -> Dict[str, Any]:
    """Šta je za timove iz ponude uzeto iz ESPN rasporeda (za prikaz)."""
    if sched is None or not sched.fetched:
        return {}
    teams = {t for t, _ in pairs if t} | {o for _, o in pairs if o}
    playing = sorted(t for t in teams if t in sched.teams_today)
    return {"games_today": len(sched.games_today),
            "away": [t for t in playing if t in sched.away_teams],
            "b2b": [t for t in playing if sched.is_b2b(t)],
            "rest": {t: sched.rest_days(t) for t in playing}}


def format_auto_context(ctx: Dict[str, Any]) -> str:
    if not ctx:
        return ""
    rest = ", ".join(f"{t}={d}" for t, d in ctx.get("rest", {}).items()) or "—"
    return (f"gosti: {', '.join(ctx.get('away', [])) or '—'} | B2B: {', '.join(ctx.get('b2b', [])) or '—'} "
            f"| dani odmora: {rest}")


def compute_bm_offset(df: pd.DataFrame) -> float:
    """Prosječna razlika sezonskog sidra i linije (informativno, prikazuje se u aplikaciji)."""
    anchors = pd.to_numeric(df["SeasonAnchor"], errors="coerce").dropna()
    lines = pd.to_numeric(df["Line"], errors="coerce").dropna()
    common = anchors.index.intersection(lines.index)
    return float(clamp((anchors[common] - lines[common]).mean(), -2.0, 4.0)) if len(common) >= 3 else 1.5


# ---------------------------------------------------------------------------
# Korak 2: Monte Carlo
# ---------------------------------------------------------------------------

def run_monte_carlo(df: pd.DataFrame, mc_sims: int, league_pts_std: float, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    updated = []

    for _, row in df.iterrows():
        proj_raw = float(row["Final Projection"])
        line_val = float(row["Line"])
        over_odds = float(row["Over Odds"])
        under_odds = float(row["Under Odds"])
        season_pts = float(row.get("SeasonAnchor", proj_raw))
        usg_val = float(row["Usage %"]) if row.get("Usage %") is not None and not pd.isna(row.get("Usage %")) else 20.0
        sigma_val = float(row.get("Sigma", league_pts_std))

        player_bm_offset = compute_per_player_bm_offset(season_pts)
        proj_devigged = proj_raw - player_bm_offset

        p_over_mkt_raw = 1.0 / over_odds
        p_under_mkt_raw = 1.0 / under_odds
        total_mkt = p_over_mkt_raw + p_under_mkt_raw
        p_over_mkt = p_over_mkt_raw / total_mkt
        p_under_mkt = p_under_mkt_raw / total_mkt

        abs_edge = abs(proj_devigged - line_val)
        market_blend = (0.55 if abs_edge < 1.5 else 0.45 if abs_edge < 3.0 else 0.35 if abs_edge < 5.0 else 0.25)
        proj = (1.0 - market_blend) * proj_devigged + market_blend * line_val
        max_edge = compute_max_edge(line_val, usg_val, sigma_val)
        proj = clamp(proj, line_val - max_edge, line_val + max_edge)

        sigma = clamp(float(row.get("Sigma", league_pts_std)), max(line_val * 0.28, 2.0), 9.5)

        sims = np.clip(rng.normal(proj, sigma, int(mc_sims)), 0.0, 80.0)
        p_over_model = float(np.mean(sims > line_val))
        p_under_model = 1.0 - p_over_model

        ev_over = (p_over_model * over_odds) - 1.0
        ev_under = (p_under_model * under_odds) - 1.0

        total_impl = (1.0 / over_odds) + (1.0 / under_odds)
        if total_impl < 1.0:
            ev_over = ev_under = 0.0

        if abs(p_over_model - p_over_mkt) < 0.025:
            ev_over = min(ev_over, 0.0)
            ev_under = min(ev_under, 0.0)

        ev_over = clamp(ev_over, -0.99, 0.35)
        ev_under = clamp(ev_under, -0.99, 0.35)

        if ev_over > ev_under and ev_over > 0:
            pick, best_ev, p_pick = "OVER", ev_over, p_over_model
        elif ev_under > 0:
            pick, best_ev, p_pick = "UNDER", ev_under, p_under_model
        else:
            pick, best_ev, p_pick = "NO VALUE", max(ev_over, ev_under), max(p_over_model, p_under_model)

        updated.append({
            **row.to_dict(),
            "Calibrated Projection": round(proj, 2),
            "BM Offset Applied":     round(player_bm_offset, 2),
            "Proj De-vigged":        round(proj_devigged, 2),
            "Market P(Over)%":       round(p_over_mkt * 100.0, 2),
            "Market P(Under)%":      round(p_under_mkt * 100.0, 2),
            "Model Pick":            pick,
            "Pick Confidence %":     round(p_pick * 100.0, 2),
            "Best EV %":             round(best_ev * 100.0, 2),
            "Projection Edge":       round(proj - line_val, 2),
            "P(Over)%":              round(p_over_model * 100.0, 2),
            "P(Under)%":             round(p_under_model * 100.0, 2),
        })

    return pd.DataFrame(updated)


# ---------------------------------------------------------------------------
# Korak 3: rangiranje i filteri
# ---------------------------------------------------------------------------

def _score(df: pd.DataFrame) -> pd.DataFrame:
    df["EV_z"] = zscore(df["Best EV %"])
    df["EDGE_z"] = zscore(df["Projection Edge"])
    df["HIT_z"] = zscore(df["Pick Confidence %"])
    df["True Score"] = 0.50 * df["EV_z"] + 0.30 * df["EDGE_z"] + 0.20 * df["HIT_z"]
    return df.sort_values("True Score", ascending=False)


def rank_and_filter(df: pd.DataFrame, min_ev: float, only_positive: bool) -> pd.DataFrame:
    df = _score(df)
    df = df[df["Best EV %"] >= min_ev]
    if only_positive:
        df = df[df["Best EV %"] > 0]
    return df


# ---------------------------------------------------------------------------
# Korak 4: upozorenje na koncentraciju po timu + EV kazna
# ---------------------------------------------------------------------------

def apply_concentration_penalty(df: pd.DataFrame) -> Tuple[pd.DataFrame, ConcentrationInfo]:
    info = ConcentrationInfo()
    over_df = df[df["Model Pick"] == "OVER"].copy()
    team_over_counts = over_df.groupby("TEAM_ABBR").size()
    concentrated = team_over_counts[team_over_counts >= 3].index.tolist()
    if not concentrated:
        return df, info

    team_usg_sums = (over_df[over_df["TEAM_ABBR"].isin(concentrated)].groupby("TEAM_ABBR")["Usage %"].sum())
    penalty_map: Dict[Any, float] = {}
    for team in concentrated:
        for rank, idx in enumerate(df[(df["TEAM_ABBR"] == team) & (df["Model Pick"] == "OVER")].index.tolist()):
            if rank == 2:
                penalty_map[idx] = 0.85
            elif rank >= 3:
                penalty_map[idx] = 0.55
    if penalty_map:
        df = df.copy()
        df["Conc Penalty"] = 1.0
        for idx, mult in penalty_map.items():
            if idx in df.index:
                df.at[idx, "Conc Penalty"] = mult
        df["Best EV %"] = (df["Best EV %"] * df["Conc Penalty"]).round(2)
        df = _score(df)

    info.teams = list(concentrated)
    for team in concentrated:
        info.counts[team] = int(team_over_counts[team])
        info.usg_sums[team] = float(team_usg_sums.get(team, 0))
        info.players[team] = over_df[over_df["TEAM_ABBR"] == team]["Player"].tolist()
        info.penalized[team] = [df.at[i, "Player"] for i, m in penalty_map.items()
                                if m < 1.0 and i in df.index and df.at[i, "TEAM_ABBR"] == team]
    return df, info


# ---------------------------------------------------------------------------
# Sve zajedno
# ---------------------------------------------------------------------------

def run_analysis(offer_text: str, bundle: DataBundle, options: Optional[AnalysisOptions] = None) -> AnalysisResult:
    """Pokreni kompletnu analizu nad tekstom ponude. Nikad ne baca izuzetak zbog praznog rezultata —
    provjeri ``result.ok`` i ``result.message``."""
    options = options or AnalysisOptions()
    rows, bad = parse_offer_text(offer_text)
    inj_df = merge_injury_override(bundle.injuries, options.injury_override)
    empty = pd.DataFrame()
    if not rows:
        return AnalysisResult(empty, empty, rows, bad, [], [], None, ConcentrationInfo(),
                              injuries_used=inj_df, message="Nema validnih redova u ponudi.")

    projections, not_found, skipped, excluded_out, pairs = build_projections(rows, bundle, options, inj_df)
    is_today, today_matches = offer_freshness(pairs, options.schedule)
    extra = dict(excluded_out=excluded_out, offer_is_today=is_today, offer_today_matches=today_matches,
                 offer_matched_rows=len(pairs), auto_context=auto_context(pairs, options.schedule))
    if projections.empty:
        msg = ("Svi matchovani igrači su OUT ili im je meč već počeo." if pairs
               else "Nijedan igrač nije matchovan u sezonskoj bazi.")
        return AnalysisResult(empty, projections, rows, bad, not_found, skipped, None, ConcentrationInfo(),
                              injuries_used=inj_df, message=msg, **extra)

    bm_offset = compute_bm_offset(projections)
    df = run_monte_carlo(projections, options.mc_sims, bundle.league_pts_std, seed=options.seed)
    df = rank_and_filter(df, options.min_ev, options.only_positive)
    df, conc = apply_concentration_penalty(df)

    rf_count = 0
    if options.recent_form_override:
        rf_set = set(options.recent_form_override.keys())
        rf_count = int(df["Player"].apply(lambda x: normalize_name(x) in rf_set).sum())

    return AnalysisResult(df, projections, rows, bad, not_found, skipped, bm_offset, conc,
                          recent_form_count=rf_count, injuries_used=inj_df, **extra)


def analyze_offer_file(path, bundle: DataBundle, options: Optional[AnalysisOptions] = None) -> AnalysisResult:
    from .offer import read_offer_file
    return run_analysis(read_offer_file(path), bundle, options)


SUMMARY_COLUMNS = ["Player", "TEAM_ABBR", "OPP_TEAM", "Line", "Over Odds", "Under Odds",
                   "Final Projection", "Calibrated Projection", "Model Pick", "Pick Confidence %",
                   "Best EV %", "Projection Edge", "True Score"]


def summary_table(df: pd.DataFrame, top: Optional[int] = None) -> pd.DataFrame:
    cols = [c for c in SUMMARY_COLUMNS if c in df.columns]
    out = df[cols]
    return out.head(top) if top else out
