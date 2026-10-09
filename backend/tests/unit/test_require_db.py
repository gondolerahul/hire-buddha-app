"""TS-05: missing infrastructure skips a tier locally and fails it under REQUIRE_DB=1."""
from __future__ import annotations

import pytest

from tests.harness.infra import infra_required, infra_unavailable


def test_without_require_db_a_missing_database_skips(monkeypatch) -> None:
    monkeypatch.delenv("REQUIRE_DB", raising=False)
    assert not infra_required()
    with pytest.raises(pytest.skip.Exception, match="no Postgres"):
        infra_unavailable("no Postgres")


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_with_require_db_a_missing_database_fails(monkeypatch, value) -> None:
    monkeypatch.setenv("REQUIRE_DB", value)
    with pytest.raises(pytest.fail.Exception, match="no Postgres.*REQUIRE_DB=1"):
        infra_unavailable("no Postgres")


def test_require_db_off_values_still_skip(monkeypatch) -> None:
    monkeypatch.setenv("REQUIRE_DB", "0")
    with pytest.raises(pytest.skip.Exception):
        infra_unavailable("no Redis")
