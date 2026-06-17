"""Background scheduler for periodic Navixy sync.

State persisted in `db.app_state` (single doc id='scheduler'):
- enabled (bool)
- interval_min (int)
- days (int)
- last_run (ISO str)
- last_result (dict)
- next_run (ISO str)
"""
import os
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.navixy_client import is_configured as navixy_configured
from app.navixy_sync import sync_navixy

logger = logging.getLogger(__name__)

JOB_ID = "navixy_sync_job"
PRIVACY_JOB_ID = "privacy_enforcement_job"
PRIVACY_INTERVAL_MIN = int(os.environ.get("PRIVACY_ENFORCE_INTERVAL_MIN", "5"))
STATE_ID = "scheduler"

_scheduler: AsyncIOScheduler | None = None


def _default_state() -> dict:
    return {
        "id": STATE_ID,
        "enabled": os.environ.get("NAVIXY_AUTO_SYNC", "true").lower() == "true",
        "interval_min": int(os.environ.get("NAVIXY_SYNC_INTERVAL_MIN", "15")),
        "days": int(os.environ.get("NAVIXY_SYNC_DAYS", "7")),
        "last_run": None,
        "last_result": None,
        "next_run": None,
    }


async def get_state(db) -> dict:
    s = await db.app_state.find_one({"id": STATE_ID}, {"_id": 0})
    if not s:
        s = _default_state()
        await db.app_state.insert_one(dict(s))
        s.pop("_id", None)
    return s


async def _run_sync():
    """Job callback — pulls Navixy data."""
    from app.db import get_db
    db = get_db()
    if not navixy_configured():
        logger.warning("Auto-sync skipped: NAVIXY_HASH not configured")
        return
    state = await get_state(db)
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = await sync_navixy(days=state.get("days", 7), force_reclassify=True)
        await db.app_state.update_one(
            {"id": STATE_ID},
            {"$set": {"last_run": started, "last_result": result}},
        )
        logger.info("Auto-sync completed: %s", result)
    except Exception as e:
        logger.exception("Auto-sync failed")
        await db.app_state.update_one(
            {"id": STATE_ID},
            {"$set": {"last_run": started, "last_result": {"error": str(e)}}},
        )


async def _run_privacy_enforcement():
    """Periodic job — enforces tracker privacy per current schedule + settings."""
    from app.db import get_db
    from app.privacy_enforcer import enforce_all_vehicles
    db = get_db()
    try:
        result = await enforce_all_vehicles(db)
        logger.info("Privacy enforcement run: %s", {k: result.get(k) for k in
                    ("enabled", "simulation", "executed", "sent_real", "simulated", "skipped", "errors")})
    except Exception:
        logger.exception("Privacy enforcement failed")


async def _persist_next_run(db):
    if _scheduler is None:
        return
    job = _scheduler.get_job(JOB_ID)
    nr = job.next_run_time.isoformat() if job and job.next_run_time else None
    await db.app_state.update_one({"id": STATE_ID}, {"$set": {"next_run": nr}})


async def init_scheduler():
    """Called from server startup. Creates and starts the scheduler."""
    from app.db import get_db
    global _scheduler
    db = get_db()
    state = await get_state(db)

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.start()
    if state.get("enabled") and navixy_configured():
        _scheduler.add_job(
            _run_sync, IntervalTrigger(minutes=state.get("interval_min", 15)),
            id=JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
        )
    # Privacy enforcement runs unconditionally — the job itself checks the
    # settings.privacy_enforcement_enabled flag and short-circuits if off.
    _scheduler.add_job(
        _run_privacy_enforcement, IntervalTrigger(minutes=PRIVACY_INTERVAL_MIN),
        id=PRIVACY_JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
    )
    await _persist_next_run(db)
    logger.info("Scheduler initialised (enabled=%s, interval_min=%s)",
                state.get("enabled"), state.get("interval_min"))


async def reconfigure(enabled: bool, interval_min: int, days: int):
    """Apply runtime change: enable/disable + reschedule."""
    from app.db import get_db
    global _scheduler
    db = get_db()
    if interval_min < 1 or interval_min > 1440:
        raise ValueError("interval_min doit être entre 1 et 1440")
    if days < 1 or days > 365:
        raise ValueError("days doit être entre 1 et 365")

    await db.app_state.update_one(
        {"id": STATE_ID},
        {"$set": {"enabled": enabled, "interval_min": interval_min, "days": days}},
        upsert=True,
    )

    if _scheduler is None:
        return await get_state(db)

    # Remove existing job
    if _scheduler.get_job(JOB_ID):
        _scheduler.remove_job(JOB_ID)

    if enabled and navixy_configured():
        _scheduler.add_job(
            _run_sync, IntervalTrigger(minutes=interval_min),
            id=JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
        )
    await _persist_next_run(db)
    return await get_state(db)


def shutdown_scheduler():
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None


async def trigger_now():
    """Run sync immediately (returns the result)."""
    from app.db import get_db
    db = get_db()
    state = await get_state(db)
    result = await sync_navixy(days=state.get("days", 7), force_reclassify=True)
    await db.app_state.update_one(
        {"id": STATE_ID},
        {"$set": {"last_run": datetime.now(timezone.utc).isoformat(), "last_result": result}},
    )
    await _persist_next_run(db)
    return result
