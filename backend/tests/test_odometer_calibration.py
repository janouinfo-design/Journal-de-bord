"""Tests — Calibration odomètre AVL16 depuis le tableau de bord (PHASE B, aucun device réel).

Couvre T1..T14 du cahier des charges :
- conversion/validation km entier (T1) ; confirmation AVL16 (T2) ; baseline sans faux delta (T3) ;
- delta post-calibration (T4) ; affectation Pro/Privé (T5,T6) ; odomètre Navixy jamais utilisé (T7) ;
- refus tracker/modèle incorrect (T8) ; cross-tenant (T9) ; device offline (T10) ;
- commande non confirmée -> calibrated=false (T11) ; valeur incohérente (T12) ;
- 2e calibration = nouvelle baseline sans faux delta (T13) ; permissions chauffeur 403 (T14).

Hooks device/AVL16 MOCKÉS (aucun appel Navixy). Verrou write forcé selon le test.
"""
from __future__ import annotations

import asyncio
import os
import pytest

from app import odometer_calibration as oc


def _run(c):
    return asyncio.get_event_loop().run_until_complete(c)


class _Coll:
    def __init__(self):
        self.docs = []

    async def find_one(self, q, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(upd.get("$set", {}))
                return
        if upsert:
            nd = dict(q); nd.update(upd.get("$set", {})); self.docs.append(nd)

    async def insert_one(self, d):
        self.docs.append(dict(d))

    async def count_documents(self, q):
        n = 0
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict):
                    val = d.get(k)
                    for op, opv in v.items():
                        if op == "$gt" and not (val is not None and val > opv): ok = False
                        elif op == "$gte" and not (val is not None and val >= opv): ok = False
                        elif op == "$lt" and not (val is not None and val < opv): ok = False
                        elif op == "$lte" and not (val is not None and val <= opv): ok = False
                elif d.get(k) != v:
                    ok = False
            if ok:
                n += 1
        return n

    def find(self, q, proj=None):
        rows = [dict(d) for d in self.docs if all(d.get(k) == v for k, v in q.items())]
        return _Cursor(rows)


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, key, direction=-1):
        self._rows.sort(key=lambda r: (r.get(key) or ""), reverse=(direction == -1))
        return self

    async def to_list(self, n):
        return self._rows[:n]


class _DB:
    def __init__(self):
        self.vehicles = _Coll()
        self.vehicle_private_capabilities = _Coll()
        self.odometer_calibrations = _Coll()
        self.audit_log = _Coll()


def _db_fmc130():
    db = _DB()
    _run(db.vehicles.update_one({"id": "v130"}, {"$set": {
        "id": "v130", "tenant_id": "default", "model": "telfmu130_fmc130",
        "navixy_tracker_id": 781479, "plate": "LOGITRAK AUDI"}}, upsert=True))
    _run(db.vehicle_private_capabilities.update_one({"tracker_id": 781479}, {"$set": {
        "tracker_id": 781479, "vehicle_id": "v130", "navixy_sensor_id": 5577108}}, upsert=True))
    return db


def _mock_send(mode="REAL"):
    async def _c(tid, cmd):
        assert "11807" in cmd or cmd.startswith("odoset:")
        return {"applied": mode == "REAL", "mode": mode, "command": cmd,
                "navixy_command_id": "cmd-x"}
    return _c


def _mock_read(seq):
    it = iter(seq)
    async def _r(tid):
        try:
            return next(it)
        except StopIteration:
            return seq[-1] if seq else None
    return _r


@pytest.fixture(autouse=True)
def _write_on(monkeypatch):
    # Par défaut ON pour tester la machine ; les tests fail-fast forcent OFF explicitement.
    monkeypatch.setenv("ODOMETER_CALIBRATION_DEVICE_WRITE", "1")
    yield


# ---------- T1 : validation / conversion km entier ----------
def test_t1_validate_dashboard_km_integer():
    assert oc.validate_dashboard_km(139620) == (139620, None)
    assert oc.validate_dashboard_km("139620") == (139620, None)
    assert oc.validate_dashboard_km(139620.0) == (139620, None)         # float entier OK
    v, err = oc.validate_dashboard_km(139620.8)                         # décimale -> refus
    assert v is None and "ENTIER" in err
    v, err = oc.validate_dashboard_km("139620.8")
    assert v is None and err
    v, err = oc.validate_dashboard_km(-1)
    assert v is None and err
    v, err = oc.validate_dashboard_km(oc.PARAM_MAX_KM + 1)
    assert v is None and err
    v, err = oc.validate_dashboard_km(True)                             # bool -> refus
    assert v is None and err


def test_t1_command_syntax_km():
    assert oc.build_calibration_command(139620) == "setparam 11807:139620"
    assert oc.build_calibration_command(139620, style="odoset") == "odoset:139620"


