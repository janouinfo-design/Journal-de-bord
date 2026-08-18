"""Phase 1 — Tracker privacy-mode compatibility scanner (Logitrak).

This is a DISCOVERY-ONLY operation. **No command is ever sent to the tracker.**

Navixy does not expose a generic "list of native protocol commands supported
by a tracker model" endpoint. The `tracker/command/*` family stores user-defined
custom commands, not protocol capabilities. So we determine compatibility from
the tracker's **model identifier** as returned by `tracker/list` (already synced
into `db.vehicles.model`).

Known privacy-capable families:
- **Teltonika FMx** (`telfmu130_fmc*`, `telfmb003_fmc*`, FMB920, FMC650, etc.)
  → `setparam` (param IDs 11000+ for sleep, 1004 for tracking mode) + DOUT toggle.
  Status = **full**.
- **Queclink GV/GL/GMT** → AT-style commands (`AT+GTCFG`). Status = **full**.
- **Concox JM-01 / GT06N** → SMS only, no IP commands. Status = **partial**.
- **Smartphone apps** (`navixymobile_xgps`, `iosnavixytracker_xgps`) → no native
  protocol command, the app's own privacy toggle must be used. Status = **none**.
- Unknown model strings → Status = **unknown** (user must verify manually).
"""
from typing import Optional


# Substring → (status, family label, recommended_command)
_MODEL_RULES: list[tuple[str, str, str, str]] = [
    # Teltonika FMC / FMB family
    ("telfm", "full",    "Teltonika FMx",        "setparam 1004:0 (sleep mode)"),
    ("teltonika", "full","Teltonika",            "setparam 1004:0 (sleep mode)"),
    ("fmc", "full",      "Teltonika FMx",        "setparam 1004:0 (sleep mode)"),
    ("fmb", "full",      "Teltonika FMx",        "setparam 1004:0 (sleep mode)"),
    # Queclink
    ("queclink", "full", "Queclink",             "AT+GTCFG,privacy=1"),
    ("quec",     "full", "Queclink",             "AT+GTCFG,privacy=1"),
    # Concox
    ("concox",  "partial", "Concox",             "PRIVACY,ON# (SMS only)"),
    ("gt06",    "partial", "Concox GT06",        "PRIVACY,ON# (SMS only)"),
    # Smartphones / Navixy apps
    ("iosnavixy",       "none", "Smartphone iOS",     "Privacy à activer dans l'app Navixy"),
    ("navixymobile",    "none", "Smartphone Android", "Privacy à activer dans l'app Navixy"),
    ("xgps",            "none", "Smartphone",         "Privacy à activer dans l'app Navixy"),
]


def classify_model(model: Optional[str]) -> dict:
    """Return {status, family, recommended_command} from the model string."""
    if not model:
        return {"status": "unknown", "family": "Modèle inconnu", "recommended_command": None}
    m = model.lower()
    for substr, status, family, cmd in _MODEL_RULES:
        if substr in m:
            return {"status": status, "family": family, "recommended_command": cmd}
    return {"status": "unknown", "family": f"Modèle non répertorié ({model})", "recommended_command": None}


async def scan_vehicle(db, vehicle: dict) -> dict:  # noqa: ARG001 (db unused for now)
    """Scan a single vehicle. Returns a row ready for the UI table.

    Discovery-only: reads the locally stored model (synced from Navixy
    `tracker/list`). No outbound call is performed.
    """
    info = classify_model(vehicle.get("model"))
    return {
        "vehicle_id": vehicle["id"],
        "plate": vehicle.get("plate", ""),
        "model": vehicle.get("model", ""),
        "navixy_tracker_id": vehicle.get("navixy_tracker_id"),
        "status": info["status"],
        "family": info["family"],
        "recommended_command": info["recommended_command"],
        "error": None if vehicle.get("navixy_tracker_id") else "Aucun tracker Navixy lié",
    }


async def scan_all_vehicles(db) -> dict:
    """Scan every vehicle of the default tenant. Aggregates counters for the UI."""
    rows: list[dict] = []
    vehicles = await db.vehicles.find({"tenant_id": "default"}, {"_id": 0}).to_list(1000)
    for v in vehicles:
        rows.append(await scan_vehicle(db, v))
    counters = {
        "full": sum(1 for r in rows if r["status"] == "full"),
        "partial": sum(1 for r in rows if r["status"] == "partial"),
        "none": sum(1 for r in rows if r["status"] == "none"),
        "unknown": sum(1 for r in rows if r["status"] == "unknown"),
        "total": len(rows),
    }
    return {"rows": rows, "counters": counters}
