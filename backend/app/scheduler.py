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
from apscheduler.triggers.cron import CronTrigger

from app.navixy_client import is_configured as navixy_configured
from app.navixy_sync import sync_navixy

logger = logging.getLogger(__name__)

JOB_ID = "navixy_sync_job"
PRIVACY_JOB_ID = "privacy_enforcement_job"
FUEL_FX_JOB_ID = "fuel_fx_job"
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
    """Job callback — pulls Navixy data for every active tenant."""
    from app.db import get_raw_db
    from app.tenant_context import set_current_tenant, reset_current_tenant
    db = get_raw_db()
    state = await get_state(db)
    started = datetime.now(timezone.utc).isoformat()
    tenants = await db.tenants.find(
        {"status": "active", "navixy_hash": {"$nin": [None, ""]}}, {"_id": 0},
    ).to_list(500)
    if not tenants:
        logger.warning("Auto-sync skipped: aucun tenant actif avec clé Navixy")
        return
    results = {}
    for t in tenants:
        token = set_current_tenant(t["id"])
        try:
            result = await sync_navixy(days=state.get("days", 7), force_reclassify=True)
            results[t["id"]] = result
            logger.info("Auto-sync tenant %s: %s", t["id"], result)
        except Exception as e:
            logger.exception("Auto-sync failed for tenant %s", t["id"])
            results[t["id"]] = {"error": str(e)}
        finally:
            reset_current_tenant(token)
        await db.tenants.update_one(
            {"id": t["id"]},
            {"$set": {"last_sync_at": started, "last_sync_result": results[t["id"]]}},
        )
    last_result = results.get("default") if list(results) == ["default"] else results
    await db.app_state.update_one(
        {"id": STATE_ID},
        {"$set": {"last_run": started, "last_result": last_result}},
    )


async def _run_privacy_enforcement():
    """Periodic job — enforces tracker privacy per tenant (schedule + settings)."""
    from app.db import get_db, get_raw_db
    from app.privacy_enforcer import enforce_all_vehicles
    from app.tenant_context import set_current_tenant, reset_current_tenant
    raw = get_raw_db()
    tenants = await raw.tenants.find({"status": "active"}, {"_id": 0, "id": 1}).to_list(500)
    for t in tenants:
        token = set_current_tenant(t["id"])
        try:
            result = await enforce_all_vehicles(get_db())
            logger.info("Privacy enforcement (%s): %s", t["id"], {k: result.get(k) for k in
                        ("enabled", "simulation", "executed", "sent_real", "simulated", "skipped", "errors")})
        except Exception:
            logger.exception("Privacy enforcement failed for tenant %s", t["id"])
        finally:
            reset_current_tenant(token)


async def _run_fuel_fx():
    """Job quotidien 16h20 Europe/Zurich — taux BCE + conversion des transactions en attente."""
    from app.db import get_raw_db
    from app.fuel_fx import sync_ecb_rates, convert_pending
    raw = get_raw_db()
    result = await sync_ecb_rates(raw)
    conv = await convert_pending(raw) if result.get("ok") else {"skipped": True}
    logger.info("Sync taux BCE: %s | conversions: %s", result, conv)


BEACON_JOB_ID = "beacon_poll"
SWEEP_JOB_ID = "session_sweep"


async def _run_beacon_poll():
    try:
        from app.driver_beacons import poll_all_tenants
        res = await poll_all_tenants()
        if any(v.get("processed") for v in res.values() if isinstance(v, dict)):
            logger.info("Beacon poll: %s", res)
    except Exception as e:
        logger.error("Beacon poll error: %s", e)


async def _run_session_sweep():
    try:
        from app.db import get_db, get_raw_db
        from app.ble_engine import sweep_sessions
        from app.tenant_context import reset_current_tenant, set_current_tenant
        raw = get_raw_db()
        async for t in raw.tenants.find({"status": "active"}, {"_id": 0, "id": 1}):
            token = set_current_tenant(t["id"])
            try:
                await sweep_sessions(get_db())
            finally:
                reset_current_tenant(token)
    except Exception as e:
        logger.error("Session sweep error: %s", e)


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
    if state.get("enabled"):
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
    # Taux BCE : publiés ~16h CET les jours ouvrés → job à 16h20 Europe/Zurich (lun-ven)
    _scheduler.add_job(
        _run_fuel_fx,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=20, timezone="Europe/Zurich"),
        id=FUEL_FX_JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
    )
    # Amorçage : si aucun taux en base, synchronisation immédiate en tâche de fond
    from app.db import get_raw_db
    if await get_raw_db().fuel_exchange_rates.count_documents({}) == 0:
        _scheduler.add_job(_run_fuel_fx, id="fuel_fx_seed",
                           next_run_time=datetime.now(timezone.utc))
    # Beacons chauffeurs (Navixy) toutes les 2 min + balayage des sessions toutes les 5 min
    _scheduler.add_job(
        _run_beacon_poll, IntervalTrigger(minutes=2),
        id=BEACON_JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
    )
    _scheduler.add_job(
        _run_session_sweep, IntervalTrigger(minutes=5),
        id=SWEEP_JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
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

    if enabled:
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
