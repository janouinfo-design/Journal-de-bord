"""Décomptes & Clôtures carburant — génération, contrôles, clôture, versions.

Période déterminée par la date comptable fournisseur (sinon date de transaction),
convertie dans le fuseau du tenant (Europe/Zurich). La clôture fige montants, taux
et affectations (snapshot de lignes versionné) et verrouille les transactions.
"""
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TENANT_TZ = ZoneInfo("Europe/Zurich")
STATEMENT_STATUSES = ("draft", "to_review", "validated", "closed")

STATUS_LABEL = {"draft": "Brouillon", "to_review": "À contrôler",
                "validated": "Validé", "closed": "Clôturé"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def basis_date_of(tx: dict) -> tuple[str, str]:
    """(date locale YYYY-MM-DD réellement utilisée, base 'accounting'|'transaction')."""
    raw = tx.get("accounting_date") or tx.get("tx_datetime")
    basis = "accounting" if tx.get("accounting_date") else "transaction"
    d = datetime.fromisoformat(raw)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(TENANT_TZ).date().isoformat(), basis


def line_issues(tx: dict) -> tuple[list[str], list[str]]:
    """(bloquants, avertissements) pour une transaction."""
    blockers, warnings = [], []
    if tx.get("match_status") == "unmatched":
        blockers.append("Non rapprochée")
    if tx.get("fx_status") == "pending":
        blockers.append("Conversion en attente")
    if tx.get("match_status") == "matched_review":
        warnings.append("Contrôle recommandé")
    return blockers, warnings


async def next_statement_number(db) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"DEC-{year}-"
    last = await db.fuel_statements.find_one(
        {"number": {"$regex": f"^{prefix}"}}, {"_id": 0, "number": 1},
        sort=[("number", -1)])
    n = 1
    if last and last.get("number"):
        try:
            n = int(last["number"].split("-")[-1]) + 1
        except ValueError:
            n = 1
    return f"{prefix}{n:04d}"


async def closed_overlap(db, date_from: str, date_to: str, exclude_id: str | None = None):
    q = {"status": "closed", "date_from": {"$lte": date_to}, "date_to": {"$gte": date_from}}
    if exclude_id:
        q["id"] = {"$ne": exclude_id}
    return await db.fuel_statements.find_one(q, {"_id": 0, "id": 1, "number": 1,
                                                 "date_from": 1, "date_to": 1})


async def build_lines(db, date_from: str, date_to: str, include_carried_over: bool = True):
    """Lignes du décompte : période + reportées/tardives antérieures non clôturées."""
    vehicles = {v["id"]: v for v in await db.vehicles.find({}, {"_id": 0, "id": 1, "plate": 1}).to_list(2000)}
    drivers = {d["id"]: d for d in await db.drivers.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)}
    txs = await db.fuel_transactions.find(
        {"$or": [{"statement_id": None}, {"statement_id": {"$exists": False}}]},
        {"_id": 0}).to_list(50000)
    lines = []
    for tx in txs:
        bd, basis = basis_date_of(tx)
        if bd > date_to:
            continue
        if bd >= date_from:
            section = "period"
        elif include_carried_over:
            section = "carried_over"
        else:
            continue
        blockers, warnings = line_issues(tx)
        lines.append({
            "id": str(uuid.uuid4()),
            "transaction_id": tx["id"],
            "section": section,
            "basis_date": bd, "basis": basis,
            "tx_datetime": tx.get("tx_datetime"), "accounting_date": tx.get("accounting_date"),
            "provider": tx.get("provider"), "card_last4": tx.get("card_last4"),
            "station_name": tx.get("station_name"), "country": tx.get("country"),
            "product_type": tx.get("product_type"),
            "quantity": tx.get("quantity"), "unit": tx.get("unit"),
            "amount_total": tx.get("amount_total"), "currency": tx.get("currency") or "CHF",
            "vat_amount": tx.get("vat_amount"),
            "fx_rate": tx.get("fx_rate"), "fx_rate_date": tx.get("fx_rate_date"),
            "fx_source": tx.get("fx_source"), "fx_status": tx.get("fx_status"),
            "amount_chf": tx.get("amount_chf"),
            "vehicle_id": tx.get("vehicle_id"),
            "vehicle_plate": vehicles.get(tx.get("vehicle_id"), {}).get("plate"),
            "driver_id": tx.get("driver_id"),
            "driver_name": drivers.get(tx.get("driver_id"), {}).get("name"),
            "trip_id": tx.get("trip_id"),
            "classification": tx.get("classification") or "unclassified",
            "match_status": tx.get("match_status"),
            "match_score": tx.get("match_score"),
            "source": tx.get("source"),
            "blockers": blockers, "warnings": warnings,
        })
    lines.sort(key=lambda x: (x["section"] != "period", x["basis_date"]))
    return lines


