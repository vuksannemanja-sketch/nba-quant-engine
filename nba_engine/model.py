"""Model projekcije poena po igraču.

Sve formule su prenesene iz originalnog ``app.py`` bez izmjena vrijednosti i težina.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .utils import clamp, get_float, status_weight


# ---------------------------------------------------------------------------
# Matematičke pomoćne funkcije
# ---------------------------------------------------------------------------

def compute_per_player_bm_offset(season_pts: float) -> float:
    """Procjena koliko kladionica 'napuhuje' liniju u odnosu na sezonski prosjek igrača."""
    league_avg = 9.0
    base_offset = season_pts * 0.05
    regression_factor = 1.0 - 0.3 * max(0.0, (season_pts - league_avg) / max(season_pts, 1.0))
    return float(np.clip(base_offset * regression_factor, 0.2, 3.5))


def compute_max_edge(line_val: float, usg: float = 20.0, sigma: float = 6.0) -> float:
    """Maksimalno dozvoljeno odstupanje projekcije od linije."""
    base = np.clip(line_val * 0.16, 2.0, 7.0)
    usg_mult = np.clip(1.0 + 0.015 * (usg - 20.0), 0.85, 1.25)
    sigma_mult = np.clip(sigma / 6.0, 0.90, 1.20)
    return float(np.clip(base * usg_mult * sigma_mult, 2.0, 8.5))


def compute_injury_boost_v2(
    injured_usage_lost: float,
    injured_minutes_lost: float,
    player_usg: float,
    has_star_out: bool,
    star_usg_lost: float,
    player_position_score: float = 0.0,
    n_active_teammates: int = 8,
) -> float:
    """Povećanje projekcije zbog odsutnih saigrača (ograničeno po usage-u igrača)."""
    base = 1.0 + 0.0025 * injured_usage_lost + 0.0014 * injured_minutes_lost
    if player_position_score > 0.5:
        base = 1.0 + (base - 1.0) * (1.0 + 0.30 * player_position_score)
    elif player_position_score > 0.0:
        base = 1.0 + (base - 1.0) * (1.0 + 0.10 * player_position_score)
    else:
        base = 1.0 + (base - 1.0) * 0.40
    if has_star_out and star_usg_lost >= 25 and player_position_score > 0.3:
        base += 0.0004 * star_usg_lost * player_position_score
    if player_usg >= 28:
        return float(np.clip(base, 1.0, 1.03))
    if player_usg >= 22:
        return float(np.clip(base, 1.0, 1.06))
    return float(np.clip(base, 1.0, 1.10))


# ---------------------------------------------------------------------------
# Pretrage timova / igrača
# ---------------------------------------------------------------------------

def is_team_b2b(b2b_df: Optional[pd.DataFrame], team_abbr: str, game_date: str) -> bool:
    if b2b_df is None or not team_abbr or not game_date:
        return False
    mask = ((b2b_df["TEAM_ABBR"] == str(team_abbr).strip().upper()) &
            (b2b_df["GAME_DATE"] == str(game_date).strip()))
    row = b2b_df[mask]
    return bool(row["IS_B2B"].iloc[0]) if not row.empty else False


def find_team_row_by_abbr(teams_df: pd.DataFrame, abbr: str) -> Optional[pd.Series]:
    if not abbr or teams_df is None or teams_df.empty:
        return None
    abbr = str(abbr).strip().upper()
    if "TEAM_ABBR" in teams_df.columns:
        tr = teams_df[teams_df["TEAM_ABBR"].astype(str).str.upper() == abbr]
        if not tr.empty:
            return tr.iloc[0]
    return None


def estimate_match_total(
    team_row: Optional[pd.Series], opp_row: Optional[pd.Series],
    pace_game: Optional[float], teams_df: pd.DataFrame,
) -> Optional[float]:
    """Procjena ukupnog broja poena meča iz ofanzivnih/defanzivnih rejtinga i tempa."""
    if team_row is None or opp_row is None:
        return None
    league_off = float(pd.to_numeric(teams_df.get("OFF_RATING", pd.Series([115.0])), errors="coerce").dropna().mean() or 115.0)
    league_def = float(pd.to_numeric(teams_df.get("DEF_RATING", pd.Series([115.0])), errors="coerce").dropna().mean() or 115.0)
    if pace_game is None:
        pace_game = (get_float(team_row, "PACE", 99.0) + get_float(opp_row, "PACE", 99.0)) / 2.0
    team_off = get_float(team_row, "OFF_RATING", league_off)
    opp_off = get_float(opp_row, "OFF_RATING", league_off)
    team_def = get_float(team_row, "DEF_RATING", league_def)
    opp_def = get_float(opp_row, "DEF_RATING", league_def)
    team_pts = team_off * pace_game / 100.0 * clamp(league_def / max(opp_def, 1e-6), 0.92, 1.08)
    opp_pts = opp_off * pace_game / 100.0 * clamp(league_def / max(team_def, 1e-6), 0.92, 1.08)
    return float(clamp(team_pts + opp_pts, 180.0, 265.0))


def _best_row(pr: pd.DataFrame) -> pd.Series:
    return pr.sort_values(["MIN", "GP"], ascending=False, na_position="last").iloc[0]


def match_player_row(players_df: pd.DataFrame, offer_name: str) -> Tuple[Optional[pd.Series], str, str]:
    """Pronađi igrača iz ponude u bazi. Vraća (red, upotrijebljeni ključ, metoda).

    Metode po redu: EXACT, LAST_FIRST ('Prezime, Ime'), INITIAL_LAST ('L. James'),
    TOKENS (svi dijelovi imena), DIFFLIB (slično ime), NOT_FOUND.
    """
    from .utils import normalize_name  # lokalni import izbjegava kružnu zavisnost pri testiranju

    name_raw = str(offer_name or "").strip()
    key = normalize_name(name_raw)
    if not key:
        return None, key, "EMPTY_KEY"
    pr = players_df[players_df["NAME_KEY"] == key]
    if not pr.empty:
        return _best_row(pr), key, "EXACT"
    if "," in name_raw:
        key2 = normalize_name(" ".join(p.strip() for p in name_raw.split(",")[::-1]))
        pr = players_df[players_df["NAME_KEY"] == key2]
        if not pr.empty:
            return _best_row(pr), key2, "LAST_FIRST"
    toks = key.split()
    if len(toks) == 2 and len(toks[0]) == 1:
        fi, ln = toks
        pr = players_df[
            players_df["NAME_KEY"].str.contains(rf"\b{re.escape(ln)}\b", na=False) &
            players_df["NAME_KEY"].str.contains(rf"\b{re.escape(fi)}", na=False)]
        if not pr.empty:
            return _best_row(pr), key, "INITIAL_LAST"
    toks = [t for t in key.split() if len(t) >= 3]
    if toks:
        mask = np.ones(len(players_df), dtype=bool)
        for t in toks:
            mask &= players_df["NAME_KEY"].str.contains(re.escape(t), na=False).to_numpy()
        pr = players_df[mask]
        if not pr.empty:
            return _best_row(pr), key, "TOKENS"
    all_keys = players_df["NAME_KEY"].dropna().astype(str).tolist()
    best = difflib.get_close_matches(key, all_keys, n=1, cutoff=0.86)
    if best:
        pr = players_df[players_df["NAME_KEY"] == best[0]]
        if not pr.empty:
            return _best_row(pr), best[0], "DIFFLIB"
    return None, key, "NOT_FOUND"


# ---------------------------------------------------------------------------
# Glavna projekcija
# ---------------------------------------------------------------------------

def build_player_context(
    r0: pd.Series,
    players_df: pd.DataFrame,
    teams_df: pd.DataFrame,
    team_row: Optional[pd.Series],
    opp_row: Optional[pd.Series],
    inj_df: Optional[pd.DataFrame],
    team_abbr: Any,
    player_name_key: str,
    total_match_used: Optional[float],
    recent_form_override: Optional[Dict[str, float]] = None,
    h2h_df: Optional[pd.DataFrame] = None,
    opp_team_abbr: Optional[str] = None,
    l10_df: Optional[pd.DataFrame] = None,
    def_matchup_df: Optional[pd.DataFrame] = None,
    off_matchup_df: Optional[pd.DataFrame] = None,
    line_val: float = 0.0,
    b2b_team: bool = False,
    b2b_opp: bool = False,
    is_home: bool = True,
    rest_days: int = 2,
    opp_rest_days: int = 2,
    use_l10_minutes: bool = False,   # minute: sezonski prosjek dopunjen minutama iz zadnjih 10 utakmica
    use_l10_sigma: bool = False,     # rasipanje: formula dopunjena stvarnim rasipanjem iz zadnjih 10 utakmica
) -> Dict[str, Any]:
    """Izračunaj projekciju poena i sve faktore za jednog igrača.

    Napomena: ``off_matchup_df`` se prima radi kompatibilnosti, ali ga model (kao ni original) ne koristi.
    """
    if recent_form_override is None:
        recent_form_override = {}

    season_pts = float(get_float(r0, "PTS", 0.0) or 0.0)
    season_min = float(get_float(r0, "MIN", 0.0) or 0.0)
    usg = float(get_float(r0, "USG_PCT", np.nan) or np.nan)
    ppm = float(get_float(r0, "PPM", np.nan) or np.nan)
    if not np.isfinite(ppm) or ppm <= 0:
        ppm = season_pts / max(season_min, 1.0)
    if season_min < 20 and np.isfinite(ppm) and ppm > 0.60:
        ppm = 0.60 * ppm + 0.40 * 0.55

    def _league(df, col, fb):
        return float(pd.to_numeric(df.get(col, pd.Series([fb])), errors="coerce").dropna().mean() or fb)

    league_pace = _league(teams_df, "PACE", 99.0)
    league_def = _league(teams_df, "DEF_RATING", 115.0)
    league_off = _league(teams_df, "OFF_RATING", 115.0)
    league_total_proxy = league_off * 2.0
    league_ts = _league(players_df, "TS_PCT", 0.56)
    league_efg = _league(players_df, "EFG_PCT", 0.54)
    league_usg = _league(players_df, "USG_PCT", 20.0)
    league_fga_pm = _league(players_df, "FGA_PM", 0.35)
    league_fta_pm = _league(players_df, "FTA_PM", 0.12)
    if league_usg < 5.0:
        league_usg *= 100.0

    team_pace = get_float(team_row, "PACE", league_pace) if team_row is not None else league_pace
    opp_pace = get_float(opp_row, "PACE", league_pace) if opp_row is not None else league_pace
    pace_game = (team_pace + opp_pace) / 2.0 if opp_row is not None else team_pace
    pace_factor = clamp(1.0 + 0.08 * (pace_game / league_pace - 1.0), 0.94, 1.07)

    team_off = get_float(team_row, "OFF_RATING", league_off) if team_row is not None else league_off
    opp_def = get_float(opp_row, "DEF_RATING", league_def) if opp_row is not None else league_def
    team_eff_matchup = clamp((team_off / league_off) * (league_def / max(opp_def, 1e-6)), 0.94, 1.08)

    total_factor = 1.0
    if total_match_used is not None and np.isfinite(total_match_used):
        total_factor = clamp(1.0 + 0.25 * (float(total_match_used) / league_total_proxy - 1.0), 0.90, 1.12)

    gp = get_float(r0, "GP", 20.0)

    # Minute: sezonski prosjek, po želji dopunjen minutama iz zadnjih 10 utakmica (L10_MIN).
    # Težina L10 raste sa brojem utakmica u formi: 0,12 po utakmici, najviše 0,60 (od 5 utakmica).
    l10_min_val = l10_std_val = None
    l10_games_val = 0.0
    if l10_df is not None and "NAME_KEY" in l10_df.columns and (use_l10_minutes or use_l10_sigma):
        _l10_early = l10_df[l10_df["NAME_KEY"] == player_name_key]
        if not _l10_early.empty:
            _re = _l10_early.iloc[0]
            l10_min_val = get_float(_re, "L10_MIN", None)
            l10_std_val = get_float(_re, "L10_STD", None)
            l10_games_val = float(get_float(_re, "GAMES_PLAYED", 0.0) or 0.0)
    minutes_base = season_min
    l10_min_weight = 0.0
    if (use_l10_minutes and l10_min_val is not None and np.isfinite(l10_min_val) and l10_min_val > 0
            and season_min > 0):
        l10_min_weight = clamp(0.12 * (l10_games_val if l10_games_val > 0 else 10.0), 0.0, 0.60)
        minutes_base = (1.0 - l10_min_weight) * season_min + l10_min_weight * float(l10_min_val)
    minutes_proj = minutes_base

    team_net = get_float(team_row, "NET_RATING", 0.0) if team_row is not None else 0.0
    opp_net = get_float(opp_row, "NET_RATING", 0.0) if opp_row is not None else 0.0
    mins_context = clamp(1.0 - 0.012 * abs((team_net or 0) - (opp_net or 0)) / 10.0, 0.97, 1.02)

    injury_boost = direct_player_penalty = 1.0
    injured_usage_lost = injured_minutes_lost = 0.0
    self_status = None  # status samog igrača na listi ozljeda (OUT, QUESTIONABLE...), None ako nije na listi

    if inj_df is not None and team_abbr:
        team_inj = inj_df[inj_df["TEAM_ABBR"].astype(str).str.upper() == str(team_abbr).upper()].copy()
        if not team_inj.empty:
            team_inj["W"] = team_inj["STATUS"].astype(str).map(status_weight).fillna(0.0)
            if "NAME_KEY" in team_inj.columns:
                self_row = team_inj[team_inj["NAME_KEY"] == player_name_key]
                if not self_row.empty:
                    self_status = str(self_row["STATUS"].iloc[0]).upper().strip()
                    direct_player_penalty = {
                        "OUT": 0.0, "INACTIVE": 0.0, "DOUBTFUL": 0.75,
                        "QUESTIONABLE": 0.92, "PROBABLE": 0.97,
                    }.get(self_status, 1.0)
            teammate_inj = team_inj[team_inj["NAME_KEY"] != player_name_key] \
                if "NAME_KEY" in team_inj.columns else team_inj
            if not teammate_inj.empty and "NAME_KEY" in teammate_inj.columns:
                teammate_pool = players_df[players_df["NAME_KEY"].isin(teammate_inj["NAME_KEY"])]
                if not teammate_pool.empty:
                    temp = teammate_pool[["NAME_KEY", "USG_PCT", "MIN"]].copy().merge(
                        teammate_inj[["NAME_KEY", "W"]], on="NAME_KEY", how="left")
                    injured_usage_lost = float((temp["USG_PCT"].fillna(0) * temp["W"].fillna(0)).sum())
                    injured_minutes_lost = float((temp["MIN"].fillna(0) * temp["W"].fillna(0)).sum())
                    if injured_minutes_lost > 200:
                        gp_avg = pd.to_numeric(players_df.get("GP", pd.Series([40])), errors="coerce").dropna().mean() or 40
                        injured_minutes_lost /= max(gp_avg, 1)
                    injured_minutes_lost = min(injured_minutes_lost, 95.0)
                    injured_usage_lost = min(injured_usage_lost, 62.0)

                    out_inj = team_inj[team_inj["STATUS"].astype(str).str.upper() == "OUT"]
                    has_star_out = False
                    star_usg_lost = 0.0
                    if not out_inj.empty and "NAME_KEY" in out_inj.columns:
                        star_pool = players_df[
                            players_df["NAME_KEY"].isin(out_inj["NAME_KEY"]) &
                            (pd.to_numeric(players_df["USG_PCT"], errors="coerce") >= 28)]
                        if not star_pool.empty:
                            has_star_out = True
                            star_usg_lost = float(star_pool["USG_PCT"].sum())

                    player_position_score = 0.0
                    if not out_inj.empty and "NAME_KEY" in out_inj.columns:
                        out_players = players_df[players_df["NAME_KEY"].isin(out_inj["NAME_KEY"])].copy()
                        cur_usg = usg if np.isfinite(usg) else 20.0
                        for _, op in out_players.iterrows():
                            out_usg = float(get_float(op, "USG_PCT", 0) or 0)
                            out_min = float(get_float(op, "MIN", 0) or 0)
                            usg_sim = max(0.0, 1.0 - abs(cur_usg - out_usg) / max(out_usg, 1.0))
                            min_sim = max(0.0, 1.0 - abs(season_min - out_min) / max(out_min, 1.0))
                            player_position_score = max(player_position_score, 0.65 * usg_sim + 0.35 * min_sim)
                        player_position_score = float(np.clip(player_position_score, 0.0, 1.0))

                    injury_boost = compute_injury_boost_v2(
                        injured_usage_lost, injured_minutes_lost,
                        usg if np.isfinite(usg) else 20.0,
                        has_star_out, star_usg_lost,
                        player_position_score=player_position_score,
                        n_active_teammates=max(1, 8 - len(out_inj)),
                    )

    minutes_proj = minutes_proj * mins_context * pace_factor * direct_player_penalty
    minutes_proj *= clamp(1.0 + 0.0004 * injured_minutes_lost, 0.99, 1.04)
    minutes_proj = clamp(minutes_proj, 8.0, 40.0)
    cap_pct = {34: 1.02, 28: 1.04, 20: 1.06}   # gornja granica u odnosu na osnovu minuta (bez L10 = sezonski prosjek)
    for threshold, cap in cap_pct.items():
        if minutes_base >= threshold:
            minutes_proj = min(minutes_proj, minutes_base * cap)
            break
    else:
        minutes_proj = min(minutes_proj, minutes_base * 1.10)
    minutes_proj = clamp(minutes_proj, 8.0, 40.0)

    usage_factor = clamp(
        1.0 + 0.15 * ((usg - league_usg) / league_usg) if np.isfinite(usg) and league_usg > 0 else 1.0,
        0.85, 1.15)

    ts = get_float(r0, "TS_PCT", league_ts)
    efg = get_float(r0, "EFG_PCT", league_efg)
    fg_pct = get_float(r0, "FG_PCT", 0.46)
    ft_pct = get_float(r0, "FT_PCT", 0.76)
    fg3_pct = get_float(r0, "FG3_PCT", 0.36)
    fga_pm = get_float(r0, "FGA_PM", league_fga_pm)
    fta_pm = get_float(r0, "FTA_PM", league_fta_pm)
    pie = get_float(r0, "PIE", 0.08)
    ast_ratio = get_float(r0, "AST_RATIO", 15.0)
    ast_to = get_float(r0, "AST_TO", 1.5)
    tov_pct = get_float(r0, "TOV_PCT", get_float(r0, "TM_TOV_PCT", 12.0))
    net_rating_player = get_float(r0, "NET_RATING", 0.0)
    plus_minus = get_float(r0, "PLUS_MINUS", 0.0)
    fg3a_raw = get_float(r0, "FG3A", None)
    fg3a_pm = get_float(r0, "FG3A_PM", None)
    if fg3a_pm is None or not np.isfinite(fg3a_pm):
        fg3a_pm = (fg3a_raw / season_min) if (fg3a_raw and np.isfinite(fg3a_raw) and season_min > 0) else 0.12

    shot_factor = clamp(1.0 + 0.10 * ((fga_pm - league_fga_pm) / max(league_fga_pm, 1e-6)), 0.92, 1.10)
    ft_pct_adj = clamp((ft_pct - 0.76) * 0.05, -0.03, 0.05) if ft_pct and np.isfinite(ft_pct) else 0.0
    ft_factor = clamp(1.0 + 0.08 * ((fta_pm - league_fta_pm) / max(league_fta_pm, 1e-6)) + ft_pct_adj, 0.94, 1.10)
    fg3_adj = clamp((fg3_pct - 0.36) * 0.08, -0.03, 0.04) if fg3_pct and np.isfinite(fg3_pct) else 0.0
    efficiency_factor = clamp(
        1.0 + 0.10 * ((ts - league_ts) / max(league_ts, 1e-6))
        + 0.06 * ((efg - league_efg) / max(league_efg, 1e-6))
        + 0.02 * (fg_pct - 0.46) + fg3_adj, 0.92, 1.12)
    playmaking_factor = clamp(1.0 + 0.012 * ((ast_ratio - 15.0) / 5.0) + 0.008 * (ast_to - 1.5), 0.97, 1.04)
    turnover_factor = clamp(1.0 - 0.035 * ((tov_pct - 12.0) / 12.0), 0.95, 1.04)
    net_adj = clamp(net_rating_player / 10.0, -0.03, 0.03) if net_rating_player and np.isfinite(net_rating_player) \
        else clamp(plus_minus / 40.0, -0.02, 0.02)
    role_factor = clamp(1.0 + 0.15 * (pie - 0.08) + net_adj, 0.93, 1.07)

    pts_paint = get_float(r0, "PTS_PAINT", None)
    pts_fb = get_float(r0, "PTS_FB", None)
    pts_2nd = get_float(r0, "PTS_2ND_CHANCE", None)
    pts_off_tov = get_float(r0, "PTS_OFF_TOV", None)
    league_pts_paint = _league(players_df, "PTS_PAINT", 4.5)
    league_pts_fb = _league(players_df, "PTS_FB", 1.5)
    league_pts_2nd = _league(players_df, "PTS_2ND_CHANCE", 1.2)
    league_pts_off_tov = _league(players_df, "PTS_OFF_TOV", 2.5)

    def _rel_adj(val, lg, w, lo, hi):
        return clamp(w * ((val - lg) / lg), lo, hi) if val is not None and np.isfinite(val) and lg > 0 else 0.0

    style_factor = clamp(
        1.0 + 0.012 * ((fg3a_pm - 0.12) / 0.10)
        + _rel_adj(pts_paint, league_pts_paint, 0.015, -0.02, 0.02)
        + _rel_adj(pts_fb, league_pts_fb, 0.010, -0.01, 0.015)
        + _rel_adj(pts_2nd, league_pts_2nd, 0.008, -0.01, 0.012)
        + _rel_adj(pts_off_tov, league_pts_off_tov, 0.007, -0.01, 0.010), 0.95, 1.06)

    opp_shooting_adj = 1.0
    opp_fg_pct = opp_fg3_pct = None
    if def_matchup_df is not None and opp_team_abbr is not None:
        try:
            dm = def_matchup_df[def_matchup_df["TEAM_ABBR"].astype(str).str.upper() == str(opp_team_abbr).upper()]
            if not dm.empty:
                opp_fg_pct = float(dm["OPP_FG_PCT"].iloc[0]) if "OPP_FG_PCT" in dm.columns else None
                opp_fg3_pct = float(dm["OPP_FG3_PCT"].iloc[0]) if "OPP_FG3_PCT" in dm.columns else None
        except Exception:
            pass
    if opp_fg_pct is not None:
        opp_shooting_adj *= clamp(1.0 + 0.05 * ((opp_fg_pct - 0.470) / 0.470), 0.97, 1.03)
    if opp_fg3_pct is not None:
        opp_shooting_adj *= clamp(1.0 + 0.03 * ((opp_fg3_pct - 0.360) / 0.360), 0.98, 1.02)

    opp_pts_off_tov_p = get_float(r0, "OPP_PTS_OFF_TOV", None)
    opp_pts_2nd_p = get_float(r0, "OPP_PTS_2ND_CHANCE", None)
    opp_pts_fb_p = get_float(r0, "OPP_PTS_FB", None)
    opp_pts_paint_p = get_float(r0, "OPP_PTS_PAINT", None)
    league_opp_pts_paint = _league(players_df, "OPP_PTS_PAINT", 4.5)
    league_opp_pts_fb = _league(players_df, "OPP_PTS_FB", 1.5)
    league_opp_pts_2nd = _league(players_df, "OPP_PTS_2ND_CHANCE", 1.2)

    def _sma(pv, pl, ov, ol, w, lo, hi):
        if pv is not None and np.isfinite(pv) and pv > 0 and ov is not None and np.isfinite(ov) and ol > 0:
            return clamp(w * ((pv - pl) / max(pl, 1e-6)) * np.sign((ov - ol) / max(ol, 1e-6)), lo, hi)
        return 0.0

    opp_style_matchup = clamp(
        1.0 + _sma(pts_paint, league_pts_paint, opp_pts_paint_p, league_opp_pts_paint, 0.015, -0.015, 0.015)
        + _sma(pts_fb, league_pts_fb, opp_pts_fb_p, league_opp_pts_fb, 0.010, -0.010, 0.010)
        + _sma(pts_2nd, league_pts_2nd, opp_pts_2nd_p, league_opp_pts_2nd, 0.008, -0.008, 0.008),
        0.96, 1.04)

    base_raw = ppm * minutes_proj
    season_anchor = season_pts * (minutes_proj / max(season_min, 1.0)) if season_min > 0 else base_raw
    star_w = clamp((usg - 24.0) / 16.0 if np.isfinite(usg) else 0.15, 0.12, 0.40)
    anchored_projection = (1.0 - star_w) * base_raw + star_w * season_anchor
    if season_pts > 0:
        anchored_projection = clamp(anchored_projection, season_pts * 0.70, season_pts * 1.30)

    # DEF matchup blok 1
    def_factor_b1 = 1.0
    if def_matchup_df is not None and opp_team_abbr is not None:
        try:
            pts_col = next((c for c in ("OPP_PTS", "PTS", "FREQ_PTS") if c in def_matchup_df.columns), None)
            if "TEAM_ABBR" in def_matchup_df.columns and pts_col:
                dm = def_matchup_df[def_matchup_df["TEAM_ABBR"].astype(str).str.upper() == str(opp_team_abbr).upper()]
                if not dm.empty:
                    opp_pts_a = float(dm[pts_col].iloc[0])
                    lg_avg = float(def_matchup_df[pts_col].mean())
                    if lg_avg > 0:
                        def_factor_b1 = clamp(opp_pts_a / lg_avg, 0.90, 1.12)
        except Exception:
            pass
    if def_factor_b1 == 1.0 and opp_def is not None and np.isfinite(opp_def) and league_def > 0:
        def_factor_b1 = 1.0 + 0.60 * (clamp(opp_def / league_def, 0.92, 1.10) - 1.0)
    anchored_projection *= def_factor_b1

    # L10/L5/L3 forma
    l10_pts = l10_trend = l5_pts = l3_pts = None
    if l10_df is not None and "NAME_KEY" in l10_df.columns:
        l10_row = l10_df[l10_df["NAME_KEY"] == player_name_key]
        if not l10_row.empty:
            r = l10_row.iloc[0]
            l10_pts = float(get_float(r, "L10_PTS", None) or 0) or None
            l5_pts = float(get_float(r, "L5_PTS", None) or 0) or None
            l3_pts = float(get_float(r, "L3_PTS", None) or 0) or None
            l10_trend = float(get_float(r, "TREND_SLOPE", None) or 0.0)

    if l10_pts is not None and l10_pts > 0:
        if l3_pts and l3_pts > 0:
            d35 = abs(l3_pts - (l5_pts or l10_pts))
            effective_form = (0.50 * l3_pts + 0.35 * (l5_pts or l10_pts) + 0.15 * l10_pts if d35 < 4.0
                              else 0.30 * l3_pts + 0.50 * (l5_pts or l10_pts) + 0.20 * l10_pts)
        elif l5_pts and l5_pts > 0:
            d = abs(l5_pts - l10_pts)
            effective_form = (0.72 * l5_pts + 0.28 * l10_pts if d > 4.0 else
                              0.65 * l5_pts + 0.35 * l10_pts if d > 2.0 else 0.55 * l5_pts + 0.45 * l10_pts)
        else:
            effective_form = l10_pts
        form_diff = abs(effective_form - season_pts)
        form_consist = (l5_pts is not None and l10_pts is not None and (
            (l5_pts > season_pts and l10_pts > season_pts) or (l5_pts < season_pts and l10_pts < season_pts)))
        if form_diff > 6.0:
            fw = 0.88 if form_consist else 0.82
        elif form_diff > 4.0:
            fw = 0.80 if form_consist else 0.74
        elif form_diff > 2.0:
            fw = 0.70 if form_consist else 0.64
        else:
            fw = 0.58
        form_anchor = effective_form * (minutes_proj / max(season_min, 1.0))
        anchored_projection = (1.0 - fw) * anchored_projection + fw * form_anchor
        if l10_trend is not None and abs(l10_trend) > 0.50:
            trend_adj = clamp(1.0 + 0.018 * l10_trend, 0.93 if form_consist else 0.95, 1.07 if form_consist else 1.05)
            anchored_projection *= trend_adj

    if (l5_pts and l10_pts and line_val > 0 and direct_player_penalty > 0.5
            and l5_pts > line_val * 1.05 and l10_pts > line_val * 1.05):
        floor_p = line_val * 0.85
        if anchored_projection < floor_p:
            anchored_projection = (anchored_projection + floor_p) / 2.0

    # DEF matchup blok 2
    def_factor_b2 = 1.0
    if def_matchup_df is not None and opp_team_abbr is not None:
        try:
            pos_col = next((c for c in ("POSITION", "PLAYER_POSITION", "POS") if c in def_matchup_df.columns), None)
            pts_col2 = next((c for c in ("FREQ_PTS", "PTS_PCT", "PTS", "FGA") if c in def_matchup_df.columns), None)
            if pos_col and pts_col2 and "TEAM_ABBR" in def_matchup_df.columns:
                pg = ("Guard" if np.isfinite(usg) and usg >= 30 else
                      "Forward" if np.isfinite(usg) and usg >= 26 else
                      "Forward" if season_min >= 28 else "Center")
                dm = def_matchup_df[
                    (def_matchup_df["TEAM_ABBR"].astype(str).str.upper() == str(opp_team_abbr).upper()) &
                    (def_matchup_df[pos_col].astype(str).str.contains(pg, case=False, na=False))]
                if not dm.empty:
                    val = float(dm[pts_col2].iloc[0])
                    avg = float(def_matchup_df[def_matchup_df[pos_col].astype(str).str.contains(pg, case=False, na=False)][pts_col2].mean()) or val
                    if avg > 0:
                        def_factor_b2 = clamp(val / avg, 0.88, 1.14)
            if def_factor_b2 == 1.0 and "TEAM_ABBR" in def_matchup_df.columns:
                efg_col = next((c for c in ("EFG_PCT", "FG_PCT", "FG2_PCT") if c in def_matchup_df.columns), None)
                if efg_col:
                    dm = def_matchup_df[def_matchup_df["TEAM_ABBR"].astype(str).str.upper() == str(opp_team_abbr).upper()]
                    if not dm.empty:
                        oe = float(dm[efg_col].mean())
                        le = float(def_matchup_df[efg_col].mean())
                        if le > 0 and oe > 0:
                            def_factor_b2 = clamp(oe / le, 0.92, 1.10)
        except Exception:
            pass
    anchored_projection *= clamp(def_factor_b2, 0.90, 1.10)
    def_matchup_factor = round(clamp(def_factor_b1 * def_factor_b2, 0.85, 1.20), 4)

    # Recent Form
    recent_pts = recent_form_override.get(player_name_key)
    is_auto_form = False
    if recent_pts is None and l5_pts and l5_pts > 0:
        recent_pts = l5_pts
        is_auto_form = True
    if recent_pts and recent_pts > 0:
        diff = abs(recent_pts - season_pts)
        rw = (0.18 if diff > 5 else 0.10) if is_auto_form else (0.85 if diff > 5 else 0.75)
        anchored_projection = (1.0 - rw) * anchored_projection + rw * recent_pts * (minutes_proj / max(season_min, 1.0))

    # H2H
    h2h_pts = h2h_pts_last = None
    h2h_games = 0
    h2h_sigma_boost = 1.0
    if h2h_df is not None and opp_team_abbr is not None:
        mask = (h2h_df["NAME_KEY"] == player_name_key) & \
               (h2h_df["OPP_TEAM"].astype(str).str.upper() == str(opp_team_abbr).upper())
        h2h_row = h2h_df[mask]
        if not h2h_row.empty:
            h2h_pts = float(get_float(h2h_row.iloc[0], "H2H_PTS_AVG", None) or 0) or None
            h2h_games = int(get_float(h2h_row.iloc[0], "H2H_GAMES", 0) or 0)
            h2h_pts_last = float(get_float(h2h_row.iloc[0], "H2H_PTS_LAST", None) or 0) or None
    h2h_display_pts = h2h_pts if (h2h_pts and h2h_games > 0) else (round(season_pts, 1) if season_pts > 0 else None)
    if h2h_pts and h2h_pts > 0 and h2h_games >= 2:
        h2h_anchor = h2h_pts * (minutes_proj / max(season_min, 1.0))
        h2h_diff = abs(h2h_pts - season_pts)
        h2h_weight = clamp(0.15 + 0.06 * h2h_games, 0.25, 0.45)
        if recent_pts is None or is_auto_form:
            h2h_weight = clamp(h2h_weight * 1.4, 0.25, 0.55)
        if season_pts > 0:
            hr = h2h_pts / max(season_pts, 1.0)
            if hr > 2.0:
                h2h_weight = 0.0
            elif hr > 1.5:
                h2h_weight = min(h2h_weight, 0.08)
            elif hr > 1.3:
                h2h_weight = min(h2h_weight, 0.15)
            elif hr < 0.5:
                h2h_weight = min(h2h_weight, 0.08)
            elif hr < 0.7:
                h2h_weight = min(h2h_weight, 0.15)
        if l5_pts and l5_pts > 0 and h2h_weight > 0 and abs(h2h_pts - l5_pts) < 3.0:
            h2h_weight = min(h2h_weight * 1.2, 0.55)
        if h2h_weight > 0:
            anchored_projection = (1.0 - h2h_weight) * anchored_projection + h2h_weight * h2h_anchor
        h2h_sigma_boost = 1.08 if h2h_diff > 6 else 1.0

    # B2B faktor
    b2b_factor = 1.0
    if b2b_team:
        cur_usg = usg if np.isfinite(usg) else 20.0
        if cur_usg >= 28:
            minutes_proj *= 0.94
            b2b_factor = 0.94
        elif cur_usg >= 22:
            minutes_proj *= 0.97
            b2b_factor = 0.97
        else:
            if not is_home:
                minutes_proj *= 0.99
                b2b_factor = 0.99
            else:
                minutes_proj *= 1.02
                b2b_factor = 1.02
        minutes_proj = clamp(minutes_proj, 8.0, 40.0)
    if b2b_opp:
        b2b_factor = clamp(b2b_factor * 1.02, 0.90, 1.10)

    # Home/Away faktor
    if is_home:
        home_away_factor = 1.02
    else:
        home_away_factor = 0.975 if b2b_team else 0.985

    # Rest Days faktor
    rest_factor = 1.0
    if rest_days == 1:
        rest_factor = 0.98 if (usg if np.isfinite(usg) else 20.0) >= 25 else 1.0
    elif rest_days >= 3:
        rest_factor = clamp(1.0 + 0.005 * min(rest_days - 2, 3), 1.0, 1.015)
    opp_rest_factor = (1.02 if opp_rest_days == 0 else 1.01 if opp_rest_days == 1 else 1.0)

    mult = clamp(
        1.0
        + 0.22 * (team_eff_matchup - 1.0)
        + 0.16 * (total_factor - 1.0)
        + 0.14 * (usage_factor - 1.0)
        + 0.10 * (injury_boost - 1.0)
        + 0.13 * (shot_factor - 1.0)
        + 0.10 * (ft_factor - 1.0)
        + 0.13 * (efficiency_factor - 1.0)
        + 0.05 * (playmaking_factor - 1.0)
        + 0.07 * (turnover_factor - 1.0)
        + 0.07 * (role_factor - 1.0)
        + 0.04 * (style_factor - 1.0)
        + 0.05 * (opp_shooting_adj - 1.0)
        + 0.04 * (opp_style_matchup - 1.0)
        + 0.08 * (b2b_factor - 1.0)
        + 0.06 * (home_away_factor - 1.0)
        + 0.04 * (rest_factor - 1.0)
        + 0.03 * (opp_rest_factor - 1.0),
        0.88, 1.12)

    final_projection = float(clamp(anchored_projection * mult, 0.0, 70.0))
    if line_val > 0:
        final_projection = float(clamp(final_projection, line_val * 0.55, line_val * 1.45))

    cv_base = clamp(0.38 - 0.004 * (usg - 20.0), 0.30, 0.46) if np.isfinite(usg) else 0.38
    sigma = float(final_projection) * cv_base
    sigma += 0.5 * clamp(abs(minutes_proj - season_min) / max(season_min, 8.0), 0.0, 1.0)
    sigma_l10_weight = 0.0
    if use_l10_sigma and l10_std_val is not None and np.isfinite(l10_std_val) and l10_std_val > 0:
        # stvarno rasipanje igrača u zadnjih 10 utakmica: 0,10 težine po utakmici, najviše 0,50
        sigma_l10_weight = clamp(0.10 * (l10_games_val if l10_games_val > 0 else 10.0), 0.0, 0.50)
        sigma = (1.0 - sigma_l10_weight) * sigma + sigma_l10_weight * float(l10_std_val)
    if line_val > 0:
        sigma = min(sigma, line_val * (0.52 if np.isfinite(usg) and usg >= 28 else 0.48))
    sigma = float(clamp(sigma, max(line_val * 0.28, 2.0) if line_val > 0 else 2.0, 13.0))
    if h2h_sigma_boost > 1.0:
        sigma = float(clamp(sigma * h2h_sigma_boost, 5.0, 14.0))
    if recent_pts is not None and not is_auto_form:
        sigma = float(clamp(sigma * 0.90, 4.0, 10.0))

    return {
        "season_pts": season_pts, "season_min": season_min, "usg": usg, "ppm": ppm,
        "minutes_proj": minutes_proj, "pace_game": pace_game,
        "team_eff_matchup": team_eff_matchup, "opp_def": opp_def,
        "total_factor": total_factor, "injury_boost": injury_boost,
        "direct_player_penalty": direct_player_penalty,
        "injury_status": self_status,
        "minutes_base": minutes_base, "l10_min": l10_min_val, "l10_min_weight": l10_min_weight,
        "l10_std": l10_std_val, "sigma_l10_weight": sigma_l10_weight,
        "usage_factor": usage_factor, "shot_factor": shot_factor,
        "ft_factor": ft_factor, "efficiency_factor": efficiency_factor,
        "playmaking_factor": playmaking_factor, "turnover_factor": turnover_factor,
        "role_factor": role_factor, "style_factor": style_factor,
        "star_w": star_w, "season_anchor": season_anchor,
        "base_projection": anchored_projection,
        "final_projection": final_projection, "sigma": sigma,
        "injured_usage_lost": injured_usage_lost, "injured_minutes_lost": injured_minutes_lost,
        "pie": pie, "ast_ratio": ast_ratio,
        "recent_form_used": None if is_auto_form else recent_pts,
        "h2h_pts": h2h_display_pts, "h2h_games": h2h_games, "h2h_pts_last": h2h_pts_last,
        "l10_pts": l10_pts, "l5_pts": l5_pts, "l10_trend": l10_trend,
        "def_matchup_factor": def_matchup_factor, "opp_style_matchup": opp_style_matchup,
        "b2b_factor": b2b_factor, "home_away_factor": home_away_factor,
        "rest_factor": rest_factor, "opp_rest_factor": opp_rest_factor,
        "is_home": is_home, "rest_days": rest_days,
    }
