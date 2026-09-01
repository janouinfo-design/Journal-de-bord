"""Thin async client for Navixy User API (api.navixy.com/v2).

Authentication credential (env, server-side only — NEVER exposed to the mobile app):
- NAVIXY_API_KEY   (RECOMMENDED for server integrations — priority)
- NAVIXY_HASH      (legacy session hash — kept for backward compat, deprecated)
The credential is passed to Navixy in the JSON field `hash` (Navixy accepts both an
API key and a session hash there). A per-tenant `navixy_hash` in the DB still takes
precedence when a tenant context is active.

Secret handling: the credential is NEVER logged, NEVER returned in API responses,
NEVER sent to the frontend.

- NAVIXY_API_URL (default https://api.navixy.com/v2)

All methods raise NavixyError on non-success responses.
"""
import os
import logging
from typing import Any, Optional
import httpx

logger = logging.getLogger(__name__)
_deprecation_warned = False


class NavixyError(Exception):
    pass


def _base_url() -> str:
    from app.tenant_context import get_tenant_doc
    t = get_tenant_doc()
    if t and t.get("navixy_api_url"):
        return t["navixy_api_url"].rstrip("/")
    return os.environ.get("NAVIXY_API_URL", "https://api.navixy.com/v2").rstrip("/")


def _env_credential() -> str:
    """Résout le credential d'environnement, NAVIXY_API_KEY prioritaire sur NAVIXY_HASH.
    Ne retourne jamais dans les logs la valeur ; émet un avertissement de dépréciation
    (sans secret) si l'ancien NAVIXY_HASH est utilisé."""
    global _deprecation_warned
    api_key = os.environ.get("NAVIXY_API_KEY", "").strip()
    if api_key:
        return api_key
    legacy = os.environ.get("NAVIXY_HASH", "").strip()
    if legacy and not _deprecation_warned:
        _deprecation_warned = True
        logger.warning(
            "NAVIXY_HASH (env) est déprécié : définissez NAVIXY_API_KEY à la place "
            "(intégration serveur recommandée). Aucune valeur n'est journalisée."
        )
    return legacy


def _hash() -> str:
    """Credential effectif transmis à Navixy dans le champ `hash`.
    Ordre : tenant.navixy_hash (contexte tenant) -> NAVIXY_API_KEY -> NAVIXY_HASH."""
    from app.tenant_context import get_tenant_doc
    t = get_tenant_doc()
    if t and t.get("navixy_hash"):
        return t["navixy_hash"]
    cred = _env_credential()
    if not cred:
        raise NavixyError("Clé d'intégration LOGITRAK non configurée")
    return cred


def is_configured() -> bool:
    from app.tenant_context import get_tenant_doc, get_tenant_id
    if get_tenant_id():
        t = get_tenant_doc()
        return bool(t and t.get("navixy_hash"))
    return bool(_env_credential())


def credential_type() -> str:
    """Type de credential ACTIF (sans jamais révéler la valeur) : API_KEY / LEGACY_HASH / NONE.
    Utilisé uniquement pour le rapport d'audit."""
    from app.tenant_context import get_tenant_doc, get_tenant_id
    if get_tenant_id():
        t = get_tenant_doc()
        if t and t.get("navixy_hash"):
            return "TENANT_HASH"
    if os.environ.get("NAVIXY_API_KEY", "").strip():
        return "API_KEY"
    if os.environ.get("NAVIXY_HASH", "").strip():
        return "LEGACY_HASH"
    return "NONE"



async def _post(client: httpx.AsyncClient, path: str, payload: dict) -> dict:
    payload = {"hash": _hash(), **payload}
    r = await client.post(f"{_base_url()}/{path.lstrip('/')}",
                          json=payload, timeout=30.0)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise NavixyError(f"Navixy {path}: {data.get('status', {}).get('description', data)}")
    return data


async def get_user_info() -> dict:
    async with httpx.AsyncClient() as c:
        return await _post(c, "user/get_info", {})


async def list_trackers() -> list[dict]:
    async with httpx.AsyncClient() as c:
        data = await _post(c, "tracker/list", {})
    return data.get("list", [])


async def list_employees() -> list[dict]:
    async with httpx.AsyncClient() as c:
        data = await _post(c, "employee/list", {})
    return data.get("list", [])