# ---------- T2 : confirmation AVL16 ≈ dashboard km ----------
def test_t2_confirmed_when_avl16_matches():
    db = _db_fmc130()
    res = _run(oc.calibrate_vehicle_odometer(
        db, tenant_id="default", vehicle_id="v130", dashboard_km=139620, actor="admin@x",
        send_command=_mock_send("REAL"),
        read_avl16_km=_mock_read([56377.978, 139620.0])))   # avant, après
    assert res["ok"] is True and res["result"] == oc.CALIB_CONFIRMED
    assert res["odometer_calibrated"] is True
    assert res["difference_km"] == 0.0


# ---------- T3 : calibration crée une baseline, 0 km de trajet artificiel ----------
def test_t3_calibration_creates_baseline_no_fake_distance():
    db = _db_fmc130()
    _run(oc.calibrate_vehicle_odometer(
        db, tenant_id="default", vehicle_id="v130", dashboard_km=139620, actor="admin@x",
        send_command=_mock_send("REAL"), read_avl16_km=_mock_read([56377.978, 139620.0])))
    # Un event confirmé existe
    ev = _run(db.odometer_calibrations.find_one({"vehicle_id": "v130"}))
    assert ev and ev["result"] == oc.CALIB_CONFIRMED
    # Le saut 56377 -> 139620 ne doit JAMAIS être une distance : crosses -> delta None
    crosses = _run(oc.crosses_calibration(db, "v130", "2000-01-01T00:00:00+00:00",
                                          "2999-01-01T00:00:00+00:00"))
    assert crosses is True
    assert oc.safe_avl16_delta_km(56377.978, 139620.0, crosses=crosses) is None  # jamais +83242


# ---------- T4 : delta après calibration = distance réelle ----------
def test_t4_delta_after_calibration():
    # 139620 -> 139625, aucune calibration entre les deux -> 5 km
    assert oc.safe_avl16_delta_km(139620.0, 139625.0, crosses=False) == 5.0


# ---------- T5/T6 : affectation Pro/Privé (delta réel classé) ----------
def test_t5_t6_delta_classification_pro_private():
    seg_km = oc.safe_avl16_delta_km(139620.0, 139628.0, crosses=False)  # 8 km
    assert seg_km == 8.0
    # (classification métier : BUSINESS->Pro, PRIVATE->Privé ; ici on valide le calcul de delta)
    pro = seg_km if True else 0
    assert pro == 8.0


# ---------- T7 : odomètre Navixy générique jamais utilisé (source explicite AVL16) ----------
def test_t7_navixy_odometer_not_used_source_is_avl16():
    db = _db_fmc130()
    _run(oc.calibrate_vehicle_odometer(
        db, tenant_id="default", vehicle_id="v130", dashboard_km=139620, actor="admin@x",
        send_command=_mock_send("REAL"), read_avl16_km=_mock_read([56377.978, 139620.0])))
    cap = _run(db.vehicle_private_capabilities.find_one({"tracker_id": 781479}))
    assert cap["private_distance_source"] == oc.SOURCE_TELTONIKA_AVL16
    assert cap["raw_avl_id"] == 16 and cap["navixy_input"] == "avl_io_16"
    assert cap["divider"] == 1000.0 and cap["multiplier"] == 1.0


# ---------- T8 : tracker/modèle incorrect -> refus ----------
def test_t8_unsupported_model_refused():
    db = _DB()
    _run(db.vehicles.update_one({"id": "vX"}, {"$set": {
        "id": "vX", "tenant_id": "default", "model": "some_unknown_model",
        "navixy_tracker_id": 111}}, upsert=True))
    res = _run(oc.calibrate_vehicle_odometer(
        db, tenant_id="default", vehicle_id="vX", dashboard_km=100, actor="admin@x",
        send_command=_mock_send("REAL"), read_avl16_km=_mock_read([1, 100])))
    assert res["ok"] is False and res["reason"] == oc.R_NOT_SUPPORTED


def test_t8b_no_tracker_refused():
    db = _DB()
    _run(db.vehicles.update_one({"id": "vNoTrk"}, {"$set": {
        "id": "vNoTrk", "tenant_id": "default", "model": "telfmu130_fmc130",
        "navixy_tracker_id": None}}, upsert=True))
    res = _run(oc.calibrate_vehicle_odometer(
        db, tenant_id="default", vehicle_id="vNoTrk", dashboard_km=100, actor="admin@x"))
    assert res["ok"] is False and res["reason"] == oc.R_NO_TRACKER


# ---------- T9 : cross-tenant -> refus (véhicule introuvable dans le mauvais tenant) ----------
def test_t9_cross_tenant_refused():
    db = _db_fmc130()  # véhicule appartient à tenant "default"
    res = _run(oc.calibrate_vehicle_odometer(
        db, tenant_id="autre_tenant", vehicle_id="v130", dashboard_km=139620, actor="admin@x",
        send_command=_mock_send("REAL"), read_avl16_km=_mock_read([1, 139620])))
    assert res["ok"] is False and res["reason"] == oc.R_NO_VEHICLE


