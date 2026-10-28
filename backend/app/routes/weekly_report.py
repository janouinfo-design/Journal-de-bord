"""Rapport hebdomadaire chauffeur — configuration + téléchargement manuel.

RBAC : admin/manager uniquement. Isolation tenant stricte (get_db scopé).
Le téléchargement régénère le rapport à la demande (aucun envoi SMTP ici).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from app.auth import require_roles
from app.access_control import require_module
from app.db import get_db, get_raw_db
from app.emailer import is_smtp_configured
from app.tenant_context import get_effective_tenant_id
from app.weekly_driver_report import (
    aggregate_week,
    get_report_config,
    monday_of,
    previous_week_monday,
)

router = APIRouter(tags=["weekly-report"], dependencies=[Depends(require_module("reports"))])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _tenant_or_400() -> str:
    tid = get_effective_tenant_id()
    if not tid:
        raise HTTPException(400, "Sélectionnez d'abord un client (en-tête X-Tenant-Id)")
    return tid


async def _config_payload(db, tid: str) -> dict:
    cfg = await get_report_config(db)
    raw = get_raw_db()
    last = await raw.weekly_report_log.find_one(
        {"tenant_id": tid}, {"_id": 0, "week_monday": 1, "status": 1,
                             "created_at": 1, "recipients": 1, "error": 1},
        sort=[("created_at", -1)])
    from app.scheduler import weekly_report_next_run
    return {
        "enabled": cfg["enabled"],
        "recipients": cfg["recipients"],
        "smtp_configured": is_smtp_configured(),
        "period_rule": "Semaine précédente — lundi à dimanche (Europe/Zurich)",
        "formats": ["pdf", "xlsx"],
        "send_day": "Lundi 06:00 (Europe/Zurich)",
        "next_run": weekly_report_next_run(),
        "last_send": last,
        "default_week": previous_week_monday().isoformat(),
    }


@router.get("/reports/weekly-driver/config")
async def get_weekly_report_config(user=Depends(require_roles("admin", "manager"))):
    tid = _tenant_or_400()
    return await _config_payload(get_db(), tid)


class WeeklyReportConfigIn(BaseModel):
    enabled: Optional[bool] = None
    recipients: Optional[list[str]] = None


@router.put("/reports/weekly-driver/config")
async def put_weekly_report_config(payload: WeeklyReportConfigIn,
                                   user=Depends(require_roles("admin", "manager"))):
    tid = _tenant_or_400()
    db = get_db()
    old = await get_report_config(db)
    updates: dict = {}
    if payload.enabled is not None:
        updates["weekly_report_enabled"] = bool(payload.enabled)
    if payload.recipients is not None:
        if len(payload.recipients) > 20:
            raise HTTPException(400, "Maximum 20 destinataires")
        clean: list[str] = []
        for r in payload.recipients:
            e = (r or "").strip().lower()
            if not _EMAIL_RE.match(e):
                raise HTTPException(400, f"Adresse e-mail invalide : {r}")
            if e not in clean:
                clean.append(e)
        updates["weekly_report_recipients"] = clean
    if updates:
        await db.settings.update_one({"id": "default"}, {"$set": updates}, upsert=True)
        from app.audit import log_audit
        await log_audit("reports.weekly_driver.config_update", user, {
            "tenant_id": tid, "old": old, "new": updates})
    return await _config_payload(db, tid)


@router.get("/reports/weekly-driver/download")
async def download_weekly_report(
    week: str = Query(..., description="Date du lundi de la semaine (YYYY-MM-DD)"),
    format: str = Query("pdf", pattern="^(pdf|xlsx)$"),
    user=Depends(require_roles("admin", "manager")),
):
    tid = _tenant_or_400()
    try:
        wm = monday_of(date.fromisoformat(week))
    except ValueError:
        raise HTTPException(400, "Paramètre week invalide — format attendu YYYY-MM-DD")
    db = get_db()
    tenant = await get_raw_db().tenants.find_one({"id": tid}, {"_id": 0, "name": 1}) or {}
    tenant_name = tenant.get("name") or tid
    dataset = await aggregate_week(db, wm)
    from app.audit import log_audit
    await log_audit("reports.weekly_driver.download", user, {
        "tenant_id": tid, "week_monday": wm.isoformat(), "format": format,
        "drivers": len(dataset["rows"])})
    fname = f"rapport_hebdo_chauffeurs_{wm.isoformat()}.{format}"
    if format == "xlsx":
        from app.reports import weekly_driver_report_to_xlsx
        return Response(
            weekly_driver_report_to_xlsx(dataset, tenant_name),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'})
    from app.reports import weekly_driver_report_to_pdf
    return Response(
        weekly_driver_report_to_pdf(dataset, tenant_name),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})
