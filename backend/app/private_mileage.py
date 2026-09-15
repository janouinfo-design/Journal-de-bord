"""Sessions kilométriques PRIVÉES basées sur l'odomètre matériel AVL16 (READ-ONLY côté device).

Contexte terrain (FMC130 781479) : en mode PRIVÉ le GPS est masqué, mais l'AVL16
(Teltonika Total Odometer, sensor `avl_io_16`) continue d'augmenter. Les km privés
fiables proviennent donc du DELTA d'odomètre AVL16 entre l'entrée et la sortie du
mode privé, jamais des points GPS.

Ce module possède la collection append-only `private_mileage_session` (historique
requêtable, 1 doc par session privée) et l'agrégateur par période avec CUTOVER
(transition douce GPS legacy -> AVL16, intervalles temporels DISJOINTS, jamais de
double comptage).

RÈGLES CLÉS
- Q4b : START capturé au moment où la commande PRIVATE est réellement acceptée/envoyée
  (dernier AVL16 frais avant bascule), PAS à la confirmation (qui peut manquer).
- END symétrique : candidat END capturé à l'envoi accepté du BUSINESS ; la confirmation
  améliore la qualité mais n'est pas l'unique moyen de préserver les km.
- null != 0. Aucune valeur inventée. Delta négatif (reset/rollover) -> refus.
- Idempotence garantie EN BASE via un index unique partiel sur les sessions OPEN.
- Feature-flag `PRIVATE_KM_SOURCE_AVL16` (défaut 0) : OFF => aucun changement de
  comportement (les hooks n'écrivent rien, l'agrégat reste GPS legacy).

Aucune écriture device, aucune commande Navixy/Teltonika, aucun secret.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

COLLECTION = "private_mileage_session"

# États de session (machine append-only).
S_OPEN = "OPEN"
S_CLOSED = "CLOSED"
S_ABANDONED = "ABANDONED"

# Qualité du calcul de distance.
Q_OK = "OK"
Q_DEGRADED = "DEGRADED"
Q_UNAVAILABLE = "UNAVAILABLE"

# Provenance de la valeur km d'une période (exposée à l'UI/rapports).
SRC_AVL16 = "AVL16"
SRC_GPS_FALLBACK = "GPS_FALLBACK"
SRC_MIXED = "MIXED_TRANSITION"
SRC_UNAVAILABLE = "UNAVAILABLE"


def enabled() -> bool:
    """Feature-flag global (défaut OFF -> aucun changement de comportement).
    Les tests peuvent l'activer explicitement dans l'environnement."""
    return os.environ.get("PRIVATE_KM_SOURCE_AVL16", "0").strip().lower() in ("1", "true", "yes", "on")


def cutover_at() -> Optional[datetime]:
    """Instant de bascule GPS legacy -> AVL16 (UTC aware) ou None si non défini.
    Avant cutover = km privés via GPS legacy ; après = via sessions AVL16.
    Si non défini alors que le flag est ON : l'AVL16 s'applique à toute la plage
    (comportement 'post-cutover partout')."""
    raw = (os.environ.get("PRIVATE_KM_AVL16_CUTOVER_AT") or "").strip()
    return _parse_ts(raw) if raw else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(ts) -> Optional[datetime]:
    """ISO / 'YYYY-MM-DD HH:MM:SS' / epoch -> datetime aware (UTC). None si invalide."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(ts).strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def private_distance(start_km, end_km) -> Optional[float]:
    """Distance privée = end - start. Conditions strictes ; jamais inventée.
    Delta négatif (reset odomètre / rollover) -> None (anomalie, non fourni)."""
    try:
        x = float(start_km)
        y = float(end_km)
    except (TypeError, ValueError):
        return None
    if y < x:
        return None
    return round(y - x, 3)


# ---------------------------------------------------------------------------
# Index Mongo — idempotence garantie EN BASE (pas seulement applicative).
# ---------------------------------------------------------------------------
async def ensure_indexes(db) -> None:
    """Crée les index de la collection. L'index UNIQUE PARTIEL sur (tenant, vehicle,
    tracker) filtré {state:OPEN} garantit qu'il ne peut exister qu'UNE session OPEN
    par véhicule/tracker, même sous concurrence (deux PRIVATE simultanés -> 1 seule)."""
    coll = db[COLLECTION]
    await coll.create_index(
        [("tenant_id", 1), ("vehicle_id", 1), ("tracker_id", 1)],
        unique=True,
        partialFilterExpression={"state": S_OPEN},
        name="uniq_open_session_per_vehicle_tracker",
    )
    await coll.create_index(
        [("tenant_id", 1), ("vehicle_id", 1), ("private_ended_at", 1)],
        name="agg_by_vehicle_ended",
    )
    await coll.create_index(
        [("tenant_id", 1), ("driver_id", 1), ("private_ended_at", 1)],
        name="agg_by_driver_ended",
    )
    await coll.create_index(
        [("tenant_id", 1), ("state", 1), ("private_started_at", 1)],
        name="scan_open_sessions",
    )


