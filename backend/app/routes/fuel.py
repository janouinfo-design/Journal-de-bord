"""Module Carburant & Décomptes — Phase 1.

Cartes carburant (CRUD, affectations, documents), transactions (import CSV/XLSX,
saisie manuelle, anti-doublons), rapprochement automatique + manuel avec score
explicable, paramètres par tenant. RBAC contrôlé côté serveur, audit complet.
"""
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.audit import log_audit
from app.auth import get_current_user, require_roles
from app.db import get_db
from app.fuel_engine import (
    CARD_STATUSES, PRODUCT_TYPES, apply_match, card_fingerprint, dedup_key,
    get_fuel_settings, match_transaction,
)
from app.fuel_fx import FX_STATE_ID, compute_fx, convert_pending, sync_ecb_rates
from app.fuel_import import INTERNAL_FIELDS, guess_mapping, normalize_row, parse_file
from app.tenant_context import get_effective_tenant_id

router = APIRouter(prefix="/fuel", tags=["fuel"])

READ_ROLES = ("admin", "manager", "lecture_seule")
MATCH_ROLES = ("admin", "manager")

STORAGE_ROOT = Path(__file__).parent.parent.parent / "storage" / "fuel"
DOC_MIME_WHITELIST = {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/heic"}
DOC_MAX_BYTES = 20 * 1024 * 1024

ASSIGNMENT_TYPES = ("vehicle", "driver", "pool", "other")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tenant_or_400() -> str:
    tid = get_effective_tenant_id()
    if not tid:
        raise HTTPException(400, "Sélectionnez d'abord un client (en-tête X-Tenant-Id)")
    return tid


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "fichier")
    base = re.sub(r"[^A-Za-z0-9._\-]+", "_", base)
    return base[:140] or "fichier"


CARD_PUBLIC_PROJECTION = {"_id": 0, "fingerprint": 0}


# ============================================================
# CARTES CARBURANT
# ============================================================
class CardIn(BaseModel):
    provider: str
    provider_account: Optional[str] = None
    card_number: str                      # utilisé pour last4 + empreinte, JAMAIS stocké
    external_card_id: Optional[str] = None
    assignment_type: str = "vehicle"      # vehicle | driver | pool | other
    vehicle_id: Optional[str] = None
    driver_id: Optional[str] = None
    allowed_products: list[str] = []
    limit_per_tx: Optional[float] = None
    limit_daily: Optional[float] = None
    limit_monthly: Optional[float] = None
    allowed_countries: list[str] = []
    allowed_networks: list[str] = []
    activated_at: Optional[str] = None
    expires_at: Optional[str] = None
    notes: Optional[str] = None


class CardUpdate(BaseModel):
    provider: Optional[str] = None
    provider_account: Optional[str] = None
    external_card_id: Optional[str] = None
    assignment_type: Optional[str] = None
    allowed_products: Optional[list[str]] = None
    limit_per_tx: Optional[float] = None
    limit_daily: Optional[float] = None
    limit_monthly: Optional[float] = None
    allowed_countries: Optional[list[str]] = None
    allowed_networks: Optional[list[str]] = None
    activated_at: Optional[str] = None
    expires_at: Optional[str] = None
    notes: Optional[str] = None


class CardStatusIn(BaseModel):
    status: str
    reason: Optional[str] = None
    replaced_by: Optional[str] = None


class AssignmentIn(BaseModel):
    type: str                             # vehicle | driver | pool | other
    vehicle_id: Optional[str] = None
    driver_id: Optional[str] = None
    valid_from: Optional[str] = None
    reason: Optional[str] = None


@router.get("/cards")
async def list_cards(status: Optional[str] = None, user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    db = get_db()
    q = {"status": status} if status else {}
    cards = await db.fuel_cards.find(q, CARD_PUBLIC_PROJECTION).sort("created_at", -1).to_list(1000)
    assignments = await db.fuel_card_assignments.find({}, {"_id": 0}).to_list(5000)
    by_card = {}
    for a in assignments:
        if not a.get("valid_to"):
            by_card[a["card_id"]] = a
    vehicles = {v["id"]: v for v in await db.vehicles.find({}, {"_id": 0, "id": 1, "plate": 1}).to_list(1000)}
    drivers = {d["id"]: d for d in await db.drivers.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)}
    for c in cards:
        a = by_card.get(c["id"])
        c["current_assignment"] = None
        if a:
            c["current_assignment"] = {
                "type": a["type"],
                "vehicle_id": a.get("vehicle_id"),
                "vehicle_plate": vehicles.get(a.get("vehicle_id"), {}).get("plate"),
                "driver_id": a.get("driver_id"),
                "driver_name": drivers.get(a.get("driver_id"), {}).get("name"),
                "valid_from": a.get("valid_from"),
            }
    return cards


