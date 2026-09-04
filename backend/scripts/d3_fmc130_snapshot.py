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
  before | private_start | private_driving | private_end | business_restored | summary

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


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "before"
    if phase not in base.PHASES:
        print(f"usage: d3_fmc130_snapshot.py [{' | '.join(base.PHASES)}]")
        return
    print(f"[D3 FMC130] tracker={base.TID}  store={base.STORE}  (READ-ONLY)", flush=True)
    import asyncio
    asyncio.run(base.run(phase))


if __name__ == "__main__":
    main()