# ---------------------------------------------------------------------------
# Cycle de vie d'une session privée.
# ---------------------------------------------------------------------------
async def open_session(db, *, tenant_id: str, driver_id: Optional[str], vehicle_id: str,
                       tracker_id: Optional[int], odo_start: Optional[float],
                       start_source: str, start_sample_at: Optional[str],
                       command_sent_at: Optional[str]) -> Optional[str]:
    """Ouvre une session PRIVÉE (Q4b : à la commande PRIVATE réellement acceptée/envoyée).

    Idempotence garantie EN BASE : l'index unique partiel {state:OPEN} empêche une 2e
    session OPEN pour le même (tenant, vehicle, tracker). En cas de course, l'insert en
    double lève DuplicateKeyError -> on renvoie None (no-op honnête, pas d'exception).

    Avant d'ouvrir, toute session OPEN du MÊME véhicule mais d'un AUTRE tracker est
    marquée ABANDONED (changement de tracker -> pas de contamination).
    """
    if not enabled():
        return None
    coll = db[COLLECTION]
    tk = (int(tracker_id) if tracker_id is not None else None)
    # Anti-contamination : abandonner une OPEN résiduelle sur un AUTRE tracker.
    await coll.update_many(
        {"tenant_id": tenant_id, "vehicle_id": vehicle_id, "state": S_OPEN,
         "tracker_id": {"$ne": tk}},
        {"$set": {"state": S_ABANDONED, "reason": "TRACKER_CHANGE", "updated_at": _now()}},
    )
    # Résoudre une OPEN résiduelle du MÊME tracker AVANT d'ouvrir (sinon l'index unique
    # partiel bloquerait la nouvelle session et l'ancien odometer_start contaminerait) :
    #  - si un candidat END existe -> clôture DEGRADED honnête (le OFF avait été envoyé) ;
    #  - sinon -> ABANDONED (SUPERSEDED_NEW_PRIVATE). Jamais de fausse confirmation.
    residual = await coll.find_one(
        {"tenant_id": tenant_id, "vehicle_id": vehicle_id, "tracker_id": tk, "state": S_OPEN},
        {"_id": 0})
    if residual:
        if residual.get("odometer_end_candidate_km") is not None:
            await close_from_candidate(
                db, tenant_id=tenant_id, vehicle_id=vehicle_id, tracker_id=tracker_id,
                confirmation_source="SUPERSEDED_NEW_PRIVATE")
        else:
            await coll.update_one(
                {"id": residual["id"], "state": S_OPEN},
                {"$set": {"state": S_ABANDONED, "reason": "SUPERSEDED_NEW_PRIVATE",
                          "updated_at": _now()}})
    sid = str(uuid.uuid4())
    doc = {
        "id": sid, "tenant_id": tenant_id, "driver_id": driver_id,
        "vehicle_id": vehicle_id, "tracker_id": tk,
        "state": S_OPEN,
        "private_started_at": _now(),
        "start_source": start_source,
        "odometer_start_km": odo_start,          # null reste null
        "start_sample_at": start_sample_at,
        "command_sent_at": command_sent_at,
        # candidats END (remplis à l'envoi BUSINESS) :
        "odometer_end_candidate_km": None,
        "end_candidate_sample_at": None,
        "business_command_sent_at": None,
        # finaux (remplis à la fermeture) :
        "private_ended_at": None, "odometer_end_km": None, "end_source": None,
        "private_km": None, "quality": None, "reason": None,
        "confirmation_source": None,
        "created_at": _now(), "updated_at": _now(),
    }
    try:
        await coll.insert_one(doc)
        return sid
    except Exception as e:  # DuplicateKeyError (VRAIE course concurrente) -> no-op idempotent
        if e.__class__.__name__ == "DuplicateKeyError":
            logger.info("private_mileage: OPEN concurrente détectée (idempotent) vehicle=%s", vehicle_id)
            return None
        raise


