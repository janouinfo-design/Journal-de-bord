"""Taux de change BCE (eurofxref) — récupération publique, stockage global, conversion CHF.

Les taux BCE sont base EUR (unités de devise pour 1 EUR) :
  montant_CHF = montant × taux(CHF, date) / taux(devise, date)
Week-end/férié : dernier taux antérieur disponible. Aucun taux → statut « pending ».
Les transactions verrouillées (décomptes clôturés) ne sont JAMAIS recalculées.
"""
import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

ECB_90D = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
_NS = {"ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
_UA = "Logitrak-Journal FX Sync/1.0"
FX_STATE_ID = "fuel_fx"


async def _fetch_xml(url: str) -> str:
    headers = {"User-Agent": _UA, "Accept": "application/xml,text/xml"}
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
        for attempt in range(3):
            try:
                r = await client.get(url)
                r.raise_for_status()
                return r.text
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)


def parse_ecb_xml(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    rows = []
    for day in root.findall(".//ecb:Cube[@time]", _NS):
        d = day.attrib["time"]
        for c in day.findall("ecb:Cube", _NS):
            rows.append({"date": d, "currency": c.attrib["currency"],
                         "rate_per_eur": float(c.attrib["rate"])})
    return rows


async def sync_ecb_rates(raw_db) -> dict:
    """Récupère les ~90 derniers jours de taux BCE et les upsert (collection globale)."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        xml_text = await _fetch_xml(ECB_90D)
        rows = parse_ecb_xml(xml_text)
    except Exception as e:
        await raw_db.app_state.update_one(
            {"id": FX_STATE_ID},
            {"$set": {"last_attempt_at": now, "last_error": str(e)}}, upsert=True)
        logger.exception("Sync taux BCE échouée")
        return {"ok": False, "error": str(e)}
    if not rows:
        await raw_db.app_state.update_one(
            {"id": FX_STATE_ID},
            {"$set": {"last_attempt_at": now, "last_error": "Flux BCE vide"}}, upsert=True)
        return {"ok": False, "error": "Flux BCE vide"}
    for r in rows:
        await raw_db.fuel_exchange_rates.update_one(
            {"date": r["date"], "currency": r["currency"]},
            {"$set": {**r, "source": "ECB", "fetched_at": now}}, upsert=True)
    latest = max(r["date"] for r in rows)
    await raw_db.app_state.update_one(
        {"id": FX_STATE_ID},
        {"$set": {"last_success_at": now, "last_attempt_at": now, "last_error": None,
                  "latest_rate_date": latest, "source_url": ECB_90D}}, upsert=True)
    return {"ok": True, "upserted": len(rows), "latest_rate_date": latest}


async def _latest_rate(db, currency: str, date_str: str):
    return await db.fuel_exchange_rates.find_one(
        {"currency": currency, "date": {"$lte": date_str}},
        {"_id": 0}, sort=[("date", -1)])


async def compute_fx(db, amount_total, currency: str, tx_datetime: str) -> dict:
    cur = (currency or "CHF").upper()
    if cur == "CHF":
        return {"amount_chf": round(float(amount_total), 2), "fx_rate": 1.0,
                "fx_rate_date": None, "fx_source": "none", "fx_status": "not_needed"}
    d = (tx_datetime or "")[:10]
    pending = {"amount_chf": None, "fx_rate": None, "fx_rate_date": None,
               "fx_source": None, "fx_status": "pending"}
    if not d:
        return pending
    if cur == "EUR":
        chf = await _latest_rate(db, "CHF", d)
        if not chf:
            return pending
        rate, rate_date = chf["rate_per_eur"], chf["date"]
    else:
        r_cur = await _latest_rate(db, cur, d)
        if not r_cur:
            return pending
        chf = await db.fuel_exchange_rates.find_one(
            {"currency": "CHF", "date": r_cur["date"]}, {"_id": 0}) \
            or await _latest_rate(db, "CHF", r_cur["date"])
        if not chf:
            return pending
        rate, rate_date = chf["rate_per_eur"] / r_cur["rate_per_eur"], r_cur["date"]
    return {"amount_chf": round(float(amount_total) * rate, 2),
            "fx_rate": round(rate, 6), "fx_rate_date": rate_date,
            "fx_source": "ecb", "fx_status": "converted"}


async def convert_pending(raw_db) -> dict:
    """Convertit les transactions en attente. Ne touche JAMAIS les transactions verrouillées."""
    q = {"locked": {"$ne": True},
         "$or": [{"fx_status": "pending"},
                 {"fx_status": {"$exists": False}, "amount_chf": None}]}
    txs = await raw_db.fuel_transactions.find(
        q, {"_id": 0, "id": 1, "amount_total": 1, "currency": 1,
            "tx_datetime": 1, "fx_status": 1}).to_list(10000)
    converted = 0
    for tx in txs:
        fx = await compute_fx(raw_db, tx.get("amount_total") or 0, tx.get("currency"), tx.get("tx_datetime"))
        if fx["fx_status"] == "pending" and tx.get("fx_status") == "pending":
            continue
        await raw_db.fuel_transactions.update_one(
            {"id": tx["id"]},
            {"$set": {**fx, "updated_at": datetime.now(timezone.utc).isoformat()}})
        if fx["fx_status"] in ("converted", "not_needed"):
            converted += 1
    return {"checked": len(txs), "converted": converted}


async def ensure_fx_indexes(raw_db):
    await raw_db.fuel_exchange_rates.create_index([("currency", 1), ("date", -1)])
    await raw_db.fuel_exchange_rates.create_index([("date", 1), ("currency", 1)], unique=True)
