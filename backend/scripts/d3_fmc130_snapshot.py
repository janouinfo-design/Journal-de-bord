"""D3 FMC130 PRÉCHECK (READ-ONLY) — pilote FMC130, resolver multi-tenant.

Stratégie V2 : distance privée = AVL ID 16 (Teltonika Total Odometer, GNSS interne),
IDENTIQUE au pilote FMC003 réussi (3657864). READ-ONLY strict : aucune commande
privatemode, aucun setparam, aucune modification de sensor/device, aucune bascule.

Résolution du credential (AUCUN AUDIT_NAVIXY_HASH manuel) :
    tracker 781479
      -> vehicle (vehicles.navixy_tracker_id)
      -> tenant_id (vehicles.tenant_id)
      -> get_integration_credential(tenant_id, "NAVIXY")   [fail-closed, jamais cross-tenant]
      -> client Navixy READ-ONLY (get_state / sensor/list / readings/list)

Ne JAMAIS afficher : API key, hash, token, credential tenant.
Pas de fallback global si le tenant réel possède son propre credential (géré par le resolver).

Si le tenant du tracker ne peut pas être résolu :
    FMC130_D3_PRECHECK = BLOCKED
    BLOCKING_REASON    = TENANT_UNRESOLVED

USAGE (dans le conteneur backend, READ-ONLY) :
    python3 scripts/d3_fmc130_snapshot.py precheck        # bloc complet (before + mapping)
    python3 scripts/d3_fmc130_snapshot.py before          # état + AVL16 + GPS
    python3 scripts/d3_fmc130_snapshot.py mapping          # mapping sensor AVL16

Tracker via env TID (défaut 781479).

Critère de mapping ATTENDU (observé, non forcé) :
    input = avl_io_16   multiplier = 1   divider = 1000   unit = km
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

import httpx

# Réutilise les helpers PURS (sans credential) du script FMC003 éprouvé.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(_HERE)          # .../backend (pour importer `app`)
for _p in (_HERE, _BACKEND_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import d3b_snapshot as base  # noqa: E402

TID = int(os.environ.get("TID", "781479"))
AVL16_INPUTS = {"avl_io_16", "hw_mileage"}
_ODO_INPUT_HINTS = ("avl_io_16", "hw_mileage", "total_od")
_ODO_LABEL_HINTS = ("odo total", "odometer", "odometre", "total odo", "mileage")
_RECENT_MAX_S = 3600  # AVL16 "récent" si horodatage < 1h


# --------------------------------------------------------------------------
# Résolution tenant + credential (resolver multi-tenant, READ-ONLY, no secret)
# --------------------------------------------------------------------------
async def _resolve_tenant_and_cred():
    """Retourne (vehicle, tenant_id, cred_dict) ou lève un blocage explicite.

    cred_dict = {"credential", "source", "api_url"} — la VALEUR n'est JAMAIS imprimée.
    """
    from app.db import init_db, get_db
    from app.tenant_context import refresh_tenant_cache
    from app.integrations import get_integration_credential

    init_db()
    db = get_db()
    await refresh_tenant_cache(db)  # peuple le cache tenant pour le resolver

    vehicle = None
    for field in ("navixy_tracker_id", "tracker_id"):
        for val in (TID, str(TID)):
            vehicle = await db.vehicles.find_one({field: val}, {"_id": 0})
            if vehicle:
                break
        if vehicle:
            break

    if not vehicle:
        return None, None, None  # TENANT_UNRESOLVED (véhicule introuvable)

    tenant_id = vehicle.get("tenant_id")
    if not tenant_id:
        return vehicle, None, None  # TENANT_UNRESOLVED (pas de tenant sur le véhicule)

    cred = get_integration_credential(tenant_id, "NAVIXY")  # fail-closed, jamais cross-tenant
    return vehicle, tenant_id, cred


def _base_url(cred):
    return (cred.get("api_url") or os.environ.get("NAVIXY_API_URL")
            or "https://api.navixy.com/v2").rstrip("/")


async def _raw(cred, path, payload):
    """POST READ-ONLY Navixy avec le credential résolu (jamais imprimé)."""
    async with httpx.AsyncClient(timeout=30) as c:
        try:
            r = await c.post(f"{_base_url(cred)}/{path}",
                             json={"hash": cred["credential"], **payload})
        except Exception as e:
            return {"_transport_error": type(e).__name__}
        try:
            return r.json()
        except Exception:
            return {"_http": r.status_code}


# --------------------------------------------------------------------------
def _find_avl16_sensor(sensors: dict):
    best = None
    for s in (sensors.get("list") or []):
        inp = str(s.get("input_name") or "").lower()
        name = str(s.get("name") or "").lower()
        if any(h in inp for h in _ODO_INPUT_HINTS):
            return s
        if any(h in name for h in _ODO_LABEL_HINTS):
            best = best or s
    return best


def _recent(ts) -> bool:
    d = base._parse(ts)
    if not d:
        return False
    try:
        return (datetime.utcnow() - d).total_seconds() <= _RECENT_MAX_S
    except Exception:
        return False


async def _resolve_model(vehicle):
    """Modèle logique via le code Navixy si dispo, sinon champ vehicle.model."""
    try:
        from app.odometer_capability import resolve_model
        m = resolve_model(vehicle.get("navixy_model_code") or vehicle.get("model"))
        if m:
            return m
    except Exception:
        pass
    return vehicle.get("model")


async def precheck():
    vehicle, tenant_id, cred = await _resolve_tenant_and_cred()

    print("\n===== FMC130 D3 PRÉCHECK (READ-ONLY) — tracker %d =====" % TID, flush=True)
    print(f"TRACKER_ID = {TID}", flush=True)

    # Blocages fail-closed AVANT tout appel réseau
    if vehicle is None or tenant_id is None:
        print("MODEL =", (vehicle.get("model") if vehicle else None), flush=True)
        print("TENANT_ID =", tenant_id, flush=True)
        print("\nFMC130_D3_PRECHECK = BLOCKED", flush=True)
        print("BLOCKING_REASON = TENANT_UNRESOLVED", flush=True)
        return
    if not cred or not cred.get("credential"):
        print("MODEL =", vehicle.get("model"), flush=True)
        print("TENANT_ID =", tenant_id, flush=True)
        print("\nFMC130_D3_PRECHECK = BLOCKED", flush=True)
        print("BLOCKING_REASON = NAVIXY_CREDENTIAL_MISSING (tenant sans credential Navixy ; "
              "aucun fallback cross-tenant)", flush=True)
        return

    # Auth READ-ONLY
    info = await _raw(cred, "user/get_info", {})
    if not (isinstance(info, dict) and info.get("success")):
        print("MODEL =", vehicle.get("model"), flush=True)
        print("TENANT_ID =", tenant_id, flush=True)
        print("CRED_SOURCE =", cred.get("source"), "(valeur jamais affichée)", flush=True)
        print("\nFMC130_D3_PRECHECK = BLOCKED", flush=True)
        print("BLOCKING_REASON = NAVIXY_AUTH_FAILED", flush=True)
        return

    state = await _raw(cred, "tracker/get_state", {"tracker_id": TID})
    sensors = await _raw(cred, "tracker/sensor/list", {"tracker_id": TID})
    readings = await _raw(cred, "tracker/readings/list", {"tracker_id": TID})

    st = (state or {}).get("state") or {}
    gps = st.get("gps") or {}
    loc = gps.get("location") or {}
    lat, lng = (loc.get("lat"), loc.get("lng")) if isinstance(loc, dict) else (None, None)
    online = st.get("connection_status") in ("active", "idle")
    moving = str(st.get("movement_status") or "").lower() == "moving"
    ignition = bool(st.get("ignition"))

    avl16 = base._find_avl16(readings or {})
    avl16_val = avl16.get("value") if avl16 else None
    avl16_ts = avl16.get("timestamp") if avl16 else None
    avl16_present = avl16 is not None
    avl16_readable = base._isnum(avl16_val)
    avl16_recent = _recent(avl16_ts)

    # Verdict GPS (NOT_MASKED attendu en Business = GPS normal)
    verdict, reason = base._masking_verdict(lat, lng, gps.get("updated"), avl16_ts, moving, ignition)
    gps_normal = (verdict == "NOT_MASKED")

    # Mapping sensor AVL16 (observé, jamais forcé)
    sensor = _find_avl16_sensor(sensors or {})
    s_defined = sensor is not None
    s_id = sensor.get("id") if sensor else None
    s_input = sensor.get("input_name") if sensor else None
    s_mult = sensor.get("multiplier") if sensor else None
    s_div = sensor.get("divider") if sensor else None
    s_unit = (sensor.get("units_type") or sensor.get("units")) if sensor else None

    # Valeur km via le sensor (converted_value si présent, sinon valeur brute normalisée)
    sensor_value_km = None
    r = base._find_avl16(readings or {})
    if r and base._isnum(r.get("value")):
        sensor_value_km = r.get("value")

    mapping_expected = (
        s_defined
        and str(s_input).lower() in _ODO_INPUT_HINTS
        and (s_mult in (1, 1.0, None))
        and (s_div in (1000, 1000.0))
        and (str(s_unit).lower() in ("km", "kilometer", "kilometre"))
    )
    scale_verified = bool(mapping_expected and avl16_readable)

    model = await _resolve_model(vehicle)

    # ------- Bloc de sortie EXACT demandé -------
    print(f"MODEL = {model}", flush=True)
    print(f"TENANT_ID = {tenant_id}", flush=True)
    print(f"CRED_SOURCE = {cred.get('source')}   (valeur jamais affichée)", flush=True)
    print(f"TRACKER_ONLINE = {online}", flush=True)
    print(f"GPS_NORMAL = {gps_normal}   ({verdict}: {reason})", flush=True)
    print("", flush=True)
    print(f"AVL16_PRESENT = {avl16_present}", flush=True)
    print(f"AVL16_RAW_VALUE = {avl16_val}", flush=True)
    print(f"AVL16_TIMESTAMP = {avl16_ts}", flush=True)
    print(f"AVL16_RECENT = {avl16_recent}", flush=True)
    print("", flush=True)
    print(f"SENSOR_DEFINED = {s_defined}", flush=True)
    print(f"SENSOR_ID = {s_id}", flush=True)
    print(f"SENSOR_INPUT = {s_input}", flush=True)
    print(f"SENSOR_MULTIPLIER = {s_mult}", flush=True)
    print(f"SENSOR_DIVIDER = {s_div}", flush=True)
    print(f"SENSOR_UNIT = {s_unit}", flush=True)
    print(f"SENSOR_VALUE_KM = {sensor_value_km}", flush=True)
    print("", flush=True)
    print(f"AVL16_API_READABLE = {avl16_readable}", flush=True)
    print(f"AVL16_SCALE_VERIFIED = {scale_verified}", flush=True)
    print("", flush=True)

    ok = (online and gps_normal and avl16_present and avl16_recent
          and avl16_readable and scale_verified)
    if ok:
        print("FMC130_D3_PRECHECK = PASS", flush=True)
        print("BLOCKING_REASON = (aucun)", flush=True)
    else:
        reasons = []
        if not online: reasons.append("TRACKER_OFFLINE")
        if not gps_normal: reasons.append("GPS_NOT_NORMAL")
        if not avl16_present: reasons.append("AVL16_ABSENT")
        if not avl16_recent: reasons.append("AVL16_STALE")
        if not avl16_readable: reasons.append("AVL16_NOT_READABLE")
        if not scale_verified: reasons.append("MAPPING_NOT_VERIFIED(mult=1/div=1000/unit=km)")
        print("FMC130_D3_PRECHECK = BLOCKED", flush=True)
        print("BLOCKING_REASON = " + ", ".join(reasons), flush=True)

    print("\n(READ-ONLY : aucune commande, aucun privatemode/setparam, aucune modif sensor/device.)",
          flush=True)
    print("D3_FMC130_EXECUTION = NOT_STARTED | PRIVATE_MODE_GLOBAL = DISABLED | "
          "REAL_DEVICE_COMMANDS = MOCK/SIMULATION", flush=True)


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "precheck"
    if phase not in ("precheck", "before", "mapping"):
        print("usage: d3_fmc130_snapshot.py [precheck | before | mapping]")
        return
    print(f"[D3 FMC130] tracker={TID}  (READ-ONLY, resolver multi-tenant)", flush=True)
    # before/mapping produisent le même bloc complet (source unique de vérité).
    asyncio.run(precheck())


if __name__ == "__main__":
    main()
