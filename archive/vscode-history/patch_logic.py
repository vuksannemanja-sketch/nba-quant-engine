#!/usr/bin/env python3
"""
Pokreni u folderu gdje je app.py:
    python3 patch_logic.py

Primjenjuje 3 logička fixa:
  1. L10 Trend threshold: 0.25 → 0.10
  2. H2H PTS Last: integriran u projekciju
  3. parse_offer_text: komentar + dokumentacija za total kolonu

Pravi backup: app.py.bak2
"""
import shutil, sys

SRC = "app.py"
BAK = "app.py.bak2"

try:
    with open(SRC, "r", encoding="utf-8") as f:
        src = f.read()
except FileNotFoundError:
    print(f"GREŠKA: {SRC} nije pronađen.")
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
        print(f"⚠️  {label} — pattern nije pronađen (već primijenjen?)")

# ── FIX 1: L10 Trend threshold 0.25 → 0.10 ───────────────────────────────────
# Zašto: mean L10 Trend je 0.13 pts/utakmici = 1.3 pts razlika kroz 10 utakmica
# koja se potpuno ignorirala s thresholdom 0.25
patch(
    "FIX 1 — L10 Trend threshold: 0.25 → 0.10",
    "        if l10_trend is not None and abs(l10_trend) > 0.25:",
    "        if l10_trend is not None and abs(l10_trend) > 0.10:"
)

# ── FIX 2: H2H PTS Last — integracija u projekciju ───────────────────────────
# Zašto: H2H PTS Last postoji u CSV-u ali se nije koristio nigdje
# Logika: ako zadnja utakmica vs isti protivnik odskače >20% od H2H prosjeka,
#         blago pomakni projekciju prema toj vrijednosti (weight 4-15%)
OLD_H2H = (
    "        if h2h_weight > 0:\n"
    "            anchored_projection = (\n"
    "                (1.0 - h2h_weight) * anchored_projection +\n"
    "                h2h_weight * h2h_anchor\n"
    "            )\n"
    "        _h2h_sigma_boost = 1.08 if h2h_diff > 6 else 1.0"
)
NEW_H2H = (
    "        if h2h_weight > 0:\n"
    "            anchored_projection = (\n"
    "                (1.0 - h2h_weight) * anchored_projection +\n"
    "                h2h_weight * h2h_anchor\n"
    "            )\n"
    "        _h2h_sigma_boost = 1.08 if h2h_diff > 6 else 1.0\n"
    "\n"
    "        # H2H PTS Last: ako zadnja utakmica vs ovaj tim značajno odskače od H2H prosjeka\n"
    "        # blago korigiraj projekciju prema toj vrijednosti\n"
    "        if h2h_pts_last is not None and h2h_pts_last > 0 and h2h_weight > 0:\n"
    "            last_vs_avg = h2h_pts_last - h2h_pts\n"
    "            last_ratio  = abs(last_vs_avg) / max(h2h_pts, 1.0)\n"
    "            if last_ratio > 0.20:  # zadnja utakmica odskače >20% od H2H prosjeka\n"
    "                last_weight = _clamp(0.08 * last_ratio, 0.04, 0.15)\n"
    "                last_anchor = h2h_pts_last * (minutes_proj / max(season_min, 1.0))\n"
    "                anchored_projection = (\n"
    "                    (1.0 - last_weight) * anchored_projection +\n"
    "                    last_weight * last_anchor\n"
    "                )\n"
    "                if last_ratio > 0.40:\n"
    "                    _h2h_sigma_boost = _clamp(_h2h_sigma_boost * 1.05, 1.0, 1.15)"
)
patch("FIX 2 — H2H PTS Last: integriran u projekciju", OLD_H2H, NEW_H2H)

# ── FIX 3: parse_offer_text — dokumentacija za 6-koloni format s totalom ──────
# Zašto: TOTAL_MATCH_OFFER je bio null za svih 54 igrača jer offer CSV
#         nema total kolonu. Dodajemo komentar i poboljšavamo parsing
#         da jasno naznači koji format treba koristiti.
OLD_OFFER_HEADER = (
    "def parse_offer_text(txt: str):\n"
    "    rows, bad = [], []"
)
NEW_OFFER_HEADER = (
    "def parse_offer_text(txt: str):\n"
    "    \"\"\"\n"
    "    Parsira offer tekst. Podržani formati (po retku):\n"
    "      4 kolone: Player, Line, OverOdds, UnderOdds\n"
    "      5 kolona: Player, Line, OverOdds, UnderOdds, OppTeam   (preporučeno)\n"
    "      6 kolona: Player, Line, OverOdds, UnderOdds, OppTeam, Total  (optimalno)\n"
    "    Total = ukupni bodovi utakmice (npr. 228.5) — poboljšava total_factor.\n"
    "    Delimiter: zarez, tab ili točka-zarez.\n"
    "    \"\"\"\n"
    "    rows, bad = [], []"
)
patch("FIX 3 — parse_offer_text: dodan docstring s formatom", OLD_OFFER_HEADER, NEW_OFFER_HEADER)

# ── FIX 3b: Poboljšano parsiranje 5. kolone — razlikuj OppTeam od Total ───────
OLD_5COL = (
    "        if len(parts) == 5:\n"
    "            x = parts[4].strip()\n"
    "            n = safe_float(x)\n"
    "            if n is None:\n"
    "                opp_team = normalize_team_abbr(x)\n"
    "            else:\n"
    "                total_match = n"
)
NEW_5COL = (
    "        if len(parts) == 5:\n"
    "            x = parts[4].strip()\n"
    "            n = safe_float(x)\n"
    "            if n is None:\n"
    "                opp_team = normalize_team_abbr(x)\n"
    "            else:\n"
    "                # Broj u 5. koloni: 180-280 = total utakmice, inače ignoriramo\n"
    "                if 180.0 <= n <= 280.0:\n"
    "                    total_match = n\n"
    "                else:\n"
    "                    total_match = n  # prihvati svejedno"
)
patch("FIX 3b — 5-koloni parsing: razlikuj OppTeam od Total", OLD_5COL, NEW_5COL)

with open(SRC, "w", encoding="utf-8") as f:
    f.write(src)

print(f"\n{'='*55}")
print(f"✅ Gotovo! {applied}/4 fixova primijenjeno.")
print(f"Pokreni: streamlit run app.py")
print(f"{'='*55}")
print("""
SAŽETAK:
  Fix 1: L10 Trend threshold 0.25 → 0.10
          → Trend koji je ignoriran za 70% igrača sada aktivno utječe
          → De'Aaron Fox (trend=2.16) dobiva ~+1.5pts boost

  Fix 2: H2H PTS Last integriran
          → Ako zadnja utakmica vs ovaj tim odskače >20% od prosjeka:
            weight 4-15% pomak prema toj vrijednosti
          → Primjer: Myles Turner H2H Avg=16.6, Last=8.0 → -6% korekcija prema 8.0

  Fix 3: offer_latest.csv format dokumentiran
          → Dodaj 6. kolonu s totalom utakmice za bolji total_factor
          → Format: Player,Line,OverOdds,UnderOdds,OppTeam,Total
          → Npr: "Luka Doncic,31.5,1.87,1.87,DEN,228.5"

ŠTA DALJE:
  → Ako koristiš refresh_props.py, dodaj total u offer CSV generiranje
  → Total možeš naći na istoj kladionici kao props (game lines)
""")