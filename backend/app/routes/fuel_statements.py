"""Routes Décomptes & Clôtures carburant — /api/livre/fuel/statements.

Création/contrôle/clôture/réouverture : Admin uniquement (RBAC serveur).
Consultation + exports : admin, manager, lecture_seule. Audit complet.
"""
import calendar
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.audit import log_audit
from app.auth import require_roles
from app.db import get_db
from app.fuel_statements import (
    build_lines, closed_overlap, compute_totals, get_lines, late_transactions,
    next_statement_number, persist_lines, refresh_statement,
)
from app.fuel_statements_exporter import build_csv, build_excel, build_pdf
from app.tenant_context import get_effective_tenant_id, get_tenant_doc

router = APIRouter(prefix="/fuel/statements", tags=["fuel-statements"])

READ_ROLES = ("admin", "manager", "lecture_seule")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tenant_or_400() -> str:
    tid = get_effective_tenant_id()
    if not tid:
        raise HTTPException(400, "Sélectionnez d'abord un client (en-tête X-Tenant-Id)")
    return tid


class StatementCreateIn(BaseModel):
    period_month: Optional[str] = None      # "YYYY-MM" (défaut : période mensuelle)
    date_from: Optional[str] = None         # "YYYY-MM-DD" (période personnalisée)
    date_to: Optional[str] = None
    type: str = "regular"                   # regular | corrective
    include_carried_over: bool = True


def _resolve_period(payload: StatementCreateIn) -> tuple[str, str]:
    if payload.period_month:
        try:
            y, m = payload.period_month.split("-")
            y, m = int(y), int(m)
            last = calendar.monthrange(y, m)[1]
            return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last:02d}"
        except (ValueError, IndexError):
            raise HTTPException(400, "Mois invalide (format attendu : AAAA-MM)")
    if payload.date_from and payload.date_to:
        if payload.date_to < payload.date_from:
            raise HTTPException(400, "La date de fin doit être postérieure à la date de début")
        return payload.date_from[:10], payload.date_to[:10]
    raise HTTPException(400, "Indiquez un mois (period_month) ou une période (date_from + date_to)")


