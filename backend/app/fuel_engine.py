"""Moteur Carburant — empreinte carte (HMAC), anti-doublons, rattachement + score explicable.

Phase 1 : règles 1 (affectation carte), 2 (véhicule fourni), 3 (chauffeur nominatif),
5 simplifiée (trajets proches via start/end des trips). Score sur 100, décomposé
point par point, seuils configurables par tenant.
"""
import hashlib
import hmac
import math
import os
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_FUEL_SETTINGS = {
    "id": "fuel",
    "station_radius_m": 500,
    "score_auto": 90,
    "score_review": 70,
    "time_window_min": 120,
    "allocation_mode": "A",  # A = coût rattaché à l'événement, B = répartition (Phase 2)
    "providers": ["Shell", "UTA", "DKV", "Migrol", "AVIA", "Agrola", "Routex", "BP", "Eni", "Socar", "Autre"],
    "anomalies": {
        "tank_enabled": True,
        "tank_tolerance_pct": 100,
        "card_enabled": True,
        "double_enabled": True,
        "double_window_min": 60,
        "amount_enabled": True,
        "amount_multiplier": 3.0,
        "amount_min_history": 5,
    },
    "weights": {
        "card_assigned_vehicle": 50,
        "vehicle_hint": 40,
        "vehicle_near_station": 30,
        "driver_on_vehicle": 20,
        "trip_time_compatible": 15,
        "fuel_type_compatible": 10,
        "fuel_type_incompatible": -40,
        "card_inactive_or_expired": -50,
    },
}

PRODUCT_TYPES = ("diesel", "essence", "adblue", "electric", "other")
UNITS = ("L", "kWh", "unit")
CARD_STATUSES = ("active", "suspended", "expired", "blocked", "replaced")
MATCH_STATUSES = ("auto_matched", "matched_review", "unmatched", "manual")

_FUEL_COMPAT = {
    "diesel": {"diesel", "adblue", "other"},
    "essence": {"essence", "other"},
    "electric": {"electric", "other"},
    "hybrid": {"essence", "diesel", "electric", "other"},
}


def _hmac_secret() -> bytes:
    return os.environ["FUEL_CARD_HMAC_SECRET"].encode()


def card_fingerprint(card_number: str) -> str:
    """Empreinte HMAC-SHA256 non réversible du numéro complet (jamais stocké)."""
    normalized = "".join(c for c in card_number if c.isalnum()).upper()
    return hmac.new(_hmac_secret(), normalized.encode(), hashlib.sha256).hexdigest()


