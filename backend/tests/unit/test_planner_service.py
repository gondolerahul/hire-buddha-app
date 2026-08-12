"""
Unit tests for src.ai.planner_service
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.ai.planning.planner_service import PlannerService


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def service(mock_db):
    return PlannerService(mock_db, company_id=uuid4())


class TestReconcile:

    @pytest.mark.asyncio
    async def test_reconcile_static_plan(self, service):
        """Should return static plan when dynamic is disabled."""
        entity = MagicMock()
        entity.planning = {
            "static_plan": {
                "steps": [
                    {"name": "step_1", "type": "THOUGHT", "description": "Think"},
                    {"name": "step_2", "type": "TOOL_CALL", "description": "Call tool"},
                ]
            },
            "dynamic_planning": {"enabled": False},
        }
        entity.type = "AGENT"
        entity.identity = {"system_prompt": "You are helpful."}
        run = MagicMock()
        run.id = uuid4()

        result = await service.reconcile(run, entity, {"input": "test"})
        assert "steps" in result
        assert len(result["steps"]) == 2

    @pytest.mark.asyncio
    async def test_reconcile_empty_plan_generates_default_for_action(self, service):
        """Should add a default step for ACTION entities with no steps."""
        entity = MagicMock()
        entity.planning = {
            "static_plan": {"steps": []},
            "dynamic_planning": {"enabled": False},
        }
        entity.type = "ACTION"
        entity.name = "TestAction"
        entity.description = "Do something"
        run = MagicMock()

        result = await service.reconcile(run, entity, {})
        assert len(result["steps"]) == 1
        assert result["steps"][0]["name"] == "Execute"


class TestHasParallelSteps:

    def test_independent_steps_returns_true(self, service):
        """Independent steps without dependencies can run in parallel."""
        steps = [
            {"step_id": "s1", "name": "a", "target": {}},
            {"step_id": "s2", "name": "b", "target": {}},
        ]
        # Both steps are immediately ready, so genuine parallelism exists
        assert service.has_parallel_steps(steps) is True

    def test_sequential_chain_returns_false(self, service):
        """A purely sequential chain cannot run steps in parallel initially."""
        steps = [
            {"step_id": "s1", "name": "a", "target": {}},
            {"step_id": "s2", "name": "b", "target": {"input_dependencies": ["s1"]}},
        ]
        # Only s1 is initially ready, so no initial parallelism
        assert service.has_parallel_steps(steps) is False

    def test_genuine_parallelism_with_deps_returns_true(self, service):
        """Should return True when multiple independent starting waves exist."""
        steps = [
            {"step_id": "s1", "name": "a", "target": {}},
            {"step_id": "s2", "name": "b", "target": {}},
            {"step_id": "s3", "name": "c", "target": {"input_dependencies": ["s1"]}},
        ]
        # s1 and s2 are both initially ready, so returns True
        assert service.has_parallel_steps(steps) is True



class TestValidateGoalProgress:

    @pytest.mark.asyncio
    async def test_validate_goal_success(self, service):
        """Should return parsed score from LLM."""
        mock_resp = MagicMock()
        mock_resp.output = '{"score": 90, "reasoning": "Goal achieved", "goal_achieved": true}'
        with patch.object(service.llm, 'call_llm', AsyncMock(return_value=mock_resp)):
            result = await service.validate_goal_progress(
                goal="Summarize the document",
                completed_steps=[{"name": "analyze", "output": "Summary complete."}],
                total_steps=2,
            )
            assert result["score"] == 90
            assert result["goal_achieved"] is True

    @pytest.mark.asyncio
    async def test_validate_goal_failure_returns_default(self, service):
        """Should return default score on LLM failure."""
        with patch.object(service.llm, 'call_llm',
                          AsyncMock(side_effect=RuntimeError("LLM down"))):
            result = await service.validate_goal_progress(
                goal="Research AI trends",
                completed_steps=[],
                total_steps=5,
            )
            assert result["score"] == 50
            assert result["goal_achieved"] is False


class TestAdaptPlan:

    @pytest.mark.asyncio
    async def test_adapt_plan_returns_revised_steps(self, service):
        """When v2 is on, returns the PlanGenerator's chosen steps."""
        revised_steps = [
            {"name": "retry_search", "type": "TOOL_CALL", "description": "Retry"}
        ]
        chosen = MagicMock()
        chosen.steps = revised_steps
        gen_result = MagicMock()
        gen_result.chosen = chosen
        with patch('src.ai.core.feature_flags.FeatureFlags.is_on',
                   AsyncMock(return_value=True)), \
             patch('src.ai.planning.plan_generator.PlanGenerator.generate',
                   AsyncMock(return_value=gen_result)):
            result = await service.adapt_plan(
                original_plan=[{"step_id": "s1", "name": "search"}],
                completed_steps=[],
                failed_step={"name": "search", "error": "timeout"},
                goal="Find information",
            )
            assert len(result) >= 1
            assert result[0]["name"] == "retry_search"

    @pytest.mark.asyncio
    async def test_adapt_plan_falls_back_to_remaining_when_v2_off(self, service):
        """When v2 is off, returns the not-yet-completed original steps."""
        with patch('src.ai.core.feature_flags.FeatureFlags.is_on',
                   AsyncMock(return_value=False)):
            result = await service.adapt_plan(
                original_plan=[{"step_id": "s1", "name": "search"},
                               {"step_id": "s2", "name": "summarize"}],
                completed_steps=[{"step_id": "s1", "name": "search"}],
                failed_step={"name": "summarize", "error": "boom"},
                goal="Find information",
            )
        assert [s["name"] for s in result] == ["summarize"]


