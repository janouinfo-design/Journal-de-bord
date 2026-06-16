"""Seed mock Navixy-style data: drivers, vehicles, trips, geofences.

Trips simulate Navixy `history/tracks` + `reports/trips` schema:
- start_time, end_time (ISO)
- start_address, end_address
- start_lat, start_lng, end_lat, end_lng
- distance_km, duration_min, fuel_l, avg_speed, max_speed
- ignition events implied
"""
import uuid
import random
from datetime import datetime, timezone, timedelta


SWISS_ADDRESSES = [
    ("Dépôt Logitrak Genève, Rte des Jeunes 8, 1227 Carouge", 46.1781, 6.1376, "depot"),
    ("Entrepôt Meyrin, Ch. des Aulx 2, 1228 Plan-les-Ouates", 46.1654, 6.1117, "entrepot"),
    ("Chantier Lancy, Rue des Bossons 80, 1213 Onex", 46.1850, 6.1004, "chantier"),
    ("Client Migros, Rte de Chancy 71, 1213 Petit-Lancy", 46.1899, 6.1097, "client"),
    ("Domicile Jean Dupont, Rue du Stand 12, 1204 Genève", 46.2009, 6.1432, "domicile"),
    ("Restaurant La Cigale, Place du Bourg-de-Four 9, 1204 Genève", 46.2015, 6.1488, "personal"),
    ("Hôpital Universitaire HUG, Rue Gabrielle-Perret-Gentil 4, 1205 Genève", 46.1928, 6.1437, "client"),
    ("Centre commercial Balexert, Av. Louis-Casaï 27, 1209 Genève", 46.2231, 6.1278, "client"),
    ("Aéroport Genève, Rte de l'Aéroport 21, 1215 Genève", 46.2381, 6.1090, "client"),
    ("Plage des Eaux-Vives, Quai Gustave-Ador, 1207 Genève", 46.2042, 6.1614, "personal"),
    ("Station-service Shell Vernier, Rte de Meyrin 220, 1214 Vernier", 46.2118, 6.0972, "client"),
    ("Domicile Marie Bonnet, Av. de Châtelaine 84, 1219 Châtelaine", 46.2106, 6.1109, "domicile"),
    ("Domicile Pierre Martin, Ch. du Pré-Bourdon 5, 1252 Meinier", 46.2278, 6.2553, "domicile"),
]


DRIVER_NAMES = [
    "Jean Dupont", "Marie Bonnet", "Pierre Martin",
    "Sophie Rey", "Lucas Favre", "Camille Joly",
]


VEHICLES = [
    {"plate": "GE 123456", "model": "Mercedes Sprinter", "mode": "mixte"},
    {"plate": "GE 234567", "model": "VW Crafter", "mode": "mixte"},
    {"plate": "GE 345678", "model": "Renault Trafic", "mode": "mixte"},
    {"plate": "GE 456789", "model": "Ford Transit", "mode": "always_pro"},
    {"plate": "GE 567890", "model": "Citroën Jumpy", "mode": "mixte"},
    {"plate": "GE 678901", "model": "Iveco Daily", "mode": "always_pro"},
]


GEOFENCES = [
    {"name": "Dépôt Logitrak Genève", "type": "depot", "lat": 46.1781, "lng": 6.1376, "radius_m": 150},
    {"name": "Entrepôt Meyrin", "type": "entrepot", "lat": 46.1654, "lng": 6.1117, "radius_m": 200},
    {"name": "Chantier Lancy", "type": "chantier", "lat": 46.1850, "lng": 6.1004, "radius_m": 100},
    {"name": "Client Migros Petit-Lancy", "type": "client", "lat": 46.1899, "lng": 6.1097, "radius_m": 100},
    {"name": "Domicile Jean Dupont", "type": "domicile", "lat": 46.2009, "lng": 6.1432, "radius_m": 100, "driver_index": 0},
    {"name": "Domicile Marie Bonnet", "type": "domicile", "lat": 46.2106, "lng": 6.1109, "radius_m": 100, "driver_index": 1},
    {"name": "Domicile Pierre Martin", "type": "domicile", "lat": 46.2278, "lng": 6.2553, "radius_m": 100, "driver_index": 2},
]


def _rand_address(prefer_type=None):
    if prefer_type:
        pool = [a for a in SWISS_ADDRESSES if a[3] == prefer_type]
        if pool:
            return random.choice(pool)
    return random.choice(SWISS_ADDRESSES)


