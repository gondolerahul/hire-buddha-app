"""
ai.core.budget — Typed Budget (Phase 11 Track 2).

The Budget is a first-class object the AgentLoop reads on every
iteration. Strategist consults ``pressure`` and ``can_afford``; the
Critic skips itself when pressure is high; the loop terminates when
``exhausted()``.

The four axes are intentionally independent — any one hitting 100%
triggers ``exhausted()``. Code that needs to know *which* axis blew
inspects ``which_exhausted()``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Literal, Optional

__all__ = ["Budget", "BudgetAxis", "budget_prompt_lines"]


def budget_prompt_lines(pressure: float, threshold: float) -> dict[str, str]:
    """Prompt constraint lines for budget-aware REACT (Phase 12 `07` §2).

    Always surfaces the consumed fraction; past ``threshold`` it adds an
    explicit "finish, don't expand" directive so the LLM plans within budget
    rather than relying on the hard engine cap alone. Pure (no I/O) so it is
    unit-testable; the step executor resolves the flag/threshold and merges the
    result into its execution-constraints block.
    """
    lines = {"Budget pressure": f"{pressure:.0%} of budget consumed"}
    if pressure >= threshold:
        lines["Budget directive"] = (
            "Budget is nearly exhausted — finish the task NOW with the cheapest "
            "sufficient action. Do not expand scope, add steps, or start new "
            "subtasks; produce the best final answer you can with what you "
            "already have."
        )
    return lines


BudgetAxis = Literal["tokens", "usd", "wall_s", "iters"]


_ZERO = Decimal("0")


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return _ZERO
    return Decimal(str(value))


@dataclass
class Budget:
    """Tracks token / USD / wall-clock / iteration consumption.

    Caps are inclusive: a 100% used axis is exhausted.
    """
    tokens_max: int = 0          # 0 ⇒ axis disabled (no cap)
    tokens_used: int = 0

    usd_max: Decimal = field(default_factory=lambda: Decimal("0"))
    usd_used: Decimal = field(default_factory=lambda: Decimal("0"))

    wall_max_s: int = 0
    wall_used_s: int = 0

    iters_max: int = 0
    iters: int = 0

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_governance(
        cls,
        *,
        max_cost_usd: Optional[float],
        timeout_ms: Optional[int],
        max_iters: int = 100,
        max_tokens: int = 2_000_000,
    ) -> "Budget":
        """Build a Budget from entity governance config.

        Sensible defaults applied for axes the entity doesn't specify.
        ``timeout_ms`` is in milliseconds (matches Governance.timeout_ms).
        """
        return cls(
            tokens_max=max_tokens,
            usd_max=_to_decimal(max_cost_usd) if max_cost_usd is not None else Decimal("100"),
            wall_max_s=(timeout_ms // 1000) if timeout_ms else 7200,
            iters_max=max_iters,
        )

    # ------------------------------------------------------------------
    # Pressure + exhaustion
    # ------------------------------------------------------------------

    def _axis_pressure(self) -> dict[BudgetAxis, float]:
        out: dict[BudgetAxis, float] = {}
        if self.tokens_max > 0:
            out["tokens"] = self.tokens_used / self.tokens_max
        if self.usd_max > 0:
            out["usd"] = float(self.usd_used / self.usd_max)
        if self.wall_max_s > 0:
            out["wall_s"] = self.wall_used_s / self.wall_max_s
        if self.iters_max > 0:
            out["iters"] = self.iters / self.iters_max
        return out

    @property
    def pressure(self) -> float:
        """Max usage fraction across all enabled axes (0..1+)."""
        axes = self._axis_pressure()
        if not axes:
            return 0.0
        return max(axes.values())

    def which_exhausted(self) -> Optional[BudgetAxis]:
        """Return the first axis at or above 100% (deterministic order)."""
        order: tuple[BudgetAxis, ...] = ("usd", "tokens", "wall_s", "iters")
        axes = self._axis_pressure()
        for axis in order:
            if axes.get(axis, 0.0) >= 1.0:
                return axis
        return None

    def exhausted(self) -> bool:
        return self.which_exhausted() is not None

    def can_afford(
        self,
        *,
        expected_usd: Decimal | float | None = None,
        expected_tokens: int = 0,
        expected_s: int = 0,
    ) -> bool:
        """Would the post-consume state still be < 100% on every axis?"""
        usd_after = self.usd_used + _to_decimal(expected_usd or 0)
        tokens_after = self.tokens_used + expected_tokens
        wall_after = self.wall_used_s + expected_s

        if self.usd_max > 0 and usd_after > self.usd_max:
            return False
        if self.tokens_max > 0 and tokens_after > self.tokens_max:
            return False
        if self.wall_max_s > 0 and wall_after > self.wall_max_s:
            return False
        return True

    # ------------------------------------------------------------------
    # Consumption
    # ------------------------------------------------------------------

    def consume(
        self,
        *,
        tokens: int = 0,
        usd: Decimal | float | None = None,
        wall_s: int = 0,
        iter_step: bool = False,
    ) -> None:
        """Mutates in place. Caller MAY exceed caps; ``exhausted()`` then True."""
        if tokens:
            self.tokens_used += int(tokens)
        if usd:
            self.usd_used += _to_decimal(usd)
        if wall_s:
            self.wall_used_s += int(wall_s)
        if iter_step:
            self.iters += 1

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        d = asdict(self)
        # Decimal → str for JSON-friendliness (CORTEX node content).
        d["usd_max"] = str(self.usd_max)
        d["usd_used"] = str(self.usd_used)
        d["pressure"] = self.pressure
        return d

    @classmethod
    def restore(cls, snapshot: dict[str, Any]) -> "Budget":
        return cls(
            tokens_max=int(snapshot.get("tokens_max", 0)),
            tokens_used=int(snapshot.get("tokens_used", 0)),
            usd_max=_to_decimal(snapshot.get("usd_max", 0)),
            usd_used=_to_decimal(snapshot.get("usd_used", 0)),
            wall_max_s=int(snapshot.get("wall_max_s", 0)),
            wall_used_s=int(snapshot.get("wall_used_s", 0)),
            iters_max=int(snapshot.get("iters_max", 0)),
            iters=int(snapshot.get("iters", 0)),
        )