def _make_child(name, typ="AGENT", goal="does work"):
    c = MagicMock()
    c.id = uuid4()
    c.name = name
    c.type = typ
    c.goal = goal
    c.description = goal
    return c


def _llm_resp(output):
    return MagicMock(
        output=output, provider="mock", model_name="mock-model",
        prompt_tokens=1, completion_tokens=1, latency_ms=1,
    )


class TestRoutingDirective:

    def test_no_tools_router_forbids_self_work(self, service):
        d = service._routing_directive("PROCESS", has_tools=False)
        assert "CHILD_ENTITY_INVOCATION" in d
        assert "NO tools" in d
        assert "at least one" in d.lower()
        # Must explicitly forbid doing the document work itself.
        assert "DO NOT" in d

    def test_router_with_tools_omits_no_tools_clause(self, service):
        d = service._routing_directive("AGENT", has_tools=True)
        assert "CHILD_ENTITY_INVOCATION" in d
        assert "NO tools" not in d


class TestEnforceChildRouting:
    """BUG 2 — a routing PROCESS/AGENT must delegate to >=1 child."""

    @pytest.mark.asyncio
    async def test_passthrough_when_valid_invocation_present(self, service):
        child = _make_child("XLSX Agent")
        steps = [{
            "type": "CHILD_ENTITY_INVOCATION", "name": "x",
            "target": {"entity_id": str(child.id)},
        }]
        run = MagicMock(); run.id = uuid4()
        out = await service._enforce_child_routing(
            run=run, entity=MagicMock(), user_input="make xlsx",
            valid_steps=steps, child_entities=[child],
        )
        assert out is steps  # unchanged — no extra LLM call

    @pytest.mark.asyncio
    async def test_flat_plan_gets_routed_to_matching_child(self, service):
        """ACTION-only plan (LLM tried to do the work) → child invocation."""
        child = _make_child("XLSX Agent")
        other = _make_child("PPTX Agent")
        steps = [{"type": "ACTION", "name": "write openpyxl code", "target": {}}]
        run = MagicMock(); run.id = uuid4()
        routing_out = __import__('json').dumps(
            [{"entity_id": str(child.id), "instruction": "build the spreadsheet"}]
        )
        with patch.object(service.llm, 'call_llm', AsyncMock(return_value=_llm_resp(routing_out))), \
             patch.object(service, '_log_planner_usage', AsyncMock()):
            out = await service._enforce_child_routing(
                run=run, entity=MagicMock(), user_input="make xlsx",
                valid_steps=steps, child_entities=[child, other],
            )
        invs = [s for s in out if s["type"] == "CHILD_ENTITY_INVOCATION"]
        assert len(invs) == 1
        assert invs[0]["target"]["entity_id"] == str(child.id)
        assert invs[0]["target"]["prompt_template"] == "build the spreadsheet"

    @pytest.mark.asyncio
    async def test_fallback_to_all_children_when_routing_empty(self, service):
        """If the routing LLM yields nothing, route to every child (never pass through)."""
        c1 = _make_child("A"); c2 = _make_child("B")
        steps = [{"type": "THOUGHT", "name": "think", "target": {}}]
        run = MagicMock(); run.id = uuid4()
        with patch.object(service, '_route_children_llm', AsyncMock(return_value=[])):
            out = await service._enforce_child_routing(
                run=run, entity=MagicMock(), user_input="x",
                valid_steps=steps, child_entities=[c1, c2],
            )
        invs = [s for s in out if s["type"] == "CHILD_ENTITY_INVOCATION"]
        assert len(invs) == 2
        assert {i["target"]["entity_id"] for i in invs} == {str(c1.id), str(c2.id)}

    @pytest.mark.asyncio
    async def test_route_children_llm_filters_unknown_ids(self, service):
        child = _make_child("A")
        run = MagicMock(); run.id = uuid4()
        out = __import__('json').dumps([
            {"entity_id": "not-a-real-id", "instruction": "x"},
            {"entity_id": str(child.id), "instruction": "do it"},
        ])
        with patch.object(service.llm, 'call_llm', AsyncMock(return_value=_llm_resp(out))), \
             patch.object(service, '_log_planner_usage', AsyncMock()):
            routed = await service._route_children_llm(run, MagicMock(), "req", [child])
        assert len(routed) == 1
        assert routed[0]["entity_id"] == str(child.id)
        assert routed[0]["instruction"] == "do it"


