"""Seed de démonstration du module Carburant — tenant Logitrak (default).

Usage (dans le conteneur backend) :
    python seed_fuel_demo.py            # crée les données de démo (refuse si déjà présentes)
    python seed_fuel_demo.py --clean    # supprime toutes les données de démo et restaure l'état

Toutes les données sont clairement marquées : stations préfixées « DÉMO »,
cartes fournisseur « DÉMO … », motif « Donnée de démonstration (seed) ».
Utilise les véhicules/chauffeurs EXISTANTS du tenant (rien n'est supprimé au seed).
"""
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

SEED_USER = {"email": "seed-demo@logitrak.ch", "role": "admin", "tenant_id": "default"}
STATE_ID = "fuel_demo_seed"
MARK = "Donnée de démonstration (seed)"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:00")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _mk_card(db, provider: str, number: str, vehicle_id, status_history=None):
    from app.fuel_engine import card_fingerprint
    now = _now()
    card = {
        "id": str(uuid.uuid4()), "provider": provider, "provider_account": None,
        "last4": number[-4:], "fingerprint": card_fingerprint(number),
        "external_card_id": None, "assignment_type": "vehicle",
        "allowed_products": ["diesel", "essence"], "limit_per_tx": None,
        "limit_daily": None, "limit_monthly": None,
        "allowed_countries": [], "allowed_networks": [],
        "activated_at": None, "expires_at": None,
        "status": "active", "replaced_by": None, "notes": MARK,
        "documents": [], "history": [{"at": now, "by": SEED_USER["email"], "action": "create"}],
        "created_at": now, "created_by": SEED_USER["email"], "updated_at": now,
    }
    for at, after in (status_history or []):
        card["history"].append({"at": at, "by": SEED_USER["email"], "action": "status",
                                "before": "active", "after": after, "reason": MARK})
        card["status"] = after
    await db.fuel_cards.insert_one(dict(card))
    if vehicle_id:
        await db.fuel_card_assignments.insert_one({
            "id": str(uuid.uuid4()), "card_id": card["id"], "type": "vehicle",
            "vehicle_id": vehicle_id, "driver_id": None,
            "valid_from": None, "valid_to": None,
            "created_by": SEED_USER["email"], "reason": MARK})
    return card


async def _mk_tx(db, dt: datetime, station: str, country, currency: str, amount: float,
                 qty, card=None, vehicle_hint=None, product="diesel"):
    from app.fuel_engine import apply_match, dedup_key
    from app.fuel_fx import compute_fx
    ts = _iso(dt)
    fx = await compute_fx(db, amount, currency, ts)
    tx = {
        "id": str(uuid.uuid4()), "external_transaction_id": None,
        "provider": (card or {}).get("provider") or "DÉMO",
        "card_id": (card or {}).get("id"), "card_last4": (card or {}).get("last4"),
        "tx_datetime": ts, "accounting_date": None,
        "station_name": station, "station_address": None,
        "country": country, "station_lat": None, "station_lng": None,
        "product_type": product, "quantity": qty, "unit": "L",
        "unit_price": round(amount / qty, 3) if qty else None,
        "amount_net": None, "vat_amount": None, "vat_rate": None,
        "amount_total": amount, "currency": currency, **fx,
        "mileage": None, "vehicle_id": None, "driver_id": None, "trip_id": None,
        "vehicle_hint": vehicle_hint,
        "classification": "unclassified", "match_status": "unmatched", "match_score": None,
        "source": "manual", "invoice_ref": None, "documents": [],
        "comment": MARK, "manual_reason": MARK,
        "dedup_key": dedup_key("default", (card or {}).get("id") or "demo", ts,
                               station, qty, amount, currency),
        "import_job_id": None,
        "created_at": _now(), "created_by": SEED_USER["email"],
        "updated_at": _now(), "updated_by": SEED_USER["email"],
    }
    await db.fuel_transactions.insert_one(dict(tx))
    await apply_match(db, tx)
    return tx["id"]