@router.post("")
async def create_statement(payload: StatementCreateIn, user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    if payload.type not in ("regular", "corrective"):
        raise HTTPException(400, "Type invalide (regular ou corrective)")
    date_from, date_to = _resolve_period(payload)
    overlap = await closed_overlap(db, date_from, date_to)
    if overlap:
        raise HTTPException(409, f"La période chevauche le décompte clôturé {overlap['number']} "
                                 f"({overlap['date_from']} → {overlap['date_to']})")
    stmt = {
        "id": str(uuid.uuid4()),
        "number": await next_statement_number(db),
        "type": payload.type,
        "scope": "fleet",
        "period_month": payload.period_month,
        "date_from": date_from, "date_to": date_to,
        "include_carried_over": payload.include_carried_over,
        "status": "draft", "version": 1, "versions": [],
        "totals": None, "close_exception": None,
        "created_at": _now(), "created_by": user["email"],
        "updated_at": _now(), "closed_at": None, "closed_by": None,
    }
    await db.fuel_statements.insert_one(dict(stmt))
    await refresh_statement(db, stmt)
    await log_audit("fuel.statement.create", user,
                    {"statement_id": stmt["id"], "number": stmt["number"],
                     "period": f"{date_from} → {date_to}", "type": payload.type})
    return await get_statement(stmt["id"], user)


@router.get("")
async def list_statements(user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    db = get_db()
    rows = await db.fuel_statements.find({}, {"_id": 0, "tenant_id": 0}) \
        .sort("created_at", -1).to_list(500)
    for r in rows:
        t = r.get("totals") or {}
        r["totals_summary"] = {"amount_chf_total": t.get("amount_chf_total"),
                               "tx_count": t.get("tx_count"),
                               "blockers_count": (t.get("blockers") or {}).get("total_count", 0)}
        r.pop("totals", None)
    return rows


@router.get("/{statement_id}")
async def get_statement(statement_id: str, user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    db = get_db()
    stmt = await db.fuel_statements.find_one({"id": statement_id}, {"_id": 0, "tenant_id": 0})
    if not stmt:
        raise HTTPException(404, "Décompte introuvable")
    stmt["lines"] = await get_lines(db, statement_id, stmt["version"])
    stmt["late_transactions"] = await late_transactions(db, stmt)
    return stmt


async def _load_editable(db, statement_id: str) -> dict:
    stmt = await db.fuel_statements.find_one({"id": statement_id}, {"_id": 0})
    if not stmt:
        raise HTTPException(404, "Décompte introuvable")
    if stmt["status"] == "closed":
        raise HTTPException(409, "Décompte clôturé — rouvrez-le d'abord (motif obligatoire)")
    return stmt


@router.post("/{statement_id}/refresh")
async def refresh(statement_id: str, user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    stmt = await _load_editable(db, statement_id)
    totals = await refresh_statement(db, stmt)
    await log_audit("fuel.statement.refresh", user,
                    {"statement_id": statement_id, "number": stmt["number"]})
    return {"refreshed": True, "totals": totals}


@router.post("/{statement_id}/check")
async def check(statement_id: str, user=Depends(require_roles("admin"))):
    """Contrôle : régénère puis passe en « Validé » (0 bloquant) ou « À contrôler »."""
    _tenant_or_400()
    db = get_db()
    stmt = await _load_editable(db, statement_id)
    totals = await refresh_statement(db, stmt)
    blockers = totals["blockers"]
    new_status = "validated" if blockers["total_count"] == 0 else "to_review"
    await db.fuel_statements.update_one(
        {"id": statement_id},
        {"$set": {"status": new_status, "checked_at": _now(), "checked_by": user["email"],
                  "updated_at": _now()}})
    await log_audit("fuel.statement.check", user,
                    {"statement_id": statement_id, "number": stmt["number"],
                     "result": new_status, "blockers": blockers["total_count"]})
    return {"status": new_status, "blockers": blockers}


class CloseIn(BaseModel):
    force: bool = False
    reason: Optional[str] = None


@router.post("/{statement_id}/close")
async def close_statement(statement_id: str, payload: CloseIn, user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    stmt = await _load_editable(db, statement_id)
    overlap = await closed_overlap(db, stmt["date_from"], stmt["date_to"], exclude_id=statement_id)
    if overlap:
        raise HTTPException(409, f"La période chevauche le décompte clôturé {overlap['number']}")
    # re-vérification systématique au moment de la clôture (données live)
    lines = await build_lines(db, stmt["date_from"], stmt["date_to"],
                              stmt.get("include_carried_over", True))
    blocked = [l for l in lines if l["blockers"]]
    if blocked and not payload.force:
        blocked_chf = round(sum(l.get("amount_chf") or 0 for l in blocked), 2)
        reasons = sorted({b for l in blocked for b in l["blockers"]})
        raise HTTPException(409, {
            "message": f"Clôture impossible — {len(blocked)} élément(s) nécessitent une intervention",
            "count": len(blocked), "amount_chf": blocked_chf, "reasons": reasons,
            "unmatched": sum(1 for l in blocked if "Non rapprochée" in l["blockers"]),
            "fx_pending": sum(1 for l in blocked if "Conversion en attente" in l["blockers"]),
        })
    exception = None
    if blocked:
        if not (payload.reason or "").strip():
            raise HTTPException(400, "Motif obligatoire pour une exception de clôture")
        lines = [l for l in lines if not l["blockers"]]
        exception = {"applied": True, "reason": payload.reason.strip(),
                     "excluded_count": len(blocked), "by": user["email"], "at": _now()}
        # transactions exclues → reportées (jamais exclues silencieusement)
        await db.fuel_transactions.update_many(
            {"id": {"$in": [l["transaction_id"] for l in blocked]}},
            {"$set": {"deferred_from_statement_id": statement_id, "updated_at": _now()}})
    totals = compute_totals(lines)
    now = _now()
    await persist_lines(db, statement_id, stmt["version"], lines)
    # verrouillage : montants/taux/affectations figés, plus aucun recalcul
    await db.fuel_transactions.update_many(
        {"id": {"$in": [l["transaction_id"] for l in lines]}},
        {"$set": {"locked": True, "statement_id": statement_id, "updated_at": now},
         "$unset": {"deferred_from_statement_id": ""}})
    await db.fuel_statements.update_one(
        {"id": statement_id},
        {"$set": {"status": "closed", "totals": totals, "closed_at": now,
                  "closed_by": user["email"], "close_exception": exception, "updated_at": now}})
    await log_audit("fuel.statement.close", user,
                    {"statement_id": statement_id, "number": stmt["number"],
                     "version": stmt["version"], "tx_locked": len(lines),
                     "amount_chf_total": totals["amount_chf_total"],
                     "exception": exception})
    return {"closed": True, "tx_locked": len(lines),
            "excluded": (exception or {}).get("excluded_count", 0),
            "totals": totals}


class ReopenIn(BaseModel):
    reason: str


@router.post("/{statement_id}/reopen")
async def reopen_statement(statement_id: str, payload: ReopenIn, user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    if not payload.reason.strip():
        raise HTTPException(400, "Motif obligatoire pour rouvrir un décompte clôturé")
    stmt = await db.fuel_statements.find_one({"id": statement_id}, {"_id": 0})
    if not stmt:
        raise HTTPException(404, "Décompte introuvable")
    if stmt["status"] != "closed":
        raise HTTPException(400, "Seul un décompte clôturé peut être rouvert")
    later = await db.fuel_statements.find_one(
        {"status": "closed", "date_from": {"$gt": stmt["date_to"]}},
        {"_id": 0, "number": 1})
    if later:
        raise HTTPException(409, f"Réouverture impossible : le décompte postérieur {later['number']} "
                                 "est déjà clôturé. Créez plutôt un décompte correctif.")
    now = _now()
    archived = {"version": stmt["version"], "totals": stmt.get("totals"),
                "closed_at": stmt.get("closed_at"), "closed_by": stmt.get("closed_by"),
                "close_exception": stmt.get("close_exception"),
                "status": "replaced", "replaced_at": now, "replaced_by": user["email"],
                "replace_reason": payload.reason.strip()}
    # déverrouillage des transactions de ce décompte
    unlocked = await db.fuel_transactions.update_many(
        {"statement_id": statement_id},
        {"$set": {"locked": False, "updated_at": now}, "$unset": {"statement_id": ""}})
    await db.fuel_statements.update_one(
        {"id": statement_id},
        {"$set": {"status": "to_review", "version": stmt["version"] + 1,
                  "closed_at": None, "closed_by": None, "close_exception": None,
                  "updated_at": now},
         "$push": {"versions": archived}})
    new_stmt = {**stmt, "version": stmt["version"] + 1}
    await refresh_statement(db, new_stmt)
    await log_audit("fuel.statement.reopen", user,
                    {"statement_id": statement_id, "number": stmt["number"],
                     "from_version": stmt["version"], "to_version": stmt["version"] + 1,
                     "tx_unlocked": unlocked.modified_count, "reason": payload.reason.strip()})
    return {"reopened": True, "version": stmt["version"] + 1, "status": "to_review"}


@router.delete("/{statement_id}")
async def delete_statement(statement_id: str, user=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    stmt = await db.fuel_statements.find_one({"id": statement_id}, {"_id": 0})
    if not stmt:
        raise HTTPException(404, "Décompte introuvable")
    if stmt["status"] not in ("draft", "to_review"):
        raise HTTPException(409, "Seuls les décomptes en brouillon ou à contrôler peuvent être supprimés")
    await db.fuel_statement_lines.delete_many({"statement_id": statement_id})
    await db.fuel_statements.delete_one({"id": statement_id})
    await log_audit("fuel.statement.delete", user,
                    {"statement_id": statement_id, "number": stmt["number"]})
    return {"deleted": True}


@router.get("/{statement_id}/export")
async def export_statement(statement_id: str, fmt: str = "pdf",
                           user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    db = get_db()
    if fmt == "xlsx":
        fmt = "excel"
    if fmt not in ("pdf", "excel", "csv"):
        raise HTTPException(400, "Format invalide (pdf, excel ou csv)")
    stmt = await db.fuel_statements.find_one({"id": statement_id}, {"_id": 0, "tenant_id": 0})
    if not stmt:
        raise HTTPException(404, "Décompte introuvable")
    lines = await get_lines(db, statement_id, stmt["version"])
    tenant = get_tenant_doc() or {}
    if fmt == "pdf":
        data, media, ext = build_pdf(stmt, lines, tenant.get("name", "")), "application/pdf", "pdf"
    elif fmt == "excel":
        data = build_excel(stmt, lines)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    else:
        data, media, ext = build_csv(stmt, lines), "text/csv; charset=utf-8", "csv"
    digest = hashlib.sha256(data).hexdigest()
    await log_audit("fuel.statement.export", user,
                    {"statement_id": statement_id, "number": stmt["number"],
                     "version": stmt["version"], "format": fmt, "sha256": digest,
                     "status": stmt["status"]})
    suffix = "" if stmt["status"] == "closed" else "_PROVISOIRE"
    filename = f"{stmt['number']}_V{stmt['version']}{suffix}.{ext}"
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
