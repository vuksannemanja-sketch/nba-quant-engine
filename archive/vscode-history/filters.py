"""
NBA_ENGINE FILTERS MODULE
=========================
Bazirano na analizi 885 pickova iz Marta 2026.
Kreirano: April 2026

Korištenje:
    from filters import apply_all_filters, get_premium_picks, get_filtered_stats
    
    filtered_df = apply_all_filters(df, model_type='SA')
"""

import pandas as pd
from typing import List, Tuple, Optional

# =============================================================================
# BLACKLIST IGRAČA - 0% HISTORICAL HIT RATE
# =============================================================================

BLACKLIST_PLAYERS: List[str] = [
    # 0% hit rate sa 5+ pickova - NIKAD NE IGRATI
    "Oso Ighodaro",
    "Scottie Barnes",
    "Jayson Tatum",
    "Ace Bailey",
    "Jaime Jaquez Jr.",
    "RJ Barrett",
    "Walter Clayton Jr.",
    "Devin Carter",
    "Jaylen Brown",
    "De'Aaron Fox",
    "Kristaps Porziņģis",
    "Miles Bridges",
    "Jaren Jackson Jr.",
    "Will Riley",
    "Precious Achiuwa",
    "Desmond Bane",
    # 0% hit rate sa 4 pickova
    "Kyle Kuzma",
    "Brandon Ingram",
    "Pelle Larsson",
    "Ja'Kobe Walter",
    "Kevin Huerter",
    "Khaman Maluach",
    "Dominick Barlow",
    "Christian Braun",
    "CJ McCollum",
    # 0% hit rate sa 3 pickova
    "Alperen Sengun",
    "Bobby Portis",
    "Donte DiVincenzo",
    "Duncan Robinson",
    "Justin Edwards",
    "Dean Wade",
    "Nick Richards",
    "Myles Turner",
    "P.J. Washington",
    "OG Anunoby",
    "Peyton Watson",
    "Rudy Gobert",
]

# =============================================================================
# UNDER BLACKLIST - VOLATILNI/MLADI IGRAČI
# =============================================================================

UNDER_BLACKLIST: List[str] = [
    # Mladi/volatilni - konstantno prelaze UNDER linije
    "Ace Bailey",           # +12.2 pts avg preko linije
    "Toumani Camara",       # +17.0 pts avg preko linije  
    "Walter Clayton Jr.",
    "Jarace Walker",
    "Devin Carter",
    "Khaman Maluach",
    "Oso Ighodaro",
    "Daniss Jenkins",
    "Payton Pritchard",     # +14.3 pts avg preko linije
    "Alperen Sengun",       # +14.5 pts avg preko linije
    "Isaiah Hartenstein",
    "Andre Jackson Jr.",
    "Brice Sensabaugh",
    "Sandro Mamukelashvili",
    "Brook Lopez",
    "Jalen Smith",
    "Taurean Prince",
    "Will Richard",
    "Kevin Huerter",
    # DODANO 1.4.2026 - svi 75%+ UNDER promašaji
    "Kam Jones",            # 80.1% UNDER MISS
    "Pat Spencer",          # 76.1% UNDER MISS (+4.5 over)
    "Isaac Okoro",          # 75.7% UNDER MISS (+3.5 over)
    "Kyle Filipowski",      # 68.3% UNDER MISS (+9.5 over!)
]

# =============================================================================
# PREMIUM WHITELIST - 100% HISTORICAL HIT RATE
# =============================================================================

PREMIUM_PLAYERS: List[str] = [
    # 100% hit rate, 4+ picka, 65%+ avg confidence
    "Jevon Carter",         # 4/4, 75.3% avg conf
    "Doug McDermott",       # 4/4, 74.6% avg conf
    "Ousmane Dieng",        # 5/5, 71.2% avg conf
    "Sidy Cissoko",         # 4/4, 70.5% avg conf
    "Jake LaRavia",         # 5/5, 69.5% avg conf
    "Reed Sheppard",        # 5/5, 68.2% avg conf
    "Collin Sexton",        # 5/5, 65.4% avg conf
    # 100% hit rate, 4+ picka (svi confidence nivoi)
    "Tre Jones",            # 6/6
    "Taylor Hendricks",     # 5/5
    "Andrew Nembhard",      # 4/4
    "Ausar Thompson",       # 4/4
    "Brandon Miller",       # 5/5
    "Daniel Gafford",       # 4/4
    "Pascal Siakam",        # 4/4
    "Kevin Durant",         # 4/4
    "Josh Hart",            # 4/4
    "Jalen Brunson",        # 5/5
    "Gui Santos",           # 4/4
    "Dylan Harper",         # 4/4
]