async def capture_end_candidate(db, *, tenant_id: str, vehicle_id: str,
                                tracker_id: Optional[int], odo_end_candidate: Optional[float],
                                end_candidate_sample_at: Optional[str],
                                business_command_sent_at: Optional[str]) -> None:
    """Enregistre un CANDIDAT END au moment où la commande BUSINESS est acceptée/envoyée
    (symétrie avec Q4b). Ne ferme PAS la session. Sert de filet si la confirmation manque."""
    if not enabled():
        return
    await db[COLLECTION].update_one(
        {"tenant_id": tenant_id, "vehicle_id": vehicle_id,
         "tracker_id": (int(tracker_id) if tracker_id is not None else None), "state": S_OPEN},
        {"$set": {"odometer_end_candidate_km": odo_end_candidate,
                  "end_candidate_sample_at": end_candidate_sample_at,
                  "business_command_sent_at": business_command_sent_at,
                  "updated_at": _now()}},
    )


def _finalize_fields(odo_start, odo_end, end_source, confirmation_source, degraded: bool) -> dict:
    """Calcule private_km + quality de façon fail-closed (null != 0)."""
    if odo_end is None or odo_start is None:
        return {"private_km": None, "quality": Q_UNAVAILABLE,
                "reason": "ODOMETER_MISSING"}
    dist = private_distance(odo_start, odo_end)
    if dist is None:
        return {"private_km": None, "quality": Q_UNAVAILABLE, "reason": "NEGATIVE_DELTA"}
    return {"private_km": dist, "quality": Q_DEGRADED if degraded else Q_OK, "reason": None}


async def close_session(db, *, tenant_id: str, vehicle_id: str, tracker_id: Optional[int],
                        odo_end: Optional[float] = None, end_source: str = "AVL16",
                        confirmation_source: Optional[str] = None,
                        degraded: bool = False) -> Optional[str]:
    """Ferme la session OPEN (idempotent : no-op si aucune OPEN).

    BORNE DE FIN AUTORITATIVE = le CANDIDAT END capturé au moment du privatemode OFF
    (odometer_end_candidate_km / business_command_sent_at). `odo_end` n'est qu'un REPLI
    utilisé UNIQUEMENT si aucun candidat n'existe. Ceci garantit qu'AUCUN kilomètre
    parcouru APRÈS le OFF (ex. trajet professionnel entre OFF et confirmation asynchrone)
    n'entre dans private_km. private_ended_at reflète la borne OFF, pas l'heure de
    confirmation. private_km = end - start (fail-closed). Ne prolonge jamais la distance."""
    if not enabled():
        return None
    coll = db[COLLECTION]
    sess = await coll.find_one(
        {"tenant_id": tenant_id, "vehicle_id": vehicle_id,
         "tracker_id": (int(tracker_id) if tracker_id is not None else None), "state": S_OPEN},
        {"_id": 0})
    if not sess:
        return None  # idempotent : déjà fermée / inexistante
    # Le candidat (OFF) prime ; repli sur odo_end seulement s'il n'y a pas de candidat.
    candidate = sess.get("odometer_end_candidate_km")
    used_candidate = candidate is not None
    end_km = candidate if used_candidate else odo_end
    # ended_at = borne OFF (business_command_sent_at / end_candidate_sample_at), jamais now().
    ended_at = (sess.get("business_command_sent_at")
                or sess.get("end_candidate_sample_at")
                or _now())
    fin = _finalize_fields(sess.get("odometer_start_km"), end_km, end_source,
                           confirmation_source, degraded)
    await coll.update_one(
        {"id": sess["id"], "state": S_OPEN},   # garde-fou : ne ferme que si TOUJOURS OPEN
        {"$set": {"state": S_CLOSED, "private_ended_at": ended_at,
                  "odometer_end_km": end_km,
                  "end_source": (end_source if used_candidate else (end_source + "_FALLBACK")),
                  "confirmation_source": confirmation_source,
                  "updated_at": _now(), **fin}},
    )
    return sess["id"]


async def close_from_candidate(db, *, tenant_id: str, vehicle_id: str,
                               tracker_id: Optional[int], confirmation_source: Optional[str]) -> Optional[str]:
    """Clôture DEGRADED depuis le candidat END (BUSINESS envoyé mais confirmation
    jamais obtenue, retour ultérieurement plausible). Jamais de fausse confirmation."""
    if not enabled():
        return None
    coll = db[COLLECTION]
    sess = await coll.find_one(
        {"tenant_id": tenant_id, "vehicle_id": vehicle_id,
         "tracker_id": (int(tracker_id) if tracker_id is not None else None), "state": S_OPEN},
        {"_id": 0})
    if not sess or sess.get("odometer_end_candidate_km") is None:
        return None
    return await close_session(
        db, tenant_id=tenant_id, vehicle_id=vehicle_id, tracker_id=tracker_id,
        odo_end=sess.get("odometer_end_candidate_km"),
        end_source=(sess.get("end_source") or "AVL16_CANDIDATE"),
        confirmation_source=confirmation_source, degraded=True)


