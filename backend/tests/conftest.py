"""Fixtures for every test suite."""
from pathlib import Path

import pytest

# A test's tier is its directory (TS-15): every test under one of these is
# marked with it, so `-m` selection matches the layout without decorators.
TIER_DIRECTORIES = ("integration", "e2e", "parity", "regression", "chaos", "isolation", "journeys")

_TESTS_ROOT = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config, items):
    for item in items:
        try:
            top = Path(str(item.fspath)).resolve().relative_to(_TESTS_ROOT).parts[0]
        except (ValueError, IndexError):
            continue
        if top in TIER_DIRECTORIES:
            item.add_marker(getattr(pytest.mark, top))


@pytest.fixture(autouse=True)
def _fresh_model_resolutions():
    """Model and key resolutions are cached per process (LP-I5); a test must not
    see one cached by another test's database state."""
    from src.config.resolution_cache import clear_all

    clear_all()
    yield
    clear_all()
