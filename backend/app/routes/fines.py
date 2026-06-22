"""Module Gestion des amendes — Phase 1.

Provides CRUD endpoints for fleet fines (`/api/livre/fines`) with strict
tenant isolation and role-based access. All write operations append an entry
to the `audit_log` collection.

Phase 1 scope:
- Schema with all fields needed by future phases (auto-driver, OCR, scheduler)
  but UI exposes the essentials only.
- No OCR, no scheduler, no auto-driver detection — placeholders kept ready.

Status state machine (no transitions enforced yet — free text validation only):
    received → to_analyze → driver_to_identify → awaiting_driver
             ↘ disputed
             ↘ to_pay → paid → recharged → closed
             ↘ cancelled
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.fines_engine import identify_driver
from app.routes._helpers import now_iso

router = APIRouter(tags=["fines"])

# --- Domain constants ------------------------------------------------------
STATUSES = [
    "received", "to_analyze", "driver_to_identify", "awaiting_driver",
    "disputed", "to_pay", "paid", "recharged", "closed", "cancelled",
]
INFRACTION_TYPES = [
    "speeding", "parking", "red_light", "toll",
    "forbidden_zone", "phone", "seatbelt", "other",
]
PRIORITIES = ["low", "normal", "high", "urgent"]
ROLES_RW = ("admin", "manager")           # read + create + update
ROLES_DELETE = ("admin",)                  # delete-only by admin


# --- Pydantic models -------------------------------------------------------
class FineIn(BaseModel):
    # Informations générales
    ref_fine: Optional[str] = None
    authority: Optional[str] = None
    country: str = "CH"
    canton: Optional[str] = None
    city: Optional[str] = None
    received_at: Optional[str] = None      # ISO date
    infraction_at: Optional[str] = None    # ISO datetime (date+time)
    location: Optional[str] = None
    # Véhicule
    vehicle_id: Optional[str] = None
    vehicle_plate: Optional[str] = None
    group: Optional[str] = None
    # Conducteur
    driver_id: Optional[str] = None
    driver_name: Optional[str] = None
    driver_validated_manually: bool = False
    # Détails
    infraction_type: str = "other"
    infraction_details: Optional[str] = None
    # Financier
    amount: float = 0.0
    admin_fees: float = 0.0
    currency: str = "CHF"
    due_date: Optional[str] = None
    paid_at: Optional[str] = None
    # Suivi
    status: str = "received"
    priority: str = "normal"
    case_owner: Optional[str] = None
    internal_notes: Optional[str] = None


class FineUpdate(BaseModel):
    # Same as FineIn but everything optional and no enforced defaults
    ref_fine: Optional[str] = None
    authority: Optional[str] = None
    country: Optional[str] = None
    canton: Optional[str] = None
    city: Optional[str] = None
    received_at: Optional[str] = None
    infraction_at: Optional[str] = None
    location: Optional[str] = None
    vehicle_id: Optional[str] = None
    vehicle_plate: Optional[str] = None
    group: Optional[str] = None
    driver_id: Optional[str] = None
    driver_name: Optional[str] = None
    driver_validated_manually: Optional[bool] = None
    infraction_type: Optional[str] = None
    infraction_details: Optional[str] = None
    amount: Optional[float] = None
    admin_fees: Optional[float] = None
    currency: Optional[str] = None
    due_date: Optional[str] = None
    paid_at: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    case_owner: Optional[str] = None
    internal_notes: Optional[str] = None


# --- Helpers ---------------------------------------------------------------
async def _next_dossier_number(db) -> str:
    """Sequential per-year dossier number: AMD-2026-0001, AMD-2026-0002, ..."""
    year = datetime.now(timezone.utc).year
    prefix = f"AMD-{year}-"
    last = await db.fines.find_one(
        {"tenant_id": "default", "dossier_number": {"$regex": f"^{prefix}"}},
        {"_id": 0, "dossier_number": 1},
        sort=[("dossier_number", -1)],
    )
    if last and last.get("dossier_number"):
        try:
            n = int(last["dossier_number"].split("-")[-1]) + 1
        except (ValueError, IndexError):
            n = 1
    else:
        n = 1
    return f"{prefix}{n:04d}"


def _validate_enums(status: Optional[str], itype: Optional[str], priority: Optional[str]):
    if status and status not in STATUSES:
        raise HTTPException(400, f"Statut invalide. Valeurs: {STATUSES}")
    if itype and itype not in INFRACTION_TYPES:
        raise HTTPException(400, f"Type d'infraction invalide. Valeurs: {INFRACTION_TYPES}")
    if priority and priority not in PRIORITIES:
        raise HTTPException(400, f"Priorité invalide. Valeurs: {PRIORITIES}")


def _compute_total(fine: dict) -> float:
    return round(float(fine.get("amount") or 0) + float(fine.get("admin_fees") or 0), 2)


async def _audit(db, action: str, fine_id: str, actor: dict, diff: dict | None = None):
    await db.audit_log.insert_one({
        "ts": now_iso(), "scope": "fines", "action": action,
        "fine_id": fine_id, "actor": actor.get("email"),
        "diff": diff or {},
    })


# --- Endpoints -------------------------------------------------------------
@router.get("/fines/meta")
async def fines_meta(user=Depends(get_current_user)):
    """Static enums + lightweight vehicle/driver lists for form selects."""
    db = get_db()
    vehicles = await db.vehicles.find(
        {"tenant_id": "default"}, {"_id": 0, "id": 1, "plate": 1, "model": 1},
    ).sort("plate", 1).to_list(1000)
    drivers = await db.drivers.find(
        {"tenant_id": "default"}, {"_id": 0, "id": 1, "name": 1, "email": 1},
    ).sort("name", 1).to_list(1000)
    return {
        "statuses": STATUSES,
        "infraction_types": INFRACTION_TYPES,
        "priorities": PRIORITIES,
        "vehicles": vehicles,
        "drivers": drivers,
    }


@router.get("/fines")
async def list_fines(
    user=Depends(require_roles(*ROLES_RW)),
    status: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    infraction_type: Optional[str] = None,
    start: Optional[str] = None,   # filters infraction_at >= start
    end: Optional[str] = None,     # filters infraction_at <= end
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    q: Optional[str] = None,       # free-text search: dossier_number, ref_fine, location, plate
    sort: str = "-infraction_at",
    page: int = 1,
    page_size: int = 50,
):
    """List fines with filters, sort and pagination. Strict tenant isolation."""
    db = get_db()
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    query: dict = {"tenant_id": "default"}
    if status:
        query["status"] = status
    if vehicle_id:
        query["vehicle_id"] = vehicle_id
    if driver_id:
        query["driver_id"] = driver_id
    if infraction_type:
        query["infraction_type"] = infraction_type
    if start:
        query.setdefault("infraction_at", {})["$gte"] = start
    if end:
        query.setdefault("infraction_at", {})["$lte"] = end
    if min_amount is not None:
        query.setdefault("total_amount", {})["$gte"] = float(min_amount)
    if max_amount is not None:
        query.setdefault("total_amount", {})["$lte"] = float(max_amount)
    if q:
        rx = {"$regex": q, "$options": "i"}
        query["$or"] = [
            {"dossier_number": rx}, {"ref_fine": rx},
            {"location": rx}, {"vehicle_plate": rx}, {"driver_name": rx},
        ]

    # Sort: prefix "-" = desc, else asc
    sort_key = sort.lstrip("-") or "infraction_at"
    sort_dir = -1 if sort.startswith("-") else 1

    total = await db.fines.count_documents(query)
    rows = await db.fines.find(query, {"_id": 0}).sort(
        sort_key, sort_dir,
    ).skip((page - 1) * page_size).limit(page_size).to_list(page_size)

    # Sum totals across the filtered set (not just page)
    total_amount = 0.0
    paid_amount = 0.0
    open_amount = 0.0
    async for r in db.fines.find(query, {"_id": 0, "total_amount": 1, "status": 1}):
        amt = float(r.get("total_amount") or 0)
        total_amount += amt
        if r.get("status") == "paid":
            paid_amount += amt
        elif r.get("status") in ("to_pay", "to_analyze", "received", "disputed",
                                 "driver_to_identify", "awaiting_driver"):
            open_amount += amt

    return {
        "rows": rows,
        "page": page,
        "page_size": page_size,
        "total": total,
        "totals": {
            "total_amount": round(total_amount, 2),
            "paid_amount": round(paid_amount, 2),
            "open_amount": round(open_amount, 2),
        },
    }


@router.post("/fines")
async def create_fine(payload: FineIn, user=Depends(require_roles(*ROLES_RW))):
    """Create a new fine. Default status = `received`."""
    _validate_enums(payload.status, payload.infraction_type, payload.priority)
    db = get_db()

    # Resolve vehicle_plate from vehicle_id if not provided
    plate = payload.vehicle_plate
    if payload.vehicle_id and not plate:
        v = await db.vehicles.find_one({"id": payload.vehicle_id}, {"_id": 0, "plate": 1})
        plate = (v or {}).get("plate")

    # Resolve driver_name from driver_id if not provided
    dname = payload.driver_name
    if payload.driver_id and not dname:
        d = await db.drivers.find_one({"id": payload.driver_id}, {"_id": 0, "name": 1})
        dname = (d or {}).get("name")

    fine = payload.model_dump()
    fine.update({
        "id": str(uuid.uuid4()),
        "tenant_id": "default",
        "dossier_number": await _next_dossier_number(db),
        "vehicle_plate": plate,
        "driver_name": dname,
        "documents": [],
        "driver_confidence": None,
        "driver_sources": [],
        "created_at": now_iso(),
        "created_by": user.get("email"),
        "updated_at": now_iso(),
        "updated_by": user.get("email"),
    })
    fine["total_amount"] = _compute_total(fine)

    # Auto-identify driver if not specified at creation time (Phase 2)
    if not fine.get("driver_id") and fine.get("vehicle_id") and fine.get("infraction_at"):
        try:
            ident = await identify_driver(db, fine["vehicle_id"], fine["infraction_at"])
            if ident.get("driver_id"):
                fine["driver_id"] = ident["driver_id"]
                fine["driver_name"] = ident["driver_name"]
                fine["driver_confidence"] = ident["confidence"]
                fine["driver_sources"] = ident["sources"]
                fine["driver_validated_manually"] = False
            # Persist the GPS trip ref when any source matched a trip
            trip_ref = next((c for c in (ident.get("candidates") or []) if c.get("source") == "GPS"), None)
            if trip_ref and trip_ref.get("trip_id"):
                fine["gps_trip_id"] = trip_ref["trip_id"]
        except Exception as e:
            # Identification failure should NEVER block fine creation
            fine["auto_identify_error"] = str(e)[:200]

    await db.fines.insert_one(fine)
    fine.pop("_id", None)
    await _audit(db, "create", fine["id"], user, diff={"dossier": fine["dossier_number"]})
    return fine


@router.post("/fines/{fine_id}/identify-driver")
async def identify_driver_endpoint(fine_id: str, user=Depends(require_roles(*ROLES_RW))):
    """Recompute driver identification for an existing fine and persist the result.

    Returns the candidates so the UI can show every source considered.
    """
    db = get_db()
    fine = await db.fines.find_one({"id": fine_id, "tenant_id": "default"}, {"_id": 0})
    if not fine:
        raise HTTPException(404, "Amende introuvable")
    if not fine.get("vehicle_id") or not fine.get("infraction_at"):
        raise HTTPException(
            400,
            "Identification impossible : véhicule et date/heure d'infraction requis.",
        )
    ident = await identify_driver(db, fine["vehicle_id"], fine["infraction_at"])
    updates = {
        "driver_id": ident.get("driver_id"),
        "driver_name": ident.get("driver_name"),
        "driver_confidence": ident.get("confidence"),
        "driver_sources": ident.get("sources") or [],
        "driver_validated_manually": False,
        "updated_at": now_iso(),
        "updated_by": user.get("email"),
    }
    trip_ref = next((c for c in (ident.get("candidates") or []) if c.get("source") == "GPS"), None)
    if trip_ref and trip_ref.get("trip_id"):
        updates["gps_trip_id"] = trip_ref["trip_id"]
    await db.fines.update_one({"id": fine_id}, {"$set": updates})
    await _audit(db, "auto_identify", fine_id, user,
                 diff={"confidence": ident.get("confidence"), "sources": ident.get("sources")})
    return {
        "fine_id": fine_id,
        "result": ident,
    }


@router.get("/fines/{fine_id}/identify-candidates")
async def identify_candidates(fine_id: str, user=Depends(require_roles(*ROLES_RW))):
    """Read-only preview of all driver candidates (no persistence)."""
    db = get_db()
    fine = await db.fines.find_one({"id": fine_id, "tenant_id": "default"}, {"_id": 0})
    if not fine:
        raise HTTPException(404, "Amende introuvable")
    if not fine.get("vehicle_id") or not fine.get("infraction_at"):
        raise HTTPException(400, "Véhicule et date/heure d'infraction requis.")
    ident = await identify_driver(db, fine["vehicle_id"], fine["infraction_at"])
    return ident


@router.get("/fines/{fine_id}")
async def get_fine(fine_id: str, user=Depends(require_roles(*ROLES_RW))):
    db = get_db()
    fine = await db.fines.find_one({"id": fine_id, "tenant_id": "default"}, {"_id": 0})
    if not fine:
        raise HTTPException(404, "Amende introuvable")
    return fine


@router.patch("/fines/{fine_id}")
async def update_fine(fine_id: str, payload: FineUpdate, user=Depends(require_roles(*ROLES_RW))):
    db = get_db()
    existing = await db.fines.find_one({"id": fine_id, "tenant_id": "default"}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Amende introuvable")

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    _validate_enums(updates.get("status"), updates.get("infraction_type"), updates.get("priority"))

    # Refresh denormalized vehicle plate / driver name when ids change
    if "vehicle_id" in updates:
        v = await db.vehicles.find_one({"id": updates["vehicle_id"]}, {"_id": 0, "plate": 1})
        updates["vehicle_plate"] = (v or {}).get("plate") or updates.get("vehicle_plate")
    if "driver_id" in updates:
        d = await db.drivers.find_one({"id": updates["driver_id"]}, {"_id": 0, "name": 1})
        updates["driver_name"] = (d or {}).get("name") or updates.get("driver_name")
        # Manual driver assignment implies validation by a human operator
        if "driver_validated_manually" not in updates:
            updates["driver_validated_manually"] = True

    # Recompute total when financial fields change
    merged = {**existing, **updates}
    updates["total_amount"] = _compute_total(merged)

    # Auto-stamp paid_at when status moves to "paid" and no manual date provided
    if updates.get("status") == "paid" and not merged.get("paid_at"):
        updates["paid_at"] = now_iso()

    updates["updated_at"] = now_iso()
    updates["updated_by"] = user.get("email")

    await db.fines.update_one({"id": fine_id}, {"$set": updates})
    await _audit(db, "update", fine_id, user, diff=list(updates.keys()))
    fresh = await db.fines.find_one({"id": fine_id}, {"_id": 0})
    return fresh


@router.delete("/fines/{fine_id}")
async def delete_fine(fine_id: str, user=Depends(require_roles(*ROLES_DELETE))):
    db = get_db()
    existing = await db.fines.find_one({"id": fine_id, "tenant_id": "default"}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Amende introuvable")
    await db.fines.delete_one({"id": fine_id})
    await _audit(db, "delete", fine_id, user, diff={"dossier": existing.get("dossier_number")})
    return {"deleted": True, "id": fine_id}


@router.get("/fines/stats/summary")
async def fines_summary(user=Depends(require_roles(*ROLES_RW))):
    """High-level KPIs for the dashboard widget (Phase 3 wiring)."""
    db = get_db()
    base = {"tenant_id": "default"}
    by_status = {}
    for s in STATUSES:
        by_status[s] = await db.fines.count_documents({**base, "status": s})
    total = sum(by_status.values())

    pipeline = [
        {"$match": base},
        {"$group": {
            "_id": None,
            "total_amount": {"$sum": "$total_amount"},
            "paid_amount": {"$sum": {"$cond": [{"$eq": ["$status", "paid"]}, "$total_amount", 0]}},
        }},
    ]
    agg = await db.fines.aggregate(pipeline).to_list(1)
    sums = agg[0] if agg else {"total_amount": 0, "paid_amount": 0}
    return {
        "total": total,
        "by_status": by_status,
        "total_amount": round(float(sums.get("total_amount") or 0), 2),
        "paid_amount": round(float(sums.get("paid_amount") or 0), 2),
    }
