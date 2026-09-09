"""Rapport hebdomadaire chauffeur — agrégation lundi -> dimanche (Europe/Zurich).

Source unique de vérité : l'agrégation vit ici, `reports.py` ne fait que la
mise en forme (PDF/XLSX depuis le MÊME dataset). Le job scheduler (lundi 06:00
Europe/Zurich) orchestre : agrégation -> PDF+XLSX -> envoi SMTP si configuré.
Un échec tenant n'affecte jamais les autres tenants. Idempotence par
(tenant, semaine) via la collection `weekly_report_log`.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Zurich")

STATUS_SENT = "sent"
STATUS_NO_SMTP = "not_sent_smtp_not_configured"
STATUS_NO_RECIPIENTS = "not_sent_no_recipients"
STATUS_ERROR = "error"


# ---------- Période ----------
def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def previous_week_monday(now: datetime | None = None) -> date:
    """Lundi de la semaine civile précédente, en heure Europe/Zurich."""
    local = (now or datetime.now(TZ)).astimezone(TZ).date()
    return monday_of(local) - timedelta(days=7)


def week_bounds(week_monday: date) -> tuple[str, str]:
    """Bornes UTC ISO [lundi 00:00, lundi suivant 00:00) en heure Europe/Zurich."""
    start = datetime(week_monday.year, week_monday.month, week_monday.day, tzinfo=TZ)
    end = start + timedelta(days=7)
    return (start.astimezone(timezone.utc).isoformat(),
            end.astimezone(timezone.utc).isoformat())


def period_label(week_monday: date) -> str:
    sunday = week_monday + timedelta(days=6)
    return f"du {week_monday.strftime('%d/%m/%Y')} au {sunday.strftime('%d/%m/%Y')}"


# ---------- Configuration (settings tenant-aware) ----------
async def get_report_config(db) -> dict:
    s = await db.settings.find_one({"id": "default"}, {"_id": 0}) or {}
    return {
        "enabled": s.get("weekly_report_enabled") is True,
        "recipients": s.get("weekly_report_recipients") or [],
    }


# ---------- Agrégation ----------
async def aggregate_week(db, week_monday: date) -> dict:
    """1 ligne par chauffeur — km PRO / PRIVÉ / non classifiés / total (= tous
    les km parcourus), nb trajets, véhicules utilisés, trajets non classifiés."""
    start_iso, end_iso = week_bounds(week_monday)
    projection = {"_id": 0, "driver_id": 1, "driver_name": 1, "vehicle_id": 1,
                  "vehicle_plate": 1, "distance_km": 1, "classification": 1}
    trips = await db.trips.find(
        {"start_time": {"$gte": start_iso, "$lt": end_iso}}, projection,
    ).limit(50000).to_list(50000)

    per: dict[str, dict] = {}
    plate_by_vid: dict[str, str] = {}
    for t in trips:
        key = t.get("driver_id") or "__none__"
        row = per.setdefault(key, {
            "driver_id": t.get("driver_id"),
            "driver_name": t.get("driver_name") or "— Sans chauffeur —",
            "km_pro": 0.0, "km_private": 0.0, "km_unclassified": 0.0,
            "trip_count": 0, "unclassified_trip_count": 0,
            "_vehicle_ids": set(),
        })
        km = t.get("distance_km") or 0
        cl = t.get("classification")
        if cl == "professional":
            row["km_pro"] += km
        elif cl == "personal":
            row["km_private"] += km
        else:
            row["km_unclassified"] += km
            row["unclassified_trip_count"] += 1
        row["trip_count"] += 1
        vid = t.get("vehicle_id")
        if vid:
            row["_vehicle_ids"].add(vid)
            if t.get("vehicle_plate"):
                plate_by_vid[vid] = t["vehicle_plate"]

    all_vids = list({v for r in per.values() for v in r["_vehicle_ids"]})
    vehicles = {}
    if all_vids:
        async for v in db.vehicles.find({"id": {"$in": all_vids}},
                                        {"_id": 0, "id": 1, "plate": 1, "model": 1}):
            vehicles[v["id"]] = v

    rows = []
    for row in per.values():
        used = []
        for vid in row.pop("_vehicle_ids"):
            v = vehicles.get(vid)
            if v and v.get("plate"):
                label = f"{v['plate']} ({v['model']})" if v.get("model") else v["plate"]
            else:
                label = plate_by_vid.get(vid) or vid
            used.append(label)
        row["vehicles_used"] = sorted(used)
        row["km_total"] = row["km_pro"] + row["km_private"] + row["km_unclassified"]
        for k in ("km_pro", "km_private", "km_unclassified", "km_total"):
            row[k] = round(row[k], 2)
        rows.append(row)
    rows.sort(key=lambda r: (r["driver_name"] or "").lower())

    totals = {
        "km_pro": round(sum(r["km_pro"] for r in rows), 2),
        "km_private": round(sum(r["km_private"] for r in rows), 2),
        "km_unclassified": round(sum(r["km_unclassified"] for r in rows), 2),
        "km_total": round(sum(r["km_total"] for r in rows), 2),
        "trip_count": sum(r["trip_count"] for r in rows),
        "unclassified_trip_count": sum(r["unclassified_trip_count"] for r in rows),
    }
    return {
        "period": {
            "week_monday": week_monday.isoformat(),
            "start": start_iso, "end": end_iso,
            "label": period_label(week_monday),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "totals": totals,
    }


# ---------- Envoi ----------
def _email_bodies(tenant_name: str, dataset: dict) -> tuple[str, str, str]:
    label = dataset["period"]["label"]
    t = dataset["totals"]
    subject = f"Rapport hebdomadaire chauffeurs — {tenant_name} — semaine {label}"
    text = (
        f"Rapport hebdomadaire chauffeurs — {tenant_name}\n"
        f"Période : semaine {label} (lundi à dimanche)\n\n"
        f"Chauffeurs : {len(dataset['rows'])}\n"
        f"Km professionnels : {t['km_pro']}\n"
        f"Km privés : {t['km_private']}\n"
        f"Km non classifiés : {t['km_unclassified']}\n"
        f"Km total : {t['km_total']}\n"
        f"Trajets : {t['trip_count']} (dont {t['unclassified_trip_count']} non classifiés)\n\n"
        "Les rapports détaillés PDF et XLSX sont en pièces jointes.\n"
    )
    html = f"""\
