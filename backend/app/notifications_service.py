"""High-level notification dispatcher.

Reads user-level notification preferences, resolves push tokens for the
targeted users / drivers / tenant, and dispatches to Expo Push.

This is the single entry-point used by `ble_engine`, `privacy_enforcer`,
the scheduler, and any future business event (contract renewal, low tracker
battery, vehicle inspection, missing driver assignment, Logibus delay, …).

Design:
- Catalog of events in `EVENT_CATALOG` with default channels + a renderer
  callable that returns `(title, body, data, category)`.
- Preferences are stored in `db.notification_preferences` keyed by user_id.
- Defaults: push=True, email=False, sms=False for all events.
- Email / SMS are stubbed (logged) — no provider wired yet. Push is live.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from pymongo.errors import DuplicateKeyError

from app.expo_push import send_to_tokens

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Event catalog — each entry knows how to render its own notification
# -------------------------------------------------------------------
def _r_ble_conflict(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any], str | None]:
    vehicle = payload.get("vehicle_plate") or payload.get("vehicle_label") or "Véhicule"
    return (
        "🚨 Conflit d'identification chauffeur",
        f"Véhicule : {vehicle}\nMerci de confirmer qui conduisait.",
        {
            "type": "ble.conflict",
            "session_id": payload.get("session_id"),
            "vehicle_id": payload.get("vehicle_id"),
            "driver_ids": payload.get("drivers", []),
            "actions": ["confirm_driver", "deny_driver"],
        },
        "BLE_CONFLICT",
    )


def _r_ble_conflict_stale(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any], str | None]:
    vehicle = payload.get("vehicle_plate") or "Véhicule"
    names = ", ".join(payload.get("driver_names") or []) or "chauffeurs inconnus"
    return (
        "⏰ Conflit chauffeur non résolu depuis plus d'une heure",
        f"Véhicule : {vehicle}\nChauffeurs en conflit : {names}\n"
        "Merci de le résoudre dans Journal de bord → Identification → Conflits.",
        {
            "type": "ble.conflict_stale",
            "vehicle_id": payload.get("vehicle_id"),
            "session_ids": payload.get("session_ids", []),
            "link": "/livre/identification?status=conflict",
        },
        None,
    )


def _r_ble_resolved(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any], str | None]:
    return (
        "✅ Conflit résolu",
        f"Le véhicule {payload.get('vehicle_plate') or ''} a été attribué.",
        {
            "type": "ble.resolved",
            "session_id": payload.get("winner_session_id"),
            "vehicle_id": payload.get("vehicle_id"),
        },
        None,
    )


def _r_kill_switch(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any], str | None]:
    return (
        "⚠️ Tracking désactivé par l'administrateur",
        payload.get("reason") or "Le mode privé a été désactivé en urgence.",
        {"type": "kill_switch"},
        None,
    )


def _r_fuel_anomaly(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any], str | None]:
    return (
        "🚨 Anomalie carburant critique",
        payload.get("explanation") or "Une anomalie critique a été détectée.",
        {
            "type": "fuel.anomaly_critical",
            "anomaly_id": payload.get("anomaly_id"),
            "transaction_id": payload.get("transaction_id"),
            "link": f"/livre/carburant/anomalies?anomaly={payload.get('anomaly_id') or ''}",
        },
        None,
    )


# Stubs for future business events — already in the catalog so prefs UI
# can list them and the backend can hook into the dispatcher later.
def _generic_render(title: str, body_tpl: str):
    def _r(p: dict[str, Any]):
        return title, body_tpl.format(**p), {"type": title, **p}, None
    return _r


EVENT_CATALOG: dict[str, dict[str, Any]] = {
    "ble.conflict": {
        "label": "Conflit d'identification chauffeur",
        "default_channels": {"push": True, "email": False, "sms": False},
        "render": _r_ble_conflict,
        "audience": "driver",  # who normally receives this
    },
    "ble.resolved": {
        "label": "Résolution de conflit",
        "default_channels": {"push": True, "email": False, "sms": False},
        "render": _r_ble_resolved,
        "audience": "driver",
    },
    "ble.conflict_stale": {
        "label": "Conflit chauffeur non résolu (> 1 h)",
        "default_channels": {"push": True, "email": True, "sms": False},
        "render": _r_ble_conflict_stale,
        "audience": "admin",
        "inapp": True,
        "email_real": True,
    },
    "kill_switch": {
        "label": "Tracking désactivé en urgence",
        "default_channels": {"push": True, "email": True, "sms": False},
        "render": _r_kill_switch,
        "audience": "admin",
    },
    "fuel.anomaly_critical": {
        "label": "Anomalie carburant critique",
        "default_channels": {"push": True, "email": False, "sms": False},
        "render": _r_fuel_anomaly,
        "audience": "admin",
        "inapp": True,       # toujours déposée dans le centre de notifications in-app
        "email_real": True,  # email SMTP réel si l'utilisateur l'active (désactivé par défaut)
    },
    # Future events (stubs)
    "contract.renewal": {
        "label": "Renouvellement de contrat à venir",
        "default_channels": {"push": False, "email": True, "sms": False},
        "render": _generic_render("📄 Renouvellement de contrat",
                                  "Le contrat « {label} » expire le {date}."),
        "audience": "admin",
    },
    "insurance.expiring": {
        "label": "Assurance bientôt échue",
        "default_channels": {"push": True, "email": True, "sms": False},
        "render": _generic_render("🛡️ Assurance bientôt échue",
                                  "L'assurance « {label} » expire le {date}."),
        "audience": "admin",
    },
    "vehicle.inspection_due": {
        "label": "Révision véhicule à prévoir",
        "default_channels": {"push": True, "email": False, "sms": False},
        "render": _generic_render("🔧 Révision véhicule",
                                  "{plate} : révision recommandée."),
        "audience": "admin",
    },
    "tracker.low_battery": {
        "label": "Batterie tracker faible",
        "default_channels": {"push": True, "email": False, "sms": False},
        "render": _generic_render("🔋 Batterie tracker faible",
                                  "{plate} : tracker à {battery}%."),
        "audience": "admin",
    },
    "tracker.gps_lost": {
        "label": "Perte de signal GPS",
        "default_channels": {"push": True, "email": False, "sms": False},
        "render": _generic_render("📡 GPS perdu",
                                  "{plate} : pas de point depuis {minutes} min."),
        "audience": "admin",
    },
    "driver.unassigned": {
        "label": "Chauffeur sans affectation",
        "default_channels": {"push": False, "email": True, "sms": False},
        "render": _generic_render("👤 Chauffeur sans affectation",
                                  "Aucune affectation prévue pour {driver_name}."),
        "audience": "admin",
    },
    "vehicle.incident": {
        "label": "Incident véhicule",
        "default_channels": {"push": True, "email": True, "sms": True},
        "render": _generic_render("🚨 Incident véhicule",
                                  "{plate} — {label}"),
        "audience": "admin",
    },
    "logibus.delay": {
        "label": "Retard sur une ligne Logibus",
        "default_channels": {"push": True, "email": False, "sms": False},
        "render": _generic_render("⏱️ Retard Logibus",
                                  "Ligne {line} : +{delay_min} min."),
        "audience": "admin",
    },
}


def event_catalog_public() -> list[dict[str, Any]]:
    """JSON-serialisable view of the catalog for the settings UI."""
    return [
        {"event": k, "label": v["label"],
         "default_channels": v["default_channels"], "audience": v["audience"]}
        for k, v in EVENT_CATALOG.items()
    ]


# -------------------------------------------------------------------
# Preferences
# -------------------------------------------------------------------
async def get_preferences(db, user_id: str) -> dict[str, Any]:
    """Read merged prefs (stored override on top of catalog defaults).

    Returns: `{user_id, channels: {push, email, sms}, events: {<event>: {push, email, sms}}}`
    """
    doc = await db.notification_preferences.find_one({"user_id": user_id}, {"_id": 0}) or {}
    saved_events = doc.get("events") or {}
    merged_events = {}
    for ev, meta in EVENT_CATALOG.items():
        merged_events[ev] = {**meta["default_channels"], **(saved_events.get(ev) or {})}
    return {
        "user_id": user_id,
        # Per-channel master switch (default: all on; user can mute everything)
        "channels": {
            "push": doc.get("channels", {}).get("push", True),
            "email": doc.get("channels", {}).get("email", True),
            "sms": doc.get("channels", {}).get("sms", True),
        },
        "events": merged_events,
        "updated_at": doc.get("updated_at"),
    }


async def set_preferences(db, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    update: dict[str, Any] = {"user_id": user_id, "updated_at": now}
    if "channels" in patch and isinstance(patch["channels"], dict):
        chans = patch["channels"]
        update["channels"] = {
            "push": bool(chans.get("push", True)),
            "email": bool(chans.get("email", True)),
            "sms": bool(chans.get("sms", True)),
        }
    if "events" in patch and isinstance(patch["events"], dict):
        clean: dict[str, dict[str, bool]] = {}
        for ev, channels in patch["events"].items():
            if ev not in EVENT_CATALOG:
                continue
            if not isinstance(channels, dict):
                continue
            clean[ev] = {
                "push": bool(channels.get("push", True)),
                "email": bool(channels.get("email", False)),
                "sms": bool(channels.get("sms", False)),
            }
        update["events"] = clean
    await db.notification_preferences.update_one(
        {"user_id": user_id}, {"$set": update}, upsert=True,
    )
    return await get_preferences(db, user_id)


# -------------------------------------------------------------------
# Dispatcher
# -------------------------------------------------------------------
async def _resolve_targets(
    db, event: str, tenant_id: str,
    user_ids: list[str] | None,
    driver_ids: list[str] | None,
    role_filter: list[str] | None,
    keep_all: bool = False,
) -> list[dict[str, Any]]:
    """Return the list of {user_id, channels, push_tokens} that should be notified."""
    query: dict[str, Any] = {"tenant_id": tenant_id} if tenant_id else {}
    if user_ids:
        query["id"] = {"$in": user_ids}
    elif driver_ids:
        # Map drivers → their linked user_id via email
        drivers = await db.drivers.find(
            {"id": {"$in": driver_ids}}, {"_id": 0, "id": 1, "email": 1},
        ).to_list(500)
        emails = [d.get("email") for d in drivers if d.get("email")]
        if not emails:
            return []
        query["email"] = {"$in": [e.lower() for e in emails]}
    elif role_filter:
        query["role"] = {"$in": role_filter}

    users = await db.users.find(query, {"_id": 0, "password_hash": 0}).to_list(1000)
    targets: list[dict[str, Any]] = []
    for u in users:
        prefs = await get_preferences(db, u["id"])
        ev_channels = prefs["events"].get(event) or {}
        # Honor per-channel master switches
        push_ok = prefs["channels"]["push"] and ev_channels.get("push", True)
        email_ok = prefs["channels"]["email"] and ev_channels.get("email", False)
        sms_ok = prefs["channels"]["sms"] and ev_channels.get("sms", False)
        if not (push_ok or email_ok or sms_ok) and not keep_all:
            continue
        # Fetch the user's active Expo push tokens (only if push is enabled)
        tokens: list[str] = []
        if push_ok:
            cursor = db.push_tokens.find(
                {"user_id": u["id"], "active": True}, {"_id": 0, "token": 1},
            )
            tokens = [d["token"] async for d in cursor]
        targets.append({
            "user_id": u["id"], "user_email": u.get("email"), "user_role": u.get("role"),
            "channels": {"push": push_ok, "email": email_ok, "sms": sms_ok},
            "push_tokens": tokens,
        })
    return targets


async def dispatch(
    event: str,
    payload: dict[str, Any],
    *,
    tenant_id: str | None = None,
    user_ids: list[str] | None = None,
    driver_ids: list[str] | None = None,
    role_filter: list[str] | None = None,
    dedup_key: str | None = None,
) -> dict[str, Any]:
    """Send the notification for `event` to the resolved audience.

    Either pass explicit `user_ids` / `driver_ids`, or let the catalog
    audience drive the `role_filter` (admin gets admin events, etc.).
    """
    from app.db import get_db
    from app.tenant_context import get_effective_tenant_id
    db = get_db()
    tenant_id = tenant_id or get_effective_tenant_id() or "default"

    meta = EVENT_CATALOG.get(event)
    if not meta:
        logger.warning("dispatch: unknown event %s", event)
        return {"ok": False, "reason": "unknown_event"}

    if not (user_ids or driver_ids or role_filter):
        # Fall back to audience-based role filter
        if meta["audience"] == "admin":
            role_filter = ["admin"]
        elif meta["audience"] == "driver":
            role_filter = ["driver"]
        else:
            role_filter = ["admin", "manager", "driver"]

    title, body, data, category = meta["render"](payload)
    data = {**(data or {}), "event": event, "payload": payload}

    # Déduplication forte : une seule notification par dedup_key (retry / concurrence)
    log_id = None
    if dedup_key:
        log_id = str(uuid.uuid4())
        try:
            await db.notifications_log.insert_one({
                "id": log_id, "ts": datetime.now(timezone.utc).isoformat(),
                "tenant_id": tenant_id, "event": event,
                "dedup_key": dedup_key, "status": "processing",
            })
        except DuplicateKeyError:
            logger.info("dispatch: %s déjà notifié (dedup %s) — ignoré", event, dedup_key)
            return {"event": event, "skipped": "duplicate", "dedup_key": dedup_key,
                    "targets": 0, "inapp_created": 0}

    targets = await _resolve_targets(
        db, event, tenant_id, user_ids, driver_ids, role_filter,
        keep_all=bool(meta.get("inapp")),
    )

    # Centre de notifications in-app (une entrée par destinataire, immédiate, dédupliquée)
    inapp_created = 0
    if meta.get("inapp") and targets:
        now_iso = datetime.now(timezone.utc).isoformat()
        link = (data or {}).get("link")
        for t in targets:
            doc = {
                "id": str(uuid.uuid4()), "user_id": t["user_id"],
                "tenant_id": tenant_id,
                "event": event, "title": title, "body": body, "link": link,
                "data": {k: v for k, v in (data or {}).items() if k != "payload"},
                "read": False, "created_at": now_iso,
            }
            if dedup_key:
                doc["dedup_key"] = dedup_key
            try:
                await db.user_notifications.insert_one(doc)
                inapp_created += 1
            except DuplicateKeyError:
                pass  # déjà notifié pour cet utilisateur

    # Aggregate all push tokens across targets (deduplicated)
    all_tokens: list[str] = []
    push_users = 0
    email_users = 0
    sms_users = 0
    for t in targets:
        if t["channels"]["push"]:
            push_users += 1
            for tok in t["push_tokens"]:
                if tok not in all_tokens:
                    all_tokens.append(tok)
        if t["channels"]["email"]:
            email_users += 1
        if t["channels"]["sms"]:
            sms_users += 1

    push_summary = {"sent": 0, "failed": 0, "dead_tokens": []}
    if all_tokens:
        push_summary = await send_to_tokens(
            all_tokens, title, body, data=data, category=category,
        )

    if email_users:
        if meta.get("email_real"):
            from app.emailer import send_email
            link = (data or {}).get("link") or "/livre"
            for t in targets:
                if t["channels"]["email"] and t.get("user_email"):
                    await send_email(
                        t["user_email"], title, body,
                        f"<p>{body.replace(chr(10), '<br/>')}</p>"
                        f"<p>Ouvrez Journal de bord ({link}) pour traiter l'alerte.</p>")
        else:
            logger.info("📧 [email STUB] %s → %d user(s) — %s", event, email_users, title)
    if sms_users:
        logger.info("✉️  [sms STUB] %s → %d user(s) — %s", event, sms_users, title)

    log_fields = {
        "title": title,
        "body": body,
        "data": data,
        "targeted_users": len(targets),
        "inapp_created": inapp_created,
        "push_sent": push_summary.get("sent"),
        "push_failed": push_summary.get("failed"),
        "email_planned": email_users,
        "sms_planned": sms_users,
    }
    if log_id:
        await db.notifications_log.update_one(
            {"id": log_id}, {"$set": {**log_fields, "status": "sent"}})
    else:
        await db.notifications_log.insert_one({
            "ts": datetime.now(timezone.utc).isoformat(),
            "tenant_id": tenant_id,
            "event": event,
            **log_fields,
        })

    return {
        "event": event,
        "title": title,
        "body": body,
        "targets": len(targets),
        "inapp_created": inapp_created,
        "push": push_summary,
        "email_users": email_users,
        "sms_users": sms_users,
    }


async def ensure_notification_indexes(raw_db):
    await raw_db.user_notifications.create_index(
        [("user_id", 1), ("dedup_key", 1)], unique=True,
        partialFilterExpression={"dedup_key": {"$exists": True}})
    await raw_db.user_notifications.create_index(
        [("user_id", 1), ("read", 1), ("created_at", -1)])
    await raw_db.notifications_log.create_index(
        [("tenant_id", 1), ("event", 1), ("dedup_key", 1)], unique=True,
        partialFilterExpression={"dedup_key": {"$exists": True}})
