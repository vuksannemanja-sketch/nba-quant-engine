"""Komandna linija: ``python -m nba_engine <komanda>``.

Komande:
  ui           pokreni Streamlit aplikaciju
  analyze      pokreni dnevnu analizu nad ponudom i ispiši najbolje pickove
  fetch-offer  povuci današnju ponudu sa The Odds API u data/offer_latest.csv
  settle       poravnaj snimljene analize sa stvarnim poenima (automatska evaluacija)
  refresh      osvježi CSV podatke (NBA Stats, ESPN, The Odds API)
  check        provjeri podešavanja, podatke i zavisnosti
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from .config import PROJECT_ROOT, Settings


def _settings_from_args(args) -> Settings:
    return Settings.load(data_dir=args.data_dir, season=args.season, env_file=args.env_file,
                         history_dir=getattr(args, "history_dir", None))


def _print_df(df, max_rows: Optional[int] = None) -> None:
    import pandas as pd
    with pd.option_context("display.max_columns", 50, "display.width", 200, "display.max_rows", max_rows or 200):
        print(df.to_string(index=False))


# ---------------------------------------------------------------------------
# komande
# ---------------------------------------------------------------------------

def cmd_check(args) -> int:
    settings = _settings_from_args(args)
    print(f"Python {sys.version.split()[0]} | projekat: {PROJECT_ROOT}")
    print("Podešavanja:", settings.describe())
    if settings.env_file:
        print(f".env fajl: {settings.env_file}")
    else:
        print(".env fajl: nema (napravi ga po uzoru na .env.example)")
    print()
    print(f"{'Podatak':22} {'Fajl':32} {'Status':8} {'Starost':>10}")
    for row in settings.data_status():
        if row["exists"]:
            age = row["age_hours"]
            age_s = f"{age * 60:.0f} min" if age < 1 else (f"{age:.1f} h" if age < 48 else f"{age / 24:.0f} dana")
            print(f"{row['label']:22} {row['path'].name:32} {'✅':8} {age_s:>10}")
        else:
            print(f"{row['label']:22} {'-':32} {'❌ nema':8} {'':>10}")
    offer = settings.find_offer()
    print()
    print("Ponuda:", offer if offer else "❌ nema (pokreni fetch-offer ili ručno upload-uj u aplikaciji)")
    try:
        import nba_api  # noqa: F401
        print("nba_api: ✅ instaliran")
    except ImportError:
        print("nba_api: ❌ nije instaliran (pip install nba_api) — refresh koraka sa NBA Stats neće raditi")
    try:
        import streamlit  # noqa: F401
        print("streamlit: ✅ instaliran")
    except ImportError:
        print("streamlit: ❌ nije instaliran (pip install streamlit)")
    return 0


def cmd_analyze(args) -> int:
    from .loaders import MissingDataError, load_bundle
    from .offer import read_offer_file
    from .pipeline import AnalysisOptions, format_auto_context, run_analysis, summary_table
    from .history import save_analysis

    settings = _settings_from_args(args)
    try:
        bundle = load_bundle(settings, fill_injury_team_from_players=not args.no_fill_injury_team,
                             blend_prior_season=not args.no_prior_season)
    except MissingDataError as e:
        print(f"❌ {e}")
        return 1
    offer_path = Path(args.offer) if args.offer else settings.find_offer()
    if offer_path is None or not offer_path.exists():
        print("❌ Nema fajla ponude. Pokreni: python -m nba_engine fetch-offer  (ili zadaj --offer PUTANJA)")
        return 1

    schedule_ctx = None
    if not args.no_schedule:
        from .schedule import fetch_schedule_context
        schedule_ctx = fetch_schedule_context()

    options = AnalysisOptions(mc_sims=args.mc_sims, min_ev=args.min_ev, only_positive=args.only_positive,
                              game_statuses=schedule_ctx.statuses if schedule_ctx else {}, schedule=schedule_ctx,
                              use_l10_minutes=not args.no_l10_minutes, use_l10_sigma=not args.no_l10_sigma)
    result = run_analysis(read_offer_file(offer_path), bundle, options)

    print(f"Sezona {settings.season} | ponuda: {offer_path.name} | redova: {len(result.offer_rows)} "
          f"(loših: {len(result.bad_lines)}) | nije nađeno: {len(result.not_found)} | preskočeno (meč u toku/završen): "
          f"{len(result.skipped_active)}")
    for note in bundle.notes:
        print("ℹ️ ", note)
    if result.offer_is_today is False:
        print(f"🛑 Ponuda NIJE za današnje mečeve: 0 od {result.offer_matched_rows} parova iz ponude je u ESPN rasporedu "
              f"(danas {result.auto_context.get('games_today', 0)} mečeva). Brojke ispod nisu upotrebljive; istorija se ne snima.")
    elif result.offer_is_today is None and not args.no_schedule:
        print("ℹ️  ESPN raspored nije dostupan — svježina ponude nije provjerena.")
    elif result.offer_is_today and result.offer_today_matches < result.offer_matched_rows:
        print(f"⚠️  {result.offer_matched_rows - result.offer_today_matches} od {result.offer_matched_rows} redova ponude nije među današnjim mečevima.")
    if result.auto_context:
        print("🏠 Automatski iz ESPN rasporeda — " + format_auto_context(result.auto_context))
    if result.excluded_out:
        print(f"⛔ Isključeno iz rangiranja, status OUT (opklada bi bila poništena): " + ", ".join(
            f"{e['Player']} ({e['Team']})" for e in result.excluded_out))
    if not result.ok:
        print(f"❌ {result.message}")
        if result.not_found:
            import pandas as pd
            _print_df(pd.DataFrame(result.not_found))
        return 1

    inj_path = settings.csv_path("injuries")
    if inj_path is not None:
        age_h = (_dt.datetime.now() - _dt.datetime.fromtimestamp(inj_path.stat().st_mtime)).total_seconds() / 3600
        if age_h > 48:
            print(f"⚠️  Tabela ozljeda je stara {age_h / 24:.0f} dana — pokreni: python -m nba_engine refresh --steps injuries")
    inj_used = result.injuries_used
    if inj_used is not None and not inj_used.empty and "NAME_KEY" in inj_used.columns:
        from .utils import normalize_name
        offer_keys = {normalize_name(r.name) for r in result.offer_rows}
        flagged = inj_used[inj_used["NAME_KEY"].isin(offer_keys)]
        if not flagged.empty:
            print(f"🏥 Igrači iz ponude na injury listi ({len(flagged)}): " + ", ".join(
                f"{r['PLAYER']} ({r['STATUS']})" for _, r in flagged.head(12).iterrows()) + (" ..." if len(flagged) > 12 else ""))
    print(f"Bookmaker offset: {result.bm_offset:.2f} | pickova nakon filtera: {len(result.df)}")
    if result.concentration.teams:
        print("⚠️ Koncentracija OVER pickova:", ", ".join(
            f"{t} ({result.concentration.counts[t]})" for t in result.concentration.teams))
    print()
    _print_df(summary_table(result.df, args.top))

    if args.out:
        result.df.to_csv(args.out, index=False)
        print(f"\n💾 Puna tabela: {args.out}")
    if not args.no_history:
        if result.offer_is_today is False:
            print("ℹ️  Istorija nije snimljena: ponuda nije za danas.")
        else:
            path = save_analysis(result.df, settings.history_dir)
            print(f"💾 Istorija: {path}")
    return 0


def cmd_fetch_offer(args) -> int:
    from .odds_api import fetch_daily_offer
    settings = _settings_from_args(args)
    res = fetch_daily_offer(settings, log=print, best_odds=not args.single_book, closing=args.closing)
    if not res.ok:
        print(f"❌ {res.message}")
        return 1
    print(f"✅ {res.message}")
    for p in res.paths:
        print("   →", p)
    return 0


def cmd_refresh(args) -> int:
    from .refresh import ALL_STEPS, run_refresh
    settings = _settings_from_args(args)
    steps: Optional[List[str]] = None
    if args.steps:
        steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    elif args.all:
        steps = list(ALL_STEPS)
    report = run_refresh(settings, steps=steps, skip_h2h=not args.with_h2h, log=print)
    return 0 if report.ok else 1


def cmd_settle(args) -> int:
    from .settle import load_all_settled, load_ledger, overall_summary, settle_history
    settings = _settings_from_args(args)
    hist = Path(getattr(args, "history_dir", None) or settings.history_dir)
    if not args.report:
        print(f"📒 Poravnanje analiza iz {hist} sa stvarnim poenima (NBA Stats game log)...")
        events = settle_history(hist, stake=args.stake, force=args.force, log=print, closing_dir=settings.data_dir)
        n = {k: sum(1 for e in events if e["status"] == k) for k in ("settled", "pending", "no_data", "error")}
        print(f"Poravnato: {n['settled']} | čeka mečeve: {n['pending']} | game log još nema datum: {n['no_data']} | greške: {n['error']}")
        for e in events:
            if e["status"] in ("pending", "error"):
                print(f"  · {e['Analysis']}: {e['detail']}")
    ledger = load_ledger(hist)
    if ledger.empty:
        print("Ledger je prazan — još nema poravnatih analiza (snimaju se samo analize ponude za današnje mečeve).")
        return 0
    cols = ["Game Date", "Analysis", "Picks", "Settled", "Wins", "Losses", "Pushes", "Void", "Accuracy %",
            "Profit", "ROI %", "MAE", "Grade"]
    print("\n📊 Po analizi:")
    _print_df(ledger.sort_values("Game Date")[cols].tail(args.last))
    o = overall_summary(load_all_settled(hist), stake=args.stake)
    print(f"\n🏁 Ukupno ({o['Days']} analiza): {o['Bets']} opklada, {o['Wins']}-{o['Losses']}-{o['Pushes']} (void {o['Void']}) | "
          f"pogodak {o['Accuracy %']} % | profit {o['Profit']:+.2f} | ROI {o['ROI %']:+.2f} % | MAE {o['MAE']} | ocjena {o['Grade']}")
    return 0


def cmd_ui(args) -> int:
    app_path = PROJECT_ROOT / "app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(args.port)]
    if args.headless:
        cmd += ["--server.headless", "true"]
    env = dict(os.environ)
    if args.season:
        env["NBA_SEASON"] = args.season
    if args.data_dir:
        env["NBA_DATA_DIR"] = str(args.data_dir)
    print("▶️ ", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(PROJECT_ROOT), env=env)


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m nba_engine", description="NBA Quant Engine")
    common_help = {
        "--season": "NBA sezona, npr. 2026-27 (podrazumijevano: iz .env ili iz podataka)",
        "--data-dir": "folder sa CSV podacima (podrazumijevano: data/)",
        "--env-file": "putanja do .env fajla (podrazumijevano: .env u korijenu)",
    }
    for flag, text in common_help.items():
        p.add_argument(flag, help=text)
    # iste opcije smiju stajati i poslije naziva komande (SUPPRESS: ne gaze vrijednost sa početka)
    common = argparse.ArgumentParser(add_help=False)
    for flag, text in common_help.items():
        common.add_argument(flag, default=argparse.SUPPRESS, help=text)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("ui", parents=[common], help="pokreni Streamlit aplikaciju")
    s.add_argument("--port", type=int, default=8501)
    s.add_argument("--headless", action="store_true")
    s.set_defaults(func=cmd_ui)

    s = sub.add_parser("analyze", parents=[common], help="dnevna analiza iz komandne linije")
    s.add_argument("--offer", help="fajl ponude (podrazumijevano: data/offer_latest.csv)")
    s.add_argument("--mc-sims", type=int, default=5000, help="broj Monte Carlo simulacija (500/1000/3000/5000)")
    s.add_argument("--min-ev", type=float, default=0.0, help="minimalni EV %% za prikaz")
    s.add_argument("--only-positive", action="store_true", help="samo pickovi sa EV > 0")
    s.add_argument("--top", type=int, default=10, help="koliko redova ispisati")
    s.add_argument("--out", help="snimi punu tabelu u CSV")
    s.add_argument("--no-history", action="store_true", help="ne snimaj u history/")
    s.add_argument("--no-schedule", action="store_true", help="ne provjeravaj ESPN raspored (bez mreže)")
    s.add_argument("--no-fill-injury-team", action="store_true",
                   help="ne dopunjavaj tim u tabeli ozljeda iz baze igrača (ponašanje starog app.py)")
    s.add_argument("--history-dir", help="folder za istoriju (podrazumijevano: history/)")
    s.add_argument("--no-prior-season", action="store_true",
                   help="ne dopunjavaj ranu sezonu prošlom sezonom (grupa B)")
    s.add_argument("--no-l10-minutes", action="store_true", help="minute samo iz sezonskog prosjeka (bez L10_MIN)")
    s.add_argument("--no-l10-sigma", action="store_true", help="rasipanje samo iz formule (bez L10_STD)")
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("fetch-offer", parents=[common], help="povuci dnevnu ponudu sa The Odds API")
    s.add_argument("--single-book", action="store_true",
                   help="kvote samo od kladionice najvišeg prioriteta (bez traženja najbolje kvote)")
    s.add_argument("--closing", action="store_true",
                   help="snimi zatvorene linije u data/closing_<datum>.csv (za CLV); ponuda se ne mijenja; troši API zahtjeve")
    s.set_defaults(func=cmd_fetch_offer)

    s = sub.add_parser("refresh", parents=[common], help="osvježi podatke")
    s.add_argument("--steps", help="koraci odvojeni zarezom: offer,players,injuries,matchups,schedule,h2h")
    s.add_argument("--with-h2h", action="store_true", help="uključi i spori H2H korak")
    s.add_argument("--all", action="store_true", help="svi koraci uključujući H2H")
    s.set_defaults(func=cmd_refresh)

    s = sub.add_parser("check", parents=[common], help="provjeri podešavanja i podatke")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("settle", parents=[common],
                       help="poravnaj snimljene analize sa stvarnim poenima (automatska evaluacija)")
    s.add_argument("--stake", type=float, default=1.0, help="ulog po opkladi za profit/ROI (podrazumijevano 1)")
    s.add_argument("--force", action="store_true", help="ponovo poravnaj i već poravnate analize")
    s.add_argument("--report", action="store_true", help="samo ispiši ledger i zbir, bez mreže")
    s.add_argument("--last", type=int, default=20, help="koliko zadnjih analiza ispisati")
    s.add_argument("--history-dir", help="folder istorije (podrazumijevano: history/)")
    s.set_defaults(func=cmd_settle)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
