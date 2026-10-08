"""hitl_expression.py — the grammar of a ``CUSTOM`` HITL checkpoint (GH-10).

    expression := clause (("and" | "or") clause)*
    clause     := ("step_count" | "cost") op number
                | "has_key(" quoted-name ")"
    op         := ">" | ">=" | "<" | "<=" | "=="

``and`` binds tighter than ``or``; there are no parentheses. ``step_count`` is
how many step outputs the run has, ``cost`` its spend in USD, ``has_key`` whether
the run's context holds that name. Nothing else parses: an entity whose
expression does not is refused when it is saved (GH-09), and one stored before
that asks a person at run time instead of never firing.
"""
from __future__ import annotations

import operator
import re
from dataclasses import dataclass
from typing import Callable, Collection, Union

__all__ = ["ExpressionError", "parse", "evaluate", "GRAMMAR_HELP"]

GRAMMAR_HELP = ("step_count or cost compared with > >= < <= == to a number, or has_key('name'); "
                "clauses joined by and / or — e.g. cost > 0.50 or step_count > 5")

_TOKEN = re.compile(r"\s*(>=|<=|==|>|<|\(|\)|'[^']*'|\"[^\"]*\"|[A-Za-z_][A-Za-z_0-9]*|\d+(?:\.\d+)?|\.\d+|\S)")
_OPS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq,
}
_VARIABLES = ("step_count", "cost")


class ExpressionError(ValueError):
    """The expression is outside the grammar."""


@dataclass(frozen=True)
class Compare:
    variable: str
    op: str
    value: float


@dataclass(frozen=True)
class HasKey:
    key: str


Clause = Union[Compare, HasKey]


def _tokens(expression: str) -> list[str]:
    tokens = _TOKEN.findall(expression or "")
    if not tokens:
        raise ExpressionError("the expression is empty")
    return tokens


def _number(token: str) -> float:
    try:
        return float(token)
    except ValueError:
        raise ExpressionError(f"expected a number, got {token!r}") from None


def _clause(tokens: list[str], i: int) -> tuple[Clause, int]:
    word = tokens[i]
    if word == "has_key":
        if tokens[i + 1:i + 2] != ["("] or tokens[i + 3:i + 4] != [")"]:
            raise ExpressionError("has_key takes one quoted name: has_key('name')")
        name = tokens[i + 2]
        if len(name) < 2 or name[0] not in "'\"" or name[-1] != name[0]:
            raise ExpressionError("has_key takes one quoted name: has_key('name')")
        return HasKey(name[1:-1]), i + 4
    if word not in _VARIABLES:
        raise ExpressionError(f"unknown name {word!r}: use step_count, cost or has_key('name')")
    if i + 2 >= len(tokens) or tokens[i + 1] not in _OPS:
        raise ExpressionError(f"{word} needs a comparison: one of > >= < <= == and a number")
    return Compare(word, tokens[i + 1], _number(tokens[i + 2])), i + 3


def parse(expression: str) -> list[list[Clause]]:
    """The expression as alternatives of conjunctions: ``a and b or c`` is
    ``[[a, b], [c]]``. Raises ``ExpressionError`` outside the grammar."""
    tokens = _tokens(expression)
    groups: list[list[Clause]] = [[]]
    i = 0
    while True:
        clause, i = _clause(tokens, i)
        groups[-1].append(clause)
        if i == len(tokens):
            return groups
        joiner = tokens[i].lower()
        if joiner == "or":
            groups.append([])
        elif joiner != "and":
            raise ExpressionError(f"expected and / or, got {tokens[i]!r}")
        i += 1
        if i == len(tokens):
            raise ExpressionError(f"the expression ends with {tokens[i - 1]!r}")


def evaluate(expression: str, *, step_count: int, cost: float, keys: Collection[str]) -> bool:
    """Whether the expression holds. Raises ``ExpressionError`` outside the grammar."""
    values = {"step_count": float(step_count), "cost": float(cost)}

    def holds(clause: Clause) -> bool:
        if isinstance(clause, HasKey):
            return clause.key in keys
        return _OPS[clause.op](values[clause.variable], clause.value)

    return any(all(holds(c) for c in group) for group in parse(expression))