async def seed():
    from app.audit import log_audit
    from app.db import get_db, get_raw_db, init_db
    from app.fuel_anomalies import detect_for_tx_ids
    from app.fuel_engine import get_fuel_settings
    from app.fuel_fx import sync_ecb_rates
    from app.fuel_statements import next_statement_number, refresh_statement
    from app.tenant_context import set_current_tenant

    init_db()
    set_current_tenant("default")
    db, raw = get_db(), get_raw_db()

    if await raw.fuel_demo_state.find_one({"id": STATE_ID}):
        print("⚠️  Données de démo déjà présentes. Lancez d'abord :  python seed_fuel_demo.py --clean")
        return

    vehicles = await db.vehicles.find({}, {"_id": 0, "id": 1, "plate": 1, "tank_capacity_l": 1}).to_list(10)
    if not vehicles:
        print("❌ Aucun véhicule dans le tenant default. Synchronisez Navixy d'abord "
              "(ou POST /api/livre/bootstrap si la base est totalement vide).")
        return
    veh_a = vehicles[0]
    veh_b = vehicles[1] if len(vehicles) > 1 else vehicles[0]

    capacity_set = None
    if not veh_a.get("tank_capacity_l"):
        await db.vehicles.update_one({"id": veh_a["id"]}, {"$set": {"tank_capacity_l": 60}})
        capacity_set = veh_a["id"]
        print(f"• Capacité réservoir 60 L définie sur {veh_a.get('plate')} (sera retirée au --clean)")
    cap = veh_a.get("tank_capacity_l") or 60

    print("• Synchronisation des taux BCE…")
    try:
        r = await sync_ecb_rates(raw)
        print(f"  taux BCE : {r}")
    except Exception as e:
        print(f"  ⚠️ sync BCE impossible ({e}) — les transactions EUR resteront « conversion en attente »")

    today = datetime.now(timezone.utc).replace(hour=10, minute=0)
    pm_last = today.replace(day=1) - timedelta(days=1)          # dernier jour du mois précédent
    pm = pm_last.replace(day=1)                                  # 1er jour du mois précédent
    period_month = pm.strftime("%Y-%m")
    plate_a = veh_a.get("plate")

    card_a = await _mk_card(db, "DÉMO Shell", "9999 0001 0001 4321", veh_a["id"])
    card_b = await _mk_card(db, "DÉMO UTA", "9999 0002 0002 8765", veh_b["id"])
    card_c = await _mk_card(db, "DÉMO Migrol", "9999 0003 0003 2109", None,
                            status_history=[(_iso(pm.replace(day=15, hour=9)), "suspended")])
    print(f"• 3 cartes créées (•••• {card_a['last4']}, •••• {card_b['last4']}, "
          f"•••• {card_c['last4']} suspendue)")

    tx_ids = []
    # ---- Mois précédent : historique + décompte ----
    for day, qty, hint in ((2, 48.0, plate_a), (6, 52.5, None), (11, 45.0, plate_a),
                           (15, 55.0, None), (20, 42.0, plate_a), (25, 50.5, None)):
        amt = round(qty * 1.86, 2)
        tx_ids.append(await _mk_tx(db, pm.replace(day=day, hour=8 + day % 9),
                                   "DÉMO Shell Lausanne", "CH", "CHF", amt, qty,
                                   card=card_a, vehicle_hint=hint))
    tx_ids.append(await _mk_tx(db, pm.replace(day=9, hour=12),
                               "DÉMO TotalEnergies Annemasse", "FR", "EUR", 88.60, 48.0, card=card_a))
    tx_ids.append(await _mk_tx(db, pm.replace(day=17, hour=16),
                               "DÉMO Aral Freiburg", "DE", "EUR", 92.30, 51.0, card=card_b))
    tx_ids.append(await _mk_tx(db, pm.replace(day=13, hour=11),
                               "DÉMO Migrol Genève", "CH", "CHF", 70.15, 38.0))  # non rapprochée
    tx_ids.append(await _mk_tx(db, pm.replace(day=22, hour=9),
                               "DÉMO Agrola Berne", "CH", "CHF", 96.70, 52.0, card=card_b))

    # ---- Mois courant : déclencheurs d'anomalies + coût du mois (widget) ----
    d = min(3, today.day)
    tx_ids.append(await _mk_tx(db, today.replace(day=d, hour=10),
                               "DÉMO Shell Lausanne", "CH", "CHF",
                               round((cap + 25) * 1.86, 2), cap + 25.0, card=card_a))     # volume > capacité
    tx_ids.append(await _mk_tx(db, today.replace(day=min(4, today.day), hour=9),
                               "DÉMO Migrol Sion", "CH", "CHF", 83.70, 45.0, card=card_c))  # carte suspendue
    d5 = min(5, today.day)
    tx_ids.append(await _mk_tx(db, today.replace(day=d5, hour=14, minute=0),
                               "DÉMO BP Nyon", "CH", "CHF", 55.80, 30.0, card=card_a))
    tx_ids.append(await _mk_tx(db, today.replace(day=d5, hour=14, minute=25),
                               "DÉMO Shell Morges", "CH", "CHF", 52.10, 28.0, card=card_a))  # double plein
    tx_ids.append(await _mk_tx(db, today.replace(day=min(8, today.day), hour=17),
                               "DÉMO Eni Martigny", "CH", "CHF", 400.00, 55.0, card=card_a))  # montant inhabituel

    print(f"• {len(tx_ids)} transactions créées (mois {period_month} + mois courant, CHF/EUR)")

    settings = await get_fuel_settings(db)
    created = await detect_for_tx_ids(db, settings, tx_ids)
    open_anoms = await db.fuel_anomalies.count_documents({"transaction_id": {"$in": tx_ids}})
    print(f"• Anomalies détectées : {open_anoms} (dont critiques → notification in-app aux admins)")

    stmt = {
        "id": str(uuid.uuid4()), "number": await next_statement_number(db),
        "type": "regular", "scope": "fleet", "period_month": period_month,
        "date_from": pm.strftime("%Y-%m-01"), "date_to": pm_last.strftime("%Y-%m-%d"),
        "include_carried_over": True, "status": "draft", "version": 1, "versions": [],
        "totals": None, "close_exception": None,
        "created_at": _now(), "created_by": SEED_USER["email"],
        "updated_at": _now(), "closed_at": None, "closed_by": None,
    }
    await db.fuel_statements.insert_one(dict(stmt))
    await refresh_statement(db, stmt)
    print(f"• Décompte {stmt['number']} créé (brouillon, période {period_month})")

    await raw.fuel_demo_state.insert_one({
        "id": STATE_ID, "tenant_id": "default", "created_at": _now(),
        "card_ids": [card_a["id"], card_b["id"], card_c["id"]],
        "tx_ids": tx_ids, "statement_id": stmt["id"], "capacity_set_vehicle_id": capacity_set,
    })
    await log_audit("fuel.demo_seed", SEED_USER,
                    {"cards": 3, "transactions": len(tx_ids), "anomalies": open_anoms,
                     "statement": stmt["number"]})
    print("\n✅ Données de démonstration en place. Suppression complète : python seed_fuel_demo.py --clean")


