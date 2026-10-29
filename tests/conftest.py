import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nba_engine.config import Settings  # noqa: E402

DATA_SEASON = "2025-26"  # sezona za koju postoje CSV fajlovi u data/ (stvarni podaci)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.load(data_dir=ROOT / "data", season=DATA_SEASON, env_file=ROOT / "tests" / "no.env",
                         history_dir=ROOT / "tests" / "_history_tmp")


@pytest.fixture(scope="session")
def real_data(settings):
    if settings.csv_path("players_main") is None or settings.csv_path("teams") is None:
        pytest.skip("Nema stvarnih CSV podataka u data/")
    return settings


@pytest.fixture(scope="session")
def bundle_legacy_mode(real_data):
    """Podaci učitani kao u starom app.py (bez dopune tima u tabeli ozljeda)."""
    from nba_engine.loaders import load_bundle
    return load_bundle(real_data, fill_injury_team_from_players=False)
