import requests
import pandas as pd
from bs4 import BeautifulSoup

BASE_URL = "https://www.basketball-reference.com"

def get_player_season_stats(player_slug, season_year=2026):
    """
    player_slug primjer: 'holidjr01'
    season_year: 2026 za sezonu 2025-26
    """

    url = f"{BASE_URL}/players/{player_slug[0]}/{player_slug}.html"

    r = requests.get(url)
    soup = BeautifulSoup(r.text, "lxml")

    table = soup.find("table", {"id": "per_game"})

    if table is None:
        return None

    df = pd.read_html(str(table))[0]
    df = df[df["Season"] == f"{season_year-1}-{str(season_year)[-2:]}"]

    if df.empty:
        return None

    return df.iloc[0]
