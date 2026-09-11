"""APP DRIVER V2 — Inspection VÉHICULE réelle, liée au Journal de bord.

Réutilise l'infrastructure existante (aucune 2e architecture, aucune 2e auth) :
- Stockage photos : app.object_storage (Emergent Object Storage).
- Multi-tenant : proxy get_db() (tenant_id du CONTEXTE serveur, jamais du client).
- Autorisation véhicule : app.vehicle_access.assert_vehicle_authorized (fail-closed).
- Audit : collection audit_log (scope 'vehicle_inspections').
- RBAC manager : app.auth.require_roles.

Collection Mongo : `vehicle_inspections` (tenant-scopée). Aucune nouvelle base.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.routes._helpers import resolve_driver_id_for_user
from app.vehicle_access import assert_vehicle_authorized
from app import ble_engine

router = APIRouter()

# Checklist de départ (extensible). Chaque item accepte OK|ANOMALIE|N/A.
CHECKLIST_ITEMS = (
    "pneus", "eclairage", "pare_brise", "carrosserie", "retroviseurs",
    "freins_temoins", "niveaux_liquides", "proprete", "equipements_obligatoires",
    "documents_vehicule", "autre",
)
ITEM_STATES = ("OK", "ANOMALIE", "N/A")
STATUS_IN_PROGRESS = "in_progress"
STATUS_VALIDATED = "validated"

PHOTO_MAX_BYTES = 20 * 1024 * 1024
PHOTO_MIME_WHITELIST = {
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "photo")
    base = re.sub(r"[^A-Za-z0-9._\-]+", "_", base)
    return base[:140] or "photo"


async def _audit(db, action: str, inspection_id: str, actor: dict, diff: dict | None = None):
    await db.audit_log.insert_one({
        "ts": _now(), "scope": "vehicle_inspections", "action": action,
        "inspection_id": inspection_id, "actor": actor.get("email"), "diff": diff or {},
    })


async def _require_driver(db, user) -> str:
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    return driver_id


async def _resolve_target_vehicle(db, driver_id: str, requested_vehicle_id: Optional[str]) -> str:
    """Véhicule cible : demandé (validé autorisé) OU véhicule de session. Fail-closed."""
    if requested_vehicle_id:
        try:
            await assert_vehicle_authorized(db, driver_id, requested_vehicle_id)
        except PermissionError as e:
            raise HTTPException(403, "Véhicule non autorisé pour ce chauffeur") from e
        return requested_vehicle_id
    sess = await ble_engine.get_current_session(db, driver_id)
    if sess and sess.get("vehicle_id"):
        return sess["vehicle_id"]
    raise HTTPException(409, "Aucun véhicule sélectionné")


def _public_photo(p: dict) -> dict:
    return {k: p.get(k) for k in ("id", "filename", "content_type", "size_bytes", "uploaded_at")}


def _public_inspection(doc: dict) -> dict:
    """DTO exposé : jamais les storage_path internes des photos."""
    checklist = []
    for it in (doc.get("checklist") or []):
        checklist.append({
            "item": it.get("item"),
            "state": it.get("state"),
            "comment": it.get("comment"),
            "photos": [_public_photo(p) for p in (it.get("photos") or [])],
        })
    return {
        "id": doc.get("id"),
        "tenant_id": doc.get("tenant_id"),
        "vehicle_id": doc.get("vehicle_id"),
        "driver_id": doc.get("driver_id"),
        "created_by": doc.get("created_by"),
        "status": doc.get("status"),
        "started_at": doc.get("started_at"),
        "validated_at": doc.get("validated_at"),
        "general_comment": doc.get("general_comment"),
        "vehicle_snapshot": doc.get("vehicle_snapshot"),
        "driver_snapshot": doc.get("driver_snapshot"),
        "checklist": checklist,
        "created_at": doc.get("created_at"),
    }


def _blank_checklist() -> list[dict]:
    return [{"item": it, "state": None, "comment": None, "photos": []} for it in CHECKLIST_ITEMS]


# ===========================================================================
# CRÉATION / REPRISE
# ===========================================================================
class NewInspectionIn(BaseModel):
    vehicle_id: Optional[str] = None


@router.post("/driver/inspections")
async def create_inspection(payload: NewInspectionIn, user=Depends(get_current_user)):
    """Nouvelle inspection (ou reprise de celle en cours) pour le véhicule sélectionné.
    Snapshot véhicule + chauffeur figé côté serveur. tenant/driver jamais du client."""
    db = get_db()
    driver_id = await _require_driver(db, user)
    vid = await _resolve_target_vehicle(db, driver_id, payload.vehicle_id)

    # Reprise : une seule inspection in_progress par (véhicule, chauffeur).
    existing = await db.vehicle_inspections.find_one(
        {"vehicle_id": vid, "driver_id": driver_id, "status": STATUS_IN_PROGRESS,
         "archived": {"$ne": True}}, {"_id": 0})
    if existing:
        return _public_inspection(existing)

    vehicle = await db.vehicles.find_one({"id": vid}, {"_id": 0, "plate": 1, "model": 1}) or {}
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0, "name": 1}) or {}
    insp_id = str(uuid.uuid4())
    doc = {
        "id": insp_id,
        "vehicle_id": vid,
        "driver_id": driver_id,
        "created_by": user.get("email"),
        "status": STATUS_IN_PROGRESS,
        "started_at": _now(),
        "validated_at": None,
        "general_comment": None,
        "vehicle_snapshot": {"plate": vehicle.get("plate"), "model": vehicle.get("model")},
        "driver_snapshot": {"name": driver.get("name")},
        "checklist": _blank_checklist(),
        "archived": False,
        "created_at": _now(),
    }
    await db.vehicle_inspections.insert_one(doc)  # tenant_id injecté par le proxy
    await _audit(db, "inspection.created", insp_id, user, diff={"vehicle_id": vid})
    return _public_inspection(doc)


async def _load_owned(db, driver_id: str, inspection_id: str, *, for_write: bool) -> dict:
    doc = await db.vehicle_inspections.find_one({"id": inspection_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Inspection introuvable")
    try:
        await assert_vehicle_authorized(db, driver_id, doc["vehicle_id"])
    except PermissionError as e:
        raise HTTPException(403, "Accès non autorisé") from e
    if doc.get("driver_id") != driver_id:
        # Le chauffeur ne modifie/consulte que SES inspections (défense en profondeur).
        raise HTTPException(403, "Accès non autorisé")
    if for_write and doc.get("status") == STATUS_VALIDATED:
        raise HTTPException(409, "Inspection validée — modification impossible")
    return doc


@router.get("/driver/inspections/current")
async def current_inspection(vehicle_id: Optional[str] = Query(None), user=Depends(get_current_user)):
    db = get_db()
    driver_id = await _require_driver(db, user)
    vid = await _resolve_target_vehicle(db, driver_id, vehicle_id)
    doc = await db.vehicle_inspections.find_one(
        {"vehicle_id": vid, "driver_id": driver_id, "status": STATUS_IN_PROGRESS,
         "archived": {"$ne": True}}, {"_id": 0})
    return {"vehicle_id": vid, "inspection": _public_inspection(doc) if doc else None}


# ===========================================================================
# CHECKLIST
# ===========================================================================
class ChecklistItemIn(BaseModel):
    item: str
    state: str
    comment: Optional[str] = None


class ChecklistIn(BaseModel):
    items: list[ChecklistItemIn]
    general_comment: Optional[str] = None


@router.put("/driver/inspections/{inspection_id}/checklist")
async def save_checklist(inspection_id: str, payload: ChecklistIn, user=Depends(get_current_user)):
    db = get_db()
    driver_id = await _require_driver(db, user)
    doc = await _load_owned(db, driver_id, inspection_id, for_write=True)

    # Fusionne les états fournis sur la checklist existante (préserve les photos déjà jointes).
    by_item = {it["item"]: it for it in (doc.get("checklist") or [])}
    for entry in payload.items:
        if entry.item not in CHECKLIST_ITEMS:
            raise HTTPException(400, f"Item inconnu : {entry.item}")
        if entry.state not in ITEM_STATES:
            raise HTTPException(400, f"État invalide : {entry.state}")
        cur = by_item.get(entry.item) or {"item": entry.item, "photos": []}
        cur["state"] = entry.state
        cur["comment"] = (entry.comment or "").strip() or None
        by_item[entry.item] = cur
    new_checklist = [by_item[it] for it in CHECKLIST_ITEMS if it in by_item]
    await db.vehicle_inspections.update_one(
        {"id": inspection_id},
        {"$set": {"checklist": new_checklist,
                  "general_comment": (payload.general_comment or "").strip() or None,
                  "updated_at": _now(), "updated_by": user.get("email")}})
    await _audit(db, "inspection.checklist_saved", inspection_id, user,
                 diff={"items": len(payload.items)})
    fresh = await db.vehicle_inspections.find_one({"id": inspection_id}, {"_id": 0})
    return _public_inspection(fresh)


# ===========================================================================
# PHOTOS (anomalies) — stockage object_storage, filename serveur
# ===========================================================================
@router.post("/driver/inspections/{inspection_id}/photos")
async def add_photo(inspection_id: str, item: str = Form(...), file: UploadFile = File(...),
                    user=Depends(get_current_user)):
    db = get_db()
    driver_id = await _require_driver(db, user)
    doc = await _load_owned(db, driver_id, inspection_id, for_write=True)
    if item not in CHECKLIST_ITEMS:
        raise HTTPException(400, f"Item inconnu : {item}")
    ctype = (file.content_type or "").lower()
    if ctype not in PHOTO_MIME_WHITELIST:
        raise HTTPException(400, f"Format photo non supporté : {file.content_type}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Fichier vide")
    if len(data) > PHOTO_MAX_BYTES:
        raise HTTPException(413, "Fichier trop volumineux (max 20 MB)")

    photo_id = str(uuid.uuid4())
    safe = _sanitize_filename(file.filename or "photo.jpg")
    from app.object_storage import put_object, APP_PREFIX
    try:
        stored = await put_object(
            f"{APP_PREFIX}/vehicle_inspections/{inspection_id}/{photo_id}_{safe}", data, ctype)
    except Exception as e:
        raise HTTPException(502, "Stockage de la photo indisponible — réessayez.") from e

    photo = {"id": photo_id, "filename": safe, "content_type": ctype,
             "size_bytes": len(data), "storage_path": stored["path"], "uploaded_at": _now()}
    # Ajoute la photo à l'item ciblé (crée l'entrée si absente).
    checklist = doc.get("checklist") or []
    found = False
    for it in checklist:
        if it.get("item") == item:
            it.setdefault("photos", []).append(photo)
            found = True
            break
    if not found:
        checklist.append({"item": item, "state": None, "comment": None, "photos": [photo]})
    await db.vehicle_inspections.update_one(
        {"id": inspection_id}, {"$set": {"checklist": checklist, "updated_at": _now(),
                                         "updated_by": user.get("email")}})
    await _audit(db, "inspection.photo_added", inspection_id, user,
                 diff={"item": item, "photo_id": photo_id})
    return _public_photo(photo)


@router.delete("/driver/inspections/{inspection_id}/photos/{photo_id}")
async def delete_photo(inspection_id: str, photo_id: str, user=Depends(get_current_user)):
    db = get_db()
    driver_id = await _require_driver(db, user)
    doc = await _load_owned(db, driver_id, inspection_id, for_write=True)
    checklist = doc.get("checklist") or []
    removed = False
    for it in checklist:
        photos = it.get("photos") or []
        new_photos = [p for p in photos if p.get("id") != photo_id]
        if len(new_photos) != len(photos):
            it["photos"] = new_photos
            removed = True
    if not removed:
        raise HTTPException(404, "Photo introuvable")
    await db.vehicle_inspections.update_one(
        {"id": inspection_id}, {"$set": {"checklist": checklist, "updated_at": _now(),
                                         "updated_by": user.get("email")}})
    await _audit(db, "inspection.photo_deleted", inspection_id, user, diff={"photo_id": photo_id})
    return {"deleted": True, "id": photo_id}


@router.get("/driver/inspections/{inspection_id}/photos/{photo_id}/download")
async def download_photo(inspection_id: str, photo_id: str, user=Depends(get_current_user)):
    db = get_db()
    doc = await db.vehicle_inspections.find_one({"id": inspection_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Inspection introuvable")
    role = user.get("role")
    if role in ("admin", "manager", "superadmin"):
        pass  # tenant garanti par le proxy get_db()
    else:
        driver_id = await _require_driver(db, user)
        try:
            await assert_vehicle_authorized(db, driver_id, doc["vehicle_id"])
        except PermissionError as e:
            raise HTTPException(403, "Accès non autorisé") from e
        if doc.get("driver_id") != driver_id:
            raise HTTPException(403, "Accès non autorisé")
    photo = next((p for it in (doc.get("checklist") or [])
                  for p in (it.get("photos") or []) if p.get("id") == photo_id), None)
    if not photo:
        raise HTTPException(404, "Photo introuvable")
    from app.object_storage import get_object
    got = await get_object(photo["storage_path"])
    if got is None:
        raise HTTPException(410, "La photo n'est plus disponible.")
    content, ct = got
    return Response(content=content, media_type=photo.get("content_type") or ct,
                    headers={"Content-Disposition": f'attachment; filename="{photo["filename"]}"'})


# ===========================================================================
# VALIDATION (immuable ensuite)
# ===========================================================================
@router.post("/driver/inspections/{inspection_id}/validate")
async def validate_inspection(inspection_id: str, user=Depends(get_current_user)):
    db = get_db()
    driver_id = await _require_driver(db, user)
    doc = await _load_owned(db, driver_id, inspection_id, for_write=True)
    # Chaque ANOMALIE doit avoir un commentaire (règle métier).
    for it in (doc.get("checklist") or []):
        if it.get("state") == "ANOMALIE" and not (it.get("comment") or "").strip():
            raise HTTPException(400, f"Anomalie sans commentaire : {it.get('item')}")
    await db.vehicle_inspections.update_one(
        {"id": inspection_id},
        {"$set": {"status": STATUS_VALIDATED, "validated_at": _now(),
                  "validated_by": user.get("email"), "updated_at": _now()}})
    await _audit(db, "inspection.validated", inspection_id, user)
    fresh = await db.vehicle_inspections.find_one({"id": inspection_id}, {"_id": 0})
    return _public_inspection(fresh)


# ===========================================================================
# HISTORIQUE / DÉTAIL (chauffeur)
# ===========================================================================
@router.get("/driver/inspections")
async def list_inspections(vehicle_id: Optional[str] = Query(None), user=Depends(get_current_user)):
    db = get_db()
    driver_id = await _require_driver(db, user)
    vid = await _resolve_target_vehicle(db, driver_id, vehicle_id)
    docs = await db.vehicle_inspections.find(
        {"vehicle_id": vid, "driver_id": driver_id, "archived": {"$ne": True}},
        {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"vehicle_id": vid, "inspections": [_public_inspection(d) for d in docs]}


@router.get("/driver/inspections/{inspection_id}")
async def get_inspection(inspection_id: str, user=Depends(get_current_user)):
    db = get_db()
    driver_id = await _require_driver(db, user)
    doc = await _load_owned(db, driver_id, inspection_id, for_write=False)
    return _public_inspection(doc)


# ===========================================================================
# GESTIONNAIRE (admin/manager) — historique par tenant (isolé, minimal)
# ===========================================================================
@router.get("/manager/inspections")
async def manager_list_inspections(
    vehicle_id: Optional[str] = Query(None),
    driver_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user=Depends(require_roles("admin", "manager")),
):
    """Historique des inspections du tenant (RBAC admin/manager). Tenant via proxy."""
    db = get_db()
    q: dict = {"archived": {"$ne": True}}
    if vehicle_id:
        q["vehicle_id"] = vehicle_id
    if driver_id:
        q["driver_id"] = driver_id
    if status in (STATUS_IN_PROGRESS, STATUS_VALIDATED):
        q["status"] = status
    docs = await db.vehicle_inspections.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"inspections": [_public_inspection(d) for d in docs]}