# =============================================================================
# VALUE PLAYERS - Visok hit rate, nizak confidence (model ih podcjenjuje)
# =============================================================================

VALUE_PLAYERS: List[str] = [
    # Hit Rate > 80%, Avg Conf < 60% - MODEL IH PODCJENJUJE
    "Kevin Durant",
    "Jalen Brunson",
    "Olivier-Maxence Prosper",
    "Josh Hart",
    "Gui Santos",
    "Dylan Harper",
    "Daniel Gafford",
    "Pascal Siakam",
    "Ausar Thompson",
    "Joel Embiid",
    "Cameron Johnson",
]

# =============================================================================
# CONFIDENCE THRESHOLDS
# =============================================================================

# Minimum confidence po modelu
MIN_CONFIDENCE_SA: float = 65.0      # SA radi najbolje na 75%+
MIN_CONFIDENCE_BEZ: float = 60.0     # BEZ je konzistentniji na nižim confidence

# Premium tier (highest priority)
PREMIUM_CONFIDENCE: float = 75.0     # 78.6% hit rate za SA na ovom nivou

# Confidence tiers za analizu
CONFIDENCE_TIERS: List[Tuple[float, float, str]] = [
    (75.0, 100.0, "PREMIUM"),
    (70.0, 75.0, "HIGH"),
    (65.0, 70.0, "MEDIUM"),
    (60.0, 65.0, "LOW"),
    (0.0, 60.0, "AVOID"),
]

# =============================================================================
# LINE RANGE FILTERS
# =============================================================================

# SA model - izbjegavati ove linije (loš hit rate)
SA_AVOID_LINE_RANGE: Tuple[float, float] = (20.0, 25.0)  # 28.9% hit rate

# BEZ model - optimalni range
BEZ_OPTIMAL_LINE_RANGE: Tuple[float, float] = (10.0, 25.0)  # 47-64% hit rate

# =============================================================================
# FILTER FUNCTIONS
# =============================================================================

def filter_blacklist(df: pd.DataFrame, player_col: str = 'Player') -> pd.DataFrame:
    """
    Uklanja igrače sa blackliste (0% historical hit rate).
    
    Args:
        df: DataFrame sa pickovima
        player_col: Naziv kolone sa imenima igrača
        
    Returns:
        Filtrirani DataFrame bez blacklist igrača
    """
    return df[~df[player_col].isin(BLACKLIST_PLAYERS)].copy()


def filter_under_blacklist(df: pd.DataFrame, 
                           player_col: str = 'Player',
                           pick_col: str = 'Model Pick') -> pd.DataFrame:
    """
    Uklanja UNDER pickove za volatilne/mlade igrače.
    
    Args:
        df: DataFrame sa pickovima
        player_col: Naziv kolone sa imenima igrača
        pick_col: Naziv kolone sa tipom picka (OVER/UNDER)
        
    Returns:
        Filtrirani DataFrame bez problematičnih UNDER pickova
    """
    mask = (df[pick_col].str.upper() == 'UNDER') & (df[player_col].isin(UNDER_BLACKLIST))
    return df[~mask].copy()


def filter_confidence(df: pd.DataFrame,
                      model_type: str = 'SA',
                      conf_col: str = 'Pick Confidence %',
                      min_conf: Optional[float] = None) -> pd.DataFrame:
    """
    Filtrira pickove po minimum confidence nivou.
    
    Args:
        df: DataFrame sa pickovima
        model_type: 'SA' ili 'BEZ'
        conf_col: Naziv kolone sa confidence vrijednostima
        min_conf: Custom minimum confidence (overrides default)
        
    Returns:
        Filtrirani DataFrame
    """
    if min_conf is None:
        min_conf = MIN_CONFIDENCE_SA if model_type.upper() == 'SA' else MIN_CONFIDENCE_BEZ
    
    return df[df[conf_col] >= min_conf].copy()