class TestReconcileRouterEnforcement:
    """End-to-end of the reconcile → dynamic-plan → enforce path (BUG 2)."""

    @pytest.mark.asyncio
    async def test_static_less_router_plan_yields_child_invocation(self, service):
        child = _make_child("XLSX Agent", goal="make spreadsheets")
        child.capabilities = {"tools": []}
        child.identity = {}

        entity = MagicMock()
        entity.id = uuid4()
        entity.name = "doc-factory-process"
        entity.type = "PROCESS"           # EntityType enum behaves like str too
        entity.planning = {
            "static_plan": {"steps": []},  # static-less router → never hits _reconcile
            "dynamic_planning": {"enabled": True},
        }
        entity.identity = {}
        entity.goal = "route document requests to the right specialist"
        entity.capabilities = {"tools": []}  # binds NO tools — pure router

        run = MagicMock()
        run.id = uuid4()
        run.company_id = service.company_id
        run.total_cost_usd = None

        _json = __import__('json')
        # Planner first returns a flat ACTION plan (LLM tries to do the work
        # itself), then the router call selects the XLSX child.
        planner_out = _json.dumps([
            {"name": "Generate xlsx", "type": "ACTION",
             "description": "use openpyxl to build it", "target": {}},
        ])
        router_out = _json.dumps(
            [{"entity_id": str(child.id), "instruction": "build the requested spreadsheet"}]
        )

        with patch.object(service.llm, 'call_llm',
                          AsyncMock(side_effect=[_llm_resp(planner_out), _llm_resp(router_out)])), \
             patch.object(service, '_log_planner_usage', AsyncMock()), \
             patch('src.ai.meta.platform_schema_compiler.resolve_meta_cognition',
                   return_value={"platform_awareness": False}), \
             patch('src.ai.meta.platform_schema_compiler.describe_entity_children',
                   AsyncMock(return_value="## Available Child Entities\n...")), \
             patch('src.ai.meta.platform_schema_compiler.load_entity_children',
                   AsyncMock(return_value=[child])), \
             patch('src.ai.core.feature_flags.FeatureFlags.is_on',
                   AsyncMock(return_value=False)):
            result = await service.reconcile(
                run, entity, {"input": "Make me an XLSX sales report"}
            )

        steps = result["steps"]
        invs = [s for s in steps if s.get("type") == "CHILD_ENTITY_INVOCATION"]
        assert len(invs) >= 1, "router plan must delegate, not print tool code as text"
        assert invs[0]["target"]["entity_id"] == str(child.id)


