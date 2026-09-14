import asyncio
from copy import deepcopy

from app import navixy_sync as ns


class Result:
    pass


class FakeTrips:
    def __init__(self):
        self.docs = []

    @staticmethod
    def _matches(doc, query):
        for k, v in query.items():
            if isinstance(v, dict) and "$exists" in v:
                if (k in doc) != bool(v["$exists"]):
                    return False
            elif doc.get(k) != v:
                return False
        return True

    async def find_one(self, query):
        for d in self.docs:
            if self._matches(d, query):
                return deepcopy(d)
        return None

    async def insert_one(self, doc):
        d = deepcopy(doc)
        d.setdefault("_id", f"mongo-{len(self.docs)+1}")
        self.docs.append(d)
        return Result()

    async def update_one(self, query, update):
        for d in self.docs:
            if self._matches(d, query):
                d.update(deepcopy(update["$set"]))
                return Result()
        raise AssertionError(f"not found: {query}")


class FakeDB:
    def __init__(self):
        self.trips = FakeTrips()


def trip_doc(
    vehicle_id,
    tracker_id,
    *,
    tenant_id="default",
    track_id=8208,
    distance=1.0,
):
    return {
        "tenant_id": tenant_id,
        "vehicle_id": vehicle_id,
        "vehicle_plate": vehicle_id,
        "navixy_tracker_id": tracker_id,
        "navixy_track_id": track_id,
        "driver_id": None,
        "driver_name": vehicle_id,
        "start_time": "2026-09-14T08:00:00+00:00",
        "end_time": None,
        "distance_km": distance,
    }


def test_same_track_id_on_two_trackers_creates_two_trips():
    async def run():
        db = FakeDB()

        assert await ns._upsert_trip(
            db, trip_doc("alliance", 3131157, distance=1.8)
        ) == "new"

        assert await ns._upsert_trip(
            db, trip_doc("audi", 781479, distance=3.5)
        ) == "new"

        assert len(db.trips.docs) == 2
        assert {d["navixy_tracker_id"] for d in db.trips.docs} == {
            3131157, 781479
        }

    asyncio.run(run())


def test_same_tracker_and_track_updates_existing():
    async def run():
        db = FakeDB()

        assert await ns._upsert_trip(
            db, trip_doc("audi", 781479, distance=3.5)
        ) == "new"

        assert await ns._upsert_trip(
            db, trip_doc("audi", 781479, distance=4.2)
        ) == "updated"

        assert len(db.trips.docs) == 1
        assert db.trips.docs[0]["distance_km"] == 4.2

    asyncio.run(run())


def test_tracker_replacement_on_same_vehicle_does_not_collide():
    async def run():
        db = FakeDB()

        assert await ns._upsert_trip(
            db, trip_doc("audi", 111111, track_id=77)
        ) == "new"

        assert await ns._upsert_trip(
            db, trip_doc("audi", 222222, track_id=77)
        ) == "new"

        assert len(db.trips.docs) == 2

    asyncio.run(run())


def test_tenant_isolation():
    async def run():
        db = FakeDB()

        assert await ns._upsert_trip(
            db,
            trip_doc("audi", 781479, tenant_id="tenant-a"),
        ) == "new"

        assert await ns._upsert_trip(
            db,
            trip_doc("audi", 781479, tenant_id="tenant-b"),
        ) == "new"

        assert len(db.trips.docs) == 2

    asyncio.run(run())


def test_legacy_trip_is_migrated_not_duplicated():
    async def run():
        db = FakeDB()

        db.trips.docs.append({
            "_id": "legacy-1",
            "id": "legacy-trip",
            "tenant_id": "default",
            "vehicle_id": "audi",
            "vehicle_plate": "audi",
            "navixy_track_id": 8208,
            "start_time": "2026-09-14T08:00:00+00:00",
            "end_time": None,
            "distance_km": 1.0,
            "auto_classified": True,
        })

        result = await ns._upsert_trip(
            db,
            trip_doc("audi", 781479, track_id=8208, distance=3.5),
        )

        assert result == "updated"
        assert len(db.trips.docs) == 1
        assert db.trips.docs[0]["navixy_tracker_id"] == 781479
        assert db.trips.docs[0]["distance_km"] == 3.5

    asyncio.run(run())


def test_build_trip_doc_uses_real_tenant_and_tracker(monkeypatch):
    async def fake_resolve(db, vehicle_id, start_iso):
        return None

    monkeypatch.setattr(ns, "resolve_driver_for_trip", fake_resolve)

    vehicle = {
        "id": "audi",
        "plate": "LOGITRAK AUDI",
        "tenant_id": "tenant-real",
    }

    raw = {
        "id": 8208,
        "start_date": "2026-09-14 10:34:14",
        "end_date": "2026-09-14 10:41:51",
        "length": 3.53,
        "bounds": {},
    }

    doc = asyncio.run(
        ns._build_trip_doc(
            object(),
            vehicle,
            781479,
            raw,
            [],
        )
    )

    assert doc["tenant_id"] == "tenant-real"
    assert doc["vehicle_id"] == "audi"
    assert doc["navixy_tracker_id"] == 781479
    assert doc["navixy_track_id"] == 8208



def test_legacy_same_track_different_time_is_not_hijacked():
    async def run():
        db = FakeDB()

        db.trips.docs.append({
            "_id": "legacy-old-tracker",
            "id": "legacy-old-trip",
            "tenant_id": "default",
            "vehicle_id": "audi",
            "vehicle_plate": "audi",
            "navixy_track_id": 8208,
            "start_time": "2026-09-06T12:34:08+00:00",
            "end_time": "2026-09-06T12:48:45+00:00",
            "distance_km": 1.8,
            "auto_classified": True,
        })

        incoming = trip_doc(
            "audi",
            781479,
            track_id=8208,
            distance=3.5,
        )

        result = await ns._upsert_trip(db, incoming)

        assert result == "new"
        assert len(db.trips.docs) == 2

        old = next(
            d for d in db.trips.docs
            if d["id"] == "legacy-old-trip"
        )

        assert "navixy_tracker_id" not in old

        new = next(
            d for d in db.trips.docs
            if d.get("navixy_tracker_id") == 781479
        )

        assert new["navixy_track_id"] == 8208
        assert new["distance_km"] == 3.5

    asyncio.run(run())
