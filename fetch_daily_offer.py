#!/usr/bin/env python3
"""
fetch_daily_offer.py - Wrapper za fetch_dnevna_ponuda_multi.py
Poziva se iz app.py u run_full_refresh_pipeline()
"""

import os
import sys

# Import glavne skripte
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

try:
    from fetch_dnevna_ponuda_multi import main, run
except ImportError:
    # Fallback: pokreni kao subprocess
    import subprocess
    result = subprocess.run(
        [sys.executable, os.path.join(script_dir, "fetch_dnevna_ponuda_multi.py")],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()