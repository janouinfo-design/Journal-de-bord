#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOGITRAK — SIMULATION VOLET 2 (resolver multi-source moderne) — 100% READ-ONLY.

AUCUNE ÉCRITURE : ce script n'exécute QUE des .find(). Aucun insert/update/delete,
aucun bulk_write, aucune migration, aucun reassign_all_trips(), aucun to_date écrit.

But : comparer, SANS rien modifier, trois valeurs par trajet :
    STORED   = trips.driver_id (déjà en base ; sert UNIQUEMENT de comparaison)
    V1       = resolver legacy time-aware actuel (Volet 1, déjà en PROD)
    V2       = resolver multi-source moderne simulé (cible Volet 2)

Règles (validées) :
- Source temporelle moderne = vehicle_assignment_events, timestamp métier `at`,
  uniquement result == "OK". Scope strict par (tenant_id, driver_id).
- Segments modernes en convention [start, end) (début inclusif, fin exclusive).
  TAKEN -> ouvre ; CHANGED -> ferme+ouvre ; RELEASED/FORCE_RELEASED -> ferme.
- modern_since(driver) = `at` du 1er event OK du chauffeur.
- Resolver V2 (par trajet (tenant, vehicle, start)) :
    1) segment moderne du VÉHICULE couvrant start :
         exactement 1 -> MODERN_SEGMENT (driver du segment)
         >= 2         -> CONFLICT_NONE (jamais deviner)
         0            -> étape 2
    2) candidat legacy = V1 (non-primary daté couvrant, sinon primary time-aware,
       sinon None).
    3) candidat legacy None -> NO_RELATION_NONE (None)
    4) candidat legacy présent :
         si trip_start >= modern_since(candidat) -> MODERN_GAP_NONE (None, PAS de legacy)
         sinon / pas de modern_since             -> LEGACY_PRE_MODERN (candidat)
- GÉNÉRIQUE : aucun ID codé en dur. IDs stables uniquement (tenant/driver/vehicle).
- Anomalies signalées, JAMAIS réparées ni interprétées.

Options facultatives via variables d'environnement (vides par défaut -> aucun code
spécial ; rien n'est inventé) :
    PILOT_DRIVER_IDS   = "id1,id2,..."  (pilotes : impact mis en évidence)
    WITNESS_PAIRS      = "driverId:vehicleId,..." (cas témoins à afficher)
    WITNESS_TRIP_IDS   = "tripId1,tripId2,..."
    SIM_SAMPLE_LIMIT   = nb d'exemples par catégorie (défaut 8)
