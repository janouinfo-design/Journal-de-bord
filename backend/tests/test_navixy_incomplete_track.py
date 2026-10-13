"""
Régression — tolérance aux tracks Navixy INCOMPLETS (sans end_date).

Bug terrain : un track sans `end_date` (trajet en cours) provoquait KeyError dans
_build_trip_doc -> interruption de sync_navixy AVANT apply_rules_to_all ->
nouveaux trajets jamais classés (classification=None).

Fix attendu : skip LOCAL du track incomplet (log clair), poursuite des autres tracks,
aucune exception propagée. Jamais inventer de date ni créer un faux trajet terminé.
"""
import asyncio
from datetime import datetime, timezone

from app import navixy_sync as ns


class FakeTrips:
    def __init__(self):
        self.docs = []

    async def find_one(self, query, *a, **k):
        return None

    async def insert_one(self, doc, *a, **k):
        self.docs.append(doc)
        class R: pass
        return R()

    async def update_one(self, *a, **k):
        class R: pass
        return R()


class FakeSessions:
    async def update_many(self, *a, **k):
        class R: pass
        return R()
    async def find_one(self, *a, **k):
        return None


class FakeDB:
    def __init__(self):
        self.trips = FakeTrips()
        self.driver_sessions = FakeSessions()


def _complete(track_id):
    return {
        "id": track_id,
        "start_date": "2026-10-13 08:00:00",
        "end_date": "2026-10-13 08:10:00",
        "length": 2.0,
        "bounds": {},
    }


def _incomplete_no_end(track_id):
    # Trajet EN COURS : pas de end_date (cas terrain réel).
    return {
        "id": track_id,
        "start_date": "2026-10-13 09:00:00",
        "length": 0.5,
        "is_moving": True,
        "bounds": {},
    }


def test_incomplete_track_is_skipped_locally_without_breaking_sync(monkeypatch):
    """Un track sans end_date est ignoré ; les tracks complets sont traités."""
    async def run():
        db = FakeDB()

        async def fake_resolve(_db, _vid, _start):
            return None
        monkeypatch.setattr(ns, "resolve_driver_for_trip", fake_resolve)

        # list_tracks renvoie : complet, INCOMPLET (sans end_date), complet
        async def fake_list_tracks(tracker_id, frm, to):
            return {"list": [_complete(1), _incomplete_no_end(2), _complete(3)]}
        monkeypatch.setattr(ns, "list_tracks", fake_list_tracks)

        vehicle = {"id": "audi", "plate": "LOGITRAK AUDI", "tenant_id": "default"}
        start = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
        errors: list[str] = []

        # NE DOIT PAS lever (avant le fix : KeyError 'end_date')
        new_c, upd_c, had_any = await ns._sync_tracks_for_vehicle(
            db, vehicle, 781479, start, end, [], errors,
        )

        # Les 2 tracks complets sont insérés ; l'incomplet est ignoré.
        assert len(db.trips.docs) == 2
        ids = {d.get("navixy_track_id") for d in db.trips.docs}
        assert ids == {1, 3}, ids
        assert new_c == 2
        assert had_any is True
        # Aucune erreur "dure" ajoutée (le skip n'est pas une erreur).
        assert errors == []

    asyncio.run(run())


def test_track_missing_start_date_is_also_skipped(monkeypatch):
    """Symétrie : un track sans start_date est également ignoré proprement."""
    async def run():
        db = FakeDB()

        async def fake_resolve(_db, _vid, _start):
            return None
        monkeypatch.setattr(ns, "resolve_driver_for_trip", fake_resolve)

        async def fake_list_tracks(tracker_id, frm, to):
            return {"list": [
                {"id": 9, "end_date": "2026-10-13 08:10:00", "length": 1.0, "bounds": {}},  # pas de start_date
                _complete(10),
            ]}
        monkeypatch.setattr(ns, "list_tracks", fake_list_tracks)

        vehicle = {"id": "audi", "plate": "AUDI", "tenant_id": "default"}
        start = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)

        new_c, upd_c, had_any = await ns._sync_tracks_for_vehicle(
            db, vehicle, 781479, start, end, [], [],
        )
        assert len(db.trips.docs) == 1
        assert db.trips.docs[0]["navixy_track_id"] == 10

    asyncio.run(run())
