"""One business cannot reach another's rows or files (Phase 14 M2, tech spec §13.3).

Every attempt must be refused — 401, 403 or 404 — and say nothing of what it
reached for: the owner's marker (in names, file contents, record fields) never
appears in the answer. A list never holds the owner's ids. A redirect counts as
reaching the file (it would be a signed storage link).
"""
from __future__ import annotations

import uuid

import pytest

REFUSED = {401, 403, 404}


def _refused(response, owner, what):
    assert response.status_code in REFUSED, f"{what}: {response.status_code} {response.text[:300]}"
    assert owner.marker not in response.text, f"{what} disclosed the owner's data"


# ── Each business is set up as the suite expects ──────────────────────────────

def test_each_business_has_its_own_ready_workspace(world):
    assert world["a"].tenant_key != world["b"].tenant_key
    for biz in world.values():
        got = biz.client.get("/api/v1/workspace")
        assert got.status_code == 200 and got.json().get("ready") is True, got.text
        # And its own rows are there for it.
        assert biz.client.get(f"/api/v1/ai/entities/{biz.ids['agent']}").status_code == 200
        if not biz.no_run:
            assert biz.client.get(f"/api/v1/ai/executions/{biz.ids['run']}").status_code == 200


# ── Agents and runs ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/v1/ai/entities/{agent}", None),
    ("PUT", "/api/v1/ai/entities/{agent}", {"description": "changed by another business"}),
    ("DELETE", "/api/v1/ai/entities/{agent}", None),
    ("GET", "/api/v1/ai/entities/{agent}/versions", None),
    ("GET", "/api/v1/ai/executions/{run}", None),
    ("GET", "/api/v1/ai/executions/{run}/trace", None),
    ("GET", "/api/v1/ai/executions/{run}/agent_state", None),
    ("POST", "/api/v1/ai/executions/{run}/cancel", None),
    ("POST", "/api/v1/ai/executions/{run}/retry", None),
    ("POST", "/api/v1/ai/executions/{run}/refine", {"feedback": "again"}),
    ("POST", "/api/v1/ai/executions/{run}/csat", {"score": 1}),
])
def test_agents_and_runs(pair, method, path, body):
    owner, intruder = pair
    if "{run}" in path:
        owner.need("run")
    url = path.format(**owner.ids)
    _refused(intruder.client.request(method, url, json=body), owner, f"{method} {path}")


@pytest.mark.parametrize("path,body", [
    ("/api/v1/ai/execute", {"entity_id": "{agent}", "input_data": {"input": "x"}}),
    ("/api/v1/campaigns", {"agent_id": "{agent}", "name": "not mine",
                           "contact_list": [{"name": "x", "phone": "+15005550006"}]}),
    ("/api/v1/automation/triggers", {"name": "not mine", "kind": "manual", "entity_id": "{agent}"}),
])
def test_another_business_agent_is_no_input(pair, path, body):
    """Naming another business's agent is refused exactly as naming an agent that does not exist:
    the answer tells the intruder nothing about whether the id is someone's."""
    owner, intruder = pair

    def send(agent_id: str):
        filled = {k: (agent_id if v == "{agent}" else v) for k, v in body.items()}
        got = intruder.client.post(path, json=filled)
        return got.status_code, got.text.replace(agent_id, "<id>")

    theirs, nobody = send(owner.ids["agent"]), send(str(uuid.uuid4()))
    assert theirs[0] in REFUSED | {422}, f"{path}: {theirs}"
    assert theirs == nobody, f"{path} answers another business's agent differently: {theirs} vs {nobody}"
    assert owner.marker not in theirs[1]


def test_lists_hold_only_their_own_rows(pair):
    owner, intruder = pair
    for path, key in (("/api/v1/ai/entities?size=100", "agent"), ("/api/v1/ai/executions?size=100", "run"),
                      ("/api/v1/ai/documents", "document"), ("/api/v1/artifacts?limit=100", "artifact"),
                      ("/api/v1/campaigns", "campaign"), ("/api/v1/automation/triggers", "trigger"),
                      ("/api/v1/automation/events?limit=100", "event"), ("/api/v1/connections", "connection")):
        if key not in owner.ids:  # a run the owner had no credit for
            continue
        got = intruder.client.get(path)
        assert got.status_code == 200, f"{path}: {got.status_code} {got.text[:300]}"
        assert owner.ids[key] not in got.text, f"{path} lists the other business's {key}"
        assert owner.marker not in got.text, f"{path} shows the other business's data"


def test_acting_for_another_business_is_refused(pair):
    """``X-Company-Id`` names the database a partner or staff acts in; a business admin may not name another's."""
    owner, intruder = pair
    header = {"X-Company-Id": owner.company_id}
    paths = [f"/api/v1/ai/entities/{owner.ids['agent']}", "/api/v1/ai/entities", "/api/v1/automation/triggers"]
    if "run" in owner.ids:
        paths.append(f"/api/v1/ai/executions/{owner.ids['run']}")
    for path in paths:
        _refused(intruder.client.get(path, headers=header), owner, f"GET {path} acting for the owner")


