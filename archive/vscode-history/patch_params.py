#!/usr/bin/env python3
"""
Pokreni u folderu gdje je app.py:
    python3 patch_params.py

Primjenjuje 5 parametarskih fixova bez ikakvih izmjena logike.
Pravi backup: app.py.bak
"""
import shutil, sys

SRC = "app.py"
BAK = "app.py.bak"

try:
    with open(SRC, "r", encoding="utf-8") as f:
        src = f.read()
except FileNotFoundError:
    print(f"GREŠKA: {SRC} nije pronađen u ovom folderu.")
    sys.exit(1)

shutil.copy2(SRC, BAK)
print(f"✅ Backup: {BAK}\n")

applied = 0

def patch(label, old, new):
    global src, applied
    if old in src:
        src = src.replace(old, new, 1)
        print(f"✅ {label}")
        applied += 1
    else:
        print(f"⚠️  {label} — nije pronađen (možda već primijenjen)")

# ── FIX 1: EV cap 0.35 → 0.50 ────────────────────────────────────────────────
# Problem: jake UNDER prilike (proj 38% ispod linije) su artificijalno ograničene
patch(
    "FIX 1 — EV cap: 0.35 → 0.50",
    "    ev_over  = _clamp(ev_over,  -0.99, 0.35)\n    ev_under = _clamp(ev_under, -0.99, 0.35)",
    "    ev_over  = _clamp(ev_over,  -0.99, 0.50)\n    ev_under = _clamp(ev_under, -0.99, 0.50)"
)

# ── FIX 2: Market blend agresivnost smanjena ──────────────────────────────────
# Problem: za edge > 3pts model reže proj i do -19% prema liniji
# Staro: 0.55 / 0.45 / 0.35 / 0.25 → Novo: 0.45 / 0.30 / 0.20 / 0.12
patch(
    "FIX 2 — Market blend: agresivnost smanjena",
    "    edge_raw = proj_devigged - line_val\n    abs_edge = abs(edge_raw)\n    if abs_edge < 1.5:\n        market_blend = 0.55\n    elif abs_edge < 3.0:\n        market_blend = 0.45\n    elif abs_edge < 5.0:\n        market_blend = 0.35\n    else:\n        market_blend = 0.25",
    "    edge_raw = proj_devigged - line_val\n    abs_edge = abs(edge_raw)\n    if abs_edge < 1.5:\n        market_blend = 0.45\n    elif abs_edge < 3.0:\n        market_blend = 0.30\n    elif abs_edge < 5.0:\n        market_blend = 0.20\n    else:\n        market_blend = 0.12"
)

# ── FIX 3: MIN_EDGE_THRESHOLD 0.04 → 0.025 ───────────────────────────────────
# Problem: Wembanyama, Jokić, CJ McCollum dobivaju NO VALUE jer je threshold previsok
patch(
    "FIX 3 — MIN_EDGE_THRESHOLD: 0.04 → 0.025",
    "    MIN_EDGE_THRESHOLD = 0.04\n    if abs(p_over_model - p_over_mkt) < MIN_EDGE_THRESHOLD:",
    "    MIN_EDGE_THRESHOLD = 0.025\n    if abs(p_over_model - p_over_mkt) < MIN_EDGE_THRESHOLD:"
)

# ── FIX 4: Sigma floor u Monte Carlo bloku ────────────────────────────────────
# Problem: line*0.28 daje Jock Landaleu sigma=5.0 na liniji 7.5 = 67% od linije
patch(
    "FIX 4 — Sigma floor MC: 0.28 → 0.20, min 2.0 → 1.5",
    "    sigma_floor_mc = float(max(line_val * 0.28, 2.0))",
    "    sigma_floor_mc = float(max(line_val * 0.20, 1.5))"
)

# ── FIX 5: Sigma floor u build_player_context ─────────────────────────────────
patch(
    "FIX 5 — Sigma floor context: 0.28 → 0.20, min 2.0 → 1.5",
    "    sigma_floor = float(max(line_val * 0.28, 2.0)) if line_val > 0 else 2.0",
    "    sigma_floor = float(max(line_val * 0.20, 1.5)) if line_val > 0 else 1.5"
)

with open(SRC, "w", encoding="utf-8") as f:
    f.write(src)

print(f"\n{'='*50}")
print(f"✅ Gotovo! {applied}/5 fixova primijenjeno.")
print(f"Pokreni: streamlit run app.py")
print(f"{'='*50}")
print("""
SAŽETAK IZMJENA:
  Fix 1: EV cap 35% → 50%  (jake UNDER prilike više nisu ograničene)
  Fix 2: Market blend 55/45/35/25% → 45/30/20/12%  (proj se manje "vuče" prema liniji)
  Fix 3: Edge threshold 4.0% → 2.5%  (Wembanyama/Jokić dobivaju pick umjesto NO VALUE)
  Fix 4+5: Sigma floor 28%/min2.0 → 20%/min1.5  (uska distribucija za niske linije)
""")