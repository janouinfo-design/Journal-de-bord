"""APP DRIVER V2 — Documents VÉHICULE réels, liés au Journal de bord.

Réutilise l'infrastructure existante (aucune 2e architecture) :
- Stockage : app.object_storage (Emergent Object Storage, soft-delete via Mongo).
- OCR : app.ocr_engine.extract_vehicle_document (MÊME moteur Gemini Vision).
- Multi-tenant : proxy get_db() (tenant_id du CONTEXTE serveur, jamais du client).
- Autorisation véhicule : app.vehicle_access.assert_vehicle_authorized (fail-closed).
- Audit : collection audit_log (scope 'vehicle_documents').

Collection Mongo : `vehicle_documents` (tenant-scopée). Aucune nouvelle base.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.auth import get_current_user
from app.db import get_db
from app.routes._helpers import resolve_driver_id_for_user
from app.vehicle_access import assert_vehicle_authorized
from app import ble_engine

router = APIRouter()

# --- Réutilisation des mêmes règles que les documents d'amende (cohérence) ---
DOCUMENT_TYPES = ("carte_grise", "assurance", "leasing", "controle_technique", "autre")
DOCUMENT_MAX_BYTES = 20 * 1024 * 1024  # 20 MB
DOCUMENT_MIME_WHITELIST = {
    "application/pdf",
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif",
}
STATUS_TO_PROCESS = "a_traiter"
STATUS_VALIDATED = "valide"
STATUS_EXPIRED = "expire"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "fichier")
    base = re.sub(r"[^A-Za-z0-9._\-]+", "_", base)
    return base[:140] or "fichier"


def _parse_date(s: Optional[str]) -> Optional[str]:
    """Valide une date ISO (YYYY-MM-DD). Retour normalisé ou None. Lève 400 si invalide."""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10]).isoformat()
    except ValueError as e:
        raise HTTPException(400, "Date invalide (format attendu YYYY-MM-DD)") from e


def _effective_status(doc: dict) -> str:
    """Statut effectif : 'expire' si expiry_date dépassée, sinon statut stocké."""
    exp = doc.get("expiry_date")
    if exp:
        try:
            if date.fromisoformat(str(exp)[:10]) < date.today():
                return STATUS_EXPIRED
        except ValueError:
            pass
    return doc.get("status") or STATUS_TO_PROCESS


async def _audit(db, action: str, doc_id: str, actor: dict, diff: dict | None = None):
    await db.audit_log.insert_one({
        "ts": _now(), "scope": "vehicle_documents", "action": action,
        "document_id": doc_id, "actor": actor.get("email"), "diff": diff or {},
    })


async def _resolve_target_vehicle(db, driver_id: str, requested_vehicle_id: Optional[str]) -> str:
    """Véhicule cible : celui demandé (validé autorisé) OU le véhicule de session courant.
    JAMAIS un vehicle_id arbitraire d'un autre tenant/hors périmètre (fail-closed)."""
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


def _public_doc(doc: dict) -> dict:
    """DTO exposé : jamais le storage_path interne."""
    return {
        "id": doc.get("id"),
        "tenant_id": doc.get("tenant_id"),
        "vehicle_id": doc.get("vehicle_id"),
        "driver_id": doc.get("driver_id"),
        "type": doc.get("type"),
        "filename": doc.get("filename"),
        "content_type": doc.get("content_type"),
        "size_bytes": doc.get("size_bytes"),
        "status": _effective_status(doc),
        "document_date": doc.get("document_date"),
        "expiry_date": doc.get("expiry_date"),
        "ocr_extracted": doc.get("ocr_extracted"),
        "created_at": doc.get("created_at"),
        "created_by": doc.get("created_by"),
    }


@router.get("/driver/vehicle-documents")
async def list_vehicle_documents(vehicle_id: Optional[str] = Query(None),
                                 user=Depends(get_current_user)):
    """Liste des documents du véhicule (par défaut : véhicule de session).
    Tenant issu du contexte serveur ; chauffeur autorisé sur le véhicule uniquement."""
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    vid = await _resolve_target_vehicle(db, driver_id, vehicle_id)
    docs = await db.vehicle_documents.find(
        {"vehicle_id": vid, "archived": {"$ne": True}}, {"_id": 0},
    ).sort("created_at", -1).to_list(500)
    return {"vehicle_id": vid, "documents": [_public_doc(d) for d in docs]}


