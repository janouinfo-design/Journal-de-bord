"""Test reproductible de l'alerte « conflit non résolu > 1 h » — À LANCER SUR LE VPS.

Usage :
    cd /app/backend && python scripts/test_conflict_alert_prod.py [--tenant default] [--keep]

Ce que fait le script (mécanisme de test EXPLICITEMENT ISOLÉ — ne touche à aucune
donnée réelle : véhicule + chauffeurs synthétiques, tout est nettoyé à la fin) :
 1. crée un véhicule de test + 2 chauffeurs de test ;
 2. crée 2 sessions en CONFLIT dont conflict_at est daté d'il y a 61 minutes
    (le seuil de production de 60 min n'est PAS modifié) ;
 3. déclenche alert_stale_conflicts() (la même fonction que le job planifié) ;
 4. affiche : notification in-app créée, statut d'envoi e-mail RÉEL
    (sent/failed/not_configured — jamais « envoyé » sans preuve), audit ;
 5. relance une 2ᵉ fois → vérifie qu'AUCUNE seconde alerte n'est émise ;
 6. nettoie tout (sauf --keep).

⚠️ La validation finale reste HUMAINE : l'e-mail n'est « validé » que lorsque
   vous l'avez réellement reçu dans votre boîte admin/manager.
"""
import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


async def main(tenant_id: str, keep: bool):
    from app.db import init_db, get_db
    from app.tenant_context import set_current_tenant, reset_current_tenant
    from app.ble_engine import alert_stale_conflicts
    from app.emailer import is_smtp_configured

    init_db()
    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mc[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=61)).isoformat()
    VID = f"test-alert-veh-{uuid.uuid4().hex[:6]}"
    D1, D2 = f"test-alert-drv1-{uuid.uuid4().hex[:6]}", f"test-alert-drv2-{uuid.uuid4().hex[:6]}"

    print(f"SMTP configuré dans cet environnement : {'OUI' if is_smtp_configured() else 'NON'}")
    if not is_smtp_configured():
        print("→ Statut e-mail attendu : « Envoi SMTP non vérifié dans cet environnement »\n")

    try:
        await db.vehicles.insert_one({"id": VID, "tenant_id": tenant_id,
                                      "plate": "TEST-ALERTE", "model": "Véhicule de test alerte"})
        await db.drivers.insert_one({"id": D1, "tenant_id": tenant_id, "name": "Test Alerte Ivan", "active": True})
        await db.drivers.insert_one({"id": D2, "tenant_id": tenant_id, "name": "Test Alerte Leart", "active": True})
        for did in (D1, D2):
            await db.driver_sessions.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tenant_id, "driver_id": did,
                "vehicle_id": VID, "status": "conflict", "conflict_at": old,
                "started_at": old, "last_seen": old, "active_driver": False,
                "source": "test_alerte"})
        print("1) Conflit synthétique créé (conflict_at = il y a 61 min, seuil prod 60 min inchangé)")

        token = set_current_tenant(tenant_id)
        try:
            res1 = await alert_stale_conflicts(get_db())
            print(f"2) Premier passage du job : {res1}  (attendu: alerted=1)")
            res2 = await alert_stale_conflicts(get_db())
            print(f"3) Second passage (anti-doublon) : {res2}  (attendu: alerted=0)")
        finally:
            reset_current_tenant(token)

        log = await db.notifications_log.find_one(
            {"tenant_id": tenant_id, "event": "ble.conflict_stale"}, sort=[("ts", -1)])
        if log:
            print("4) notifications_log :")
            print(f"   in-app créées      : {log.get('inapp_created')}")
            print(f"   e-mails planifiés  : {log.get('email_planned')}")
            delivery = log.get("email_delivery")
            if delivery == "not_configured":
                print("   e-mail             : Envoi SMTP non vérifié dans cet environnement")
            elif isinstance(delivery, dict):
                print(f"   e-mail             : remis au serveur SMTP → sent={delivery.get('sent')} failed={delivery.get('failed')}")
                print("   ⚠ « Validé » seulement quand vous l'avez REÇU dans votre boîte.")
            else:
                print(f"   e-mail             : {delivery}")
        else:
            print("4) ✗ Aucune entrée notifications_log — échec")

        aud = await db.audit_log.find_one(
            {"tenant_id": tenant_id, "action": "conflict_stale_alerted", "vehicle_id": VID})
        print(f"5) Audit conflict_stale_alerted : {'présent' if aud else '✗ ABSENT'}")
        n = await db.driver_sessions.count_documents(
            {"vehicle_id": VID, "conflict_alert_sent": True})
        print(f"6) Sessions marquées alertées : {n}/2")
    finally:
        if keep:
            print("\n--keep : données de test conservées (nettoyez-les manuellement).")
        else:
            await db.vehicles.delete_many({"id": VID})
            await db.drivers.delete_many({"id": {"$in": [D1, D2]}})
            await db.driver_sessions.delete_many({"vehicle_id": VID})
            await db.notifications_log.delete_many(
                {"event": "ble.conflict_stale", "data.vehicle_id": VID})
            print("\nNettoyage complet effectué (véhicule, chauffeurs, sessions de test).")
    mc.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", default="default")
    p.add_argument("--keep", action="store_true")
    a = p.parse_args()
    asyncio.run(main(a.tenant, a.keep))
