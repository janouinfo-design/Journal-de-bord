# LOGITRAK — Volet 2 (resolver multi-source moderne) — ÉTAT DE RÉFÉRENCE

> Statut : **CODE CANONIQUE VALIDÉ FINAL** — intégration GitHub = acheminement uniquement.
> **Déploiement PROD : NON DONNÉ.** Aucun git pull / git apply / build / restart /
> migration / backfill / reassign_all_trips() autorisé à ce stade.

## 1. Architecture

```
navixy_sync            -> resolve_driver_for_trip()        -> V2 (moderne, tenant réel du véhicule)
reassign_all_trips     -> _resolve_driver_for_trip_v1()    -> V1 (legacy "default", INCHANGÉ)
```

- V2 déduit le `tenant_id` depuis le véhicule (`db.vehicles.find_one`). Tenant
  introuvable/ambigu -> retour **V1 exact** (jamais de lecture silencieuse des
  events du tenant `"default"`).
- Invariant : **« V2 == V1 sauf autorité moderne PROUVÉE ».**
- `reassign_all_trips()` utilise **exclusivement** V1 (route admin de réécriture
  historique) — jamais V2.

## 2. Règles V2 (catégories de résolution)

| Catégorie            | Condition                                                             | Résultat |
|----------------------|-----------------------------------------------------------------------|----------|
| `MODERN_SEGMENT`     | 1 segment moderne `[start,end)` couvrant le véhicule                   | driver du segment |
| `CONFLICT_NONE`      | ≥ 2 segments couvrants, OU conflit de reconstruction (à partir de T)  | `None` |
| `NO_RELATION_NONE`   | aucun segment moderne + candidat V1 = None                            | `None` |
| `MODERN_GAP_NONE`    | aucun segment moderne + `trip_start >= modern_since(candidat V1)`     | `None` (fail-closed) |
| `LEGACY_PRE_MODERN`  | aucun segment moderne + `trip_start < modern_since` (ou pas moderne)  | candidat V1 (== V1) |

- Source moderne : `vehicle_assignment_events`, `result="OK"`, timestamp `at`,
  scope strict `(tenant_id, driver_id)`.
- Segments `[start,end)` : TAKEN ouvre ; CHANGED ferme+ouvre ;
  RELEASED/FORCE_RELEASED ferme ; ouvert en fin de journal -> `end=None`.
- **Conflit temporel** : un conflit à l'instant T n'invalide PAS rétroactivement
  une relation moderne prouvée **avant** T. Neutralisation (`None`) uniquement
  **à partir** de l'instant du conflit (`conflict_vehicle_since`).

## 3. KNOWN_LIMITATION (hors périmètre Volet 2)

Le resolver legacy V1 (`list_assignments`) filtre `tenant_id="default"` **en dur**
(mono-tenant historique). La généralisation multi-tenant du legacy est un lot
séparé (« Volet 2B »). Conséquence : pour un véhicule d'un tenant ≠ "default", le
candidat V1 est None -> V2 ne produit que `MODERN_SEGMENT` ou `None`
(`fallback_V1 = 0`). Aucune bascule silencieuse vers les events `"default"`.

## 4. Empreintes canoniques

| Fichier | git hash-object | SHA-256 |
|---|---|---|
| `backend/app/assignments.py` | `af3ef053e75a4d6d5b79c4b3a0c6f47de24d62e9` | `c9b26737133782d55431d279303a1434bb21bdfd0472b0a19e619917ab692902` |
| `deliverables/sim_volet2_readonly.py` | — | `9abaf5a3df5bd0bb30ba85fdf4c3059dc993927b622c4b27b9ac0261c4b7156f` |

Préimage PROD de référence (avant Volet 2) :
- `backend/app/assignments.py` blob `4555027d2ff59e2f132f1605b2ffa9d3da5405cb`
  / SHA-256 `092543e644ac6fd9434bd7273c3fc3ab168949e613a2ec0405d90e4b62f09501`.

`navixy_sync.py` : **INCHANGÉ**.

## 5. Tests (certifiés testing_agent)

- `tests/test_resolve_driver_fail_closed.py` : **14/14** (V1 non-régression, 0 skip/xfail)
- `tests/test_resolve_driver_v2.py` : **17/17** (V2, dont fail-closed strict + conflit temporel)
- `tests/test_fmc130_resolve_pending.py` : **12/12** (non-régression)
- **Total : 43/43 PASS** (fichiers lancés isolément).

> Artefact connu (KNOWN / OUT OF SCOPE) : lancer `test_resolve_driver_fail_closed.py`
> + `test_fmc130_resolve_pending.py` ENSEMBLE provoque `RuntimeError: no current
> event loop` (asyncio.get_event_loop() déprécié dans FMC130). Non lié au Volet 2 ;
> corrigé dans un lot séparé. Chaque fichier passe 100% isolé.

## 6. Simulateur READ-ONLY (acheminement puis run manuel sur VPS)

Fichier : `deliverables/sim_volet2_readonly.py` (SHA `9abaf5a3...`).
100% READ-ONLY (uniquement `.find()`), aucune écriture, aucun `reassign_all_trips()`.
Reproduit exactement V1 runtime (assignments `tenant_id="default"` en dur) tout en
scopant les events modernes sur le tenant réel du véhicule.

Critères de GO attendus au dernier run PROD :
- `tenant != default` : `fallback_V1 = 0`
- `default` : `fallback_V1` selon V1 réel
- `0` pilote impacté, `0` anomalie structurelle
- témoin Audi -> `MODERN_SEGMENT`
- cas stale (type 09ce) post-`modern_since` -> `MODERN_GAP_NONE`
- trajet manuel signalé, jamais réécrit

## 7. Verrou

Déploiement PROD **NON DONNÉ**. Intégration GitHub = acheminement de fichiers
uniquement. Prochaine étape : dernier run READ-ONLY PROD du simulateur, analyse de
la sortie, puis GO explicite.
