@router.get("/driver/km-summary")
async def driver_km_summary(
    period: str = Query("today", regex="^(today|week|month)$"),
    user=Depends(get_current_user),
):
    """Km Pro / Km Privé du chauffeur pour SON véhicule actif, sur la période demandée.

    - Source = trajets réels (`trips`), agrégés par classification. AUCUN calcul GPS mobile.
    - Périodes (bornes en Europe/Zurich, timezone chauffeur — cf. mode Privé) :
        today = 00:00 (jour courant) -> maintenant
        week  = lundi 00:00 -> maintenant
        month = 1er du mois 00:00 -> maintenant
      Les bornes locales sont converties en UTC pour interroger `trips` (start_time ISO UTC).
    - Scoping strict : véhicule de l’affectation ACTIVE Lot 2 (fallback session legacy) + son tenant.
    - Si pas de véhicule actif -> valeurs None (l'app affiche « — », jamais une fausse valeur).
    Retour : {period, period_label, vehicle_id, pro_km, private_km, available}.

    NOTE (km privés & AVL16) : `private_km` agrège ici les trajets classés « personal »
    disposant d'une distance. En mode Privé, la position GPS est masquée ; les km privés
    fiables proviennent de l'odomètre matériel (AVL16), pas des points GPS. Le branchement
    AVL16 -> km privés est un chantier BACKEND séparé (hors de ce ticket UI).
    """
    from zoneinfo import ZoneInfo
    db = get_db()
    tenant_id = user.get("tenant_id") or "default"
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")

    # Source Lot 2 prioritaire : affectation persistante ACTIVE.
    # Fallback BLE/session conservé uniquement pour rétro-compatibilité.
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

    if not vehicle_id:
        return {"period": period, "period_label": period_label, "vehicle_id": None,
                "pro_km": None, "private_km": None, "available": False}

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

    # Km PRO = trajets professionnels réels (inchangé).
    q_pro = {"tenant_id": tenant_id, "vehicle_id": vehicle_id, "start_time": {"$gte": start_iso}}
    trips_pro = await db.trips.find(
        q_pro, {"_id": 0, "distance_km": 1, "classification": 1}).limit(20000).to_list(20000)
    pro = round(sum((t.get("distance_km") or 0) for t in trips_pro
                    if t.get("classification") == "professional"), 1)

    # Km PRIVÉ = source AVL16 (sessions) avec CUTOVER + fallback GPS legacy (intervalles
    # disjoints, jamais de double comptage). Provenance explicite. Voir app.private_mileage.
    from app import private_mileage as _pm

    async def _gps_personal_km(s_utc, e_utc):
        """Fallback legacy : somme des trajets 'personal' (distance GPS) sur [s_utc, e_utc]."""
        qq = {"tenant_id": tenant_id, "vehicle_id": vehicle_id,
              "classification": "personal",
              "start_time": {"$gte": s_utc.isoformat(), "$lt": e_utc.isoformat()}}
        docs = await db.trips.find(qq, {"_id": 0, "distance_km": 1}).limit(20000).to_list(20000)
        return round(sum((d.get("distance_km") or 0) for d in docs), 1)

    agg = await _pm.aggregate_private_km(
        db, tenant_id=tenant_id, vehicle_id=vehicle_id,
        start_utc=start_utc, end_utc=end_utc, gps_fallback_km=_gps_personal_km)

    return {"period": period, "period_label": period_label, "vehicle_id": vehicle_id,
            "pro_km": pro, "private_km": agg["private_km"],
            "private_km_source": agg["private_km_source"], "available": True}