def filter_line_range(df: pd.DataFrame,
                      model_type: str = 'SA',
                      line_col: str = 'Line',
                      avoid: bool = True) -> pd.DataFrame:
    """
    Filtrira pickove po line range-u.
    
    Args:
        df: DataFrame sa pickovima
        model_type: 'SA' ili 'BEZ'
        line_col: Naziv kolone sa linijama
        avoid: True = izbjegavaj loše range, False = fokusiraj se na dobre
        
    Returns:
        Filtrirani DataFrame
    """
    if model_type.upper() == 'SA' and avoid:
        low, high = SA_AVOID_LINE_RANGE
        return df[~((df[line_col] >= low) & (df[line_col] <= high))].copy()
    elif model_type.upper() == 'BEZ' and not avoid:
        low, high = BEZ_OPTIMAL_LINE_RANGE
        return df[(df[line_col] >= low) & (df[line_col] <= high)].copy()
    
    return df.copy()


def mark_premium_players(df: pd.DataFrame,
                         player_col: str = 'Player') -> pd.DataFrame:
    """
    Označava premium igrače (100% historical hit rate).
    
    Args:
        df: DataFrame sa pickovima
        player_col: Naziv kolone sa imenima igrača
        
    Returns:
        DataFrame sa dodatnom kolonom 'Is_Premium'
    """
    df = df.copy()
    df['Is_Premium'] = df[player_col].isin(PREMIUM_PLAYERS)
    return df


def mark_value_players(df: pd.DataFrame,
                       player_col: str = 'Player') -> pd.DataFrame:
    """
    Označava value igrače (model ih podcjenjuje).
    
    Args:
        df: DataFrame sa pickovima
        player_col: Naziv kolone sa imenima igrača
        
    Returns:
        DataFrame sa dodatnom kolonom 'Is_Value'
    """
    df = df.copy()
    df['Is_Value'] = df[player_col].isin(VALUE_PLAYERS)
    return df


def assign_confidence_tier(df: pd.DataFrame,
                           conf_col: str = 'Pick Confidence %') -> pd.DataFrame:
    """
    Dodaje tier oznaku na osnovu confidence nivoa.
    
    Args:
        df: DataFrame sa pickovima
        conf_col: Naziv kolone sa confidence vrijednostima
        
    Returns:
        DataFrame sa dodatnom kolonom 'Confidence_Tier'
    """
    df = df.copy()
    
    def get_tier(conf):
        for low, high, tier in CONFIDENCE_TIERS:
            if low <= conf < high:
                return tier
        return "UNKNOWN"
    
    df['Confidence_Tier'] = df[conf_col].apply(get_tier)
    return df


def sort_picks(df: pd.DataFrame,
               conf_col: str = 'Pick Confidence %') -> pd.DataFrame:
    """
    Sortira pickove: Premium igrači prvi, zatim po confidence DESC.
    
    Args:
        df: DataFrame sa pickovima (mora imati 'Is_Premium' kolonu)
        conf_col: Naziv kolone sa confidence vrijednostima
        
    Returns:
        Sortirani DataFrame
    """
    if 'Is_Premium' not in df.columns:
        df = mark_premium_players(df)
    
    return df.sort_values(
        by=['Is_Premium', conf_col],
        ascending=[False, False]
    ).reset_index(drop=True)


# =============================================================================
# MAIN FILTER FUNCTION
# =============================================================================

