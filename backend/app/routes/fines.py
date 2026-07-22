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

import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.fines_engine import identify_driver
from app.fines_exporter import export_csv, export_excel, export_pdf
from app.ocr_engine import extract_fine_from_document
from app.routes._helpers import now_iso, resolve_driver_id_for_user

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
# lecture_seule : accès GET uniquement (toute écriture est bloquée globalement dans get_current_user)
ROLES_RW = ("admin", "manager", "lecture_seule")  # read + create + update
ROLES_DELETE = ("admin",)                  # delete-only by admin

DOCUMENT_KINDS = ("pdf", "photo", "courrier", "contestation", "preuve_paiement", "libre")
DOCUMENT_MAX_BYTES = 20 * 1024 * 1024     # 20 MB hard cap per file
DOCUMENT_MIME_WHITELIST = {
    "application/pdf",
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif",
}
STORAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "storage" / "fines"
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)


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
@router.post("/fines/ocr-extract")
async def ocr_extract(
    file: UploadFile = File(...),
    user=Depends(require_roles(*ROLES_RW)),
):
    """Phase 5 — Run OCR on an uploaded fine document and return structured fields.

    Accepts a JPEG / PNG / WEBP image OR a PDF (first page is rendered).
    The endpoint is read-only — it does NOT create the fine. The frontend is
    expected to pre-fill the form and let the user review every field before
    saving (`POST /fines`).
    """
    import logging
    log = logging.getLogger(__name__)

    allowed = {"image/jpeg", "image/jpg", "image/png", "image/webp",
               "application/pdf"}
    if (file.content_type or "").lower() not in allowed:
        raise HTTPException(
            400, f"Format non supporté : {file.content_type}. Accepté : JPEG, PNG, WEBP, PDF.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(400, "Fichier vide")
    # Cap at 10 MB — large enough for any reasonable fine document
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Fichier trop volumineux (max 10 MB)")

    try:
        extracted = await extract_fine_from_document(
            data,
            file.content_type or "",
            session_id=f"ocr-{user.get('email')}-{uuid.uuid4().hex[:8]}",
        )
    except ValueError as e:
        raise HTTPException(400, f"Document invalide : {e}") from e
    except Exception as e:
        log.exception("OCR extraction failed")
        raise HTTPException(502, f"Échec de l'extraction OCR : {str(e)[:200]}") from e

    # Audit (no fine_id yet — it's a pre-create scan)
    db = get_db()
    await db.audit_log.insert_one({
        "ts": now_iso(), "scope": "fines", "action": "ocr_extract",
        "actor": user.get("email"),
        "diff": {
            "filename": file.filename,
            "content_type": file.content_type,
            "size_bytes": len(data),
            "extracted_keys": sorted(list((extracted or {}).keys())),
        },
    })

    return {
        "ok": True,
        "extracted": extracted or {},
        "model": "gemini-3.1-pro-preview",
    }


@router.get("/fines/mine")
async def list_my_fines(user=Depends(get_current_user)):
    """List fines belonging to the current driver — accessible to any authenticated user.

    The endpoint resolves the driver record linked to the user's email and returns
    only fines where `driver_id` matches. Read-only view; chauffeurs cannot edit /
    delete / create / export from this endpoint.
    """
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        # Allow admins/managers to call this gracefully; they just have no own fines
        return {"rows": [], "total": 0, "totals": {"total_amount": 0, "paid_amount": 0, "open_amount": 0}}

    rows = await db.fines.find(
        {"tenant_id": "default", "driver_id": driver_id},
        {"_id": 0, "internal_notes": 0},   # hide manager-private notes from chauffeurs
    ).sort("infraction_at", -1).to_list(1000)

    total_amount = sum(float(r.get("total_amount") or 0) for r in rows)
    paid_amount = sum(float(r.get("total_amount") or 0) for r in rows if r.get("status") == "paid")
    open_amount = sum(float(r.get("total_amount") or 0) for r in rows
                      if r.get("status") in ("to_pay", "to_analyze", "received", "disputed",
                                              "driver_to_identify", "awaiting_driver"))
    return {
        "rows": rows,
        "total": len(rows),
        "totals": {
            "total_amount": round(total_amount, 2),
            "paid_amount": round(paid_amount, 2),
            "open_amount": round(open_amount, 2),
        },
    }


@router.get("/fines/export")
async def export_fines(
    user=Depends(require_roles(*ROLES_RW)),
    fmt: str = Query("csv", pattern="^(csv|excel|pdf)$"),
    status: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    infraction_type: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    q: Optional[str] = None,
    sort: str = "-infraction_at",
):
    """Export the filtered list of fines as CSV, Excel or PDF.

    The filter parameters are kept in sync with `GET /fines` so an admin can
    "Export what I see" by reusing the URL filters.
    """
    db = get_db()
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

    sort_key = sort.lstrip("-") or "infraction_at"
    sort_dir = -1 if sort.startswith("-") else 1
    # No pagination on exports — they pull the full filtered set, capped at 10k for safety
    rows = await db.fines.find(query, {"_id": 0}).sort(sort_key, sort_dir).limit(10000).to_list(10000)
    from app.audit import log_audit
    await log_audit("fine.export", user, {"format": fmt, "count": len(rows)})

    # Aggregate totals for the PDF summary band
    totals = {"total_amount": 0.0, "paid_amount": 0.0, "open_amount": 0.0}
    for r in rows:
        amt = float(r.get("total_amount") or 0)
        totals["total_amount"] += amt
        if r.get("status") == "paid":
            totals["paid_amount"] += amt
        elif r.get("status") in ("to_pay", "to_analyze", "received", "disputed",
                                 "driver_to_identify", "awaiting_driver"):
            totals["open_amount"] += amt

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if fmt == "csv":
        data = export_csv(rows)
        media = "text/csv; charset=utf-8"
        ext = "csv"
    elif fmt == "excel":
        data = export_excel(rows)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    else:
        data = export_pdf(rows, totals=totals)
        media = "application/pdf"
        ext = "pdf"

    filename = f"logitrak_amendes_{ts}.{ext}"

    await db.audit_log.insert_one({
        "ts": now_iso(), "scope": "fines", "action": f"export_{fmt}",
        "actor": user.get("email"),
        "diff": {"count": len(rows), "filters_applied": bool(status or vehicle_id or driver_id
                                                              or infraction_type or start or end
                                                              or min_amount or max_amount or q)},
    })

    return StreamingResponse(
        io_iter(data), media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def io_iter(data: bytes):
    """Tiny generator so StreamingResponse can flush the bytes."""
    yield data


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


# --- Documents (Phase 3) ---------------------------------------------------
def _sanitize_filename(name: str) -> str:
    """Drop directory components + sanitize for safe filesystem use."""
    base = os.path.basename(name or "fichier")
    base = re.sub(r"[^A-Za-z0-9._\-]+", "_", base)
    return base[:140] or "fichier"


@router.post("/fines/{fine_id}/documents")
async def upload_document(
    fine_id: str,
    file: UploadFile = File(...),
    kind: str = Form("libre"),
    user=Depends(require_roles(*ROLES_RW)),
):
    """Attach a document (PDF or image) to a fine.

    Stored on disk under `/app/backend/storage/fines/{fine_id}/`. The metadata
    is appended to the `fines.documents` array. The actual file path is never
    exposed — clients fetch via the `download` endpoint.
    """
    if kind not in DOCUMENT_KINDS:
        raise HTTPException(400, f"Type invalide. Valeurs: {list(DOCUMENT_KINDS)}")
    if (file.content_type or "").lower() not in DOCUMENT_MIME_WHITELIST:
        raise HTTPException(
            400, f"Format non supporté : {file.content_type}. Accepté : PDF, JPEG, PNG, WEBP, HEIC.",
        )

    db = get_db()
    fine = await db.fines.find_one({"id": fine_id, "tenant_id": "default"}, {"_id": 0})
    if not fine:
        raise HTTPException(404, "Amende introuvable")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Fichier vide")
    if len(data) > DOCUMENT_MAX_BYTES:
        raise HTTPException(413, "Fichier trop volumineux (max 20 MB)")

    doc_id = str(uuid.uuid4())
    safe_name = _sanitize_filename(file.filename or "fichier")
    fine_dir = STORAGE_ROOT / fine_id
    fine_dir.mkdir(parents=True, exist_ok=True)
    file_path = fine_dir / f"{doc_id}_{safe_name}"
    file_path.write_bytes(data)

    doc_meta = {
        "id": doc_id,
        "kind": kind,
        "filename": safe_name,
        "content_type": file.content_type,
        "size_bytes": len(data),
        "uploaded_at": now_iso(),
        "uploaded_by": user.get("email"),
    }
    await db.fines.update_one(
        {"id": fine_id},
        {"$push": {"documents": doc_meta},
         "$set": {"updated_at": now_iso(), "updated_by": user.get("email")}},
    )
    await _audit(db, "upload_document", fine_id, user,
                 diff={"doc_id": doc_id, "kind": kind, "filename": safe_name,
                       "size": len(data)})
    return doc_meta


@router.get("/fines/{fine_id}/documents/{doc_id}/download")
async def download_document(
    fine_id: str, doc_id: str,
    user=Depends(require_roles(*ROLES_RW)),
):
    db = get_db()
    fine = await db.fines.find_one(
        {"id": fine_id, "tenant_id": "default"},
        {"_id": 0, "documents": 1},
    )
    if not fine:
        raise HTTPException(404, "Amende introuvable")
    docs = fine.get("documents") or []
    doc = next((d for d in docs if d.get("id") == doc_id), None)
    if not doc:
        raise HTTPException(404, "Document introuvable")

    fine_dir = STORAGE_ROOT / fine_id
    file_path = fine_dir / f"{doc_id}_{doc['filename']}"
    if not file_path.exists():
        raise HTTPException(410, "Le fichier n'est plus disponible sur le serveur.")
    return FileResponse(
        path=str(file_path),
        media_type=doc.get("content_type") or "application/octet-stream",
        filename=doc["filename"],
    )


@router.delete("/fines/{fine_id}/documents/{doc_id}")
async def delete_document(
    fine_id: str, doc_id: str,
    user=Depends(require_roles(*ROLES_RW)),
):
    db = get_db()
    fine = await db.fines.find_one(
        {"id": fine_id, "tenant_id": "default"},
        {"_id": 0, "documents": 1},
    )
    if not fine:
        raise HTTPException(404, "Amende introuvable")
    docs = fine.get("documents") or []
    doc = next((d for d in docs if d.get("id") == doc_id), None)
    if not doc:
        raise HTTPException(404, "Document introuvable")

    # Remove from disk first; if it fails the metadata stays so the user can retry
    file_path = STORAGE_ROOT / fine_id / f"{doc_id}_{doc['filename']}"
    try:
        if file_path.exists():
            file_path.unlink()
    except OSError as e:
        raise HTTPException(500, f"Suppression refusée : {e}") from e

    await db.fines.update_one(
        {"id": fine_id},
        {"$pull": {"documents": {"id": doc_id}},
         "$set": {"updated_at": now_iso(), "updated_by": user.get("email")}},
    )
    await _audit(db, "delete_document", fine_id, user,
                 diff={"doc_id": doc_id, "filename": doc.get("filename")})
    return {"deleted": True, "id": doc_id}


# --- Extended stats (Phase 3) ----------------------------------------------
@router.get("/fines/stats/extended")
async def fines_stats_extended(user=Depends(require_roles(*ROLES_RW))):
    """KPIs + top 10 rankings + 12-month evolution for the analytics page."""
    db = get_db()
    base = {"tenant_id": "default"}

    rows = await db.fines.find(base, {"_id": 0}).to_list(50000)

    total = len(rows)
    total_amount = sum(float(r.get("total_amount") or 0) for r in rows)
    paid_amount = sum(float(r.get("total_amount") or 0) for r in rows
                      if r.get("status") == "paid")
    pending_amount = sum(float(r.get("total_amount") or 0) for r in rows
                         if r.get("status") in ("to_pay", "to_analyze", "received",
                                                "disputed", "driver_to_identify",
                                                "awaiting_driver"))
    disputed = sum(1 for r in rows if r.get("status") == "disputed")

    # Overdue (due_date passed, not paid/cancelled/closed)
    now_utc = datetime.now(timezone.utc)
    overdue = 0
    for r in rows:
        if r.get("status") in ("paid", "recharged", "closed", "cancelled"):
            continue
        d = r.get("due_date")
        if not d:
            continue
        try:
            if datetime.fromisoformat(str(d).replace("Z", "+00:00")).replace(tzinfo=timezone.utc if "T" not in str(d) else None) < now_utc:
                overdue += 1
        except (ValueError, TypeError):
            pass

    # Buckets
    by_status: dict = {s: 0 for s in STATUSES}
    by_type: dict = {t: 0 for t in INFRACTION_TYPES}
    for r in rows:
        by_status[r.get("status") or "received"] = by_status.get(r.get("status") or "received", 0) + 1
        by_type[r.get("infraction_type") or "other"] = by_type.get(r.get("infraction_type") or "other", 0) + 1

    # Top 10 vehicles + drivers
    def _top10(key_field: str, label_field: str):
        agg: dict = {}
        for r in rows:
            k = r.get(key_field)
            if not k:
                continue
            bucket = agg.setdefault(k, {"key": k, "label": r.get(label_field) or k,
                                        "count": 0, "total": 0.0})
            bucket["count"] += 1
            bucket["total"] += float(r.get("total_amount") or 0)
        items = sorted(agg.values(), key=lambda x: -x["count"])[:10]
        for it in items:
            it["total"] = round(it["total"], 2)
        return items

    top_vehicles = _top10("vehicle_id", "vehicle_plate")
    top_drivers = _top10("driver_id", "driver_name")
    top_amounts = sorted(
        ({"key": r.get("id"),
          "label": r.get("dossier_number"),
          "vehicle": r.get("vehicle_plate"),
          "driver": r.get("driver_name"),
          "total": round(float(r.get("total_amount") or 0), 2),
          "status": r.get("status")} for r in rows),
        key=lambda x: -x["total"],
    )[:10]

    # 12-month evolution (count + amount)
    from collections import OrderedDict
    months = OrderedDict()
    for i in range(11, -1, -1):
        d = (now_utc.replace(day=1) - _months_delta(i))
        key = d.strftime("%Y-%m")
        months[key] = {"month": key, "count": 0, "amount": 0.0}
    for r in rows:
        inf = r.get("infraction_at")
        if not inf:
            continue
        try:
            d = datetime.fromisoformat(str(inf).replace("Z", "+00:00"))
            key = d.strftime("%Y-%m")
            if key in months:
                months[key]["count"] += 1
                months[key]["amount"] += float(r.get("total_amount") or 0)
        except (ValueError, TypeError):
            continue
    monthly = list(months.values())
    for m in monthly:
        m["amount"] = round(m["amount"], 2)

    return {
        "kpis": {
            "total": total,
            "total_amount": round(total_amount, 2),
            "paid_amount": round(paid_amount, 2),
            "pending_amount": round(pending_amount, 2),
            "disputed": disputed,
            "overdue": overdue,
        },
        "by_status": by_status,
        "by_type": by_type,
        "monthly": monthly,
        "top_vehicles": top_vehicles,
        "top_drivers": top_drivers,
        "top_amounts": top_amounts,
    }


def _months_delta(n: int):
    """Return a relativedelta of `n` months — kept inline to avoid the dateutil dep."""
    # Simplest workable approach: subtract n months by going through the date arith
    from datetime import timedelta
    return timedelta(days=30 * n)

