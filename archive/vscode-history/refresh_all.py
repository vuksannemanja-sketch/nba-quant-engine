"""
refresh_all.py
Pokreće sve refresh skripte redom i ispisuje rezultat.
Korištenje: python refresh_all.py
"""

import os
import sys
import subprocess
import time

SCRIPTS = [
    ("refresh_data.py",      "Players CSV (season stats)"),
    ("refresh_injuries.py",  "Injuries CSV"),
    ("refresh_matchups.py",  "DEF/OFF matchup + L10 forma"),
    ("refresh_h2h.py",       "H2H CSV"),
    ("refresh_schedule.py",  "Raspored + B2B flags"),
    ("refresh_props.py",     "Player props + offer.csv (The Odds API)"),
]

def run_all():
    root = os.getcwd()
    ran, missing, failed = [], [], []

    print("=" * 55)
    print("  NBA Quant Engine — Refresh ALL")
    print("=" * 55)

    for sname, label in SCRIPTS:
        spath = os.path.join(root, sname)
        if not os.path.exists(spath):
            print(f"  ⏭️  SKIP     {sname:<28} (nije pronađen)")
            missing.append(sname)
            continue

        print(f"  ▶️  Pokrećem {sname:<28} [{label}]")
        t0 = time.time()
        try:
            subprocess.check_call([sys.executable, spath])
            elapsed = time.time() - t0
            print(f"  ✅ OK       {sname:<28} ({elapsed:.1f}s)")
            ran.append(sname)
        except subprocess.CalledProcessError as e:
            elapsed = time.time() - t0
            print(f"  ❌ FAIL     {sname:<28} exit code {e.returncode} ({elapsed:.1f}s)")
            failed.append((sname, f"exit code {e.returncode}"))
        except Exception as e:
            print(f"  ❌ FAIL     {sname:<28} {e}")
            failed.append((sname, str(e)))

        # Pauza između API poziva — izbjegava rate limiting
        time.sleep(1.5)

    print("=" * 55)
    print(f"  Završeno: ✅ {len(ran)} OK  |  ⏭️  {len(missing)} skip  |  ❌ {len(failed)} fail")

    if failed:
        print("\n  Greške:")
        for sname, err in failed:
            print(f"    - {sname}: {err}")

    if missing:
        print("\n  Nedostajući skripti (preskočeni):")
        for sname in missing:
            print(f"    - {sname}")

    print("=" * 55)
    return len(failed) == 0

if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)