def apply_all_filters(df: pd.DataFrame,
                      model_type: str = 'SA',
                      player_col: str = 'Player',
                      pick_col: str = 'Model Pick',
                      conf_col: str = 'Pick Confidence %',
                      line_col: str = 'Line',
                      min_confidence: Optional[float] = None,
                      apply_line_filter: bool = True,
                      verbose: bool = True) -> pd.DataFrame:
    """
    Primjenjuje sve filtere na DataFrame sa pickovima.
    
    Args:
        df: DataFrame sa pickovima
        model_type: 'SA' ili 'BEZ'
        player_col: Naziv kolone sa imenima igrača
        pick_col: Naziv kolone sa tipom picka
        conf_col: Naziv kolone sa confidence vrijednostima
        line_col: Naziv kolone sa linijama
        min_confidence: Custom minimum confidence
        apply_line_filter: Da li primjeniti line filter
        verbose: Da li printati statistike
        
    Returns:
        Filtrirani i sortirani DataFrame
    """
    original_count = len(df)
    
    # 1. Blacklist filter
    filtered = filter_blacklist(df, player_col)
    after_blacklist = len(filtered)
    
    # 2. Under blacklist filter
    filtered = filter_under_blacklist(filtered, player_col, pick_col)
    after_under = len(filtered)
    
    # 3. Confidence filter
    filtered = filter_confidence(filtered, model_type, conf_col, min_confidence)
    after_conf = len(filtered)
    
    # 4. Line filter (opciono)
    if apply_line_filter and line_col in filtered.columns:
        filtered = filter_line_range(filtered, model_type, line_col)
    after_line = len(filtered)
    
    # 5. Mark premium i value igrače
    filtered = mark_premium_players(filtered, player_col)
    filtered = mark_value_players(filtered, player_col)
    
    # 6. Assign confidence tier
    filtered = assign_confidence_tier(filtered, conf_col)
    
    # 7. Sort
    filtered = sort_picks(filtered, conf_col)
    
    if verbose:
        print(f"\n{'='*50}")
        print(f"FILTER STATS ({model_type} MODEL)")
        print(f"{'='*50}")
        print(f"Original picks:        {original_count}")
        print(f"After blacklist:       {after_blacklist} (-{original_count - after_blacklist})")
        print(f"After UNDER blacklist: {after_under} (-{after_blacklist - after_under})")
        print(f"After confidence:      {after_conf} (-{after_under - after_conf})")
        if apply_line_filter:
            print(f"After line filter:     {after_line} (-{after_conf - after_line})")
        print(f"{'='*50}")
        print(f"FINAL PICKS: {len(filtered)}")
        print(f"Premium picks: {filtered['Is_Premium'].sum()}")
        print(f"Value picks: {filtered['Is_Value'].sum()}")
        print(f"{'='*50}\n")
    
    return filtered


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_premium_picks(df: pd.DataFrame,
                      player_col: str = 'Player',
                      conf_col: str = 'Pick Confidence %') -> pd.DataFrame:
    """
    Vraća samo premium pickove (premium igrači + 75%+ confidence).
    """
    filtered = df[
        (df[player_col].isin(PREMIUM_PLAYERS)) | 
        (df[conf_col] >= PREMIUM_CONFIDENCE)
    ].copy()
    
    filtered = mark_premium_players(filtered, player_col)
    return sort_picks(filtered, conf_col)


def get_filtered_stats(df: pd.DataFrame,
                       result_col: str = 'Result') -> dict:
    """
    Vraća statistike za filtrirani DataFrame.
    """
    total = len(df)
    if total == 0:
        return {"total": 0, "hits": 0, "hit_rate": 0.0}
    
    hits = (df[result_col].str.upper().str.contains('HIT')).sum()
    
    return {
        "total": total,
        "hits": hits,
        "hit_rate": round(hits / total * 100, 2),
        "premium_count": df['Is_Premium'].sum() if 'Is_Premium' in df.columns else 0,
        "value_count": df['Is_Value'].sum() if 'Is_Value' in df.columns else 0,
    }


def is_blacklisted(player: str) -> bool:
    """Provjerava da li je igrač na blacklisti."""
    return player in BLACKLIST_PLAYERS


def is_under_blacklisted(player: str) -> bool:
    """Provjerava da li je igrač na UNDER blacklisti."""
    return player in UNDER_BLACKLIST


def is_premium(player: str) -> bool:
    """Provjerava da li je igrač premium."""
    return player in PREMIUM_PLAYERS


def is_value(player: str) -> bool:
    """Provjerava da li je igrač value pick."""
    return player in VALUE_PLAYERS


# =============================================================================
# QUICK CHECK FUNCTION (za pojedinačne pickove)
# =============================================================================

