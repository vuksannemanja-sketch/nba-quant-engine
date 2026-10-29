#!/usr/bin/env python3
"""
Pokreni u folderu gdje je app.py:
    python3 patch_app.py
"""
import shutil, sys

SRC = "app.py"
BAK = "app.py.bak"

try:
    with open(SRC, "r", encoding="utf-8") as f:
        src = f.read()
except FileNotFoundError:
    print(f"GREŠKA: {SRC} nije pronađen. Pokreni iz foldera gdje je app.py.")
    sys.exit(1)

shutil.copy2(SRC, BAK)
print(f"✅ Backup: {BAK}")

fixes_applied = 0

# ── FIX 1 ─────────────────────────────────────────────────────────────────────
OLD1 = "        df = pd.read_csv(path)\n        df = _std_rename(df)"
NEW1 = "        df = pd.read_csv(path)\n        df = _dedupe_cols(df)          # FIX 1\n        df = _std_rename(df)"
if OLD1 in src:
    src = src.replace(OLD1, NEW1, 1); fixes_applied += 1
    print("✅ FIX 1: _dedupe_cols u prepare()")
else:
    print("⚠️  FIX 1 preskocen (vec primijenjen)")

# ── FIX 2 ─────────────────────────────────────────────────────────────────────
OLD2 = '        df["TEAM_NUMERIC_ID"] = df["TEAM_NUMERIC_ID"].fillna(df["TEAM_ABBR"].map(lambda x: ABBR_TO_TEAM_ID.get(x)))'
NEW2 = (
    '        _abbr_s = df["TEAM_ABBR"]\n'
    '        if isinstance(_abbr_s, pd.DataFrame): _abbr_s = _abbr_s.iloc[:, 0]\n'
    '        df["TEAM_NUMERIC_ID"] = df["TEAM_NUMERIC_ID"].fillna(\n'
    '            _abbr_s.map(lambda x: ABBR_TO_TEAM_ID.get(x) if isinstance(x, str) else None)\n'
    '        )  # FIX 2'
)
if OLD2 in src:
    src = src.replace(OLD2, NEW2, 1); fixes_applied += 1
    print("✅ FIX 2: sigurna fillna u prepare()")
else:
    print("⚠️  FIX 2 preskocen (vec primijenjen)")

# ── FIX 3 + 4 — zamijeni cijelu __X merge petlju sigurnom verzijom ────────────
# Stara verzija ima 3 buga:
#   - list(merged.columns) hvata snapshot, ali inplace drop mijenja df tokom iter
#   - merged[base_col] moze biti DataFrame ako su duplikovane kolone
#   - merged[c] puca KeyError jer je c vec dropovan
# Rjesenje: _dedupe_cols(merged) PRIJE petlje + provjera c in merged.columns
# ─────────────────────────────────────────────────────────────────────────────
OLD34 = (
    '        for c in list(merged.columns):\n'
    '            if c.endswith("__X"):\n'
    '                base_col = c[:-3]\n'
    '                if base_col in merged.columns:\n'
    '                    merged[base_col] = merged[base_col].combine_first(merged[c])\n'
    '                    merged.drop(columns=[c], inplace=True)\n'
    '                else:\n'
    '                    merged.rename(columns={c: base_col}, inplace=True)'
)
NEW34 = (
    '        # FIX 3+4: dedupe prije petlje + sigurna combine_first\n'
    '        merged = _dedupe_cols(merged)\n'
    '        for c in [col for col in merged.columns if col.endswith("__X")]:\n'
    '            if c not in merged.columns:\n'
    '                continue\n'
    '            base_col = c[:-3]\n'
    '            if base_col in merged.columns:\n'
    '                _left  = merged[base_col]\n'
    '                _right = merged[c]\n'
    '                if isinstance(_left,  pd.DataFrame): _left  = _left.iloc[:, 0]\n'
    '                if isinstance(_right, pd.DataFrame): _right = _right.iloc[:, 0]\n'
    '                merged[base_col] = _left.combine_first(_right)\n'
    '                merged.drop(columns=[c], inplace=True)\n'
    '            else:\n'
    '                merged.rename(columns={c: base_col}, inplace=True)'
)
if OLD34 in src:
    src = src.replace(OLD34, NEW34, 1); fixes_applied += 1
    print("✅ FIX 3+4: sigurna __X merge petlja")
else:
    # Pokusaj alternate — ako je fix3 bio primijenjen, petlja izgleda drugacije
    OLD34b = (
        '        for c in list(merged.columns):\n'
        '            if c.endswith("__X"):\n'
        '                base_col = c[:-3]\n'
        '                if base_col in merged.columns:\n'
        '                    # FIX 3: guard against duplicate cols returning DataFrame\n'
        '                    _left  = merged[base_col]\n'
        '                    _right = merged[c]\n'
        '                    if isinstance(_left,  pd.DataFrame): _left  = _left.iloc[:, 0]\n'
        '                    if isinstance(_right, pd.DataFrame): _right = _right.iloc[:, 0]\n'
        '                    merged[base_col] = _left.combine_first(_right)\n'
        '                    merged.drop(columns=[c], inplace=True)\n'
        '                else:\n'
        '                    merged.rename(columns={c: base_col}, inplace=True)'
    )
    NEW34b = (
        '        # FIX 3+4: dedupe prije petlje + sigurna combine_first\n'
        '        merged = _dedupe_cols(merged)\n'
        '        for c in [col for col in merged.columns if col.endswith("__X")]:\n'
        '            if c not in merged.columns:\n'
        '                continue\n'
        '            base_col = c[:-3]\n'
        '            if base_col in merged.columns:\n'
        '                _left  = merged[base_col]\n'
        '                _right = merged[c]\n'
        '                if isinstance(_left,  pd.DataFrame): _left  = _left.iloc[:, 0]\n'
        '                if isinstance(_right, pd.DataFrame): _right = _right.iloc[:, 0]\n'
        '                merged[base_col] = _left.combine_first(_right)\n'
        '                merged.drop(columns=[c], inplace=True)\n'
        '            else:\n'
        '                merged.rename(columns={c: base_col}, inplace=True)'
    )
    if OLD34b in src:
        src = src.replace(OLD34b, NEW34b, 1); fixes_applied += 1
        print("✅ FIX 3+4 (alt): sigurna __X merge petlja")
    else:
        print("⚠️  FIX 3+4 nije pronađen — prijavi grešku")

with open(SRC, "w", encoding="utf-8") as f:
    f.write(src)

print(f"\n✅ Gotovo! {fixes_applied} fix(a) primijenjen(a).")
print("Pokreni: streamlit run app.py")