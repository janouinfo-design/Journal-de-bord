"""Rapport mensuel fiscal chauffeurs — mois civil précédent (Europe/Zurich).

Réutilise l'agrégation partagée `weekly_driver_report.aggregate_range` et y
ajoute les éléments utiles à la déclaration : part privée (% des km classifiés),
cumul annuel (1er janvier -> fin du mois) et statut fiscal (Complet / À compléter
tant qu'il reste des trajets non classifiés). Aucun montant CHF n'est inventé.
Job scheduler : le 1er du mois à 06:00 Europe/Zurich. Idempotence par
(tenant, mois) via `monthly_report_log`.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from app.weekly_driver_report import (
    STATUS_ERROR,
    STATUS_NO_RECIPIENTS,
    STATUS_NO_SMTP,
    STATUS_SENT,
    TZ,
    aggregate_range,
)

logger = logging.getLogger(__name__)

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre"]

FISCAL_COMPLETE = "complete"
FISCAL_INCOMPLETE = "incomplete"


# ---------- Période ----------
def parse_month(value: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{4})-(\d{2})", (value or "").strip())
    if not m:
        raise ValueError("format attendu YYYY-MM")
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        raise ValueError("mois hors plage 01-12")
    return year, month


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def month_label(year: int, month: int) -> str:
    return f"{MONTHS_FR[month - 1]} {year}"


def previous_month(now: datetime | None = None) -> tuple[int, int]:
    """Mois civil précédent, en heure Europe/Zurich."""
    local = (now or datetime.now(TZ)).astimezone(TZ).date()
    prev = local.replace(day=1) - timedelta(days=1)
    return prev.year, prev.month


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def month_bounds(year: int, month: int) -> tuple[str, str]:
    """Bornes UTC ISO [1er 00:00, 1er du mois suivant 00:00) en heure Europe/Zurich."""
    start = datetime(year, month, 1, tzinfo=TZ)
    end = datetime(year + 1, 1, 1, tzinfo=TZ) if month == 12 else datetime(year, month + 1, 1, tzinfo=TZ)
    return _utc_iso(start), _utc_iso(end)


def year_start_iso(year: int) -> str:
    return _utc_iso(datetime(year, 1, 1, tzinfo=TZ))


# ---------- Configuration (settings tenant-aware) ----------
async def get_report_config(db) -> dict:
    s = await db.settings.find_one({"id": "default"}, {"_id": 0}) or {}
    return {
        "enabled": s.get("monthly_report_enabled") is True,
        "recipients": s.get("monthly_report_recipients") or [],
    }


# ---------- Agrégation ----------
def _pct_private(km_pro: float, km_private: float) -> float | None:
    classified = km_pro + km_private
    return round(km_private / classified * 100, 1) if classified > 0 else None


async def aggregate_month(db, year: int, month: int) -> dict:
    start_iso, end_iso = month_bounds(year, month)
    rows, totals = await aggregate_range(db, start_iso, end_iso)
    ytd_rows, ytd_totals = await aggregate_range(db, year_start_iso(year), end_iso)
    ytd_by_driver = {r["driver_id"] or "__none__": r for r in ytd_rows}

    for r in rows:
        y = ytd_by_driver.get(r["driver_id"] or "__none__", {})
        r["pct_private"] = _pct_private(r["km_pro"], r["km_private"])
        r["ytd_km_pro"] = y.get("km_pro", 0.0)
        r["ytd_km_private"] = y.get("km_private", 0.0)
        r["ytd_km_unclassified"] = y.get("km_unclassified", 0.0)
        r["fiscal_status"] = (FISCAL_COMPLETE if r["unclassified_trip_count"] == 0
                              else FISCAL_INCOMPLETE)

    totals["pct_private"] = _pct_private(totals["km_pro"], totals["km_private"])
    totals["ytd_km_pro"] = ytd_totals["km_pro"]
    totals["ytd_km_private"] = ytd_totals["km_private"]
    totals["ytd_km_unclassified"] = ytd_totals["km_unclassified"]
    totals["incomplete_drivers"] = sum(1 for r in rows if r["fiscal_status"] == FISCAL_INCOMPLETE)

    return {
        "period": {
            "month": month_key(year, month),
            "year": year,
            "month_num": month,
            "start": start_iso, "end": end_iso,
            "label": month_label(year, month),
            "ytd_label": f"01/01/{year} - fin {month_label(year, month)}",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "totals": totals,
    }


# ---------- Envoi ----------
def _email_bodies(tenant_name: str, dataset: dict) -> tuple[str, str, str]:
    label = dataset["period"]["label"]
    t = dataset["totals"]
    pct = "non calculable" if t["pct_private"] is None else f"{t['pct_private']} %"
    subject = f"Rapport mensuel fiscal chauffeurs — {tenant_name} — {label}"
    text = (
        f"Rapport mensuel fiscal chauffeurs — {tenant_name}\n"
        f"Période : {label} (mois civil, Europe/Zurich)\n\n"
        f"Chauffeurs : {len(dataset['rows'])}\n"
        f"Km professionnels : {t['km_pro']}\n"
        f"Km privés : {t['km_private']}\n"
        f"Km non classifiés : {t['km_unclassified']}\n"
        f"Km total : {t['km_total']}\n"
        f"Part privée (km classifiés) : {pct}\n"
        f"Trajets : {t['trip_count']} (dont {t['unclassified_trip_count']} non classifiés)\n"
        f"Chauffeurs à compléter avant déclaration : {t['incomplete_drivers']}\n"
        f"Cumul annuel : PRO {t['ytd_km_pro']} km · PRIVÉ {t['ytd_km_private']} km\n\n"
        "Les rapports détaillés PDF et XLSX sont en pièces jointes.\n"
    )
    html = f"""\