"""
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from pymongo import MongoClient

# ---------------------------------------------------------------------------
# Constantes métier (alignées sur app/vehicle_assignment.py et app/assignments.py)
# ---------------------------------------------------------------------------
RESULT_OK = "OK"
EV_TAKE = "VEHICLE_TAKEN"
EV_END = "VEHICLE_RELEASED"
EV_CHANGE = "VEHICLE_CHANGED"
EV_FORCE = "VEHICLE_FORCE_RELEASED"
OPEN_TYPES = {EV_TAKE}
CLOSE_TYPES = {EV_END, EV_FORCE}
CHANGE_TYPES = {EV_CHANGE}
RELEVANT_TYPES = OPEN_TYPES | CLOSE_TYPES | CHANGE_TYPES

POS_INF = "9999-12-31T23:59:59+00:00"  # borne haute pour segment open-ended (comparaison ISO)

SAMPLE_LIMIT = int(os.environ.get("SIM_SAMPLE_LIMIT", "8"))


def _env_list(name):
    raw = os.environ.get(name, "").strip()
    return [x.strip() for x in raw.split(",") if x.strip()] if raw else []


PILOT_DRIVER_IDS = set(_env_list("PILOT_DRIVER_IDS"))
WITNESS_TRIP_IDS = set(_env_list("WITNESS_TRIP_IDS"))
WITNESS_PAIRS = set(_env_list("WITNESS_PAIRS"))  # "driver:vehicle"


# ---------------------------------------------------------------------------
# Helpers temporels (comparaison ISO lexicographique = correcte si tz identique).
# On normalise en ISO UTC pour fiabiliser les comparaisons.
# ---------------------------------------------------------------------------
def _norm(ts):
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Resolver LEGACY (reproduit fidèlement le Volet 1 PROD de assignments.py).
# ---------------------------------------------------------------------------
def _in_window(trip_iso, asg):
    # non-primary : convention [from, to] INCLUSIVE (identique au PROD)
    if not trip_iso:
        return False
    f, t = asg.get("from_date"), asg.get("to_date")
    if f and trip_iso < f:
        return False
    if t and trip_iso > t:
        return False
    return True


def _covers_primary(trip_iso, asg):
    # primary : convention [start, end) (Volet 1)
    if not trip_iso:
        return False
    f, t = asg.get("from_date"), asg.get("to_date")
    if f and trip_iso < f:
        return False
    if t and trip_iso >= t:
        return False
    return True


def resolve_legacy_v1(asgs_for_vehicle, trip_iso):
    """asgs_for_vehicle : liste d'assignments (legacy) pour CE véhicule, CE tenant.
    Reproduit resolve_driver_for_trip (Volet 1) : None si rien ne couvre."""
    if not asgs_for_vehicle:
        return None
    matches = [a for a in asgs_for_vehicle
               if not a.get("is_primary") and _in_window(trip_iso, a)]
    if matches:
        matches.sort(key=lambda a: a.get("from_date") or "", reverse=True)
        return matches[0].get("driver_id")
    for a in asgs_for_vehicle:
        if a.get("is_primary") and _covers_primary(trip_iso, a):
            return a.get("driver_id")
    return None


# ---------------------------------------------------------------------------
# Reconstruction des segments modernes par (tenant, driver) depuis les events OK.
# Retourne : segments (liste), anomalies (liste), modern_since (dict), meta.
# ---------------------------------------------------------------------------
def rebuild_segments(events_by_driver):
    """events_by_driver : {driver_id: [event, ...]} (déjà filtrés OK + triés par at).
    Segment = {driver_id, vehicle_id, start, end}  (end=None -> open-ended)."""
    all_segments = []
    anomalies = []
    modern_since = {}
    per_driver_meta = {}

    for driver_id, evs in events_by_driver.items():
        # events déjà triés par at asc
        first_at = evs[0]["_at"] if evs else None
        last_at = evs[-1]["_at"] if evs else None
        modern_since[driver_id] = first_at
        open_seg = None  # {vehicle_id, start}
        driver_segments = []
        prev_at = None

        for ev in evs:
            at = ev["_at"]
            typ = ev.get("type")
            fv = ev.get("from_vehicle_id")
            tv = ev.get("to_vehicle_id")

            # garde-fous structurels (signalés, jamais réparés)
            if at is None:
                anomalies.append({"driver_id": driver_id, "kind": "EVENT_NO_AT",
                                  "event_id": ev.get("id"), "type": typ})
                continue
            if prev_at is not None and at == prev_at:
                anomalies.append({"driver_id": driver_id, "kind": "SAME_TIMESTAMP",
                                  "event_id": ev.get("id"), "at": at, "type": typ})
            prev_at = at

            if typ in OPEN_TYPES:  # VEHICLE_TAKEN
                if not tv:
                    anomalies.append({"driver_id": driver_id, "kind": "TAKE_NO_VEHICLE",
                                      "event_id": ev.get("id"), "at": at})
                    continue
                if open_seg is not None:
                    anomalies.append({"driver_id": driver_id, "kind": "TAKE_WHILE_OPEN",
                                      "event_id": ev.get("id"), "at": at,
                                      "open_vehicle": open_seg["vehicle_id"], "take_vehicle": tv})
                    # fermeture défensive de l'ancien à `at` (documentée, non "réparée")
                    driver_segments.append({"driver_id": driver_id,
                                            "vehicle_id": open_seg["vehicle_id"],
                                            "start": open_seg["start"], "end": at,
                                            "anomalous": True})
                open_seg = {"vehicle_id": tv, "start": at}

            elif typ in CHANGE_TYPES:  # VEHICLE_CHANGED (défensif, non présent en PROD actuelle)
                if not tv:
                    anomalies.append({"driver_id": driver_id, "kind": "CHANGE_NO_TARGET",
                                      "event_id": ev.get("id"), "at": at})
                    continue
                if open_seg is None:
                    anomalies.append({"driver_id": driver_id, "kind": "CHANGE_WHILE_CLOSED",
                                      "event_id": ev.get("id"), "at": at, "to_vehicle": tv})
                    open_seg = {"vehicle_id": tv, "start": at}
                    continue
                if fv and open_seg["vehicle_id"] != fv:
                    anomalies.append({"driver_id": driver_id, "kind": "CHANGE_FROM_MISMATCH",
                                      "event_id": ev.get("id"), "at": at,
                                      "open_vehicle": open_seg["vehicle_id"], "from_vehicle": fv})
                driver_segments.append({"driver_id": driver_id,
                                        "vehicle_id": open_seg["vehicle_id"],
                                        "start": open_seg["start"], "end": at,
                                        "anomalous": False})
                open_seg = {"vehicle_id": tv, "start": at}

            elif typ in CLOSE_TYPES:  # VEHICLE_RELEASED / VEHICLE_FORCE_RELEASED
                if open_seg is None:
                    anomalies.append({"driver_id": driver_id, "kind": "RELEASE_WHILE_CLOSED",
                                      "event_id": ev.get("id"), "at": at, "from_vehicle": fv})
                    continue
                if fv and open_seg["vehicle_id"] != fv:
                    anomalies.append({"driver_id": driver_id, "kind": "RELEASE_FROM_MISMATCH",
                                      "event_id": ev.get("id"), "at": at,
                                      "open_vehicle": open_seg["vehicle_id"], "from_vehicle": fv})
                driver_segments.append({"driver_id": driver_id,
                                        "vehicle_id": open_seg["vehicle_id"],
                                        "start": open_seg["start"], "end": at,
                                        "anomalous": False})
                open_seg = None

        # segment resté ouvert -> open-ended (couvre jusqu'à +inf)
        if open_seg is not None:
            driver_segments.append({"driver_id": driver_id,
                                    "vehicle_id": open_seg["vehicle_id"],
                                    "start": open_seg["start"], "end": None,
                                    "anomalous": False})

        all_segments.extend(driver_segments)
        # trous = intervalles entre fin d'un segment et début du suivant
        gaps = 0
        ds_sorted = sorted(driver_segments, key=lambda s: s["start"])
        for i in range(1, len(ds_sorted)):
            prev_end = ds_sorted[i - 1]["end"]
            if prev_end is not None and ds_sorted[i]["start"] > prev_end:
                gaps += 1
        per_driver_meta[driver_id] = {
            "modern_since": first_at, "last_event_at": last_at,
            "n_events": len(evs), "n_segments": len(driver_segments), "gaps": gaps,
        }

    return all_segments, anomalies, modern_since, per_driver_meta


def _seg_covers(seg, trip_iso):
    """[start, end) — end=None => open-ended (couvre tout à partir de start)."""
    if trip_iso is None or seg["start"] is None:
        return False
    if trip_iso < seg["start"]:
        return False
    if seg["end"] is not None and trip_iso >= seg["end"]:
        return False
    return True


def main():
    t0 = time.time()
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERREUR: MONGO_URL ou DB_NAME absent de l'environnement.", file=sys.stderr)
        sys.exit(2)

    cli = MongoClient(mongo_url)
    db = cli[db_name]

    now_iso = datetime.now(timezone.utc).isoformat()
    d7 = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    # ---- 1) Charger tous les tenants présents (events + trips + assignments) ----
    tenants = set()
    for coll in ("vehicle_assignment_events", "trips", "assignments"):
        for t in db[coll].distinct("tenant_id"):
            if t:
                tenants.add(t)
    tenants = sorted(tenants)

    print("=" * 78)
    print("LOGITRAK — SIMULATION VOLET 2 (READ-ONLY) — resolver multi-source moderne")
    print("=" * 78)
    print(f"DB={db_name}  tenants={tenants}  now={now_iso}")
    print(f"PILOT_DRIVER_IDS={sorted(PILOT_DRIVER_IDS) or '(non fourni)'}")
    print(f"WITNESS_PAIRS={sorted(WITNESS_PAIRS) or '(non fourni)'}")
    print(f"WITNESS_TRIP_IDS={sorted(WITNESS_TRIP_IDS) or '(non fourni)'}")
    print("-" * 78)

    # Totaux globaux
    g_events = 0
    g_segments = 0
    g_modern_drivers = 0
    g_trips = 0
    cat_counts = defaultdict(int)
    three_way = {"V2_eq_V1": 0, "V2_diff_V1": 0, "V2_eq_STORED": 0, "V2_diff_STORED": 0}
    v1_to_v2_loss = defaultdict(int)   # driver -> nb trips perdus (driver->None) par V2
    v1_to_v2_gain = defaultdict(int)   # driver -> nb trips gagnés (None/other->driver) par V2
    v1_to_v2_moved = defaultdict(int)  # (from->to) driver->driver
    temporal = {"today": 0, "7d": 0, "30d": 0, "older": 0}
    km_impact = {"pro": 0.0, "private": 0.0, "unclassified": 0.0,
                 "to_none": 0.0, "driver_to_driver": 0.0}
    manual_impacted = 0   # auto_classified == False et V2 != V1
    pilot_impacted = 0
    mixed_mode = []       # (driver, vehicle, n_trips, km, first_start, last_start)
    mixed_agg = defaultdict(lambda: {"n": 0, "km": 0.0, "first": None, "last": None})
    all_anomalies = []
    samples = defaultdict(list)
    witness_rows = []

    for tenant in tenants:
        # ---- events OK, triés par at ----
        ev_cur = db.vehicle_assignment_events.find(
            {"tenant_id": tenant, "result": RESULT_OK, "type": {"$in": list(RELEVANT_TYPES)}},
            {"_id": 0, "id": 1, "driver_id": 1, "type": 1,
             "from_vehicle_id": 1, "to_vehicle_id": 1, "at": 1},
        )
        events_by_driver = defaultdict(list)
        for ev in ev_cur:
            ev["_at"] = _norm(ev.get("at"))
            events_by_driver[ev.get("driver_id")].append(ev)
            g_events += 1
        for d in events_by_driver:
            events_by_driver[d].sort(key=lambda e: e["_at"] or "")

        segments, anomalies, modern_since, per_driver_meta = rebuild_segments(events_by_driver)
        for a in anomalies:
            a["tenant_id"] = tenant
        all_anomalies.extend(anomalies)
        g_segments += len(segments)
        g_modern_drivers += len([d for d in modern_since if modern_since[d]])

        # index segments par vehicle
        segs_by_vehicle = defaultdict(list)
        for s in segments:
            segs_by_vehicle[s["vehicle_id"]].append(s)

        # ---- assignments legacy par vehicle ----
        asgs_by_vehicle = defaultdict(list)
        for a in db.assignments.find({"tenant_id": tenant},
                                     {"_id": 0, "vehicle_id": 1, "driver_id": 1,
                                      "from_date": 1, "to_date": 1, "is_primary": 1}):
            asgs_by_vehicle[a.get("vehicle_id")].append(a)

        # ---- trips ----
        tr_cur = db.trips.find(
            {"tenant_id": tenant},
            {"_id": 0, "id": 1, "vehicle_id": 1, "driver_id": 1, "start_time": 1,
             "distance_km": 1, "classification": 1, "auto_classified": 1},
        )
        for tr in tr_cur:
            g_trips += 1
            vid = tr.get("vehicle_id")
            stored = tr.get("driver_id")
            start = _norm(tr.get("start_time"))
            km = tr.get("distance_km") or 0.0
            cls = tr.get("classification")
            auto = tr.get("auto_classified")

            # ---- V1 (legacy time-aware actuel) ----
            v1 = resolve_legacy_v1(asgs_by_vehicle.get(vid, []), start)

            # ---- V2 (multi-source moderne) ----
            covering = [s for s in segs_by_vehicle.get(vid, []) if _seg_covers(s, start)]
            # dédoublonner par driver (un même driver ne peut couvrir qu'une fois un instant
            # en théorie ; plusieurs drivers couvrant = vrai conflit)
            cov_drivers = {s["driver_id"] for s in covering}
            if len(cov_drivers) == 1:
                v2 = next(iter(cov_drivers))
                cat = "MODERN_SEGMENT"
            elif len(cov_drivers) >= 2:
                v2 = None
                cat = "CONFLICT_NONE"
            else:
                # pas de segment moderne couvrant ce véhicule
                if v1 is None:
                    v2 = None
                    cat = "NO_RELATION_NONE"
                else:
                    ms = modern_since.get(v1)
                    if ms is not None and start is not None and start >= ms:
                        v2 = None
                        cat = "MODERN_GAP_NONE"
                        # cas "mixte" : chauffeur moderne, candidat legacy après modern_since
                        key = (v1, vid)
                        agg = mixed_agg[key]
                        agg["n"] += 1
                        agg["km"] += km
                        if agg["first"] is None or (start and start < agg["first"]):
                            agg["first"] = start
                        if agg["last"] is None or (start and start > agg["last"]):
                            agg["last"] = start
                    else:
                        v2 = v1
                        cat = "LEGACY_PRE_MODERN"

            cat_counts[cat] += 1

            # ---- comparaisons 3-way ----
            if v2 == v1:
                three_way["V2_eq_V1"] += 1
            else:
                three_way["V2_diff_V1"] += 1
            if v2 == stored:
                three_way["V2_eq_STORED"] += 1
            else:
                three_way["V2_diff_STORED"] += 1

            changed = (v2 != v1)
            if changed:
                # répartition temporelle du changement
                today_start = now_iso[:10] + "T00:00:00+00:00"
                if start and start >= today_start:  # aujourd'hui (depuis minuit UTC)
                    temporal["today"] += 1
                elif start and start >= d7:
                    temporal["7d"] += 1
                elif start and start >= d30:
                    temporal["30d"] += 1
                else:
                    temporal["older"] += 1

                # qui perd / qui gagne
                if v1 is not None and v2 is None:
                    v1_to_v2_loss[v1] += 1
                    km_impact["to_none"] += km
                elif v1 is None and v2 is not None:
                    v1_to_v2_gain[v2] += 1
                elif v1 is not None and v2 is not None and v1 != v2:
                    v1_to_v2_moved[(v1, v2)] += 1
                    km_impact["driver_to_driver"] += km

                # impact km par classe
                if cls == "professional":
                    km_impact["pro"] += km
                elif cls == "personal":
                    km_impact["private"] += km
                else:
                    km_impact["unclassified"] += km

                # garde-fous
                if auto is False:
                    manual_impacted += 1
                if (stored in PILOT_DRIVER_IDS) or (v1 in PILOT_DRIVER_IDS) or (v2 in PILOT_DRIVER_IDS):
                    pilot_impacted += 1

                # échantillons
                if len(samples[cat]) < SAMPLE_LIMIT:
                    samples[cat].append({
                        "trip": tr.get("id"), "vehicle": vid, "start": start,
                        "stored": stored, "v1": v1, "v2": v2, "km": km,
                        "class": cls, "auto_classified": auto,
                    })

            # témoins explicites
            pair = f"{stored}:{vid}" if stored else f"None:{vid}"
            pair_v1 = f"{v1}:{vid}" if v1 else None
            if (tr.get("id") in WITNESS_TRIP_IDS) or (pair in WITNESS_PAIRS) \
               or (pair_v1 and pair_v1 in WITNESS_PAIRS):
                witness_rows.append({
                    "trip": tr.get("id"), "vehicle": vid, "start": start,
                    "stored": stored, "v1": v1, "v2": v2, "cat": cat, "km": km,
                })

    # agrégation cas mixtes
    for (driver, vehicle), agg in mixed_agg.items():
        mixed_mode.append({"driver_id": driver, "vehicle_id": vehicle,
                           "n_trips": agg["n"], "km": round(agg["km"], 1),
                           "first_start": agg["first"], "last_start": agg["last"]})

    elapsed = round(time.time() - t0, 2)

    # =====================================================================
    # RAPPORT
    # =====================================================================
    print("INVENTAIRE")
    print(f"  events OK lus (TAKEN/RELEASED/CHANGED/FORCE) : {g_events}")
    print(f"  chauffeurs sous autorité moderne             : {g_modern_drivers}")
    print(f"  segments modernes reconstruits               : {g_segments}")
    print(f"  trips scannés                                : {g_trips}")
    print(f"  temps d'exécution                            : {elapsed}s")
    print("-" * 78)

    print("RÉPARTITION PAR SOURCE DE RÉSOLUTION V2")
    for c in ("MODERN_SEGMENT", "LEGACY_PRE_MODERN", "MODERN_GAP_NONE",
              "NO_RELATION_NONE", "CONFLICT_NONE"):
        print(f"  {c:<20} : {cat_counts.get(c, 0)}")
    print("-" * 78)

    print("COMPARAISON 3-WAY (STORED vs V1 vs V2)")
    print(f"  V2 == V1       : {three_way['V2_eq_V1']}")
    print(f"  V2 != V1       : {three_way['V2_diff_V1']}   <-- changements introduits par Volet 2")
    print(f"  V2 == STORED   : {three_way['V2_eq_STORED']}")
    print(f"  V2 != STORED   : {three_way['V2_diff_STORED']}")
    print("-" * 78)

    print("RÉPARTITION TEMPORELLE DES CHANGEMENTS V1->V2")
    print(f"  aujourd'hui : {temporal['today']}   7j : {temporal['7d']}   "
          f"30j : {temporal['30d']}   plus ancien : {temporal['older']}")
    print("-" * 78)

    print("IMPACT KM (sur trips où V2 != V1)")
    print(f"  km PRO concernés          : {round(km_impact['pro'], 1)}")
    print(f"  km PRIVÉ concernés        : {round(km_impact['private'], 1)}")
    print(f"  km non classés concernés  : {round(km_impact['unclassified'], 1)}")
    print(f"  km quittant un driver->None : {round(km_impact['to_none'], 1)}")
    print(f"  km driver->driver          : {round(km_impact['driver_to_driver'], 1)}")
    print("  (NB: classification/km NON modifiés par la simulation ; effet indirect km-summary à surveiller)")
    print("-" * 78)

    print("QUI PERD DES TRIPS (driver -> None) [top 15]")
    for d, n in sorted(v1_to_v2_loss.items(), key=lambda x: -x[1])[:15]:
        tag = " [PILOTE]" if d in PILOT_DRIVER_IDS else ""
        print(f"  {d} : {n}{tag}")
    print("QUI GAGNE DES TRIPS (None/autre -> driver) [top 15]")
    for d, n in sorted(v1_to_v2_gain.items(), key=lambda x: -x[1])[:15]:
        tag = " [PILOTE]" if d in PILOT_DRIVER_IDS else ""
        print(f"  {d} : {n}{tag}")
    print("MOUVEMENTS driver->driver [top 15]")
    for (a, b), n in sorted(v1_to_v2_moved.items(), key=lambda x: -x[1])[:15]:
        print(f"  {a} -> {b} : {n}")
    print("-" * 78)

    print("GARDE-FOUS")
    print(f"  trips MANUELS (auto_classified=False) impactés par V2 : {manual_impacted}")
    print(f"  trips PILOTES impactés par V2                         : {pilot_impacted}"
          + ("" if PILOT_DRIVER_IDS else "  (liste pilotes non fournie)"))
    print("-" * 78)

    print(f"CAS MIXTES (chauffeur moderne + candidat legacy après modern_since) : {len(mixed_mode)}")
    for row in sorted(mixed_mode, key=lambda r: -r["n_trips"])[:20]:
        print(f"  driver={row['driver_id']} vehicle={row['vehicle_id']} "
              f"trips={row['n_trips']} km={row['km']} "
              f"[{row['first_start']} .. {row['last_start']}]")
    print("-" * 78)

    print("FRONTIÈRES MODERNES PAR CHAUFFEUR (modern_since / #segments / premier-dernier / trous)")
    # réafficher depuis per_driver_meta de tous tenants : recharger agrégé rapide
    # (on réaffiche uniquement les infos déjà calculées par tenant plus haut n'est pas stocké
    #  globalement ; on recalcule un résumé compact ici)
    # -> pour rester READ-ONLY et simple, on affiche un comptage global.
    print(f"  (détail par chauffeur disponible : {g_modern_drivers} chauffeurs modernes)")
    print("-" * 78)

    print("ANOMALIES STRUCTURELLES (signalées, JAMAIS réparées)")
    if not all_anomalies:
        print("  aucune")
    else:
        kinds = defaultdict(int)
        for a in all_anomalies:
            kinds[a["kind"]] += 1
        for k, n in sorted(kinds.items(), key=lambda x: -x[1]):
            print(f"  {k} : {n}")
        for a in all_anomalies[:20]:
            print(f"    - {a}")
    print("-" * 78)

    print("ÉCHANTILLONS PAR CATÉGORIE DE CHANGEMENT (max "
          f"{SAMPLE_LIMIT}/cat)")
    for cat in ("MODERN_SEGMENT", "MODERN_GAP_NONE", "CONFLICT_NONE",
                "LEGACY_PRE_MODERN", "NO_RELATION_NONE"):
        rows = samples.get(cat, [])
        if rows:
            print(f"  [{cat}]")
            for r in rows:
                print(f"    trip={r['trip']} veh={r['vehicle']} start={r['start']} "
                      f"STORED={r['stored']} V1={r['v1']} V2={r['v2']} "
                      f"km={r['km']} class={r['class']} auto={r['auto_classified']}")
    print("-" * 78)

    if witness_rows:
        print("TÉMOINS EXPLICITES (fournis via env)")
        for r in witness_rows[:40]:
            print(f"  trip={r['trip']} veh={r['vehicle']} start={r['start']} "
                  f"STORED={r['stored']} V1={r['v1']} V2={r['v2']} cat={r['cat']} km={r['km']}")
        print("-" * 78)

    # -------------------- VERDICT --------------------
    structural = bool(all_anomalies)
    if pilot_impacted > 0 or manual_impacted > 0 or structural:
        verdict = "FAIL"
    elif len(mixed_mode) > 0 or cat_counts.get("CONFLICT_NONE", 0) > 0:
        verdict = "REVIEW_REQUIRED"
    else:
        verdict = "PASS"
    print(f"VERDICT = {verdict}")
    print("  PASS            = généralisable sans anomalie bloquante")
    print("  REVIEW_REQUIRED = cas mixtes / conflits à analyser avant patch")
    print("  FAIL            = pilotes/manuels touchés ou incohérences structurelles")
    print("=" * 78)
    print("AUCUNE ÉCRITURE EFFECTUÉE — SIMULATION READ-ONLY TERMINÉE.")

    cli.close()


if __name__ == "__main__":
    main()
