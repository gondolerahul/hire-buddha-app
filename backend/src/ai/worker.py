"""
worker.py — Arq worker entrypoint.

This file is intentionally minimal. All execution logic lives in:
  - ai.core.execution_engine   (ExecutionEngine)
  - ai.core.arq_jobs           (job functions)
  - ai.core.prompt_utils        (parse_variables, build_sandwich_prompt, etc.)
  - ai.core.context_utils       (store_step_output, sanitize_context)
  - ai.core.exceptions          (UncertaintySignal, AgentError, etc.)
  - ai.step_executor            (StepExecutorService)

Only WorkerSettings and cron registration remain here because arq
requires them at module level for worker discovery.

Phase 10A restructuring: decomposed from 1,992 lines → ~80 lines.
"""
from arq.connections import RedisSettings
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

# Model imports needed by arq at module scope
from src.common.database import AsyncSessionLocal  # noqa: F401


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


class WorkerSettings:
    functions = [
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
    ]
    # Register CORTEX scheduled wake-up cron
    cron_jobs = [
        # Run every 5 minutes to check for scheduled tree resumptions
        # arq expects: cron(coroutine, minute=set, hour=set, ...)
    ]

    job_timeout = 7200  # 2-hour absolute ceiling; per-entity timeout via logic_gate config

    # Parse Redis URL from environment config
    @staticmethod
    def _parse_redis_url():
        from src.common.config import settings
        from urllib.parse import urlparse
        parsed = urlparse(settings.REDIS_URL or "redis://localhost:6379")
        return parsed.hostname or "localhost", parsed.port or 6379

    _host, _port = _parse_redis_url.__func__()
    redis_settings = RedisSettings(host=_host, port=_port)


try:
    from arq.cron import cron
    WorkerSettings.cron_jobs = [
        cron(cortex_resume_scheduled, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        # C: Auto-schedule dreaming every 6 hours
        cron(dreaming_cron_trigger, hour={0, 6, 12, 18}, minute={15}),
        # Weekly critic calibration (Sunday 03:15 UTC)
        cron(critic_calibration_job, weekday=6, hour=3, minute=15),
        # Weekly skill candidate scan (Sunday 04:30 UTC)
        cron(skill_promotion_scan, weekday=6, hour=4, minute=30),
        # Weekly Meta-Agent prompt-evolution candidates
        # (Monday 05:00 UTC; never auto-applies — HITL gate required).
        cron(meta_agent_prompt_evolution, weekday=0, hour=5, minute=0),
        # Hourly KPI rollup refresh (xx:07 to spread
        # load away from other top-of-hour crons).
        cron(kpi_rollup_refresh, minute={7}),
        # /9: Nightly cost-estimator baseline refresh from
        # telemetry (02:30 UTC — quiet hour, follows the daily aggregate).
        cron(cost_estimator_refresh, hour=2, minute=30),
    ]
except ImportError:
    pass  # arq.cron may not be available in all versions

