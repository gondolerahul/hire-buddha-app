"""AK-10 — the flags kept by the census do what their names say.

``agent_loop.snapshot_every_iteration`` gates the per-iteration snapshot write;
``bandit.epsilon`` and ``planner.n_candidates`` resolve through the flag
service, so a company or global row overrides the default (they used to read
the defaults dict directly); the three weekly crons skip a company whose flag
is off.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.ai.core import arq_jobs
from src.ai.core.agent_loop import AgentLoop
from src.ai.core.agent_state import AgentState
from src.ai.schemas.enums import EntityType


class _Cortex:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    async def write(self, **kwargs: Any) -> None:
        self.writes.append(kwargs)


class _Db:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _Flags:
    def __init__(self, floats: dict[str, float], on: bool = True) -> None:
        self.floats = floats
        self.on = on
        self.float_calls: list[tuple[str, Any]] = []

    async def is_on(self, key: str, **_: Any) -> bool:
        return self.on

    async def get_float(self, key: str, *, company_id: Any = None, **_: Any) -> float:
        self.float_calls.append((key, company_id))
        return self.floats[key]


def _state() -> AgentState:
    state = AgentState(
        run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(),
        entity_type=EntityType.AGENT,
    )
    state.cortex_working_root_id = uuid4()
    return state


async def test_no_snapshot_is_written_when_the_flag_is_off() -> None:
    loop = AgentLoop(db=_Db(), redis=None, feature_flags=_Flags({}))  # type: ignore[arg-type]
    cortex = _Cortex()
    loop.cortex = cortex
    loop._snapshot_each_iteration = False
    await loop._snapshot(_state())
    assert cortex.writes == []

    loop._snapshot_each_iteration = True
    await loop._snapshot(_state())
    assert len(cortex.writes) == 1


async def test_bandit_epsilon_comes_from_the_flag_service() -> None:
    flags = _Flags({"bandit.epsilon": 0.35})
    loop = AgentLoop(db=_Db(), redis=None, feature_flags=flags)  # type: ignore[arg-type]
    state = _state()
    bandit = await loop._build_bandit(state)
    assert bandit is not None and bandit.epsilon == pytest.approx(0.35)
    assert ("bandit.epsilon", state.company_id) in flags.float_calls


async def test_planner_candidate_count_comes_from_the_flag_service(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.ai.core import feature_flags as ff
    from src.ai.planning import planner_service
    from src.ai.planning.plan_generator import PlanGenerator

    seen: dict[str, int] = {}

    async def _get_float(self: Any, key: str, **_: Any) -> float:
        assert key == "planner.n_candidates"
        return 5.0

    class _Result:
        chosen = type("C", (), {"steps": [], "style": "x", "estimated_cost_usd": 0})()
        alternates: list[Any] = []
        judge_reasoning = ""

    async def _generate(self: Any, ctx: Any, n: int) -> Any:
        seen["n"] = n
        return _Result()

    async def _roster(self: Any, entity: Any, static_plan: Any) -> tuple[str, None]:
        return "", None

    monkeypatch.setattr(ff.FeatureFlags, "get_float", _get_float)
    monkeypatch.setattr(PlanGenerator, "generate", _generate)
    monkeypatch.setattr(planner_service.PlannerService, "_child_roster", _roster)
    svc = planner_service.PlannerService.__new__(planner_service.PlannerService)
    svc.db = None
    svc.company_id = uuid4()
    svc.llm = None
    entity = type("E", (), {"goal": "g", "id": uuid4()})()
    await svc._generate_dynamic_plan_v2(None, entity, {}, {})  # type: ignore[arg-type]
    assert seen["n"] == 5


async def test_a_cron_flag_is_resolved_once_per_company(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.ai.core import feature_flags as ff

    calls: list[Any] = []

    async def _is_on(self: Any, key: str, *, company_id: Any = None, **_: Any) -> bool:
        calls.append((key, company_id))
        return company_id == "on"

    monkeypatch.setattr(ff.FeatureFlags, "is_on", _is_on)
    cache: dict[Any, bool] = {}
    key = "meta_agent.skill_promotion_cron"
    assert await arq_jobs._company_flag_on(None, key, "on", cache) is True
    assert await arq_jobs._company_flag_on(None, key, "off", cache) is False
    assert await arq_jobs._company_flag_on(None, key, "on", cache) is True
    assert calls == [(key, "on"), (key, "off")]
