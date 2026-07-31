"""Alertes anomalies carburant — détection serveur, explications précises, dédup.

4 règles, toutes pilotées par les seuils configurables du tenant (settings.anomalies),
aucune valeur métier en dur. Données manquantes → règle muette (jamais de valeur fictive).
Dédup stricte : une seule anomalie par (transaction, type), jamais recréée après décision.
"""
import uuid
from datetime import datetime, timedelta, timezone
from statistics import median

ANOMALY_SEVERITY = {
    "tank_overflow": "critical",
    "card_inactive": "critical",
    "double_fill": "warning",
    "amount_unusual": "warning",
}
ANOMALY_STATUSES = ("open", "justified", "corrected", "rejected")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _card_status_at(card: dict, tx_datetime: str) -> str:
    """Statut de la carte au moment de la transaction (historique daté)."""
    changes = sorted((h["at"], h["after"]) for h in card.get("history", [])
                     if h.get("action") == "status" and h.get("at") and h.get("after"))
    status = "active"
    for at, after in changes:
        if at <= tx_datetime:
            status = after
        else:
            break
    return status


async def _exists(db, tx_id: str, atype: str) -> bool:
    return await db.fuel_anomalies.find_one(
        {"transaction_id": tx_id, "type": atype}, {"_id": 0, "id": 1}) is not None


async def _create(db, atype: str, tx: dict, explanation: str, context: dict,
                  related_tx_id: str | None = None) -> dict:
    doc = {
        "id": str(uuid.uuid4()), "type": atype,
        "severity": ANOMALY_SEVERITY[atype], "status": "open",
        "transaction_id": tx["id"], "related_transaction_id": related_tx_id,
        "vehicle_id": tx.get("vehicle_id"), "card_id": tx.get("card_id"),
        "explanation": explanation, "context": context,
        "detected_at": _now(),
        "decided_by": None, "decided_at": None, "decision_reason": None,
    }
    await db.fuel_anomalies.insert_one(dict(doc))
    return doc


async def _check_tank(db, tx, cfg, vehicles) -> bool:
    if not cfg.get("tank_enabled", True):
        return False
    qty, unit = tx.get("quantity"), tx.get("unit")
    veh = vehicles.get(tx.get("vehicle_id"))
    if not qty or not veh:
        return False
    cap_key, cap_label = ("tank_capacity_l", "réservoir") if unit == "L" \
        else ("battery_capacity_kwh", "batterie") if unit == "kWh" else (None, None)
    cap = (veh or {}).get(cap_key) if cap_key else None
    if not cap:
        return False  # capacité inconnue → aucune alerte
    tol = float(cfg.get("tank_tolerance_pct", 100))
    limit = cap * tol / 100.0
    if qty <= limit:
        return False
    if await _exists(db, tx["id"], "tank_overflow"):
        return False
    await _create(db, "tank_overflow", tx,
                  f"{qty:g} {unit} relevés pour une capacité de {cap_label} de {cap:g} {unit} "
                  f"sur {veh.get('plate') or 'le véhicule'} (tolérance {tol:g} %, limite {limit:g} {unit}).",
                  {"quantity": qty, "unit": unit, "capacity": cap,
                   "tolerance_pct": tol, "limit": round(limit, 2)})
    return True


async def _check_card(db, tx, cfg, cards_cache) -> bool:
    if not cfg.get("card_enabled", True):
        return False
    card_id = tx.get("card_id")
    if not card_id:
        return False
    card = cards_cache.get(card_id)
    if card is None:
        card = await db.fuel_cards.find_one(
            {"id": card_id}, {"_id": 0, "status": 1, "history": 1, "last4": 1}) or {}
        cards_cache[card_id] = card
    status_at = _card_status_at(card, tx.get("tx_datetime") or "")
    if status_at == "active":
        return False
    if await _exists(db, tx["id"], "card_inactive"):
        return False
    label = {"suspended": "suspendue", "expired": "expirée",
             "blocked": "bloquée", "replaced": "remplacée"}.get(status_at, status_at)
    await _create(db, "card_inactive", tx,
                  f"Transaction effectuée avec la carte •••• {card.get('last4') or '????'} "
                  f"alors qu'elle était {label} au moment du plein.",
                  {"card_status_at_tx": status_at, "card_last4": card.get("last4")})
    return True