class TestReconcileV2RouterEnforcement:
    """BUG 2 regression: the v2 PlanGenerator path (planner.v2_enabled=True,
    the production default) has no routing directive, so a static-less router
    comes back with flat THOUGHT/ACTION steps. ``reconcile`` must still enforce
    delegation via the centralised ``_maybe_enforce_router`` — otherwise the
    AgentLoop drives flat steps that produce no child run and no artifact (the
    exact failure observed for doc-factory-process)."""

    @pytest.mark.asyncio
    async def test_v2_flat_router_plan_gets_child_invocation(self, service):
        child = _make_child("XLSX Agent", goal="make spreadsheets")
        child.capabilities = {"tools": []}
        child.identity = {}

        entity = MagicMock()
        entity.id = uuid4()
        entity.name = "doc-factory-process"
        entity.type = "PROCESS"
        entity.planning = {
            "static_plan": {"steps": []},
            "dynamic_planning": {"enabled": True},
        }
        entity.identity = {}
        entity.goal = "route document requests to the right specialist"
        entity.capabilities = {"tools": []}  # pure router

        run = MagicMock()
        run.id = uuid4()
        run.company_id = service.company_id
        run.total_cost_usd = None

        # The v2 generator returns a flat plan with the tell-tale _plan_meta.
        v2_flat = {
            "steps": [
                {"step_id": "step_1_abcd", "name": "Analyze request",
                 "type": "THOUGHT", "target": {}, "input_dependencies": []},
                {"step_id": "step_2_efgh", "name": "Draft via openpyxl",
                 "type": "ACTION", "target": {"workflow": "writing_specialist"},
                 "input_dependencies": ["s1"]},
            ],
            "_plan_meta": {"style": "DAG_PARALLEL"},
        }

        with patch.object(service, '_generate_dynamic_plan_v2',
                          AsyncMock(return_value=v2_flat)), \
             patch('src.ai.meta.platform_schema_compiler.load_entity_children',
                   AsyncMock(return_value=[child])), \
             patch.object(service, '_route_children_llm',
                          AsyncMock(return_value=[{
                              "entity_id": str(child.id),
                              "instruction": "build the spreadsheet"}])), \
             patch('src.ai.core.feature_flags.FeatureFlags.is_on',
                   AsyncMock(return_value=True)):   # planner.v2_enabled ON
            result = await service.reconcile(
                run, entity, {"input": "Make me an XLSX sales report"}
            )

        invs = [s for s in result["steps"] if s.get("type") == "CHILD_ENTITY_INVOCATION"]
        assert len(invs) >= 1, "v2 router plan must be forced to delegate"
        assert invs[0]["target"]["entity_id"] == str(child.id)

    @pytest.mark.asyncio
    async def test_v2_tool_bearing_agent_not_forced_to_delegate(self, service):
        """An AGENT that binds its own tools is NOT a router — its v2 plan
        passes through untouched even with children present."""
        child = _make_child("Sub Agent")
        entity = MagicMock()
        entity.id = uuid4()
        entity.name = "tool-agent"
        entity.type = "AGENT"
        entity.planning = {
            "static_plan": {"steps": []},
            "dynamic_planning": {"enabled": True},
        }
        entity.identity = {}
        entity.goal = "do work with my own tools"
        entity.capabilities = {"tools": [{"tool_id": "sandbox_code"}]}

        run = MagicMock(); run.id = uuid4(); run.company_id = service.company_id
        v2_plan = {"steps": [{"step_id": "s1", "name": "work",
                              "type": "ACTION", "target": {}}],
                   "_plan_meta": {}}

        with patch.object(service, '_generate_dynamic_plan_v2',
                          AsyncMock(return_value=v2_plan)), \
             patch('src.ai.meta.platform_schema_compiler.load_entity_children',
                   AsyncMock(return_value=[child])), \
             patch('src.ai.core.feature_flags.FeatureFlags.is_on',
                   AsyncMock(return_value=True)):
            result = await service.reconcile(run, entity, {"input": "go"})

        assert result["steps"] == v2_plan["steps"]  # untouched
        assert all(s.get("type") != "CHILD_ENTITY_INVOCATION" for s in result["steps"])
