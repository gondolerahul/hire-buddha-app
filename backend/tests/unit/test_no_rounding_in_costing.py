"""Phase 15 T1-5, REQ-CO-1, K-1: nothing in costing, rating or settlement rounds.

Calls were billed per started minute (``ceil``), hosting and sandbox time were
rounded to 6 decimals. Amounts are kept to 10 decimals and rounded only at the
three edges K-1 allows — display, a payment's gateway amount, invoice totals —
none of which is in these modules. A ``round(`` / ``ceil(`` / ``quantize(`` /
``ROUND_*`` here fails this test; a legitimate edge goes in its own module.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"

COSTING_MODULES = [
    "ai/usage_service.py",
    "ai/services/cost_attribution.py",
    "ai/governance/tool_cost_resolver.py",
    "ai/governance/run_cost.py",
    "ai/tools/sandbox/metering.py",
    "ai/memory/embedding_service.py",
    "apps/metering.py",
    "billing/units.py",
    "billing/billing_service.py",
    "gateway/call_spend.py",
    "voice/usage_logger.py",
]
FORBIDDEN_CALLS = {"round", "ceil", "floor", "quantize", "to_integral_value", "to_integral"}


def _rounding(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in FORBIDDEN_CALLS:
                found.append(f"{name}() at line {node.lineno}")
        elif isinstance(node, (ast.Name, ast.Attribute)):
            name = getattr(node, "id", None) or getattr(node, "attr", None)
            if isinstance(name, str) and name.startswith("ROUND_"):
                found.append(f"{name} at line {node.lineno}")
        elif isinstance(node, ast.alias) and node.name.startswith("ROUND_"):
            found.append(f"import {node.name}")
    return found


def test_costing_modules_do_not_round():
    offenders = {module: hits for module in COSTING_MODULES if (hits := _rounding(SRC / module))}
    assert offenders == {}


def test_the_check_sees_rounding(tmp_path):
    sample = tmp_path / "m.py"
    sample.write_text("import math\nfrom decimal import ROUND_HALF_UP\nx = math.ceil(1.5)\ny = round(2.5, 6)\n")
    assert len(_rounding(sample)) == 3
