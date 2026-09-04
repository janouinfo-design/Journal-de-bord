"""D3 FMC130 SNAPSHOT CAPTURE (READ-ONLY) — pilote FMC130.

Stratégie V2 : distance privée = AVL ID 16 (Teltonika Total Odometer, GNSS interne),
IDENTIQUE au pilote FMC003 réussi (3657864). Ce script NE FAIT QUE LIRE : aucune
commande privatemode, aucun setparam, aucun raw_command, aucune bascule.

Il réutilise la même logique éprouvée que d3b_snapshot.py (détection AVL16,
verdict de masquage GPS, tracker online), généralisée à n'importe quel tracker
FMC130 via la variable d'environnement TID.

⚠️ À exécuter dans l'environnement RÉEL contenant le FMC130 pilote (pas ce fork).
Credential via env AUDIT_NAVIXY_HASH. Tracker via env TID (OBLIGATOIRE pour FMC130).

PHASES (argument) :
  before | private_start | private_driving | private_end | business_restored | summary | mapping

`mapping` : vérifie (READ-ONLY) le mapping Navixy du sensor AVL16
  (input=avl_io_16, multiplier=1, divider=1000, unit=km — attendu, à confirmer).

USAGE (READ-ONLY) :
  docker exec -e AUDIT_NAVIXY_HASH="$KEY" -e TID=<FMC130_TRACKER_ID> <conteneur> \
    python3 scripts/d3_fmc130_snapshot.py before
  ... (bascule Privé MANUELLE/opérateur, sur GO explicite — hors de ce script) ...
  ... private_start / private_driving / private_end ...
  ... (retour Professionnel MANUEL, sur GO) ...
  ... business_restored / summary ...

Le fichier cumulatif est /tmp/d3_fmc130_<TID>_snapshots.json.
"""
import os
import sys

# On réutilise INTÉGRALEMENT la logique de d3b_snapshot (AVL16 + verdict masquage).
# Aucune duplication : même code prouvé sur FMC003, généralisé par TID.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

if "TID" not in os.environ:
    raise SystemExit(
        "ABORT: variable TID obligatoire pour FMC130 (aucun défaut). "
        "Ex: -e TID=<FMC130_TRACKER_ID>."
    )

import d3b_snapshot as base  # noqa: E402

# Fichier de stockage distinct pour ne pas mélanger avec le pilote FMC003.
base.STORE = f"/tmp/d3_fmc130_{os.environ['TID']}_snapshots.json"

# Indices de nom/label pour repérer le sensor odométrique AVL16 dans sensor/list.
_ODO_INPUT_HINTS = ("avl_io_16", "hw_mileage", "total_od")
_ODO_LABEL_HINTS = ("odo total", "odometer", "odometre", "total odo", "mileage")


def _find_avl16_sensor(sensors: dict):
    """Repère le sensor AVL16 (Total Odometer) dans tracker/sensor/list (READ-ONLY)."""
    best = None
    for s in (sensors.get("list") or []):
        inp = str(s.get("input_name") or "").lower()
        name = str(s.get("name") or "").lower()
        if any(h in inp for h in _ODO_INPUT_HINTS):
            return s  # match direct sur l'input AVL16
        if any(h in name for h in _ODO_LABEL_HINTS):
            best = best or s
    return best


async def check_mapping():
    """Vérifie le mapping Navixy du sensor AVL16 : input=avl_io_16, multiplier, divider,
    unit. Attendu (à confirmer terrain) : multiplier=1, divider=1000, unit=km. READ-ONLY."""
    _ = base._hash()
    info = await base.raw("user/get_info", {})
    if not (isinstance(info, dict) and info.get("success")):
        st = (info.get("status") or {}) if isinstance(info, dict) else {}
        print(f"[AUTH] echec: {st.get('description') or info} — rien fait.", flush=True)
        return
    print("[AUTH] success=True", flush=True)
    sensors = await base.raw("tracker/sensor/list", {"tracker_id": base.TID})
    s = _find_avl16_sensor(sensors or {})

    if not s:
        print("\n===== AVL16 MAPPING (READ-ONLY) — tracker %d =====" % base.TID, flush=True)
        print("  AVL16_SENSOR_FOUND = NO  -> mapping non vérifiable", flush=True)
        print("  FMC130_D3_PRECHECK = BLOCKED", flush=True)
        print("  BLOCKING_REASON = sensor AVL16 (avl_io_16/hw_mileage) absent de sensor/list", flush=True)
        return

    mult = s.get("multiplier")
    divi = s.get("divider")
    unit = s.get("units_type") or s.get("units")
    inp = s.get("input_name")
    ok = (str(inp).lower() in _ODO_INPUT_HINTS
          and (mult in (1, 1.0, None))
          and (divi in (1000, 1000.0))
          and (str(unit).lower() in ("km", "kilometer", "kilometre")))
    print("\n===== AVL16 MAPPING (READ-ONLY) — tracker %d =====" % base.TID, flush=True)
    print(f"  SENSOR_ID        = {s.get('id')}", flush=True)
    print(f"  SENSOR_NAME      = {s.get('name')}", flush=True)
    print(f"  INPUT_NAME       = {inp}   (attendu: avl_io_16 / hw_mileage)", flush=True)
    print(f"  MULTIPLIER       = {mult} (attendu: 1)", flush=True)
    print(f"  DIVIDER          = {divi} (attendu: 1000)", flush=True)
    print(f"  UNIT             = {unit} (attendu: km)", flush=True)
    print(f"  MAPPING_MATCHES_EXPECTED = {'YES' if ok else 'NO'}", flush=True)
    print("  (Aucune écriture. Aucune modification de sensor. READ-ONLY.)", flush=True)


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "before"
    valid = tuple(base.PHASES) + ("mapping",)
    if phase not in valid:
        print(f"usage: d3_fmc130_snapshot.py [{' | '.join(valid)}]")
        return
    print(f"[D3 FMC130] tracker={base.TID}  store={base.STORE}  (READ-ONLY)", flush=True)
    import asyncio
    if phase == "mapping":
        asyncio.run(check_mapping())
    else:
        asyncio.run(base.run(phase))


if __name__ == "__main__":
    main()
