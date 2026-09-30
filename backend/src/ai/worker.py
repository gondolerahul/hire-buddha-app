"""
worker.py — Arq worker entrypoint.

This file is intentionally minimal. The job functions live in
``ai.core.arq_jobs`` (runs, documents, Dreaming, CORTEX, crons),
``ai.campaign_worker`` and ``mobile.reconciler``; a run itself is driven by
``ai.core.agent_loop.AgentLoop``.

Only WorkerSettings and cron registration remain here because arq
requires them at module level for worker discovery. Every job and cron is
registered through ``traced_job``, so each run is a span in the trace of
whatever queued it (SA-10).
"""
import logging
import warnings

# Suppress third-party DeprecationWarnings we can't fix (dependency-internal)
warnings.filterwarnings("ignore", message=".*Inheritance class AiohttpClientSession.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*datetime.datetime.utcnow.*", module="sqlalchemy")
warnings.filterwarnings("ignore", message=".*has been renamed to.*ddgs.*", category=RuntimeWarning)

logger = logging.getLogger(__name__)

# --- Arq job imports (used by WorkerSettings.functions) ---
from src.ai.core.arq_jobs import (
    run_execution_recursive,
    process_gateway_event,
    process_document,
    dreaming_worker,
    dreaming_cron_trigger,
    dreaming_outcome_trigger,
    graph_maintenance_worker,
    resume_execution,
    resume_parent_run,
    cortex_resume_scheduled,
    critic_calibration_job,
    skill_promotion_scan,
    meta_agent_prompt_evolution,
    kpi_rollup_refresh,
    cost_estimator_refresh,
)
from src.ai.campaign_worker import (
    execute_campaign_task,
    pause_campaign_task,
    stop_campaign_task,
)

from src.mobile.reconciler import mobile_housekeeping_job

# Model imports needed by arq at module scope
from src.common.database import AsyncSessionLocal  # noqa: F401
from src.common.job_queue import arq_redis_settings
from src.common.telemetry import setup_tracing, shutdown_tracing, traced_job
from src.common.worker_health import start_heartbeat, stop_heartbeat
from arq.constants import default_queue_name


# ---------------------------------------------------------------------------
# Arq WorkerSettings
# ---------------------------------------------------------------------------

# Intended dedicated queue for async child runs, so a fan-out PROCESS can't
# starve top-level runs (and vice-versa). NOT routed yet: enqueuing children
# here requires deploying a worker bound to this queue, otherwise children
# would never be consumed. Until that worker exists, child dispatch stays on
# the default queue and load is bounded by governance.max_concurrent_children
# (see ChildEntityExecutor). Wire this in the C4 chain alongside the deletion.
CHILD_RUN_QUEUE = "children"


async def startup(ctx: dict) -> None:
    setup_tracing("hirebuddha-worker")
    # Reported on /api/v1/health, so a dead worker is visible (SA-I4).
    start_heartbeat(ctx, default_queue_name)


async def shutdown(ctx: dict) -> None:
    await stop_heartbeat(ctx)
    shutdown_tracing()


class WorkerSettings:
    functions = [traced_job(job) for job in (
        run_execution_recursive,
        process_gateway_event,
        process_document,
        execute_campaign_task,
        pause_campaign_task,
        stop_campaign_task,
        resume_execution,
        resume_parent_run,
        # Outcome-triggered Dreaming.
        dreaming_outcome_trigger,
        # Enqueued by dreaming_cron_trigger (must be registered to run).
        dreaming_worker,
        graph_maintenance_worker,
    )]
    # Register CORTEX scheduled wake-up cron
    cron_jobs = [
        # Run every 5 minutes to check for scheduled tree resumptions
        # arq expects: cron(coroutine, minute=set, hour=set, ...)
    ]

    job_timeout = 7200  # 2-hour absolute ceiling; per-entity timeout via logic_gate config

    on_startup = startup
    on_shutdown = shutdown

    # All of REDIS_URL — password, TLS and database index included (SA-05).
    redis_settings = arq_redis_settings()


try:
    from arq.cron import cron
    WorkerSettings.cron_jobs = [
        cron(traced_job(cortex_resume_scheduled), minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        # C: Auto-schedule dreaming every 6 hours
        cron(traced_job(dreaming_cron_trigger), hour={0, 6, 12, 18}, minute={15}),
        # Daily semantic-graph maintenance: decay stale edges, prune the weakest.
        cron(traced_job(graph_maintenance_worker), hour={3}, minute={45}),
        # Weekly critic calibration (Sunday 03:15 UTC)
        cron(traced_job(critic_calibration_job), weekday=6, hour=3, minute=15),
        # Weekly skill candidate scan (Sunday 04:30 UTC)
        cron(traced_job(skill_promotion_scan), weekday=6, hour=4, minute=30),
        # Weekly Meta-Agent prompt-evolution candidates
        # (Monday 05:00 UTC; never auto-applies — HITL gate required).
        cron(traced_job(meta_agent_prompt_evolution), weekday=0, hour=5, minute=0),
        # Hourly KPI rollup refresh (xx:07 to spread
        # load away from other top-of-hour crons).
        cron(traced_job(kpi_rollup_refresh), minute={7}),
        # /9: Nightly cost-estimator baseline refresh from
        # telemetry (02:30 UTC — quiet hour, follows the daily aggregate).
        cron(traced_job(cost_estimator_refresh), hour=2, minute=30),
        # Mobile dialer: expire stale call attempts + reconcile unidentified AI legs.
        cron(traced_job(mobile_housekeeping_job), minute={1, 6, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56}),
    ]
except ImportError:
    pass  # arq.cron may not be available in all versions

