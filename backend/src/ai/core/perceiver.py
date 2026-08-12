"""
ai.core.perceiver — Gather signals into a typed Perception (Track 2).

The Perceiver is the *only* place that reads from CORTEX / memory /
HITL on behalf of the AgentLoop. Strategist reads ``Perception``; it
does not query CORTEX directly. Track 6 (Memory v2) replaces the
internals here; the surface stays stable.

This Track 2 implementation degrades gracefully:

  * If ``cortex`` is None, ``viewport_text`` is "".
  * If ``memory_assembler`` is None, intelligence + episodic are [].
  * If ``db`` is None, pending_hitl is [].

That lets unit tests construct a Perceiver with all None deps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.ai.core.agent_state import AgentState, Reflection

__all__ = ["Perception", "Perceiver"]


@dataclass
class Perception:
    """One iteration's snapshot of what the agent "sees" before acting."""
    iteration: int
    viewport_text: str = ""
    intelligence_rules: list[dict[str, Any]] = field(default_factory=list)
    recent_reflections: list[Reflection] = field(default_factory=list)
    similar_past_runs: list[dict[str, Any]] = field(default_factory=list)
    budget_pressure: float = 0.0
    pending_hitl: list[dict[str, Any]] = field(default_factory=list)
    open_subgoals_text: str = ""
    last_action_summary: str = ""
    last_observation_summary: str = ""

    def to_prompt_block(self) -> str:
        """Render Perception as a structured text block for LLM injection."""
        parts: list[str] = []
        if self.open_subgoals_text:
            parts.append(f"## Open subgoals\n{self.open_subgoals_text}")
        if self.viewport_text:
            parts.append(f"## CORTEX viewport\n{self.viewport_text}")
        if self.intelligence_rules:
            rules = "\n".join(f"  - {r.get('title') or r.get('id') or '?'}: {r.get('summary', '')}"
                              for r in self.intelligence_rules[:5])
            parts.append(f"## Intelligence rules\n{rules}")
        if self.recent_reflections:
            refs = "\n".join(f"  - iter {r.iteration}: {r.what_worked or r.what_didnt}"
                             for r in self.recent_reflections)
            parts.append(f"## Recent reflections\n{refs}")
        if self.similar_past_runs:
            past = "\n".join(f"  - run {r.get('run_id', '?')}: {r.get('summary', '')}"
                             for r in self.similar_past_runs[:3])
            parts.append(f"## Similar past runs\n{past}")
        if self.pending_hitl:
            parts.append(f"## Pending HITL approvals\n  count={len(self.pending_hitl)}")
        parts.append(f"## Budget pressure\n  {self.budget_pressure:.2f}")
        if self.last_action_summary:
            parts.append(f"## Last action\n{self.last_action_summary}")
        if self.last_observation_summary:
            parts.append(f"## Last observation\n{self.last_observation_summary}")
        return "\n\n".join(parts)