def dedup_key(tenant_id: str, card_ref: str, tx_datetime: str, station: str,
              quantity, amount, currency: str) -> str:
    raw = f"{tenant_id}|{card_ref}|{tx_datetime}|{(station or '').strip().lower()}|{quantity}|{amount}|{(currency or '').upper()}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def get_fuel_settings(db) -> dict:
    doc = await db.settings.find_one({"id": "fuel"}, {"_id": 0}) or {}
    merged = {**DEFAULT_FUEL_SETTINGS, **doc}
    merged["weights"] = {**DEFAULT_FUEL_SETTINGS["weights"], **(doc.get("weights") or {})}
    merged["anomalies"] = {**DEFAULT_FUEL_SETTINGS["anomalies"], **(doc.get("anomalies") or {})}
    return merged


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse_dt(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


async def _active_assignment(db, card_id: str, at: datetime, a_type: str):
    rows = await db.fuel_card_assignments.find(
        {"card_id": card_id, "type": a_type}, {"_id": 0}).to_list(50)
    for a in rows:
        vf = _parse_dt(a["valid_from"]) if a.get("valid_from") else None
        vt = _parse_dt(a["valid_to"]) if a.get("valid_to") else None
        if (vf is None or vf <= at) and (vt is None or at <= vt):
            return a
    return None


async def match_transaction(db, tx: dict, settings: dict | None = None) -> dict:
    """Applique les règles de rattachement, retourne le résultat explicable."""
    settings = settings or await get_fuel_settings(db)
    w = settings["weights"]
    window = timedelta(minutes=settings.get("time_window_min", 120))
    radius = settings.get("station_radius_m", 500)
    at = _parse_dt(tx["tx_datetime"])

    breakdown = []          # [{rule, label, points}]
    candidates = {}         # vehicle_id -> partial score
    vehicle_id = None
    driver_id = tx.get("driver_id")
    trip_id = None
    method = None

    card = await db.fuel_cards.find_one({"id": tx.get("card_id")}, {"_id": 0}) if tx.get("card_id") else None

    # Règle 1 — carte affectée à un véhicule au moment de la transaction
    if card:
        assignment = await _active_assignment(db, card["id"], at, "vehicle")
        if assignment and assignment.get("vehicle_id"):
            vehicle_id = assignment["vehicle_id"]
            method = "card_assignment"
            breakdown.append({"rule": "card_assigned_vehicle",
                              "label": "Carte affectée à ce véhicule au moment du plein",
                              "points": w["card_assigned_vehicle"]})

    # Règle 2 — identifiant véhicule fourni (plaque / hint de l'import)
    if not vehicle_id and tx.get("vehicle_hint"):
        hint = str(tx["vehicle_hint"]).strip().lower().replace(" ", "")
        vehicles = await db.vehicles.find({}, {"_id": 0, "id": 1, "plate": 1}).to_list(1000)
        for v in vehicles:
            if v.get("plate", "").lower().replace(" ", "") == hint or v["id"] == tx["vehicle_hint"]:
                vehicle_id = v["id"]
                method = "provider_vehicle"
                breakdown.append({"rule": "vehicle_hint",
                                  "label": f"Véhicule fourni par le relevé ({v.get('plate')})",
                                  "points": w["vehicle_hint"]})
                break

    # Règle 3 — carte nominative : véhicule conduit par le chauffeur à l'heure du plein
    if card and not driver_id:
        d_assign = await _active_assignment(db, card["id"], at, "driver")
        if d_assign and d_assign.get("driver_id"):
            driver_id = d_assign["driver_id"]
    if driver_id:
        trips = await db.trips.find(
            {"driver_id": driver_id,
             "start_time": {"$lte": (at + window).isoformat()},
             "end_time": {"$gte": (at - window).isoformat()}},
            {"_id": 0, "id": 1, "vehicle_id": 1, "start_time": 1, "end_time": 1}).to_list(20)
        if trips:
            t0 = trips[0]
            if not vehicle_id:
                vehicle_id = t0.get("vehicle_id")
                method = method or "driver_trip"
            if vehicle_id and t0.get("vehicle_id") == vehicle_id:
                breakdown.append({"rule": "driver_on_vehicle",
                                  "label": "Chauffeur associé conduisait ce véhicule",
                                  "points": w["driver_on_vehicle"]})

    # Règle 5 (simplifiée Phase 1) — trajets proches de la station (start/end)
    if tx.get("station_lat") is not None and tx.get("station_lng") is not None:
        q = {"start_time": {"$lte": (at + window).isoformat()},
             "end_time": {"$gte": (at - window - timedelta(hours=1)).isoformat()}}
        trips = await db.trips.find(q, {"_id": 0, "id": 1, "vehicle_id": 1, "start_time": 1,
                                        "end_time": 1, "start_lat": 1, "start_lng": 1,
                                        "end_lat": 1, "end_lng": 1}).to_list(500)
        for t in trips:
            dists = []
            if t.get("start_lat") is not None:
                dists.append(_haversine_m(tx["station_lat"], tx["station_lng"], t["start_lat"], t["start_lng"]))
            if t.get("end_lat") is not None:
                dists.append(_haversine_m(tx["station_lat"], tx["station_lng"], t["end_lat"], t["end_lng"]))
            if dists and min(dists) <= radius:
                vid = t.get("vehicle_id")
                if vid:
                    candidates[vid] = candidates.get(vid, 0) + w["vehicle_near_station"]
                if vehicle_id and vid == vehicle_id:
                    if not any(b["rule"] == "vehicle_near_station" for b in breakdown):
                        breakdown.append({"rule": "vehicle_near_station",
                                          "label": f"Véhicule vu à moins de {radius} m de la station",
                                          "points": w["vehicle_near_station"]})
                    if t["start_time"] <= tx["tx_datetime"] <= t["end_time"]:
                        if not any(b["rule"] == "trip_time_compatible" for b in breakdown):
                            trip_id = t["id"]
                            breakdown.append({"rule": "trip_time_compatible",
                                              "label": "Trajet en cours à l'heure de la transaction",
                                              "points": w["trip_time_compatible"]})
                elif not vehicle_id and vid:
                    candidates[vid] = candidates.get(vid, 0)
        # aucun véhicule encore trouvé mais un seul candidat géographique net
        if not vehicle_id and len(candidates) == 1:
            vehicle_id = next(iter(candidates))
            method = "geo_single_candidate"
            breakdown.append({"rule": "vehicle_near_station",
                              "label": f"Seul véhicule présent à moins de {radius} m de la station",
                              "points": w["vehicle_near_station"]})

    # Rattachement trajet (si véhicule connu et pas encore de trajet)
    if vehicle_id and not trip_id:
        t = await db.trips.find_one(
            {"vehicle_id": vehicle_id,
             "start_time": {"$lte": tx["tx_datetime"]},
             "end_time": {"$gte": tx["tx_datetime"]}},
            {"_id": 0, "id": 1})
        if t:
            trip_id = t["id"]
            breakdown.append({"rule": "trip_time_compatible",
                              "label": "Trajet en cours à l'heure de la transaction",
                              "points": w["trip_time_compatible"]})

    # Compatibilité carburant
    if vehicle_id and tx.get("product_type"):
        v = await db.vehicles.find_one({"id": vehicle_id}, {"_id": 0, "fuel_type": 1})
        vft = (v or {}).get("fuel_type")
        if vft:
            if tx["product_type"] in _FUEL_COMPAT.get(vft, set()):
                breakdown.append({"rule": "fuel_type_compatible",
                                  "label": f"Type de carburant compatible ({tx['product_type']} / {vft})",
                                  "points": w["fuel_type_compatible"]})
            else:
                breakdown.append({"rule": "fuel_type_incompatible",
                                  "label": f"Carburant incompatible ({tx['product_type']} pour véhicule {vft})",
                                  "points": w["fuel_type_incompatible"]})

    # Pénalité carte inactive / expirée au moment de la transaction
    if card:
        expired = card.get("expires_at") and tx["tx_datetime"][:10] > card["expires_at"][:10]
        if card.get("status") != "active" or expired:
            breakdown.append({"rule": "card_inactive_or_expired",
                              "label": "Carte non active ou expirée au moment de la transaction",
                              "points": w["card_inactive_or_expired"]})

    score = max(0, min(100, sum(b["points"] for b in breakdown)))
    if not vehicle_id:
        status = "unmatched"
    elif score >= settings["score_auto"]:
        status = "auto_matched"
    elif score >= settings["score_review"]:
        status = "matched_review"
    else:
        status = "unmatched"

    # classification héritée du trajet
    classification = "unclassified"
    if trip_id:
        t = await db.trips.find_one({"id": trip_id}, {"_id": 0, "classification": 1})
        c = (t or {}).get("classification")
        classification = {"professional": "professional", "personal": "personal"}.get(c, "unclassified")

    cand_list = sorted(
        [{"vehicle_id": k, "partial_score": v} for k, v in candidates.items()],
        key=lambda x: -x["partial_score"])[:10]

    return {
        "vehicle_id": vehicle_id,
        "driver_id": driver_id,
        "trip_id": trip_id,
        "classification": classification,
        "match_status": status,
        "match_score": score,
        "breakdown": breakdown,
        "candidates": cand_list,
        "method": method,
    }


async def apply_match(db, tx: dict, settings: dict | None = None) -> dict:
    """Calcule et persiste le rattachement d'une transaction (hors attributions manuelles)."""
    result = await match_transaction(db, tx, settings)
    now = datetime.now(timezone.utc).isoformat()
    await db.fuel_transactions.update_one(
        {"id": tx["id"]},
        {"$set": {"vehicle_id": result["vehicle_id"], "driver_id": result["driver_id"],
                  "trip_id": result["trip_id"], "classification": result["classification"],
                  "match_status": result["match_status"], "match_score": result["match_score"],
                  "updated_at": now}})
    await db.fuel_transaction_matches.update_one(
        {"transaction_id": tx["id"]},
        {"$set": {"transaction_id": tx["id"], "score": result["match_score"],
                  "status": result["match_status"], "breakdown": result["breakdown"],
                  "candidates": result["candidates"], "method": result["method"],
                  "computed_at": now},
         "$setOnInsert": {"id": str(uuid.uuid4())},
         "$push": {"history": {"at": now, "score": result["match_score"],
                               "status": result["match_status"], "by": "auto"}}},
        upsert=True)
    return result


async def ensure_fuel_indexes(db):
    """Index Phase 1 — appelé au démarrage (idempotent)."""
    await db.fuel_transactions.create_index(
        [("tenant_id", 1), ("provider", 1), ("external_transaction_id", 1)],
        unique=True,
        partialFilterExpression={"external_transaction_id": {"$type": "string"}})
    await db.fuel_transactions.create_index([("tenant_id", 1), ("dedup_key", 1)])
    await db.fuel_transactions.create_index([("tenant_id", 1), ("tx_datetime", -1)])
    await db.fuel_transactions.create_index([("tenant_id", 1), ("card_id", 1)])
    await db.fuel_transactions.create_index([("tenant_id", 1), ("vehicle_id", 1)])
    await db.fuel_transactions.create_index([("tenant_id", 1), ("driver_id", 1)])
    await db.fuel_transactions.create_index([("tenant_id", 1), ("match_status", 1)])
    await db.fuel_cards.create_index(
        [("tenant_id", 1), ("fingerprint", 1)], unique=True,
        partialFilterExpression={"fingerprint": {"$type": "string"}})
    await db.fuel_cards.create_index([("tenant_id", 1), ("status", 1)])
    await db.fuel_card_assignments.create_index([("tenant_id", 1), ("card_id", 1)])
    await db.fuel_import_rows.create_index([("tenant_id", 1), ("job_id", 1)])
