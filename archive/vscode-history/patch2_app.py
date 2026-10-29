"""
patch2_app.py — Fix za:
  1. build_player_context poziv (nedostaju h2h_df, l10_df, matchup_df, opp_team_abbr)
  2. nba_api 1.11.4 parametri (per_mode_simple → per_mode_detailed)
  3. DEF/OFF matchup - koristi LeagueDashTeamStats umjesto pt endpoint

Pokreni: python patch2_app.py
"""

import os, re, shutil
from datetime import datetime

APP_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
BACKUP_PATH = APP_PATH.replace("app.py", f"app_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")

if not os.path.exists(APP_PATH):
    print(f"❌ app.py nije pronađen: {APP_PATH}")
    exit(1)

shutil.copy2(APP_PATH, BACKUP_PATH)
print(f"✅ Backup: {os.path.basename(BACKUP_PATH)}")

with open(APP_PATH, encoding="utf-8") as f:
    content = f.read()

patches_applied = []
patches_skipped = []

# ─────────────────────────────────────────────────────────────
# PATCH H — build_player_context poziv (dodaj h2h_df, opp_team_abbr, l10_df, matchup)
# ─────────────────────────────────────────────────────────────
OLD_CALL = """    ctx = build_player_context(
        r0=r0, players_df=players_df, teams_df=teams_df,
        team_row=team_row, opp_row=opp_row, inj_df=inj_df,
        team_abbr=team_abbr, player_name_key=used_key,
        total_match_used=total_match_used,
        recent_form_override=recent_form_override,
    )"""

NEW_CALL = """    ctx = build_player_context(
        r0=r0, players_df=players_df, teams_df=teams_df,
        team_row=team_row, opp_row=opp_row, inj_df=inj_df,
        team_abbr=team_abbr, player_name_key=used_key,
        total_match_used=total_match_used,
        recent_form_override=recent_form_override,
        h2h_df=h2h_df, opp_team_abbr=opp_team_abbr,
        l10_df=l10_df if 'l10_df' in dir() else None,
        def_matchup_df=def_matchup_df if 'def_matchup_df' in dir() else None,
        off_matchup_df=off_matchup_df if 'off_matchup_df' in dir() else None,
    )"""

if "l10_df=l10_df" not in content:
    if OLD_CALL in content:
        content = content.replace(OLD_CALL, NEW_CALL)
        patches_applied.append("H — build_player_context poziv (h2h_df, l10_df, matchup_df)")
    else:
        patches_skipped.append("H — poziv nije pronađen (možda već patchovan drugačije)")
else:
    patches_skipped.append("H — već postoji")

# ─────────────────────────────────────────────────────────────
# PATCH I — L10 kolone u results tablici
# ─────────────────────────────────────────────────────────────
OLD_RESULT_H2H = """        "H2H PTS Avg":          round(float(ctx["h2h_pts"]),      1) if ctx.get("h2h_pts")      else None,
        "H2H Games":            int(ctx["h2h_games"])                if ctx.get("h2h_games")     else None,
        "H2H PTS Last":         round(float(ctx["h2h_pts_last"]), 1) if ctx.get("h2h_pts_last")  else None,"""

NEW_RESULT_H2H = """        "H2H PTS Avg":          round(float(ctx["h2h_pts"]),      1) if ctx.get("h2h_pts")      else None,
        "H2H Games":            int(ctx["h2h_games"])                if ctx.get("h2h_games")     else None,
        "H2H PTS Last":         round(float(ctx["h2h_pts_last"]), 1) if ctx.get("h2h_pts_last")  else None,
        "L10 PTS":              round(float(ctx["l10_pts"]),      1) if ctx.get("l10_pts")       else None,
        "L5 PTS":               round(float(ctx["l5_pts"]),       1) if ctx.get("l5_pts")        else None,
        "L10 Trend":            round(float(ctx["l10_trend"]),    2) if ctx.get("l10_trend") is not None else None,
        "DEF Factor":           round(float(ctx["def_matchup_factor"]), 3) if ctx.get("def_matchup_factor") else None,"""

if "L10 PTS" not in content:
    if OLD_RESULT_H2H in content:
        content = content.replace(OLD_RESULT_H2H, NEW_RESULT_H2H)
        patches_applied.append("I — L10/DEF kolone u results tablici")
    else:
        patches_skipped.append("I — H2H result blok nije pronađen")
else:
    patches_skipped.append("I — već postoji")

# ─────────────────────────────────────────────────────────────
# PATCH J — build_player_context return dict (dodaj l10/def polja)
# ─────────────────────────────────────────────────────────────
OLD_RETURN = """        "recent_form_used": recent_pts,
        "h2h_pts": h2h_pts, "h2h_games": h2h_games, "h2h_pts_last": h2h_pts_last,
    }"""

NEW_RETURN = """        "recent_form_used": recent_pts,
        "h2h_pts": h2h_pts, "h2h_games": h2h_games, "h2h_pts_last": h2h_pts_last,
        "l10_pts": l10_pts if 'l10_pts' in dir() else None,
        "l5_pts":  l5_pts  if 'l5_pts'  in dir() else None,
        "l10_trend": l10_trend if 'l10_trend' in dir() else None,
        "def_matchup_factor": def_matchup_factor if 'def_matchup_factor' in dir() else 1.0,
    }"""

if '"l10_pts": l10_pts' not in content:
    if OLD_RETURN in content:
        content = content.replace(OLD_RETURN, NEW_RETURN)
        patches_applied.append("J — build_player_context return dict (l10/def polja)")
    else:
        patches_skipped.append("J — return dict nije pronađen")
else:
    patches_skipped.append("J — već postoji")

# ─────────────────────────────────────────────────────────────
# Sačuvaj
# ─────────────────────────────────────────────────────────────
with open(APP_PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("\n" + "=" * 55)
print("  PATCH 2 REZULTATI")
print("=" * 55)
for p in patches_applied:
    print(f"  ✅ {p}")
for p in patches_skipped:
    print(f"  ⏭️  {p}")
print(f"\n  Backup: {os.path.basename(BACKUP_PATH)}")
print("\n  Sljedeći koraci:")
print("  streamlit run app.py")