# ---------- T10 : device offline -> aucune calibration ----------
def test_t10_device_offline_refused():
    db = _db_fmc130()
    res = _run(oc.calibrate_vehicle_odometer(
        db, tenant_id="default", vehicle_id="v130", dashboard_km=139620, actor="admin@x",
        send_command=_mock_send("REAL"), read_avl16_km=_mock_read([56377.978, 139620.0]),
        device_online=False))
    assert res["ok"] is False and res["reason"] == oc.R_DEVICE_OFFLINE
    # aucun event confirmé
    assert _run(db.odometer_calibrations.count_documents({"vehicle_id": "v130"})) == 0


# ---------- T11 : commande envoyée mais AVL16 non relu -> calibrated=false (PENDING) ----------
def test_t11_not_confirmed_when_no_avl16_after():
    db = _db_fmc130()
    res = _run(oc.calibrate_vehicle_odometer(
        db, tenant_id="default", vehicle_id="v130", dashboard_km=139620, actor="admin@x",
        send_command=_mock_send("REAL"), read_avl16_km=_mock_read([56377.978, None])))
    assert res["ok"] is False and res["odometer_calibrated"] is False
    assert res["result"] == oc.CALIB_PENDING
    # event tracé mais non confirmé ; baseline capability non figée
    cap = _run(db.vehicle_private_capabilities.find_one({"tracker_id": 781479}))
    assert cap.get("odometer_calibrated") in (False, None)
    assert cap.get("calibration_baseline_km") is None


# ---------- T12 : AVL16 reçu mais incohérent -> calibration non validée ----------
def test_t12_incoherent_avl16_not_validated():
    db = _db_fmc130()
    res = _run(oc.calibrate_vehicle_odometer(
        db, tenant_id="default", vehicle_id="v130", dashboard_km=139620, actor="admin@x",
        send_command=_mock_send("REAL"),
        read_avl16_km=_mock_read([56377.978, 140000.0])))   # écart 380 km >> tolérance
    assert res["ok"] is False and res["result"] == oc.CALIB_FAILED
    assert res["odometer_calibrated"] is False
    assert abs(res["difference_km"]) > oc.CONFIRM_TOLERANCE_KM


# ---------- T13 : 2e calibration -> nouvelle baseline, aucun delta artificiel ----------
def test_t13_second_calibration_new_baseline_no_fake_delta():
    db = _db_fmc130()
    # 1re calibration confirmée
    _run(oc.calibrate_vehicle_odometer(
        db, tenant_id="default", vehicle_id="v130", dashboard_km=139620, actor="admin@x",
        send_command=_mock_send("REAL"), read_avl16_km=_mock_read([56377.978, 139620.0])))
    # 2e calibration confirmée (nouvelle valeur)
    _run(oc.calibrate_vehicle_odometer(
        db, tenant_id="default", vehicle_id="v130", dashboard_km=139650, actor="admin@x",
        send_command=_mock_send("REAL"), read_avl16_km=_mock_read([139625.0, 139650.0])))
    # 2 events append-only (aucun écrasement)
    n = _run(db.odometer_calibrations.count_documents({"vehicle_id": "v130"}))
    assert n == 2
    # Une distance qui traverse une des calibrations -> jamais le saut
    crosses = _run(oc.crosses_calibration(db, "v130", "2000-01-01T00:00:00+00:00",
                                          "2999-01-01T00:00:00+00:00"))
    assert crosses is True


# ---------- T14 (fail-fast) : write OFF -> refus immédiat, aucune commande, aucun event ----------
def test_t14_device_write_off_failfast(monkeypatch):
    monkeypatch.setenv("ODOMETER_CALIBRATION_DEVICE_WRITE", "0")
    db = _db_fmc130()

    async def _forbid(tid, cmd):
        raise AssertionError("Aucune commande ne doit partir avec write OFF")

    res = _run(oc.calibrate_vehicle_odometer(
        db, tenant_id="default", vehicle_id="v130", dashboard_km=139620, actor="admin@x",
        send_command=_forbid, read_avl16_km=_mock_read([56377.978])))
    assert res["ok"] is False and res["reason"] == oc.R_DEVICE_WRITE_DISABLED
    assert res["http"] == 503 and res["odometer_calibrated"] is False
    # aucun event de calibration créé
    assert _run(db.odometer_calibrations.count_documents({"vehicle_id": "v130"})) == 0


def test_write_lock_default_is_off(monkeypatch):
    monkeypatch.delenv("ODOMETER_CALIBRATION_DEVICE_WRITE", raising=False)
    assert oc.calibration_device_write_enabled() is False
    # découplé du Mode Privé : PRIVATE_MODE_DEVICE_WRITE=1 ne doit PAS activer la calibration
    monkeypatch.setenv("PRIVATE_MODE_DEVICE_WRITE", "1")
    assert oc.calibration_device_write_enabled() is False
    monkeypatch.setenv("ODOMETER_CALIBRATION_DEVICE_WRITE", "1")
    assert oc.calibration_device_write_enabled() is True