def check_pick(player: str, 
               pick_type: str, 
               confidence: float, 
               line: float,
               model_type: str = 'SA') -> dict:
    """
    Brza provjera pojedinačnog picka.
    
    Args:
        player: Ime igrača
        pick_type: 'OVER' ili 'UNDER'
        confidence: Confidence procenat
        line: Points linija
        model_type: 'SA' ili 'BEZ'
        
    Returns:
        Dict sa statusom i preporukama
    """
    result = {
        "player": player,
        "pick_type": pick_type,
        "confidence": confidence,
        "line": line,
        "status": "PASS",
        "warnings": [],
        "is_premium": is_premium(player),
        "is_value": is_value(player),
        "recommendation": "PLAY"
    }
    
    # Check blacklist
    if is_blacklisted(player):
        result["status"] = "BLOCKED"
        result["warnings"].append(f"🚫 {player} je na BLACKLIST (0% historical hit rate)")
        result["recommendation"] = "SKIP"
        return result
    
    # Check UNDER blacklist
    if pick_type.upper() == 'UNDER' and is_under_blacklisted(player):
        result["status"] = "BLOCKED"
        result["warnings"].append(f"⚠️ {player} je na UNDER BLACKLIST (volatilan igrač)")
        result["recommendation"] = "SKIP"
        return result
    
    # Check confidence
    min_conf = MIN_CONFIDENCE_SA if model_type.upper() == 'SA' else MIN_CONFIDENCE_BEZ
    if confidence < min_conf:
        result["status"] = "WARNING"
        result["warnings"].append(f"📉 Confidence {confidence}% je ispod minimuma ({min_conf}%)")
        result["recommendation"] = "RISKY"
    
    # Check line range for SA
    if model_type.upper() == 'SA':
        low, high = SA_AVOID_LINE_RANGE
        if low <= line <= high:
            result["status"] = "WARNING"
            result["warnings"].append(f"📊 Line {line} je u lošem range-u za SA model (20-25)")
            result["recommendation"] = "RISKY"
    
    # Premium boost
    if result["is_premium"]:
        result["warnings"].append(f"⭐ {player} je PREMIUM igrač (100% historical)")
        if result["recommendation"] != "SKIP":
            result["recommendation"] = "STRONG PLAY"
    
    # Value boost
    if result["is_value"]:
        result["warnings"].append(f"💎 {player} je VALUE igrač (model ga podcjenjuje)")
    
    # High confidence boost
    if confidence >= PREMIUM_CONFIDENCE:
        result["warnings"].append(f"🎯 PREMIUM CONFIDENCE ({confidence}%)")
        if result["recommendation"] not in ["SKIP", "RISKY"]:
            result["recommendation"] = "STRONG PLAY"
    
    return result


# =============================================================================
# EXPORT ZA STREAMLIT
# =============================================================================

def get_all_lists() -> dict:
    """Vraća sve liste za prikaz u UI."""
    return {
        "blacklist": BLACKLIST_PLAYERS,
        "under_blacklist": UNDER_BLACKLIST,
        "premium": PREMIUM_PLAYERS,
        "value": VALUE_PLAYERS,
    }


def get_filter_config() -> dict:
    """Vraća konfiguraciju filtera."""
    return {
        "min_confidence_sa": MIN_CONFIDENCE_SA,
        "min_confidence_bez": MIN_CONFIDENCE_BEZ,
        "premium_confidence": PREMIUM_CONFIDENCE,
        "sa_avoid_line_range": SA_AVOID_LINE_RANGE,
        "bez_optimal_line_range": BEZ_OPTIMAL_LINE_RANGE,
    }


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    # Test check_pick funkcije
    print("\n" + "="*60)
    print("FILTER MODULE TEST")
    print("="*60)
    
    test_cases = [
        ("Oso Ighodaro", "UNDER", 75.0, 8.5, "SA"),
        ("Ace Bailey", "UNDER", 70.0, 18.5, "SA"),
        ("Collin Sexton", "OVER", 68.0, 16.5, "SA"),
        ("Random Player", "OVER", 55.0, 22.0, "SA"),
        ("Jevon Carter", "UNDER", 78.0, 7.5, "SA"),
    ]
    
    for player, pick, conf, line, model in test_cases:
        result = check_pick(player, pick, conf, line, model)
        print(f"\n{player} | {pick} | {conf}% | Line {line}")
        print(f"  Status: {result['status']}")
        print(f"  Recommendation: {result['recommendation']}")
        for w in result['warnings']:
            print(f"  {w}")