# ---------------------------------------------------------------------------
# Agrégation par période AVEC CUTOVER (intervalles disjoints, pas de double comptage).
# ---------------------------------------------------------------------------
async def _sum_avl16_km(db, *, tenant_id: str, vehicle_id: str,
                        start_utc: datetime, end_utc: datetime) -> tuple[Optional[float], int]:
    """Somme des private_km des sessions CLOSED rattachées à [start,end] par private_ended_at.

    NULL != 0 : une somme numérique n'est renvoyée QUE si au moins une session CLOSED porte
    un private_km NUMÉRIQUE. Des sessions CLOSED ayant toutes private_km=None (indisponible)
    -> retour (None, n) ; ne JAMAIS produire 0.0/AVL16 à partir d'indisponibilités.
    Retourne (somme_numérique|None, count_total_sessions)."""
    coll = db[COLLECTION]
    q = {"tenant_id": tenant_id, "vehicle_id": vehicle_id, "state": S_CLOSED,
         "private_ended_at": {"$gte": start_utc.isoformat(), "$lte": end_utc.isoformat()}}
    total = None
    n = 0            # sessions CLOSED trouvées
    numeric = 0      # dont private_km numérique
    async for s in coll.find(q, {"_id": 0, "private_km": 1}):
        n += 1
        km = s.get("private_km")
        if isinstance(km, (int, float)):
            numeric += 1
            total = (total or 0.0) + float(km)
    if numeric == 0:
        return None, n   # aucune valeur exploitable -> indisponible (jamais 0 inventé)
    return round(total, 1), n


async def aggregate_private_km(
    db, *, tenant_id: str, vehicle_id: str,
    start_utc: datetime, end_utc: datetime,
    gps_fallback_km: Callable[[datetime, datetime], Awaitable[Optional[float]]],
) -> dict:
    """Km privés d'une période [start_utc, end_utc] (UTC aware).

    - Flag OFF  -> GPS legacy sur toute la plage (aucun changement de comportement).
    - Flag ON   -> découpage par CUTOVER (intervalles DISJOINTS) :
        * partie AVANT cutover  -> GPS legacy  (gps_fallback_km sur [start, min(end,cutover)])
        * partie APRÈS cutover  -> sessions AVL16 (rattachées par private_ended_at)
      Provenance : AVL16 | GPS_FALLBACK | MIXED_TRANSITION | UNAVAILABLE.
      Post-cutover SANS session AVL16 -> UNAVAILABLE (null), jamais un GPS silencieux.
    null != 0. Retourne {private_km, private_km_source, session_count, avl16_km, gps_km}.
    """
    # Flag OFF -> comportement legacy strict (GPS).
    if not enabled():
        gps = await gps_fallback_km(start_utc, end_utc)
        return {"private_km": gps, "private_km_source": SRC_GPS_FALLBACK,
                "session_count": 0, "avl16_km": None, "gps_km": gps}

    cut = cutover_at()

    # Pas de cutover défini -> AVL16 s'applique à toute la plage (post-cutover partout).
    if cut is None:
        avl, n = await _sum_avl16_km(db, tenant_id=tenant_id, vehicle_id=vehicle_id,
                                     start_utc=start_utc, end_utc=end_utc)
        if avl is not None:                       # null != 0 : nombre exploitable requis
            return {"private_km": avl, "private_km_source": SRC_AVL16,
                    "session_count": n, "avl16_km": avl, "gps_km": None}
        return {"private_km": None, "private_km_source": SRC_UNAVAILABLE,
                "session_count": n, "avl16_km": None, "gps_km": None}

    # Cas 1 : période ENTIÈREMENT pré-cutover -> GPS legacy.
    if end_utc <= cut:
        gps = await gps_fallback_km(start_utc, end_utc)
        return {"private_km": gps, "private_km_source": SRC_GPS_FALLBACK,
                "session_count": 0, "avl16_km": None, "gps_km": gps}

    # Cas 2 : période ENTIÈREMENT post-cutover -> AVL16 (ou UNAVAILABLE, jamais GPS).
    if start_utc >= cut:
        avl, n = await _sum_avl16_km(db, tenant_id=tenant_id, vehicle_id=vehicle_id,
                                     start_utc=start_utc, end_utc=end_utc)
        if avl is not None:                       # null != 0
            return {"private_km": avl, "private_km_source": SRC_AVL16,
                    "session_count": n, "avl16_km": avl, "gps_km": None}
        return {"private_km": None, "private_km_source": SRC_UNAVAILABLE,
                "session_count": n, "avl16_km": None, "gps_km": None}

    # Cas 3 : période TRAVERSANT le cutover -> MIXED (intervalles disjoints).
    # FAIL-CLOSED : les DEUX portions doivent être mesurables. Si la portion AVL16
    # post-cutover est indisponible (aucune session numérique), on NE remplace PAS par 0
    # et on N'annonce PAS un total MIXED partiel : la période n'est pas entièrement
    # connue -> UNAVAILABLE (null). Idem si le GPS legacy est indisponible.
    gps = await gps_fallback_km(start_utc, cut)          # [start, cutover)
    avl, n = await _sum_avl16_km(db, tenant_id=tenant_id, vehicle_id=vehicle_id,
                                 start_utc=cut, end_utc=end_utc)  # [cutover, end]
    if not isinstance(gps, (int, float)) or not isinstance(avl, (int, float)):
        return {"private_km": None, "private_km_source": SRC_UNAVAILABLE,
                "session_count": n, "avl16_km": avl, "gps_km": gps}
    total = round(float(gps) + float(avl), 1)
    return {"private_km": total, "private_km_source": SRC_MIXED,
            "session_count": n, "avl16_km": avl, "gps_km": gps}


