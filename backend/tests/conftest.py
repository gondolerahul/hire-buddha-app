"""Fixtures for every test suite."""
import pytest


@pytest.fixture(autouse=True)
def _fresh_model_resolutions():
    """Model and key resolutions are cached per process (LP-I5); a test must not
    see one cached by another test's database state."""
    from src.config.resolution_cache import clear_all

    clear_all()
    yield
    clear_all()
