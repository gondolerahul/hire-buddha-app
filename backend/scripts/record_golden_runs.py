#!/usr/bin/env python3
"""
record_golden_runs.py — Run the LEGACY ExecutionEngine against each
regression-suite fixture+input pair and save the resulting RunResult
to disk as a "golden" snapshot.

Track 2's parity tests load these snapshots and assert the new
AgentLoop reaches the same status, similar cost, and similar output
without needing a fresh LLM-credit-burning legacy run on every PR.

Usage:
    cd backend
    source .venv/bin/activate
    python -m backend.scripts.record_golden_runs \\
        --output backend/tests/parity/goldens \\
        --cases simple_skill_topic_easy research_agent_brief

Environment requirements:
    * DATABASE_URL — Postgres reachable from this host.
    * REDIS_URL    — Redis reachable from this host.
    * LLM provider env vars (ANTHROPIC_API_KEY, etc.) — real LLM calls
      will be made.

The recorder seeds a fresh test tenant, inserts the entity fixture,
creates an ExecutionRun, runs ExecutionEngine.execute_run, then writes
the snapshot. It does NOT clean up — the operator is expected to use
a throw-away test database.

This script is INTENTIONALLY one-shot. It is not invoked by CI. The
recorded JSON snapshots are checked into the repo at
``backend/tests/parity/goldens/<case_id>.json``.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("record_golden_runs")


async def _record_one(case_id: str, output_dir: Path, *, hermetic: bool) -> bool:
    """Record one case. Returns True on success.

    When ``hermetic`` is True the legacy engine runs under the
    deterministic LLM + tool patches (no API keys / network) so the golden
    is reproducible and matches how the parity gate runs candidates.
    """
    # Imports are local so the script can be inspected (--help) even
    # when the DB / Redis env is unset.
    import contextlib

    from src.common.database import AsyncSessionLocal

    from tests.parity.extract import extract_run_result
    from tests.parity.hermetic import hermetic_llm_and_tools, seed_parity_run
    from tests.parity.worker_sim import drive_run_to_completion
    from tests.regression.loader import load_case

    patch_ctx = hermetic_llm_and_tools() if hermetic else contextlib.nullcontext()

    case_path = REPO_ROOT / "backend" / "tests" / "regression" / "cases" / f"{case_id}.yaml"
    if not case_path.exists():
        logger.error("Case file not found: %s", case_path)
        return False

    case = load_case(case_path)

    import redis.asyncio as aioredis
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    redis_client = await aioredis.from_url(redis_url)

    async with AsyncSessionLocal() as db:
        # Seed company + entity + run via the SAME helper the parity tests
        # use, so the golden and the candidate run identical entity configs.
        run_id = await seed_parity_run(
            db,
            entity_fixture=case.entity_fixture,
            input_data=case.input,
            child_fixtures=case.child_fixtures,
        )
        logger.info("Seeded run %s for case %s", run_id, case_id)

    # Execute via the AgentLoop (the sole engine; C4 deleted execute_run),
    # driven through the in-process arq drainer so async child dispatch
    # suspends + resumes to completion. The drainer commits via its own
    # sessions, so extract on a fresh session below.
    logger.info("Executing AgentLoop via worker_sim drainer (hermetic=%s) ...", hermetic)
    try:
        with patch_ctx:
            await drive_run_to_completion(str(run_id))
    except Exception:
        logger.exception("Run raised — recording partial snapshot anyway")

    async with AsyncSessionLocal() as db:
        # Re-fetch + extract.
        rr = await extract_run_result(db, str(run_id))
        snapshot_path = output_dir / f"{case_id}.json"
        rr.save(snapshot_path)
        logger.info(
            "Saved golden snapshot: %s  (status=%s cost=$%.4f steps=%d)",
            snapshot_path, rr.status, rr.total_cost_usd, rr.step_count,
        )

    await redis_client.aclose()
    return True


async def _main(args: Any) -> int:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Hermetic mode: deterministic mock LLM + stubbed tools. Default ON when
    # no LLM key is present so goldens are reproducible in CI / dev. Force
    # with --hermetic, disable with --no-hermetic (real LLM calls).
    has_llm_key = any(
        os.environ.get(k)
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                  "GEMINI_API_KEY", "VERTEX_PROJECT")
    )
    if args.hermetic is None:
        hermetic = not has_llm_key
    else:
        hermetic = args.hermetic
    logger.info("Recording goldens (hermetic=%s, llm_key_present=%s)",
                hermetic, has_llm_key)

    if args.cases:
        case_ids = list(args.cases)
    else:
        # Default: every case YAML on disk.
        cases_dir = REPO_ROOT / "backend" / "tests" / "regression" / "cases"
        case_ids = [p.stem for p in sorted(cases_dir.glob("*.yaml"))]

    if not case_ids:
        logger.error("No cases to record.")
        return 1

    failures = 0
    for cid in case_ids:
        logger.info("=== Recording golden for %s ===", cid)
        ok = await _record_one(cid, output_dir, hermetic=hermetic)
        if not ok:
            failures += 1
    return 0 if failures == 0 else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "backend" / "tests" / "parity" / "goldens"),
        help="Directory to write <case_id>.json snapshots into.",
    )
    parser.add_argument(
        "--cases",
        nargs="*",
        default=None,
        help="Specific case ids to record. Default: every YAML under "
             "backend/tests/regression/cases/.",
    )
    parser.add_argument(
        "--hermetic",
        dest="hermetic",
        action="store_true",
        default=None,
        help="Force deterministic mock LLM + stubbed tools (no API keys). "
             "Auto-enabled when no LLM key is present.",
    )
    parser.add_argument(
        "--no-hermetic",
        dest="hermetic",
        action="store_false",
        help="Use the real LLM provider (requires keys + credits).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(_main(args)))
