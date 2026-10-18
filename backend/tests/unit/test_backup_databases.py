"""Decision D45: databases are exported every week and the last few weeks kept.

The control database goes to ``platform/backups/<week>/``, each tenant's own
database to its namespace ``t-<key>/backups/<week>/``, with a manifest of
sizes and SHA-256 per week; one database failing does not stop the others;
weeks beyond the kept number are deleted. ``pg_dump`` signs in through the
environment — never with a password on its command line.
"""
import hashlib
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.engine import make_url

from scripts import backup_databases as backups
from src.common.platform import dbauth, identity
from tests.harness.storage import MemoryStorage

NOW = datetime(2026, 10, 18, 20, 30, tzinfo=timezone.utc)  # ISO week 2026-W42

CONTROL = backups.Target("hb_control", make_url("postgresql+asyncpg://id-hb-dev-worker@pg/hb_control"), "platform")
ACME = backups.Target("t_devacme01", make_url("postgresql+asyncpg://id-hb-dev-worker@pool/t_devacme01"), "t-devacme01")
BETA = backups.Target("t_devbeta001", make_url("postgresql+asyncpg://id-hb-dev-worker@pool/t_devbeta001"), "t-devbeta001")


async def _fake_dump(target, path):
    path.write_bytes(f"PGDMP {target.database}".encode())


def test_the_week_folder():
    assert backups.iso_week(NOW) == "2026-W42"
    assert backups.iso_week(datetime(2027, 1, 1, tzinfo=timezone.utc)) == "2026-W53"
    assert backups.export_key(ACME, "2026-W42") == "t-devacme01/backups/2026-W42/t_devacme01.dump"


async def test_each_database_goes_to_its_own_namespace_with_a_manifest():
    storage = MemoryStorage()
    report = await backups.backup(now=NOW, dump=_fake_dump, storage=storage, keep_weeks=5,
                                  found=[CONTROL, ACME, BETA])
    assert report["failed"] == [] and len(report["exported"]) == 3
    assert storage.objects["platform/backups/2026-W42/hb_control.dump"] == b"PGDMP hb_control"
    assert storage.objects["t-devacme01/backups/2026-W42/t_devacme01.dump"] == b"PGDMP t_devacme01"
    manifest = json.loads(storage.objects["t-devbeta001/backups/2026-W42/manifest.json"])
    assert manifest["week"] == "2026-W42"
    assert manifest["databases"] == [{
        "database": "t_devbeta001", "key": "t-devbeta001/backups/2026-W42/t_devbeta001.dump",
        "bytes": len(b"PGDMP t_devbeta001"), "sha256": hashlib.sha256(b"PGDMP t_devbeta001").hexdigest()}]
    # A tenant's export never lands in another tenant's or the platform's namespace.
    assert not [k for k in storage.objects if k.startswith("t-devacme01/") and "beta" in k]


async def test_one_failure_does_not_stop_the_others():
    async def flaky(target, path):
        if target is ACME:
            raise RuntimeError("pg_dump: connection refused")
        await _fake_dump(target, path)

    storage = MemoryStorage()
    report = await backups.backup(now=NOW, dump=flaky, storage=storage, keep_weeks=5, found=[CONTROL, ACME, BETA])
    assert [f["database"] for f in report["failed"]] == ["t_devacme01"]
    assert "connection refused" in report["failed"][0]["error"]
    assert {e["database"] for e in report["exported"]} == {"hb_control", "t_devbeta001"}
    assert not any(k.startswith("t-devacme01/") for k in storage.objects)


async def test_only_the_last_weeks_are_kept():
    storage = MemoryStorage()
    for week in ("2026-W36", "2026-W37", "2026-W38", "2026-W39", "2026-W40", "2026-W41"):
        await storage.put(f"platform/backups/{week}/hb_control.dump", b"old")
        await storage.put(f"platform/backups/{week}/manifest.json", b"{}")
    await storage.put("t-devacme01/backups/2026-W30/t_devacme01.dump", b"other tenant")

    report = await backups.backup(now=NOW, dump=_fake_dump, storage=storage, keep_weeks=5, found=[CONTROL])
    weeks = sorted({k.split("/")[2] for k in storage.objects if k.startswith("platform/backups/")})
    assert weeks == ["2026-W38", "2026-W39", "2026-W40", "2026-W41", "2026-W42"]
    assert "platform/backups/2026-W36/hb_control.dump" in report["pruned"]
    # Pruning one namespace leaves the others alone.
    assert "t-devacme01/backups/2026-W30/t_devacme01.dump" in storage.objects


def test_pg_dump_signs_in_with_the_url_password_through_the_environment():
    env = dbauth.libpq_environment(make_url("postgresql+asyncpg://postgres:s3cret@localhost:5433/hirebuddha"),
                                   "password")
    assert env == {"PGHOST": "localhost", "PGPORT": "5433", "PGDATABASE": "hirebuddha",
                   "PGUSER": "postgres", "PGPASSWORD": "s3cret"}


def test_pg_dump_signs_in_with_an_entra_token_on_azure():
    class _Tokens:
        name = "fake"

        def sync_token(self, scope):
            assert scope == dbauth.POSTGRES_ENTRA_SCOPE
            return "entra-token"

        async def token(self, scope):
            return "entra-token"

    identity.set_token_source(_Tokens())
    try:
        env = dbauth.libpq_environment(
            make_url("postgresql+asyncpg://id-hb-dev-worker@psql-hb-dev-control.postgres.database.azure.com"
                     ":5432/hb_control?ssl=require"), "entra_token")
    finally:
        identity.set_token_source(None)
    assert env["PGUSER"] == "id-hb-dev-worker" and env["PGPASSWORD"] == "entra-token"
    assert env["PGSSLMODE"] == "require"


async def test_the_command_line_carries_no_password(monkeypatch, tmp_path):
    seen = {}

    class _Process:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_exec(*args, env=None, **kwargs):
        seen["args"], seen["env"] = args, env
        return _Process()

    monkeypatch.setattr(backups.asyncio, "create_subprocess_exec", fake_exec)
    target = backups.Target("hirebuddha", make_url("postgresql+asyncpg://postgres:s3cret@localhost:5433/hirebuddha"),
                            "platform")
    monkeypatch.setattr("src.common.config.settings.DB_AUTH", "password")
    await backups.pg_dump(target, tmp_path / "x.dump")
    assert "s3cret" not in " ".join(map(str, seen["args"]))
    assert seen["env"]["PGPASSWORD"] == "s3cret" and "--format=custom" in seen["args"]


async def test_a_failed_pg_dump_says_why(monkeypatch, tmp_path):
    class _Process:
        returncode = 1

        async def communicate(self):
            return b"", b"pg_dump: error: server version: 16.4; pg_dump version: 15.8"

    async def fake_exec(*args, **kwargs):
        return _Process()

    monkeypatch.setattr(backups.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr("src.common.config.settings.DB_AUTH", "password")
    target = backups.Target("d", make_url("postgresql+asyncpg://u:p@h/d"), "platform")
    with pytest.raises(RuntimeError, match="server version"):
        await backups.pg_dump(target, tmp_path / "x.dump")
