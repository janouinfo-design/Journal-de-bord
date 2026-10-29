# CHANGELOG — Livre de bord LOGITRAK

## 29/10/2026 — GARDE-FOU 7 JOURS AVANT ENFORCE · EXCLUSION (LECTURE) DES REFUS SHADOW POLLUÉS

### Fenêtre polluée identifiée et neutralisée sans toucher à l'audit
- Fenêtre : `tenant.modules_update` **14:29:52 UTC** (fines/fuel/fuel_cards coupés par un test UI) → **14:55:47 UTC** (rétablis). 42 refus `access.shadow_deny` bruts sur Logitrak : **35 pollués** (module fines ×5, fuel ×5, fuel_cards ×3 ; permissions fines.* ×9, fuel.* ×13 — tous entre 14:30 et 14:37) et **7 légitimes** (`identification.self`, lecture@logitrak.ch, exemption documentée).
- Méthode : `scripts/mark_polluted_shadow_window.py` (dry-run → `--apply`, idempotent) dérive la fenêtre des audits modules coupés→rétablis et l'enregistre dans `tenants.observation_exclusions[]` `{id, from, to, modules, reason, source, created_at}` + audit `tenant.observation_exclusion_add` (motif, 35 événements couverts). **Aucun événement supprimé ni modifié.**
- Règle de lecture `access_control.deny_exclusion(deny, exclusions)` : refus exclu si `at ∈ [from, to]` et module du refus (clé module, ou module de la permission) ∈ `modules`. Utilisée par `enforce_readiness` (`observation.shadow_denies` = valides, `excluded`, `exclusions[]`), `scripts/enforce_preflight.py` (colonne `exclus=`) et `GET /admin/audit` (annotation `excluded` par ligne, page Audit : bannière « 42 refus — 7 à analyser · 35 exclus », badge « exclu du calcul »).

### Garde-fou observation (configurable, côté serveur)
- `OBSERVATION_MIN_DAYS` = env `ENFORCE_MIN_OBSERVATION_DAYS` (défaut 7). `enforce_readiness(..., min_days=None)` : observation `fail` si jamais en shadow ou `days < min_days` ; `observation.required_days`, `eligible_at` (= début shadow + N j), `blocked_reasons[]`.
- `PATCH /admin/tenants/{id}` avec `access_control_mode=enforce` (depuis un autre mode) → `_readiness()` partagé ; si non prêt : **409 `{code: enforce_not_ready, msg, reasons, eligible_at}`**, mode inchangé, audit `tenant.enforce_refused`. Vérifié sur `default` : 409, reste shadow.
- UI `TenantModulesDialog` : encart rouge « Passage en mode Appliqué refusé par le serveur » + raisons + « Éligible à partir du … », ligne « N refus exclus du calcul — fenêtre de test identifiée » avec bornes/modules ; bouton Confirmer désactivé. Vérifié par screenshot sur Client Test B (jamais observé) et Logitrak (0 j / 7, éligible 05/11/2026 13:39 UTC).
- Tests : `tests/test_enforce_readiness.py` réécrit **9/9** (pur : clean, warnings non bloquants, garde-fou None/3 j/7 j/min_days configurable, exclusions = règle de lecture ; endpoint ; PATCH enforce 409 jamais observé + 409 à 2 j avec `eligible_at` + legacy libre ; PATCH autorisé après 8 j sur tenant jetable puis retour legacy immédiat, `count(enforce) == 0`). `tests/test_lot56_qa_agent.py::test_enforce_readiness_default` adapté (exclusions ≥ 35, ready ⇔ aucun fail, refusé tant que < 7 j).
- **0 tenant réel passé en enforce** (seul un tenant jetable `ac6-*` l'est 1 requête dans le test, puis supprimé).
- Régression : run 1 → 3 FAIL (2 tests Lot 2 qui passaient un tenant jetable en enforce sans observation — devenus caducs par le garde-fou, adaptés : 409 puis shadow antidaté 8 j puis 200 ; 1 timeout TCP réseau sur `test_07_driver_claim_app`, repassé seul) ; **run final 973 PASS / 0 FAIL / 4 SKIP / 4 warnings — 542 s**. Le flaky Energy cache (`test_vehicule_different_miss_e2e`, 968/1 du run précédent, 25/25 isolé) n'a pas été masqué ni supprimé ; il est passé ce run. Nettoyage preview rejoué (reste 2 tenants, 9 users, 14 chauffeurs, 1 invitation ; 0 tenant en enforce ; 44 refus shadow bruts conservés sur Logitrak dont 35 exclus).


### Nettoyage base preview (`scripts/cleanup_preview_test_data.py`, dry-run → `--apply`)
- Supprimé : 89 tenants `TEST Suspend*` / `TEST_Tenant*` (+ 46 users `test_susp_*@x.ch`, 356 entrées audit), 36 users `ivan.<hex>@example.com`,
  150 chauffeurs de test (`Ivan Petrov*` ×84, `TEST_INV_*` ×92… — 0 trajet / affectation / amende / transaction liés, vérifié avant suppression),
  95 invitations `test.inv.*@client.ch` / `pending.*@client.ch`.
- Reste : tenants Logitrak + Client Test B ; 9 utilisateurs (comptes partagés, superadmin, logitrak@, admin-b@, paul.test, invite.test) ; 14 chauffeurs ; 1 invitation.
- Dette : `test_impersonation`, `test_administration`, `test_phase3_admin_driver` recréent ces artefacts à chaque run (pas de cleanup de fixture) — relancer le script après une régression complète.

### Lot 5 — app chauffeur Expo consciente des modules / permissions (`logitrak-driver-app/`)
- `api/client.ts` : `fetchMe(): MePayload` (payload `/auth/me` complet) ; intercepteur : 401 `account_disabled` ⇒ tokens purgés, pas de refresh.
- `store/authStore.ts` : `access {modules, permissions, mode, loaded}` (`normalizeAccess` — `loaded=true` seulement si `/auth/me` enrichi a répondu), `can(...perms)`, `hasModule(code)`, `refreshAccess()` (appelé au retour au premier plan et tant que l'accès n'est pas chargé — `RootNavigator`) ; login = `/auth/login` puis `/auth/me` ; **accès non chargé ⇒ rien n'est masqué** (le backend tranche, l'app affiche un message lisible) ; messages via `describeApiError`.
- `navigation/tabsPolicy.ts` (pur, testé) : Conduite ⇐ `drivers` + `identification.self|edit` ; Trajets ⇐ `journal` + `journal.view_self|view` ; Profil / Réglages toujours. `RootNavigator` rend les onglets selon `visibleTabs(access, role)`.
- Écrans : cartes Mode Privé masquées si module `private_mode` coupé (`DriverScreen`, `DriverScreenManual`) ; section Classification masquée sans `trips.classify_self|classify` (`TripDetailScreen`) ; tracé : message « non autorisé » distinct de « masqué (personnel) ».
- `utils/apiError.ts` : `ACCESS_MESSAGES` (module_disabled, permission_denied, account_disabled, tenant_suspended, tenant_missing, invalid_tenant), `describeApiError`, `isAccessDenied`, `errorCode` ; utilisés par `tripsStore` (chargement + classification), `usePrivateMode.reasonToMessage` (+ `api/privateMode` lit `detail.code`), `authStore`.
- Qualité : `tsc --noEmit` 0 erreur · eslint 0 erreur · jest 13 suites / **84 tests PASS** (`accessPolicy.test.ts` nouveau, `authStore.test.ts` étendu : modules/permissions, accès non chargé = rien masqué, compte désactivé). Aucun build EAS / store.
- Backend aligné pour l'app : `GET|POST /livre/driver/private-mode` déclarent `module="private_mode"` (comme les réglages web) ; `require_permission` dérive désormais le module automatiquement quand toutes les permissions relèvent du même module ⇒ module coupé renvoie `module_disabled` (et non `permission_denied`) sur `/trips`, `/vehicles`, `/drivers`, `/dashboard`, `/trips/{id}/track`… (trouvé par l'agent de test, `iteration_39.json`). Test `test_enforce_driver_private_mode_module` (lot23) + `tests/test_lot56_qa_agent.py` 6/6.

