"""
ai.planning.plan_style_bandit — Phase 11 Track 4 epsilon-greedy bandit.

The bandit decides between candidate plan styles when the Strategist
faces a strategic choice. Arm state lives in the entity's
IntelligenceTree under the existing ``🎯 Strategies`` section, stored
as a STRATEGY-type ``CortexNode`` with one row per ``task_class``.

Arms (see ``PlanStyleArm``):

  * ``DAG_PARALLEL``    — multi-step DAG executor.
  * ``DAG_SEQUENTIAL``  — sequential SingleStep over the plan.
  * ``RECURSIVE``       — recursive expansion.
  * ``SINGLE_TOOL``     — one TOOL_CALL step.
  * ``DIALOG``          — Dialog executor (Track 5+).
  * ``CHILD_ENTITY``    — ChildEntity executor.

State per arm::

    {
      "pulls": int,
      "successes": int,
      "avg_cost_usd": float,
      "last_pull_at": iso8601,
    }

Selection: ε-greedy. ε is read from the FeatureFlags numeric defaults
(``bandit.epsilon``, default 0.10) unless overridden at construction.

Persistence is best-effort — when no DB session is available the
bandit operates in-memory only (useful for unit tests). When a row
write fails for any reason the bandit logs and continues; the next
update will retry naturally.
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

__all__ = [
    "PlanStyleArm",
    "ArmState",
    "PlanStyleBandit",
    "STRATEGIES_SECTION_TITLE",
]


STRATEGIES_SECTION_TITLE = "🎯 Strategies"


class PlanStyleArm(str, Enum):
    DAG_PARALLEL = "DAG_PARALLEL"
    DAG_SEQUENTIAL = "DAG_SEQUENTIAL"
    RECURSIVE = "RECURSIVE"
    SINGLE_TOOL = "SINGLE_TOOL"
    DIALOG = "DIALOG"
    CHILD_ENTITY = "CHILD_ENTITY"


@dataclass
class ArmState:
    pulls: int = 0
    successes: int = 0
    avg_cost_usd: float = 0.05
    last_pull_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pulls": int(self.pulls),
            "successes": int(self.successes),
            "avg_cost_usd": float(self.avg_cost_usd),
            "last_pull_at": self.last_pull_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ArmState":
        return cls(
            pulls=int(raw.get("pulls", 0)),
            successes=int(raw.get("successes", 0)),
            avg_cost_usd=float(raw.get("avg_cost_usd", 0.05)),
            last_pull_at=raw.get("last_pull_at"),
        )


@dataclass
class BanditTable:
    arms: dict[str, ArmState] = field(default_factory=dict)

    def get_or_seed(self, arm: str) -> ArmState:
        if arm not in self.arms:
            self.arms[arm] = ArmState()
        return self.arms[arm]

    def to_json(self) -> str:
        return json.dumps({k: v.to_dict() for k, v in self.arms.items()})

    @classmethod
    def from_json(cls, raw: Optional[str]) -> "BanditTable":
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except Exception:
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls(arms={k: ArmState.from_dict(v) for k, v in data.items()
                         if isinstance(v, dict)})


class PlanStyleBandit:
    """Epsilon-greedy bandit over plan styles.

    Persistence is via the entity's IntelligenceTree (``🎯 Strategies``
    section). When ``db`` is None the bandit is purely in-memory.
    """

    def __init__(
        self,
        db: Any = None,
        company_id: Any = None,
        *,
        epsilon: float = 0.10,
        rng: Optional[random.Random] = None,
        ema_alpha: float = 0.2,
    ):
        self.db = db
        self.company_id = company_id
        self.epsilon = float(epsilon)
        self.rng = rng or random.Random()
        self.ema_alpha = float(ema_alpha)
        self._memory_tables: dict[tuple[Any, str], BanditTable] = {}

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    async def select_arm(
        self,
        *,
        entity_id: Any,
        task_class: str,
        candidates: list[str],
    ) -> tuple[str, bool]:
        """Pick one arm from ``candidates``.

        Returns ``(arm, exploring)`` where ``exploring`` is True when
        the choice was a random exploration pull (informational only).
        """
        if not candidates:
            raise ValueError("PlanStyleBandit.select_arm needs at least one candidate")
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) == 1:
            return candidates[0], False

        table = await self.load_table(entity_id, task_class)
        for c in candidates:
            table.get_or_seed(c)

        if self.rng.random() < self.epsilon:
            return self.rng.choice(candidates), True
        scored = sorted(
            candidates,
            key=lambda c: self.score(table.arms[c]),
            reverse=True,
        )
        return scored[0], False

    # ------------------------------------------------------------------
    # Outcome update
    # ------------------------------------------------------------------

    async def update_arm(
        self,
        *,
        entity_id: Any,
        task_class: str,
        arm: str,
        success: bool,
        cost_usd: float,
    ) -> ArmState:
        table = await self.load_table(entity_id, task_class)
        st = table.get_or_seed(arm)
        st.pulls += 1
        if success:
            st.successes += 1
        alpha = self.ema_alpha
        if st.pulls == 1:
            st.avg_cost_usd = float(cost_usd)
        else:
            st.avg_cost_usd = (1 - alpha) * st.avg_cost_usd + alpha * float(cost_usd)
        st.last_pull_at = datetime.utcnow().isoformat()
        await self.save_table(entity_id, task_class, table)
        return st

    # ------------------------------------------------------------------
    # Score
    # ------------------------------------------------------------------

    @staticmethod
    def score(st: ArmState) -> float:
        """Higher is better. Win-rate-per-dollar with Laplace smoothing."""
        win_rate = (st.successes + 1) / (st.pulls + 2)
        return win_rate / max(st.avg_cost_usd, 0.01)

    # ------------------------------------------------------------------
    # Persistence — IntelligenceTree under 🎯 Strategies
    # ------------------------------------------------------------------

    async def load_table(self, entity_id: Any, task_class: str) -> BanditTable:
        key = (entity_id, task_class)
        if self.db is None or entity_id is None or self.company_id is None:
            return self._memory_tables.setdefault(key, BanditTable())
        try:
            node = await self._find_arm_node(entity_id, task_class)
            if node is None:
                return self._memory_tables.setdefault(key, BanditTable())
            return BanditTable.from_json(node.content)
        except Exception as exc:                                            # pragma: no cover
            logger.debug("bandit load_table fell back to memory: %s", exc)
            return self._memory_tables.setdefault(key, BanditTable())

    async def save_table(
        self, entity_id: Any, task_class: str, table: BanditTable,
    ) -> None:
        key = (entity_id, task_class)
        self._memory_tables[key] = table
        if self.db is None or entity_id is None or self.company_id is None:
            return
        try:
            await self._upsert_arm_node(entity_id, task_class, table)
        except Exception as exc:                                            # pragma: no cover
            logger.warning("bandit save_table failed (kept in memory): %s", exc)

    async def _find_arm_node(self, entity_id: UUID, task_class: str) -> Any:
        from sqlalchemy import select
        from src.ai.memory.cortex_models import (
            CortexNode,
            CortexNodeType,
        )
        from src.ai.memory.intelligence_tree_service import (
            IntelligenceTreeService,
            STRATEGIES_TITLE,
        )

        svc = IntelligenceTreeService(self.db, self.company_id)
        tree = await svc.get_or_create_intelligence_tree(entity_id)
        # Strategies section root
        section = (await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree.id,
                CortexNode.parent_id == tree.root_node_id,
                CortexNode.title == STRATEGIES_TITLE,
            )
        )).scalar_one_or_none()
        if section is None:
            return None
        title = self._arm_node_title(task_class)
        return (await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree.id,
                CortexNode.parent_id == section.id,
                CortexNode.node_type == CortexNodeType.STRATEGY,
                CortexNode.title == title,
            )
        )).scalar_one_or_none()

    async def _upsert_arm_node(self, entity_id: UUID, task_class: str, table: BanditTable) -> None:
        from sqlalchemy import select
        from src.ai.memory.cortex_models import (
            CortexNode,
            CortexNodeStatus,
            CortexNodeType,
        )
        from src.ai.memory.intelligence_tree_service import (
            IntelligenceTreeService,
            STRATEGIES_TITLE,
        )

        svc = IntelligenceTreeService(self.db, self.company_id)
        tree = await svc.get_or_create_intelligence_tree(entity_id)
        section = (await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree.id,
                CortexNode.parent_id == tree.root_node_id,
                CortexNode.title == STRATEGIES_TITLE,
            )
        )).scalar_one_or_none()
        if section is None:
            return  # section missing — abort; caller will retry

        title = self._arm_node_title(task_class)
        summary = self._render_summary(table)
        content = table.to_json()
        existing = await self._find_arm_node(entity_id, task_class)
        if existing is not None:
            existing.summary = summary
            existing.content = content
            existing.metadata_extra = {
                **(existing.metadata_extra or {}),
                "task_class": task_class,
                "updated_at": datetime.utcnow().isoformat(),
            }
            await self.db.flush()
            return

        new_node = CortexNode(
            id=uuid4(),
            tree_id=tree.id,
            parent_id=section.id,
            node_type=CortexNodeType.STRATEGY,
            title=title,
            summary=summary,
            content=content,
            status=CortexNodeStatus.ACTIVE,
            depth=section.depth + 1,
            sibling_order=0,
            metadata_extra={
                "task_class": task_class,
                "kind": "bandit_arm_table",
                "created_at": datetime.utcnow().isoformat(),
            },
        )
        self.db.add(new_node)
        tree.total_nodes = (tree.total_nodes or 0) + 1
        await self.db.flush()

    @staticmethod
    def _arm_node_title(task_class: str) -> str:
        return f"Bandit: {task_class}"

    @staticmethod
    def _render_summary(table: BanditTable) -> str:
        if not table.arms:
            return "Bandit arm table (empty)."
        parts = []
        for arm, st in sorted(table.arms.items()):
            wr = (st.successes / st.pulls) if st.pulls else 0.0
            parts.append(
                f"{arm}: pulls={st.pulls} wins={st.successes} wr={wr:.2f} "
                f"cost=${st.avg_cost_usd:.4f}"
            )
        return " | ".join(parts)