# ── Documents and files ───────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/v1/ai/documents/{document}", None),
    ("PATCH", "/api/v1/ai/documents/{document}", {"filename": "renamed.txt"}),
    ("DELETE", "/api/v1/ai/documents/{document}", None),
    ("GET", "/api/v1/artifacts/{artifact}", None),
    ("GET", "/api/v1/artifacts/{artifact}/download", None),
    ("DELETE", "/api/v1/artifacts/{artifact}", None),
    ("GET", "/api/v1/files/{artifact}", None),
])
def test_documents_and_files(pair, method, path, body):
    owner, intruder = pair
    url = path.format(**owner.ids)
    _refused(intruder.client.request(method, url, json=body), owner, f"{method} {path}")


def test_a_file_link_is_not_handed_out_for_another_business(pair):
    """``/files/{id}`` answers a signed storage link (302) only to the file's own business."""
    owner, intruder = pair
    mine = owner.client.get(f"/api/v1/files/{owner.ids['artifact']}")
    assert mine.status_code in (200, 302), mine.text
    theirs = intruder.client.get(f"/api/v1/files/{owner.ids['artifact']}")
    assert theirs.status_code in REFUSED and "location" not in theirs.headers


def test_a_public_avatar_is_found_only_under_its_own_business(pair):
    """Avatars are public by design, but only under their own company: naming another finds nothing."""
    owner, intruder = pair
    wrong = intruder.client.get(f"/api/v1/files/{owner.ids['avatar']}/public",
                                params={"company": intruder.company_id})
    assert wrong.status_code == 404, wrong.text[:300]


# ── Campaigns ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/v1/campaigns/{campaign}", None),
    ("GET", "/api/v1/campaigns/{campaign}/status", None),
    ("GET", "/api/v1/campaigns/{campaign}/active-calls", None),
    ("GET", "/api/v1/campaigns/{campaign}/download", None),
    ("PATCH", "/api/v1/campaigns/{campaign}/status?status=paused", None),
])
def test_campaigns(pair, method, path, body):
    owner, intruder = pair
    _refused(intruder.client.request(method, path.format(**owner.ids), json=body), owner, f"{method} {path}")


# ── Automation ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/v1/automation/triggers/{trigger}", None),
    ("PATCH", "/api/v1/automation/triggers/{trigger}", {"enabled": False}),
    ("DELETE", "/api/v1/automation/triggers/{trigger}", None),
    ("GET", "/api/v1/automation/triggers/{trigger}/firings", None),
    ("POST", "/api/v1/automation/triggers/{trigger}/run", None),
    ("GET", "/api/v1/automation/events/{event}", None),
    ("POST", "/api/v1/automation/events/{event}/replay", None),
])
def test_triggers_and_events(pair, method, path, body):
    owner, intruder = pair
    _refused(intruder.client.request(method, path.format(**owner.ids), json=body), owner, f"{method} {path}")


# ── Connections ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/v1/connections/{connection}", None),
    ("POST", "/api/v1/connections/{connection}/test", None),
    ("GET", "/api/v1/connections/{connection}/impact", None),
    ("PUT", "/api/v1/connections/{connection}/grants", {"grants": [{"principal_kind": "all_agents"}]}),
    ("DELETE", "/api/v1/connections/{connection}", None),
])
def test_connections(pair, method, path, body):
    owner, intruder = pair
    _refused(intruder.client.request(method, path.format(**owner.ids), json=body), owner, f"{method} {path}")


# ── Records (Data API) ────────────────────────────────────────────────────────

def test_records(pair):
    owner, intruder = pair
    contact = owner.ids["contact"]
    with owner.records() as data:
        etag = data.get(f"/v1/contact/{contact}").headers["ETag"]  # the version a writer would send
    with intruder.records() as data:
        _refused(data.get(f"/v1/contact/{contact}"), owner, "GET a record")
        _refused(data.patch(f"/v1/contact/{contact}", json={"source": "changed"}, headers={"If-Match": etag}),
                 owner, "PATCH a record")
        _refused(data.delete(f"/v1/contact/{contact}"), owner, "archive a record")
        _refused(data.get(f"/v1/contact/{contact}/history"), owner, "a record's history")
        listed = data.get("/v1/contact", params={"filter[source][eq]": owner.marker})
        assert listed.status_code == 200 and contact not in listed.text and owner.marker not in listed.text
    # The owner's token names the owner's database: it is no key to the intruder's.
    with owner.records() as data:
        assert data.get(f"/v1/contact/{intruder.ids['contact']}").status_code in REFUSED