async def clean():
    from app.audit import log_audit
    from app.db import get_db, get_raw_db, init_db
    from app.tenant_context import set_current_tenant

    init_db()
    set_current_tenant("default")
    db, raw = get_db(), get_raw_db()

    state = await raw.fuel_demo_state.find_one({"id": STATE_ID})
    if not state:
        print("Rien à nettoyer (aucun état de seed trouvé).")
        return
    tx_ids, card_ids = state["tx_ids"], state["card_ids"]
    anoms = await db.fuel_anomalies.find({"transaction_id": {"$in": tx_ids}},
                                         {"_id": 0, "id": 1}).to_list(200)
    anom_keys = [f"fuel.anomaly:{a['id']}" for a in anoms]
    n1 = (await db.user_notifications.delete_many({"dedup_key": {"$in": anom_keys}})).deleted_count
    n2 = (await db.notifications_log.delete_many({"dedup_key": {"$in": anom_keys}})).deleted_count
    n3 = (await db.fuel_anomalies.delete_many({"transaction_id": {"$in": tx_ids}})).deleted_count
    n4 = (await db.fuel_transaction_matches.delete_many({"transaction_id": {"$in": tx_ids}})).deleted_count
    n5 = (await db.fuel_transactions.delete_many({"id": {"$in": tx_ids}})).deleted_count
    n6 = (await db.fuel_statement_lines.delete_many({"statement_id": state["statement_id"]})).deleted_count
    n7 = (await db.fuel_statements.delete_many({"id": state["statement_id"]})).deleted_count
    n8 = (await db.fuel_card_assignments.delete_many({"card_id": {"$in": card_ids}})).deleted_count
    n9 = (await db.fuel_cards.delete_many({"id": {"$in": card_ids}})).deleted_count
    if state.get("capacity_set_vehicle_id"):
        await db.vehicles.update_one({"id": state["capacity_set_vehicle_id"]},
                                     {"$unset": {"tank_capacity_l": ""}})
        print("• Capacité réservoir retirée du véhicule de démo")
    await raw.fuel_demo_state.delete_one({"id": STATE_ID})
    await log_audit("fuel.demo_clean", SEED_USER,
                    {"transactions": n5, "cards": n9, "anomalies": n3, "statements": n7})
    print(f"✅ Démo supprimée — tx:{n5} cartes:{n9} affectations:{n8} anomalies:{n3} "
          f"notifications:{n1}+{n2} décompte:{n7} lignes:{n6} rapprochements:{n4}")


if __name__ == "__main__":
    asyncio.run(clean() if "--clean" in sys.argv else seed())