@router.post("/cards")
async def create_card(payload: CardIn, user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    if payload.assignment_type not in ASSIGNMENT_TYPES:
        raise HTTPException(400, f"Type d'affectation invalide. Valeurs: {list(ASSIGNMENT_TYPES)}")
    digits = re.sub(r"\D", "", payload.card_number)
    if len(digits) < 4:
        raise HTTPException(400, "Numéro de carte invalide (minimum 4 chiffres)")
    fp = card_fingerprint(payload.card_number)
    if await db.fuel_cards.find_one({"fingerprint": fp}, {"_id": 0, "id": 1}):
        raise HTTPException(409, "Cette carte existe déjà (même numéro)")
    for p in payload.allowed_products:
        if p not in PRODUCT_TYPES:
            raise HTTPException(400, f"Produit invalide: {p}. Valeurs: {list(PRODUCT_TYPES)}")
    now = _now()
    card = {
        "id": str(uuid.uuid4()),
        "provider": payload.provider.strip(),
        "provider_account": payload.provider_account,
        "last4": digits[-4:],
        "fingerprint": fp,
        "external_card_id": payload.external_card_id,
        "assignment_type": payload.assignment_type,
        "allowed_products": payload.allowed_products,
        "limit_per_tx": payload.limit_per_tx,
        "limit_daily": payload.limit_daily,
        "limit_monthly": payload.limit_monthly,
        "allowed_countries": [c.upper() for c in payload.allowed_countries],
        "allowed_networks": payload.allowed_networks,
        "activated_at": payload.activated_at,
        "expires_at": payload.expires_at,
        "status": "active",
        "replaced_by": None,
        "notes": payload.notes,
        "documents": [],
        "history": [{"at": now, "by": user["email"], "action": "create"}],
        "created_at": now, "created_by": user["email"], "updated_at": now,
    }
    await db.fuel_cards.insert_one(dict(card))
    if payload.vehicle_id or payload.driver_id:
        a_type = "driver" if payload.assignment_type == "driver" else "vehicle"
        await db.fuel_card_assignments.insert_one({
            "id": str(uuid.uuid4()), "card_id": card["id"], "type": a_type,
            "vehicle_id": payload.vehicle_id, "driver_id": payload.driver_id,
            "valid_from": payload.activated_at, "valid_to": None,
            "created_by": user["email"], "reason": "Affectation initiale"})
    await log_audit("fuel.card_create", user,
                    {"card_id": card["id"], "provider": card["provider"], "last4": card["last4"]})
    card.pop("fingerprint", None)
    card.pop("tenant_id", None)
    return card


@router.get("/cards/{card_id}")
async def get_card(card_id: str, user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    db = get_db()
    card = await db.fuel_cards.find_one({"id": card_id}, CARD_PUBLIC_PROJECTION)
    if not card:
        raise HTTPException(404, "Carte introuvable")
    card["assignments"] = await db.fuel_card_assignments.find(
        {"card_id": card_id}, {"_id": 0}).sort("valid_from", -1).to_list(100)
    return card


@router.patch("/cards/{card_id}")
async def update_card(card_id: str, payload: CardUpdate, user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    card = await db.fuel_cards.find_one({"id": card_id}, {"_id": 0})
    if not card:
        raise HTTPException(404, "Carte introuvable")
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    if not changes:
        return {"updated": False}
    if "assignment_type" in changes and changes["assignment_type"] not in ASSIGNMENT_TYPES:
        raise HTTPException(400, "Type d'affectation invalide")
    before = {k: card.get(k) for k in changes}
    now = _now()
    await db.fuel_cards.update_one(
        {"id": card_id},
        {"$set": {**changes, "updated_at": now},
         "$push": {"history": {"at": now, "by": user["email"], "action": "update",
                               "before": before, "after": changes}}})
    await log_audit("fuel.card_update", user,
                    {"card_id": card_id, "before": before, "after": changes})
    return {"updated": True}


@router.post("/cards/{card_id}/status")
async def set_card_status(card_id: str, payload: CardStatusIn, user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    if payload.status not in CARD_STATUSES:
        raise HTTPException(400, f"Statut invalide. Valeurs: {list(CARD_STATUSES)}")
    card = await db.fuel_cards.find_one({"id": card_id}, {"_id": 0, "status": 1})
    if not card:
        raise HTTPException(404, "Carte introuvable")
    now = _now()
    update = {"status": payload.status, "updated_at": now}
    if payload.status == "replaced" and payload.replaced_by:
        update["replaced_by"] = payload.replaced_by
    await db.fuel_cards.update_one(
        {"id": card_id},
        {"$set": update,
         "$push": {"history": {"at": now, "by": user["email"], "action": "status",
                               "before": card["status"], "after": payload.status,
                               "reason": payload.reason}}})
    await log_audit("fuel.card_status", user,
                    {"card_id": card_id, "before": card["status"], "after": payload.status,
                     "reason": payload.reason})
    return {"updated": True, "status": payload.status}


@router.post("/cards/{card_id}/assignments")
async def add_assignment(card_id: str, payload: AssignmentIn, user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    if payload.type not in ASSIGNMENT_TYPES:
        raise HTTPException(400, f"Type invalide. Valeurs: {list(ASSIGNMENT_TYPES)}")
    if not await db.fuel_cards.find_one({"id": card_id}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Carte introuvable")
    if payload.vehicle_id and not await db.vehicles.find_one({"id": payload.vehicle_id}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Véhicule introuvable")
    if payload.driver_id and not await db.drivers.find_one({"id": payload.driver_id}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Chauffeur introuvable")
    now = _now()
    valid_from = payload.valid_from or now
    # clôture des affectations ouvertes du même type (historisation)
    await db.fuel_card_assignments.update_many(
        {"card_id": card_id, "type": payload.type, "valid_to": None},
        {"$set": {"valid_to": valid_from, "closed_by": user["email"]}})
    a = {"id": str(uuid.uuid4()), "card_id": card_id, "type": payload.type,
         "vehicle_id": payload.vehicle_id, "driver_id": payload.driver_id,
         "valid_from": valid_from, "valid_to": None,
         "created_by": user["email"], "reason": payload.reason}
    await db.fuel_card_assignments.insert_one(dict(a))
    await log_audit("fuel.card_assignment", user,
                    {"card_id": card_id, "type": payload.type,
                     "vehicle_id": payload.vehicle_id, "driver_id": payload.driver_id,
                     "reason": payload.reason})
    a.pop("tenant_id", None)
    return a


@router.post("/cards/{card_id}/documents")
async def upload_card_document(card_id: str, file: UploadFile = File(...),
                               user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    if not await db.fuel_cards.find_one({"id": card_id}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Carte introuvable")
    return await _store_document(db, "fuel_cards", card_id, file, user, "fuel.card_document_upload")


@router.get("/cards/{card_id}/documents/{doc_id}/download")
async def download_card_document(card_id: str, doc_id: str, user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    db = get_db()
    card = await db.fuel_cards.find_one({"id": card_id}, {"_id": 0, "documents": 1})
    if not card:
        raise HTTPException(404, "Carte introuvable")
    return _serve_document("cards", card_id, card.get("documents") or [], doc_id)


# ============================================================
# TRANSACTIONS
# ============================================================
class ManualTxIn(BaseModel):
    card_id: Optional[str] = None
    tx_datetime: str
    station_name: Optional[str] = None
    station_address: Optional[str] = None
    country: Optional[str] = None
    station_lat: Optional[float] = None
    station_lng: Optional[float] = None
    product_type: Optional[str] = None
    quantity: Optional[float] = None
    unit: str = "L"
    unit_price: Optional[float] = None
    amount_total: float
    vat_amount: Optional[float] = None
    vat_rate: Optional[float] = None
    currency: str = "CHF"
    mileage: Optional[float] = None
    vehicle_id: Optional[str] = None
    driver_id: Optional[str] = None
    invoice_ref: Optional[str] = None
    comment: Optional[str] = None
    reason: str                                # motif obligatoire pour toute saisie manuelle
    force: bool = False                        # forcer malgré un doublon probable


def _tx_query(date_from, date_to, card_id, vehicle_id, driver_id, match_status, source, q, fx_status=None):
    query = {}
    if fx_status:
        query["fx_status"] = fx_status
    if date_from:
        query.setdefault("tx_datetime", {})["$gte"] = date_from
    if date_to:
        query.setdefault("tx_datetime", {})["$lte"] = date_to + ("T23:59:59" if len(date_to) == 10 else "")
    if card_id:
        query["card_id"] = card_id
    if vehicle_id:
        query["vehicle_id"] = vehicle_id
    if driver_id:
        query["driver_id"] = driver_id
    if match_status:
        query["match_status"] = match_status
    if source:
        query["source"] = source
    if q:
        query["station_name"] = {"$regex": re.escape(q), "$options": "i"}
    return query


async def _enrich_tx(db, items: list[dict]):
    vehicles = {v["id"]: v for v in await db.vehicles.find({}, {"_id": 0, "id": 1, "plate": 1}).to_list(1000)}
    drivers = {d["id"]: d for d in await db.drivers.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)}
    for t in items:
        t["vehicle_plate"] = vehicles.get(t.get("vehicle_id"), {}).get("plate")
        t["driver_name"] = drivers.get(t.get("driver_id"), {}).get("name")
    return items


@router.get("/transactions")
async def list_transactions(date_from: Optional[str] = None, date_to: Optional[str] = None,
                            card_id: Optional[str] = None, vehicle_id: Optional[str] = None,
                            driver_id: Optional[str] = None, match_status: Optional[str] = None,
                            source: Optional[str] = None, q: Optional[str] = None,
                            fx_status: Optional[str] = None,
                            page: int = 1, page_size: int = 50,
                            user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    db = get_db()
    page_size = min(max(page_size, 1), 200)
    query = _tx_query(date_from, date_to, card_id, vehicle_id, driver_id, match_status, source, q, fx_status)
    total = await db.fuel_transactions.count_documents(query)
    items = await db.fuel_transactions.find(query, {"_id": 0}) \
        .sort("tx_datetime", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    await _enrich_tx(db, items)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/my-transactions")
async def my_transactions(page: int = 1, page_size: int = 50, user=Depends(get_current_user)):
    """Chauffeur : uniquement ses propres transactions."""
    _tenant_or_400()
    if user.get("role") != "driver":
        raise HTTPException(403, "Réservé aux chauffeurs")
    if not user.get("driver_id"):
        return {"items": [], "total": 0, "page": 1, "page_size": page_size}
    db = get_db()
    page_size = min(max(page_size, 1), 200)
    q = {"driver_id": user["driver_id"]}
    total = await db.fuel_transactions.count_documents(q)
    items = await db.fuel_transactions.find(q, {"_id": 0}) \
        .sort("tx_datetime", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    await _enrich_tx(db, items)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/transactions/{tx_id}")
async def get_transaction(tx_id: str, user=Depends(get_current_user)):
    _tenant_or_400()
    db = get_db()
    tx = await db.fuel_transactions.find_one({"id": tx_id}, {"_id": 0})
    if not tx:
        raise HTTPException(404, "Transaction introuvable")
    role = user.get("role")
    if role == "driver" and tx.get("driver_id") != user.get("driver_id"):
        raise HTTPException(403, "Accès refusé")
    if role not in ("admin", "manager", "lecture_seule", "superadmin", "driver"):
        raise HTTPException(403, "Accès refusé")
    tx["match_detail"] = await db.fuel_transaction_matches.find_one(
        {"transaction_id": tx_id}, {"_id": 0, "history": 0})
    await _enrich_tx(db, [tx])
    if tx.get("match_detail") and tx["match_detail"].get("candidates"):
        vehicles = {v["id"]: v for v in await db.vehicles.find({}, {"_id": 0, "id": 1, "plate": 1}).to_list(1000)}
        for c in tx["match_detail"]["candidates"]:
            c["vehicle_plate"] = vehicles.get(c["vehicle_id"], {}).get("plate")
    return tx


@router.post("/transactions")
async def create_manual_transaction(payload: ManualTxIn, user=Depends(require_roles("admin"))):
    tid = _tenant_or_400()
    db = get_db()
    if not payload.reason.strip():
        raise HTTPException(400, "Motif obligatoire pour une saisie manuelle")
    card = None
    if payload.card_id:
        card = await db.fuel_cards.find_one({"id": payload.card_id}, {"_id": 0, "id": 1, "last4": 1, "provider": 1})
        if not card:
            raise HTTPException(404, "Carte introuvable")
    dk = dedup_key(tid, payload.card_id or "manual", payload.tx_datetime,
                   payload.station_name or "", payload.quantity, payload.amount_total, payload.currency)
    dup = await db.fuel_transactions.find_one({"dedup_key": dk}, {"_id": 0, "id": 1})
    if dup and not payload.force:
        raise HTTPException(409, "Doublon probable détecté (même carte, date, station, montant). "
                                 "Confirmez avec force=true si c'est bien une transaction distincte.")
    now = _now()
    fx = await compute_fx(db, payload.amount_total, payload.currency, payload.tx_datetime)
    tx = {
        "id": str(uuid.uuid4()),
        "external_transaction_id": None,
        "provider": (card or {}).get("provider") or "manuel",
        "card_id": payload.card_id,
        "card_last4": (card or {}).get("last4"),
        "tx_datetime": payload.tx_datetime,
        "accounting_date": None,
        "station_name": payload.station_name, "station_address": payload.station_address,
        "country": (payload.country or "").upper() or None,
        "station_lat": payload.station_lat, "station_lng": payload.station_lng,
        "product_type": payload.product_type,
        "quantity": payload.quantity, "unit": payload.unit,
        "unit_price": payload.unit_price,
        "amount_net": None, "vat_amount": payload.vat_amount, "vat_rate": payload.vat_rate,
        "amount_total": payload.amount_total, "currency": payload.currency.upper(),
        **fx,
        "mileage": payload.mileage,
        "vehicle_id": payload.vehicle_id, "driver_id": payload.driver_id, "trip_id": None,
        "classification": "unclassified",
        "match_status": "manual" if payload.vehicle_id else "unmatched",
        "match_score": None,
        "source": "manual", "invoice_ref": payload.invoice_ref,
        "documents": [], "comment": payload.comment,
        "manual_reason": payload.reason.strip(),
        "dedup_key": dk, "import_job_id": None,
        "created_at": now, "created_by": user["email"], "updated_at": now, "updated_by": user["email"],
    }
    await db.fuel_transactions.insert_one(dict(tx))
    if not payload.vehicle_id:
        await apply_match(db, tx)
    await log_audit("fuel.tx_manual_create", user,
                    {"transaction_id": tx["id"], "amount": payload.amount_total,
                     "currency": tx["currency"], "reason": payload.reason,
                     "forced_duplicate": bool(dup)})
    tx.pop("tenant_id", None)
    return await get_transaction(tx["id"], user)


class MatchPatchIn(BaseModel):
    vehicle_id: Optional[str] = None
    driver_id: Optional[str] = None
    trip_id: Optional[str] = None
    reason: str


@router.patch("/transactions/{tx_id}/match")
async def manual_match(tx_id: str, payload: MatchPatchIn, user=Depends(require_roles(*MATCH_ROLES))):
    _tenant_or_400()
    db = get_db()
    if not payload.reason.strip():
        raise HTTPException(400, "Motif obligatoire pour une attribution manuelle")
    tx = await db.fuel_transactions.find_one({"id": tx_id}, {"_id": 0})
    if not tx:
        raise HTTPException(404, "Transaction introuvable")
    if tx.get("locked"):
        raise HTTPException(409, "Transaction verrouillée par un décompte clôturé — "
                                 "rouvrez le décompte pour modifier le rapprochement")
    if payload.vehicle_id and not await db.vehicles.find_one({"id": payload.vehicle_id}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Véhicule introuvable")
    classification = "unclassified"
    if payload.trip_id:
        trip = await db.trips.find_one({"id": payload.trip_id}, {"_id": 0, "classification": 1})
        if not trip:
            raise HTTPException(404, "Trajet introuvable")
        classification = {"professional": "professional",
                          "personal": "personal"}.get(trip.get("classification"), "unclassified")
    before = {k: tx.get(k) for k in ("vehicle_id", "driver_id", "trip_id", "match_status")}
    now = _now()
    await db.fuel_transactions.update_one(
        {"id": tx_id},
        {"$set": {"vehicle_id": payload.vehicle_id, "driver_id": payload.driver_id,
                  "trip_id": payload.trip_id, "classification": classification,
                  "match_status": "manual", "updated_at": now, "updated_by": user["email"]}})
    await db.fuel_transaction_matches.update_one(
        {"transaction_id": tx_id},
        {"$set": {"transaction_id": tx_id, "status": "manual", "method": "manual",
                  "decided_by": user["email"], "decided_at": now, "reason": payload.reason},
         "$setOnInsert": {"id": str(uuid.uuid4())},
         "$push": {"history": {"at": now, "status": "manual", "by": user["email"],
                               "reason": payload.reason}}},
        upsert=True)
    await log_audit("fuel.match_manual", user,
                    {"transaction_id": tx_id, "before": before,
                     "after": {"vehicle_id": payload.vehicle_id, "driver_id": payload.driver_id,
                               "trip_id": payload.trip_id},
                     "reason": payload.reason})
    return {"updated": True, "match_status": "manual"}


class MatchRunIn(BaseModel):
    only_unmatched: bool = True
    date_from: Optional[str] = None


@router.post("/match/run")
async def run_matching(payload: MatchRunIn, user=Depends(require_roles(*MATCH_ROLES))):
    _tenant_or_400()
    db = get_db()
    q = {"match_status": {"$in": ["unmatched", "matched_review"]}} if payload.only_unmatched \
        else {"match_status": {"$ne": "manual"}}
    q["locked"] = {"$ne": True}
    if payload.date_from:
        q["tx_datetime"] = {"$gte": payload.date_from}
    txs = await db.fuel_transactions.find(q, {"_id": 0}).sort("tx_datetime", -1).to_list(2000)
    settings = await get_fuel_settings(db)
    counts = {"processed": 0, "auto_matched": 0, "matched_review": 0, "unmatched": 0}
    for tx in txs:
        result = await apply_match(db, tx, settings)
        counts["processed"] += 1
        counts[result["match_status"]] = counts.get(result["match_status"], 0) + 1
    await log_audit("fuel.match_run", user, counts)
    return counts


@router.post("/transactions/{tx_id}/documents")
async def upload_tx_document(tx_id: str, file: UploadFile = File(...),
                             user=Depends(get_current_user)):
    _tenant_or_400()
    db = get_db()
    tx = await db.fuel_transactions.find_one({"id": tx_id}, {"_id": 0, "id": 1, "driver_id": 1})
    if not tx:
        raise HTTPException(404, "Transaction introuvable")
    role = user.get("role")
    if role == "driver":
        if tx.get("driver_id") != user.get("driver_id"):
            raise HTTPException(403, "Vous ne pouvez joindre un justificatif qu'à vos propres transactions")
    elif role not in ("admin", "manager", "superadmin"):
        raise HTTPException(403, "Accès refusé")
    return await _store_document(db, "fuel_transactions", tx_id, file, user, "fuel.tx_document_upload")


@router.get("/transactions/{tx_id}/documents/{doc_id}/download")
async def download_tx_document(tx_id: str, doc_id: str, user=Depends(get_current_user)):
    _tenant_or_400()
    db = get_db()
    tx = await db.fuel_transactions.find_one({"id": tx_id}, {"_id": 0, "documents": 1, "driver_id": 1})
    if not tx:
        raise HTTPException(404, "Transaction introuvable")
    if user.get("role") == "driver" and tx.get("driver_id") != user.get("driver_id"):
        raise HTTPException(403, "Accès refusé")
    return _serve_document("transactions", tx_id, tx.get("documents") or [], doc_id)


class IssueIn(BaseModel):
    message: str


@router.post("/transactions/{tx_id}/report-issue")
async def report_tx_issue(tx_id: str, payload: IssueIn, user=Depends(get_current_user)):
    """Signaler une erreur sur une transaction (chauffeur : uniquement les siennes)."""
    _tenant_or_400()
    db = get_db()
    if not payload.message.strip():
        raise HTTPException(400, "Message obligatoire")
    tx = await db.fuel_transactions.find_one({"id": tx_id}, {"_id": 0, "id": 1, "driver_id": 1})
    if not tx:
        raise HTTPException(404, "Transaction introuvable")
    role = user.get("role")
    if role == "driver":
        if tx.get("driver_id") != user.get("driver_id"):
            raise HTTPException(403, "Vous ne pouvez signaler une erreur que sur vos propres transactions")
    elif role not in ("admin", "manager", "superadmin"):
        raise HTTPException(403, "Accès refusé")
    issue = {"id": str(uuid.uuid4()), "message": payload.message.strip(),
             "reported_by": user.get("email"), "reported_at": _now(), "status": "open"}
    await db.fuel_transactions.update_one(
        {"id": tx_id}, {"$push": {"issues": issue}, "$set": {"updated_at": _now()}})
    await log_audit("fuel.tx_issue_report", user,
                    {"transaction_id": tx_id, "issue_id": issue["id"], "message": issue["message"]})
    return issue


async def _store_document(db, coll_name: str, entity_id: str, file: UploadFile, user, audit_action: str):
    if (file.content_type or "").lower() not in DOC_MIME_WHITELIST:
        raise HTTPException(400, f"Format non supporté : {file.content_type}. Accepté : PDF, JPEG, PNG, WEBP, HEIC.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Fichier vide")
    if len(data) > DOC_MAX_BYTES:
        raise HTTPException(413, "Fichier trop volumineux (max 20 MB)")
    sub = "cards" if coll_name == "fuel_cards" else "transactions"
    doc_id = str(uuid.uuid4())
    safe_name = _sanitize_filename(file.filename or "fichier")
    d = STORAGE_ROOT / sub / entity_id
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{doc_id}_{safe_name}").write_bytes(data)
    meta = {"id": doc_id, "filename": safe_name, "content_type": file.content_type,
            "size_bytes": len(data), "uploaded_at": _now(), "uploaded_by": user.get("email")}
    await db[coll_name].update_one({"id": entity_id},
                                   {"$push": {"documents": meta}, "$set": {"updated_at": _now()}})
    await log_audit(audit_action, user, {"entity_id": entity_id, "doc_id": doc_id, "filename": safe_name})
    return meta


def _serve_document(sub: str, entity_id: str, documents: list, doc_id: str):
    doc = next((d for d in documents if d.get("id") == doc_id), None)
    if not doc:
        raise HTTPException(404, "Document introuvable")
    file_path = STORAGE_ROOT / sub / entity_id / f"{doc_id}_{doc['filename']}"
    if not file_path.exists():
        raise HTTPException(410, "Le fichier n'est plus disponible sur le serveur.")
    return FileResponse(path=str(file_path),
                        media_type=doc.get("content_type") or "application/octet-stream",
                        filename=doc["filename"])


# ============================================================
# IMPORTS CSV / XLSX
# ============================================================
@router.get("/import-fields")
async def import_fields(user=Depends(require_roles("admin"))):
    return INTERNAL_FIELDS


@router.post("/imports")
async def upload_import(file: UploadFile = File(...), provider: str = Form("Autre"),
                        user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    data = await file.read()
    if not data:
        raise HTTPException(400, "Fichier vide")
    if len(data) > 30 * 1024 * 1024:
        raise HTTPException(413, "Fichier trop volumineux (max 30 MB)")
    try:
        columns, rows = parse_file(data, file.filename or "")
    except ValueError as e:
        raise HTTPException(400, f"Fichier illisible : {e}")
    if not rows:
        raise HTTPException(400, "Aucune ligne de données trouvée")
    if len(rows) > 20000:
        raise HTTPException(413, "Trop de lignes (max 20 000 par fichier)")
    job = {"id": str(uuid.uuid4()), "provider": provider,
           "filename": _sanitize_filename(file.filename or "import"),
           "columns": columns, "mapping": None, "status": "mapping",
           "counts": {"total": len(rows)},
           "created_at": _now(), "created_by": user["email"]}
    await db.fuel_import_jobs.insert_one(dict(job))
    await db.fuel_import_rows.insert_many([
        {"id": str(uuid.uuid4()), "job_id": job["id"], "row_index": i,
         "raw": r, "normalized": None, "status": "pending", "errors": [],
         "imported": False, "transaction_id": None}
        for i, r in enumerate(rows)])
    # mapping sauvegardé pour ce fournisseur ?
    saved = await db.fuel_import_mappings.find_one(
        {"provider": provider}, {"_id": 0, "mapping": 1}, sort=[("created_at", -1)])
    guessed = (saved or {}).get("mapping") or guess_mapping(columns)
    await log_audit("fuel.import_upload", user,
                    {"job_id": job["id"], "filename": job["filename"], "rows": len(rows),
                     "provider": provider})
    job.pop("tenant_id", None)
    return {"job_id": job["id"], "columns": columns, "guessed_mapping": guessed,
            "sample": rows[:10], "total": len(rows), "fields": INTERNAL_FIELDS}


class MappingIn(BaseModel):
    mapping: dict          # {colonne_fichier: champ_interne | "ignore"}
    save_as_default: bool = False


async def _resolve_card(db, cards_cache: dict, normalized: dict):
    """Résout la carte par empreinte HMAC du numéro complet, sinon par last4 unique."""
    if normalized.get("card_number"):
        fp = card_fingerprint(normalized["card_number"])
        if fp in cards_cache["by_fp"]:
            return cards_cache["by_fp"][fp]
    last4 = normalized.get("card_last4")
    if last4:
        matches = cards_cache["by_last4"].get(last4, [])
        if len(matches) == 1:
            return matches[0]
    return None


async def _cards_cache(db):
    cards = await db.fuel_cards.find({}, {"_id": 0, "id": 1, "last4": 1, "fingerprint": 1,
                                          "provider": 1, "status": 1}).to_list(2000)
    by_fp, by_last4 = {}, {}
    for c in cards:
        if c.get("fingerprint"):
            by_fp[c["fingerprint"]] = c
        by_last4.setdefault(c.get("last4"), []).append(c)
    return {"by_fp": by_fp, "by_last4": by_last4}


@router.post("/imports/{job_id}/mapping")
async def apply_mapping(job_id: str, payload: MappingIn, user=Depends(require_roles("admin"))):
    tid = _tenant_or_400()
    db = get_db()
    job = await db.fuel_import_jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Import introuvable")
    if job["status"] == "confirmed":
        raise HTTPException(400, "Import déjà confirmé")
    mapped_fields = [f for f in payload.mapping.values() if f and f != "ignore"]
    if "tx_datetime" not in mapped_fields or "amount_total" not in mapped_fields:
        raise HTTPException(400, "Le mapping doit inclure au minimum « Date et heure » et « Montant TTC »")

    rows = await db.fuel_import_rows.find({"job_id": job_id}, {"_id": 0}).sort("row_index", 1).to_list(20000)
    cache = await _cards_cache(db)
    counts = {"total": len(rows), "ok": 0, "duplicate": 0, "unknown_card": 0,
              "invalid": 0, "amount_mismatch": 0}
    seen_keys = set()

    for r in rows:
        normalized, errors = normalize_row(r["raw"], payload.mapping)
        card = await _resolve_card(db, cache, normalized)
        normalized["card_id"] = card["id"] if card else None
        normalized.pop("card_number", None)   # jamais persisté
        status = "ok"
        hard_errors = [e for e in errors if "incohérent" not in e]
        mismatch = any("incohérent" in e for e in errors)
        if hard_errors:
            status = "invalid"
        else:
            dk = dedup_key(tid, normalized.get("card_id") or normalized.get("card_last4") or "?",
                           normalized.get("tx_datetime"), normalized.get("station_name") or "",
                           normalized.get("quantity"), normalized.get("amount_total"),
                           normalized.get("currency"))
            normalized["dedup_key"] = dk
            ext = normalized.get("external_transaction_id")
            dup = False
            if ext and await db.fuel_transactions.find_one(
                    {"provider": job["provider"], "external_transaction_id": ext}, {"_id": 0, "id": 1}):
                dup = True
            if not dup and await db.fuel_transactions.find_one({"dedup_key": dk}, {"_id": 0, "id": 1}):
                dup = True
            intra_key = ext or dk
            if intra_key in seen_keys:
                dup = True
            seen_keys.add(intra_key)
            if dup:
                status = "duplicate"
            elif not card:
                status = "unknown_card"
            elif mismatch:
                status = "amount_mismatch"
        counts[status] += 1
        await db.fuel_import_rows.update_one(
            {"id": r["id"]},
            {"$set": {"normalized": normalized, "status": status, "errors": errors}})

    await db.fuel_import_jobs.update_one(
        {"id": job_id}, {"$set": {"mapping": payload.mapping, "status": "preview", "counts": counts}})
    if payload.save_as_default:
        await db.fuel_import_mappings.insert_one({
            "id": str(uuid.uuid4()), "provider": job["provider"], "mapping": payload.mapping,
            "created_at": _now(), "created_by": user["email"]})
    return {"counts": counts}


@router.get("/imports/{job_id}/rows")
async def import_rows(job_id: str, status: Optional[str] = None, page: int = 1, page_size: int = 50,
                      user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    q = {"job_id": job_id}
    if status:
        q["status"] = status
    page_size = min(max(page_size, 1), 200)
    total = await db.fuel_import_rows.count_documents(q)
    rows = await db.fuel_import_rows.find(q, {"_id": 0, "raw": 0}) \
        .sort("row_index", 1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": rows, "total": total, "page": page}


async def _row_to_transaction(db, job, row, user, forced_reason=None):
    n = row["normalized"]
    now = _now()
    fx = await compute_fx(db, n["amount_total"], n.get("currency") or "CHF", n["tx_datetime"])
    card = await db.fuel_cards.find_one({"id": n.get("card_id")},
                                        {"_id": 0, "last4": 1}) if n.get("card_id") else None
    ext = n.get("external_transaction_id")
    forced_duplicate_of = None
    if forced_reason and ext and await db.fuel_transactions.find_one(
            {"provider": job["provider"], "external_transaction_id": ext}, {"_id": 0, "id": 1}):
        forced_duplicate_of = ext
        ext = f"{ext}#dup-{row['row_index']}"
    tx = {
        "id": str(uuid.uuid4()),
        "external_transaction_id": ext,
        "forced_duplicate_of": forced_duplicate_of,
        "provider": job["provider"],
        "card_id": n.get("card_id"),
        "card_last4": (card or {}).get("last4") or n.get("card_last4"),
        "tx_datetime": n["tx_datetime"], "accounting_date": n.get("accounting_date"),
        "station_name": n.get("station_name"), "station_address": n.get("station_address"),
        "country": n.get("country"),
        "station_lat": n.get("station_lat"), "station_lng": n.get("station_lng"),
        "product_type": n.get("product_type"),
        "quantity": n.get("quantity"), "unit": n.get("unit"),
        "unit_price": n.get("unit_price"),
        "amount_net": n.get("amount_net"), "vat_amount": n.get("vat_amount"),
        "vat_rate": n.get("vat_rate"),
        "amount_total": n["amount_total"], "currency": n.get("currency") or "CHF",
        **fx,
        "mileage": n.get("mileage"),
        "vehicle_hint": n.get("vehicle_hint"), "driver_hint": n.get("driver_hint"),
        "vehicle_id": None, "driver_id": None, "trip_id": None,
        "classification": "unclassified",
        "match_status": "unmatched", "match_score": None,
        "source": "xlsx" if job["filename"].lower().endswith((".xlsx", ".xls")) else "csv",
        "invoice_ref": n.get("invoice_ref"),
        "documents": [], "comment": n.get("comment"),
        "amount_check_warning": row["status"] == "amount_mismatch",
        "forced_import_reason": forced_reason,
        "dedup_key": n.get("dedup_key"),
        "import_job_id": job["id"],
        "created_at": now, "created_by": user["email"], "updated_at": now, "updated_by": user["email"],
    }
    await db.fuel_transactions.insert_one(dict(tx))
    await db.fuel_import_rows.update_one(
        {"id": row["id"]}, {"$set": {"imported": True, "transaction_id": tx["id"]}})
    return tx


@router.post("/imports/{job_id}/confirm")
async def confirm_import(job_id: str, user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    job = await db.fuel_import_jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Import introuvable")
    if job["status"] != "preview":
        raise HTTPException(400, "Appliquez d'abord le mapping (aperçu) avant de confirmer")
    rows = await db.fuel_import_rows.find(
        {"job_id": job_id, "status": {"$in": ["ok", "amount_mismatch", "unknown_card"]},
         "imported": False},
        {"_id": 0}).sort("row_index", 1).to_list(20000)
    settings = await get_fuel_settings(db)
    imported = 0
    match_counts = {"auto_matched": 0, "matched_review": 0, "unmatched": 0}
    for row in rows:
        tx = await _row_to_transaction(db, job, row, user)
        result = await apply_match(db, tx, settings)
        match_counts[result["match_status"]] = match_counts.get(result["match_status"], 0) + 1
        imported += 1
    await db.fuel_import_jobs.update_one(
        {"id": job_id}, {"$set": {"status": "confirmed", "confirmed_at": _now(),
                                  "imported_count": imported}})
    await log_audit("fuel.import_confirm", user,
                    {"job_id": job_id, "imported": imported, "match": match_counts,
                     "duplicates_kept_aside": job["counts"].get("duplicate", 0)})
    return {"imported": imported, "match": match_counts,
            "duplicates_in_review": job["counts"].get("duplicate", 0),
            "invalid_skipped": job["counts"].get("invalid", 0)}


class ForceRowIn(BaseModel):
    reason: str


@router.post("/imports/{job_id}/rows/{row_id}/force")
async def force_import_row(job_id: str, row_id: str, payload: ForceRowIn,
                           user=Depends(require_roles("admin"))):
    """Importe une ligne de la file de vérification (doublon probable) avec motif."""
    _tenant_or_400()
    db = get_db()
    if not payload.reason.strip():
        raise HTTPException(400, "Motif obligatoire")
    job = await db.fuel_import_jobs.find_one({"id": job_id}, {"_id": 0})
    row = await db.fuel_import_rows.find_one({"id": row_id, "job_id": job_id}, {"_id": 0})
    if not job or not row:
        raise HTTPException(404, "Ligne introuvable")
    if row["imported"]:
        raise HTTPException(400, "Ligne déjà importée")
    if row["status"] not in ("duplicate", "unknown_card", "amount_mismatch"):
        raise HTTPException(400, "Seules les lignes de la file de vérification peuvent être forcées")
    tx = await _row_to_transaction(db, job, row, user, forced_reason=payload.reason.strip())
    await apply_match(db, tx)
    await log_audit("fuel.import_force_row", user,
                    {"job_id": job_id, "row_id": row_id, "transaction_id": tx["id"],
                     "row_status": row["status"], "reason": payload.reason})
    return {"imported": True, "transaction_id": tx["id"]}


@router.get("/imports")
async def list_imports(user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    return await db.fuel_import_jobs.find({}, {"_id": 0, "columns": 0, "mapping": 0}) \
        .sort("created_at", -1).to_list(100)


# ============================================================
# PARAMÈTRES + VUE D'ENSEMBLE
# ============================================================
@router.get("/settings")
async def fuel_settings(user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    return await get_fuel_settings(get_db())


class FuelSettingsIn(BaseModel):
    station_radius_m: Optional[int] = None
    score_auto: Optional[int] = None
    score_review: Optional[int] = None
    time_window_min: Optional[int] = None
    allocation_mode: Optional[str] = None
    providers: Optional[list[str]] = None


@router.put("/settings")
async def update_fuel_settings(payload: FuelSettingsIn, user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        return await get_fuel_settings(db)
    if "allocation_mode" in changes and changes["allocation_mode"] not in ("A", "B"):
        raise HTTPException(400, "Mode de répartition invalide (A ou B)")
    if changes.get("score_auto") and changes.get("score_review") \
            and changes["score_review"] >= changes["score_auto"]:
        raise HTTPException(400, "Le seuil de contrôle doit être inférieur au seuil automatique")
    before = await get_fuel_settings(db)
    await db.settings.update_one({"id": "fuel"}, {"$set": changes,
                                                  "$setOnInsert": {"id": "fuel"}}, upsert=True)
    await log_audit("fuel.settings_update", user,
                    {"before": {k: before.get(k) for k in changes}, "after": changes})
    return await get_fuel_settings(db)


@router.get("/overview")
async def fuel_overview(date_from: Optional[str] = None, date_to: Optional[str] = None,
                        user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    db = get_db()
    q = _tx_query(date_from, date_to, None, None, None, None, None, None)
    txs = await db.fuel_transactions.find(
        q, {"_id": 0, "amount_total": 1, "currency": 1, "match_status": 1,
            "quantity": 1, "unit": 1, "classification": 1,
            "amount_chf": 1, "fx_status": 1}).to_list(20000)
    by_currency, by_status, qty = {}, {}, {"L": 0.0, "kWh": 0.0}
    by_class = {"professional": 0.0, "personal": 0.0, "unclassified": 0.0}
    chf_total, fx_pending = 0.0, 0
    for t in txs:
        cur = t.get("currency") or "CHF"
        by_currency[cur] = round(by_currency.get(cur, 0) + (t.get("amount_total") or 0), 2)
        if t.get("amount_chf") is not None:
            chf_total += t["amount_chf"]
        if t.get("fx_status") == "pending":
            fx_pending += 1
        st = t.get("match_status") or "unmatched"
        by_status[st] = by_status.get(st, 0) + 1
        if t.get("quantity") and t.get("unit") in qty:
            qty[t["unit"]] = round(qty[t["unit"]] + t["quantity"], 2)
        cl = t.get("classification") or "unclassified"
        by_class[cl if cl in by_class else "unclassified"] += t.get("amount_total") or 0
    cards = await db.fuel_cards.find({}, {"_id": 0, "status": 1}).to_list(2000)
    card_statuses = {}
    for c in cards:
        card_statuses[c["status"]] = card_statuses.get(c["status"], 0) + 1
    recent = await db.fuel_transactions.find(q, {"_id": 0}).sort("tx_datetime", -1).to_list(10)
    await _enrich_tx(db, recent)
    return {
        "transactions_count": len(txs),
        "amount_by_currency": by_currency,
        "amount_chf_total": round(chf_total, 2),
        "fx_pending": fx_pending,
        "match_statuses": by_status,
        "quantities": qty,
        "amount_by_classification": {k: round(v, 2) for k, v in by_class.items()},
        "cards_by_status": card_statuses,
        "recent": recent,
    }


# ============================================================
# TAUX DE CHANGE (BCE)
# ============================================================
@router.get("/fx/status")
async def fx_status(user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    db = get_db()
    state = await db.app_state.find_one({"id": FX_STATE_ID}, {"_id": 0}) or {}
    pending = await db.fuel_transactions.count_documents({"fx_status": "pending"})
    sample = []
    latest = state.get("latest_rate_date")
    if latest:
        sample = await db.fuel_exchange_rates.find(
            {"date": latest, "currency": {"$in": ["CHF", "USD", "GBP"]}},
            {"_id": 0, "currency": 1, "rate_per_eur": 1}).to_list(10)
    return {"last_success_at": state.get("last_success_at"),
            "last_attempt_at": state.get("last_attempt_at"),
            "last_error": state.get("last_error"),
            "latest_rate_date": latest,
            "pending_count": pending, "sample_rates": sample}


@router.get("/fx/rates")
async def fx_rates(date: Optional[str] = None, user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    db = get_db()
    d = (date or _now())[:10]
    latest = await db.fuel_exchange_rates.find_one(
        {"currency": "CHF", "date": {"$lte": d}}, {"_id": 0, "date": 1}, sort=[("date", -1)])
    if not latest:
        return {"requested_date": d, "effective_date": None, "rates": []}
    rows = await db.fuel_exchange_rates.find(
        {"date": latest["date"]}, {"_id": 0}).sort("currency", 1).to_list(100)
    return {"requested_date": d, "effective_date": latest["date"], "rates": rows}


@router.post("/fx/sync")
async def fx_sync(user=Depends(require_roles("admin"))):
    """Synchronisation manuelle BCE + conversion des transactions en attente."""
    _tenant_or_400()
    from app.db import get_raw_db
    raw = get_raw_db()
    result = await sync_ecb_rates(raw)
    if not result.get("ok"):
        raise HTTPException(502, f"Source BCE indisponible : {result.get('error')} — "
                                 "les taux existants sont conservés, réessayez plus tard.")
    conv = await convert_pending(raw)
    db = get_db()
    still_pending = await db.fuel_transactions.count_documents({"fx_status": "pending"})
    await log_audit("fuel.fx_sync", user,
                    {"upserted": result["upserted"], "latest_rate_date": result["latest_rate_date"],
                     "converted": conv["converted"], "still_pending_tenant": still_pending})
    return {**result, "converted": conv["converted"], "pending_in_tenant": still_pending}


# ============================================================
# DONNÉES DE RÉFÉRENCE (selects du frontend)
# ============================================================
@router.get("/refs")
async def fuel_refs(user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    db = get_db()
    vehicles = await db.vehicles.find({}, {"_id": 0, "id": 1, "plate": 1, "model": 1,
                                           "fuel_type": 1}).sort("plate", 1).to_list(1000)
    drivers = await db.drivers.find({"active": {"$ne": False}},
                                    {"_id": 0, "id": 1, "name": 1}).sort("name", 1).to_list(1000)
    cards = await db.fuel_cards.find({}, {"_id": 0, "id": 1, "provider": 1, "last4": 1,
                                          "status": 1}).to_list(1000)
    settings = await get_fuel_settings(db)
    return {"vehicles": vehicles, "drivers": drivers, "cards": cards,
            "providers": settings["providers"], "product_types": list(PRODUCT_TYPES)}