<!DOCTYPE html>
<html><body style="font-family:Arial,Helvetica,sans-serif;background:#f4f6f8;padding:24px;">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:8px;padding:32px;border:1px solid #e2e8f0;">
    <h2 style="margin:0 0 8px;color:#0f172a;">Rapport mensuel fiscal chauffeurs — {tenant_name}</h2>
    <p style="color:#334155;">Période : <strong>{label}</strong> (mois civil, Europe/Zurich)</p>
    <table style="border-collapse:collapse;color:#334155;font-size:14px;">
      <tr><td style="padding:2px 12px 2px 0;">Chauffeurs</td><td><strong>{len(dataset['rows'])}</strong></td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Km professionnels</td><td><strong>{t['km_pro']}</strong></td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Km privés</td><td><strong>{t['km_private']}</strong></td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Km non classifiés</td><td><strong>{t['km_unclassified']}</strong></td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Km total</td><td><strong>{t['km_total']}</strong></td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Part privée (km classifiés)</td><td><strong>{pct}</strong></td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Trajets</td><td><strong>{t['trip_count']}</strong> (dont {t['unclassified_trip_count']} non classifiés)</td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Chauffeurs à compléter</td><td><strong>{t['incomplete_drivers']}</strong></td></tr>
      <tr><td style="padding:2px 12px 2px 0;">Cumul annuel</td><td><strong>PRO {t['ytd_km_pro']} km · PRIVÉ {t['ytd_km_private']} km</strong></td></tr>
    </table>
    <p style="color:#64748b;font-size:13px;margin-top:16px;">
      Les rapports détaillés <strong>PDF</strong> (prêt à archiver) et <strong>XLSX</strong> (exploitable) sont en pièces jointes.</p>
  </div>
</body></html>"""
    return subject, text, html


async def _log_run(raw, tenant_id: str, month: str, status: str,
                   recipients: list[str], error: str | None):
    await raw.monthly_report_log.insert_one({
        "tenant_id": tenant_id,
        "month": month,
        "status": status,
        "recipients": recipients,
        "error": error,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def run_monthly_report_job(year_month: str | None = None) -> dict:
    """Job du 1er du mois 06:00 Europe/Zurich — mois civil précédent complet.

    Statuts : sent | not_sent_smtp_not_configured | not_sent_no_recipients |
    error | already_sent (idempotence). SMTP absent ne fait jamais échouer le job.
    """
    from app import emailer
    from app.db import get_db, get_raw_db
    from app.reports import monthly_driver_report_to_pdf, monthly_driver_report_to_xlsx
    from app.tenant_context import reset_current_tenant, set_current_tenant

    raw = get_raw_db()
    year, month = parse_month(year_month) if year_month else previous_month()
    key = month_key(year, month)
    results: dict[str, str] = {}

    async for t in raw.tenants.find({"status": "active"}, {"_id": 0, "id": 1, "name": 1}):
        token = set_current_tenant(t["id"])
        try:
            db = get_db()
            cfg = await get_report_config(db)
            if not cfg["enabled"]:
                continue
            already = await raw.monthly_report_log.find_one(
                {"tenant_id": t["id"], "month": key, "status": STATUS_SENT})
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
                dataset = await aggregate_month(db, year, month)
                pdf = monthly_driver_report_to_pdf(dataset, tenant_name)
                xlsx = monthly_driver_report_to_xlsx(dataset, tenant_name)
                subject, text, html = _email_bodies(tenant_name, dataset)
                ok = await emailer.send_email_with_attachments(
                    recipients, subject, text, html,
                    [(f"rapport_mensuel_fiscal_chauffeurs_{key}.pdf", pdf, "application", "pdf"),
                     (f"rapport_mensuel_fiscal_chauffeurs_{key}.xlsx", xlsx, "application",
                      "vnd.openxmlformats-officedocument.spreadsheetml.sheet")])
                status = STATUS_SENT if ok else STATUS_ERROR
                error = None if ok else "Échec de l'envoi SMTP"
            await _log_run(raw, t["id"], key, status, recipients, error)
            results[t["id"]] = status
            logger.info("Rapport mensuel %s (%s): %s", key, t["id"], status)
        except Exception as e:
            logger.exception("Rapport mensuel échoué pour tenant %s", t["id"])
            try:
                await _log_run(raw, t["id"], key, STATUS_ERROR, [], str(e)[:300])
            except Exception:
                pass
            results[t["id"]] = STATUS_ERROR
        finally:
            reset_current_tenant(token)
    return results
