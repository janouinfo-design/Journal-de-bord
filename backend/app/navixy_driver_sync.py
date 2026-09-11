"""
Journal/Driver App -> Navixy current-driver synchronisation.

Source of truth:
    Journal driver session = business truth.
    Navixy employee assignment = projection of the current active driver.

Safety:
- strict tenant matching between driver and vehicle;
- explicit ENABLED + WRITE gates;
- no credential is ever logged or returned;
- stop only unassigns when Navixy still contains the expected driver;
- Navixy errors never need to corrupt the local driver session.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.integrations import get_integration_credential


class NavixyDriverSyncError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sync_enabled() -> bool:
    return os.getenv("NAVIXY_DRIVER_SYNC_ENABLED", "0").strip().lower() in (
        "1", "true", "yes", "on"
    )


def write_enabled() -> bool:
    return os.getenv("NAVIXY_DRIVER_SYNC_WRITE", "0").strip().lower() in (
        "1", "true", "yes", "on"
    )


def unassign_write_enabled() -> bool:
    return os.getenv(
        "NAVIXY_DRIVER_SYNC_UNASSIGN_WRITE", "0"
    ).strip().lower() in (
        "1", "true", "yes", "on"
    )


def _employee_id(current: Optional[dict]) -> Optional[int]:
    if not current:
        return None
    try:
        return int(current.get("id"))
    except (TypeError, ValueError):
        return None


async def _audit(db, action: str, **payload) -> None:
    await db.audit_log.insert_one({
        "ts": _now(),
        "scope": "navixy_driver_sync",
        "action": action,
        **payload,
    })


async def _set_session_sync(db, session_id: Optional[str], **fields) -> None:
    if not session_id:
        return
    await db.driver_sessions.update_one(
        {"id": session_id},
        {"$set": {
            **fields,
            "navixy_sync_updated_at": _now(),
        }},
    )


def _integration(tenant_id: str) -> tuple[str, str]:
    cred = get_integration_credential(tenant_id, "NAVIXY")
    if not cred or not cred.get("credential"):
        raise NavixyDriverSyncError(
            f"NAVIXY integration unavailable for tenant={tenant_id}"
        )

    base = (
        cred.get("api_url")
        or os.getenv("NAVIXY_API_URL")
        or "https://api.navixy.com/v2"
    ).rstrip("/")

    return base, cred["credential"]


async def _post(tenant_id: str, path: str, payload: dict) -> dict:
    base, credential = _integration(tenant_id)

    body = {"hash": credential, **payload}

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{base}/{path.lstrip('/')}",
            json=body,
        )

    response.raise_for_status()
    data = response.json() or {}

    if data.get("success") is not True:
        status = data.get("status") or {}
        code = status.get("code")
        description = status.get("description") or "unknown Navixy error"
        raise NavixyDriverSyncError(
            f"Navixy {path} failed code={code}: {description}"
        )

    return data


async def read_tracker_employee(
    tenant_id: str,
    tracker_id: int,
) -> Optional[dict]:
    data = await _post(
        tenant_id,
        "tracker/employee/read",
        {"tracker_id": int(tracker_id)},
    )
    current = data.get("current")
    return current if isinstance(current, dict) else None


async def read_employee(
    tenant_id: str,
    employee_id: int,
) -> Optional[dict]:
    data = await _post(
        tenant_id,
        "employee/read",
        {"employee_id": int(employee_id)},
    )
    value = data.get("value")
    return value if isinstance(value, dict) else None


async def assign_tracker_employee(
    tenant_id: str,
    tracker_id: int,
    employee_id: int,
) -> None:
    if not write_enabled():
        raise NavixyDriverSyncError("NAVIXY_DRIVER_SYNC_WRITE_DISABLED")

    await _post(
        tenant_id,
        "tracker/employee/assign",
        {
            "tracker_id": int(tracker_id),
            "new_employee_id": int(employee_id),
        },
    )


async def unassign_employee_from_tracker(
    tenant_id: str,
    tracker_id: int,
    employee_id: int,
) -> None:
    """
    Clear employee.tracker_id only after caller verified that this employee
    is still the current driver of this tracker.
    """
    if not unassign_write_enabled():
        raise NavixyDriverSyncError(
            "NAVIXY_DRIVER_SYNC_UNASSIGN_WRITE_DISABLED"
        )

    employee = await read_employee(tenant_id, employee_id)
    if not employee:
        raise NavixyDriverSyncError("NAVIXY_EMPLOYEE_NOT_FOUND")

    try:
        employee_tracker = (
            int(employee["tracker_id"])
            if employee.get("tracker_id") is not None
            else None
        )
    except (TypeError, ValueError):
        employee_tracker = None

    if employee_tracker != int(tracker_id):
        raise NavixyDriverSyncError(
            "NAVIXY_EMPLOYEE_TRACKER_CHANGED"
        )

    # Employee object returned by Navixy is used as the update object.
    # tracker_id=null is the documented representation of "no tracker assigned".
    updated = dict(employee)
    updated["tracker_id"] = None

    await _post(
        tenant_id,
        "employee/update",
        {"employee": updated},
    )


async def _resolve_entities(db, driver_id: str, vehicle_id: str) -> dict:
    driver = await db.drivers.find_one(
        {"id": driver_id},
        {"_id": 0},
    )
    vehicle = await db.vehicles.find_one(
        {"id": vehicle_id},
        {"_id": 0},
    )

    if not driver:
        raise NavixyDriverSyncError("DRIVER_NOT_FOUND")
    if not vehicle:
        raise NavixyDriverSyncError("VEHICLE_NOT_FOUND")

    driver_tenant = driver.get("tenant_id")
    vehicle_tenant = vehicle.get("tenant_id")

    if not driver_tenant or not vehicle_tenant:
        raise NavixyDriverSyncError("TENANT_MISSING")

    if driver_tenant != vehicle_tenant:
        raise NavixyDriverSyncError("CROSS_TENANT_REFUSED")

    employee_id = driver.get("navixy_employee_id")
    tracker_id = vehicle.get("navixy_tracker_id")

    if employee_id is None:
        raise NavixyDriverSyncError("NAVIXY_EMPLOYEE_ID_MISSING")
    if tracker_id is None:
        raise NavixyDriverSyncError("NAVIXY_TRACKER_ID_MISSING")

    return {
        "tenant_id": str(driver_tenant),
        "employee_id": int(employee_id),
        "tracker_id": int(tracker_id),
        "driver": driver,
        "vehicle": vehicle,
    }


async def sync_claim(
    db,
    driver_id: str,
    vehicle_id: str,
    *,
    session_id: Optional[str] = None,
    actor: Optional[str] = None,
) -> dict:
    """
    Project a confirmed Journal APP session into Navixy.

    Local driving state is never rolled back if Navixy is unavailable.
    """
    if not sync_enabled():
        return {"status": "disabled"}

    try:
        ctx = await _resolve_entities(db, driver_id, vehicle_id)
        tenant = ctx["tenant_id"]
        employee_id = ctx["employee_id"]
        tracker_id = ctx["tracker_id"]

        current = await read_tracker_employee(tenant, tracker_id)
        current_id = _employee_id(current)

        if current_id == employee_id:
            await _set_session_sync(
                db, session_id,
                navixy_sync_status="synced",
                navixy_employee_id=employee_id,
                navixy_tracker_id=tracker_id,
            )
            await _audit(
                db,
                "driver_assignment_noop",
                tenant_id=tenant,
                driver_id=driver_id,
                vehicle_id=vehicle_id,
                session_id=session_id,
                tracker_id=tracker_id,
                employee_id=employee_id,
                actor=actor,
                result="already_assigned",
            )
            return {
                "status": "synced",
                "result": "already_assigned",
                "tracker_id": tracker_id,
                "employee_id": employee_id,
            }

        if not write_enabled():
            await _set_session_sync(
                db, session_id,
                navixy_sync_status="dry_run",
                navixy_employee_id=employee_id,
                navixy_tracker_id=tracker_id,
            )
            await _audit(
                db,
                "driver_assignment_dry_run",
                tenant_id=tenant,
                driver_id=driver_id,
                vehicle_id=vehicle_id,
                session_id=session_id,
                tracker_id=tracker_id,
                previous_employee_id=current_id,
                employee_id=employee_id,
                actor=actor,
                result="write_disabled",
            )
            return {
                "status": "dry_run",
                "tracker_id": tracker_id,
                "previous_employee_id": current_id,
                "employee_id": employee_id,
            }

        await assign_tracker_employee(
            tenant,
            tracker_id,
            employee_id,
        )

        verified = await read_tracker_employee(tenant, tracker_id)
        verified_id = _employee_id(verified)

        if verified_id != employee_id:
            raise NavixyDriverSyncError(
                f"ASSIGN_VERIFY_FAILED expected={employee_id} actual={verified_id}"
            )

        await _set_session_sync(
            db, session_id,
            navixy_sync_status="synced",
            navixy_employee_id=employee_id,
            navixy_tracker_id=tracker_id,
            navixy_synced_at=_now(),
        )
        await _audit(
            db,
            "driver_assigned",
            tenant_id=tenant,
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            session_id=session_id,
            tracker_id=tracker_id,
            previous_employee_id=current_id,
            employee_id=employee_id,
            actor=actor,
            result="success",
        )

        return {
            "status": "synced",
            "result": "assigned",
            "tracker_id": tracker_id,
            "previous_employee_id": current_id,
            "employee_id": employee_id,
        }

    except Exception as exc:
        await _set_session_sync(
            db, session_id,
            navixy_sync_status="error",
            navixy_sync_error=type(exc).__name__,
        )
        await _audit(
            db,
            "driver_assignment_failed",
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            session_id=session_id,
            actor=actor,
            result="error",
            error_type=type(exc).__name__,
        )
        return {
            "status": "error",
            "error": type(exc).__name__,
        }


async def sync_stop(
    db,
    driver_id: str,
    vehicle_id: str,
    *,
    session_id: Optional[str] = None,
    actor: Optional[str] = None,
) -> dict:
    """
    Remove the Journal driver from Navixy ONLY if Navixy still says that the
    same employee is assigned to that tracker.
    """
    if not sync_enabled():
        return {"status": "disabled"}

    try:
        ctx = await _resolve_entities(db, driver_id, vehicle_id)
        tenant = ctx["tenant_id"]
        employee_id = ctx["employee_id"]
        tracker_id = ctx["tracker_id"]

        current = await read_tracker_employee(tenant, tracker_id)
        current_id = _employee_id(current)

        if current_id is None:
            await _audit(
                db,
                "driver_unassignment_noop",
                tenant_id=tenant,
                driver_id=driver_id,
                vehicle_id=vehicle_id,
                session_id=session_id,
                tracker_id=tracker_id,
                employee_id=employee_id,
                actor=actor,
                result="already_unassigned",
            )
            return {
                "status": "synced",
                "result": "already_unassigned",
            }

        # Anti-race / anti-overwrite:
        # never remove another driver assigned after our local session changed.
        if current_id != employee_id:
            await _audit(
                db,
                "driver_unassignment_skipped",
                tenant_id=tenant,
                driver_id=driver_id,
                vehicle_id=vehicle_id,
                session_id=session_id,
                tracker_id=tracker_id,
                employee_id=employee_id,
                current_employee_id=current_id,
                actor=actor,
                result="current_driver_changed",
            )
            return {
                "status": "skipped",
                "result": "current_driver_changed",
                "current_employee_id": current_id,
            }

        if not unassign_write_enabled():
            await _audit(
                db,
                "driver_unassignment_dry_run",
                tenant_id=tenant,
                driver_id=driver_id,
                vehicle_id=vehicle_id,
                session_id=session_id,
                tracker_id=tracker_id,
                employee_id=employee_id,
                actor=actor,
                result="write_disabled",
            )
            return {
                "status": "dry_run",
                "tracker_id": tracker_id,
                "employee_id": employee_id,
            }

        await unassign_employee_from_tracker(
            tenant,
            tracker_id,
            employee_id,
        )

        verified = await read_tracker_employee(tenant, tracker_id)
        verified_id = _employee_id(verified)

        if verified_id is not None:
            raise NavixyDriverSyncError(
                f"UNASSIGN_VERIFY_FAILED actual={verified_id}"
            )

        await _audit(
            db,
            "driver_unassigned",
            tenant_id=tenant,
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            session_id=session_id,
            tracker_id=tracker_id,
            employee_id=employee_id,
            actor=actor,
            result="success",
        )

        return {
            "status": "synced",
            "result": "unassigned",
            "tracker_id": tracker_id,
            "employee_id": employee_id,
        }

    except Exception as exc:
        await _audit(
            db,
            "driver_unassignment_failed",
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            session_id=session_id,
            actor=actor,
            result="error",
            error_type=type(exc).__name__,
        )
        return {
            "status": "error",
            "error": type(exc).__name__,
        }