async def list_zones() -> list[dict]:
    async with httpx.AsyncClient() as c:
        data = await _post(c, "zone/list", {})
    return data.get("list", [])


async def list_tracks(tracker_id: int, date_from: str, date_to: str) -> dict:
    """`from` / `to` format: 'YYYY-MM-DD HH:MM:SS' (server timezone)."""
    async with httpx.AsyncClient() as c:
        return await _post(c, "track/list", {
            "tracker_id": tracker_id, "from": date_from, "to": date_to,
        })


async def read_track_points(tracker_id: int, date_from: str, date_to: str,
                            track_id: Optional[int] = None,
                            simplify: bool = True, point_limit: int = 500) -> list[dict]:
    """Fetch raw GPS points (`track/read`) for a tracker over a time range.

    `date_from` / `date_to` format: 'YYYY-MM-DD HH:MM:SS' (server timezone).
    Optionally restrict to a specific Navixy track_id. Returns the raw list
    of point dicts (`lat`, `lng`, `get_time`, `speed`, `heading`, ...).
    """
    body: dict = {
        "tracker_id": int(tracker_id),
        "from": date_from,
        "to": date_to,
        "simplify": simplify,
        "point_limit": int(point_limit),
    }
    if track_id is not None:
        body["track_id"] = int(track_id)
    async with httpx.AsyncClient() as c:
        data = await _post(c, "track/read", body)
    return data.get("list") or []


async def list_commands(tracker_id: int) -> list[dict]:
    """List available commands for a given tracker (depends on its model/firmware).

    Each item typically contains: id, name, command_type, description, params...
    See https://navixy.com/docs/navixy-api/user-api/backend-api/resources/tracker/command
    """
    async with httpx.AsyncClient() as c:
        data = await _post(c, "tracker/command/list", {"tracker_id": tracker_id})
    return data.get("list", [])


async def send_raw_command(tracker_id: int, command: str, reliable: bool = True) -> dict:
    """Send a raw protocol command to a tracker via Navixy (Phase 2 — write op).

    Endpoint: `tracker/raw_command/send`. Returns `{success, command_id, ...}`.
    `reliable=True` makes Navixy queue and retry the command until ACK/timeout.

    Caller is responsible for ensuring the device supports this command. The
    enforcer module restricts the call to vehicles classified as 'full'
    compatibility (see `privacy_scan.classify_model`).
    """
    async with httpx.AsyncClient() as c:
        return await _post(c, "tracker/raw_command/send", {
            "tracker_id": int(tracker_id),
            "command": command,
            "reliable": reliable,
        })


# ---------------------------------------------------------------------------
# READ-ONLY counters / odometer (audit odomètre Teltonika -> Navixy).
# Endpoints Navixy User API officiels (vérifiés sur la doc, NON inventés) :
#   - tracker/get_counters            {hash, tracker_id}
#   - tracker/counter/value/get       {hash, tracker_id, type: "odometer"|"engine_hours"}
# Aucune écriture ici. `counter/value/set` n'est volontairement PAS implémenté
# (write op non autorisée pendant l'audit).
# ---------------------------------------------------------------------------
async def get_counters(tracker_id: int) -> dict:
    """Lit TOUS les compteurs courants d'un tracker (odometer, engine_hours, ...).

    Réponse Navixy typique : {success, list|counters: [{type, value, update_time, ...}]}
    ou une forme mappée selon la version. Le mapping exact est résolu par l'appelant.
    """
    async with httpx.AsyncClient() as c:
        return await _post(c, "tracker/get_counters", {"tracker_id": int(tracker_id)})


async def get_counter_value(tracker_id: int, counter_type: str = "odometer") -> dict:
    """Lit la valeur d'UN compteur (par défaut l'odomètre) pour un tracker.

    counter_type ∈ {"odometer", "engine_hours"}. Réponse Navixy : {success, value, ...}.
    """
    if counter_type not in ("odometer", "engine_hours"):
        raise NavixyError("counter_type doit être 'odometer' ou 'engine_hours'")
    async with httpx.AsyncClient() as c:
        return await _post(c, "tracker/counter/value/get", {
            "tracker_id": int(tracker_id),
            "type": counter_type,
        })

