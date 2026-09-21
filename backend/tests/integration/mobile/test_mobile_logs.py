"""App diagnostic logs: ingestion, scoping and filtering."""
from tests.integration.mobile.test_mobile_flow import REP2_CLI, REP_CLI, verified_device


def entry(seq, level="INFO", tag="Orchestrator", message="Step", **fields):
    return {"seq": seq, "level": level, "tag": tag, "message": message,
            "fields": fields, "device_ts": "2026-09-21T10:00:00Z"}


async def test_logs_are_stored_and_readable(api, world, db):
    device_id = await verified_device(api, db, world, world.rep, REP_CLI)
    client = api.as_user(world.rep)

    r = await client.post("/api/v1/mobile/logs", json={
        "device_id": device_id,
        "app_version": "1.0.1 (2)",
        "entries": [
            entry(1, message="Run started", run="r1"),
            entry(2, tag="CallRegistry", message="Merge attempt", action="CONFERENCE"),
            entry(3, level="ERROR", message="Merge failed", calls="c1:ACTIVE | c2:HOLDING"),
        ],
    })
    assert r.status_code == 200 and r.json() == {"accepted": 3}

    listed = (await client.get("/api/v1/mobile/logs?limit=10")).json()
    assert listed["total"] == 3
    newest = listed["entries"][0]
    assert newest["message"] == "Merge failed" and newest["level"] == "ERROR"
    assert newest["app_version"] == "1.0.1 (2)"
    assert newest["fields"]["calls"] == "c1:ACTIVE | c2:HOLDING"

    # level filter is a floor: ERROR only
    errors = (await client.get("/api/v1/mobile/logs?level=ERROR")).json()
    assert [e["message"] for e in errors["entries"]] == ["Merge failed"]
    # text search
    found = (await client.get("/api/v1/mobile/logs?search=Merge")).json()
    assert found["total"] == 2


async def test_reps_see_only_their_own_logs_admins_see_the_company(api, world, db):
    await verified_device(api, db, world, world.rep, REP_CLI)
    await verified_device(api, db, world, world.rep2, REP2_CLI)
    await api.as_user(world.rep).post("/api/v1/mobile/logs", json={"entries": [entry(1, message="from rep one")]})
    await api.as_user(world.rep2).post("/api/v1/mobile/logs", json={"entries": [entry(1, message="from rep two")]})

    mine = (await api.as_user(world.rep).get("/api/v1/mobile/logs")).json()
    assert [e["message"] for e in mine["entries"]] == ["from rep one"]

    admin = (await api.as_user(world.admin).get("/api/v1/mobile/logs")).json()
    assert {e["message"] for e in admin["entries"]} == {"from rep one", "from rep two"}

    # another tenant sees nothing of ours
    assert (await api.as_user(world.outsider).get("/api/v1/mobile/logs")).json()["total"] == 0


async def test_bad_rows_do_not_lose_the_batch(api, world, db):
    await verified_device(api, db, world, world.rep, REP_CLI)
    r = await api.as_user(world.rep).post("/api/v1/mobile/logs", json={
        "device_id": "not-a-uuid",
        "entries": [
            {"seq": 1, "level": "SHOUT", "tag": "T", "message": "odd level", "fields": {}, "device_ts": "nonsense"},
            entry(2, message="fine"),
        ],
    })
    assert r.status_code == 200 and r.json() == {"accepted": 2}
    entries = (await api.as_user(world.rep).get("/api/v1/mobile/logs")).json()["entries"]
    assert {e["level"] for e in entries} == {"INFO"}
    assert all(e["device_id"] is None for e in entries)


async def test_oversized_batch_rejected(api, world, db):
    await verified_device(api, db, world, world.rep, REP_CLI)
    r = await api.as_user(world.rep).post(
        "/api/v1/mobile/logs", json={"entries": [entry(i) for i in range(501)]}
    )
    assert r.status_code == 422  # schema caps the batch before it reaches the service
