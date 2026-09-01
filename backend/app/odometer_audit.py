"""Audit odomètre — lecture READ-ONLY de l'odomètre matériel via Navixy.

Objectif (Phase audit) : exposer une lecture FIABLE et HONNÊTE de l'odomètre d'un
véhicule, sans jamais fabriquer de donnée.

RÈGLES STRICTES :
- Aucune écriture (pas de counter/value/set).
- Aucune estimation GPS : on ne lit QUE le compteur hardware Navixy (issu du
  Total Odometer Teltonika si Navixy l'utilise comme source).
- Si la donnée n'est pas disponible (Navixy non configuré, tracker absent,
  compteur vide) → status "UNAVAILABLE" et odometer_km = null. JAMAIS 0.
- Contrôles d'intégrité : donnée périmée (STALE) signalée, pas de calcul entre
  deux trackers différents.

Priorité de source (voir prompt §21). On ne classe une source comme HARDWARE que
si Navixy la fournit réellement ; sinon on reste transparent.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from app.navixy_client import get_counter_value, get_counters, is_configured, NavixyError

# Au-delà de ce délai, la lecture odomètre est considérée « périmée » (STALE).
ODOMETER_STALE_AFTER = timedelta(hours=24)


def _parse_ts(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _extract_odometer(payload: dict) -> tuple[Optional[float], Optional[str]]:
    """Extrait (valeur_km, timestamp_iso) d'une réponse Navixy counters, de façon
    tolérante aux variations de schéma. Retourne (None, None) si introuvable.
    """
    if not isinstance(payload, dict):
        return None, None

    # Forme 1 : counter/value/get -> {"success":true,"value":<km>, "update_time": "..."}
    if "value" in payload and not isinstance(payload.get("value"), (dict, list)):
        try:
            return float(payload["value"]), payload.get("update_time") or payload.get("time")
        except (TypeError, ValueError):
            return None, None

    # Forme 2 : get_counters -> liste de compteurs
    candidates = payload.get("counters") or payload.get("list") or []
    if isinstance(candidates, dict):
        candidates = list(candidates.values())
    for c in candidates or []:
        if not isinstance(c, dict):
            continue
        ctype = (c.get("type") or c.get("name") or "").lower()
        if "odom" in ctype:
            raw = c.get("value")
            ts = c.get("update_time") or c.get("time")
            try:
                return (float(raw) if raw is not None else None), ts
            except (TypeError, ValueError):
                return None, ts
    return None, None


async def read_vehicle_odometer(tracker_id: Optional[int]) -> dict:
    """Lit l'odomètre matériel d'un véhicule via Navixy (READ-ONLY).

    Retour normalisé (jamais de 0 fictif) :
      {odometer_km, source, timestamp, status, fresh}
    status ∈ {REAL, UNAVAILABLE, STALE, ERROR}
    """
    base = {
        "odometer_km": None,
        "source": None,
        "timestamp": None,
        "status": "UNAVAILABLE",
        "fresh": False,
    }

    if not is_configured():
        # NAVIXY_HASH absent -> on ne peut rien lire. On reste honnête.
        return {**base, "status": "UNAVAILABLE", "reason": "navixy_not_configured"}

    if not tracker_id:
        return {**base, "status": "UNAVAILABLE", "reason": "no_tracker_mapped"}

    # Lecture réelle (odomètre matériel). On tente la valeur ciblée puis le bulk.
    try:
        try:
            resp = await get_counter_value(int(tracker_id), "odometer")
        except NavixyError:
            resp = await get_counters(int(tracker_id))
    except NavixyError as e:
        return {**base, "status": "ERROR", "reason": str(e)}
    except Exception as e:  # réseau / timeout
        return {**base, "status": "ERROR", "reason": f"navixy_unreachable: {e}"}

    km, ts = _extract_odometer(resp)
    if km is None:
        return {**base, "status": "UNAVAILABLE", "reason": "counter_empty"}

    dt = _parse_ts(ts)
    fresh = bool(dt and (datetime.now(timezone.utc) - dt) <= ODOMETER_STALE_AFTER)
    status = "REAL" if fresh else ("STALE" if dt else "REAL")
    return {
        "odometer_km": round(km, 1),
        # Source affichée : compteur Navixy (alimenté par le Total Odometer Teltonika
        # si Navixy est configuré ainsi). La provenance fine reste à valider terrain.
        "source": "NAVIXY_COUNTER",
        "timestamp": ts,
        "status": status,
        "fresh": fresh,
    }
