"""Reports — PDF / Excel / CSV exports + Swiss tax report."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Response

from app.auth import get_current_user
from app.db import get_db
from app.reports import (
    swiss_tax_report_pdf,
    trips_to_csv,
    trips_to_pdf,
    trips_to_xlsx,
)

from app.routes._helpers import (
    filename,
    filter_trips_query,
    get_settings_doc,
)

router = APIRouter(tags=["reports"])


@router.get("/reports/export")
async def export_report(
    classification: str = Query(..., regex="^(professional|personal)$"),
    fmt: str = Query("pdf", regex="^(pdf|xlsx|csv)$"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    driver_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    group: Optional[str] = None,
    company: Optional[str] = None,
    user=Depends(get_current_user),
):
    db = get_db()
    settings = await get_settings_doc(db)
    q = await filter_trips_query(db, user, start, end, driver_id, vehicle_id, classification,
                                 group=group, company=company)
    # Reports need most trip fields (addresses, speeds, fuel, durations) for
    # the PDF/Excel/CSV output. Cap at 10k to avoid runaway memory on huge fleets.
    trips = await db.trips.find(q, {"_id": 0}).sort("start_time", -1).limit(10000).to_list(10000)
    from app.audit import log_audit
    await log_audit("report.export", user,
                    {"classification": classification, "format": fmt, "count": len(trips)})

    # Confidentialité (Phase 2/3) : un trajet effectué en Mode Privé (device) ne doit
    # JAMAIS exporter de localisation (adresses/coords), quelle que soit sa classification.
    # On conserve les champs métier (distance, durée) ; on remplace la géo par un libellé.
    from app.private_mode_engine import redact_private_trip, trip_is_private
    _redacted = []
    for _t in trips:
        if trip_is_private(_t):
            _rt = redact_private_trip(_t)
            _rt["start_address"] = "Privé — position masquée"
            _rt["end_address"] = "Privé — position masquée"
            _redacted.append(_rt)
        else:
            _redacted.append(_t)
    trips = _redacted

    # Privacy mode 'masked' for managers — personal report contains no per-trip data
    is_masked = (classification == "personal"
                 and settings.get("mode") == "masked"
                 and user["role"] != "admin")
    if is_masked:
        total_km = round(sum((t.get("distance_km") or 0) for t in trips), 1)
        all_q = dict(q)
        all_q.pop("classification", None)
        # Aggregate-only — just the distance + classification fields
        all_km_docs = await db.trips.find(
            all_q, {"_id": 0, "distance_km": 1, "classification": 1},
        ).limit(20000).to_list(20000)
        total_all = round(sum((d.get("distance_km") or 0) for d in all_km_docs), 1)
        pct = round(total_km / total_all * 100, 1) if total_all else 0
        trips = [{
            "start_time": start or "", "end_time": end or "",
            "driver_name": "—", "vehicle_plate": "—",
            "start_address": "—", "end_address": "—",
            "distance_km": total_km, "duration_min": 0,
            "fuel_l": 0, "avg_speed": 0, "max_speed": 0,
        }]
        label = f"Personnel (anonymisé · {pct}% sur la période)"
    else:
        label = "Professionnel" if classification == "professional" else "Personnel"
    title = f"Rapport {label} — Logitrak Livre de Bord"
    subtitle = ""
    if start or end:
        subtitle = f"Période : {start or '—'} → {end or '—'}"

    if fmt == "csv":
        data = trips_to_csv(trips, label)
        return Response(data, media_type="text/csv",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{filename(classification, "csv")}"'})
    if fmt == "xlsx":
        data = trips_to_xlsx(trips, label, title)
        return Response(
            data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition":
                     f'attachment; filename="{filename(classification, "xlsx")}"'},
        )
    data = trips_to_pdf(trips, label, title, subtitle)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'attachment; filename="{filename(classification, "pdf")}"'})


@router.get("/reports/tax-swiss")
async def tax_swiss_report(
    year: int = Query(...),
    driver_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    db = get_db()
    start = f"{year}-01-01T00:00:00+00:00"
    end = f"{year}-12-31T23:59:59+00:00"
    q = await filter_trips_query(db, user, start, end, driver_id, vehicle_id, None)
    # Swiss tax report aggregate — need distance, classification, fuel, vehicle_id.
    projection = {"_id": 0, "distance_km": 1, "classification": 1, "fuel_l": 1, "vehicle_id": 1}
    trips = await db.trips.find(q, projection).limit(20000).to_list(20000)

    pro_km = sum(t["distance_km"] for t in trips if t.get("classification") == "professional")

    # Km PRIVÉ = source canonique AVL16 (même agrégateur/cutover que km-summary).
    # Flag OFF -> l'agrégateur retombe sur le GPS legacy (mêmes chiffres qu'avant).
    from datetime import datetime, timezone
    from app import private_mileage as _pm
    tenant_id = user.get("tenant_id") or "default"
    start_utc = datetime(year, 1, 1, tzinfo=timezone.utc)
    end_utc = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    # SCOPE des véhicules : trajets présents (PRO/PRIVÉ GPS) UNION véhicules ayant une
    # session AVL16 CLOSED dans la période (FIX PR#6 : un véhicule privé AVL16 SANS trip
    # GPS dans la fenêtre doit quand même entrer dans l'agrégation privée).
    scope_vids = {t.get("vehicle_id") for t in trips if t.get("vehicle_id")}
    sess_q = {"tenant_id": tenant_id, "state": _pm.S_CLOSED,
              "private_ended_at": {"$gte": start_utc.isoformat(), "$lte": end_utc.isoformat()}}
    if driver_id:
        sess_q["driver_id"] = driver_id
    if vehicle_id:
        sess_q["vehicle_id"] = vehicle_id
    async for s in db[_pm.COLLECTION].find(sess_q, {"_id": 0, "vehicle_id": 1}):
        if s.get("vehicle_id"):
            scope_vids.add(s["vehicle_id"])
    scope_vids = sorted(scope_vids)

    async def _gps_personal_for_vehicle(vid, s_utc, e_utc):
        qq = dict(q)
        qq.update({"vehicle_id": vid, "classification": "personal",
                   "start_time": {"$gte": s_utc.isoformat(), "$lt": e_utc.isoformat()}})
        docs = await db.trips.find(qq, {"_id": 0, "distance_km": 1}).limit(20000).to_list(20000)
        return round(sum((d.get("distance_km") or 0) for d in docs), 1)

    priv_agg = await _pm.aggregate_private_km_for_scope(
        db, tenant_id=tenant_id, vehicle_ids=scope_vids,
        start_utc=start_utc, end_utc=end_utc,
        gps_fallback_km_for_vehicle=_gps_personal_for_vehicle)
    # FIX PR#6 : ne JAMAIS convertir None -> 0. Un privé indisponible reste indisponible
    # (pas de faux 0 km / 0 %). Le générateur PDF gère l'état "Indisponible".
    perso_km = priv_agg["private_km"]                 # peut être None
    private_km_source = priv_agg["private_km_source"]
    perso_available = isinstance(perso_km, (int, float))

    pro_fuel = sum(t.get("fuel_l", 0) for t in trips if t.get("classification") == "professional")
    perso_fuel = sum(t.get("fuel_l", 0) for t in trips if t.get("classification") == "personal")

    if perso_available:
        total_km = pro_km + perso_km
        stats = {
            "pro_km": round(pro_km, 1),
            "perso_km": round(perso_km, 1),
            "total_km": round(total_km, 1),
            "pct_pro": round(pro_km / total_km * 100, 1) if total_km else 0,
            "pct_perso": round(perso_km / total_km * 100, 1) if total_km else 0,
            "pro_fuel": round(pro_fuel, 2),
            "perso_fuel": round(perso_fuel, 2),
            "perso_available": True,
            "private_km_source": private_km_source,   # traçabilité interne/audit
        }
    else:
        # Privé indisponible : on n'invente NI km NI % ; pro reste factuel.
        stats = {
            "pro_km": round(pro_km, 1),
            "perso_km": None,
            "total_km": None,
            "pct_pro": None,
            "pct_perso": None,
            "pro_fuel": round(pro_fuel, 2),
            "perso_fuel": round(perso_fuel, 2),
            "perso_available": False,
            "private_km_source": private_km_source,   # UNAVAILABLE
        }

    owner = ""
    if driver_id:
        d = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
        if d:
            owner = d.get("name", "")
    if vehicle_id:
        v = await db.vehicles.find_one({"id": vehicle_id}, {"_id": 0})
        if v:
            owner = (owner + " — " if owner else "") + v.get("plate", "")

    data = swiss_tax_report_pdf(stats, year, owner)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'attachment; filename="rapport_fiscal_suisse_{year}.pdf"'})
