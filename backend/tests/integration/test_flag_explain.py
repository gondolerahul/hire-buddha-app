"""GH-20: why a flag has its value — explained the way the resolver resolves it.

``explain_flags`` answers every declared flag for a company from one query.
It must agree with ``FeatureFlags.resolve`` / ``resolve_float`` flag by flag,
tier by tier, or the page would explain a value nothing uses. Real Postgres
(rolled back).
"""
from __future__ import annotations

import pytest

from src.ai.core import feature_flags as ff
from src.ai.core.flag_explain import explain_flags

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
async def test_every_flag_is_explained_as_it_resolves(db, test_company_id, monkeypatch):
    flags = ff.FeatureFlags(db)
    # One flag at each tier, numeric ones too, and one from the environment.
    await flags.set("bandit.enabled", enabled=False)                                 # global
    await flags.set("planner.v2_enabled", enabled=False, company_id=test_company_id)  # company
    await flags.set("bandit.enabled", enabled=True, company_id=test_company_id)       # company over global
    await flags.set("planner.n_candidates", value_json=2, company_id=test_company_id)
    await flags.set("bandit.epsilon", value_json=0.3)                                 # global numeric
    monkeypatch.setenv("AI_FLAG_TASK_CLASSIFIER_V2_ENABLED", "true")
    monkeypatch.setenv("AI_FLAG_AGENT_LOOP_BUDGET_PRESSURE_THRESHOLD", "0.9")
    ff.invalidate_process_cache()

    explained = {e["flag_key"]: e for e in await explain_flags(db, test_company_id)}
    assert set(explained) == set(ff.DEFAULTS) | set(ff.NUMERIC_DEFAULTS)

    for key in ff.DEFAULTS:
        resolved = await flags.resolve(key, company_id=test_company_id)
        assert (explained[key]["value"], explained[key]["source"]) == (resolved.value, resolved.source), key
    for key in ff.NUMERIC_DEFAULTS:
        value, source = await flags.resolve_float(key, company_id=test_company_id)
        assert (explained[key]["value"], explained[key]["source"]) == (value, source), key

    assert explained["bandit.enabled"]["source"] == "company"
    assert explained["planner.n_candidates"] == {"flag_key": "planner.n_candidates", "kind": "numeric",
                                                 "value": 2.0, "source": "company"}
    assert explained["task_classifier.v2_enabled"]["source"] in ("env", "global", "company")
    ff.invalidate_process_cache()
