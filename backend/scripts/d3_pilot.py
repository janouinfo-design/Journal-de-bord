"""D3 pilote — FMC130 tracker 781479 UNIQUEMENT. Gaté + DRY-RUN par défaut.

SÉCURITÉ :
- Aucune écriture device n'est faite sans flag explicite d'environnement PAR GATE :
    D3_ALLOW_TRIGGER_WRITE=1   -> autorise GATE 2 (setparam Trigger Type)   [NON utilisé par défaut]
    D3_ALLOW_PRIVATE_ON=1      -> autorise GATE 4 (privatemode ON)
    D3_ALLOW_PRIVATE_OFF=1     -> autorise GATE 7 (privatemode OFF)
- Sans ces flags, le script fait UNIQUEMENT des LECTURES et imprime ce qu'il FERAIT (dry-run).
- Verrou dur : ne s'exécute QUE sur TENANT/TID ci-dessous ; refuse tout autre device.
- HTTP 200 n'est jamais considéré comme confirmation device (on relit l'état).

Usage (lectures seules, sûr) :
    docker exec -e PYTHONPATH=/app -w /app journal_backend python3 /tmp/d3_pilot.py read
Usage (une gate d'écriture, exemple PRIVATE ON) — SUR AUTORISATION EXPLICITE :
    docker exec -e PYTHONPATH=/app -e D3_ALLOW_PRIVATE_ON=1 -w /app journal_backend python3 /tmp/d3_pilot.py private_on
"""
import asyncio, os, sys, httpx
from app.tenant_context import set_current_tenant, reset_current_tenant, refresh_tenant_cache
from app.db import init_db
from app import navixy_client as nc

# ---- VERROUS DURS (ne jamais élargir sans nouvelle décision) ----
TENANT = "default"
TID = 781479
EXPECTED_MODEL_TOKEN = "fmc130"   # doit apparaître dans source.model

async def raw(path, payload):
    base = nc._base_url(); h = nc._hash()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{base}/{path}", json={"hash": h, **payload})
        try:
            return r.json()
        except Exception:
            return {"http": r.status_code, "text": r.text[:150]}

async def _guard(trk):
    me = next((x for x in trk if x.get("id") == TID), None)
    model = (me or {}).get("source", {}).get("model", "")
    if EXPECTED_MODEL_TOKEN not in str(model).lower():
        raise SystemExit(f"ABORT: device {TID} model={model} != FMC130 attendu. Aucune action.")
    return me

async def read_state(label):
    st = await raw("tracker/get_state", {"tracker_id": TID})
    s = st.get("state", {})
    gps = s.get("gps", {}).get("location")
    print(f"[{label}] gps={gps} movement={s.get('movement_status')} ign={s.get('ignition')}", flush=True)
    return st

async def read_can_mileage(label):
    rd = await raw("tracker/readings/list", {"tracker_id": TID})
    val = None
    for grp in ("inputs", "virtual_sensors", "counters"):
        for it in rd.get(grp, []) or []:
            nm = str(it.get("input_name") or it.get("name") or "").lower()
            if "can_mileage" in nm:
                val = it.get("value"); ts = it.get("update_time")
                print(f"[{label}] can_mileage = {val} @ {ts}", flush=True)
    if val is None:
        print(f"[{label}] can_mileage = ABSENT des readings !", flush=True)
    return val

async def gate_read():
    db = init_db(); await refresh_tenant_cache(db); tok = set_current_tenant(TENANT)
    try:
        trk = await nc.list_trackers(); await _guard(trk)
        print("== GATE 1/3/5/8 LECTURES (dry-run, aucune écriture) ==", flush=True)
        await read_state("state")
        await read_can_mileage("can_mileage")
    finally:
        reset_current_tenant(tok)

async def gate_private(action):
    """action = 'ON' | 'OFF' — n'écrit QUE si le flag correspondant est présent."""
    flag = "D3_ALLOW_PRIVATE_ON" if action == "ON" else "D3_ALLOW_PRIVATE_OFF"
    allowed = os.environ.get(flag) == "1"
    db = init_db(); await refresh_tenant_cache(db); tok = set_current_tenant(TENANT)
    try:
        trk = await nc.list_trackers(); await _guard(trk)
        print(f"== GATE {'4' if action=='ON' else '7'} PRIVATE {action} (device {TID}) ==", flush=True)
        await read_state("before"); await read_can_mileage("before")
        cmd = f"privatemode {action.lower()}"   # commande envoyée telle quelle au device
        if not allowed:
            print(f"DRY-RUN : commande NON envoyée. Pour exécuter, relancer avec {flag}=1", flush=True)
            print(f"          (aurait envoyé raw_command '{cmd}' au SEUL tracker {TID})", flush=True)
            return
        # ÉCRITURE RÉELLE (autorisée explicitement)
        print(f"ENVOI raw_command '{cmd}' -> tracker {TID} ...", flush=True)
        resp = await nc.send_raw_command(TID, cmd, reliable=True)
        print("  navixy resp (HTTP ok != confirmation device):", str(resp)[:200], flush=True)
        # Relecture d'état (confirmation réelle à valider par l'opérateur)
        await asyncio.sleep(3)
        await read_state("after"); await read_can_mileage("after")
        print("  -> Vérifier manuellement l'état PRIVATE réel du device (AVL/state).", flush=True)
    finally:
        reset_current_tenant(tok)

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "read"
    if action == "read":
        asyncio.run(gate_read())
    elif action == "private_on":
        asyncio.run(gate_private("ON"))
    elif action == "private_off":
        asyncio.run(gate_private("OFF"))
    else:
        print("usage: d3_pilot.py [read|private_on|private_off]")

if __name__ == "__main__":
    main()
