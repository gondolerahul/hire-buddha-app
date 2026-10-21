"""The tenant split tool moves a business into its own database (Phase 14 WS7 7.1, 7.3).

A business with an agent and its active version, a run and its child run,
CORTEX nodes (a parent, a child with an embedding), a campaign and its call, a
connection with its sealed secret, a trigger with an event and its firing —
all in the shared database — is provisioned onto a pool server of this test's
own and copied; every table's count and checksum match; the forward and self
references come back; the sealed secret still opens there. Running it again
is refused unless ``replace``; a dry run only counts the source.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

import src.main  # noqa: F401

pytestmark = [pytest.mark.needs_db]


@pytest_asyncio.fixture
async def business(monkeypatch, tmp_path):
    import asyncpg
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.automation import store
    from src.auth.models import Company
    from src.common import database
    from src.common.config import settings
    from src.common.platform.kek import set_kek
    from src.common.platform.kek.local import LocalKeyEncryption
    from src.common.platform.storage import set_storage
    from src.common.tenancy import provisioner
    from src.common.tenancy.directory import directory
    from src.common.tenancy.engines import engines
    from src.common.tenancy.models import TenantDbServer, TenantDirectoryEntry, TenantProvisioningLog
    from src.common.tenancy.session import control_session
    from src.connections import crypto
    from tests.harness.infra import infra_unavailable
    from tests.harness.storage import MemoryStorage

    url = make_url(settings.CONTROL_DATABASE_URL)
    if (url.host or "localhost") not in ("localhost", "127.0.0.1", "::1", "db", "postgres"):
        pytest.skip("the split test creates databases on a local server only")
    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        infra_unavailable(f"Postgres unreachable ({exc})")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(settings, "TENANCY_MODE", "single")
    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "local")

    async def _no_nudge(*a, **k):
        return None

    monkeypatch.setattr(store, "nudge", _no_nudge)
    storage = MemoryStorage()
    set_storage(storage)
    set_kek(LocalKeyEncryption(tmp_path / "keys"))
    crypto.forget_cached()
    company_id = uuid.uuid4()
    server = f"split-pool-{uuid.uuid4().hex[:6]}"
    async with control_session() as db:
        db.add(Company(id=company_id, name="Split Co", type="TENANT", status="active"))
        await provisioner.add_server(db, name=server, host=url.host or "localhost", capacity=5, region="test")
        await db.commit()
    try:
        yield {"id": company_id, "server": server, "storage": storage}
    finally:
        set_storage(None)
        set_kek(None)
        crypto.forget_cached()
        async with control_session() as db:
            entry = await db.get(TenantDirectoryEntry, company_id)
            db_name = entry.db_name if entry else None
            await db.execute(delete(TenantProvisioningLog).where(TenantProvisioningLog.company_id == company_id))
            await db.execute(delete(TenantDirectoryEntry).where(TenantDirectoryEntry.company_id == company_id))
            await db.execute(delete(TenantDbServer).where(TenantDbServer.name == server))
            await db.commit()
        directory.invalidate()
        await engines.dispose_all()
        if db_name:
            admin = await asyncpg.connect(url.set(drivername="postgresql", database="postgres")
                                          .render_as_string(hide_password=False))
            try:
                await admin.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
            finally:
                await admin.close()
        from tests.harness.purge import purge_companies

        async with control_session() as db:
            await db.execute(text("DELETE FROM connection_audit WHERE company_id = :c"), {"c": company_id})
            await db.execute(text("DELETE FROM cortex_nodes WHERE tree_id IN "
                                  "(SELECT id FROM cortex_trees WHERE company_id = :c)"), {"c": company_id})
            await purge_companies(await db.connection(), [company_id])
            await db.commit()
        await engine.dispose()


async def _seed(company_id):
    """A little of everything, in the shared database."""
    from src.ai.campaign_models import Campaign, CampaignCall
    from src.ai.memory.cortex_models import CortexTree, CortexTreeStatus
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun
    from src.ai.orm.versions import EntityVersion
    from src.automation.models import Event, Trigger, TriggerFiring
    from src.common.tenancy.session import control_session
    from src.connections import service
    from cortex_memory.models import CortexNode

    async with control_session() as db:
        agent = HierarchicalEntity(company_id=company_id, type="AGENT", status="ACTIVE", name="Split agent")
        db.add(agent)
        await db.flush()
        version = EntityVersion(entity_id=agent.id, company_id=company_id, version_number=1,
                                snapshot={"name": "Split agent"}, content_hash="x" * 64)
        db.add(version)
        await db.flush()
        agent.active_version_id = version.id
        parent = ExecutionRun(entity_id=agent.id, company_id=company_id, status="COMPLETED", input_data={})
        db.add(parent)
        await db.flush()
        db.add(ExecutionRun(entity_id=agent.id, company_id=company_id, status="COMPLETED", input_data={},
                            parent_run_id=parent.id, depth=1))
        tree = CortexTree(company_id=company_id, entity_id=agent.id, task_description="digest",
                          status=CortexTreeStatus.SUSPENDED)
        db.add(tree)
        await db.flush()
        root = CortexNode(tree_id=tree.id, node_type="root", title="root")
        db.add(root)
        await db.flush()
        db.add(CortexNode(tree_id=tree.id, parent_id=root.id, node_type="finding", title="child",
                          embedding=[0.25] * 768))
        campaign = Campaign(company_id=company_id, created_by=uuid.uuid4(), agent_id=agent.id, name="split",
                            contact_list=[], total_contacts=1, provider="twilio", status="draft")
        db.add(campaign)
        await db.flush()
        db.add(CampaignCall(campaign_id=campaign.id, contact_data={"phone": "+15550001111"}, status="pending"))
        trigger = Trigger(company_id=company_id, name="Mail", kind="event", entity_id=agent.id,
                          event_type="email.received", created_by_kind="user")
        event = Event(id=uuid.uuid4(), company_id=company_id, type="email.received", source="test", dedupe_key=f"d-{uuid.uuid4()}",
                      trust="verified", data={"subject": "hi"}, status="routed", received_at=datetime.utcnow(),
                      time=datetime.utcnow())
        db.add_all([trigger, event])
        await db.flush()
        db.add(TriggerFiring(trigger_id=trigger.id, event_id=event.id, outcome="skipped_overlap"))
        await db.commit()
        ids = {"agent": agent.id, "version": version.id, "parent": parent.id}
    made = await service.create_from_form(company_id, None, "api_key", {"service_name": "Courier",
                                                                       "api_key": "split-secret"})
    ids["connection"] = uuid.UUID(made["id"])
    return ids


async def test_a_business_moves_into_its_own_database_and_every_table_matches(business):
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun
    from src.common.tenancy.split import SplitRefused, split_tenant
    from src.connections import crypto
    from src.connections.models import ConnectionSecret
    from cortex_memory.models import CortexNode

    ids = await _seed(business["id"])
    from src.common.tenancy.session import control_session

    async with control_session() as db:  # saving an agent records its own version: read what is active
        ids["version"] = (await db.get(HierarchicalEntity, ids["agent"])).active_version_id
    assert ids["version"] is not None
    dry = await split_tenant(business["id"], dry_run=True)
    counts = {row["table"]: row["source_count"] for row in dry["tables"]}
    assert counts["hierarchical_entities"] == 1 and counts["execution_runs"] == 2 and counts["cortex_nodes"] == 2

    manifest = await split_tenant(business["id"], server_name=business["server"])
    assert manifest["mismatches"] == 0, [t for t in manifest["tables"] if not t["match"]]
    moved = {row["table"]: row["target_count"] for row in manifest["tables"]}
    assert (moved["campaign_calls"], moved["trigger_firings"], moved["connection_secrets"]) == (1, 1, 1)
    assert manifest["stored_at"] in business["storage"].objects

    # Read it the way the platform will: the business's own tenant session.
    from src.common.config import settings
    from src.common.tenancy.directory import directory
    from src.common.tenancy.session import tenant_session

    settings.TENANCY_MODE = "split"
    directory.invalidate()
    try:
        async with tenant_session(business["id"]) as db:
            agent = await db.get(HierarchicalEntity, ids["agent"])
            assert agent.active_version_id == ids["version"]                      # the forward key came back
            child = (await db.execute(select(ExecutionRun).where(ExecutionRun.parent_run_id == ids["parent"]))
                     ).scalar_one()
            assert child.depth == 1
            nodes = (await db.execute(select(CortexNode).order_by(CortexNode.title))).scalars().all()
            assert [n.title for n in nodes] == ["child", "root"] and nodes[0].parent_id == nodes[1].id
            assert len(nodes[0].embedding) == 768
            row = await db.get(ConnectionSecret, ids["connection"])
            assert await crypto.open_secret(db, business["id"], ids["connection"], row.dek_version, row.nonce,
                                            row.ciphertext) == {"api_key": "split-secret"}
    finally:
        settings.TENANCY_MODE = "single"
        directory.invalidate()

    with pytest.raises(SplitRefused, match="already holds"):
        await split_tenant(business["id"], server_name=business["server"])
    again = await split_tenant(business["id"], server_name=business["server"], replace=True)
    assert again["mismatches"] == 0


async def test_a_rehearsal_moves_credentials_rows_and_files_and_reports_them(business):
    """WS7 7.4, 7.5: the business's old e-mail row becomes a connection, its rows
    move, its file moves into ``t-<key>`` (same bytes; the row follows it), and the
    report — kept as JSON and Markdown — says all is well."""
    from src.ai.artifact_models import Artifact
    from src.ai.email_models import EmailConnection
    from src.ai.orm.entity import HierarchicalEntity
    from src.common.config import settings
    from src.common.platform.storage import company_namespace, legacy_namespace
    from src.common.security import encrypt_api_key
    from src.common.tenancy.directory import directory
    from src.common.tenancy.rehearsal import rehearse
    from src.common.tenancy.session import control_session, tenant_session
    from src.connections.models import Connection

    company = business["id"]
    storage = business["storage"]
    old_key = f"{legacy_namespace(company)}/artifacts/2026-10-19/{uuid.uuid4().hex}_report.txt"
    await storage.put(old_key, b"the quarterly report", content_type="text/plain")
    async with control_session() as db:
        db.add(Artifact(company_id=company, origin="system-generated", file_category="documents",
                        file_name="report.txt", file_path=old_key, storage_key=old_key, file_size=20,
                        mime_type="text/plain"))
        db.add(EmailConnection(company_id=company, email_address="ops@split.test",
                               encrypted_app_password=encrypt_api_key("mail-pass")))
        avatar = f"/api/v1/files/{uuid.uuid4()}/public"  # saved before split mode: no company
        agent = HierarchicalEntity(company_id=company, type="AGENT", status="ACTIVE", name="Avatar agent",
                                   identity={"system_prompt": "hi", "profile_image_url": avatar})
        db.add(agent)
        await db.commit()
        agent_id = agent.id

    report = await rehearse([company], server_name=business["server"], files=True)
    [result] = report["results"]
    assert result["ok"] is True, result
    assert (result["mismatches"], result["credentials"]["converted"], result["files"]["moved"]) == (0, 1, 1)
    assert f"{report['stored_at']}/report.md" in storage.objects
    assert "| ok |" in storage.objects[f"{report['stored_at']}/report.md"].decode()

    key = result["tenant_key"]
    settings.TENANCY_MODE = "split"
    directory.invalidate()
    try:
        async with tenant_session(company) as db:
            [artifact] = (await db.execute(select(Artifact).where(Artifact.company_id == company))).scalars().all()
            assert artifact.storage_key == artifact.file_path == old_key.replace(legacy_namespace(company), f"t-{key}")
            assert storage.objects[artifact.storage_key] == b"the quarterly report"
            [mailbox] = (await db.execute(select(Connection).where(Connection.company_id == company,
                                                                   Connection.connector_id == "imap_mailbox"))
                         ).scalars().all()
            assert mailbox.external_account_id == "ops@split.test"
            # The agent's avatar URL now names the company, as split mode serves it (M2-4).
            moved_agent = await db.get(HierarchicalEntity, agent_id)
            assert moved_agent.identity == {"system_prompt": "hi", "profile_image_url": f"{avatar}?company={company}"}
        assert result["files"]["avatar_urls"] == 1
        assert company_namespace(company) == f"t-{key}"            # new files go to the tenant's namespace
    finally:
        settings.TENANCY_MODE = "single"
        directory.invalidate()
