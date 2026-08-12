#!/usr/bin/env python3
"""
lint_ai_layout.py — Enforces the AI package shape defined in
docs/phase11/07_folder_restructure.md.

Exits non-zero on violation; prints a single-line error per violation.

Run manually:
    python backend/scripts/lint_ai_layout.py
Or hooked into pre-commit / CI.
"""
from __future__ import annotations

import re
import sys
from typing import Optional
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = REPO_ROOT / "backend" / "src" / "ai"

# Top-level files allowed directly under backend/src/ai/. Track 1 will move
# the remaining service-layer modules (models.py, schemas.py, *_service.py,
# etc.) into orm/, schemas/, services/. Until then, they live on a transitional
# allow-list.
ALLOWED_TOPLEVEL: set[str] = {
    "__init__.py",
    "worker.py",
    "README.md",
    # Phase 11 Track 9 — onboarding doc lives at the package root.
    "ONBOARDING.md",
}

# Transitional: legacy top-level modules still tolerated. Each entry MUST be
# removed by the Track listed in the trailing comment.
TRANSITIONAL_TOPLEVEL: set[str] = {
    # Track 1 — schemas/ + orm/ split
    "schemas.py",
    "models.py",
    # Track 1 — services/ extraction
    "service.py",
    "router.py",
    "constants.py",
    "tools.py",
    "step_executor.py",
    "tool_executor.py",
    "tool_fallback.py",
    "text_extractor.py",
    "entity_clone_helpers.py",
    "failure_pattern_service.py",
    "persona_service.py",
    "usage_service.py",
    "artifact_models.py",
    "artifact_router.py",
    "artifact_service.py",
    "campaign_executor.py",
    "campaign_models.py",
    "campaign_router.py",
    "campaign_service.py",
    "campaign_worker.py",
    "email_models.py",
    "email_router.py",
    "lead_queue_model.py",
    "lead_queue_service.py",
    "lead_queue_worker.py",
    "reports_router.py",
    "reports_service.py",
    "social_connection_service.py",
    "social_models.py",
    "social_router.py",
    "tool_management_router.py",
    "tool_management_service.py",
}

# Maximum line counts per package. Caps reflect HEAD reality plus a small
# buffer; tighten as each Track lands. The Phase 11 plan's aspirational caps
# (core/600, planning/600, memory/800, meta/800, governance/600, tools/1000,
# llm/800) are the post-programme targets.
MAX_LINES: dict[str, int] = {
    "core": 1500,         # agent_loop.py is 1480 (loop + suspend/resume).
    "planning": 700,
    "memory": 1200,       # cortex_service.py is 1117 (CORTEX engine).
    "meta": 900,          # platform_schema_compiler.py is 839.
    "governance": 600,
    "tools": 1000,
    "llm": 800,
    "shared": 400,
}

# Forbidden patterns inside source files.
FORBIDDEN_IMPORT_PATTERNS: list[str] = [
    "from src.ai.worker import ",
    "import src.ai.worker",
]

# Forbidden cross-package aliases that mask name collisions.
FORBIDDEN_ALIAS_PATTERNS: list[str] = [
    " as CortexService",       # the CortexRouter alias dance — Track 0 killed it
]


# Comment-narration ban. These patterns mark historical narrative
# ("# Phase 10D: ...", "# Fix B: ...", etc.) that new readers find
# confusing. Load-bearing rules should be rewritten as invariant comments
# instead ("MUST run before commit() to ...").
# Mode: "warn" → reported but does not fail the lint; "error" → counts
# as a violation.
COMMENT_NARRATION_MODE: str = "error"

COMMENT_NARRATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"#\s*Phase\s+\d+", re.IGNORECASE),
    re.compile(r"#\s*Fix\s+[A-Z]?\d?\s*:", re.IGNORECASE),
    re.compile(r"#\s*RACE-\d+", re.IGNORECASE),
    re.compile(r"#\s*Ph-[A-Z]", re.IGNORECASE),
    re.compile(r"#\s*Gap\s*#\d+", re.IGNORECASE),
]


# Canary-label ban (de-canary). No source identifier or filename under
# backend/src/ai may carry the canary prefix (p11 / P11 / phase11). The
# only retained references live in one-release redirect shims outside this
# tree (main.py, the frontend route table), which carry removal dates.
CANARY_LABEL_MODE: str = "error"

CANARY_LABEL_PATTERN: re.Pattern[str] = re.compile(r"\b[pP]11\b|phase11", re.IGNORECASE)


