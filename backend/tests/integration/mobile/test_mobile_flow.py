"""End-to-end backend flow for the mobile dialer against a disposable Postgres + Redis db 15."""
import asyncio
import io
import json
from datetime import datetime, timedelta
from uuid import uuid4

import openpyxl
import pytest
from sqlalchemy import select, text

from src.ai.campaign_models import Campaign, CampaignCall
from src.mobile import realtime
from src.mobile.identification import (
    bind_session_by_token, complete_device_verification, resolve_mobile_inbound,
)
from src.mobile.models import MobileCallAttempt, UserDevice
from src.mobile.reconciler import expire_stale_attempts

REP_CLI = "+919876500001"
REP2_CLI = "+919876500002"


def xlsx(rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def create_campaign(api, world, user, assignees=None, rows=None):
    client = api.as_user(user)
    content = xlsx(rows or [["Name", "Mobile", "City"], ["Asha", 9812345678, "Pune"],
                            ["Ravi", 9812345679, "Mumbai"], ["Bad", "123", "X"]])
    r = await client.post("/api/v1/campaigns/upload-contacts",
                          files={"file": ("leads.xlsx", content, "application/octet-stream")})
    assert r.status_code == 200, r.text
    upload = r.json()
    body = {"agent_id": str(world.agent.id), "name": "Sept leads", "contact_upload_id": upload["upload_id"],
            "execution_mode": "mobile_conference"}
    if assignees is not None:
        body["assignee_user_ids"] = [str(a.id) for a in assignees]
    r = await client.post("/api/v1/campaigns", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"], upload


async def verified_device(api, db, world, user, cli, install_id=None):
    client = api.as_user(user)
    r = await client.post("/api/v1/mobile/devices", json={"install_id": install_id or uuid4().hex,
                                                          "model": "Pixel 8", "phone_account_label": "SIM 1"})
    assert r.status_code == 200, r.text
    dev = r.json()
    assert dev["status"] == "unverified" and dev["verification"]["did"] == world.did
    session = await resolve_mobile_inbound(db, from_number=cli.lstrip("+"), to_number=world.did,
                                           call_sid=f"CA{uuid4().hex}", provider="tata_tele")
    assert session is not None and session.session_metadata["expects_verification"]
    result = await complete_device_verification(db, session.id, dev["verification"]["code"])
    assert result and result.verified_cli == cli
    return dev["device_id"]


async def start_and_lease(api, user, campaign_id, device_id):
    client = api.as_user(user)
    r = await client.post(f"/api/v1/mobile/campaigns/{campaign_id}/runs", json={"device_id": device_id})
    assert r.status_code == 201, r.text
    run_id = r.json()["run_id"]
    r = await client.post(f"/api/v1/mobile/runs/{run_id}/next")
    assert r.status_code == 200, r.text
    return run_id, r.json()


async def new_attempt(api, user, run_id, lease, device_id):
    r = await api.as_user(user).post("/api/v1/mobile/call-attempts", json={
        "run_id": run_id, "campaign_call_id": lease["campaign_call_id"], "device_id": device_id})
    assert r.status_code == 201, r.text
    return r.json()


# ── schema ──────────────────────────────────────────────────────────────

async def test_sql_script_created_schema(db):
    tables = set((await db.execute(text(
        "select table_name from information_schema.tables where table_schema='public'"))).scalars())
    assert {"user_devices", "mobile_call_attempts", "mobile_call_events", "contact_uploads",
            "campaign_assignees", "mobile_campaign_runs"} <= tables
    cols = set((await db.execute(text(
        "select column_name from information_schema.columns where table_name='campaigns'"))).scalars())
    assert {"execution_mode", "contact_upload_id"} <= cols


# ── campaign creation ───────────────────────────────────────────────────

async def test_upload_and_create_mobile_campaign(api, world, db):
    campaign_id, upload = await create_campaign(api, world, world.admin, assignees=[world.rep])
    assert upload["valid_rows"] == 2 and upload["invalid_rows"] == 1
    assert upload["errors"][0]["reason"] == "too_short"

    campaign = await db.get(Campaign, campaign_id)
    assert campaign.execution_mode == "mobile_conference" and campaign.provider == "tata_tele"
    phones = sorted((await db.execute(select(CampaignCall.contact_data["phone"].astext)
                                      .where(CampaignCall.campaign_id == campaign.id))).scalars())
    assert phones == ["+919812345678", "+919812345679"]

    # the upload can't be reused, and mobile campaigns can't be server-dialed
    r = await api.as_user(world.admin).post("/api/v1/campaigns", json={
        "agent_id": str(world.agent.id), "name": "dup", "contact_upload_id": upload["upload_id"],
        "execution_mode": "mobile_conference", "assignee_user_ids": [str(world.rep.id)]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "upload_already_used"
    r = await api.as_user(world.admin).patch(f"/api/v1/campaigns/{campaign_id}/status?status=running")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "use_mobile_run"


async def test_tenant_user_cannot_assign_others_and_sees_only_assigned(api, world):
    client = api.as_user(world.rep)
    content = xlsx([["phone"], [9812345678]])
    upload = (await client.post("/api/v1/campaigns/upload-contacts",
                                files={"file": ("l.xlsx", content, "application/octet-stream")})).json()
    r = await client.post("/api/v1/campaigns", json={
        "agent_id": str(world.agent.id), "name": "x", "contact_upload_id": upload["upload_id"],
        "execution_mode": "mobile_conference", "assignee_user_ids": [str(world.rep2.id)]})
    assert r.status_code == 403

    await create_campaign(api, world, world.admin, assignees=[world.rep2])
    mine, _ = await create_campaign(api, world, world.rep)  # self-assigned by default
    listed = (await api.as_user(world.rep).get("/api/v1/mobile/campaigns")).json()["campaigns"]
    assert [c["id"] for c in listed] == [mine]
    assert len((await api.as_user(world.admin).get("/api/v1/mobile/campaigns")).json()["campaigns"]) == 2
    r = await api.as_user(world.outsider).get(f"/api/v1/mobile/campaigns/{mine}")
    assert r.status_code == 404


async def test_non_tenant_roles_rejected(api, world):
    r = await api.as_user(world.app_admin).get("/api/v1/mobile/me")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "role_not_supported"


# ── devices ─────────────────────────────────────────────────────────────

async def test_unverified_device_cannot_run(api, world):
    campaign_id, _ = await create_campaign(api, world, world.admin, assignees=[world.rep])
    dev = (await api.as_user(world.rep).post("/api/v1/mobile/devices", json={"install_id": uuid4().hex})).json()
    r = await api.as_user(world.rep).post(f"/api/v1/mobile/campaigns/{campaign_id}/runs",
                                          json={"device_id": dev["device_id"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "device_not_verified"


async def test_device_verification_captures_cli_and_wrong_code_fails(api, world, db):
    dev = (await api.as_user(world.rep).post("/api/v1/mobile/devices", json={"install_id": uuid4().hex})).json()
    session = await resolve_mobile_inbound(db, from_number="09876500001", to_number="918065251146",
                                           call_sid="CA-verify", provider="tata_tele")
    assert await complete_device_verification(db, session.id, "000000" if dev["verification"]["code"] != "000000" else "111111") is None
    result = await complete_device_verification(db, session.id, dev["verification"]["code"])
    assert result.verified_cli == REP_CLI
    device = await db.get(UserDevice, result.device_id)
    await db.refresh(device)
    assert device.status == "verified" and device.verification_code_hash is None


# ── leasing ─────────────────────────────────────────────────────────────

async def test_concurrent_leases_never_collide(api, world, db):
    campaign_id, _ = await create_campaign(
        api, world, world.admin, assignees=[world.rep, world.rep2],
        rows=[["phone"]] + [[9812300000 + i] for i in range(6)])
    d1 = await verified_device(api, db, world, world.rep, REP_CLI)
    d2 = await verified_device(api, db, world, world.rep2, REP2_CLI)
    c1 = api.as_user(world.rep)
    run1 = (await c1.post(f"/api/v1/mobile/campaigns/{campaign_id}/runs", json={"device_id": d1})).json()["run_id"]
    run2 = (await api.as_user(world.rep2).post(f"/api/v1/mobile/campaigns/{campaign_id}/runs",
                                               json={"device_id": d2})).json()["run_id"]

    from src.mobile import service
    from src.common.database import AsyncSessionLocal

    async def lease(user, run):
        async with AsyncSessionLocal() as s:
            return await service.next_lead(s, user, run)

    results = await asyncio.gather(*[lease(world.rep, run1) for _ in range(1)], *[lease(world.rep2, run2) for _ in range(1)])
    ids = [r["campaign_call_id"] for r in results]
    assert len(set(ids)) == 2


# ── identification ──────────────────────────────────────────────────────

async def test_cli_bind_then_dtmf_confirm(api, world, db):
    campaign_id, _ = await create_campaign(api, world, world.admin, assignees=[world.rep])
    device_id = await verified_device(api, db, world, world.rep, REP_CLI)
    run_id, lease = await start_and_lease(api, world.rep, campaign_id, device_id)
    attempt = await new_attempt(api, world.rep, run_id, lease, device_id)
    assert attempt["did"] == world.did and len(attempt["dtmf_token"]) == 4

    session = await resolve_mobile_inbound(db, from_number="919876500001", to_number="+918065251146",
                                           call_sid="CA-cli", provider="tata_tele")
    meta = session.session_metadata
    assert meta["bound"] and meta["identification"]["method"] == "cli"
    assert meta["attempt_id"] == attempt["attempt_id"]
    assert meta["contact_data"]["phone"] == lease["contact"]["phone"]
    assert meta["rep_name"] == "Ravi" and meta["company_name"] == "Acme Realty"
    assert session.agent_id == world.agent.id and session.phone_number == lease["contact"]["phone"]

    result = await bind_session_by_token(db, session.id, attempt["dtmf_token"])
    assert result.status == "confirmed" and result.method == "cli+dtmf"


async def test_dtmf_overrides_wrong_cli_binding(api, world, db):
    campaign_id, _ = await create_campaign(api, world, world.admin, assignees=[world.rep, world.rep2])
    d1 = await verified_device(api, db, world, world.rep, REP_CLI)
    d2 = await verified_device(api, db, world, world.rep2, REP2_CLI)
    run1, lease1 = await start_and_lease(api, world.rep, campaign_id, d1)
    run2, lease2 = await start_and_lease(api, world.rep2, campaign_id, d2)
    a1 = await new_attempt(api, world.rep, run1, lease1, d1)
    a2 = await new_attempt(api, world.rep2, run2, lease2, d2)

    # Carrier presented rep1's CLI but the call is really rep2's (e.g. shared/misreported CLI)
    session = await resolve_mobile_inbound(db, from_number=REP_CLI, to_number=world.did,
                                           call_sid="CA-conflict", provider="tata_tele")
    assert session.session_metadata["attempt_id"] == a1["attempt_id"]
    result = await bind_session_by_token(db, session.id, a2["dtmf_token"])
    assert result.status == "rebound"

    await db.commit()
    first = await db.get(MobileCallAttempt, a1["attempt_id"], populate_existing=True)
    second = await db.get(MobileCallAttempt, a2["attempt_id"], populate_existing=True)
    assert first.status == "pending" and first.voice_session_id is None
    assert second.voice_session_id == session.id and second.identification_conflict


async def test_unbound_session_binds_by_dtmf_and_genuine_inbound_untouched(api, world, db):
    # No attempts/verifications open: a normal customer call is not treated as mobile
    assert await resolve_mobile_inbound(db, from_number="+919999999999", to_number=world.did,
                                        call_sid="CA-genuine", provider="tata_tele") is None

    campaign_id, _ = await create_campaign(api, world, world.admin, assignees=[world.rep])
    device_id = await verified_device(api, db, world, world.rep, REP_CLI)
    run_id, lease = await start_and_lease(api, world.rep, campaign_id, device_id)
    attempt = await new_attempt(api, world.rep, run_id, lease, device_id)

    # CLI withheld by the carrier
    session = await resolve_mobile_inbound(db, from_number=None, to_number=world.did,
                                           call_sid="CA-nocli", provider="tata_tele")
    assert session.session_metadata["bound"] is False
    assert session.session_metadata["fallback_inbound"] is True
    result = await bind_session_by_token(db, session.id, attempt["dtmf_token"])
    assert result.status == "bound" and result.method == "dtmf"
    assert result.metadata["contact_data"]["phone"] == lease["contact"]["phone"]


# ── attempts & events ───────────────────────────────────────────────────

async def test_events_lead_failed_releases_lead_and_dedupes(api, world, db):
    campaign_id, _ = await create_campaign(api, world, world.admin, assignees=[world.rep])
    device_id = await verified_device(api, db, world, world.rep, REP_CLI)
    run_id, lease = await start_and_lease(api, world.rep, campaign_id, device_id)
    attempt = await new_attempt(api, world.rep, run_id, lease, device_id)
    client = api.as_user(world.rep)

    # can't take another lead while this attempt is open
    r = await client.post(f"/api/v1/mobile/runs/{run_id}/next")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "attempt_in_progress"

    batch = {"events": [
        {"seq": 1, "type": "ai_answered", "device_ts": "2026-09-17T10:00:00Z"},
        {"seq": 2, "type": "lead_dialing"},
        {"seq": 3, "type": "lead_failed", "payload": {"cause": "busy"}},
    ]}
    r = await client.post(f"/api/v1/mobile/call-attempts/{attempt['attempt_id']}/events", json=batch)
    assert r.json() == {"accepted": [1, 2, 3], "duplicates": []}
    r = await client.post(f"/api/v1/mobile/call-attempts/{attempt['attempt_id']}/events", json=batch)
    assert r.json() == {"accepted": [], "duplicates": [1, 2, 3]}

    call = await db.get(CampaignCall, lease["campaign_call_id"])
    await db.refresh(call)
    assert call.status == "failed" and call.disposition == "busy" and call.leased_by_device_id is None
    detail = (await client.get(f"/api/v1/mobile/call-attempts/{attempt['attempt_id']}")).json()
    assert detail["status"] == "lead_failed" and detail["lead_failure_cause"] == "busy"

    # next lead now allowed
    r = await client.post(f"/api/v1/mobile/runs/{run_id}/next")
    assert r.status_code == 200 and r.json()["campaign_call_id"] != lease["campaign_call_id"]


async def test_merged_event_publishes_control_message(api, world, db):
    campaign_id, _ = await create_campaign(api, world, world.admin, assignees=[world.rep])
    device_id = await verified_device(api, db, world, world.rep, REP_CLI)
    run_id, lease = await start_and_lease(api, world.rep, campaign_id, device_id)
    attempt = await new_attempt(api, world.rep, run_id, lease, device_id)
    session = await resolve_mobile_inbound(db, from_number=REP_CLI, to_number=world.did,
                                           call_sid="CA-merge", provider="tata_tele")

    received = []

    async def listen():
        async for msg in realtime.subscribe(realtime.session_control_channel(session.id)):
            received.append(msg)
            return

    task = asyncio.create_task(listen())
    await asyncio.sleep(0.3)
    r = await api.as_user(world.rep).post(f"/api/v1/mobile/call-attempts/{attempt['attempt_id']}/events",
                                          json={"events": [{"seq": 1, "type": "merged"}]})
    assert r.status_code == 200
    await asyncio.wait_for(task, 5)
    assert received[0]["type"] == "merged" and received[0]["attempt_id"] == attempt["attempt_id"]
    call = await db.get(CampaignCall, lease["campaign_call_id"])
    await db.refresh(call)
    assert call.status == "calling"


async def test_new_attempt_supersedes_open_one(api, world, db):
    campaign_id, _ = await create_campaign(api, world, world.admin, assignees=[world.rep])
    device_id = await verified_device(api, db, world, world.rep, REP_CLI)
    run_id, lease = await start_and_lease(api, world.rep, campaign_id, device_id)
    first = await new_attempt(api, world.rep, run_id, lease, device_id)
    second = await new_attempt(api, world.rep, run_id, lease, device_id)
    a = await db.get(MobileCallAttempt, first["attempt_id"])
    assert a.status == "superseded" and second["status"] == "pending"


async def test_expired_attempt_returns_lead(api, world, db):
    campaign_id, _ = await create_campaign(api, world, world.admin, assignees=[world.rep])
    device_id = await verified_device(api, db, world, world.rep, REP_CLI)
    run_id, lease = await start_and_lease(api, world.rep, campaign_id, device_id)
    attempt = await new_attempt(api, world.rep, run_id, lease, device_id)
    await db.execute(text("update mobile_call_attempts set expires_at = now() at time zone 'utc' - interval '1 minute'"))
    await db.commit()
    assert await expire_stale_attempts(db) == 1
    call = await db.get(CampaignCall, lease["campaign_call_id"], populate_existing=True)
    assert call.status == "pending"
    # an expired attempt is no longer bindable by CLI
    assert (await resolve_mobile_inbound(db, from_number=REP_CLI, to_number=world.did,
                                         call_sid="CA-late", provider="tata_tele")) is None


async def test_calling_hours_and_daily_cap(api, world, db, monkeypatch):
    from src.common.config import settings

    campaign_id, _ = await create_campaign(api, world, world.admin, assignees=[world.rep])
    device_id = await verified_device(api, db, world, world.rep, REP_CLI)
    client = api.as_user(world.rep)
    run_id = (await client.post(f"/api/v1/mobile/campaigns/{campaign_id}/runs", json={"device_id": device_id})).json()["run_id"]

    monkeypatch.setattr(settings, "MOBILE_CALLING_HOURS_ENFORCED", True)
    monkeypatch.setattr(settings, "MOBILE_CALLING_HOURS_START", "00:00")
    monkeypatch.setattr(settings, "MOBILE_CALLING_HOURS_END", "00:00")
    r = await client.post(f"/api/v1/mobile/runs/{run_id}/next")
    assert r.status_code == 423

    monkeypatch.setattr(settings, "MOBILE_CALLING_HOURS_ENFORCED", False)
    monkeypatch.setattr(settings, "MOBILE_REP_DAILY_ATTEMPT_CAP", 1)
    lease = (await client.post(f"/api/v1/mobile/runs/{run_id}/next")).json()
    attempt = await new_attempt(api, world.rep, run_id, lease, device_id)
    await client.post(f"/api/v1/mobile/call-attempts/{attempt['attempt_id']}/events",
                      json={"events": [{"seq": 1, "type": "lead_failed", "payload": {"cause": "no_answer"}}]})
    r = await client.post(f"/api/v1/mobile/runs/{run_id}/next")
    assert r.status_code == 429


async def test_run_completes_when_no_leads_left(api, world, db):
    campaign_id, _ = await create_campaign(api, world, world.admin, assignees=[world.rep],
                                           rows=[["phone"], [9812345678]])
    device_id = await verified_device(api, db, world, world.rep, REP_CLI)
    run_id, lease = await start_and_lease(api, world.rep, campaign_id, device_id)
    client = api.as_user(world.rep)
    attempt = await new_attempt(api, world.rep, run_id, lease, device_id)
    await client.post(f"/api/v1/mobile/call-attempts/{attempt['attempt_id']}/events",
                      json={"events": [{"seq": 1, "type": "skipped"}]})
    r = await client.post(f"/api/v1/mobile/runs/{run_id}/next")
    assert r.status_code == 204
    campaign = await db.get(Campaign, campaign_id, populate_existing=True)
    assert campaign.status == "completed"
