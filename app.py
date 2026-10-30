# =====================================================
# NBA Quant Engine – Streamlit aplikacija (prikaz)
# Sva logika je u paketu nba_engine/; ovaj fajl samo crta UI.
# Pokretanje:  python -m nba_engine ui   (ili: streamlit run app.py)
# =====================================================
from __future__ import annotations

import datetime
import inspect
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

from nba_engine.config import CSV_LABELS, Settings
from nba_engine.evaluation import (compare_two_models, evaluate_engine, grade_engine,
                                   load_actual_results_csv, load_prediction_results_csv)
from nba_engine.history import analysis_fingerprint, save_analysis, save_evaluation, timestamp_now
from nba_engine.loaders import DataBundle, MissingDataError, load_bundle
from nba_engine.offer import (offer_rows_to_frame, parse_injury_override, parse_recent_form_input,
                              parse_rest_days, parse_team_list, read_offer_file)
from nba_engine.pipeline import MC_SIMS_CHOICES, AnalysisOptions, format_auto_context, run_analysis
from nba_engine.refresh import ALL_STEPS, DEFAULT_STEPS, STEP_LABELS, run_refresh
from nba_engine.schedule import STATE_ICON, fetch_schedule_context, games_for_date
from nba_engine.settle import load_all_settled, load_ledger, overall_summary, settle_history
from nba_engine.utils import normalize_name, smart_decode


def _wide(fn):
    """Puna širina elementa — radi i na starijim i na novijim verzijama Streamlita."""
    params = inspect.signature(fn).parameters
    return {"width": "stretch"} if "width" in params else {"use_container_width": True}


WIDE_DF = _wide(st.dataframe)
WIDE_BTN = _wide(st.button)

settings = Settings.load()
TODAY = datetime.date.today()
TODAY_ISO = TODAY.isoformat()

st.set_page_config(page_title="NBA Quant Engine", layout="wide")
st.title(f"🏀 NBA Quant Engine – {settings.season}")


# =====================================================
# Keširano učitavanje (ključ = putanje + vrijeme izmjene fajlova)
# =====================================================

def _data_stamp(s: Settings) -> tuple:
    return tuple((k, str(p), p.stat().st_mtime if p is not None else None) for k, p in s.all_csv_paths().items())


@st.cache_data(ttl=3600, show_spinner="Učitavam CSV podatke...")
def _load_bundle_cached(data_dir: str, season: str, fill_injury_team: bool, stamp: tuple) -> DataBundle:
    return load_bundle(Settings.load(data_dir=data_dir, season=season), fill_injury_team)


@st.cache_data(ttl=300, show_spinner=False)
def _schedule_cached(today_iso: str):
    """ESPN raspored: statusi mečeva, domaćin/gost, B2B, odmor i današnji parovi (keš po danu)."""
    return fetch_schedule_context()


def _fmt_age(hours: float) -> str:
    return f"{int(hours * 60)} min" if hours < 1 else f"{hours:.1f}h"


# =====================================================
# Gornji red: dugme za osvježavanje + status podataka
# =====================================================

st.markdown("---")
col_main1, col_main2, col_main3 = st.columns([2, 1, 1])
with col_main1:
    run_daily = st.button(f"🚀 OSVJEŽI PODATKE I POKRENI ANALIZU — {TODAY.strftime('%d.%m.%Y')}",
                          type="primary", **WIDE_BTN)
with col_main2:
    _offer_path = settings.find_offer()
    _players_ok = settings.csv_path("players_main") is not None
    if _offer_path is not None and _players_ok:
        st.success("✅ Podaci spremni")
    elif _offer_path is None:
        st.warning("⚠️ Nema fajla ponude (offer_latest.csv)")
    else:
        st.warning("⚠️ Nema CSV-a igrača")