def lint() -> int:
    violations: list[str] = []

    # 1. Top-level file whitelist.
    if AI_ROOT.exists():
        allowed = ALLOWED_TOPLEVEL | TRANSITIONAL_TOPLEVEL
        for p in AI_ROOT.iterdir():
            if p.is_file() and p.name not in allowed:
                violations.append(
                    f"LAYOUT: top-level file not allowed: "
                    f"backend/src/ai/{p.name}"
                )

    # 2. File size caps per package.
    for pkg, cap in MAX_LINES.items():
        pkg_root = AI_ROOT / pkg
        if not pkg_root.exists():
            continue
        for py in pkg_root.rglob("*.py"):
            try:
                n = sum(1 for _ in py.read_text().splitlines())
            except OSError:
                continue
            if n > cap:
                violations.append(
                    f"SIZE: {py.relative_to(REPO_ROOT)} has {n} lines "
                    f"(cap for {pkg}/ is {cap})"
                )

    # 3. Forbidden import / alias patterns inside ai/.
    if AI_ROOT.exists():
        for py in AI_ROOT.rglob("*.py"):
            try:
                text = py.read_text()
            except OSError:
                continue
            for pat in FORBIDDEN_IMPORT_PATTERNS:
                if pat in text:
                    violations.append(
                        f"IMPORT: {py.relative_to(REPO_ROOT)} contains "
                        f"forbidden pattern '{pat}'"
                    )
            for pat in FORBIDDEN_ALIAS_PATTERNS:
                if pat not in text:
                    continue
                # Backwards-compat alias is allowed when the file marks it.
                if "Backwards-compat alias" in text or "DEPRECATED" in text:
                    continue
                violations.append(
                    f"ALIAS: {py.relative_to(REPO_ROOT)} contains "
                    f"forbidden pattern '{pat}'"
                )

    # 4. Comment-narration sweep.
    narration_hits: list[str] = []
    if AI_ROOT.exists():
        for py in AI_ROOT.rglob("*.py"):
            try:
                text = py.read_text()
            except OSError:
                continue
            in_triple_string: Optional[str] = None
            for lineno, line in enumerate(text.splitlines(), start=1):
                # Track open/close of triple-quoted blocks so docstring
                # and prompt-template content doesn't trip the matcher.
                idx = 0
                while idx < len(line):
                    if in_triple_string:
                        end = line.find(in_triple_string, idx)
                        if end == -1:
                            idx = len(line)
                            break
                        idx = end + 3
                        in_triple_string = None
                    else:
                        d3 = line.find('"""', idx)
                        s3 = line.find("'''", idx)
                        nxt = min((p for p in (d3, s3) if p != -1), default=-1)
                        if nxt == -1:
                            break
                        in_triple_string = '"""' if nxt == d3 else "'''"
                        idx = nxt + 3
                if in_triple_string is not None:
                    continue
                stripped = line.lstrip()
                if not stripped.startswith("#"):
                    continue
                for pat in COMMENT_NARRATION_PATTERNS:
                    if pat.search(line):
                        narration_hits.append(
                            f"NARRATION: {py.relative_to(REPO_ROOT)}:{lineno} "
                            f"matches {pat.pattern!r}"
                        )
                        break

    # 5. Canary-label sweep (filenames + source identifiers).
    canary_hits: list[str] = []
    if AI_ROOT.exists():
        for py in AI_ROOT.rglob("*.py"):
            rel = py.relative_to(REPO_ROOT)
            # Skip Alembic migrations: renaming applied revisions is unsafe.
            if "migrations" in py.parts:
                continue
            if CANARY_LABEL_PATTERN.search(py.name):
                canary_hits.append(f"CANARY: filename carries canary label: {rel}")
            try:
                text = py.read_text()
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if CANARY_LABEL_PATTERN.search(line):
                    canary_hits.append(
                        f"CANARY: {rel}:{lineno} carries canary label "
                        f"(p11/P11/phase11)"
                    )

    # 6. tools/ root must hold only the package shell (C8 subgrouping).
    #    Every concrete tool lives in a subpackage; the root keeps only the
    #    registry shell + resilience wrapper.
    tools_root = AI_ROOT / "tools"
    TOOLS_ROOT_ALLOWED = {"__init__.py", "base.py", "resilience.py", "README.md"}
    if tools_root.exists():
        for p in tools_root.iterdir():
            if p.is_file() and p.name not in TOOLS_ROOT_ALLOWED:
                violations.append(
                    f"LAYOUT: loose tool file at tools/ root (move to a "
                    f"subpackage): backend/src/ai/tools/{p.name}"
                )

    for v in violations:
        print(v)
    for n in narration_hits:
        print(n)
    for c in canary_hits:
        print(c)
    if COMMENT_NARRATION_MODE == "error":
        violations.extend(narration_hits)
    if CANARY_LABEL_MODE == "error":
        violations.extend(canary_hits)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(lint())