@router.post("/driver/vehicle-documents")
async def upload_vehicle_document(
    file: UploadFile = File(...),
    type: str = Form("autre"),
    vehicle_id: Optional[str] = Form(None),
    document_date: Optional[str] = Form(None),
    expiry_date: Optional[str] = Form(None),
    user=Depends(get_current_user),
):
    """Ajoute un document au véhicule sélectionné. Sécurité 100% serveur.
    Pipeline : Mobile -> Journal API -> Object Storage -> OCR existant (best-effort)."""
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")

    if type not in DOCUMENT_TYPES:
        raise HTTPException(400, f"Type invalide. Valeurs: {list(DOCUMENT_TYPES)}")
    ctype = (file.content_type or "").lower()
    if ctype not in DOCUMENT_MIME_WHITELIST:
        raise HTTPException(400, f"Format non supporté : {file.content_type}. Accepté : PDF, JPEG, PNG, WEBP, HEIC.")

    # Véhicule cible figé À LA CRÉATION (autorisé + du tenant), jamais modifié ensuite.
    vid = await _resolve_target_vehicle(db, driver_id, vehicle_id)
    doc_date = _parse_date(document_date)
    exp_date = _parse_date(expiry_date)

    data = await file.read()
    if not data:
        raise HTTPException(400, "Fichier vide")
    if len(data) > DOCUMENT_MAX_BYTES:
        raise HTTPException(413, "Fichier trop volumineux (max 20 MB)")

    doc_id = str(uuid.uuid4())
    safe_name = _sanitize_filename(file.filename or "document")
    from app.object_storage import put_object, APP_PREFIX
    try:
        stored = await put_object(
            f"{APP_PREFIX}/vehicle_documents/{vid}/{doc_id}_{safe_name}", data,
            ctype or "application/octet-stream")
    except Exception as e:
        raise HTTPException(502, "Stockage du fichier indisponible — réessayez.") from e

    doc = {
        "id": doc_id,
        "vehicle_id": vid,
        "driver_id": driver_id,
        "type": type,
        "filename": safe_name,
        "content_type": ctype,
        "size_bytes": len(data),
        "storage_path": stored["path"],
        "status": STATUS_TO_PROCESS,
        "document_date": doc_date,
        "expiry_date": exp_date,
        "ocr_extracted": None,
        "archived": False,
        "created_at": _now(),
        "created_by": user.get("email"),
    }
    await db.vehicle_documents.insert_one(doc)  # tenant_id injecté par le proxy
    await _audit(db, "vehicle_document.created", doc_id, user,
                 diff={"vehicle_id": vid, "type": type, "filename": safe_name, "size": len(data)})
    await _audit(db, "vehicle_document.file_added", doc_id, user, diff={"filename": safe_name})

    # OCR best-effort — MÊME moteur existant. Échec => status inchangé, ocr_extracted=null (jamais inventé).
    try:
        from app.ocr_engine import extract_vehicle_document
        extracted = await extract_vehicle_document(data, ctype, session_id=f"vehdoc-{doc_id}")
        if extracted:
            patch = {"ocr_extracted": extracted}
            # Ne remplit une date que si absente ET fournie par l'OCR (jamais d'écrasement).
            if not doc_date and extracted.get("document_date"):
                patch["document_date"] = _parse_date(extracted.get("document_date"))
            if not exp_date and extracted.get("expiry_date"):
                patch["expiry_date"] = _parse_date(extracted.get("expiry_date"))
            await db.vehicle_documents.update_one({"id": doc_id}, {"$set": patch})
            doc.update(patch)
            await _audit(db, "vehicle_document.ocr", doc_id, user, diff={"ok": True})
    except Exception:
        await _audit(db, "vehicle_document.ocr", doc_id, user, diff={"ok": False})

    return _public_doc(doc)


@router.get("/driver/vehicle-documents/{doc_id}/download")
async def download_vehicle_document(doc_id: str, user=Depends(get_current_user)):
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    doc = await db.vehicle_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document introuvable")
    # Autorisation : le document doit appartenir à un véhicule autorisé pour ce chauffeur.
    try:
        await assert_vehicle_authorized(db, driver_id, doc["vehicle_id"])
    except PermissionError as e:
        raise HTTPException(403, "Accès non autorisé") from e
    from app.object_storage import get_object
    got = await get_object(doc["storage_path"])
    if got is None:
        raise HTTPException(410, "Le fichier n'est plus disponible.")
    content, ct = got
    return Response(
        content=content,
        media_type=doc.get("content_type") or ct,
        headers={"Content-Disposition": f'attachment; filename="{doc["filename"]}"'},
    )


@router.post("/driver/vehicle-documents/{doc_id}/validate")
async def validate_vehicle_document(doc_id: str, user=Depends(get_current_user)):
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    doc = await db.vehicle_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document introuvable")
    try:
        await assert_vehicle_authorized(db, driver_id, doc["vehicle_id"])
    except PermissionError as e:
        raise HTTPException(403, "Accès non autorisé") from e
    await db.vehicle_documents.update_one(
        {"id": doc_id}, {"$set": {"status": STATUS_VALIDATED,
                                  "updated_at": _now(), "updated_by": user.get("email")}})
    await _audit(db, "vehicle_document.validated", doc_id, user)
    fresh = await db.vehicle_documents.find_one({"id": doc_id}, {"_id": 0})
    return _public_doc(fresh)


@router.delete("/driver/vehicle-documents/{doc_id}")
async def archive_vehicle_document(doc_id: str, user=Depends(get_current_user)):
    """Soft-delete (archive) — le fichier physique n'est jamais purgé ici."""
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    doc = await db.vehicle_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document introuvable")
    try:
        await assert_vehicle_authorized(db, driver_id, doc["vehicle_id"])
    except PermissionError as e:
        raise HTTPException(403, "Accès non autorisé") from e
    await db.vehicle_documents.update_one(
        {"id": doc_id}, {"$set": {"archived": True, "updated_at": _now(),
                                  "updated_by": user.get("email")}})
    await _audit(db, "vehicle_document.archived", doc_id, user)
    return {"archived": True, "id": doc_id}