# ---------------------------------------------------------------------------
# Agrégation MULTI-VÉHICULE (rapports flotte/chauffeur). Réutilise STRICTEMENT
# l'agrégateur canonique par véhicule ci-dessus (aucune 2e logique AVL16).
# ---------------------------------------------------------------------------
async def aggregate_private_km_for_scope(
    db, *, tenant_id: str, vehicle_ids: list[str],
    start_utc: datetime, end_utc: datetime,
    gps_fallback_km_for_vehicle: Callable[[str, datetime, datetime], Awaitable[Optional[float]]],
) -> dict:
    """Km privés agrégés sur un ENSEMBLE de véhicules (même politique cutover/fallback).

    - Somme les contributions numériques par véhicule (via aggregate_private_km).
    - Provenance flotte : AVL16 (que de l'AVL16), GPS_FALLBACK (que du GPS),
      MIXED_TRANSITION (mélange AVL16+GPS sur la fenêtre), UNAVAILABLE (aucune
      contribution numérique -> None, jamais 0 inventé).
    - null != 0 : si aucun véhicule ne produit de nombre -> private_km=None.
    """
    total = None
    n_sessions = 0
    saw_avl = saw_gps = saw_mixed = saw_unavail = False
    for vid in vehicle_ids:
        async def _gps(s, e, _vid=vid):
            return await gps_fallback_km_for_vehicle(_vid, s, e)
        r = await aggregate_private_km(
            db, tenant_id=tenant_id, vehicle_id=vid,
            start_utc=start_utc, end_utc=end_utc, gps_fallback_km=_gps)
        src = r.get("private_km_source")
        if src == SRC_AVL16:
            saw_avl = True
        elif src == SRC_GPS_FALLBACK:
            saw_gps = True
        elif src == SRC_MIXED:
            saw_mixed = True
        elif src == SRC_UNAVAILABLE:
            saw_unavail = True
        n_sessions += int(r.get("session_count") or 0)
        km = r.get("private_km")
        if isinstance(km, (int, float)):
            total = (total or 0.0) + float(km)
    # FAIL-CLOSED (donnée partielle) : si AU MOINS UN véhicule du scope est UNAVAILABLE,
    # le total flotte n'est PAS entièrement mesurable -> on ne sous-compte pas silencieusement.
    # -> private_km=None, source=UNAVAILABLE tant que TOUT le scope requis n'est pas mesurable.
    if saw_unavail:
        return {"private_km": None, "private_km_source": SRC_UNAVAILABLE,
                "session_count": n_sessions}
    # Provenance agrégée (tous les véhicules mesurables).
    if saw_mixed or (saw_avl and saw_gps):
        source = SRC_MIXED
    elif saw_avl:
        source = SRC_AVL16
    elif saw_gps:
        source = SRC_GPS_FALLBACK
    else:
        source = SRC_UNAVAILABLE
    if total is None:
        source = SRC_UNAVAILABLE
    return {"private_km": (round(total, 1) if total is not None else None),
            "private_km_source": source, "session_count": n_sessions}