with col_main3:
    if _offer_path is not None:
        _mtime = datetime.datetime.fromtimestamp(_offer_path.stat().st_mtime).strftime("%d.%m. %H:%M")
        st.info(f"📋 Ponuda: {_offer_path.name} ({_mtime})")
    else:
        st.info("📋 Pokreni osvježavanje ponude")
st.markdown("---")


# =====================================================
# Bočna traka: kontrole analize
# =====================================================

st.sidebar.header("⚙️ Controls")
mc_sims = st.sidebar.selectbox("Monte Carlo sims", list(MC_SIMS_CHOICES), index=3)
min_ev = st.sidebar.slider("Min EV %", -10, 25, 0)
show_only_positive = st.sidebar.checkbox("Only EV > 0", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("📈 Recent Form Override")
recent_form_txt = st.sidebar.text_area("Format: Ime, L5 prosjek (jedan po retku)", height=160,
                                       placeholder="Gui Santos, 18.2\nQuentin Grimes, 22.1")
recent_form_override = parse_recent_form_input(recent_form_txt)
if recent_form_override:
    st.sidebar.success(f"✅ {len(recent_form_override)} recent form override(s) aktivan")
    with st.sidebar.expander("Pregled overridea"):
        for k, v in recent_form_override.items():
            st.write(f"• {k}: {v} pts")

st.sidebar.markdown("---")
st.sidebar.subheader("🔁 Back-to-Back")
st.sidebar.caption("B2B se računa automatski iz ESPN rasporeda; ovdje upiši samo dopune (odvojeno zarezom)")
b2b_teams_manual = parse_team_list(st.sidebar.text_input("B2B timovi (npr. DET, MEM, LAL)", placeholder="DET, BOS"))
if b2b_teams_manual:
    st.sidebar.success(f"✅ B2B: {', '.join(sorted(b2b_teams_manual))}")
b2b_date_input = st.sidebar.text_input("Datum utakmice (YYYY-MM-DD)", value=TODAY_ISO)

st.sidebar.markdown("---")
st.sidebar.subheader("🏠 Home / Away & Rest Days")
st.sidebar.caption("Upiši timove koji igraju na gostovanju (odvojeno zarezom)")
st.sidebar.caption("Domaćin/gost i dani odmora se čitaju automatski iz ESPN rasporeda; ručni unos ima prednost")
away_teams_manual = parse_team_list(st.sidebar.text_input("Away timovi danas — ispravke (npr. DET, PHI)",
                                                          placeholder="DET, PHI", key="away_teams_input"))
if away_teams_manual:
    st.sidebar.success(f"✅ Away: {', '.join(sorted(away_teams_manual))}")
st.sidebar.caption("Rest Days — ispravke po timu (format: TIM=DANI, npr. OKC=3, MIN=2)")
rest_days_map = parse_rest_days(st.sidebar.text_input("Rest days po timu", placeholder="OKC=3, MIN=2, CLE=1",
                                                      key="rest_days_input"))
if rest_days_map:
    st.sidebar.success(f"✅ Rest: {rest_days_map}")

st.sidebar.markdown("---")
st.sidebar.subheader("🏥 Injury Override")
st.sidebar.caption("Format: Ime, Status  |  Statusi: OUT, QUESTIONABLE, DOUBTFUL, PROBABLE")
injury_override_txt = st.sidebar.text_area("Manualni injury override", height=110,
                                           placeholder="Joel Embiid, OUT\nDamian Lillard, QUESTIONABLE",
                                           key="injury_override")

st.sidebar.markdown("---")
st.sidebar.button("▶️ Pokreni / Osvježi analizu", type="primary", **WIDE_BTN)
st.sidebar.caption("Klikni nakon što uneseš Recent Form, B2B i Injury podatke")

# ── Osvježavanje podataka ─────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("🗓️ Osvježavanje podataka")

try:
    import nba_api  # noqa: F401
    _nba_api_ok = True
except ImportError:
    _nba_api_ok = False
    st.sidebar.warning("⚠️ `nba_api` nije instaliran — koraci sa NBA Stats neće raditi.")
    st.sidebar.code("pip install nba_api", language="bash")
if not settings.odds_api_key:
    st.sidebar.warning("⚠️ ODDS_API_KEY nije postavljen u .env — korak „ponuda“ neće raditi.")

_step_flags = {}
with st.sidebar.expander("Koraci osvježavanja", expanded=False):
    for _name in ALL_STEPS:
        _step_flags[_name] = st.checkbox(STEP_LABELS[_name], value=_name in DEFAULT_STEPS, key=f"step_{_name}")
    st.caption("H2H traje 10–20 min; uključi ga samo kada trebaš svježe H2H podatke.")
_selected_steps = [n for n in ALL_STEPS if _step_flags.get(n)]

_players_path = settings.csv_path("players_main")
if _players_path is not None:
    _age_h = (datetime.datetime.now() - datetime.datetime.fromtimestamp(_players_path.stat().st_mtime)).total_seconds() / 3600
    _fc = "🟢" if _age_h < 6 else ("🟡" if _age_h < 24 else "🔴")
    st.sidebar.caption(f"{_fc} Podaci stari: **{_fmt_age(_age_h)}**")
else:
    st.sidebar.caption("⚪ Nema podataka — pokreni osvježavanje")

_refresh_btn = st.sidebar.button(f"🔄 Pokreni osvježavanje ({TODAY.strftime('%d.%m.%Y')})",
                                 key="full_refresh_pipeline_btn", type="primary", **WIDE_BTN)

if run_daily or _refresh_btn:
    if not _selected_steps:
        st.sidebar.error("Nijedan korak nije označen.")
    else:
        _log_lines: list = []
        with st.status("🔄 Osvježavam podatke...", expanded=True) as _status:
            _log_box = st.empty()

            def _log(msg: str) -> None:
                _log_lines.append(str(msg))
                _log_box.code("\n".join(_log_lines[-40:]), language="")

            _report = run_refresh(settings, steps=_selected_steps, log=_log)
            if _report.ok:
                _status.update(label="✅ Osvježavanje završeno", state="complete")
            else:
                _status.update(label=f"⚠️ Osvježavanje završeno sa {len(_report.failed)} greškom/greškama", state="error")
        for _line in _report.summary_lines():
            (st.success if _line.startswith("✅") else st.error)(_line)
        st.cache_data.clear()
        if _report.ok:
            st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### 📦 Data status")
for _row in settings.data_status():
    _name = _row["path"].name if _row["exists"] else "nema"
    _age = f" · {_fmt_age(_row['age_hours'])}" if _row["exists"] else ""
    st.sidebar.write(f"{_row['label']}: {'✅' if _row['exists'] else '❌'} → {_name}{_age}")
st.sidebar.caption(f"Sezona: {settings.season} ({settings.season_source}) · {settings.data_dir}")


# =====================================================
# Učitavanje podataka
# =====================================================

try:
    bundle = _load_bundle_cached(str(settings.data_dir), settings.season, True, _data_stamp(settings))
except MissingDataError as e:
    st.error(str(e))
    st.stop()
except Exception as e:  # noqa: BLE001
    st.error(f"Greška pri učitavanju podataka: {e}")
    st.stop()

players_df, teams_df = bundle.players, bundle.teams
for _note in bundle.notes:
    st.sidebar.caption("ℹ️ " + _note)

_inj_path = settings.csv_path("injuries")
if _inj_path is not None:
    _inj_age_h = (datetime.datetime.now() - datetime.datetime.fromtimestamp(_inj_path.stat().st_mtime)).total_seconds() / 3600
    if _inj_age_h > 48:
        st.warning(f"⚠️ Tabela ozljeda ({_inj_path.name}) je stara {_inj_age_h / 24:.0f} dana — statusi OUT/QUESTIONABLE "
                   "vjerovatno više ne važe. Pokreni osvježavanje (korak „Ozljede“) ili koristi ručni Injury Override.")

injury_override_df: Optional[pd.DataFrame] = None
if injury_override_txt and injury_override_txt.strip():
    injury_override_df = parse_injury_override(injury_override_txt, players_df)
    if not injury_override_df.empty:
        st.sidebar.success(f"🏥 {len(injury_override_df)} injury override(s) aktivno")
        with st.sidebar.expander("Pregled injury overridea"):
            for _, _ir in injury_override_df.iterrows():
                _abbr = _ir["TEAM_ABBR"] if pd.notna(_ir["TEAM_ABBR"]) else "?"
                st.write(f"• {_ir['PLAYER']} ({_abbr}): **{_ir['STATUS']}**")


with st.expander("🔍 DEBUG DATA — status svih izvora"):
    st.markdown("**📁 CSV fajlovi na disku:**")
    for _row in settings.data_status():
        if _row["exists"]:
            st.write(f"✅ {_row['label']}: {_row['path'].name}, {_row['size_kb']}KB, "
                     f"zadnji update: {_row['modified'].strftime('%d.%m %H:%M')}")
        else:
            st.write(f"❌ {_row['label']}: fajl ne postoji")
    st.markdown("---")
    st.markdown("**📊 Učitani DataFrameovi:**")
    _sum = bundle.summary()
    st.write(f"players_df: {_sum['players']} rows, {len(players_df.columns)} cols")
    st.write(f"teams_df:   {_sum['teams']} rows")
    st.write(f"inj_df:     {_sum['injuries']} rows")
    if bundle.l10 is not None and not bundle.l10.empty:
        st.write(f"l10_df:     ✅ {_sum['l10']} rows — kolone: {list(bundle.l10.columns)}")
        st.dataframe(bundle.l10.head(5), **WIDE_DF)
    else:
        st.write("l10_df:     ❌ None ili prazan")
    if bundle.h2h is not None and not bundle.h2h.empty:
        st.write(f"h2h_df:     ✅ {_sum['h2h']} rows — kolone: {list(bundle.h2h.columns)}")
        st.dataframe(bundle.h2h.head(5), **WIDE_DF)
    else:
        st.write("h2h_df:     ❌ None ili prazan")
    st.markdown("---")
    st.markdown("**🔑 NAME_KEY matching:**")
    _pk = set(players_df["NAME_KEY"].dropna().tolist())
    if bundle.l10 is not None and not bundle.l10.empty and "NAME_KEY" in bundle.l10.columns:
        _lk = set(bundle.l10["NAME_KEY"].dropna().tolist())
        st.write(f"L10 NAME_KEY match: {len(_pk & _lk)}/{len(_lk)} igrača matchovano")
        _unm = _lk - _pk
        if _unm:
            st.write(f"  ⚠️ L10 bez matcha: {sorted(list(_unm))[:10]}")
    if bundle.h2h is not None and not bundle.h2h.empty and "NAME_KEY" in bundle.h2h.columns:
        _hk = set(bundle.h2h["NAME_KEY"].dropna().tolist())
        st.write(f"H2H NAME_KEY match: {len(_pk & _hk)}/{len(_hk)} igrača matchovano")
    if bundle.injuries is not None and not bundle.injuries.empty:
        _with_team = int(bundle.injuries["TEAM_ABBR"].notna().sum())
        st.write(f"Ozljede sa poznatim timom: {_with_team}/{len(bundle.injuries)}")
    st.markdown("---")
    _debug_cols = [c for c in ("PLAYER_NAME", "TEAM_ABBR", "TEAM_NUMERIC_ID", "MIN", "PTS", "USG_PCT",
                               "TS_PCT", "PIE", "PTS_PAINT", "PACE") if c in players_df.columns]
    st.dataframe(players_df[_debug_cols].head(20), **WIDE_DF)


# =====================================================
# NBA raspored — danas + sutra (ESPN)
# =====================================================

_schedule_ctx = _schedule_cached(TODAY_ISO)
_game_statuses = _schedule_ctx.statuses if _schedule_ctx is not None else {}
if _schedule_ctx is None or not _schedule_ctx.fetched:
    st.caption("ℹ️ ESPN raspored nije dostupan: domaćin/gost, B2B i odmor rade samo iz ručnog unosa, svježina ponude se ne provjerava.")
if _game_statuses:
    _today_games = games_for_date(_game_statuses, TODAY.strftime("%Y%m%d"))
    _tomorrow_games = games_for_date(_game_statuses, (TODAY + datetime.timedelta(days=1)).strftime("%Y%m%d"))
    with st.expander(f"📅 NBA Raspored — Danas ({len(_today_games)}) + Sutra ({len(_tomorrow_games)})"):
        for _label, _games, _live in (("Danas", _today_games, True), ("Sutra", _tomorrow_games, False)):
            if not _games:
                continue
            st.markdown(f"**{_label}:**")
            _cols = st.columns(min(4, max(1, len(_games))))
            for _ci, (_abbr, _g) in enumerate(_games.items()):
                with _cols[_ci % len(_cols)]:
                    st.markdown(f"**{_abbr} vs {_g['opponent']}**")
                    st.caption(f"{STATE_ICON.get(_g['state'], '🕐') if _live else '🕐'} {_g['detail']}")


# =====================================================
# Ponuda — automatski ili ručni upload
# =====================================================

st.subheader("📂 Offer — automatski ili manual upload")
auto_offer_path = settings.find_offer()
col_src1, col_src2 = st.columns([3, 1])
with col_src1:
    uploaded = st.file_uploader("Manual upload (opcionalno — ako ne uploaduješ, koristi se automatski offer)",
                                type=["txt", "csv"])
with col_src2:
    st.markdown("&nbsp;", unsafe_allow_html=True)
    if auto_offer_path is not None:
        _mtime2 = datetime.datetime.fromtimestamp(auto_offer_path.stat().st_mtime).strftime("%d.%m. %H:%M")
        st.success(f"✅ Auto offer\n{auto_offer_path.name}\nažuriran: {_mtime2}")
    else:
        st.warning("⚠️ offer_latest.csv nije pronađen.")

actual_uploaded = st.file_uploader("Upload results CSV za evaluaciju: Player, Actual Points, (optional: Closing Line…)",
                                   type=["csv"], key="actual_results_upload")
second_model_uploaded = st.file_uploader("Optional: Upload second model prediction CSV", type=["csv"],
                                         key="second_model_upload")

if uploaded is not None:
    offer_text = smart_decode(uploaded.getvalue())
    offer_source = f"📤 Manual upload: {uploaded.name}"
elif auto_offer_path is not None:
    offer_text = read_offer_file(auto_offer_path)
    offer_source = f"🤖 Auto-load: {auto_offer_path.name}"
else:
    st.error("❌ Nema offer podataka. Pokreni osvježavanje (korak „ponuda“) ili uploaduj ručno.")
    st.stop()
st.caption(f"Izvor ponude: {offer_source}")


# =====================================================
# Analiza
# =====================================================

options = AnalysisOptions(
    mc_sims=int(mc_sims), min_ev=float(min_ev), only_positive=bool(show_only_positive),
    recent_form_override=recent_form_override, b2b_teams_manual=b2b_teams_manual,
    b2b_date=b2b_date_input, away_teams_manual=away_teams_manual, rest_days_map=rest_days_map,
    injury_override=injury_override_df, game_statuses=_game_statuses, schedule=_schedule_ctx,
)
with st.spinner("Računam projekcije i Monte Carlo..."):
    result = run_analysis(offer_text, bundle, options)

st.caption(f"Parsed rows: {len(result.offer_rows)} | Skipped lines: {len(result.bad_lines)}")
with st.expander("🧾 Debug parsed rows"):
    if result.offer_rows:
        st.dataframe(offer_rows_to_frame(result.offer_rows), **WIDE_DF)
    if result.bad_lines:
        st.dataframe(pd.DataFrame(result.bad_lines, columns=["raw", "reason"]), **WIDE_DF)

if result.skipped_active:
    _skip_df = pd.DataFrame(result.skipped_active)
    _in_live = int((_skip_df["Status"] == "🔴 LIVE").sum())
    _in_final = int((_skip_df["Status"] == "✅ Final").sum())
    _msg = []
    if _in_live:
        _msg.append(f"{_in_live} igrača (meč u toku)")
    if _in_final:
        _msg.append(f"{_in_final} igrača (meč završen)")
    st.warning(f"⏭️ Preskočeno {len(result.skipped_active)} igrača — " + ", ".join(_msg))
    with st.expander("📋 Preskočeni igrači (meč počeo ili završio)"):
        st.dataframe(_skip_df, **WIDE_DF)

# Svježina ponude: parovi iz ponude moraju biti današnji mečevi po ESPN rasporedu
if result.offer_is_today is False:
    st.error(f"🛑 **Ponuda nije za današnje mečeve.** Nijedan od {result.offer_matched_rows} parova iz ponude nije u današnjem "
             f"ESPN rasporedu ({result.auto_context.get('games_today', 0)} mečeva danas). Brojke ispod nisu upotrebljive i "
             "istorija se ne snima. Povuci novu ponudu (korak „ponuda“ ili upload).")
elif result.offer_is_today and result.offer_today_matches < result.offer_matched_rows:
    st.warning(f"⚠️ {result.offer_matched_rows - result.offer_today_matches} od {result.offer_matched_rows} redova ponude nije među današnjim mečevima.")
if result.auto_context:
    st.caption("🏠 Automatski iz ESPN rasporeda — " + format_auto_context(result.auto_context))
if result.excluded_out:
    st.warning(f"⛔ {len(result.excluded_out)} igrača isključeno iz rangiranja — status OUT (opklada bi bila poništena)")
    with st.expander("⛔ Isključeni igrači (OUT)"):
        st.dataframe(pd.DataFrame(result.excluded_out), **WIDE_DF)

if not result.ok:
    st.error(result.message)
    if result.not_found:
        st.dataframe(pd.DataFrame(result.not_found), **WIDE_DF)
    st.stop()

with st.expander("🔎 Debug players not found"):
    if result.not_found:
        st.dataframe(pd.DataFrame(result.not_found), **WIDE_DF)
    else:
        st.write("All players matched ✅")

_inj_used = result.injuries_used
if _inj_used is not None and not _inj_used.empty and "NAME_KEY" in _inj_used.columns:
    _offer_keys = {normalize_name(r.name) for r in result.offer_rows}
    _flagged = _inj_used[_inj_used["NAME_KEY"].isin(_offer_keys)]
    if not _flagged.empty:
        with st.expander(f"🏥 Igrači iz ponude na injury listi ({len(_flagged)}) — provjeri prije uplate"):
            _cols = [c for c in ("PLAYER", "TEAM_ABBR", "STATUS", "DESCRIPTION") if c in _flagged.columns]
            st.dataframe(_flagged[_cols].reset_index(drop=True), **WIDE_DF)

st.caption(f"Bookmaker offset: **{result.bm_offset:.2f}**")
df = result.df

conc = result.concentration
if conc.teams:
    st.markdown("---")
    st.warning(f"⚠️ **Team Concentration Warning** — {len(conc.teams)} tim(a) ima 3+ OVER pickova")
    for team in conc.teams:
        usg_sum = conc.usg_sums.get(team, 0.0)
        c1, c2, c3 = st.columns(3)
        c1.metric(f"🏀 {team} OVER pickovi", conc.counts.get(team, 0))
        c2.metric("Ukupni USG%", f"{usg_sum:.0f}%", delta="⚠️ Visoko" if usg_sum > 85 else "OK",
                  delta_color="inverse" if usg_sum > 85 else "normal")
        c3.metric("EV penalty primijenjen", f"{len(conc.penalized.get(team, []))} igrač(a)")
        st.caption(f"Igrači: {', '.join(conc.players.get(team, []))}")
        if conc.penalized.get(team):
            st.caption(f"🔻 Penalizirani: {', '.join(conc.penalized[team])}")
    st.markdown("---")

if recent_form_override and result.recent_form_count > 0:
    st.info(f"📈 {result.recent_form_count} igrač(a) ima aktivan Recent Form override")

st.subheader("📊 Full Portfolio")
st.dataframe(df, **WIDE_DF)
st.subheader("🔥 TOP 3")
st.dataframe(df.head(3), **WIDE_DF)


# =====================================================
# Evaluacija / poređenje modela
# =====================================================

st.markdown("---")
st.subheader("✅ Engine Evaluation / Grading")
stake_size = st.number_input("Stake per bet", min_value=0.1, value=1.0, step=0.1)
actual_results_df: Optional[pd.DataFrame] = None
evaluated_df: Optional[pd.DataFrame] = None

if actual_uploaded is not None:
    try:
        actual_results_df = load_actual_results_csv(actual_uploaded)
    except Exception as e:  # noqa: BLE001
        st.error(f"Greška pri učitavanju results CSV: {e}")

if actual_results_df is not None:
    try:
        evaluated_df, eval_summary = evaluate_engine(df, actual_results_df, stake=stake_size, model_name="Engine 1")
        grade = grade_engine(eval_summary)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Accuracy", f"{eval_summary['Accuracy %']}%")
        c2.metric("ROI", f"{eval_summary['ROI %']}%")
        c3.metric("Profit", f"{eval_summary['Profit']}")
        c4.metric("MAE", f"{eval_summary['MAE']}")
        c5.metric("Grade", grade)
        st.dataframe(pd.DataFrame([eval_summary]), **WIDE_DF)
        eval_cols = [c for c in ("Player", "Model Pick", "Line", "Final Projection", "Actual Points",
                                 "Bet Result", "Used Odds", "Profit", "Projection Edge", "CLV")
                     if c in evaluated_df.columns]
        st.dataframe(evaluated_df[eval_cols], **WIDE_DF)
    except Exception as e:  # noqa: BLE001
        st.error(f"Greška u engine evaluaciji: {e}")

if actual_results_df is not None and second_model_uploaded is not None:
    st.markdown("---")
    st.subheader("⚔️ Compare Two Models")
    try:
        second_model_df = load_prediction_results_csv(second_model_uploaded)
        _, summary_1 = evaluate_engine(df, actual_results_df, stake=stake_size, model_name="Engine 1")
        _, summary_2 = evaluate_engine(second_model_df, actual_results_df, stake=stake_size, model_name="Engine 2")
        summary_1["Grade"] = grade_engine(summary_1)
        summary_2["Grade"] = grade_engine(summary_2)
        winner, compare_df = compare_two_models(summary_1, summary_2)
        if winner == "TIE":
            st.info("Rezultat poređenja: TIE")
        else:
            st.success(f"Winner: {winner}")
        st.dataframe(compare_df, **WIDE_DF)
    except Exception as e:  # noqa: BLE001
        st.error(f"Greška u compare modulu: {e}")


# =====================================================
# Automatska evaluacija: snimljene analize vs stvarni poeni
# =====================================================

st.markdown("---")
st.subheader("📈 Automatska evaluacija — sve snimljene analize")
st.caption("Svaka snimljena analiza se poslije odigranih mečeva poravnava sa stvarnim poenima iz NBA game loga. "
           "Računa se samo OVER/UNDER; igrač koji nije igrao = VOID. Profit je u jedinicama uloga (1 po opkladi). "
           "Ovo je jedini pravi pokazatelj koliko model vrijedi.")
_sc1, _sc2 = st.columns([1, 3])
if _sc1.button("🔄 Poravnaj nove analize", help="Povlači game log sa NBA Stats (10–20 s) i poravnava sve još neporavnate analize"):
    with st.spinner("Povlačim stvarne rezultate i poravnavam..."):
        _msgs: list = []
        try:
            _events = settle_history(settings.history_dir, stake=1.0, log=_msgs.append)
            _n = {k: sum(1 for e in _events if e["status"] == k) for k in ("settled", "pending", "no_data", "error")}
            _sc2.success(f"Poravnato: {_n['settled']} | čeka mečeve: {_n['pending']} | game log još nema datum: {_n['no_data']} | greške: {_n['error']}")
            for _m in _msgs:
                st.caption(_m)
        except Exception as e:  # noqa: BLE001
            st.error(f"Poravnanje nije uspjelo: {e}")
_ledger = load_ledger(settings.history_dir)
if _ledger.empty:
    _sc2.info("Još nema poravnatih analiza. Analize se snimaju u history/ samo kad je ponuda za današnje mečeve; "
              "sutradan klikni „Poravnaj nove analize“ ili pokreni: python -m nba_engine settle")
else:
    _o = overall_summary(load_all_settled(settings.history_dir), stake=1.0)
    _m1, _m2, _m3, _m4, _m5, _m6 = st.columns(6)
    _m1.metric("Opklada", _o["Bets"])
    _m2.metric("Pogodak", f"{_o['Accuracy %']}%")
    _m3.metric("ROI", f"{_o['ROI %']}%")
    _m4.metric("Profit", f"{_o['Profit']:+.2f}")
    _m5.metric("MAE", _o["MAE"] if _o["MAE"] is not None else "-")
    _m6.metric("Ocjena", _o["Grade"])
    st.caption(f"{_o['Days']} analiza | {_o['Wins']}-{_o['Losses']}-{_o['Pushes']} | void {_o['Void']} | "
               "ocjena po istim pragovima kao ručna evaluacija (A–F)")
    st.dataframe(_ledger.sort_values("Game Date", ascending=False), **WIDE_DF)
    with st.expander("Detalji po pick-u (zadnja poravnata analiza)"):
        _last_name = str(_ledger.sort_values("Game Date").iloc[-1]["Analysis"])
        _last_path = settings.history_dir / f"settled_{_last_name}"
        if _last_path.exists():
            _sd = pd.read_csv(_last_path)
            _scols = [c for c in ("Player", "TEAM_ABBR", "OPP_TEAM", "Model Pick", "Line", "Final Projection",
                                  "Actual Points", "Actual Opp", "Bet Result", "Used Odds", "Profit", "Abs Error") if c in _sd.columns]
            st.dataframe(_sd[_scols], **WIDE_DF)
        else:
            st.write("Fajl sa detaljima nije pronađen.")


# =====================================================
# Istorija (isti rezultat se u jednoj sesiji snima samo jednom)
# =====================================================

_fp = analysis_fingerprint(df)
if result.offer_is_today is False:
    st.caption("Istorija nije snimljena: ponuda nije za današnje mečeve.")
elif st.session_state.get("last_history_fp") != _fp:
    _ts = timestamp_now()
    try:
        _hist_path = save_analysis(df, settings.history_dir, _ts)
        st.session_state["last_history_fp"] = _fp
        st.session_state["last_history_file"] = _hist_path.name
        st.caption(f"Saved history: {_hist_path.name}")
    except Exception as e:  # noqa: BLE001
        st.warning(f"Could not save history csv: {e}")
    if actual_results_df is not None and evaluated_df is not None:
        try:
            _eval_path = save_evaluation(evaluated_df, settings.history_dir, _ts)
            st.caption(f"Saved evaluation CSV: {_eval_path.name}")
        except Exception as e:  # noqa: BLE001
            st.warning(f"Could not save evaluation csv: {e}")
else:
    st.caption(f"Istorija već snimljena: {st.session_state.get('last_history_file', '')}")
