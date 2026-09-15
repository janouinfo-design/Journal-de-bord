"""D2 CONFIG-READ — FMC130 (tracker 781479 UNIQUEMENT). READ-ONLY STRICT.

============================  INTERDICTIONS DURES  ============================
Aucune écriture, aucune commande device. Ce script N'IMPORTE ni n'appelle :
  - privatemode ON/OFF
  - setparam / getparam via raw_command/send  (raw_command ENVOIE une commande -> INTERDIT)
  - counter write / counter/value/set / counter/update
  - sensor create / update
  - tout endpoint de configuration en écriture
D3 ne doit PAS être lancé.

OBJECTIF (D2, fermeture config FMC130) : déterminer si l'on peut LIRE, sans aucune
écriture, la configuration/état réel du device pour statuer :
  - firmware exact
  - configuration Odometer / Odometer Calculation Source
  - état d'activation du Total Odometer (I/O)
  - configuration Private/Business + GPS Data Masking + Odometer-in-Private + Trigger Type
  - état CAN/OBD (diagnostics)

MÉTHODE (endpoints Navixy officiellement READ-ONLY uniquement) :
  - tracker/get_state              (état + firmware éventuel + inputs)
  - tracker/get_diagnostics        (dernières valeurs CAN/OBD reçues)   [READ-ONLY]
  - tracker/settings/read          (réglages plateforme de base)         [READ-ONLY]
  - tracker/settings/tracking/read (mode de tracking plateforme)         [READ-ONLY]
  - tracker/command/list           (INFO SEULEMENT — liste les commandes DISPONIBLES,
                                     NE DONNE PAS la config réelle du device)
IMPORTANT : `tracker/command/list` ne prouve PAS la configuration réelle ; il est
lu uniquement à titre informatif et clairement étiqueté comme tel.

Fait notable (doc Navixy) : l'API User Navixy N'EXPOSE PAS de lecture des paramètres
Teltonika (Odometer Calc Source, Total Odometer I/O, Private/Business, GPS masking,
Trigger Type). La seule voie "raw getparam" passerait par raw_command/send = ÉCRITURE
de commande -> INTERDIT ici. Le script le constate factuellement et conclut.

Verdict final imprimé (un seul) :
  READY_FOR_D3 | READY_FOR_D3_CONFIG_PILOT | CONFIGURATOR_READ_REQUIRED |
  FMC130_NO_VALID_ODOMETER_SOURCE

Usage (READ-ONLY) :
  docker exec -e PYTHONPATH=/app -w /app journal_backend python3 /tmp/d2_fmc130_config_read.py
"""
import asyncio
import json
import copy

import httpx

from app.tenant_context import set_current_tenant, reset_current_tenant, refresh_tenant_cache
from app.db import init_db
from app import navixy_client as nc

TENANT = "default"
TID = 781479
EXPECTED_MODEL_TOKEN = "fmc130"
RAW_OUT = "/tmp/d2_fmc130_config_read_raw.json"

SECRET_KEY_HINTS = [
    "hash", "token", "api_key", "apikey", "password", "secret", "credential",
    "imei", "sim", "iccid", "imsi", "phone", "msisdn", "device_id",
]
GPS_KEY_HINTS = ["lat", "lng", "lon", "latitude", "longitude", "location", "address"]


