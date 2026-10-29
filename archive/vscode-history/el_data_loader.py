import requests
import pandas as pd


EL_URL = (
    "https://staging.euroleaguebasketball.net/euroleague/stats/players/"
    "?size=1000"
    "&viewType=traditional"
    "&statisticMode=perGame"
    "&seasonCode=E2025"
    "&seasonMode=Single"
    "&sortDirection=descending"
)


def load_euroleague_stats():

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    r = requests.get(EL_URL, headers=headers)

    if r.status_code != 200:
        return pd.DataFrame()

    data = r.json()

    if "data" not in data:
        return pd.DataFrame()

    df = pd.DataFrame(data["data"])

    # Standardizacija kolona za naš engine
    df.rename(columns={
        "player": "Player",
        "pts": "PTS",
        "min": "MIN",
        "usg": "USG_PCT"
    }, inplace=True)

    return df
