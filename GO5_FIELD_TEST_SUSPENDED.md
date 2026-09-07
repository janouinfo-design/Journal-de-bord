# GO 5 — TEST TERRAIN FMC003 3657864 : SUSPENDU (prérequis opérationnels manquants)

> État logiciel = PRÊT et SÛR. Le test terrain réel (bascule Privé + roulage) est
> SUSPENDU faute de prérequis **humains/app**, pas pour un défaut de code.

## État validé (GO 1 → GO 4)
```text
GO1 Save to Github        : OK (branche feat/private-mode-pilot, commit dbf7e6f)
GO2 Déploiement fail-closed: OK (backend prod healthy, imports Mode Privé OK)
GO3 navixy_hash migration  : OK (3/3 chiffrés valides, idempotent, decrypt OK)
GO4 Activation pilote      : OK (gate étanche : default + 3657864 ; autres refusés ; kill switch OK)
Device write               : PRIVATE_MODE_DEVICE_WRITE=0 (aucune écriture device possible)
Précheck terrain 3657864   : PASS (online, AVL16 140314.86 km, sensor avl_io_16 /1000 km)
```

## Prérequis GO 5 — état
```text
✅ Device 3657864 online + AVL16 + config validée (précheck PASS)
✅ Gate pilote activée et étanche (tenant default + tracker 3657864)
✅ Kill switch fonctionnel (testé ON->bloque, OFF->restaure)
❌ Chauffeur pilote avec COMPTE MOBILE : ABSENT
   - "Orhan" existe comme DRIVER métier mais SANS email / SANS compte user mobile
   - Seul compte mobile chauffeur en prod = chauffeur@logitrak.ch (Jean Dupont), non pilote
❌ Audi 3657864 non assignée à un chauffeur (assigned_driver_id=None, 0 assignment)
❌ App mobile branchée sur la PROD : l'app observée listait des véhicules DÉMO (GE 1234xx),
   donc pointée sur l'environnement de démo, pas sur ce backend prod
❌ Conducteur physique prêt à rouler l'Audi
```

## Ce qu'il faut réunir avant un futur GO 5 (actions opérateur, sur GO explicite)
1. **Créer un compte mobile chauffeur** pour le pilote (ex. Orhan) :
   - créer/mettre à jour le `driver` avec un email valide ;
   - créer le `user` role=driver + mot de passe (via le flux « Activer l'accès » de l'admin).
2. **Assigner ce chauffeur à l'Audi 3657864** (assignment ou assigned_driver_id) pour qu'elle
   apparaisse dans SON app.
3. **Brancher l'app mobile du chauffeur sur la PROD** (EXPO_PUBLIC_API_URL = domaine prod réel),
   et NON sur l'environnement de démo (confidentialite-flag.preview…).
4. **Planifier un créneau avec conducteur** (roulage réel de quelques km requis pour l'incrément AVL16).
5. **Confirmer la config device** GPS Data Masking = Data Sent As Zero (11813=1) toujours en place
   sur le FMC003 (relecture Configurator/Air Console, READ-ONLY).

## Séquence GO 5 (déjà préparée, à exécuter quand les 5 prérequis sont réunis)
```text
0. Précheck online + config      (READ-ONLY)  -> PASS
1. Snapshot ODO_BEFORE           (READ-ONLY)
2. Confirmer config FMC003        (READ-ONLY)  -> GPS masking conforme
3. PRIVATE_MODE_DEVICE_WRITE=1 + recreate      -> device_write_enabled=True (aucune commande auto)
4. Vérif runtime (feature/device_write/pilot)  (READ-ONLY)
5. 1 SEULE bascule PRIVÉ via app/API chauffeur -> confirmation réelle (pas SIMULATED)
6. Preuve GPS masqué (device + /trips + web)   (READ-ONLY)
7-8. Rouler ~2-3 km, mesurer ODO_PRIVATE_END, delta>0
9. 1 SEULE bascule PRO (retour) via app/API    -> confirmation réelle
10-11. Nouvelle position Pro + ODO_AFTER monotone
12. PRIVATE_MODE_DEVICE_WRITE=0 + recreate      -> device_write_enabled=False
13. Kill switch état final = false
14. Isolation : 781479 refusé, autres tenants refusés
```

## État verrouillé pendant la suspension
```text
PRIVATE_MODE_ENABLED=true (pilote éligible)
PRIVATE_MODE_DEVICE_WRITE=0   -> AUCUNE écriture device possible
ALLOW_GLOBAL_NAVIXY_FALLBACK=false · APP_ENV=production · SIMULATE_CONFIRM=false
kill_switch=false
Pilote = default + 3657864 uniquement ; 781479 et autres tenants refusés.
Aucune commande device envoyée. Aucun test terrain effectué.
```

## Rappel important
Ce n'est PAS un échec technique : le mécanisme Mode Privé (backend + gate + kill switch +
odomètre AVL16) est déployé, activé pour le pilote et prouvé étanche. Le blocage est purement
opérationnel (compte chauffeur mobile + app sur prod + conducteur).