### Lot 6 — préparation du passage enforce (garde-fous)
- `access_control.enforce_readiness(tenant, users, denies, shadow_since, now)` (pur) → `checks` [tenant_active fail/ok · observation ≥ 7 j warn · shadow_denies 30 j warn (groupés kind/key, users, rôles) · roles_known fail/ok · overrides_valid warn], `ready` = aucun fail, `invalid_overrides`, `users.by_role`.
- `GET /api/admin/tenants/{id}/enforce-readiness` (superadmin ; `shadow_since` = dernier audit `tenant.update` → shadow si le mode effectif est shadow).
- `TenantModulesDialog` : la confirmation « Confirmer le mode Appliqué » charge le bilan, l'affiche (icônes ok / warn / fail, liste des refus observés) et **désactive la confirmation si un contrôle échoue**. Zone à hauteur minimale fixe.
- `access.shadow_deny` : `details.role` ajouté (lecture par rôle dans le bilan).
- `scripts/enforce_preflight.py [--tenant id]` (lecture seule, code retour 1 si blocage) : users entreprise sans tenant_id, rôles inconnus, tenants non actifs, bilan par client. Exécution preview : PRÉ-VOL OK — Logitrak READY (warn : 0 j d'observation, 2 refus `identification.self` = exemption lecture_seule), Client Test B READY (jamais en observation).
- Tests `tests/test_enforce_readiness.py` 4/4 (pur ×3 + endpoint 200 / 404 / 403).
- Dev : `craco.config.js` `devServer.client.overlay.runtimeErrors` filtre « ResizeObserver loop » (avertissement bénin remonté par l'overlay CRA lors de l'ouverture de l'AlertDialog sur le Dialog).

### Régression
- **Pollution preview réparée** : un test UI avait coupé `fines`, `fuel`, `fuel_cards` sur le tenant `default` (`PUT /admin/tenants/default/modules`, audit 14:29) ⇒ 8 échecs (`test_me_enriched` ×4, `test_office_role_creatable_since_lot3`, 3 assertions « default sans `modules_enabled` »). Décision utilisateur : **tous les modules réactivés sur default** via l'API Super Admin (audit `tenant.modules_update` before 7 → after 10, mode shadow conservé) et assertions adaptées à l'état voulu (`enabled_modules(default)` == 10 modules legacy, mode ∈ {legacy, shadow}, jamais enforce) dans `test_lot1_qa_agent.py` / `test_lot23_qa_agent.py`. Les 38 refus shadow `fuel*`/`fines*` journalisés pendant la fenêtre polluée (14:29 → 15:00) sont des artefacts (seuls les 5 `identification.self` lecture_seule sont légitimes).
- **Régression complète finale** : `968 PASS / 1 FAIL / 4 SKIP / 4 warnings — 536 s` ; l'unique échec `tests/test_energy_cache.py::TestCacheE2E::test_vehicule_different_miss_e2e` est le flaky Energy cache connu (hors périmètre, TTL 60 s partagé entre tests) — **25/25 PASS relancé seul**. Deux runs intermédiaires : 961/1 (timeout TCP réseau sur `test_disable_user_blocks_login`, repassé seul) puis interrompu pour relancer après le correctif `module_disabled`. Nettoyage preview rejoué après la régression (8 tenants `TEST*`, 12 chauffeurs, 8 invitations recréés par les suites → supprimés ; reste 2 tenants, 9 users, 14 chauffeurs, 1 invitation).

## 29/10/2026 — PHASE 4C · LOTS 2 & 3 : MODULES PAR CLIENT (SUPER ADMIN) & PERMISSIONS PAR UTILISATEUR

### Lot 2 — Super Admin « Modules & licences »
- Backend `routes/admin.py` : `GET /admin/modules/catalog` ; `PUT /admin/tenants/{id}/modules` (`normalize_modules` : dict complet, dépendance OFF ⇒ dépendant OFF, 400 `unknown_module`, audit `tenant.modules_update` before/after/enabled/disabled, `refresh_tenant_cache`) ; `PATCH /admin/tenants/{id}` + `access_control_mode` (400 si hors legacy|shadow|enforce, audit before/after) ; `_tenant_out` → `modules_enabled`, `modules_effective`, `access_control_mode`, `access_control_mode_effective` ; `TENANT_ROLES` importé d'`access_control` (office inclus).
- Frontend : `AdminTenantsPage` colonne « Modules » (n modules + badge Legacy / Observation / Appliqué, bouton `tenant-modules-btn-<id>`), `components/admin/TenantModulesDialog.jsx` (groupes Cœur / Métier / Réservés, 17 `module-switch-<code>`, cascade de dépendances côté client identique au backend, hint « Forcé OFF », sélecteur `tenant-mode-select`, `AlertDialog` de confirmation pour enforce, compteur `x / 17`).
- Décision d'interprétation (réponse double à la question 1) : les 17 modules sont affichés et commutables ; les 7 réservés portent le tag « réservé » et n'ont aucun effet tant que leur backend n'existe pas.

### Lot 3 — Utilisateurs, rôle office, permissions individuelles
- Backend `routes/team.py` : `TEAM_ROLES = TENANT_ROLES` (office créable) ; `GET /team/permissions/catalog` (users.view) ; `GET /team/users/{id}/permissions` ; `PUT /team/users/{id}/permissions` (users.permissions ; `validate_override` → 400 `unknown_permission` | `module_disabled` | `sensitive_not_allowed_for_role` | `write_not_allowed_for_read_only` ; auto-modification et compte superadmin refusés ; grant prioritaire sur revoke ; grant+revoke vides ⇒ `$unset` ; audit `user.permissions_update` {email, role, before, after, granted, revoked, sensitive_granted, gps_access_granted, reason}) ; changement de rôle ⇒ `permissions_override` réinitialisée (audit `permissions_override_reset`).
- `access_control.py` : `require_permission(..., parity_exempt=())`, `normalize_modules`, `modules_catalog`, `permissions_catalog` (modules ordonnés), template `manager` sans `fuel.statements` (parité legacy : décomptes gérés par admin seul ; office le garde).
- **Migration `require_roles` → `require_permission` (121 routes, table explicite)** : fuel 37 (`fuel.view` / `fuel_cards.view|edit` module fuel_cards / `fuel.edit` / `fuel.reconcile` / `fuel.import` / `fuel.admin` / `vehicles.admin` / `fuel.view|view_self` / `fuel.edit_self|edit|reconcile`), fines 16 (`fines.view|edit|export|admin`, `fines.view|view_self` pour mine/meta), energy 14 (`energy.view|view_self|edit|admin|export`), ble 21 (`identification.view|edit`, `drivers.admin`, `identification.self|edit` pour l'ingestion), identification 16 (`identification.self|view` en GET avec `parity_exempt=("lecture_seule",)`, `identification.self|edit` en écriture), fuel_statements 9 (`fuel.view`, `fuel.statements`, `fuel.export`), weekly/monthly 6 (`reports.admin`), odometer_calibration 2 (`vehicles.admin`, module journal). Registre : 186 entrées, 50/53 permissions liées (template-only : `fines.pay`, `journal.export`).
- Test de parité T24 étendu : `lecture_seule` considéré refusé en legacy sur les endpoints dont toutes les permissions sont des écritures (blocage global existant) ; exemptions déclarées vérifiées par `test_parity_exemptions_are_documented` (exactement 9 GET `/driver/*`, rôle lecture_seule — console chauffeur jamais utilisée par ce rôle, unique refus observé en shadow sur Logitrak).
- Frontend : `AuthContext` (`refreshMe`, `can(...perms)`, `hasModule(code)`, `tenant`, `modules`, `permissions`, `accessMode`) ; `ProtectedRoute` `roles | perms | module` ; `AppLayout` onglets filtrés module + permission (onglets « self » chauffeur gardent `roles`), `ConflictInbox` sous `can("trips.classify")` ; `App.js` routes migrées (AML supprimé) ; sous-onglets `DriversLayout` / `EnergyLayout` / `FuelLayout` / `AdministrationLayout` filtrés ; `lib/roles.js` (labels, options, hints, office) ; `TeamUsersPage` réécrit (rôle Office, colonnes Permissions + Statut, Désactiver / Réactiver principal, DELETE secondaire avec avertissement, actions conditionnées par `can`) ; `components/livre/UserPermissionsDialog.jsx` + `PermissionGroup.jsx` (réplique locale d'`expand`/`effective_permissions`, badges rôle / accordée / retirée / implicite / non, verrouillage sensible driver & lecture_seule, cascade view ⇒ edit/admin au décochage, avertissement GPS + motif, « Revenir au rôle »).
- Labels office ajoutés : `AdminUsersPage` (+ option de rôle), `ImpersonationBanner`, `TeamImpersonationPage`, `AppLayout`.

### Mode Observation (shadow) & Audit
- Tenant `default` (Logitrak) : `access_control_mode=shadow` écrit via `PATCH /admin/tenants/default` (audit `tenant.update` before legacy → after shadow). Aucune initialisation de `modules_enabled`. Env serveur inchangé (`legacy`).
- `AdminAuditPage` : bouton « Refus observés » (`audit-shadow-filter`), bannière `audit-shadow-banner`, détail lisible, **course de requêtes corrigée** (compteur de requête : réponses obsolètes ignorées — bug trouvé par l'agent de test).
- Premier constat : 1 seul refus observé sur Logitrak — `lecture_seule` GET `/livre/driver/vehicles` (`identification.self`), c'est l'exemption déclarée ; aucun autre écart entre matrice legacy et templates.

### Login
- Vignette « Lecture seule » (`auth-demo-readonly`, lecture@logitrak.ch / lecture123).

### Tests
- `tests/test_access_control_lot23.py` 23/23 (catalogue, cascade + audit modules, mode, office, catalogue permissions, règles de surcharge + audit GPS, matrice legacy 17 routes × rôles sur tenant default, enforce sur tenant jetable). `tests/test_access_control_lot1.py` 19/19 (T24 sur 186 entrées). Tests `access_control_mode == "legacy"` sur default assouplis en `in ("legacy","shadow")`.
- Agent de test `test_reports/iteration_38.json` : backend 12/12 (`tests/test_lot23_qa_agent.py`), frontend tous flux OK (4 rôles de navigation, dialogs, enforce confirm, Équipe, désactivation) ; 1 bug MEDIUM (course audit) corrigé.
- Régression backend complète : voir « Résultat régression » ci-dessous.

### Résultat régression
- **Régression backend complète : 956 PASS / 2 FAIL / 4 SKIP / 4 warnings — 732 s (13:50:06 → 14:02:20 UTC).**
  Les 2 échecs sont deux attentes de l'agent de test Lot 1 rendues caduques par les décisions des Lots 2/3 (pas des régressions) :
  `test_lot1_qa_agent::test_office_role_refused` (office est désormais créable) et `test_zz_default_tenant_untouched`
  (default porte `access_control_mode=shadow` sur demande). Tests mis à jour (`test_office_role_creatable_since_lot3`,
  default autorisé en legacy|shadow, jamais enforce) → `test_lot1_qa_agent.py` 25 PASS / 1 skip. `test_energy_cache` E2E : PASS.
  Baseline Lot 1 922/0/4 → 958 tests (+23 Lot 2/3, +12 QA Lot 2/3, +1 exemptions), 0 régression fonctionnelle.

## 29/10/2026 — Login : vignette « Super Admin » dans les comptes de démo
- `frontend/src/pages/LoginPage.jsx` + `constants/testIds.js` : 4e vignette « Super Admin — Plateforme Logitrak » (`auth-demo-superadmin`), visible uniquement avec `REACT_APP_SHOW_DEMO_ACCOUNTS=true` (preview). Pré-remplit l'email `superadmin@logitrak.ch` et focalise le champ mot de passe ; le mot de passe (secret réel, `backend/.env`) n'est **pas** embarqué dans le bundle.

## 28/10/2026 — PHASE 4C · LOT 1 : FONDATIONS BACKEND MODULES / PERMISSIONS — LOT 1 : PASS

### Périmètre réalisé (backend uniquement, mode `legacy` actif)
- Nouveau `backend/app/access_control.py` : `MODULES` (17), `PERMISSIONS` (53), `ROLE_TEMPLATES`
  (admin, manager, office, driver, lecture_seule), `SENSITIVE_PERMISSIONS` (10), `WRITE_PERMISSIONS`,
  `effective_permissions()`, `validate_override()` (règles anti-escalade, consommé au Lot 3),
  `strip_positions()` / `must_strip_positions()`, `require_module()`, `require_permission()`, `me_payload()`.
- `ACCESS_CONTROL_MODE=legacy` ajouté à `backend/.env` (preview). Résolution : tenant.access_control_mode > env > `legacy`.
- `auth.py` : re-vérification `active` par requête et au refresh (401 `account_disabled`), `_resolve_tenant()`
  (X-Tenant-Id superadmin validé : 400 `invalid_tenant` / 403 `tenant_suspended` sur `/api/livre`, non bloquant
  ailleurs ; entreprise : `user.tenant_id` strict → 403 `tenant_missing`), cache `request.state`, `/auth/me` enrichi,
  `/auth/register` + `/auth/users` sous `require_permission` (repli `"default"` retiré de `/auth/users`).
- `audit.py` : erreurs d'insertion loggées (`logger.error`), `acting_tenant` superadmin.
- Routeurs annotés `require_module` : ble, identification (drivers) · fines · fuel, fuel_statements · energy ·
  weekly_report, monthly_report (reports) · notifications. 65 endpoints sous `require_permission(..., legacy_roles=...)`
  dans auth, dashboard, misc, settings, team, notifications, reports — parité stricte avec l'ancienne matrice
  `require_roles` (test T24 automatisé pour admin / manager / driver / lecture_seule).
- Réponses d'erreur structurées `{code, msg, ...}` ; refus legacy inchangés (`"Accès refusé"` texte).

### Catalogue des 53 permissions (module → permissions · rôles par défaut)
- journal (6) : journal.view (A,M,O,L) · journal.view_self (A,D) · journal.export (A,M,O,L) · **positions.view** (A,M,L — sensible) · vehicles.edit (A,M) · vehicles.admin (A)
- trip_classification (5) : trips.classify (A,M) · trips.classify_self (A,D) · work_schedule.view (tous) · work_schedule.edit (A,M) · privacy_policy.edit (A,M — sensible)
- private_mode (3) : private_mode.view (A,M) · private_mode.edit (A — sensible) · private_mode.admin (A — sensible)
- drivers (6) : drivers.view (A,M,O) · drivers.edit (A) · drivers.admin (A) · identification.view (A,M) · identification.edit (A,M) · identification.self (A,D)
- energy (5) : energy.view (A,M,O,L) · energy.view_self (A,D) · energy.edit (A,M) · energy.admin (A — sensible) · energy.export (A,M,O,L)
- fuel (9) : fuel.view (A,M,O,L) · fuel.view_self (A,D) · fuel.edit_self (A,D) · fuel.edit (A,O) · fuel.import (A,O) · fuel.reconcile (A,M) · fuel.statements (A,M,O) · fuel.admin (A) · fuel.export (A,M,O,L)
- fuel_cards (2) : fuel_cards.view (A,M,O,L) · fuel_cards.edit (A,O)
- fines (6) : fines.view (A,M,O,L) · fines.view_self (A,D) · fines.edit (A,M,O) · fines.pay (A,M,O) · fines.admin (A) · fines.export (A,M,O,L)
- reports (2) : reports.view (A,M,O,L) · reports.admin (A,M)
- notifications (2) : notifications.manage_self (tous) · notifications.manage_company (A)
- plateforme-tenant (7, sans module) : users.view (A) · users.edit (A — sensible) · users.permissions (A — sensible) · users.impersonate (A — sensible) · settings.view (A,M) · settings.edit (A — sensible) · audit.view (A — sensible)
- Contrôles : 0 doublon · 0 permission inconnue dans les templates / `require_permission` / tests · 0 permission orpheline
  (toutes dans ≥ 1 template) · 25 liées à un endpoint dès le Lot 1, 28 portées par les templates et les routeurs
  `require_module` en attendant la migration permission par permission des routeurs fuel / fines / energy / ble (Lot 3).
- Écart vs spécification (~50, objectif de granularité, texte de la spec non persisté dans le workspace) : les 3
  permissions `*_self` ajoutées pendant l'implémentation pour obtenir la parité legacy stricte du rôle driver sans
  lui accorder la permission « entreprise » correspondante : `trips.classify_self` (driver reclasse SES trajets —
  `PUT /trips/{id}/classify`, contrôle de propriété existant), `identification.self` (console chauffeur `/driver/*`),
  `fuel.edit_self` (justificatifs / signalements sur SES transactions carburant). Aucune nouvelle fonctionnalité.

### Décisions figées appliquées
- Module OFF → 403 `module_disabled` ; permission insuffisante → 403 `permission_denied` ; autre tenant → 404 (proxy Mongo) ;
  non authentifié / désactivé → 401 ; superadmin : aucun bypass de module, tenant invalide 400 / suspendu 403 sur `/livre`.
- Rôles = modèles par défaut, surcharges `permissions_override {grant, revoke}` lues (aucune UI, aucun écrit par l'app au Lot 1).
- `office` : présent dans les templates uniquement, non créable (`TEAM_ROLES` inchangé) ; sans `positions.view` par défaut.
- Suppression d'utilisateur : la désactivation (`active=false`) reste la cible ; `DELETE /team/users/{id}` inchangé.

### Tests
- `tests/test_access_control_lot1.py` : 18/18 (catalogues, parité T24, résolution, overrides, modes legacy / shadow / enforce
  sur tenant jetable, X-Tenant-Id, suspendu, compte désactivé, audit non silencieux).
- Agent de test `test_reports/iteration_37.json` : 25/25 + 1 skip volontaire (`tests/test_lot1_qa_agent.py`), 0 critique ;
  2 remarques mineures corrigées (console superadmin jamais verrouillée par un tenant suspendu hors `/livre` ; repli `default` `/auth/users`).
- Ciblés : 219/219 (multitenant, administration, impersonation, driver_vehicle_access, iteration18_readonly_invite,
  navixy_multitenant, phase3_admin_driver, private_mode_gate / phase2 / confirmation, reports_private_redaction,
  notifications, iteration6_privacy_enforcement).
- **Régression complète : 922 PASS / 0 FAIL / 4 SKIP / 4 warnings — 567 s (14:17:49 → 14:27:18 UTC).**
  Baseline 878 / 1 / 3 : +44 tests (Lot 1 + QA), `test_energy_cache::test_hit_dans_ttl_e2e` connu **PASS** ce run
  (flake environnemental, non modifié), +1 skip = skip volontaire QA. Aucune nouvelle régression.
- Preview : backend redémarré (`legacy` chargé, `/auth/me` → `access_control_mode=legacy`), smoke 22 endpoints admin / driver
  conformes. PROD non touchée, aucun deploy, aucune migration, 0 tenant initialisé, aucune écriture device Navixy.

### Fichiers
- Créés : `backend/app/access_control.py`, `backend/tests/test_access_control_lot1.py` (+ `backend/tests/test_lot1_qa_agent.py`
  et `test_reports/iteration_37.json`, `test_reports/pytest/lot1_qa_agent.xml` par l'agent de test).
- Modifiés : `backend/app/auth.py`, `backend/app/audit.py`, `backend/.env` (+1 clé), `backend/app/routes/{ble,dashboard,energy,fines,fuel,fuel_statements,identification,misc,monthly_report,notifications,reports,settings,team,weekly_report}.py`, `memory/PRD.md`, `memory/CHANGELOG.md`, `memory/test_credentials.md`.
- Supprimés : aucun. Baseline non suivie intouchée : `.env.example`, `frontend/yarn.lock`, `logitrak-driver-app/.env.example`, `logitrak-driver-app/yarn.lock`, `yarn.lock`.
- Effets de bord de la suite de tests (pré-existants) : `test_reports/pytest/iteration23_evidence.json` réécrit, 1 PNG de test dans `backend/storage/fuel/transactions/`.

## 26/08/2026 — MAPPING TENANT ENERGY + CAMPAGNE REAL ENERGY (energie.logitrak.ch)

### Contexte
- Le projet ÉNERGIE (externe, jamais modifié depuis ce workspace) est déployé en production
  sur le VPS utilisateur : `https://energie.logitrak.ch` (TLS valide, auth Bearer active).
- `backend/.env` : `ENERGY_API_BASE_URL=https://energie.logitrak.ch` (bascule depuis l'URL preview),
  `ENERGY_API_TOKEN` inchangé (64 car., jamais affiché).

### Lot mapping tenant (vérifié puis complété)
- `settings.energy_tenant_id` par tenant Journal (doc settings tenant-scoped via proxy Mongo),
  fail-closed : AUCUN appel HTTP Energy tenant-specific sans mapping explicite. Pas de variable globale.
- Routes : GET/PUT `/api/livre/energy/tenant-mapping` (GET admin+manager, PUT admin seul,
  validation `^[A-Za-z0-9_.-]{1,64}$`, audit `log_audit` sans token).
- Fail-closed appliqué dans `/status`, `/trips`, `/overview` et `_build_reconciliation`
  (preview + exports + candidats d'alertes).
- Mapping persisté via PUT admin audité : `default → paas_13588`. Client Test B : AUCUN mapping
  (fail-closed prouvé, aucune fuite des données paas_13588).
- UI : `EnergyTenantCard.jsx` dans Paramètres (admin modifie, manager lecture disabled,
  chauffeur/lecture_seule sans accès page ; badge Configuré/Non configuré ; jamais de token).

### Correctifs client Journal prouvés pendant la campagne (energy_client.py)
1. Batch : Energy résout le véhicule par `ref` (= navixy_tracker_id) + fenêtre `start`/`end`
   → items wire enrichis (`ref`, `start`, `end`), champs Journal conservés.
2. Vehicle summary : `{ref}` du path = navixy_tracker_id (le query param n'est PAS résolu par Energy).

### Correctifs exports/UI
- `reports.py` : suffixe « (périmé) » sur le type de mesure quand availability=STALE (XLSX + PDF rapprochement).
- `EnergyOverviewPage` : « contrat vv1 » corrigé, unité technique `count` masquée.
- `EnergyReconciliationPage` : nesting <div> dans <p> corrigé (drawer).
- `TripEnergyBlock` : REASON_LABEL += no_per_trip_energy, mapping_invalid, energy_tenant_not_configured.

### Preuves HTTP réelles (agent-tested, https://energie.logitrak.ch)
- Health : 200, contract_version "v1" (ÉCART documenté vs batch "1.0"), navixy_configured true.
- Auth : sans token 401 / bon token 200.
- Batch direct : contract "1.0", fuel/electric DIRECTS, pas de clé `energy`, null jamais 0,
  ref 781479 résolu, ref 999999 → mapping_invalid, powertrain UNKNOWN conservé.
- Fleet : 6 métriques exactes (nulls honnêtes, obd_coverage 25% ESTIMATED, vehicles_with_data 3).
- Vehicle 781479 : fuel_liters_total 28.0 L / STALE / MEASURED / NAVIXY_CAN (ts 2024-06-20).
- Via Journal : batch trip pilote → UNAVAILABLE `no_per_trip_energy` (honnête, tracker résolu) ;
  overview réel ; rapprochement 18 lignes / 6 non mappés, AUDI 28.0 L badge Périmé, statut
  IMPOSSIBLE (0 achat carburant — achats ≠ conso respecté) ; XLSX « Mesuré (périmé) » ;
  PDF rapprochement conforme ; PDF fiscal « Estimé* » conservé.
- Résilience réelle : Energy down (404 avant déploiement VPS) → indisponibilité propre, rien inventé.

### Tests
- Ciblés : 26/26 PASS (test_energy_tenant_mapping complet avec Energy réel + test_energy_contract).
- 6 tests legacy adaptés (comportement voulu : fail-closed avant trip_not_found, mode connecté réel,
  suffixe (périmé), raison batch appartenant à Energy).
- RÉGRESSION COMPLÈTE : **582 PASS / 0 FAIL / 3 SKIP** (run isolé propre).
  Note : 1 faux échec `test_no_dispatch_to_notifications` lors de 2 runs pytest concurrents
  (course sur notifications_log par événements ble.resolved d'une autre suite) — 41/41 PASS en isolation,
  la préparation d'alertes ne touche JAMAIS notifications_log.
- Testing agent frontend iteration_29.json : **7/7 PASS** (carte tenant admin/manager, RBAC chauffeur,
  overview réel sans zéro, rapprochement réel + badge Périmé, exports téléchargés, bloc trajet honnête).
  Mapping production restauré par le testing agent après son test d'écriture.

### Décision real_energy_validated : FALSE (inchangé)
Bloquants exacts :
1. Energy ne fournit pas encore d'énergie PAR TRAJET (no_per_trip_energy honnête) —
   la consommation réelle par trajet n'est pas prouvable aujourd'hui.
2. Risque legacy latent BEV : 0,085 L/km appliqué à la synchro sans filtre motorisation
   (aucun BEV actuel ; jamais présenté comme mesuré — étiqueté Estimé partout).
3. Le GO utilisateur exigeait explicitement « real_energy_validated reste false » — flip
   uniquement sur décision utilisateur explicite.

### Risques externes Energy (P1, non modifiables d'ici)
- Energy accepte un tenant optionnel avec fallback tenant par défaut côté Energy
  (prouvé : mapping sans tenant → tenant Energy par défaut avec les 12 trackers).
  Neutralisé côté Journal par tenant explicite fail-closed.
- Écarts contrat : health "v1" vs batch "1.0" ; fleet/vehicle summary sans contract_version.

### Non modifié (conformément aux règles)
Projet ÉNERGIE, legacy 0,085 (navixy_sync.py:39/275), 6 véhicules non mappés,
Mongo historique (5 421 trips), PDF fiscal legacy, alertes réelles (désactivées),
real_energy_validated (false).

## 26/08/2026 (après-midi) — GARDE-FOU BEV : legacy 0,085 L/km filtré par motorisation

### Règle métier (centralisée dans app/navixy_sync.py)
- `POWERTRAIN_FROM_FUEL_TYPE` (mapping canonique unique, réutilisé par routes/energy.py — plus de duplication)
  + `powertrain_from_fuel_type()` + `legacy_fuel_estimation_allowed(vehicle)`.
- Source motorisation : UNIQUEMENT `vehicles.fuel_type` (jamais nom/modèle/plaque/label).
- ICE (ice/diesel/essence/petrol) → legacy autorisé.
- BEV (electric/bev/ev) → legacy INTERDIT → fuel_l ABSENT (jamais 0).
- HEV/PHEV → cas ambigu, aucune convention 8,5 L/100 validée pour hybrides → PAS de calcul (documenté).
- UNKNOWN → legacy CONSERVÉ (dette résiduelle documentée : flotte actuelle 0/18 motorisations
  renseignées, fiscalité existante préservée). UNKNOWN jamais converti en BEV/ICE.
- `_build_trip_doc` : fuel_l écrit conditionnellement. AUCUNE migration Mongo (historique intact,
  pilot trip fuel_l=0.66 vérifié). Seed mock démo : véhicules sans fuel_type → UNKNOWN → inchangé.

### Affichages corrigés (absence fuel_l → jamais 0)
- HistoryPage : « — » (testid trip-fuel-na-{id}) au lieu de 0.00 L.
- reports.py : CSV/XLSX cellule vide (t.get("fuel_l") sans défaut 0) ; PDF trajets « — ».
- Totaux/PDF fiscal : sommes inchangées (un BEV ne contribue aucun litre — vérifié tax-swiss 2023 test).

### Tests
- Nouveau `tests/test_legacy_fuel_guard.py` : 22/22 PASS (T1-T15 sauf T11 UI ; helper, _build_trip_doc,
  historique intact, API trips null, exports CSV/XLSX/PDF, PDF fiscal, TripEnergyBlock indépendant).
- RÉGRESSION COMPLÈTE : 603 PASS / 0 FAIL réel / 3 SKIP (1 flaky infra : OCR amendes 502 ingress
  preview pendant appel Gemini — 5/5 PASS en re-run isolé, module non touché par le lot).
- Testing agent iteration_30.json : 5/5 PASS frontend (HistoryPage —/8.50 L, TripEnergyBlock honnête,
  exports XLSX vide + PDF —, non-régression Énergie : AUDI 28.0 L Périmé, motorisations Inconnue).
- real_energy_validated : toujours false (flag non modifié). Projet ÉNERGIE non modifié. Mongo non migré.

### Dette résiduelle / P-liste
- P2 : UNKNOWN reçoit encore le legacy (par choix documenté) — se résorbera quand fuel_type sera renseigné.
- P3 : total fiscal d'une période 100% BEV afficherait « 0.00 » (somme réelle vide) — cosmétique, non traité.
- P3 : date inputs natifs (mm/dd/yyyy) au lieu du Calendar shadcn (pré-existant, relevé 2× par testing agent).

## 26/08/2026 (soir) — MOTORISATIONS RÉELLES : vehicles.fuel_type depuis sources prouvées

### Sources examinées (18 véhicules, lecture seule d'abord)
- Source A (DB structurée) : fuel_type 0/18, VIN 0/18, pas de powertrain/engine_type.
  tank_capacity_l=65 sur « 1-Enyaq 01 Bern » (saisie référence capacité, PAS une preuve de motorisation).
- Source B (VIN) : NON DISPONIBLE (0/18 + aucun décodeur VIN configuré).
- Source C (Documents) : NON DISPONIBLE (aucune collection documents véhicule).
- Source D (Navixy garage, API réelle vehicle/list) : 10 véhicules Navixy, 5 liés par tracker_id.
  2 avec champ structuré fuel_type : Audi A3 2018 (tracker 781479) = petrol + « Sans plomb 95 » +
  VIN WAUZZZ8VJA151370 ; Toyota Previa (tracker 3131157) = petrol (VIN non normalisé, non utilisé).
- Source E (Energy) : powertrain UNKNOWN partout — rien d'utilisable, non falsifié.

### Écritures (2/18, via nouvel endpoint audité)
- LOGITRAK AUDI → fuel_type=essence (normalisation canonique petrol→essence, mapping ICE).
- 5-Alliance 01 → fuel_type=essence.
- 16 restants → UNKNOWN (dont Zoe/Enyaq×3/Volvo EX30 : noms évocateurs, déduction INTERDITE ;
  6 GE-* archivés démo ; iPhone/Tab traceurs ; ORHAN/IVAN/NEDIR sans source).

### Code
- Backend misc.py : PUT /api/livre/vehicles/{id}/fuel-type — admin only, valeurs contrôlées
  (diesel/essence/hybrid/phev/electric/null), audit vehicle.fuel_type_updated (before/after/source).
- Frontend SettingsPage : colonne « Motorisation » (Select contrôlé, admin only, manager disabled)
  dans le sheet Gérer les véhicules. testid settings-vehicle-fueltype-{plate}.
- Aucun changement du helper garde-fou. Aucun recalcul des 5 435 trips historiques.
- Effet dérivé attendu : rapprochement affiche AUDI/Alliance = Thermique (ICE) ; Energy garde
  son powertrain UNKNOWN (JOURNAL=ICE vs ENERGY=UNKNOWN documenté, aucune falsification).

### Tests
- tests/test_vehicle_fuel_type.py : 17/17 PASS (T1-T18 ; T UI via testing agent).
- 1 test legacy adapté : test_powertrain_never_inferred (powertrain == mapping du fuel_type prouvé).
- RÉGRESSION COMPLÈTE : 621 PASS / 0 FAIL / 3 SKIP (run final propre ; flaky OCR infra 502 re-testé 5/5).
- Testing agent iteration_31 : 5/5 PASS (colonne, valeurs, edit admin + restauration, RBAC manager
  disabled, rapprochement Thermique + 28.0 L Périmé conservé, historique intact).

### P3 notés (testing agent, non corrigés — hors périmètre)
- Flicker du sheet véhicules après changement (load() complet au lieu d'un update local).
- Double mécanisme RBAC dans la même table (canEdit vs role==='admin').
- SettingsPage.jsx 527 lignes (extraction composant possible).

## 27/08/2026 — ACCÈS VÉHICULES PAR CHAUFFEUR (ALL / SELECTED / SINGLE + véhicule par défaut)

### Modèle
- Champs sur doc `drivers` : vehicle_access_mode (ALL|SELECTED|SINGLE, ABSENT = ALL implicite),
  allowed_vehicle_ids, default_vehicle_id. AUCUNE migration Mongo : défaut implicite ALL préserve
  le comportement historique (claim libre dans le tenant) — aucun chauffeur ne perd de véhicule.
- `assignments` (qui conduit quoi, résolution trajets) INCHANGÉ et distinct du modèle d'accès.

### Backend (source d'autorité)
- Nouveau app/vehicle_access.py : get_vehicle_access, get_authorized_vehicles_for_driver,
  get_authorized_vehicle_ids_for_driver, assert. Véhicules actifs uniquement
  (active≠False, deleted≠True, archived≠True). Default hors périmètre invalidé (jamais arbitraire).
- team.py : GET (admin+manager) / PUT (admin only) /team/drivers/{id}/vehicle-access.
  Validations : SELECTED ≥1 véhicule existant du tenant ; SINGLE exactement 1 (default auto) ;
  default ∈ périmètre ; audit driver.vehicle_access_updated (before/after complets).
- identification.py : GET /driver/vehicles (access_mode + default + véhicules autorisés, tenant
  depuis l'identité) ; claim → 403 hors périmètre (même tenant) ; fleet-tags filtrés pour role driver.
- _helpers.filter_trips_query : historique par véhicule intersecté avec le périmètre autorisé
  (ne peut jamais élargir ; ALL = comportement identique à avant).

### Frontend admin
- DriverVehicleAccessCard.jsx montée dans DriverSheet (fiche chauffeur, /livre/conducteurs/chauffeurs) :
  radios 3 modes, multi-select recherchable + compteur, dropdown default limité au périmètre,
  toast de confirmation, RBAC UI (manager lecture seule). DriverConsolePage NON modifiée (phase 2 séparée).
- Fix a11y pré-existant : Badge <div> dans <p> (Méthodes d'identification) → <div>.

### Tests
- tests/test_driver_vehicle_access.py : 25/25 PASS (T1-T20 : ALL tenant-only, SELECTED exact,
  SINGLE, defaults, cross-tenant 404/400, RBAC driver/manager 403, inactif exclu, liste vide sans
  fallback, assignments préservés, claim 403 = aucune session créée pendant les tests).
- 1 test legacy adapté : claim véhicule inexistant → 403 (fail-closed avant résolution) au lieu de 404.
- RÉGRESSION COMPLÈTE : 646 PASS / 0 FAIL / 3 SKIP (run final propre).
- Testing agent iteration_32 : 8/8 PASS (section fiche, SELECTED 4 véhicules + compteur, default
  limité, persistance reload, SINGLE, restauration production, RBAC manager, aucun cross-tenant).
- État final : Jean Dupont restauré ALL/Aucun ; 0 véhicule de test résiduel.

### Prochaine étape convenue (GO séparé)
- Prompt n°2 : DriverConsolePage.jsx consomme GET /api/livre/driver/vehicles
  (auto-sélection SINGLE, default proposé, choix si plusieurs sans default, message si aucun véhicule).

## 27/08/2026 (suite) — Uploads amendes migrés vers Emergent Object Storage
- Nouveau app/object_storage.py (init lazy + re-mint sur 404, put/get httpx async, préfixe logitrak-journal).
- fines.py : upload → put_object (storage_path canonique en meta), download → get_object
  (fallback lecture disque legacy pour anciens fichiers preview), delete → soft-delete meta.
- Migration one-shot : 1 document réel migré (les autres fichiers disque = orphelins de tests sans meta).
- Prouvé e2e réel : upload → download octets identiques → delete 404. Suite fines : 61/61 PASS
  (1 test adapté : vérification storage_path au lieu du disque).
- Raison : le stockage pod-local est perdu au déploiement (blocage pré-déploiement levé).

## 08/09/2026 — Console Chauffeur : accès véhicules (frontend, LIVRÉ)
- Nouveau DriverVehiclePicker.jsx monté dans DriverConsolePage (/driver) : consomme exclusivement
  GET /api/livre/driver/vehicles — jamais /livre/vehicles (liste globale) côté chauffeur.
- Logique pure lib/driverVehicleSelection.js : priorité sélection active valide > localStorage valide
  (clé logitrak.driver.vehicle.<userId>, purge si non autorisé) > default backend > unique > aucune.
- Fail-closed : erreur API = état erreur explicite + bouton Réessayer, aucune liste, aucune sélection.
- SINGLE : auto-sélection + sélecteur verrouillé (badge ATTRIBUÉ + cadenas). SELECTED : liste exacte.
- Révocation en session : refresh (driver-refresh) → désélection + notice « n'est plus autorisé » + purge.
- Liste vide : empty state explicite. Bouton « Je conduis ce véhicule » → POST /driver/claim (403 backend géré).
- Backend INCHANGÉ. Energy/Object Storage/cache rapprochement intouchés. real_energy_validated=false.
- Tests : jest T1–T10 11/11 PASS · testing agent iteration_33 : 7/7 PASS (ALL/SELECTED/SINGLE, persistance,
  révocation, 403, cleanup mode ALL restauré) · régression backend unique 646 PASS / 0 FAIL / 3 SKIP.

## 08/09/2026 (suite) — Cache rapprochement Energy (LIVRÉ)
- Nouveau app/energy_cache.py : cache mémoire éphémère (non persistant), TTL 60 s,
  TTL erreur 30 s (erreur transport JAMAIS conservée au TTL normal). Aucune collection Mongo.
- Clé : tenant Journal + tenant Energy + vehicle_id|ref + période + type de summary — zéro partage cross-tenant.
- _build_reconciliation (source unique preview/XLSX/PDF/candidates) cache les réponses Energy BRUTES
  sanitizées ; rapprochement toujours recalculé localement (achats/seuils actuels). Valeurs jamais modifiées
  (null≠0, STALE conservé, measurement_type/source/timestamp intacts — prouvé rows MISS == rows HIT).
- preview?refresh=true = BYPASS réel (appels Energy refaits + cache mis à jour). Bouton « Actualiser »
  ajouté sur /livre/energie/rapprochement (recon-refresh-btn). Réponse preview expose bloc cache
  {ttl_seconds, persistent:false, hit, miss, expired, bypass}. Logs HIT/MISS/EXPIRED/BYPASS sans secret.
- Fail-closed inchangé : tenant sans mapping → aucun appel/cache véhicule (health non tenant-specific conservé).
- Perf réelle (energie.logitrak.ch) : MISS 7,9 s → HIT 0,16 s ; XLSX 0,15 s ; PDF 0,18 s après preview.
- Tests : test_energy_cache.py 24/24 PASS · testing agent iteration_34 : tout PASS ·
  régression complète 670 PASS / 0 FAIL / 3 SKIP. real_energy_validated=false (absent en DB).

## 08/09/2026 (suite) — Pré-déploiement cache Energy (READ-ONLY, aucun déploiement)
- Modèle process prod vérifié : compose 1 replica, Dockerfile CMD uvicorn SANS --workers → 1 process,
  cache mémoire partagé entre requêtes = OK pour prod. Vérif résiduelle VPS fournie (docker exec ps).
- +1 test unitaire : erreur transport écrase l'ancienne valeur AVAILABLE et reste explicite (11/11 module).
- BLOQUANT identifié : ENERGY_API_BASE_URL / ENERGY_API_TOKEN absents de docker-compose.yml et env.example
  → en prod Energy serait not_connected. Patch minimal (2 lignes compose + 2 clés .env VPS) proposé, NON appliqué.
- Delta lot cache (commit 110877f) : backend energy_cache.py + routes/energy.py ; frontend EnergyReconciliationPage.jsx ;
  tests test_energy_cache.py. env NON modifié, DB migration NON, Energy NON modifié.
- Commandes déploiement + rollback + smoke test post-deploy préparées, AUCUNE exécutée (attente GO).

## 08/09/2026 (suite) — RÉCONCILIATION private-mode-pilot + Energy (mergée en preview, NON déployée)
- Découverte : prod VPS = branche feat/private-mode-pilot (131 commits, historique orphelin du 16/08 :
  console chauffeur MODE MANUEL + Mode Privé + SOS + km, page admin Kilométrage/calibration odomètre,
  chiffrement credentials Navixy, app Expo). Notre lignée (151 commits) = Energy/rapprochement/cache/
  accès véhicules/Object Storage/BEV. Aucun ancêtre Git commun → fusion 3-way par contenu
  (BASE=e998ac6 Clôture Phase 3, clone isolé /root/reconcile, graft local, aucun push).
- Résolution : 229 identiques, 10 conflits résolus en conservant LES DEUX lignées. Décisions clés :
  console web = version prod mode manuel, MAIS picker rebranché sur GET /driver/vehicles (source
  d'autorité ALL/SELECTED/SINGLE) ; my-vehicles backend désormais INTERSECTÉ avec vehicle_access ;
  claim 403 conservé ; routes __init__ = energy + odometer_calibration ; misc = redact_private_trip
  + fuel_l_meta ; App.js = redirect conducteurs + route kilometrage ; .emergent/PRD/test_reports = nôtres.
- Console BLE web remplacée par le mode manuel (décision prod assumée) ; DriverVehiclePicker.jsx démonté
  mais conservé avec lib driverVehicleSelection + tests jest.
- Fix infra tests prod : _run() event-loop robuste (test_migrate_navixy_hash, test_odometer_calibration).
- Preview : PRIVATE_MODE_ENABLED absent = fail-closed prouvé (PRIVATE_MODE_FEATURE_DISABLED, bouton Privé disabled).
- Tests : régression combinée 830 PASS / 0 FAIL / 3 SKIP · testing agent iteration_35 : 12/12 + frontend 100 %,
  0 défaut (deux lignées). real_energy_validated=false. AUCUN déploiement VPS.
- P3 connu : warning a11y DialogContent (picker véhicule, préexistant lignée prod) ; warning eslint VehicleOdometerPage.

## 9 juin 2026 — Correctifs A+B Console Chauffeur (incident « pas de véhicules »)
- Diagnostic prod : backend SAIN (Orhan → ALL → 14 véhicules, prouvé par curl interne + proxy public). Cause : index.html servi sans Cache-Control (ancien bundle en cache possible) + état « Aucun véhicule sélectionné » mal interprété.
- Correctif A : frontend/nginx.conf → `location = /index.html { add_header Cache-Control "no-cache"; }` (assets /static/ restent immutable 30j). Effet au prochain rebuild frontend.
- Correctif B : DriverConsolePage.jsx → picker inline remplacé par le composant autoritaire DriverVehiclePicker (GET /livre/driver/vehicles exclusif) dans la modal ; états erreur (Réessayer) / vide (« Aucun véhicule autorisé ») distincts ; pré-sélection du défaut si autorisé ; claim explicite ; auto-ouverture de la modal si aucun véhicule (ref autoOpenedRef). Anciens testids driver-picker-item-*/driver-picker-empty supprimés.
- Backend NON modifié. Tests : unit 11/11, testing agent iteration_36 6/6 PASS, auto-open self-testé (compte temporaire créé puis supprimé), build prod OK (my-vehicles absent du bundle).
- Déploiement prod : rebuild journal_frontend UNIQUEMENT requis (backend inchangé).

## 9 juin 2026 (suite) — Resync hotfix + sécurisation tests + régression 0 FAIL
- Resync workspace ← prod 0aad5fd : 4 fichiers backend (odometer_calibration, odometer_capability, private_mode_engine, routes/odometer_calibration) — byte-identiques (sha256 4/4 vérifiés contre prod).
- 5 assertions `== 18` remplacées par comptage dynamique des véhicules actifs (4 fichiers de tests Energy/Reconciliation + iter35).
- DÉCOUVERTE CRITIQUE : test_iteration6_privacy_enforcement appelait POST /privacy/kill-switch qui envoie TOUJOURS des commandes réelles ; la preview a un credential Navixy actif → des `setparam 11000:0` réels sont partis vers 8 trackers (12:49 et 13:53 UTC) lors des suites complètes (mécanisme présent depuis l'itération 6). Tracker 781479 vérifié READ-ONLY après coup : TRACKING, télémétrie fraîche, AVL16 vivant — pas de dégât.
- Sécurisation (tests uniquement, kill_switch() produit INTACT) : (A) purge tracker_privacy_state en début de module ; (B) barrière anti-device-write = navixy_api_url tenant → sinkhole 127.0.0.1:9 pendant le module (posée/retirée via PATCH superadmin) ; (C) assert 0 cible private avant tout kill-switch ; + 3 tests de preuve dont kill-switch avec cible fictive → sent:0/errors:1.
- t15 (driver_vehicle_access) : baseline filtré `^TEST-` (artefacts d'autres suites exclus) ; 2 orphelins TEST-ASGN purgés ; hygiène anti-accumulation ajoutée au module fines.
- RÉGRESSION FINALE : **845 PASS / 0 FAIL / 3 skip** (409 s). Post-run : 0 commande real+success, 0 private, navixy_api_url restaurée, 4 assignments navixy réels intacts.
- Rien déployé ; prod reste sur 0aad5fd (contient déjà correctifs A+B Console Chauffeur + hotfix odomètre).

## 9 juin 2026 — App mobile : P0+P1 (picker autoritaire, périmètre, WebSocket)
- Audit écran par écran mobile vs backend : 3 écarts (picker manuel sur /driver/my-vehicles = bug Orhan reproduit en live ; flotte globale /livre/vehicles exposée en mode BLE/VehiclePicker ; WS token en query param → 4401 systématique).
- P0 : DriverScreenManual → GET /driver/vehicles exclusif ; états loading/error(Réessayer)/vide distincts ; pré-sélection (actuel autorisé > défaut autorisé > unique, jamais le 1er arbitraire — module pur src/utils/driverVehicleSelection.ts, parité web T1–T10) ; claim explicite « Je conduis ce véhicule » ; auto-ouverture si aucun véhicule ; badge mode ALL/SELECTED/SINGLE (SINGLE verrouillé).
- P1 : vehiclesStore réécrit sur /driver/vehicles (fail-closed, accessMode/defaultVehicleId exposés) → recherche/récents/VehiclePicker/mode BLE tous scopés ; getVehicles+getMyVehicles supprimés de l'API mobile.
- P1 WS : buildRealtimeConnection (token JAMAIS dans l'URL, header Authorization via 3e arg WebSocket RN) ; close 4401 → attente plafond 30s (pas de boucle agressive).
- Tests : 73/73 PASS (15 nouveaux : sélection T1–T10, store SELECTED/EMPTY/ERROR fail-closed, garde statique anti /livre/vehicles + /driver/my-vehicles, WS sans token dans URL). tsc propre. Backend : 0 fichier modifié (845/0/3 intact).
- Reste : validation réelle sur téléphone (Expo Go mode manuel, puis BLE en dev build).

## 9 juin 2026 — Rapport hebdomadaire chauffeurs (gel backend levé pour ce chantier, GO utilisateur)
- Service `backend/app/weekly_driver_report.py` : agrégation semaine civile précédente (lundi 00:00 → dimanche 23:59:59 Europe/Zurich, bornes UTC correctes y c. passage heure d'été) ; 1 ligne/chauffeur : km PRO / PRIVÉ / non classifiés / TOTAL (= tous les km parcourus), nb trajets, véhicules utilisés (plaque+modèle), trajets non classifiés restants. Ligne « — Sans chauffeur — » si trips orphelins.
- Rendu : `weekly_driver_report_to_pdf/xlsx` dans `reports.py` (patterns existants, MÊME dataset pour les 2 formats, lignes non-classifiés surlignées en PDF, note « Km total = tous les km »).
- Routes `backend/app/routes/weekly_report.py` (admin/manager, tenant strict) : GET/PUT `/api/livre/reports/weekly-driver/config` (enabled + destinataires ≤20 validés/dédupliqués, audit) ; GET `/download?week=YYYY-MM-DD&format=pdf|xlsx` (date ramenée au lundi, semaine vide = rapport valide « aucune donnée », audit).
- Job APScheduler `weekly_driver_report` : CRON lundi 06:00 Europe/Zurich ; par tenant enabled → agrégation → PDF+XLSX → 1 email, 2 pièces jointes (emailer étendu `send_email_with_attachments`) ; statuts loggés `weekly_report_log` : sent / not_sent_smtp_not_configured / not_sent_no_recipients / error / already_sent (idempotence par tenant+semaine, seul `sent` bloque la relance) ; échec tenant isolé ; SMTP absent ne fait jamais échouer le job.
- UI : `WeeklyDriverReportCard.jsx` dans Paramètres (admin/manager) : toggle, destinataires, lecture seule (période, formats, prochain envoi, dernier envoi+statut, statut SMTP), téléchargement manuel PDF/XLSX par semaine. data-testid `weekly-report-*`.
- Tests : 17 nouveaux (`tests/test_weekly_driver_report.py`, SMTP 100 % mocké, 0 email réel) : bornes/DST, agrégation exacte (bornes dimanche 23:30 locale incluse / lundi 00:30 exclue), RBAC (driver 403), validation, tenant isolation, XLSX valeurs exactes, semaine vide, job sent/idempotent/no-smtp/no-recipients/disabled/error.
- RÉGRESSION FINALE : **862 PASS / 0 FAIL / 3 skip** (516 s, run unique séquentiel). Post-run : 0 commande real+success pendant la fenêtre, 0 private résiduel, navixy_api_url restaurée, 4 assignments réels intacts, artefacts TEST-WKR purgés, config settings restaurée, SMTP_HOST absent du .env preview (0 email réel possible).
- STOP respecté : aucun deploy/push/commit manuel. SMTP prod : statut toujours NON VÉRIFIÉ (sortie VPS attendue) — sans SMTP le rapport reste généré + téléchargeable, seul l'e-mail est sauté.

## 10 septembre 2026 — Rapport mensuel fiscal chauffeurs (item backlog choisi, backend additif)
- Refactor minimal `weekly_driver_report.py` : cœur d'agrégation extrait en `aggregate_range(db, start_iso, end_iso)` ; `aggregate_week` l'enveloppe (17 tests hebdo re-PASS).
- Service `backend/app/monthly_driver_report.py` : `parse_month/previous_month/month_bounds/year_start_iso` (Europe/Zurich, DST géré), `aggregate_month` = agrégation du mois + agrégation cumul annuel (01/01 → fin du mois) ; par chauffeur : `pct_private` (km privés / km classifiés, `None` si aucun classifié — jamais 0), `ytd_km_pro/private/unclassified`, `fiscal_status` complete|incomplete ; totaux + `incomplete_drivers`. Job `run_monthly_report_job(year_month)` : mêmes statuts que l'hebdo, log `monthly_report_log`, idempotence tenant+mois, SMTP absent non bloquant.
- Renderers `monthly_driver_report_to_pdf/xlsx` (`reports.py`, 12 colonnes, lignes « À compléter » surlignées, notes % privé / cumul / statut, aucun montant CHF).
- Routes `routes/monthly_report.py` (admin/manager) : GET/PUT `/api/livre/reports/monthly-driver/config` (clés `monthly_report_enabled/recipients`, audit `reports.monthly_driver.config_update`), GET `/download?month=YYYY-MM&format=pdf|xlsx` (400 mois invalide, 422 format, audit). Scheduler : CRON `day=1 06:00 Europe/Zurich`, `monthly_report_next_run()`.
- UI : `MonthlyDriverReportCard.jsx` sous la carte hebdo dans Paramètres (toggle, destinataires, prochain/dernier envoi, statut SMTP, `<input type="month">` + PDF/XLSX).
- Tests : `tests/test_monthly_driver_report.py` 17 PASS (SMTP 100 % mocké) ; suite hebdo+mensuel 34/34 ; téléchargement XLSX réel via navigateur vérifié ; DB restaurée. Pas de deploy/push/commit.

## 10 septembre 2026 — Régression backend finale après rapport mensuel (GO utilisateur)
- Run unique séquentiel `pytest tests/` : 878 PASS / 1 FAIL / 3 skip / 4 warnings en 448 s. FAIL unique `test_energy_cache::TestCacheE2E::test_hit_dans_ttl_e2e` = flake dépendant de la latence Energy réel (entrées erreur TTL 30 s expirées entre r1 et r2) ; rejoué seul : 25/25 PASS. Aucun fichier modifié avant/pendant le run.
- Contrôles : 0 commande Navixy real+success, 0 send_command, URL Navixy restaurée, assignments 4/4 intacts, expected_state private 0, états simulés 11 (aucun réel), configs rapports restaurées, artefacts TEST-WKR/MKR 0, SMTP absent en preview. Dette de tests pré-existante : drivers TEST_INV_/TEST_PEND non nettoyés (test_iteration18), evidence JSON réécrit, PNG test fuel. Aucun push/deploy/commit manuel (checkpoint plateforme 9a91209 automatique).
