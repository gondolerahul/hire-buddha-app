"""Analytics API: funnel math, rep scoping, paged calls, timeline."""
from datetime import datetime

import pytest
from sqlalchemy import update

from src.ai.campaign_models import CampaignCall
from src.mobile.identification import resolve_mobile_inbound
from src.mobile.models import MobileCallAttempt
from tests.integration.mobile.test_mobile_flow import (
    REP2_CLI, REP_CLI, create_campaign, new_attempt, start_and_lease, verified_device,
)


@pytest.fixture
def analytics_api(api):
    from src.mobile.analytics_router import router

    # the shared client's app only has campaign + mobile routers; add analytics
    api._transport.app.include_router(router, prefix="/api/v1")
    return api


async def post_events(client, attempt_id, *types, payload=None):
    events = [{"seq": i + 1, "type": t, "payload": (payload or {}) if t == "lead_failed" else {}}
              for i, t in enumerate(types)]
    r = await client.post(f"/api/v1/mobile/call-attempts/{attempt_id}/events", json={"events": events})
    assert r.status_code == 200, r.text


async def test_funnel_rates_and_scoping(analytics_api, world, db):
    api = analytics_api
    campaign_id, _ = await create_campaign(
        api, world, world.admin, assignees=[world.rep, world.rep2],
        rows=[["name", "phone"], ["Asha", 9812345678], ["Ravi", 9812345679], ["Mina", 9812345670]])
    d1 = await verified_device(api, db, world, world.rep, REP_CLI)
    d2 = await verified_device(api, db, world, world.rep2, REP2_CLI)

    # rep1: answered + merged conversation, lead interested
    run1, lease1 = await start_and_lease(api, world.rep, campaign_id, d1)
    a1 = await new_attempt(api, world.rep, run1, lease1, d1)
    await resolve_mobile_inbound(db, from_number=REP_CLI, to_number=world.did, call_sid="CA-a1",
                                 provider="tata_tele")
    # the gateway would mark the AI ready once the model connects
    await db.execute(update(MobileCallAttempt).where(MobileCallAttempt.id == a1["attempt_id"])
                     .values(ai_ready_at=datetime.utcnow()))
    await db.commit()
    c1 = api.as_user(world.rep)
    await post_events(c1, a1["attempt_id"], "ai_answered", "lead_dialing", "lead_answered", "merged", "completed")
    await db.execute(update(CampaignCall).where(CampaignCall.id == lease1["campaign_call_id"])
                     .values(disposition="interested", status="completed"))
    await db.execute(update(MobileCallAttempt).where(MobileCallAttempt.id == a1["attempt_id"])
                     .values(conversation_seconds=95))
    await db.commit()

    # rep2: lead busy
    run2, lease2 = await start_and_lease(api, world.rep2, campaign_id, d2)
    a2 = await new_attempt(api, world.rep2, run2, lease2, d2)
    await post_events(api.as_user(world.rep2), a2["attempt_id"], "ai_answered", "lead_dialing", "lead_failed",
                      payload={"cause": "busy"})

    admin_view = (await api.as_user(world.admin).get(f"/api/v1/campaigns/{campaign_id}/mobile-analytics")).json()
    f = admin_view["funnel"]
    assert (f["leads"], f["attempted"], f["lead_dialed"], f["lead_answered"], f["merged"], f["conversation"],
            f["interested"]) == (3, 2, 2, 1, 1, 1, 1)
    assert admin_view["rates"]["answer"] == 0.5
    assert admin_view["rates"]["merge_success"] == 1.0
    assert admin_view["outcomes"]["busy"] == 1 and admin_view["outcomes"]["interested"] == 1
    assert {r["name"] for r in admin_view["by_rep"]} == {"Ravi", "Sunita"}

    # a rep only ever sees their own numbers, even when asking for someone else's
    rep2_view = (await api.as_user(world.rep2).get(
        f"/api/v1/campaigns/{campaign_id}/mobile-analytics?user_id={world.rep.id}")).json()
    assert rep2_view["funnel"]["merged"] == 0 and [r["name"] for r in rep2_view["by_rep"]] == ["Sunita"]

    calls = (await api.as_user(world.admin).get(f"/api/v1/campaigns/{campaign_id}/calls?limit=10")).json()
    assert calls["total"] == 3
    by_id = {c["campaign_call_id"]: c for c in calls["items"]}
    assert by_id[lease1["campaign_call_id"]]["disposition"] == "interested"
    assert by_id[lease1["campaign_call_id"]]["phone_masked"].endswith(lease1["contact"]["phone"][-4:])
    assert "*" in by_id[lease1["campaign_call_id"]]["phone_masked"]
    assert by_id[lease2["campaign_call_id"]]["lead_failure_cause"] == "busy"

    summary = (await api.as_user(world.admin).get("/api/v1/mobile/analytics/summary")).json()
    assert summary["funnel"]["attempts"] == 2 and sum(d["attempted"] for d in summary["daily"]) == 2

    timeline = (await api.as_user(world.rep).get(f"/api/v1/mobile/call-attempts/{a1['attempt_id']}/timeline")).json()
    assert [e["type"] for e in timeline["timeline"] if e["source"] == "app"] == [
        "ai_answered", "lead_dialing", "lead_answered", "merged", "completed"]
    r = await api.as_user(world.rep2).get(f"/api/v1/mobile/call-attempts/{a1['attempt_id']}/timeline")
    assert r.status_code == 404
    r = await api.as_user(world.outsider).get(f"/api/v1/campaigns/{campaign_id}/mobile-analytics")
    assert r.status_code == 404
