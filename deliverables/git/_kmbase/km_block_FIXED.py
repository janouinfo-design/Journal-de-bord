@router.get("/driver/km-summary")
async def driver_km_summary(
    period: str = Query("today", regex="^(today|week|month)$"),
    user=Depends(get_current_user),
):
    """Km Pro / Km Privé du CHAUFFEUR (tous véhicules confondus), sur la période demandée.

    - Source = trajets réels (`trips`), agrégés par classification, scopés par driver_id.
    - Décision produit : KPI CENTRÉS CHAUFFEUR. Le véhicule actif sert au contexte
      opérationnel (mode PRO/PRIVÉ, commandes) mais ne filtre PAS les km historiques :
      un changement de véhicule en cours de période ne masque pas les km déjà parcourus.
    - Périodes (bornes en Europe/Zurich) : today=00:00 ; week=lundi 00:00 ; month=1er 00:00.
    - Km PRIVÉ : on PRÉSERVE la logique AVL16 + cutover + fallback GPS en appelant
      `aggregate_private_km` VÉHICULE PAR VÉHICULE (uniquement les véhicules du chauffeur
      sur la période), puis en sommant. Aucun double comptage (1 trip = 1 vehicle_id).
      `private_km_source` reflète honnêtement la (ou les) source(s) réellement combinées.
    Retour : {period, period_label, vehicle_id (contexte), pro_km, private_km, available}.
    """
    from zoneinfo import ZoneInfo
    db = get_db()
    tenant_id = user.get("tenant_id") or "default"
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")

    # Véhicule ACTIF (contexte opérationnel uniquement) : affectation persistante Lot 2,
    # fallback session BLE. NE FILTRE PLUS les km (décision produit : KPI centrés chauffeur).
    from app import vehicle_assignment as va
    vehicle_id = await va.resolve_active_vehicle(db, driver_id, tenant_id)
    if not vehicle_id:
        sess = await ble_engine.get_current_session(db, driver_id)
        vehicle_id = sess.get("vehicle_id") if sess else None

    # Instant courant en heure locale chauffeur (Europe/Zurich).
    _TZ = ZoneInfo("Europe/Zurich")
    now_local = datetime.now(timezone.utc).astimezone(_TZ)
    _MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                  "août", "septembre", "octobre", "novembre", "décembre"]
    if period == "month":
        period_label = f"{_MONTHS_FR[now_local.month - 1].capitalize()} {now_local.year}"
    elif period == "week":
        monday = now_local - timedelta(days=now_local.weekday())
        sunday = monday + timedelta(days=6)
        period_label = (f"{monday.day} – {sunday.day} {_MONTHS_FR[sunday.month - 1]}")
    else:
        period_label = "Aujourd'hui"

    # Bornes de période en LOCAL (Europe/Zurich) puis converties en UTC pour la requête.
    if period == "today":
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        base = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_local = base - timedelta(days=now_local.weekday())  # lundi 00:00 local
    else:  # month
        start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = datetime.now(timezone.utc)
    start_iso = start_utc.isoformat()

    # Km PRO = trajets 'professional' du CHAUFFEUR (tous véhicules) sur la période.
    q_pro = {"tenant_id": tenant_id, "driver_id": driver_id, "start_time": {"$gte": start_iso}}
    trips_pro = await db.trips.find(
        q_pro, {"_id": 0, "distance_km": 1, "classification": 1}).limit(20000).to_list(20000)
    pro = round(sum((t.get("distance_km") or 0) for t in trips_pro
                    if t.get("classification") == "professional"), 1)

    # Km PRIVÉ = agrégation CHAUFFEUR, mais en PRÉSERVANT AVL16 + cutover + fallback GPS :
    # on appelle aggregate_private_km POUR CHAQUE véhicule RÉELLEMENT utilisé par le chauffeur
    # sur la période, puis on somme. gps_fallback_km reste fermé sur le vehicle_id courant.
    from app import private_mileage as _pm

    # Véhicules du chauffeur sur la période (jamais tout le tenant).
    driver_vehicle_ids = await db.trips.distinct(
        "vehicle_id", {"tenant_id": tenant_id, "driver_id": driver_id,
                       "start_time": {"$gte": start_iso}})
    driver_vehicle_ids = [v for v in driver_vehicle_ids if v]

    def _make_gps_fallback(_vid):
        async def _gps_personal_km(s_utc, e_utc):
            """Fallback GPS legacy : trajets 'personal' du CHAUFFEUR sur CE véhicule."""
            qq = {"tenant_id": tenant_id, "driver_id": driver_id, "vehicle_id": _vid,
                  "classification": "personal",
                  "start_time": {"$gte": s_utc.isoformat(), "$lt": e_utc.isoformat()}}
            docs = await db.trips.find(qq, {"_id": 0, "distance_km": 1}).limit(20000).to_list(20000)
            return round(sum((d.get("distance_km") or 0) for d in docs), 1)
        return _gps_personal_km

    priv_total = 0.0
    sources: set = set()
    any_value = False
    any_unavailable = False
    for _vid in driver_vehicle_ids:
        agg = await _pm.aggregate_private_km(
            db, tenant_id=tenant_id, vehicle_id=_vid,
            start_utc=start_utc, end_utc=end_utc,
            gps_fallback_km=_make_gps_fallback(_vid))
        pk = agg.get("private_km")
        if pk is not None:
            priv_total += pk
            any_value = True
            if pk:
                sources.add(agg.get("private_km_source"))
        else:
            any_unavailable = True

    # Provenance honnête en multi-véhicules.
    if not any_value and any_unavailable:
        private_km = None
        private_km_source = "UNAVAILABLE"
    else:
        private_km = round(priv_total, 1)
        if len(sources) > 1:
            private_km_source = "MIXED"
        elif len(sources) == 1:
            private_km_source = next(iter(sources))
        else:
            private_km_source = "GPS_FALLBACK"  # 0 km, aucune source distincte

    return {"period": period, "period_label": period_label, "vehicle_id": vehicle_id,
            "pro_km": pro, "private_km": private_km,
            "private_km_source": private_km_source, "available": True}