def _gen_trip(driver_id, driver_name, vehicle_id, vehicle_plate, day: datetime):
    weekday = day.weekday()  # 0=Mon ... 6=Sun
    is_weekend = weekday >= 5
    # Force a personal-ish trip on weekend, professional during weekdays
    if is_weekend:
        start = _rand_address("domicile")
        end = _rand_address("personal")
        hour = random.randint(9, 19)
    else:
        # Mix of business and after-hours personal
        if random.random() < 0.85:
            start = _rand_address("depot") if random.random() < 0.5 else _rand_address("entrepot")
            end = _rand_address("client") if random.random() < 0.6 else _rand_address("chantier")
            hour = random.randint(7, 17)
        else:
            start = _rand_address("domicile")
            end = _rand_address("personal")
            hour = random.choice([6, 19, 20, 21])

    start_dt = day.replace(hour=hour, minute=random.randint(0, 50), second=0, microsecond=0)
    duration_min = random.randint(8, 95)
    end_dt = start_dt + timedelta(minutes=duration_min)
    distance_km = round(random.uniform(2.5, 78.0), 1)
    avg_speed = round(distance_km / max(duration_min / 60, 0.05), 1)
    max_speed = round(avg_speed * random.uniform(1.2, 1.7), 1)
    fuel_l = round(distance_km * random.uniform(0.07, 0.11), 2)

    return {
        "id": str(uuid.uuid4()),
        "tenant_id": "default",
        "driver_id": driver_id,
        "driver_name": driver_name,
        "vehicle_id": vehicle_id,
        "vehicle_plate": vehicle_plate,
        "navixy_track_id": random.randint(1_000_000, 9_999_999),
        "start_time": start_dt.astimezone(timezone.utc).isoformat(),
        "end_time": end_dt.astimezone(timezone.utc).isoformat(),
        "start_address": start[0],
        "start_lat": start[1],
        "start_lng": start[2],
        "start_zone_type": start[3],
        "end_address": end[0],
        "end_lat": end[1],
        "end_lng": end[2],
        "end_zone_type": end[3],
        "distance_km": distance_km,
        "duration_min": duration_min,
        "fuel_l": fuel_l,
        "avg_speed": min(avg_speed, 110),
        "max_speed": min(max_speed, 140),
        "classification": None,        # to be set by rule engine
        "auto_classified": True,
        "modified_by": None,
        "modified_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def seed_mock_data(force: bool = False):
    from app.db import get_db
    db = get_db()

    if not force and await db.trips.count_documents({}) > 0:
        return

    if force:
        await db.drivers.delete_many({})
        await db.vehicles.delete_many({})
        await db.trips.delete_many({})
        await db.geofences.delete_many({})

    # Drivers — first driver maps to the chauffeur user account (env DRIVER_EMAIL)
    import os
    driver_user_email = os.environ.get("DRIVER_EMAIL", "chauffeur@logitrak.ch").lower()
    drivers = []
    for i, name in enumerate(DRIVER_NAMES):
        email = driver_user_email if i == 0 else f"{name.lower().replace(' ', '.')}@logitrak.ch"
        drivers.append({
            "id": str(uuid.uuid4()),
            "tenant_id": "default",
            "name": name,
            "email": email,
            "navixy_employee_id": 1000 + i,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    await db.drivers.insert_many(drivers)

    # Vehicles
    vehicles = []
    for i, v in enumerate(VEHICLES):
        vehicles.append({
            "id": str(uuid.uuid4()),
            "tenant_id": "default",
            "plate": v["plate"],
            "model": v["model"],
            "mode": v["mode"],
            "navixy_tracker_id": 5000 + i,
            "assigned_driver_id": drivers[i % len(drivers)]["id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    await db.vehicles.insert_many(vehicles)

    # Geofences
    geos = []
    for g in GEOFENCES:
        item = {
            "id": str(uuid.uuid4()),
            "tenant_id": "default",
            "name": g["name"],
            "type": g["type"],
            "lat": g["lat"],
            "lng": g["lng"],
            "radius_m": g["radius_m"],
            "driver_id": drivers[g["driver_index"]]["id"] if "driver_index" in g else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        geos.append(item)
    await db.geofences.insert_many(geos)

    # Trips — last 45 days
    today = datetime.now(timezone.utc)
    trips = []
    for day_offset in range(45):
        day = today - timedelta(days=day_offset)
        for v in vehicles:
            driver = next((d for d in drivers if d["id"] == v["assigned_driver_id"]), drivers[0])
            n_trips = random.choices([0, 1, 2, 3, 4], weights=[1, 2, 4, 3, 2])[0]
            for _ in range(n_trips):
                trips.append(_gen_trip(driver["id"], driver["name"], v["id"], v["plate"], day))
    if trips:
        await db.trips.insert_many(trips)