async def _check_double(db, tx, cfg) -> bool:
    if not cfg.get("double_enabled", True):
        return False
    if not tx.get("tx_datetime") or not (tx.get("card_id") or tx.get("vehicle_id")):
        return False
    window = int(cfg.get("double_window_min", 60))
    t0 = _dt(tx["tx_datetime"])
    lo, hi = (t0 - timedelta(minutes=window)).isoformat(), (t0 + timedelta(minutes=window)).isoformat()
    ors = []
    if tx.get("card_id"):
        ors.append({"card_id": tx["card_id"]})
    if tx.get("vehicle_id"):
        ors.append({"vehicle_id": tx["vehicle_id"]})
    other = await db.fuel_transactions.find_one(
        {"id": {"$ne": tx["id"]}, "tx_datetime": {"$gte": lo, "$lte": hi}, "$or": ors},
        {"_id": 0, "id": 1, "tx_datetime": 1, "station_name": 1, "card_id": 1, "vehicle_id": 1})
    if not other:
        return False
    if await _exists(db, tx["id"], "double_fill") or await _exists(db, other["id"], "double_fill"):
        return False
    delta_min = abs(int((_dt(other["tx_datetime"]) - t0).total_seconds() / 60))
    same_card = tx.get("card_id") and tx.get("card_id") == other.get("card_id")
    link = "la même carte" if same_card else "le même véhicule"
    s1, s2 = tx.get("station_name") or "station inconnue", other.get("station_name") or "station inconnue"
    diff_station = s1 != s2
    await _create(db, "double_fill", tx,
                  f"Deux pleins à {delta_min} min d'intervalle avec {link} "
                  f"({'stations différentes : ' + s1 + ' / ' + s2 if diff_station else 'même station : ' + s1}) "
                  f"— fenêtre de détection : {window} min.",
                  {"interval_min": delta_min, "window_min": window,
                   "same_card": bool(same_card), "different_stations": diff_station,
                   "stations": [s1, s2]},
                  related_tx_id=other["id"])
    return True


async def _check_amount(db, tx, cfg) -> bool:
    if not cfg.get("amount_enabled", True):
        return False
    amount = tx.get("amount_chf")
    if amount is None or not tx.get("vehicle_id") or not tx.get("tx_datetime"):
        return False  # pas de CHF fiable ou pas d'historique véhicule → muette
    min_hist = int(cfg.get("amount_min_history", 5))
    mult = float(cfg.get("amount_multiplier", 3.0))
    hist = await db.fuel_transactions.find(
        {"vehicle_id": tx["vehicle_id"], "id": {"$ne": tx["id"]},
         "tx_datetime": {"$lt": tx["tx_datetime"]}, "amount_chf": {"$ne": None}},
        {"_id": 0, "amount_chf": 1}).sort("tx_datetime", -1).to_list(50)
    if len(hist) < min_hist:
        return False
    med = median(h["amount_chf"] for h in hist)
    if med <= 0 or amount <= med * mult:
        return False
    if await _exists(db, tx["id"], "amount_unusual"):
        return False
    await _create(db, "amount_unusual", tx,
                  f"Montant de {amount:.2f} CHF, soit {amount / med:.1f}× la médiane historique "
                  f"du véhicule ({med:.2f} CHF sur {len(hist)} transactions ; "
                  f"seuil : {mult:g}× la médiane).",
                  {"amount_chf": amount, "median_chf": round(med, 2),
                   "history_count": len(hist), "multiplier": mult})
    return True


async def detect_transactions(db, settings: dict, txs: list[dict]) -> int:
    """Applique les 4 règles à une liste de transactions. Retourne le nb d'alertes créées."""
    cfg = settings.get("anomalies") or {}
    vehicles = {v["id"]: v for v in await db.vehicles.find(
        {}, {"_id": 0, "id": 1, "plate": 1, "tank_capacity_l": 1, "battery_capacity_kwh": 1}).to_list(2000)}
    cards_cache = {}
    created = 0
    for tx in txs:
        for check in (_check_tank, _check_card, _check_double, _check_amount):
            if check is _check_tank:
                ok = await _check_tank(db, tx, cfg, vehicles)
            elif check is _check_card:
                ok = await _check_card(db, tx, cfg, cards_cache)
            elif check is _check_double:
                ok = await _check_double(db, tx, cfg)
            else:
                ok = await _check_amount(db, tx, cfg)
            created += 1 if ok else 0
    return created


async def run_full_scan(db, settings: dict) -> int:
    txs = await db.fuel_transactions.find({}, {"_id": 0}).sort("tx_datetime", 1).to_list(20000)
    return await detect_transactions(db, settings, txs)


async def detect_for_tx_ids(db, settings: dict, tx_ids: list[str]) -> int:
    if not tx_ids:
        return 0
    txs = await db.fuel_transactions.find({"id": {"$in": tx_ids}}, {"_id": 0}).to_list(len(tx_ids))
    return await detect_transactions(db, settings, txs)


async def ensure_anomaly_indexes(raw_db):
    await raw_db.fuel_anomalies.create_index(
        [("tenant_id", 1), ("transaction_id", 1), ("type", 1)], unique=True)
    await raw_db.fuel_anomalies.create_index([("tenant_id", 1), ("status", 1), ("severity", 1)])