def _scrub(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if any(h in kl for h in SECRET_KEY_HINTS):
                s = str(v)
                out[k] = v if v in (None, "", 0) else f"***MASKED({len(s)} chars)***"
            elif kl in GPS_KEY_HINTS or any(kl.endswith("_" + h) for h in GPS_KEY_HINTS):
                out[k] = v if v in (None, "", 0) else "***GPS_MASKED***"
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(obj, list):
        return [_scrub(x) for x in obj]
    return obj


async def raw(path, payload):
    """POST READ-ONLY. Retourne le JSON, ou un dict d'erreur (jamais d'exception qui casse l'audit)."""
    base = nc._base_url()
    h = nc._hash()
    async with httpx.AsyncClient(timeout=30) as c:
        try:
            r = await c.post(f"{base}/{path}", json={"hash": h, **payload})
        except Exception as e:
            return {"_transport_error": type(e).__name__}
        try:
            data = r.json()
        except Exception:
            return {"_http": r.status_code, "_text": r.text[:200]}
        data["_http"] = r.status_code
        return data


async def _guard(trk):
    me = next((x for x in trk if x.get("id") == TID), None)
    if not me:
        raise SystemExit(f"ABORT: tracker {TID} introuvable. Aucune action.")
    model = (me or {}).get("source", {}).get("model", "")
    label = (me or {}).get("label", "")
    fw = (me or {}).get("source", {}).get("firmware_version") \
        or (me or {}).get("firmware_version")
    if EXPECTED_MODEL_TOKEN not in str(model).lower():
        raise SystemExit(f"ABORT: device {TID} model={model!r} != FMC130. Aucune action.")
    print(f"[GUARD] tracker={TID} label={label!r} model={model!r} firmware={fw!r} -> OK (FMC130)",
          flush=True)
    return me


def _status_ok(resp):
    return isinstance(resp, dict) and resp.get("success") is True


def _status_line(name, resp):
    if not isinstance(resp, dict):
        return f"  {name:<32} -> reponse inattendue"
    if resp.get("_transport_error"):
        return f"  {name:<32} -> ERREUR TRANSPORT ({resp['_transport_error']})"
    if resp.get("success") is True:
        keys = [k for k in resp.keys() if not k.startswith("_") and k not in ("success", "status")]
        return f"  {name:<32} -> OK (cles: {', '.join(keys) or 'aucune'})"
    st = (resp.get("status") or {})
    desc = st.get("description") or st.get("code") or resp.get("_text") or "echec"
    return f"  {name:<32} -> INDISPONIBLE ({desc})"


async def run():
    db = init_db()
    await refresh_tenant_cache(db)
    tok = set_current_tenant(TENANT)
    raw_dump = {}
    try:
        trk = await nc.list_trackers()
        me = await _guard(trk)
        raw_dump["tracker_list_entry"] = _scrub(copy.deepcopy(me))

        print("\n" + "=" * 70, flush=True)
        print("D2 FMC130 CONFIG-READ — READ-ONLY (tracker %d)" % TID, flush=True)
        print("=" * 70, flush=True)

        # --- Endpoints READ-ONLY tentés ---
        state = await raw("tracker/get_state", {"tracker_id": TID})
        raw_dump["get_state"] = _scrub(copy.deepcopy(state))

        diagnostics = await raw("tracker/get_diagnostics", {"tracker_id": TID})
        raw_dump["get_diagnostics"] = _scrub(copy.deepcopy(diagnostics))

        settings = await raw("tracker/settings/read", {"tracker_id": TID})
        raw_dump["settings_read"] = _scrub(copy.deepcopy(settings))

        tracking = await raw("tracker/settings/tracking/read", {"tracker_id": TID})
        raw_dump["settings_tracking_read"] = _scrub(copy.deepcopy(tracking))

        # INFO SEULEMENT : liste des commandes disponibles (PAS la config reelle)
        cmds = await raw("tracker/command/list", {"tracker_id": TID})
        raw_dump["command_list_INFO_ONLY"] = _scrub(copy.deepcopy(cmds))

        print("\n----- [A] Disponibilite des endpoints READ-ONLY -----", flush=True)
        print(_status_line("tracker/get_state", state), flush=True)
        print(_status_line("tracker/get_diagnostics", diagnostics), flush=True)
        print(_status_line("tracker/settings/read", settings), flush=True)
        print(_status_line("tracker/settings/tracking/read", tracking), flush=True)
        print(_status_line("tracker/command/list [INFO]", cmds), flush=True)

        # --- Ce que l'on PEUT reellement lire (config device Teltonika) ---
        print("\n----- [B] Parametres device Teltonika recherches -----", flush=True)
        readable = {}

        # firmware (parfois dans source)
        fw = (me.get("source") or {}).get("firmware_version") or me.get("firmware_version")
        readable["firmware"] = fw
        print(f"  firmware_exact                     = {fw if fw else 'NON_LISIBLE_VIA_NAVIXY'}", flush=True)

        # diagnostics CAN/OBD (dernieres valeurs recues)
        diag_items = []
        if _status_ok(diagnostics):
            for key in ("list", "diagnostics", "values", "data"):
                v = diagnostics.get(key)
                if isinstance(v, list):
                    diag_items = v
                    break
        print(f"  can_obd_diagnostics                = "
              f"{'PRESENT (' + str(len(diag_items)) + ' items)' if diag_items else 'AUCUN / NON_RENOUVELE'}",
              flush=True)

        # Les parametres suivants NE SONT PAS exposes par l'API User Navixy :
        for label_param in (
            "odometer_calculation_source",
            "total_odometer_io_enabled",
            "total_odometer_avl_id",
            "private_business_supported",
            "gps_data_masking",
            "odometer_calc_in_private_mode",
            "trigger_type",
        ):
            print(f"  {label_param:<34} = NON_LISIBLE_VIA_NAVIXY", flush=True)

        readable["can_obd_diagnostics_count"] = len(diag_items)

        # --- Verdict ---
        # Regle : la config Teltonika (odometer source, total odo I/O, private/business,
        # gps masking, trigger) N'EST PAS lisible via l'API User Navixy en READ-ONLY.
        # Le seul "raw getparam" passerait par raw_command/send = ECRITURE de commande -> interdit.
        device_config_readable = False  # constat factuel (voir doc Navixy + endpoints ci-dessus)

        print("\n" + "=" * 70, flush=True)
        print("SYNTHESE CONFIG-READ", flush=True)
        print("=" * 70, flush=True)
        print(f"  DEVICE_CONFIG_READABLE_VIA_NAVIXY  = {'YES' if device_config_readable else 'NO'}", flush=True)
        print(f"  CONFIGURATOR_READ_REQUIRED         = {'NO' if device_config_readable else 'YES'}", flush=True)
        print("  RAISON: l'API User Navixy n'expose pas les parametres Teltonika (Odometer Calc", flush=True)
        print("          Source, Total Odometer I/O, Private/Business, GPS masking, Trigger Type).", flush=True)
        print("          La lecture 'raw getparam' passerait par raw_command/send = ECRITURE de", flush=True)
        print("          commande -> INTERDITE en D2. Aucune commande envoyee.", flush=True)

        # Verdict unique attendu
        verdict = "CONFIGURATOR_READ_REQUIRED" if not device_config_readable else "READY_FOR_D3_CONFIG_PILOT"

        print("\n" + "=" * 70, flush=True)
        print("VERDICT D2 FMC130 (un seul)", flush=True)
        print("=" * 70, flush=True)
        print(f"  {verdict}", flush=True)
        print("  (D3 NON lance. Aucune ecriture, aucune commande device.)", flush=True)

        # --- Checklist Configurator (lecture seule, a relever manuellement) ---
        print("\n----- [C] CHECKLIST Teltonika Configurator (LECTURE SEULE) -----", flush=True)
        print("  Connecter le FMC130 (781479 / LOGITRAK AUDI) au Configurator et RELEVER (ne rien", flush=True)
        print("  modifier / ne pas cliquer Save to device) :", flush=True)
        print("   1. Device Info : Firmware version, Configuration version, IMEI (ne pas divulguer).", flush=True)
        print("   2. System > Odometer : 'Odometer Calculation Source' (GNSS / LVCAN / OBD),", flush=True)
        print("      valeur actuelle 'Total Odometer', et si 'Trip Odometer' est actif.", flush=True)
        print("   3. I/O : element 'Total Odometer' -> Priority (None/Low/High) et Operand.", flush=True)
        print("      NOTER l'AVL ID reellement affiche pour Total Odometer (NE PAS supposer 16).", flush=True)
        print("   4. Private/Business (ou 'Trip / Odometer' selon firmware) : mode supporte ?", flush=True)
        print("      'GPS Data Masking' on/off ; comportement odometre pendant mode Prive.", flush=True)
        print("   5. Trigger Type du mode Private/Business (Digital input / Timer / etc.).", flush=True)
        print("   6. OBD/CAN : si 'LV-CAN'/'ALL-CAN'/OBD est configure et actif (explique le", flush=True)
        print("      CAN_OBD_NOT_CURRENTLY_REPORTING observe cote Navixy).", flush=True)
        print("  -> Reporter ces valeurs ; elles determineront READY_FOR_D3 / READY_FOR_D3_CONFIG_PILOT", flush=True)
        print("     / FMC130_NO_VALID_ODOMETER_SOURCE.", flush=True)

        # --- RAW ---
        try:
            with open(RAW_OUT, "w", encoding="utf-8") as f:
                json.dump(raw_dump, f, ensure_ascii=False, indent=2, default=str)
            size = len(json.dumps(raw_dump, default=str))
            print(f"\n----- RAW JSON masque sauvegarde -> {RAW_OUT} ({size} chars) -----", flush=True)
            if size <= 14000:
                print(json.dumps(raw_dump, ensure_ascii=False, indent=2, default=str), flush=True)
            else:
                print("  (RAW volumineux : voir le fichier. Extraits diagnostics/settings ci-dessous.)",
                      flush=True)
                for key in ("get_diagnostics", "settings_read", "settings_tracking_read"):
                    print(f"\n  --- {key} ---", flush=True)
                    print(json.dumps(raw_dump.get(key, {}), ensure_ascii=False, indent=2, default=str)[:5000],
                          flush=True)
        except Exception as e:
            print(f"  (impossible d'ecrire {RAW_OUT}: {type(e).__name__})", flush=True)

    finally:
        reset_current_tenant(tok)


if __name__ == "__main__":
    asyncio.run(run())