<!DOCTYPE html>
<html><body style="font-family:Arial,Helvetica,sans-serif;background:#f4f6f8;padding:24px;">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:8px;padding:32px;border:1px solid #e2e8f0;">
    <h2 style="margin:0 0 8px;color:#0f172a;">Rapport hebdomadaire chauffeurs — {tenant_name}</h2>
    <p style="color:#334155;">Période : <strong>semaine {label}</strong> (lundi à dimanche)</p>
    <table style="border-collapse:collapse;color:#334155;font-size:14px;">
      <tr><td style="padding:2px 12px 2px 0;">Chauffeurs</td><td><strong>{len(dataset['rows'])}</strong></td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Km professionnels</td><td><strong>{t['km_pro']}</strong></td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Km privés</td><td><strong>{t['km_private']}</strong></td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Km non classifiés</td><td><strong>{t['km_unclassified']}</strong></td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Km total</td><td><strong>{t['km_total']}</strong></td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Trajets</td><td><strong>{t['trip_count']}</strong> (dont {t['unclassified_trip_count']} non classifiés)</td></tr>
    </table>
    <p style="color:#64748b;font-size:13px;margin-top:16px;">
      Les rapports détaillés <strong>PDF</strong> (prêt à archiver) et <strong>XLSX</strong> (exploitable) sont en pièces jointes.</p>
  </div>
</body></html>"""
    return subject, text, html


async def _log_run(raw, tenant_id: str, week_monday_iso: str, status: str,
                   recipients: list[str], error: str | None):
    await raw.weekly_report_log.insert_one({
        "tenant_id": tenant_id,
        "week_monday": week_monday_iso,
        "status": status,
        "recipients": recipients,
        "error": error,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def run_weekly_report_job(week_monday: date | None = None) -> dict:
    """Job du lundi 06:00 Europe/Zurich — semaine précédente complète.

    Statuts : sent | not_sent_smtp_not_configured | not_sent_no_recipients |
    error | already_sent (idempotence). SMTP absent ne fait jamais échouer le job.
    """
    from app import emailer
    from app.db import get_db, get_raw_db
    from app.reports import weekly_driver_report_to_pdf, weekly_driver_report_to_xlsx
    from app.tenant_context import reset_current_tenant, set_current_tenant

    raw = get_raw_db()
    wm = week_monday or previous_week_monday()
    wm_iso = wm.isoformat()
    results: dict[str, str] = {}

    async for t in raw.tenants.find({"status": "active"}, {"_id": 0, "id": 1, "name": 1}):
        token = set_current_tenant(t["id"])
        try:
            db = get_db()
            cfg = await get_report_config(db)
            if not cfg["enabled"]:
                continue
            already = await raw.weekly_report_log.find_one(
                {"tenant_id": t["id"], "week_monday": wm_iso, "status": STATUS_SENT})
            if already:
                results[t["id"]] = "already_sent"
                continue

            recipients = cfg["recipients"]
            error = None
            if not recipients:
                status = STATUS_NO_RECIPIENTS
            elif not emailer.is_smtp_configured():
                status = STATUS_NO_SMTP
            else:
                tenant_name = t.get("name") or t["id"]
                dataset = await aggregate_week(db, wm)
                pdf = weekly_driver_report_to_pdf(dataset, tenant_name)
                xlsx = weekly_driver_report_to_xlsx(dataset, tenant_name)
                subject, text, html = _email_bodies(tenant_name, dataset)
                ok = await emailer.send_email_with_attachments(
                    recipients, subject, text, html,
                    [(f"rapport_hebdo_chauffeurs_{wm_iso}.pdf", pdf, "application", "pdf"),
                     (f"rapport_hebdo_chauffeurs_{wm_iso}.xlsx", xlsx, "application",
                      "vnd.openxmlformats-officedocument.spreadsheetml.sheet")])
                status = STATUS_SENT if ok else STATUS_ERROR
                error = None if ok else "Échec de l'envoi SMTP"
            await _log_run(raw, t["id"], wm_iso, status, recipients, error)
            results[t["id"]] = status
            logger.info("Rapport hebdo %s (%s): %s", wm_iso, t["id"], status)
        except Exception as e:
            logger.exception("Rapport hebdo échoué pour tenant %s", t["id"])
            try:
                await _log_run(raw, t["id"], wm_iso, STATUS_ERROR, [], str(e)[:300])
            except Exception:
                pass
            results[t["id"]] = STATUS_ERROR
        finally:
            reset_current_tenant(token)
    return results
