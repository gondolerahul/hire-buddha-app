"""
worker.py — Arq worker entrypoint.

This file is intentionally minimal. The job functions live in
``ai.core.arq_jobs`` (runs, documents, Dreaming, CORTEX, crons),
``ai.campaign_worker`` and ``mobile.reconciler``; a run itself is driven by
``ai.core.agent_loop.AgentLoop``.

Only the two worker settings classes and cron registration remain here
because arq requires them at module level for worker discovery:
``WorkerSettings`` consumes the default queue (top-level runs, documents,
campaigns, gateway events, crons), ``ChildWorkerSettings`` the child-run
queue and ``EventWorkerSettings`` the automation events (Phase 14 WS3). Every job and cron is
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
    resume_paused_run,
    resume_waiting_run,
    cortex_resume_scheduled,
    sweep_stuck_runs,
    critic_calibration_job,
    skill_promotion_scan,
    meta_agent_prompt_evolution,
    kpi_rollup_refresh,
)
from src.ai.campaign_worker import (
    execute_campaign_task,
    pause_campaign_task,
    stop_campaign_task,
)

from src.mobile.reconciler import mobile_housekeeping_job
from src.billing.jobs import billing_daily_credits, billing_subscription_reconciliation
from src.common.tenancy.provisioner import provision_tenant

# Model imports needed by arq at module scope
from src.common.database import AsyncSessionLocal  # noqa: F401
from src.common.config import settings
from src.common.job_queue import CHILD_RUN_QUEUE, EVENT_QUEUE, arq_redis_settings
from src.automation.retention import prune_event_history
from src.automation.worker import automation_sweep, release_parked, route_event
from src.connections.jobs import connection_refresh, prune_unrouted_events
from src.automation.pollers import run_pollers
from src.common.telemetry import setup_tracing, shutdown_tracing, traced_job
from src.common.worker_health import start_heartbeat, stop_heartbeat
from src.common.worker_metrics import serve_metrics
from arq.constants import default_queue_name


# ---------------------------------------------------------------------------
# Arq WorkerSettings
# ---------------------------------------------------------------------------

def _listen_for_flag_changes(ctx: dict) -> None:
    """Drop a changed feature flag from this worker's cache at once (GH-14), and
    in split mode a changed tenant directory row."""
    import asyncio

    from src.ai.core.feature_flags import listen_for_invalidations

    ctx["flag_listener"] = asyncio.create_task(listen_for_invalidations(settings.REDIS_URL))
    from src.common.tenancy.session import is_split
    if is_split():  # tenant directory changes (Phase 14 WS2)
        from src.common.tenancy.directory import listen_for_changes
        ctx["directory_listener"] = asyncio.create_task(listen_for_changes(settings.REDIS_URL))


async def startup(ctx: dict) -> None:
    setup_tracing("hirebuddha-worker")
    serve_metrics(settings.WORKER_METRICS_PORT, settings.WORKER_METRICS_ADDR)          # IN-20
    # Reported on /api/v1/health, so a dead worker is visible (SA-I4).
    start_heartbeat(ctx, default_queue_name)
    _listen_for_flag_changes(ctx)


async def child_startup(ctx: dict) -> None:
    setup_tracing("hirebuddha-child-worker")
    serve_metrics(settings.CHILD_WORKER_METRICS_PORT, settings.WORKER_METRICS_ADDR)    # IN-20
    start_heartbeat(ctx, CHILD_RUN_QUEUE)
    _listen_for_flag_changes(ctx)


async def event_startup(ctx: dict) -> None:
    setup_tracing("hirebuddha-event-worker")
    serve_metrics(settings.EVENT_WORKER_METRICS_PORT, settings.WORKER_METRICS_ADDR)
    start_heartbeat(ctx, EVENT_QUEUE)
    _listen_for_flag_changes(ctx)


async def shutdown(ctx: dict) -> None:
    for name in ("flag_listener", "directory_listener"):
        listener = ctx.pop(name, None)
        if listener is not None:
            listener.cancel()
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
        # A run parked on a HITL approval (GH-07).
        resume_paused_run,
        # A run parked on wait_for_event (Phase 14 WS3).
        resume_waiting_run,
        # Outcome-triggered Dreaming.
        dreaming_outcome_trigger,
        # Enqueued by dreaming_cron_trigger (must be registered to run).
        dreaming_worker,
        graph_maintenance_worker,
        # A new tenant's database and resources (Phase 14 WS2 2.8).
        provision_tenant,
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
        # Parents stuck WAITING_ON_CHILDREN: re-enqueue a lost resume, or fail
        # and settle a parent that waited past the timeout (AK-03). Runs parked
        # on an approval: re-enqueue a lost resume or deadline (GH-07).
        cron(traced_job(sweep_stuck_runs), minute={2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57}),
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
        # Mobile dialer: expire stale call attempts + reconcile unidentified AI legs.
        cron(traced_job(mobile_housekeeping_job), minute={1, 6, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56}),
        # Billing (BC-04): renew expired daily credits and reap abandoned
        # checkouts at midnight UTC; reconcile subscriptions with Razorpay.
        cron(traced_job(billing_daily_credits), hour={0}, minute={0}),
        cron(traced_job(billing_subscription_reconciliation), hour={1}, minute={30}),
    ]
except ImportError:
    pass  # arq.cron may not be available in all versions


class ChildWorkerSettings:
    """Child runs only (SA-07): ``python -m arq src.ai.worker.ChildWorkerSettings``.

    ChildEntityExecutor and CORTEX RECURSE enqueue child runs on
    ``CHILD_RUN_QUEUE``, so a fan-out waits for these slots instead of taking
    the ones top-level runs, documents and events need. ``max_jobs`` caps
    concurrent children across all parents; ``governance.max_concurrent_children``
    caps one parent's batch (AK-07). A parent is resumed
    — ``resume_parent_run`` — on the default queue. Same functions as the main
    worker, so anything enqueued here still runs; no crons.
    """
    queue_name = CHILD_RUN_QUEUE
    functions = WorkerSettings.functions
    max_jobs = settings.CHILD_WORKER_MAX_JOBS
    job_timeout = WorkerSettings.job_timeout
    redis_settings = WorkerSettings.redis_settings

    on_startup = child_startup
    on_shutdown = shutdown


class EventWorkerSettings:
    """Automation events only (Phase 14 WS3, tech spec §7.8):
    ``python -m arq src.ai.worker.EventWorkerSettings``.

    The router decides which triggers an event starts and creates their runs;
    the runs themselves go to the default queue. Its own queue and worker, so
    a burst of events (a busy webhook, a schedule catching up) never waits
    behind long runs, nor takes their slots. The automation sweep — the
    outbox relay, held events after a resume, queued firings — is its cron.
    """
    queue_name = EVENT_QUEUE
    functions = [traced_job(job) for job in (route_event, release_parked, automation_sweep, prune_event_history,
                                             connection_refresh, prune_unrouted_events, run_pollers)]
    max_jobs = settings.EVENT_WORKER_MAX_JOBS
    job_timeout = 600
    redis_settings = WorkerSettings.redis_settings

    on_startup = event_startup
    on_shutdown = shutdown


try:
    from arq.cron import cron
    EventWorkerSettings.cron_jobs = [
        cron(traced_job(automation_sweep), second={0, 30}),
        # Event history kept (D47): only businesses that set a limit lose anything.
        cron(traced_job(prune_event_history), hour={2}, minute={40}),
        # Connections (WS5): tokens refreshed before they expire; unrouted deliveries kept 7 days.
        cron(traced_job(connection_refresh), minute=set(range(3, 60, 10))),
        cron(traced_job(prune_unrouted_events), hour={3}, minute={10}),
        # Pollers (WS3 3.13): new mail on connected mailboxes, while a trigger listens.
        cron(traced_job(run_pollers), minute=set(range(0, 60, 2)), second={15}),
    ]
except ImportError:
    pass
