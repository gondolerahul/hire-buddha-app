"""The isolation suite runs against a deployed environment (tech spec §13.3).

It needs two businesses on that environment and a token for an admin of each:
``python -m scripts.isolation_tenants`` makes them (run it where the platform's
settings are, e.g. in an API pod) and prints the JSON this suite reads.

    ISOLATION_BASE_URL   the platform API, e.g. https://gateway.azdev.hirebuddha.com
    ISOLATION_FIXTURES   path to that JSON

Without both, every test here is skipped (``REQUIRE_ISOLATION=1`` makes that a
failure). Each business makes one of everything — an agent, a run, a document,
a file, an avatar, a campaign, a trigger and its event, a connection, a record
— and the other business then tries each one by id. What the suite makes is
deleted at the end, except the run, the campaign and the event, which have no
delete.
"""
from __future__ import annotations

import io
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Dict, Iterator

import httpx
import pytest

BASE_URL = os.environ.get("ISOLATION_BASE_URL", "").rstrip("/")
FIXTURES = os.environ.get("ISOLATION_FIXTURES", "")
SIDES = ("a", "b")


@dataclass
class Business:
    side: str
    company_id: str
    tenant_key: str
    client: httpx.Client
    marker: str
    ids: Dict[str, str] = field(default_factory=dict)
    records_token: str = ""
    no_run: str = ""  # why this business could not start a run, if it could not

    def need(self, key: str) -> str:
        if key == "run" and self.no_run:
            pytest.skip(f"business {self.side} could not start a run: {self.no_run}")
        return self.ids[key]

    def records(self, token: str | None = None) -> httpx.Client:
        """A Data API client with this business's records token (or the one given)."""
        return httpx.Client(base_url=f"{BASE_URL}/data", timeout=30,
                            headers={"Authorization": f"Bearer {token or self.records_token}"})


def _check(response: httpx.Response, what: str) -> dict:
    assert response.status_code < 300, f"{what}: {response.status_code} {response.text[:500]}"
    return response.json() if response.content else {}


def _make_everything(biz: Business) -> None:
    c, ids, mark = biz.client, biz.ids, biz.marker
    agent = _check(c.post("/api/v1/ai/entities", json={
        "name": f"isolation agent {mark}", "type": "AGENT", "status": "DRAFT",
        "identity": {"system_prompt": "Reply with the single word OK."}}), "agent")
    ids["agent"] = agent["id"]

    started = c.post("/api/v1/ai/execute", json={
        "entity_id": ids["agent"], "input_data": {"input": f"isolation {mark}"}})
    if started.status_code == 402:  # a business with no credit: the run cases are skipped
        biz.no_run = started.json().get("detail", "no credit")
    else:
        ids["run"] = _check(started, "run")["id"]
        c.post(f"/api/v1/ai/executions/{ids['run']}/cancel")  # no model spend beyond a first step

    doc = _check(c.post("/api/v1/ai/documents/upload", files={
        "file": (f"isolation-{mark}.txt", io.BytesIO(f"isolation marker {mark}".encode()), "text/plain")}),
        "document")
    ids["document"] = doc["id"]

    art = _check(c.post("/api/v1/artifacts/upload", data={"file_category": "text", "purpose": mark}, files={
        "file": (f"isolation-{mark}.txt", io.BytesIO(f"isolation file {mark}".encode()), "text/plain")}),
        "artifact")
    ids["artifact"] = art["id"]

    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15"
           b"\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND"
           b"\xaeB`\x82")
    avatar = _check(c.post("/api/v1/ai/avatar/upload", files={"file": ("a.png", io.BytesIO(png), "image/png")}),
                    "avatar")
    ids["avatar_url"] = avatar["url"]
    ids["avatar"] = avatar["url"].split("/api/v1/files/")[1].split("/")[0]

    campaign = _check(c.post("/api/v1/campaigns", json={
        "agent_id": ids["agent"], "name": f"isolation campaign {mark}",
        "contact_list": [{"name": f"isolation {mark}", "phone": "+15005550006"}]}), "campaign")
    ids["campaign"] = campaign["id"]

    trigger = _check(c.post("/api/v1/automation/triggers", json={
        "name": f"isolation trigger {mark}", "kind": "manual", "entity_id": ids["agent"]}), "trigger")
    ids["trigger"] = trigger["id"]
    # A draft agent does not run from a trigger: the event is recorded, nothing is spent.
    event = _check(c.post(f"/api/v1/automation/triggers/{ids['trigger']}/run"), "trigger run")
    ids["event"] = event["id"]

    conn = _check(c.post("/api/v1/connections/form", json={
        "connector_id": "provider_api_key", "display_name": f"isolation {mark}",
        "fields": {"provider": f"isolation-{mark}", "api_key": f"not-a-real-key-{mark}"}}), "connection")
    ids["connection"] = conn["id"]

    token = _check(c.post("/api/v1/records/token"), "records token")
    assert token["tenant"] == biz.tenant_key
    biz.records_token = token["token"]
    with biz.records() as data:
        contact = _check(data.post("/v1/contact", json={"first_name": "Isolation", "last_name": mark,
                                                         "source": mark}), "contact")
    ids["contact"] = contact.get("id") or contact["data"]["id"]


def _clean_up(biz: Business) -> None:
    c, ids = biz.client, biz.ids
    for path in (f"/api/v1/automation/triggers/{ids.get('trigger')}", f"/api/v1/connections/{ids.get('connection')}",
                 f"/api/v1/ai/documents/{ids.get('document')}", f"/api/v1/artifacts/{ids.get('artifact')}",
                 f"/api/v1/artifacts/{ids.get('avatar')}"):
        if "None" not in path:
            c.delete(path)
    if ids.get("contact") and biz.records_token:
        with biz.records() as data:
            data.delete(f"/v1/contact/{ids['contact']}")


@pytest.fixture(scope="session")
def world() -> Iterator[Dict[str, Business]]:
    if not (BASE_URL and FIXTURES):
        if os.environ.get("REQUIRE_ISOLATION") == "1":
            pytest.fail("ISOLATION_BASE_URL and ISOLATION_FIXTURES are required")
        pytest.skip("no environment to test: set ISOLATION_BASE_URL and ISOLATION_FIXTURES")
    with open(FIXTURES, encoding="utf-8") as fh:
        fixtures = json.load(fh)
    run = uuid.uuid4().hex[:8]
    businesses: Dict[str, Business] = {}
    for side in SIDES:
        f = fixtures[side]
        client = httpx.Client(base_url=BASE_URL, timeout=60, follow_redirects=False,
                              headers={"Authorization": f"Bearer {f['token']}"})
        businesses[side] = Business(side, f["company_id"], f["tenant_key"], client, f"{side}-{run}")
    try:
        for biz in businesses.values():
            _make_everything(biz)
        yield businesses
    finally:
        for biz in businesses.values():
            try:
                _clean_up(biz)
            finally:
                biz.client.close()


@pytest.fixture(params=[("a", "b"), ("b", "a")], ids=["b-reaches-for-a", "a-reaches-for-b"])
def pair(request, world):
    """(owner, intruder): every case runs both ways."""
    owner, intruder = request.param
    return world[owner], world[intruder]
