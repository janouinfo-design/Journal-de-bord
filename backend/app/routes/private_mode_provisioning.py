# app/routes/private_mode_provisioning.py
"""LOT P1 -- READ-ONLY tenant-scoped provisioning diagnostic endpoint.

GET /api/livre/vehicles/{vehicle_id}/private-mode/provisioning
RBAC: admin (require_roles also accepts superadmin). No device command, no write.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_roles
from app.db import get_db
from app.tenant_context import get_effective_tenant_id
from app import private_mode_provisioning as engine
from app import private_mode_field_validation as field_validation
from pydantic import BaseModel

router = APIRouter(tags=["private-mode-provisioning"])


def _effective_tenant(user):
    """Superadmin uses the explicitly selected tenant (never 'default')."""
    if user.get("role") == "superadmin":
        return get_effective_tenant_id()
    return user.get("tenant_id") or "default"


@router.get("/vehicles/{vehicle_id}/private-mode/provisioning")
async def get_private_mode_provisioning(
    vehicle_id: str,
    user=Depends(require_roles("admin")),
):
    tenant_id = _effective_tenant(user)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Aucun tenant s\u00e9lectionn\u00e9")
    db = get_db()
    try:
        return await engine.build_provisioning_diagnostic(
            db, tenant_id=tenant_id, vehicle_id=vehicle_id
        )
    except engine.ProvisioningResolveError:
        # Another tenant's vehicle must be indistinguishable from a missing one.
        raise HTTPException(status_code=404, detail="V\u00e9hicule introuvable")


@router.post("/vehicles/{vehicle_id}/private-mode/provisioning/discovery")
async def persist_private_mode_discovery(
    vehicle_id: str,
    user=Depends(require_roles("admin")),
):
    """Persist Raw-IoT discovery evidence only. Never promotes profile readiness."""
    tenant_id = _effective_tenant(user)
    if not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="Aucun tenant sélectionné",
        )

    db = get_db()
    try:
        return await engine.persist_input_discovery(
            db,
            tenant_id=tenant_id,
            vehicle_id=vehicle_id,
        )
    except engine.ProvisioningResolveError:
        raise HTTPException(
            status_code=404,
            detail="Véhicule introuvable",
        )


class _FieldValidationFinalizeIn(BaseModel):
    # Confirmation EXPLICITE obligatoire (action sensible : peut promouvoir la
    # capability). Pas de valeur par défaut -> le client doit envoyer confirm=true.
    confirm: bool


@router.post("/vehicles/{vehicle_id}/private-mode/field-validation/start")
async def start_field_validation_route(
    vehicle_id: str,
    user=Depends(require_roles("admin")),
):
    """P3E-5 — Ouvre une session de validation terrain FMC003 (admin/superadmin).

    N'envoie AUCUNE commande device et ne promeut AUCUNE capability.
    Crée uniquement la session de validation (`private_mode_field_validations`)
    et son entrée d'audit.
    """
    tenant_id = _effective_tenant(user)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Aucun tenant s\u00e9lectionn\u00e9")
    db = get_db()
    res = await field_validation.start_field_validation(
        db, tenant_id=tenant_id, vehicle_id=vehicle_id,
        actor=user.get("email", "?"))
    if res.get("ok"):
        return res
    reason = res.get("reason")
    status = {
        field_validation.R_VEHICLE_NOT_FOUND: 404,
        field_validation.R_NOT_FMC003: 409,
        field_validation.R_NO_TRACKER: 409,
        field_validation.R_SESSION_ALREADY_OPEN: 409,
    }.get(reason, 400)
    raise HTTPException(status_code=status, detail=res)


@router.get("/vehicles/{vehicle_id}/private-mode/field-validation/{validation_id}")
async def get_field_validation_route(
    vehicle_id: str,
    validation_id: str,
    user=Depends(require_roles("admin")),
):
    """P3E-5 — Statut + preuves d'une session (bornée au tenant ET au véhicule)."""
    tenant_id = _effective_tenant(user)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Aucun tenant s\u00e9lectionn\u00e9")
    db = get_db()
    res = await field_validation.get_field_validation_status(
        db, tenant_id=tenant_id, validation_id=validation_id)
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail="Session introuvable")
    if res.get("vehicle_id") != vehicle_id:
        raise HTTPException(status_code=404, detail="Session introuvable")
    return res


@router.post("/vehicles/{vehicle_id}/private-mode/field-validation/{validation_id}/finalize")
async def finalize_field_validation_route(
    vehicle_id: str,
    validation_id: str,
    payload: _FieldValidationFinalizeIn,
    user=Depends(require_roles("admin")),
):
    """P3E-5 — Collecte les preuves (aucune commande device), calcule le verdict
    et promeut la capability du tracker UNIQUEMENT si PASS complet.
    N'active JAMAIS `vehicle.private_mode_pilot` (action admin séparée)."""
    if payload.confirm is not True:
        raise HTTPException(status_code=400, detail="Confirmation requise")
    tenant_id = _effective_tenant(user)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Aucun tenant s\u00e9lectionn\u00e9")
    db = get_db()
    status_doc = await field_validation.get_field_validation_status(
        db, tenant_id=tenant_id, validation_id=validation_id)
    if not status_doc.get("ok") or status_doc.get("vehicle_id") != vehicle_id:
        raise HTTPException(status_code=404, detail="Session introuvable")
    res = await field_validation.finalize_field_validation(
        db, tenant_id=tenant_id, validation_id=validation_id,
        actor=user.get("email", "?"))
    if not res.get("ok"):
        reason = res.get("reason")
        status = {
            field_validation.R_SESSION_NOT_FOUND: 404,
            field_validation.R_SESSION_NOT_OPEN: 409,
        }.get(reason, 400)
        raise HTTPException(status_code=status, detail=res)
    return res
