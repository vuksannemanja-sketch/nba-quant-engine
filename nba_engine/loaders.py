"""Učitavanje CSV fajlova iz ``data/`` u standardizovane DataFrame-ove.

Sve funkcije su čiste (bez Streamlit keša) da bi radile i iz komandne linije i iz testova.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import previous_season, Settings
from .teams import ABBR_TO_TEAM_ID, TEAM_ID_TO_ABBR, normalize_team_abbr
from .utils import extract_injury_status, fix_usg_scale, normalize_name


# ---------------------------------------------------------------------------
# Pomoćne
# ---------------------------------------------------------------------------

def _s1d(df: pd.DataFrame, col: str) -> pd.Series:
    """Garantuj 1D Series bez obzira na duplirane kolone."""
    v = df[col]
    return (v.iloc[:, 0] if isinstance(v, pd.DataFrame) else v).reset_index(drop=True)


def _dedupe_cols(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[:, ~df.columns.duplicated()]


def _std_rename(df: pd.DataFrame) -> pd.DataFrame:
    """Standardizuj nazive kolona (PLAYER_NAME, TEAM_ABBR, TEAM, TEAM_ID) i popuni TEAM_ABBR iz TEAM_ID."""
    rename_map: Dict[str, str] = {}
    for c in df.columns:
        cl = c.strip().upper()
        if cl in ("PLAYER", "PLAYER_NAME", "NAME"):
            rename_map[c] = "PLAYER_NAME"
        elif cl in ("TEAM_ABBR", "TEAM_ABBREVIATION", "TM"):
            rename_map[c] = "TEAM_ABBR"
        elif cl in ("TEAM", "TEAM_NAME"):
            rename_map[c] = "TEAM"
        elif cl == "TEAM_ID":
            rename_map[c] = "TEAM_ID"
    df = df.rename(columns=rename_map)
    if "TEAM_ID" in df.columns:
        has_abbr = "TEAM_ABBR" in df.columns
        abbr_mostly_na = False
        if has_abbr:
            col = df["TEAM_ABBR"]
            if isinstance(col, pd.DataFrame):
                col = col.iloc[:, 0]
            abbr_mostly_na = bool(float(col.isna().mean()) > 0.5)
        if not has_abbr or abbr_mostly_na:
            df["TEAM_ABBR"] = pd.to_numeric(df["TEAM_ID"], errors="coerce").apply(
                lambda x: TEAM_ID_TO_ABBR.get(int(x)) if pd.notna(x) else None)
    return df


def _exists(path) -> bool:
    return path is not None and os.path.exists(path)


# ---------------------------------------------------------------------------
# Timovi
# ---------------------------------------------------------------------------

def load_teams_csv(path: os.PathLike) -> pd.DataFrame:
    df = pd.read_csv(path)
    rename_map: Dict[str, str] = {}
    for c in df.columns:
        cl = c.strip().upper()
        if cl in ("TEAM", "TEAM_NAME", "NAME"):
            rename_map[c] = "TEAM_NAME"
        elif cl == "TEAM_ID":
            rename_map[c] = "TEAM_ID"
        elif cl in ("TEAM_ABBR", "TEAM_ABBREVIATION"):
            rename_map[c] = "TEAM_ABBR"
    df = df.rename(columns=rename_map)
    for c in ("OFF_RATING", "DEF_RATING", "PACE", "NET_RATING", "PTS", "OPP_PTS"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "TEAM_ID" in df.columns:
        sample = df["TEAM_ID"].dropna().astype(str).str.strip().head(10)
        if len(sample) and sample.str.fullmatch(r"[A-Z]{2,4}").all():
            df["TEAM_ABBR"] = df["TEAM_ID"].astype(str).str.strip().str.upper()
            df["TEAM_NUMERIC_ID"] = df["TEAM_ABBR"].apply(
                lambda x: ABBR_TO_TEAM_ID.get(str(x).strip().upper()) if pd.notna(x) else None)
        else:
            if "TEAM_ABBR" in df.columns:
                df["TEAM_ABBR"] = df["TEAM_ABBR"].map(normalize_team_abbr)
            elif "TEAM_NAME" in df.columns:
                df["TEAM_ABBR"] = df["TEAM_NAME"].map(normalize_team_abbr)
            else:
                df["TEAM_ABBR"] = df["TEAM_ID"].map(normalize_team_abbr)
            df["TEAM_NUMERIC_ID"] = pd.to_numeric(df["TEAM_ID"], errors="coerce").fillna(
                pd.Series(df["TEAM_ABBR"].apply(
                    lambda x: ABBR_TO_TEAM_ID.get(str(x).upper()) if pd.notna(x) else None
                ), dtype=object))
    else:
        if "TEAM_ABBR" in df.columns:
            df["TEAM_ABBR"] = df["TEAM_ABBR"].map(normalize_team_abbr)
        elif "TEAM_NAME" in df.columns:
            df["TEAM_ABBR"] = df["TEAM_NAME"].map(normalize_team_abbr)
        else:
            df["TEAM_ABBR"] = np.nan
        df["TEAM_NUMERIC_ID"] = _s1d(df, "TEAM_ABBR").apply(
            lambda x: ABBR_TO_TEAM_ID.get(str(x).strip().upper()) if pd.notna(x) else None)
    if "NET_RATING" not in df.columns:
        if "OFF_RATING" in df.columns and "DEF_RATING" in df.columns:
            df["NET_RATING"] = df["OFF_RATING"] - df["DEF_RATING"]
        elif "PTS" in df.columns and "OPP_PTS" in df.columns:
            df["NET_RATING"] = df["PTS"] - df["OPP_PTS"]
        else:
            df["NET_RATING"] = 0.0
    return df


# ---------------------------------------------------------------------------
# Igrači (glavni + base/advanced/misc spojeni)
# ---------------------------------------------------------------------------

_NUMERIC_PLAYER_COLS = (
    "MIN", "PTS", "FGA", "FGM", "FG_PCT", "FG3A", "FG3_PCT", "FTA", "FT_PCT",
    "USG_PCT", "TS_PCT", "EFG_PCT", "TOV_PCT", "TM_TOV_PCT", "TPAR", "FTR",
    "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE", "PIE", "POSS", "AST_PCT",
    "AST_RATIO", "AST_TO", "REB_PCT", "OREB_PCT", "DREB_PCT", "PTS_PAINT",
    "PTS_FB", "PTS_2ND_CHANCE", "PTS_OFF_TOV", "PFD", "PF", "BLK", "BLKA",
    "OPP_PTS_OFF_TOV", "OPP_PTS_2ND_CHANCE", "OPP_PTS_FB", "OPP_PTS_PAINT",
    "PLUS_MINUS", "NBA_FANTASY_PTS", "GP", "W_PCT",
)

_UPDATE_COLS = {
    "TEAM_ABBR", "TEAM_NUMERIC_ID", "GP", "USG_PCT", "TS_PCT", "EFG_PCT",
    "FG3A", "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE", "PIE",
    "PTS_PAINT", "PTS_FB", "PTS_2ND_CHANCE", "PTS_OFF_TOV", "PFD", "PLUS_MINUS",
    "OPP_PTS_OFF_TOV", "OPP_PTS_2ND_CHANCE", "OPP_PTS_FB", "OPP_PTS_PAINT",
    "AST_RATIO", "AST_TO", "AST_PCT", "TOV_PCT", "FG_PCT", "FG3_PCT", "FT_PCT",
}


def _prepare_players(path, label: str) -> Optional[pd.DataFrame]:
    if not _exists(path):
        return None
    df = pd.read_csv(path).reset_index(drop=True)
    df = _dedupe_cols(df)
    df = _std_rename(df)
    df = fix_usg_scale(df)
    df[f"SRC_{label}"] = 1
    if "PLAYER_NAME" not in df.columns:
        return None
    df["NAME_KEY"] = df["PLAYER_NAME"].astype(str).map(normalize_name)

    if "TEAM_ABBR" in df.columns:
        df["TEAM_ABBR"] = _s1d(df, "TEAM_ABBR").map(normalize_team_abbr)
    elif "TEAM" in df.columns:
        df["TEAM_ABBR"] = _s1d(df, "TEAM").map(normalize_team_abbr)
    elif "TEAM_ID" in df.columns:
        df["TEAM_ABBR"] = _s1d(df, "TEAM_ID").map(normalize_team_abbr)
    else:
        df["TEAM_ABBR"] = np.nan

    tid_raw = df.get("TEAM_ID", pd.Series(dtype=float))
    if isinstance(tid_raw, pd.DataFrame):
        tid_raw = tid_raw.iloc[:, 0]
    df["TEAM_NUMERIC_ID"] = pd.to_numeric(tid_raw, errors="coerce").reset_index(drop=True)

    abbr_s = _s1d(df, "TEAM_ABBR")
    mapped = abbr_s.apply(lambda x: ABBR_TO_TEAM_ID.get(str(x).strip().upper()) if pd.notna(x) else None)
    num = pd.to_numeric(df["TEAM_NUMERIC_ID"], errors="coerce").reset_index(drop=True)
    df["TEAM_NUMERIC_ID"] = num.where(num.notna(), mapped)
    return df


def load_players_merged(main_path, base_path=None, adv_path=None, misc_path=None) -> pd.DataFrame:
    """Spoji glavni CSV igrača sa base/advanced/misc tabelama i izračunaj izvedene kolone (PPM, FGA_PM...)."""
    if not _exists(main_path):
        raise ValueError("Glavni players CSV nije pronađen.")

    main = _prepare_players(main_path, "MAIN")
    if main is None:
        raise ValueError("players csv missing PLAYER_NAME column.")
    merged = main.copy()

    for path, label in ((base_path, "BASE"), (adv_path, "ADV"), (misc_path, "MISC")):
        extra_df = _prepare_players(path, label)
        if extra_df is None:
            continue
        join_cols = [c for c in ("NAME_KEY", "PLAYER_ID") if c in merged.columns and c in extra_df.columns]
        key = ["PLAYER_ID"] if "PLAYER_ID" in join_cols else ["NAME_KEY"]
        extra_df = extra_df.sort_values(key).drop_duplicates(key)
        extra_cols = [c for c in extra_df.columns if c not in merged.columns or c in _UPDATE_COLS]
        extra_slim = extra_df[key + [c for c in extra_cols if c not in key]].copy()
        merged = merged.merge(extra_slim, on=key, how="left", suffixes=("", "__X"))

        seen_x: set = set()
        for c in list(merged.columns):
            if not c.endswith("__X") or c in seen_x or c not in merged.columns:
                continue
            seen_x.add(c)
            base_col = c[:-3]
            col_x = _s1d(merged, c)
            if base_col in merged.columns:
                merged[base_col] = _s1d(merged, base_col).combine_first(col_x)
            else:
                merged[base_col] = col_x
            merged = merged.drop(columns=[cc for cc in merged.columns if cc == c], errors="ignore")
            merged = _dedupe_cols(merged)
        merged = _dedupe_cols(merged)

    merged = _dedupe_cols(merged)
    if "PLAYER_NAME" not in merged.columns:
        raise ValueError("players csv missing PLAYER_NAME column.")
    if "MIN" not in merged.columns:
        raise ValueError("players csv missing MIN column.")

    for c in _NUMERIC_PLAYER_COLS:
        if c in merged.columns:
            merged[c] = pd.to_numeric(merged[c], errors="coerce")

    merged = fix_usg_scale(merged)

    if "FG3A" not in merged.columns or merged["FG3A"].isna().mean() > 0.5:
        if "3PA" in merged.columns:
            fg3a_ex = merged.get("FG3A", pd.Series(dtype=float))
            merged["FG3A"] = fg3a_ex.combine_first(pd.to_numeric(merged["3PA"], errors="coerce"))
        else:
            merged["FG3A"] = np.nan

    merged["TEAM_ABBR"] = merged["TEAM_ABBR"].map(normalize_team_abbr)
    merged["TEAM_NUMERIC_ID"] = pd.to_numeric(merged["TEAM_NUMERIC_ID"], errors="coerce").fillna(
        merged["TEAM_ABBR"].apply(lambda x: ABBR_TO_TEAM_ID.get(x) if pd.notna(x) else None))

    min_safe = pd.to_numeric(merged["MIN"], errors="coerce").replace(0, np.nan)

    def _per_min(col: str) -> pd.Series:
        return (pd.to_numeric(merged.get(col), errors="coerce") / min_safe).replace([np.inf, -np.inf], np.nan)

    merged["PPM"] = _per_min("PTS")
    merged["FGA_PM"] = _per_min("FGA")
    merged["FTA_PM"] = _per_min("FTA")
    merged["FG3A_PM"] = _per_min("FG3A")
    merged["PFD_PM"] = _per_min("PFD")
    merged["POSS_PM"] = _per_min("POSS")
    merged["PPM"] = merged["PPM"].fillna(0.55).clip(0.20, 1.25)
    return merged


# ---------------------------------------------------------------------------
# Ozljede
# ---------------------------------------------------------------------------

def load_injuries_csv(path) -> Optional[pd.DataFrame]:
    if not _exists(path):
        return None
    df = pd.read_csv(path)
    rename_map: Dict[str, str] = {}
    for c in df.columns:
        cl = c.strip().upper()
        if cl in ("PLAYER", "PLAYER_NAME", "NAME"):
            rename_map[c] = "PLAYER"
        elif cl in ("TEAM", "TEAM_NAME"):
            rename_map[c] = "TEAM"
        elif cl in ("TEAM_ABBR", "TEAM_ABBREVIATION"):
            rename_map[c] = "TEAM_ABBR"
        elif cl in ("DESCRIPTION", "STATUS_NOTE", "NOTE"):
            rename_map[c] = "DESCRIPTION"
    df = df.rename(columns=rename_map)
    if "TEAM_ABBR" in df.columns:
        df["TEAM_ABBR"] = df["TEAM_ABBR"].map(normalize_team_abbr)
    elif "TEAM" in df.columns:
        df["TEAM_ABBR"] = df["TEAM"].map(normalize_team_abbr)
    else:
        df["TEAM_ABBR"] = np.nan
    if "STATUS" not in df.columns:
        df["STATUS"] = df["DESCRIPTION"].astype(str).map(extract_injury_status) \
            if "DESCRIPTION" in df.columns else "UNKNOWN"
    if "PLAYER" in df.columns:
        df["NAME_KEY"] = df["PLAYER"].astype(str).map(normalize_name)
    return df


def fill_injury_teams(inj_df: Optional[pd.DataFrame], players_df: pd.DataFrame) -> Tuple[Optional[pd.DataFrame], int]:
    """Popuni praznu kolonu tima u tabeli ozljeda iz baze igrača (spajanje po ključu imena).

    Vraća (tabela, broj popunjenih redova). Ne mijenja postojeće vrijednosti tima.
    """
    if inj_df is None or inj_df.empty or "NAME_KEY" not in inj_df.columns:
        return inj_df, 0
    if players_df is None or "NAME_KEY" not in players_df.columns or "TEAM_ABBR" not in players_df.columns:
        return inj_df, 0
    df = inj_df.copy()
    if "TEAM_ABBR" not in df.columns:
        df["TEAM_ABBR"] = np.nan
    lookup = (players_df.dropna(subset=["TEAM_ABBR"])
              .drop_duplicates("NAME_KEY").set_index("NAME_KEY")["TEAM_ABBR"])
    current = df["TEAM_ABBR"].astype(object)
    missing = current.isna() | (current.astype(str).str.strip() == "")
    filled = df["NAME_KEY"].map(lookup).where(missing)
    n = int(filled.notna().sum())
    if n:
        df["TEAM_ABBR"] = current.where(filled.isna(), filled)
    return df, n


# ---------------------------------------------------------------------------
# Forma, matchup, H2H, B2B
# ---------------------------------------------------------------------------

def load_l10_csv(path) -> Optional[pd.DataFrame]:
    if not _exists(path):
        return None
    try:
        df = pd.read_csv(path)
        rename: Dict[str, str] = {}
        for c in df.columns:
            cl = c.strip().upper()
            if cl in ("PLAYER_NAME", "PLAYER", "NAME", "IME_IGRAČA", "IME_IGRACA"):
                rename[c] = "PLAYER_NAME"
            elif cl in ("L10_PTS", "L10_BODOVI"):
                rename[c] = "L10_PTS"
            elif cl in ("L5_PTS", "L5_BODOVI"):
                rename[c] = "L5_PTS"
            elif cl in ("L3_PTS", "L3_BODOVI"):
                rename[c] = "L3_PTS"
            elif cl == "L10_MIN":
                rename[c] = "L10_MIN"
            elif cl == "L10_STD":
                rename[c] = "L10_STD"
            elif cl in ("TREND_SLOPE", "NAGIB_TRENDA"):
                rename[c] = "TREND_SLOPE"
            elif cl in ("LAST_PTS", "ZADNJE_BODOVI"):
                rename[c] = "LAST_PTS"
            elif cl in ("NAME_KEY", "KLJUČ_IMENA", "KLJUC_IMENA"):
                rename[c] = "NAME_KEY"
        df = df.rename(columns=rename)
        for col in ("L10_PTS", "L5_PTS", "L3_PTS", "L10_MIN", "L10_STD", "TREND_SLOPE", "LAST_PTS"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "NAME_KEY" not in df.columns or df["NAME_KEY"].isna().all():
            if "PLAYER_NAME" in df.columns:
                df["NAME_KEY"] = df["PLAYER_NAME"].astype(str).map(normalize_name)
        return df
    except Exception:
        return None


def _load_matchup_csv(path, skip_cols: Tuple[str, ...]) -> Optional[pd.DataFrame]:
    if not _exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if "TEAM_ABBREVIATION" in df.columns:
            df = df.rename(columns={"TEAM_ABBREVIATION": "TEAM_ABBR"})
        if "TEAM_ID" in df.columns and "TEAM_ABBR" not in df.columns:
            df["TEAM_ABBR"] = df["TEAM_ID"].apply(lambda x: TEAM_ID_TO_ABBR.get(x))
        for col in df.columns:
            if col not in skip_cols:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception:
        return None


def load_def_matchup_csv(path) -> Optional[pd.DataFrame]:
    return _load_matchup_csv(path, skip_cols=("TEAM_ABBR", "TEAM_NAME", "POSITION", "TEAM_ID"))


def load_off_matchup_csv(path) -> Optional[pd.DataFrame]:
    return _load_matchup_csv(path, skip_cols=("TEAM_ABBR", "TEAM_NAME", "TEAM_ID"))


def load_h2h_csv(path) -> Optional[pd.DataFrame]:
    if not _exists(path):
        return None
    try:
        df = pd.read_csv(path)
        rename_map: Dict[str, str] = {}
        for c in df.columns:
            cl = c.strip().upper()
            if cl in ("PLAYER_NAME", "PLAYER", "NAME", "IME_IGRAČA", "IME_IGRACA"):
                rename_map[c] = "PLAYER_NAME"
            elif cl in ("OPP_TEAM", "OPP_TIM", "PROTIVNIK", "OPPONENT"):
                rename_map[c] = "OPP_TEAM"
            elif cl in ("H2H_PTS_AVG", "PROSJEK_BODOVA_U_H2H"):
                rename_map[c] = "H2H_PTS_AVG"
            elif cl in ("H2H_GAMES", "U_H2H_IGRAMA"):
                rename_map[c] = "H2H_GAMES"
            elif cl in ("H2H_PTS_LAST", "POSLJEDNJI_BOD_U_H2H"):
                rename_map[c] = "H2H_PTS_LAST"
            elif cl in ("NAME_KEY", "KLJUČ_IMENA", "KLJUC_IMENA"):
                rename_map[c] = "NAME_KEY"
        df = df.rename(columns=rename_map)
        for col in ("H2H_PTS_AVG", "H2H_PTS_LAST", "H2H_GAMES"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "NAME_KEY" not in df.columns or df["NAME_KEY"].isna().all():
            if "PLAYER_NAME" in df.columns:
                df["NAME_KEY"] = df["PLAYER_NAME"].astype(str).map(normalize_name)
        return df
    except Exception:
        return None


def load_b2b_csv(path) -> Optional[pd.DataFrame]:
    if not _exists(path):
        return None
    try:
        df = pd.read_csv(path)
        rename: Dict[str, str] = {}
        for c in df.columns:
            cl = c.strip().upper()
            if cl == "GAME_DATE":
                rename[c] = "GAME_DATE"
            elif cl == "TEAM_ABBR":
                rename[c] = "TEAM_ABBR"
            elif cl == "IS_B2B":
                rename[c] = "IS_B2B"
        df = df.rename(columns=rename)
        if "GAME_DATE" not in df.columns or "TEAM_ABBR" not in df.columns:
            return None
        df["IS_B2B"] = df["IS_B2B"].astype(str).str.lower().isin(("true", "1", "yes"))
        df["GAME_DATE"] = df["GAME_DATE"].astype(str).str.strip()
        df["TEAM_ABBR"] = df["TEAM_ABBR"].astype(str).str.strip().str.upper()
        return df
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Sve zajedno
# ---------------------------------------------------------------------------

@dataclass
class DataBundle:
    """Svi učitani podaci za jednu analizu."""
    players: pd.DataFrame
    teams: pd.DataFrame
    injuries: Optional[pd.DataFrame] = None
    h2h: Optional[pd.DataFrame] = None
    l10: Optional[pd.DataFrame] = None
    def_matchup: Optional[pd.DataFrame] = None
    off_matchup: Optional[pd.DataFrame] = None
    b2b: Optional[pd.DataFrame] = None
    paths: Dict[str, Optional[Path]] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    prior_info: Dict[str, object] = field(default_factory=dict)   # dopuna prošlom sezonom (vidi prior.py)

    @property
    def league_pts_std(self) -> float:
        return float(pd.to_numeric(self.players["PTS"], errors="coerce").dropna().std() or 6.0)

    def summary(self) -> Dict[str, int]:
        def _n(df):
            return 0 if df is None else int(len(df))
        return {"players": _n(self.players), "teams": _n(self.teams), "injuries": _n(self.injuries),
                "h2h": _n(self.h2h), "l10": _n(self.l10), "def_matchup": _n(self.def_matchup),
                "off_matchup": _n(self.off_matchup), "b2b": _n(self.b2b)}


class MissingDataError(RuntimeError):
    """Nedostaje obavezan CSV (igrači ili timovi)."""


def _apply_prior_season(settings: Settings, players: pd.DataFrame, teams: pd.DataFrame,
                        notes: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, object]]:
    """Rana sezona: dopuni igrače i timove prošlom sezonom ako njeni fajlovi postoje (vidi prior.py)."""
    from .prior import blend_players, blend_teams
    prev = previous_season(settings.season)
    try:
        prior_settings = Settings.load(data_dir=settings.data_dir, season=prev, env_file=settings.env_file,
                                       history_dir=settings.history_dir)
        ppaths = prior_settings.all_csv_paths()
    except Exception as e:  # noqa: BLE001
        notes.append(f"Prošla sezona ({prev}) nije dostupna: {e}")
        return players, teams, {"season": prev, "available": False}
    if ppaths.get("players_main") is None or ppaths.get("teams") is None:
        return players, teams, {"season": prev, "available": False}
    try:
        prior_players = load_players_merged(ppaths["players_main"], ppaths["players_base"],
                                            ppaths["players_adv"], ppaths["players_misc"])
        prior_teams = load_teams_csv(ppaths["teams"])
    except Exception as e:  # noqa: BLE001
        notes.append(f"Prošla sezona ({prev}) nije učitana: {e}")
        return players, teams, {"season": prev, "available": False}
    players, pinfo = blend_players(players, prior_players)
    teams, tinfo = blend_teams(teams, prior_teams)
    info: Dict[str, object] = {"season": prev, "available": True, "players_blended": pinfo["blended"],
                               "players_mean_prior_weight": pinfo["mean_prior_weight"], "teams_blended": tinfo["blended"]}
    if pinfo["blended"] or tinfo["blended"]:
        notes.append(f"Rana sezona: {pinfo['blended']} igrača i {tinfo['blended']} timova dopunjeno prošlom sezonom ({prev}); "
                     f"prosječna težina prošle sezone kod dopunjenih igrača {pinfo['mean_prior_weight']:.0%}.")
    return players, teams, info


def load_bundle(settings: Settings, fill_injury_team_from_players: bool = True,
                blend_prior_season: bool = True) -> DataBundle:
    """Učitaj sve CSV fajlove prema podešavanjima.

    ``fill_injury_team_from_players``: ako tabela ozljeda nema tim (prazna kolona),
    dopuni ga iz baze igrača po imenu — bez toga model ozljeda nema efekta.
    ``blend_prior_season``: na početku sezone (do 20 utakmica) statistiku igrača i timova dopuni
    prošlom sezonom, srazmjerno broju odigranih utakmica (``prior.py``). Isključi za staro ponašanje.
    """
    paths = settings.all_csv_paths()
    if paths["players_main"] is None or paths["teams"] is None:
        missing = [k for k in ("players_main", "teams") if paths[k] is None]
        raise MissingDataError(
            "Nedostaje obavezan CSV: " + ", ".join(missing) +
            f" (traženo u {settings.data_dir}, sezona {settings.season}). Pokreni osvježavanje podataka.")

    notes: List[str] = []
    players = load_players_merged(paths["players_main"], paths["players_base"],
                                  paths["players_adv"], paths["players_misc"])
    teams = load_teams_csv(paths["teams"])
    prior_info: Dict[str, object] = {}
    if blend_prior_season:
        players, teams, prior_info = _apply_prior_season(settings, players, teams, notes)
    injuries = load_injuries_csv(paths["injuries"])
    if fill_injury_team_from_players and injuries is not None:
        injuries, n_filled = fill_injury_teams(injuries, players)
        if n_filled:
            notes.append(f"Ozljede: tim dopunjen iz baze igrača za {n_filled} redova.")

    return DataBundle(
        players=players, teams=teams, injuries=injuries,
        h2h=load_h2h_csv(paths["h2h"]), l10=load_l10_csv(paths["l10"]),
        def_matchup=load_def_matchup_csv(paths["def_matchup"]),
        off_matchup=load_off_matchup_csv(paths["off_matchup"]),
        b2b=load_b2b_csv(paths["b2b"]),
        paths=paths, notes=notes, prior_info=prior_info,
    )