def compute_totals(lines: list[dict]) -> dict:
    t = {"tx_count": len(lines), "amount_chf_total": 0.0,
         "liters": 0.0, "kwh": 0.0,
         "pro_chf": 0.0, "perso_chf": 0.0, "unclassified_chf": 0.0,
         "carried_over_count": sum(1 for l in lines if l["section"] == "carried_over"),
         "amounts_by_currency": {}}
    by_vehicle, by_driver = {}, {}
    blockers = {"unmatched": {"count": 0, "amount_chf": 0.0},
                "fx_pending": {"count": 0, "amounts_by_currency": {}},
                "review": {"count": 0}}
    for l in lines:
        chf = l.get("amount_chf")
        cur = l.get("currency") or "CHF"
        t["amounts_by_currency"][cur] = round(
            t["amounts_by_currency"].get(cur, 0) + (l.get("amount_total") or 0), 2)
        if chf is not None:
            t["amount_chf_total"] += chf
            cl = l.get("classification")
            key = {"professional": "pro_chf", "personal": "perso_chf"}.get(cl, "unclassified_chf")
            t[key] += chf
        if l.get("quantity"):
            if l.get("unit") == "kWh":
                t["kwh"] += l["quantity"]
            elif l.get("unit") == "L":
                t["liters"] += l["quantity"]
        if "Non rapprochée" in l["blockers"]:
            blockers["unmatched"]["count"] += 1
            if chf is not None:
                blockers["unmatched"]["amount_chf"] = round(blockers["unmatched"]["amount_chf"] + chf, 2)
        if "Conversion en attente" in l["blockers"]:
            blockers["fx_pending"]["count"] += 1
            blockers["fx_pending"]["amounts_by_currency"][cur] = round(
                blockers["fx_pending"]["amounts_by_currency"].get(cur, 0) + (l.get("amount_total") or 0), 2)
        if l["warnings"]:
            blockers["review"]["count"] += 1
        for key_id, name, agg in ((l.get("vehicle_id"), l.get("vehicle_plate"), by_vehicle),
                                  (l.get("driver_id"), l.get("driver_name"), by_driver)):
            k = key_id or "__none__"
            row = agg.setdefault(k, {"id": key_id, "label": name or "Non attribué",
                                     "tx_count": 0, "liters": 0.0, "kwh": 0.0,
                                     "amount_chf": 0.0, "pro_chf": 0.0, "perso_chf": 0.0})
            row["tx_count"] += 1
            if l.get("quantity"):
                if l.get("unit") == "kWh":
                    row["kwh"] += l["quantity"]
                elif l.get("unit") == "L":
                    row["liters"] += l["quantity"]
            if chf is not None:
                row["amount_chf"] += chf
                if l.get("classification") == "professional":
                    row["pro_chf"] += chf
                elif l.get("classification") == "personal":
                    row["perso_chf"] += chf
    for agg in (by_vehicle, by_driver):
        for row in agg.values():
            for k in ("liters", "kwh", "amount_chf", "pro_chf", "perso_chf"):
                row[k] = round(row[k], 2)
    for k in ("amount_chf_total", "liters", "kwh", "pro_chf", "perso_chf", "unclassified_chf"):
        t[k] = round(t[k], 2)
    blockers["unmatched"]["amount_chf"] = round(blockers["unmatched"]["amount_chf"], 2)
    blockers["total_count"] = blockers["unmatched"]["count"] + blockers["fx_pending"]["count"]
    t["by_vehicle"] = sorted(by_vehicle.values(), key=lambda x: -x["amount_chf"])
    t["by_driver"] = sorted(by_driver.values(), key=lambda x: -x["amount_chf"])
    t["blockers"] = blockers
    return t


async def persist_lines(db, statement_id: str, version: int, lines: list[dict]):
    await db.fuel_statement_lines.delete_many({"statement_id": statement_id, "version": version})
    if lines:
        await db.fuel_statement_lines.insert_many(
            [{**l, "statement_id": statement_id, "version": version} for l in lines])


async def refresh_statement(db, stmt: dict) -> dict:
    """Régénère lignes + totaux depuis les données actuelles (états non clôturés)."""
    lines = await build_lines(db, stmt["date_from"], stmt["date_to"],
                              stmt.get("include_carried_over", True))
    totals = compute_totals(lines)
    await persist_lines(db, stmt["id"], stmt["version"], lines)
    await db.fuel_statements.update_one(
        {"id": stmt["id"]},
        {"$set": {"totals": totals, "refreshed_at": _now(), "updated_at": _now()}})
    return totals


async def get_lines(db, statement_id: str, version: int):
    return await db.fuel_statement_lines.find(
        {"statement_id": statement_id, "version": version},
        {"_id": 0, "tenant_id": 0}).to_list(50000)


async def late_transactions(db, stmt: dict) -> list[dict]:
    """Transactions tardives : arrivées après clôture, période concernée, non incluses."""
    if stmt.get("status") != "closed":
        return []
    lines = await build_lines(db, stmt["date_from"], stmt["date_to"], include_carried_over=False)
    return [l for l in lines if l["section"] == "period"]


async def ensure_statement_indexes(db):
    await db.fuel_statements.create_index([("tenant_id", 1), ("status", 1)])
    await db.fuel_statements.create_index([("tenant_id", 1), ("number", 1)])
    await db.fuel_statement_lines.create_index(
        [("tenant_id", 1), ("statement_id", 1), ("version", 1)])