class Perceiver:
    """Gathers Perception from CORTEX + memory + DB. Stateless."""

    def __init__(
        self,
        *,
        db: Any = None,
        cortex: Any = None,
        memory_assembler: Any = None,
        max_viewport_chars: int = 4000,
    ):
        self.db = db
        self.cortex = cortex
        self.memory = memory_assembler
        self.max_viewport_chars = max_viewport_chars

    async def gather(self, state: AgentState) -> Perception:
        viewport_text = await self._gather_viewport(state)
        intel_rules = await self._gather_intelligence_rules(state)
        episodic = await self._gather_similar_runs(state)
        pending_hitl = await self._gather_pending_hitl(state)

        return Perception(
            iteration=state.iteration,
            viewport_text=viewport_text,
            intelligence_rules=intel_rules,
            recent_reflections=state.reflections[-3:],
            similar_past_runs=episodic,
            budget_pressure=state.budget.pressure,
            pending_hitl=pending_hitl,
            open_subgoals_text=self._render_subgoals(state),
            last_action_summary=self._summarise_action(state),
            last_observation_summary=self._summarise_observation(state),
        )

    # ------------------------------------------------------------------
    # Component gatherers (each guards its own deps).
    # ------------------------------------------------------------------

    async def _gather_viewport(self, state: AgentState) -> str:
        if self.cortex is None or state.cortex_cursor is None:
            return ""
        try:
            viewport = await self.cortex.navigate(state.cortex_cursor)
        except Exception:
            return ""
        if viewport is None:
            return ""
        # cortex.navigate returns either a Viewport object with
        # to_prompt_text() or a dict-like response.
        if hasattr(viewport, "to_prompt_text"):
            try:
                txt: str = viewport.to_prompt_text()
            except TypeError:
                # Legacy signature accepted kwargs.
                txt = viewport.to_prompt_text()
        else:
            txt = str(viewport)
        if len(txt) > self.max_viewport_chars:
            txt = txt[: self.max_viewport_chars] + "\n…[truncated]"
        return txt

    async def _gather_intelligence_rules(self, state: AgentState) -> list[dict[str, Any]]:
        if self.memory is None:
            return []
        for attr in ("intelligence_rules", "get_intelligence_rules"):
            fn = getattr(self.memory, attr, None)
            if fn is None:
                continue
            try:
                result = await fn(entity_id=state.entity_id, top_k=5)
            except TypeError:
                try:
                    result = await fn(state.entity_id, 5)
                except Exception:
                    continue
            except Exception:
                continue
            if isinstance(result, list):
                return await self._apply_rule_lifecycle(
                    [self._coerce_dict(r) for r in result], state)
        return []

    async def _apply_rule_lifecycle(
        self, rules: list[dict[str, Any]], state: AgentState,
    ) -> list[dict[str, Any]]:
        """Drop retired rules; with the flag, keep only confirmed (`06` §5)."""
        from src.ai.memory.rule_lifecycle import filter_for_prompt

        confirmed_only = False
        try:
            from src.ai.core.feature_flags import FeatureFlags
            confirmed_only = await FeatureFlags().is_on(
                "memory.rule_lifecycle_confirmed_only",
                company_id=getattr(state, "company_id", None),
            )
        except Exception:
            confirmed_only = False
        return filter_for_prompt(rules, confirmed_only=confirmed_only)

    async def _gather_similar_runs(self, state: AgentState) -> list[dict[str, Any]]:
        if self.memory is None:
            return []
        for attr in ("recent_similar_runs", "similar_runs"):
            fn = getattr(self.memory, attr, None)
            if fn is None:
                continue
            try:
                result = await fn(entity_id=state.entity_id, top_k=3)
            except TypeError:
                try:
                    result = await fn(state.entity_id, 3)
                except Exception:
                    continue
            except Exception:
                continue
            if isinstance(result, list):
                return [self._coerce_dict(r) for r in result]
        return []

    async def _gather_pending_hitl(self, state: AgentState) -> list[dict[str, Any]]:
        if self.db is None:
            return []
        try:
            from sqlalchemy import select

            from src.ai.orm.execution import HumanApproval
            rows = (await self.db.execute(
                select(HumanApproval)
                .where(HumanApproval.run_id == state.run_id)
                .where(HumanApproval.status == "PENDING")
            )).scalars().all()
        except Exception:
            return []
        return [
            {"id": str(r.id), "trigger": r.checkpoint_trigger}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_subgoals(state: AgentState) -> str:
        if not state.open_subgoals:
            return "(none)"
        return "\n".join(
            f"  - [{sg.priority}] {sg.description}"
            f"{' (blocked: ' + sg.blocked_on + ')' if sg.blocked_on else ''}"
            for sg in state.open_subgoals
        )

    @staticmethod
    def _summarise_action(state: AgentState) -> str:
        if state.last_action is None:
            return ""
        a = state.last_action
        return f"iter {a.iteration} via {a.executor} (move_id={a.move_id[:8]})"

    @staticmethod
    def _summarise_observation(state: AgentState) -> str:
        if state.last_observation is None:
            return ""
        o = state.last_observation
        return (
            f"outcome={o.outcome} novelty={o.novelty_score:.2f} "
            f"Δgoal={o.goal_delta_estimate:+.2f} — {o.summary or '(no summary)'}"
        )

    @staticmethod
    def _coerce_dict(obj: Any) -> dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "to_dict"):
            try:
                d = obj.to_dict()
                if isinstance(d, dict):
                    return d
            except Exception:
                pass
        # Last resort: shallow attribute scrape.
        return {k: getattr(obj, k) for k in dir(obj) if not k.startswith("_")}
