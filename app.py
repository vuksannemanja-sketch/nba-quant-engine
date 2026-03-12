import os
import re
import time
import subprocess
import sys
import difflib
import unicodedata
import numpy as np
import pandas as pd
import streamlit as st

# =====================================================
# CONFIG
# =====================================================

SEASON = "2025-26"

DATA_DIR_CANDIDATES = [
    os.path.join(os.getcwd(), "data"),
    "/mnt/data",
    os.getcwd(),
]
DATA_DIR = next((p for p in DATA_DIR_CANDIDATES if os.path.isdir(p)), os.getcwd())

PLAYER_MAIN_CSV = next((p for p in [
    os.path.join(DATA_DIR, "players_2025-26.csv"),
] if os.path.exists(p)), None)
PLAYER_BASE_CSV = next((p for p in [
    os.path.join(DATA_DIR, "players_2025-26_base.csv"),
] if os.path.exists(p)), None)
PLAYER_ADV_CSV  = next((p for p in [
    os.path.join(DATA_DIR, "players_2025-26_advanced.csv"),
] if os.path.exists(p)), None)
PLAYER_MISC_CSV = next((p for p in [
    os.path.join(DATA_DIR, "players_2025-26_misc.csv"),
] if os.path.exists(p)), None)
TEAM_CSV = next((p for p in [
    os.path.join(DATA_DIR, "teams_2025-26.csv"),
] if os.path.exists(p)), None)
INJ_CSV = next((p for p in [
    os.path.join(DATA_DIR, "injuries_2025-26.csv"),
    os.path.join(DATA_DIR, "injuries.csv"),
] if os.path.exists(p)), None)
H2H_CSV = next((p for p in [
    os.path.join(DATA_DIR, "h2h_2025-26.csv"),
] if os.path.exists(p)), None)
L10_CSV = next((p for p in [
    os.path.join(DATA_DIR, "form_l10_2025-26.csv"),
] if os.path.exists(p)), None)
DEF_MATCHUP_CSV = next((p for p in [
    os.path.join(DATA_DIR, "def_matchup_2025-26.csv"),
] if os.path.exists(p)), None)
OFF_MATCHUP_CSV = next((p for p in [
    os.path.join(DATA_DIR, "off_matchup_2025-26.csv"),
] if os.path.exists(p)), None)

TEAM_ID_TO_ABBR = {
    1610612737: "ATL", 1610612738: "BOS", 1610612751: "BKN", 1610612766: "CHA",
    1610612741: "CHI", 1610612739: "CLE", 1610612742: "DAL", 1610612743: "DEN",
    1610612765: "DET", 1610612744: "GSW", 1610612745: "HOU", 1610612754: "IND",
    1610612746: "LAC", 1610612747: "LAL", 1610612763: "MEM", 1610612748: "MIA",
    1610612749: "MIL", 1610612750: "MIN", 1610612740: "NOP", 1610612752: "NYK",
    1610612753: "ORL", 1610612755: "PHI", 1610612756: "PHX", 1610612757: "POR",
    1610612758: "SAC", 1610612759: "SAS", 1610612760: "OKC", 1610612761: "TOR",
    1610612762: "UTA", 1610612764: "WAS",
}
ABBR_TO_TEAM_ID = {v: k for k, v in TEAM_ID_TO_ABBR.items()}
TEAM_NAME_TO_ABBR = {
    "atlanta hawks": "ATL", "boston celtics": "BOS", "brooklyn nets": "BKN",
    "charlotte hornets": "CHA", "chicago bulls": "CHI", "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL", "denver nuggets": "DEN", "detroit pistons": "DET",
    "golden state warriors": "GSW", "houston rockets": "HOU", "indiana pacers": "IND",
    "los angeles clippers": "LAC", "la clippers": "LAC", "los angeles lakers": "LAL",
    "memphis grizzlies": "MEM", "miami heat": "MIA", "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN", "new orleans pelicans": "NOP",
    "new york knicks": "NYK", "orlando magic": "ORL", "philadelphia 76ers": "PHI",
    "phoenix suns": "PHX", "portland trail blazers": "POR", "sacramento kings": "SAC",
    "san antonio spurs": "SAS", "oklahoma city thunder": "OKC",
    "toronto raptors": "TOR", "utah jazz": "UTA", "washington wizards": "WAS",
}

st.set_page_config(page_title="NBA Quant Engine", layout="wide")
st.title("NBA Quant Engine - 2025-26")

st.info("App is running! Upload your CSV data files to the data/ folder to use full functionality.")
st.write("**Required files:**")
st.write("- players_2025-26.csv")
st.write("- teams_2025-26.csv")
st.write("- injuries_2025-26.csv (optional)")
st.write("- players_2025-26_advanced.csv (optional)")
st.write("- players_2025-26_base.csv (optional)")
st.write("- players_2025-26_misc.csv (optional)")
st.write("- h2h_2025-26.csv (optional)")
st.write("- form_l10_2025-26.csv (optional)")
st.write("- def_matchup_2025-26.csv (optional)")
