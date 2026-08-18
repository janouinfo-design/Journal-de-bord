# Logitrak — Livre de Bord Professionnel / Personnel

## Problem statement (verbatim)
Créer un nouveau module "Livre de Bord Professionnel / Personnel" dans Logitrak,
entièrement connecté à Navixy via les API de tracking et l'historique GPS.
Distinction km pro / perso, 3 modes confidentialité, rapport fiscal suisse,
affectation manuelle, droits par rôle.

## User choices
- Standalone app, JWT custom auth, backend Python (reportlab + openpyxl)
- Navixy hash fourni (`a25480874b7492bd01ff1d926061e491`) — branché en prod (api.navixy.com/v2)

## Architecture (mise à jour)
- **Backend**: FastAPI + Motor + APScheduler. Modules `/app/backend/app/` :
  `auth.py`, `db.py`, `mock_navixy.py`, `rules.py`, `reports.py`, `routes.py`,
  `navixy_client.py` (HTTP async httpx), `navixy_sync.py` (sync trackers/employees/zones/tracks),
  `scheduler.py` (auto-sync), `assignments.py` (driver↔vehicle time-aware).
- **Frontend**: React 19, sidebar dark + secondary white, IBM Plex Sans/Mono, Recharts.
- **DB**: `users`, `drivers`, `vehicles`, `trips`, `geofences`, `settings`, `audit_log`,
  `app_state` (scheduler), `assignments` (driver↔vehicle assignments).

## Implemented — 16/06/2026
### Iteration 37 — PHASE 3 : Fiche Admin Chauffeur + KPI Identification + « Je m'arrête » (18/08/2026) — TESTING AGENT (iteration_24.json : 27/27 PASS backend + frontend Playwright, régression 176/176)
- **Page /livre/administration/chauffeurs (admin + manager)** : table Chauffeur/Compte/Identification/Véhicule actuel/Session/Dernier accès/Statut/Actions, recherche + 10 filtres, menu actions (Voir/Modifier/Voir session/Activer accès/Reset mdp/Aperçu console/Délier/Désactiver). Managers via AdministrationIndex (utilisateurs/apercus restent admin-only, onglets filtrés par rôle).
- **Formulaire Nouveau chauffeur** : Identité (first_name/last_name → name calculé serveur, 400 si vide), Accès mobile (switch + email + mdp temporaire → grant-access dans le même flux), tag BLE facultatif.
- **DriverSheet (drawer fiche)** : identité, compte mobile (reset mdp temporaire one-shot affiché une fois/jamais loggé + must_change_password + purge login_attempts ; désactiver/réactiver compte via PATCH /team/users {active}), méthodes d'identification (APP: dernière connexion/confirmation ; BLE: tag, dernière détection, « Validation terrain : en attente » tant que app_state.ble_field_proof_{tid}.validated absent), session actuelle (+ Clôturer auditée), 20 dernières sessions, 15 événements audit utiles, dernière activité avec nature.
- **Endpoints nouveaux** : GET /team/drivers/{id}/overview (admin+manager), POST /team/drivers/{id}/reset-password (admin), POST /driver/stop. Liste /team/drivers enrichie (account actif/last_login, current_session+plate, last_activity) avec résolution robuste user_id ∨ users.driver_id ∨ email(role driver) via _find_driver_account.
- **« Je m'arrête »** : stop_driving idempotent (sans session → {stopped:false} 200, jamais 500), end_source=APP/end_reason=app_stop, audit driver_session_closed, sa session/son tenant uniquement, bouton rouge console chauffeur (driver-stop-btn). Fins auto conservées (trip end/timeout/admin/driver_change).
- **Page Identification refondue (sans casser l'existant)** : 8 KPI (Sessions, APP, BLE, APP+BLE, À valider, Conflits, Non identifiés=trips.unidentified, Taux tooltip "(Sessions − À valider − Conflits) ÷ Sessions") ; KPI CLIQUABLES → filtres ; PRO/PRIVÉ déplacés dans bandeau ident-trip-mode-strip ; filtres Source/Chauffeur/Véhicule (GET /ble/sessions?source&driver_id&vehicle_id) ; SourceBadge ; confiance null → « Confirmé » ; occupants « +N détectés » → dialog.
- **Moteur** : amend close → ended_at + end_reason=admin ; sweep 3e passe confirmed/manual inactives >24h → closed timeout ; audits driver.ble_tag_assigned/removed + driver.disabled/enabled.
- Nettoyage : tags test retirés, 2 sessions zombies closes, test flaky test_iteration23::test_07 corrigé (purge ble_detections avant claim).
- **Rapport final Phase 3 livré** (RÉALISÉ/PARTIEL/NON RÉALISÉ + technique + endpoint mobile /driver/stop = 18 endpoints). **STOP acté : app Expo NON commencée, en attente validation utilisateur.**
- NON RÉALISÉ connu : champ langue chauffeur, unicité internal_number/email (à confirmer), édition horodatages sessions (volontaire). Dette : warnings React pré-existants (clé dupliquée, DialogTitle Radix).

### Iteration 35 — Lot 1 Chauffeurs / Sessions conducteur v2 / Beacons Navixy (17/08/2026) — SELF-TESTÉ (30+ cas curl/python + 164 pytest régression PASS + smoke screenshot)
- **Brute force login** (`auth.py`) : 5 échecs → verrouillage 15 min (collection GLOBALE `login_attempts`, index unique identifier), message générique unique, bon mot de passe refusé pendant verrou, compteur remis à zéro au succès, audit `auth.login_failed/login_locked/login_locked_attempt` SANS mot de passe. Login refuse aussi : user.active=False, chauffeur (role driver) dont drivers.active=False. `last_login_at` stampé.
- **POST /api/auth/change-password** : vérifie mdp actuel, min 8 car., unset must_change_password, audit.
- **Moteur sessions v2** (`ble_engine.py`) : `identification_source` (APP / BLE / APP+BLE / MANUEL — distinct de PRO/PRIVÉ), `active_driver` unique par véhicule (index unique partiel tenant+vehicle where active_driver=True), statut `ending` + délai de grâce, `OPEN_STATUSES`. NOUVELLE SÉMANTIQUE conflits : plusieurs candidats NON confirmés → tous « À valider » (pending, jamais de choix au RSSI) ; conflit réservé aux CONTRADICTIONS d'identités confirmées (2 confirmés simultanés, claim vs présence récente, 2 claims concurrents). Statut confirmed/conflict jamais rétrogradé par une simple détection. Fusion sources (APP puis BLE → APP+BLE, testé).
- **« Je conduis »** : `POST /api/livre/driver/claim` — atomique (DuplicateKeyError sur index partiel), autre conducteur présent/confirmé <10 min → conflit explicite ; sinon changement volontaire (ancienne session closed + end_reason=driver_change + audit driver_change). Concurrence testée (2 claims simultanés → max 1 actif, 0 écrasement). Admin non lié à un chauffeur → 400 (bug resolve_driver_id_for_user corrigé : ne fabrique plus un driver_id depuis user.id ; valide l'existence du driver).
- **Endpoints mobile (future app Expo)** : GET /driver/my-vehicle (session courante ou dernier véhicule, AUCUNE donnée inventée), GET /driver/my-profile (compte, tag BLE, dernière détection, jamais de mdp). PUT /trips/{id}/classify ouvert au driver pour SES trajets uniquement (403 sinon).
- **Poller beacons Navixy** (`driver_beacons.py`) : POST beacon/data/read par tenant actif avec clé, mapping hardware_id→drivers.ble_id_norm + tracker→vehicle, dedup détections, RSSI plancher, tenant-scoped (set_current_tenant), inconnus JAMAIS inventés. Scheduler : poll 2 min + sweep sessions 5 min (ending→closed après grâce, stale→closed). `mark_sessions_trip_end` branché dans navixy_sync._upsert_trip (fin de trajet récente → sessions ENDING ; backfill >3h ignoré — c'était l'édition no-op perdue du lot précédent). Module VALIDÉ AVEC MOCK NAVIXY LOCAL (8/8 : parse, ingestion, session BLE, dedup, tenant, ending, sweep, backfill) — ⚠️ CHAÎNE RÉELLE tag chauffeur→Teltonika→Navixy NON PROUVÉE (PARTIEL) : script terrain `backend/scripts/ble_proof.py` + endpoint admin POST /ble/beacons/poll-now?window_min= prêts pour le test utilisateur.
- **Tags chauffeurs** : drivers.ble_id normalisé en ble_id_norm (create/update team.py), unicité par tenant (409), index tenant+ble_id_norm.
- **Dashboard KPIs** : identified_app/ble/app_ble, manual_set, confirmed, pending_validation, conflicts, detections, trips{total,unidentified,identification_rate,forced_pro/perso} — anciens noms conservés (widget compatible, vérifié screenshot).
- **Tests mis à jour (nouvelle sémantique)** : test_phase_a_regression (multiples candidats → pending ; conflit = contradiction confirmée, helper _force_conflict), test_notifications (reset prefs pollution + conflit via confirmations), superadmin pw via env (était hardcodé obsolète), fuel_anomalies count>=1 (dérive démo 5 anomalies). Bug cleanup-test-data corrigé (filtrait tag_id au lieu de ble_tag_id). Suites : 84+80 PASS.
- **RESTE (phases suivantes validées utilisateur)** : Phase 2 preuve BLE terrain réelle (utilisateur fera le test avec tag physique), Phase 3 fiche admin chauffeur + KPIs page Identification UI + champs first/last name/langue/wizard, Phase 4 régression complète testing_agent 12 cas, Phase 5 rapport strict RÉALISÉ/PARTIEL/NON RÉALISÉ.

### Iteration 36 — Régression complète Phases 1–2 (17/08/2026) — TESTING AGENT (iteration_23.json)
- 16 scénarios du cahier des charges exécutés : **14 PASS, 2 PARTIEL** (T08 APP+BLE = simulation uniquement ; T16 preuve BLE terrain = en attente test physique utilisateur), 0 FAIL, 0 critique.
- Suite pérenne créée : `backend/tests/test_iteration23_regression.py` (17 tests, ~18 s, rejouable).
- Rapport complet RÉALISÉ/PARTIEL/NON RÉALISÉ + tableau des tests + liste exacte des 17 endpoints mobile (Expo) livré à l'utilisateur dans le chat (17/08). `/api/auth/refresh` accepte le refresh_token en body (prévu Expo).
- Points mineurs notés (non bloquants) : tenant_id absent de la réponse POST /team/drivers ; pas d'unicité internal_number ; tenant B sans véhicules API ; warning React clé dupliquée (préexistant).
- **STOP Phase 3 demandé par l'utilisateur** : fiche Admin Chauffeur + KPIs Identification en attente de sa validation du rapport.

### Iteration 34 — Widget Carburant tableau de bord (31/07/2026) — SELF-TESTÉ (cohérence totaux vérifiée par calcul indépendant + RBAC + multi-tenant + navigation filtrée via screenshot)
- Backend `GET /livre/fuel/widget` (admin/manager/lecture_seule 200 ; chauffeur 403) : mois courant fuseau Europe/Zurich, date comptable sinon transaction (même logique que les décomptes) — coût CHF, tx_count, litres/kWh séparés, comparaison mois précédent (delta % ; null si aucune donnée — jamais de division par zéro), unmatched_count + fx_pending_count globaux tenant, anomalies open/critical, état du décompte mensuel (mois précédent sinon courant, sinon « À créer »)
- Frontend `components/fuel/FuelWidget.jsx` inséré dans DashboardPage (avant FinesWidget) — 7 indicateurs TOUS cliquables vers les listes pré-filtrées : coût/litres/kWh → transactions?date_from&date_to, non rapprochées → ?match_status=unmatched, conversions → ?fx_status=pending, anomalies → /anomalies, décompte → /decomptes/{id} ; masqué automatiquement pour le chauffeur (catch 403)
- FuelTransactionsPage : init date_from/date_to depuis les query params
- Vérifs : widget 666.33 CHF / 11 tx / 277.7 L == calcul MongoDB indépendant ; tenant B = zéros ; clic « Non rapprochées » → 10 transactions filtrées (vérifié navigateur)
- Prochaines priorités validées : 1) Notification anomalie critique (in-app immédiate + email optionnel configurable, dédup 1 notif/anomalie, destinataires configurables, pas au chauffeur sauf règle explicite, journalisée) 2) Rappel de clôture (le 5 du mois fuseau client, uniquement si décompte précédent non clôturé, 1 rappel/période, lien direct, journalisé). Backlog : taux fournisseur manuel, connecteurs fournisseurs Phase 3.


### Iteration 33 — Alertes anomalies (31/07/2026) — TESTÉ backend curl complet + testing agent iteration_21 (100 % backend 9/9 + 100 % frontend, 0 défaut)
- **Moteur** `app/fuel_anomalies.py` — 4 règles serveur, TOUS les seuils configurables par tenant (settings.anomalies, aucune valeur en dur), données manquantes → règle muette :
  - R1 volume > capacité (L/kWh, tolérance % configurable, MUETTE si capacité véhicule inconnue) — critique
  - R2 carte non active AU MOMENT de la tx (reconstitution via l'historique daté des statuts) — critique
  - R3 double plein rapproché (même carte OU véhicule, fenêtre min configurable, stations différentes signalées, tx liée référencée) — avertissement
  - R4 montant inhabituel (> multiplicateur × médiane historique du même véhicule, min. d'historique configurable, jamais de valeur fictive) — avertissement
  - Explications précises FR avec valeurs + context chiffré ; dédup stricte (index unique tenant+tx+type, jamais recréée après décision — validé created=0 au re-scan)
- **Détection auto** après import confirm / force row / saisie manuelle / attribution manuelle / match run + bouton « Analyser maintenant » (admin+manager, audit fuel.anomaly.scan)
- **Décisions** Justifier/Corriger/Rejeter (admin+manager), motif obligatoire (400), une seule décision (409), audit fuel.anomaly.justify/correct/reject
- **Capacités véhicules** : GET /vehicles-capacities + PATCH /vehicles/{id}/capacity (admin, audit fuel.vehicle.capacity_update) — saisie dans Paramètres carburant
- **Blocage clôture** : anomalie critique ouverte = bloquant de décompte (« Anomalie critique non résolue » dans line_issues + blockers.anomalies.count + lien dans le bloc de contrôle) — validé count=2 sur décompte août test
- **UI** : onglet Anomalies (admin/manager/lecture_seule ; chauffeur 403+redirect), files par statut avec compteurs, badges gravité, liens tx→TxDetailDialog, dialog décision ; Paramètres : section 4 règles (switches+seuils validés serveur 400) + capacités ; Vue d'ensemble : KPI « Anomalies ouvertes » cliquable rouge
- Seuils par défaut : tolérance 100 %, fenêtre 60 min (démo actuellement 120), multiplicateur 3.0, min. historique 5
- Régression : /app/backend/tests/test_fuel_anomalies_regression.py (9 tests, ~3 s)
- État démo : 3 ouvertes / 2 justifiées (tenant default, tx août 2026) ; carte •••• 9010 suspendue (voulu) ; Enyaq réservoir 65 L ; DEC-2026-0001 V2 « À contrôler » intact


### Iteration 32 — Taux de change BCE + Décomptes & Clôtures (31/07/2026) — TESTÉ curl complet + testing agent iteration_20 (bug PDF corrigé après)
- **Taux de change BCE** (`app/fuel_fx.py`, sans correction manuelle — reportée sur demande utilisateur) :
  - Flux public eurofxref-hist-90d (sans clé), sync APScheduler quotidienne 16h20 Europe/Zurich (lun-ven) + seed au démarrage + `POST /fx/sync` admin (audit `fuel.fx_sync`).
  - Collection GLOBALE `fuel_exchange_rates` (date+currency unique) ; formule : CHF = montant × taux(CHF)/taux(devise) ; week-end/férié → dernier taux antérieur (fx_rate_date enregistrée) ; devise sans taux → `fx_status=pending` (« Conversion en attente », badge amber liste+détail) reconvertie au prochain sync ; montant+devise d'origine JAMAIS modifiés ; tx `locked` JAMAIS recalculées ; champs tx : amount_chf, fx_rate, fx_rate_date, fx_source(ecb/none), fx_status.
  - Endpoints : GET /fx/status, GET /fx/rates?date=, POST /fx/sync (admin). UI : carte FX dans Paramètres (dernier taux, sync, pending), bloc conversion dans TxDetailDialog, ≈CHF dans les listes, overview amount_chf_total+fx_pending, filtre fx_status=pending via query param.
- **Décomptes & Clôtures** (`app/fuel_statements.py`, `app/fuel_statements_exporter.py`, `app/routes/fuel_statements.py`, pages FuelStatementsPage + FuelStatementDetailPage, onglet Décomptes admin/manager/lecture_seule) :
  - Numéro DEC-YYYY-NNNN, période mensuelle (défaut) ou personnalisée, type régulier/correctif, périmètre flotte, fuseau Europe/Zurich, date comptable fournisseur sinon date transaction (base affichée), transactions antérieures non clôturées incluses en section « reportées/tardives ».
  - Statuts : draft → to_review → validated → closed. Contrôle (check) : validated si 0 bloquant. Bloquants = non rapprochées + conversions en attente ; avertissement = contrôle recommandé. Bloc rouge UI avec compteurs/montants + liens vers transactions pré-filtrées.
  - Clôture : refuse (409 détaillé) si bloquants ; exception admin avec motif → tx bloquantes REPORTÉES (deferred_from_statement_id, jamais exclues silencieusement) ; clôture verrouille les tx (locked+statement_id), fige totaux/lignes (snapshot versionné fuel_statement_lines) ; non-chevauchement de clôturés ; PATCH match sur tx verrouillée → 409 ; match/run ignore les locked.
  - Réouverture : admin, motif + confirmation renforcée UI, interdite si période postérieure clôturée (conseil correctif), V archivée « Annulée et remplacée » (versions[]), version++, retour to_review, tx déverrouillées, écarts financiers affichés. Transactions tardives (post-clôture) listées séparément, jamais intégrées silencieusement.
  - Exports serveur PDF/Excel(9 onglets)/CSV depuis snapshot, mention « PROVISOIRE — ÉLÉMENTS À CONTRÔLER » + suffixe _PROVISOIRE si non clôturé, note version corrigée V2 + écarts, sha256 dans audit `fuel.statement.export`. Audit complet fuel.statement.create/check/close/reopen/delete/refresh.
  - RBAC : create/check/close/reopen/refresh/delete=admin ; list/get/export=admin/manager/lecture_seule ; chauffeur 403 + redirection URL directe. Isolation tenant B validée.
- **Bug corrigé post-test** : build_pdf crashait (500) sur close_exception=None → `(stmt.get("close_exception") or {})`. PDF revalidé par curl. Note test agent : « overview 666.33 vs ~758 attendu » = fausse alerte (l'estimation du brief était erronée, 666.33 est mathématiquement correct).
- État de démo : DEC-2026-0001 en V2 « À contrôler » (11 tx, 9 non rapprochées + 1 conversion en attente XXX) + 3 tx TEST_FX (EUR convertie, USD week-end, XXX pending).
- Reporté (phases suivantes) : correction manuelle du taux (fx-override taux fournisseur), Alertes anomalies, Widget carburant dashboard, connecteurs fournisseurs.

## Implemented (précédent)

### Iteration 31 — Module Carburant & Décomptes Phase 1 COMPLET (31/07/2026) — TESTÉ 26/26 backend + frontend 4 rôles (iteration_19.json)
- **Backend** (`app/routes/fuel.py` ~1010 LOC, `app/fuel_engine.py`, `app/fuel_import.py`) :
  - Cartes : CRUD admin, numéro JAMAIS stocké (HMAC `FUEL_CARD_HMAC_SECRET` + last4), doublon 409, statuts avec motif, affectations historisées véhicule/chauffeur/pool, documents.
  - Transactions : liste filtrée (dates/carte/véhicule/chauffeur/statut/source/station), saisie manuelle avec motif obligatoire + anti-doublon 409/force, détail avec breakdown.
  - `GET /my-transactions` (driver only, filtre serveur `driver_id`), `GET /transactions/{id}` 403 si tx d'autrui.
  - **`POST /transactions/{id}/report-issue`** (nouveau) : chauffeur (ses tx), admin, manager — push `issues[]` + audit `fuel.tx_issue_report`.
  - Justificatifs : upload/download tx (driver = ses tx only) + cartes, whitelist mime, 20 MB.
  - Import CSV/XLSX : upload → mapping (auto-guess + mémorisation par fournisseur) → aperçu compteurs (ok/duplicate/unknown_card/invalid/amount_mismatch) → confirm ; doublons en file de révision, force ligne avec motif.
  - Rapprochement : score explicable /100 (règles carte affectée +50, véhicule fourni +40, geo, chauffeur, carburant compatible, pénalités), `POST /match/run` (admin/manager), attribution manuelle PATCH avec motif.
  - `GET /refs` restreint à admin/manager/lecture_seule (le chauffeur ne voit JAMAIS les listes véhicules/chauffeurs/cartes).
  - Paramètres tenant : seuils score_auto/score_review, fenêtre temporelle, rayon station, mode répartition A/B, fournisseurs.
- **Frontend** (`pages/fuel/` 8 fichiers + `components/fuel/TxDetailDialog.jsx` + `ManualTxDialog.jsx`) :
  - Nav : onglet « Carburant » (admin/manager/lecture_seule) et « Mes transactions » (driver) → `/livre/carburant/*`.
  - Sous-onglets horizontaux par rôle : admin = Vue d'ensemble/Transactions/Cartes/Rapprochements/Importations/Paramètres ; manager = idem sans Importations/Paramètres ; lecture_seule = Vue d'ensemble/Transactions/Cartes ; driver = « Mes transactions » uniquement.
  - Pages : FuelOverviewPage (KPIs), FuelTransactionsPage (filtres+pagination+détail+saisie manuelle), FuelMatchingPage (4 files + run + breakdown), FuelImportsPage (wizard 3 étapes + historique + force avec motif), FuelSettingsPage, FuelMyTransactionsPage (driver), FuelCardsPage.
  - TxDetailDialog partagé : détail complet, score explicable point par point, attribution manuelle (admin/manager, motif obligatoire), justificatifs (upload/download), signalement d'erreur.
  - Guards routes React : driver redirigé vers /livre/dashboard sur /carburant/cartes|rapprochements|importations|parametres.
- **Tests** : `/app/backend/tests/test_fuel_phase1.py` 26/26 PASS (isolation driver 7, workflow driver 5, lecture_seule 7, manager 4, multi-tenant 2, dedup+force 1) + Playwright 4 rôles 100 % (iteration_19.json). Curl préalables : report-issue 200, driver→tx d'autrui 403, driver refs 403.
- Backlog mineur (console, non bloquant, PRÉ-EXISTANT hors fuel) : warning React « two children with same key » (probablement notifications/menus) + WS /api/livre/realtime échoue parfois à l'établissement en preview.
- Phases suivantes NON commencées : décomptes/clôtures, taux de change BCE (Phase 2), connecteurs fournisseurs + sync programmée (Phase 3), anomalies avancées (Phase 4).

### Iteration 30 — Test SMTP Intégré (22/07/2026) — TESTÉ curl + envoi réel (aiosmtpd local) + UI
- `GET /api/livre/settings/smtp-status` (admin) : {configured, host, port, from_addr, user_set} — jamais le mot de passe.
- `POST /api/livre/settings/smtp-test {to?}` (admin, défaut = email de l'admin) : 400 si non configuré (variables manquantes citées), envoi synchrone réel sinon, 502 avec l'erreur SMTP précise en cas d'échec. Audit `settings.smtp_test`.
- UI : Paramètres → carte n°5 « Emails (SMTP) » (`SmtpTestCard.jsx`, masquée pour manager) : badge Configuré (host:port + expéditeur) ou encadré ambre avec instructions .env VPS ; champ destinataire + bouton « Tester l'envoi » (désactivé si non configuré). Carte notifications renumérotée 6.
- Validé : status/400/403-manager via curl, envoi réel OK via serveur SMTP local (aiosmtpd = dépendance de TEST, non ajoutée aux requirements), exception propagée, screenshot UI conforme.

### Iteration 29 — Lecture Seule + Invitation Chauffeur Email + Historique des Aperçus (22/07/2026) — TESTÉ 26/26 pytest + UI Playwright
- **Rôle « lecture_seule »** : blocage GLOBAL serveur de toute écriture (POST/PUT/PATCH/DELETE → 403, whitelist logout/refresh/impersonate-end) dans `auth.py::get_current_user`. Accès : Tableau de bord, Historique, Amendes (consultation + exports), Rapports (exports PDF/Excel/CSV). Pas d'accès : Identification, Console PWA, Administration, Paramètres (guards ProtectedRoute + TABS). Rôle disponible dans les selects TeamUsersPage/AdminUsersPage, mapping labels partout. Compte test : lecture@logitrak.ch/lecture123.
- **Invitation chauffeur par email (SMTP client)** : `POST /api/livre/team/drivers/{id}/invite {email}` → token 7 jours usage unique (sha256, collection globale `invitations`) → email via SMTP .env (`SMTP_HOST/PORT/USER/PASSWORD/FROM`, `app/emailer.py`, smtplib+to_thread, 465 SSL/587 STARTTLS) avec fallback lien copiable si SMTP non configuré (email_sent=false). Endpoints publics `GET/POST /api/auth/invitation/{token}[/accept]` (mdp min 8, création compte driver lié + login auto → /driver). UI : dialog Accès PWA 2 modes (Inviter par email / Mot de passe manuel), badge « Invitation envoyée » + Renvoyer, page publique `/invitation`. Vars SMTP ajoutées à .env.example + docker-compose.yml.
- **Historique des Aperçus** : onglet Administration → Aperçus (`TeamImpersonationPage`, admin/superadmin). `GET /api/livre/team/impersonation-sessions` (superadmin : ?tenant_id=all|id + colonne/filtre Entreprise). Colonnes : admin réel, utilisateur consulté, rôle, début, fin, durée, statut (actif/terminé/expiré/refusé/en attente), source (Admin Client/Super Admin), motif. Filtres client-side (admin, utilisateur, rôle, statut, période). Lecture seule (aucune modification possible). Champ **Motif facultatif** ajouté au dialog « Se connecter comme… » (`ImpersonateDialog.jsx` partagé). Tracking : `ended_at` (fin via bouton retour), `denied_at` (échange sur token expiré), TTL session aperçu réduit à 60 min (`IMP_ACCESS_TTL_MIN`).
- Tests : `/app/backend/tests/test_iteration18_readonly_invite.py` (26/26 PASS), iteration_18.json. Bug HIGH (pending_invitation manquant — régression par écrasement du testing agent) + redirection /livre/identification : CORRIGÉS et revérifiés.
- ⚠️ Leçon : le testing agent a écrasé des edits dans team.py/App.js/TeamUsersPage.jsx — toujours auditer le code après son passage.

### Iteration 28 — « Se connecter comme… » (Impersonation) (22/07/2026) — TESTÉ 19/19 + 13/13 UI
- **Backend** (déjà en place, complété) :
  - `POST /api/livre/team/users/{id}/impersonate` (admin/superadmin) : token éphémère 60 s, usage unique, hash SHA256 en DB (`impersonation_tokens`, collection globale), guards : imbrication interdite (403), tenant suspendu (403), cible superadmin (400), soi-même (400), cross-tenant admin client (404). Audit `user.impersonate_start`.
  - `POST /api/auth/impersonate` : échange token → Bearer JWT avec claims `imp_*` (AUCUN cookie posé → session admin intacte). Audit `user.impersonate_open`. Réutilisation → 401.
  - `POST /api/auth/impersonate/end` : audit `user.impersonate_end`.
  - `get_current_user` : Bearer prioritaire sur cookie ; attache `user.impersonated_by` depuis les claims.
  - `audit.py` : toute action en aperçu logge `impersonation{actor_id, actor_email, session_id}` + note FR.
- **Frontend** (nouveau) :
  - `lib/api.js` : `IMP_TOKEN_KEY` (sessionStorage, par onglet) → header `Authorization: Bearer` prioritaire ; skip `X-Tenant-Id` en aperçu.
  - `AuthContext.jsx` : capture `?imp_token=` module-level, **échange mémoïsé (StrictMode-safe : bug double-échange du token à usage unique corrigé)**, `endImpersonation()` (end + clear + window.close + écran fallback « fermez cet onglet »), logout en aperçu = endImpersonation (ne détruit JAMAIS les cookies admin).
  - `ImpersonationBanner.jsx` (nouveau) : bandeau ambre fixe bas sur TOUTES les pages (y compris Console PWA /driver), bouton « Retour au compte administrateur », écran « Aperçu terminé », bandeau rouge si token invalide/expiré. Monté dans App.js.
  - `TeamUsersPage` : bouton œil par ligne (sauf soi-même/superadmin), tooltip « Ouvrir l'application comme X dans un nouvel onglet ». Chauffeur → `/driver`, autres → `/livre/dashboard`.
  - `TeamDriversPage` : bouton œil si compte lié + actif, sinon texte « Aucun accès PWA actif ».
  - `AdminUsersPage` (superadmin) : bouton œil cross-tenant (header `X-Tenant-Id` explicite = tenant du user), masqué si tenant suspendu.
  - `AdminAuditPage` : mention ambre « aperçu par {admin} » sous l'utilisateur effectif.
- Tests : `/app/backend/tests/test_impersonation.py` (19/19 PASS, régression réutilisable) + Playwright full flow (iteration_17.json). Aucun bug.
- Backlog mineur issu du test : endpoint `DELETE /api/admin/tenants/{id}` (ou soft-delete) inexistant (405).

### Iteration 27 — Phase B Mobile Native Expo finalisée (22/06/2026)
- Audit complet du scaffold `/app/logitrak-driver-app/` : **scanner BLE + queue offline + background task + auth JWT + WebSocket + push notifications + handlers d'actions** déjà câblés et `App.tsx` les orchestre au démarrage
- `app.json` correctement configuré : iOS `bluetooth-central` + Android `BLUETOOTH_SCAN/CONNECT/FOREGROUND_SERVICE` + plugin `react-native-ble-plx` avec `isBackgroundEnabled: true`
- `eas.json` mis à jour : URLs API pointant vers `trip-classifier-2.preview.emergentagent.com` (dev/preview) et `documents-web.logitrak.ch` (production)
- TypeScript typecheck PASS (0 erreur)
- **README.md** réécrit avec procédure complète : install Node/EAS → `eas init` → `eas build --profile preview --platform android` (~10 min) → installation APK sur Tab A9 → autorisations Bluetooth/Localisation/Notifications → test avec login chauffeur
- Documenté : limitation continue background (iOS Core Bluetooth state preservation OK ; Android foreground service réservé Phase C)
- ⚠️ Test final hors-sandbox : nécessite `eas login` + Tab A9 physique. Le code est prêt, le déploiement appartient à l'utilisateur.

### Iteration 26 — BLE Apprentissage + Refactor navixy + Doc beacons (22/06/2026)
- **Mode Apprentissage BLE** : nouveaux endpoints `GET/POST/DELETE /api/livre/ble/aliases` pour mapper un ID anonyme Chrome (ex. `unJ9KACgjvi...`) à un tag MAC réel. `_resolve_tag()` du `ble_engine` consulte désormais la collection `ble_aliases` en fallback. Bouton **"Apparier"** ajouté à chaque ligne non reconnue du Debug BLE → modal `PairAliasDialog` avec sélecteur de tag. Audit log : `alias_pair` / `alias_delete`.
- **Refactor `navixy_sync.py`** (200 lignes complexité 41 → 6 fonctions testables) : `_sync_trackers`, `_sync_employees`, `_sync_zones`, `_sync_tracks` orchestrées par `sync_navixy()` slim. Helpers `_build_trip_doc` + `_upsert_trip` + `_sync_tracks_for_vehicle`. Signature publique inchangée. Vérifié en exécution réelle : 12 trackers / 6 drivers / 28 zones / 1 new trip / 40 updated / 0 errors → résultat identique.
- **Guide configuration beacons in-app** (`BleBeaconSetupGuide.jsx`) : modal accordéon avec procédure pas-à-pas pour 4 marques (Minew BeaconSET+, Bluecharm BC011/037, Holy IoT, nRF Connect universel). Accessible depuis Gérer les tags BLE → bouton **"Comment configurer un beacon ?"**. Format MAC sans `:` recommandé.

### Iteration 25 — Module Gestion des amendes Phases 3, 5, 6 (22/06/2026)
- **Phase 5 (OCR IA)** : intégration Gemini Vision (`gemini-3.1-pro-preview`) via `emergentintegrations`. POST `/api/livre/fines/ocr-extract` accepte JPEG/PNG/WEBP/PDF (PyMuPDF rend la 1ère page), extrait 14 champs structurés en JSON, pré-remplit le formulaire avec bouton "Importer & analyser" violet en haut du dialog création. EMERGENT_LLM_KEY ajouté au backend/.env.
- **Phase 6 (Exports)** : `app/fines_exporter.py` génère PDF (ReportLab, A4 paysage, bandeau totaux), Excel (openpyxl, header bleu, freeze pane, auto-fit colonnes) et CSV (UTF-8 BOM, ;-delimited). Endpoint `GET /fines/export?fmt=csv|excel|pdf` réutilise tous les filtres de la liste. 3 boutons sur la page Amendes (PDF rouge, Excel vert, CSV gris).
- **Phase 3 (Documents + Dashboard analytics + Widget)** :
  - Upload disque sous `/app/backend/storage/fines/{fine_id}/{doc_id}_{filename}`, 6 types (pdf/photo/courrier/contestation/preuve_paiement/libre), cap 20 MB, mime whitelist
  - `POST/GET-download/DELETE /fines/{id}/documents/{doc_id}` avec audit log
  - `GET /fines/stats/extended` : KPIs (total, montants, contestées, en retard), by_status, by_type, 12 mois d'évolution, top 10 véhicules + chauffeurs + montants
  - Nouvelle page `/livre/amendes/dashboard` avec Recharts (LineChart bi-axe, BarChart, PieChart, 3 RankingTables)
  - `<FinesWidget>` injecté sur le Dashboard principal (gradient rosé/ambre, total/ouvert/à payer, cliquable)
  - Section "Documents joints" dans le FineFormDialog (mode édition uniquement) avec 6 boutons typés + liste + download/delete par ligne
- Testing : 21/21 backend pytest + frontend full flow PASS (iteration_12). Zéro bug critique.

### Iteration 24 — Module Gestion des amendes Phase 2 (19/06/2026)
- New `fines_engine.identify_driver(db, vehicle_id, infraction_at)` cross-references BLE sessions (95% conf.) + GPS trips (85%) + Assignments (60%) with multi-source bonus +5 capped at 98
- Auto-trigger on POST /api/livre/fines when driver_id is empty + dedicated POST /fines/{id}/identify-driver (persisted with audit log) + GET /fines/{id}/identify-candidates (read-only with all candidates and per-source scores)
- PATCH driver_id → auto-sets driver_validated_manually=true
- New `IdentificationPanel` component in FineFormDialog with confidence label colored by tier + sources badges + "Identifier" and "Voir le trajet" buttons
- Confidence badge in FinesPage table (90%+ emerald, 70-89% blue, <70% amber) or "M" for manual validation
- HistoryPage accepts ?vehicle=&date= URL params; vehicle filter + ±1 day date range pre-filled
- Testing: 14/14 backend pytest PASS + full frontend deep-link PASS (iteration_10 + iteration_11)

### Iteration 23 — Module Gestion des amendes Phase 1 (19/06/2026)
- New module `/livre/amendes` (Administration → Gestion des amendes), admin & manager only
- Backend route module `/app/backend/app/routes/fines.py`:
  - Mongo collection `fines` with multi-tenant isolation (tenant_id='default')
  - All schema fields ready for future phases (driver_confidence, driver_sources, documents[])
  - Sequential dossier numbering AMD-YYYY-NNNN
  - Enums: 10 statuses, 8 infraction_types, 4 priorities
  - Endpoints: GET /meta, GET / (filters+sort+pagination+aggregated totals), POST, GET/{id}, PATCH/{id} (with auto paid_at stamp on status=paid, denormalization refresh), DELETE/{id} (admin only), GET /stats/summary
  - Audit log entries on create/update/delete (scope='fines')
- Frontend:
  - `pages/FinesPage.jsx` — KPI band + filter section + sortable/paginated table with colored status badges, overdue auto-detection
  - `components/fines/FineFormDialog.jsx` — 5 sections (Infos, Véhicule, Détails, Financier, Suivi)
  - `constants/fines.js` — status/type/priority constants + tone classes
  - Sidebar new section "Administration → Gestion des amendes"
  - `ProtectedRoute` extended with `roles` prop; `/livre/amendes` restricted to admin+manager
- Testing: 26/26 backend pytest cases pass + full frontend admin flow (create/edit/delete/filters) PASS via testing_agent_v3_fork (iteration_9.json)
- Out of scope (later phases): auto-driver detection (Phase 2), GPS link, document upload (Phase 3), reminders (Phase 4), OCR (Phase 5), exports (Phase 6)

### Iteration 1 (MVP)
- JWT auth + 3 demo roles
- Mock Navixy seed (6 véhicules, 6 chauffeurs, ~600 trajets)
- Moteur de règles auto (mode véhicule → géofence → horaires)
- Dashboard 6 KPIs + pie + line 30j + table chauffeur
- Historique pro/perso, mode B masquant pour gestionnaires
- Settings : 3 modes (A/B/C), règles, modes véhicules
- Rapports PDF/Excel/CSV, rapport fiscal suisse PDF
- Affectation manuelle (audit log)
- Driver visibility filter

### Iteration 2 — Navixy live
- Client async httpx, sync trackers/employees/zones/tracks (chunks 7 jours)
- Détection auto type de zone (mots-clés sur labels)
- Endpoint admin `POST /api/livre/navixy/sync`
- UI Settings : carte "Synchronisation Navixy" avec bouton + période
- Fuel estimé 8.5L/100km (Navixy ne fournit pas fuel_l dans track/list)

### Iteration 3 — APScheduler + assignments
- **APScheduler** : sync auto périodique configurable
  (intervalle 1-1440 min, période 1-365 jours, on/off)
  - State persisté dans `db.app_state` ; `last_run`, `last_result`, `next_run`
  - Endpoints `GET/PUT /api/livre/navixy/scheduler`, `POST /api/livre/navixy/scheduler/run-now`
  - UI dans Settings : toggle, inputs, "Lancer maintenant", "Appliquer"
- **Assignments time-aware** (driver↔vehicle many-to-many)
  - Collection `assignments` : `{vehicle_id, driver_id, from_date, to_date, is_primary, source}`
  - `resolve_driver_for_trip()` → trajets attribués au bon chauffeur selon la fenêtre temporelle
  - `reassign_all_trips()` appelé automatiquement après chaque ajout/suppression
  - Endpoints `GET/POST/DELETE /api/livre/assignments`
  - UI : bouton "Chauffeurs" par véhicule ouvre Dialog avec liste + formulaire d'ajout
  - Visibilité chauffeur étendue : voit ses trajets + ceux des véhicules qui lui ont été assignés
  - Optimistic UI updates pour ajout/suppression

## Bug fixes

### Iteration 11 — Phase B spec + multi-driver conflict + WebSocket realtime
- **Doc Phase B Expo** : `/app/docs/phase_b_native_spec.md` — stack Expo SDK 51+ react-native-ble-plx, perms iOS/Android, architecture offline-first avec queue locale, plan tests, coûts (Apple 99$/yr + Play 25$), planning 6-7 semaines, critères d'acceptation
- **Multi-driver conflict detection** (`ble_engine._maybe_flag_conflict`) :
  * Déclenché à chaque ingest si 2+ drivers ont des sessions ouvertes sur le même véhicule dans la fenêtre 5min avec confidence delta ≤ 30
  * Marque TOUTES les sessions impliquées en `status='conflict'`
  * Audit log `action='conflict_detected'` avec drivers + confidences
  * **Jamais d'auto-choix** — admin doit résoudre
  * `POST /ble/sessions/{id}/resolve` (admin only) : `{winner_driver_id}` → winner gardé en `confirmed`/`pending`, autres clôturées en `closed` + audit
- **WebSocket realtime** (`app/realtime.py` + endpoint `/api/livre/realtime`) :
  * In-memory broadcaster avec rooms par tenant_id, lock asyncio
  * Auth via cookie session (`get_user_from_request` ajouté à `auth.py`)
  * Messages JSON `{type, data, ts}` : `session_opened`, `session_updated`, `conflict_detected`, `conflict_resolved`
  * Hook frontend `useRealtime.js` avec reconnexion exponentielle (500ms→30s cap), ping 25s
  * Badge "Live"/"Hors-ligne" pulsant en haut de la page Identification
  * Toast `warning` au reçu d'un `conflict_detected`, refresh silencieux sur sessions
- Frontend : Dialog "Conflit BLE — Qui conduisait réellement ?" avec radio buttons des drivers en conflit
- Tests : conflit déclenché empiriquement (Jean conf=73 + Marie conf=70 sur LOGITRAK AUDI → status=conflict) ; resolve renvoie `{winner_session_id, closed_count, final_status}` ; badge Live visible ; sessions nettoyées après test
- État final : sessions de test clôturées, mode=mixte, allow_driver_override=true

### Iteration 10 — Polylignes Navixy réelles (`tracker/track/read` + cache)
- Backend `navixy_client.read_track_points(tracker_id, from, to, track_id?, simplify=true, point_limit=300)`
  appelle `track/read` au format `'YYYY-MM-DD HH:MM:SS'`. Retourne 139 points GPS pour un trajet typique.
- Backend `GET /api/livre/trips/{trip_id}/track?refresh=` (auth all roles, mais voir invariant) :
  * **Invariant strict masqué** : si `settings.mode=='masked'` ET `trip.classification=='personal'` → **403 immédiat**, même pour admin. Les points ne sont JAMAIS lus, mis en cache, ni renvoyés.
  * Cache permanent dans `db.trip_tracks` keyed by trip_id (trips immuables une fois clos)
  * Cache négatif si erreur Navixy pour éviter de hammer
  * Fallback gracieux : ligne droite `[start_lng/lat, end_lng/lat]` si pas de tracker_id / pas de NAVIXY_HASH / erreur réseau
  * Source labelisée : `navixy | cache | fallback_no_tracker | fallback_no_points | fallback_navixy_error`
- Frontend `TripsMap.jsx` :
  * Pool de fetch concurrency=6 au mount/changement de trips
  * Garde `fetchedRef` pour ne pas refetch déjà chargés
  * Indicateur de chargement « chargement des traces GPS… (N restants) »
  * Si polyline réelle reçue → remplace la ligne droite
  * Fallback ligne droite reste affichée en attendant
- Validation manuelle :
  * 139 points GPS chargés sur un trajet réel ✅
  * 2e appel → source='cache' ✅
  * Mode masqué → admin reçoit 403 sur perso trip ✅
  * UI : polylignes suivent les routes (autoroutes, périphériques), plus de lignes droites

### Iteration 9 — Carte MapLibre dans l'historique
- Dépendances ajoutées : `maplibre-gl@5.24`, `react-map-gl@8.1` (via yarn)
- Composant `frontend/src/components/livre/TripsMap.jsx` (NOUVEAU) :
  * Tuiles **OpenStreetMap raster** (gratuit, sans clé API)
  * Polylignes droites départ→arrivée par trajet, color-coding :
    - Pro = `#2196F3`, Perso = `#F59E0B`, N/C = `#94A3B8`
  * Markers verts au départ
  * Popup HTML au clic : date, classification, plaque, adresses, distance, chauffeur
  * Auto-fit bounds, contrôles zoom/orientation MapLibre
  * Légende Pro/Privé/N/C dans le header
- **Invariant Personnel Masqué STRICT (même pour admin)** :
  * Filtre client-side : `if settingsMode==="masked" → keep only trips where classification==="professional"`
  * Bandeau jaune « Mode Personnel Masqué — N trajet(s) personnel(s) masqué(s) sur la carte »
  * data-testid `trips-map-masked-notice` pour les tests
  * Testé end-to-end : admin + masked + perso page → **0 trajet** affiché alors que 500 dans la liste
- Intégration dans `pages/HistoryPage.jsx` (sous les filtres, avant le tableau)
- Pas de modification backend (utilise les `start_lat/lng` + `end_lat/lng` déjà présents)

### Iteration 8 — MVP Phase A : Identification BLE chauffeur ↔ véhicule
- Backend `app/ble_engine.py` (NOUVEAU 350+ lignes) :
  * Modèles MongoDB : `ble_tags`, `ble_detections`, `driver_sessions`
  * `ingest_detection()` : ignore si rssi < seuil ou tag inconnu, sinon
    open/extend session, ferme les autres sessions actives du chauffeur, recompute confidence
  * `_compute_confidence()` : 0..100 = 35 % stabilité + 25 % force + 20 % durée + 20 % historique
  * `driver_set_mode()` : stamp `mobile_override` sur session + propage aux trips à venir, audit log
- Backend `rules.classify_trip` : cascade **mobile_override > vehicle.mode > geofence > schedule**
- Backend endpoints : CRUD /ble/tags, /ble/detections (driver), /ble/simulate (admin),
  /ble/sessions (read+amend), /ble/dashboard, /ble/settings, /driver/current-session,
  /driver/manual-mode
- Frontend `IdentificationPage.jsx` : 8 KPIs + filtres + tableau sessions + actions + Dialog
- Frontend `DriverConsolePage.jsx` (PWA /driver) : mobile-first sombre, 2 gros boutons PRO/PRIVÉ,
  vehicle card pulse + RSSI + confidence, banner override, simulateur BLE, polling 10s
- Frontend Settings Sheet : colonne « Tag BLE » avec inline editor
- Navigation : section « Identification BLE » gated admin
- Tests : pytest 32/32 PASS ; bug ObjectId leak corrigé
- État final : mode=mixte, allow_driver_override=true, ble_enabled=true

### Iteration 6 — Privacy Phase 2 (Tracker enforcement)
- Backend `app/privacy_enforcer.py` (NOUVEAU) :
  * `compute_expected_state(vehicle, schedule, now)` → 'tracking' | 'private'
  * `enforce_all_vehicles(db)` : itère, skip incompatibles, envoie (ou simule) via `send_raw_command`
  * `kill_switch(db)` : force tous les véhicules privés à revenir en tracking (réel par design)
  * `list_states(db)` : ne retourne que les véhicules compatibles
  * Constantes : REAFFIRM_AFTER=12h, PRIVATE_MAX_AGE=24h
  * Commands Teltonika : `setparam 11000:4` (private/deep sleep) / `setparam 11000:0` (tracking)
  * Commands Queclink : `AT+GTCFG=,privacy_mode=1` / `=0`
- Backend `app/navixy_client.py` : `send_raw_command(tracker_id, command, reliable=true)` via `tracker/raw_command/send`
- Backend `app/scheduler.py` : nouveau job `_run_privacy_enforcement` toutes les 5 min (IntervalTrigger),
  enregistré inconditionnellement au startup ; le job lui-même no-op si `settings.privacy_enforcement_enabled=False`
- Backend endpoints :
  * `GET /api/livre/privacy/enforcement-config` (admin/manager)
  * `PUT /api/livre/privacy/enforcement-config` (admin) + audit_log
  * `GET /api/livre/privacy/state` (admin/manager) — véhicules compatibles uniquement
  * `POST /api/livre/privacy/enforce-now` (admin)
  * `POST /api/livre/privacy/kill-switch` (admin)
- Frontend `PrivacyEnforcementCard.jsx` : 2 toggles (enabled / simulation), 2 boutons (Forcer / Kill switch),
  tableau d'état par véhicule, bannière rouge si mode réel actif, confirm() avant kill switch
- Safety nets : simulation=true par défaut, REAFFIRM 12h, expiry 24h, kill switch, skip incompatibles,
  RBAC strict, audit_log de toute modif config
- Tests : pytest 20/20 PASS (test_iteration6_privacy_enforcement.py), frontend e2e admin/manager/driver OK
- État final laissé sain : enabled=false, simulation=true

### Iteration 5 — Privacy Phase 1 (Tracker compatibility scan, read-only)
- Backend : `GET /api/livre/privacy/tracker-compatibility` et `/{vehicle_id}` (admin/manager only)
  → détection par modèle de traceur synchronisé Navixy ; aucune commande sortante
- Modèles répertoriés :
  * Teltonika FMC130 / FMC230 / FMC003 / FMB* → `full` (`setparam 1004:0 (sleep mode)`)
  * Queclink GV/GL/GMT → `full` (`AT+GTCFG,privacy=1`)
  * Concox JM-01 / GT06 → `partial` (SMS seulement)
  * Smartphones Navixy (iOS/Android) → `none`
  * Autres → `unknown`
- Frontend : `<PrivacyCompatCard />` injecté dans Paramètres (admin/manager only)
  4 compteurs + tableau (plaque, modèle, famille, statut, commande prévue) + Re-scanner
- Sur la flotte réelle : 10 Teltonika compatibles, 2 smartphones non supportés,
  6 véhicules mock à vérifier (modèles génériques type "Mercedes Sprinter")
- Garde-fous Phase 1 : endpoint requireRoles(admin/manager), composant masqué pour drivers,
  AUCUN appel à `tracker/raw_command/send` (vérifié par AST static check du testing agent)
- Tests : backend pytest 10/10 PASS, frontend admin+driver flows OK après fix `canEdit && <PrivacyCompatCard />`

### Iteration 4 — Filtres Groupe/Société + KPI complets + always_perso strict
- Backend : nouveaux endpoints `GET /api/livre/groups` (premier token des plaques) et
  `GET /api/livre/companies` (distinct tenant_id, label "Logitrak" pour default).
- Backend : `/dashboard`, `/trips`, `/reports/export` propagent désormais
  les filtres `group` et `company`.
- Backend KPI étendus : `kpi.unclassified_km`, `kpi.pro_fuel`, `kpi.perso_fuel`.
- Backend `rules.apply_rules_to_all()` : les véhicules en mode `always_pro` /
  `always_perso` reclassifient TOUS leurs trajets (override manuel inclus) au lieu
  des seuls trajets auto-classifiés — sémantique "100 % Personnel" stricte.
- Frontend : Dashboard expose 6 filtres (Chauffeur / Véhicule / Groupe / Société /
  Du / Au) + 8 KPI dont "Km non classifiés" et "Carburant personnel".
- Frontend : HistoryPage Pro/Perso ajoute Groupe + Société, exports PDF/Excel/CSV
  respectent désormais tous les filtres actifs (group/company inclus).
- Privacy invariant validé end-to-end : en mode "Personnel Masqué" pour gestionnaires,
  /trips renvoie {id, classification, distance_km, masked:true}, /reports/export renvoie
  une seule ligne agrégée ("—"), et l'UI HistoryPage cache list+exports.
- Tests : backend pytest 16/16 PASS (iteration 4), frontend e2e 100%.

### Bug fixes
- xlsx export merged-cell crash
- Driver-user mapping (chauffeur ↔ Jean Dupont)
- AssignmentsDialog refresh timing (optimistic insert)

## Tests
- Backend pytest : 19/19 PASS (iteration 3) + 32/32 PASS (iteration 8 BLE) + 34/34 PASS (iteration 13 régression) + 17/17 PASS (iteration 14 notifications) — **168/170 PASS** au total (2 échecs legacy pré-existants modes A/B/C dans `test_livre_de_bord.py`, non liés au refactoring)
- Frontend e2e : tous les flows validés via testing_agent_v3

## Implemented — 19/02/2026 (suite)
### Iteration 21 — Cleanup test data + GET /auth/users
- **Backend** :
  - `POST /api/livre/ble/cleanup-test-data` (admin) avec `{dry_run: bool}` — supprime les tags
    contenant `TEST` / `CONFLICTAG` / `TESTTAG` / `TESTBEACON` / `MOCK` (post-normalisation) +
    les sessions liées (`tag_id` OU `identifier` matché). Audit log + counts retournés.
  - `GET /api/auth/users` (admin) — liste tous les utilisateurs (id, email, role, full_name),
    `password_hash` exclu. Utilisé par le sélecteur user des préférences notifications.
- **Frontend** :
  - `BleTagsManager` : bouton « Nettoyer les données de test » en bas de la modal,
    avec preview dry-run avant confirmation puis suppression.
  - `NotificationsPreferencesCard` : sélecteur user cible utilise désormais `/auth/users`
    (3 utilisateurs : admin + manager + chauffeur), avec fallback vers `/livre/drivers`
    pour les déploiements plus anciens.
- **Smoke test curl** :
  - `GET /auth/users` → 3 users avec roles
  - Cleanup dry-run → 6 tags + 0 sessions à supprimer
  - Cleanup réel → 6 tags effacés
  - RBAC manager 403 sur les 2 endpoints
- **Smoke screenshot** : bouton Sparkles présent, tags réduits à 10 après cleanup
- **Tests régression** : 83/83 PASS

### Iteration 20 — Suppression définitive de session BLE
- **Backend** : nouveau `DELETE /api/livre/ble/sessions/{id}` (admin only) — hard delete
  avec log dans `audit_log` (`scope=ble`, `action=delete_session`, acteur, session_id).
- **Frontend** : 4e bouton « Corbeille » 🗑️ dans la colonne Actions de chaque ligne sessions.
  Distinction visuelle : annuler (`text-rose-500`, XCircle) vs supprimer (`text-rose-700`, Trash2).
  Confirmation modale double : « Action IRRÉVERSIBLE — la ligne disparaîtra de l'historique BLE ».
- **RBAC** : backend renvoie 403 « Accès refusé » au manager ; le toast s'affiche côté UI.
- **Smoke test curl** : admin DELETE → 200 + `deleted:true`. Manager DELETE → 403.
- **Tests régression** : 66/66 PASS (Phase A inchangée).

### Iteration 19 — Normalisation + Debug BLE
- **Backend `ble_engine.normalize_identifier()`** (nouveau) : canonicalise tout identifiant BLE
  en strippant `:` `-` ` ` `.` `/` et en upper-casing. `BC:57:29:1D:22:C5`, `bc-57-29-1d-22-c5`,
  `bc57291d22c5` → tous matchent `BC57291D22C5`. Validé : 3 formats curl → même canon.
- **`upsert_tag()`** stocke désormais `identifier` (canon) + `identifier_raw` (saisie d'origine).
- **`_resolve_tag()`** : matching canonique avec fallback legacy (scan + normalisation à la volée
  pour les tags créés avant normalisation).
- **Endpoint `GET /api/livre/ble/debug/recent-detections`** (admin only) : 100 dernières détections
  enrichies de `identifier_raw`, `identifier_canon`, `driver_name`, RSSI, platform, manufacturer_data,
  service_uuids, matched_tag_id, battery.
- **`frontend/src/components/livre/BleDebugDialog.jsx`** (nouveau, 165 LOC) :
  modal live avec polling 3 s, table scrollable (max-h 420 px, min-w 900 px, sticky headers),
  bouton « Copier » l'identifiant canonique, bouton Pause/Reprise, surlignage des détections
  non associées en jaune.
- **`BleTagsManager`** : hint sous le champ identifiant listant les 3 formats acceptés
  (`BC:57:29:1D:22:C5`, `BC-57-29-1D-22-C5`, `BC57291D22C5`, ou nom comme `KBPro_653127`).
- **`IdentificationPage`** : 2nd bouton header **Debug BLE** (orange, icône Bug) à côté de
  « Gérer les tags BLE ».
- **Smoke test live** : 3 formats → canon `BC57291D22C5` identique ✅. Endpoint debug retourne
  100 lignes enrichies ✅. Modal Debug s'ouvre, table peuplée, bouton Copier fonctionnel.
- **Tests régression** : 83/83 PASS (test_phase_a_regression + test_iteration8_ble + test_notifications).

### Iteration 18 — UI Gestion des tags BLE
- **`frontend/src/components/livre/BleTagsManager.jsx`** (nouveau, 175 LOC) :
  - Dialog modale avec formulaire d'ajout (identifiant + sélecteur véhicule) + tableau des tags existants
  - GET `/livre/ble/tags`, POST `/livre/ble/tags`, DELETE `/livre/ble/tags/{id}` (endpoints déjà en place)
  - Vide-état, loading, toasts success/error, confirmation de suppression
  - data-testids : `ble-tags-dialog`, `ble-tags-identifier`, `ble-tags-vehicle`, `ble-tags-add`, `ble-tags-table`, `ble-tags-row-<id>`, `ble-tags-delete-<id>`, `ble-tags-close`
- **`frontend/src/pages/IdentificationPage.jsx`** : bouton « Gérer les tags BLE » ajouté dans le header (admin only via la page elle-même), ouvre la modal.
- **Smoke test** : modal s'ouvre, tags existants listés (BUS35, CONFLICTAG, TEST_*), bouton suppression visible
- **Backend** : aucun changement (les endpoints existaient déjà depuis Phase A)
- **Tests régression** : 66/66 PASS (test_phase_a_regression + test_iteration8_ble)
- **Compatibilité** : aucun impact sur PWA `/driver`, app native Expo, ou flux existants

### Iteration 17 — Code Quality Cleanup post-review
- **Tests pytest** : remplacement de `assert x is True/False` → `assert x` / `assert not (x)` dans
  `test_phase_a_regression.py`, `test_notifications.py`, `test_iteration8_ble.py` (16 assertions).
  Suite Phase A : 83/83 toujours PASS.
- **Empty catch blocks → logs scopés `console.debug`** :
  - `hooks/useRealtime.js` (3 blocs : ping send, malformed payload, close on unmount, WS error, constructor)
  - `contexts/AuthContext.jsx:36` (logout endpoint failure)
  - `components/livre/TripsMap.jsx:93,222` (track fetch fallback, fitBounds skip)
  - `components/livre/ConflictInbox.jsx:40` (drivers 403 silencieux conservé, autres erreurs loguées)
  - `pages/DriverConsolePage.jsx:49` (driver-not-linked filtré, autres loguées)
  - `pages/SettingsPage.jsx:121,141` (schedule save échec, vehicle mode refus)
- **Index-as-key anti-pattern** corrigé :
  - `DashboardPage.jsx:185` → `key={d.name || \`pie-${i}\`}` (catégorie stable)
  - `ScheduleEditor.jsx:222` → `key={\`d${d.idx}-p${i}\`}` (composite stable)
  - `DayTimeline.jsx:28` → `key={\`band-${p.from}-${p.to}-${i}\`}`
- **LoginPage.jsx** : commentaire explicite ajouté précisant que les comptes DEMO affichés sont
  des seeds publics (PAS un secret). Confirmation : pas de vraie clé/credential exposé dans le code.
- **NotificationsPreferencesCard.jsx** : extraction d'`EventSection` → composant dédié
  `NotificationEventSection.jsx` (107 LOC, présentationnel pur, avec sous-composant `EventRow`).
  Card principale passée de 360 → 286 LOC (-21%), complexité réduite. Lint : 0 erreur.
- **navixy_sync.py** : 3 erreurs ruff E701 (statements one-line) corrigées.

#### Faux positifs justifiés (non corrigés)
- **React Hook deps** flaggées sur `api`, `COLORS`, `CONCURRENCY`, `STYLE_OSM`, `wsUrl` etc :
  ce sont des constantes/imports module-level stables — les ajouter aux deps causerait des
  re-renders/re-connexions inutiles. Le `[]` empty-deps de `useRealtime.useEffect` est intentionnel
  (connexion établie une fois par mount).
- **`sync_navixy()` (206 LOC, complexité 41)** : code legacy d'intégration Navixy, fonctionnel
  et couvert par les tests d'itération 3. Un refactor risquerait de casser la synchro production
  sans gain immédiat — reporté à une itération dédiée avec suite de tests étendue préalable.
- **Composants legacy >200 LOC** (`TripsMap`, `ScheduleEditor`, `AssignmentsDialog`) :
  fonctionnent, non touchés ce cycle pour éviter régression UX. Split possible plus tard.

### Iteration 16 — UI Settings web : panneau Préférences de notification
- **`frontend/src/components/livre/NotificationsPreferencesCard.jsx`** (nouveau, 360 LOC) :
  - Section 5 du Settings (cohérence visuelle avec les 4 autres sections numérotées)
  - Charge le catalogue (`GET /notifications/catalog`) + les préférences (`GET /notifications/preferences`)
  - 3 master switches Push / Email / SMS (hint « stubbé — actif à l'ajout de Resend/Twilio »)
  - Matrice événement × canal : 11 lignes (3 LOGITRAK actifs + 8 stubs business), 3 toggles + bouton Tester par ligne
  - Sauvegarde via `PUT /notifications/preferences` (toast + état loading)
  - Bouton **Tester** (admin only) via `POST /notifications/test`, retour intelligent : nb d'appareils touchés / tokens morts / aucun appareil
  - Sélecteur **utilisateur cible** (admin only) pour tester sur un autre user via le catalogue chauffeurs
  - États gérés : loading initial, erreur de chargement, saving, testing par événement
  - 11 `data-testid` (`settings-notifications-card`, `-save`, `-master-push/email/sms`, `-target-user`, `-row-<event>`, `-toggle-<event>-<channel>`, `-test-<event>`)
- **`frontend/src/pages/SettingsPage.jsx`** : 2 lignes ajoutées (import + montage de la card en bas de la page)
- **Validation manuelle** :
  - Screenshot Playwright : card affichée, 11 événements listés, 33 toggles, 11 boutons Test, sélecteur user, Enregistrer
  - PUT `/notifications/preferences` → 200 OK, persistance vérifiée après reload (aria-checked conservé)
  - POST `/notifications/test` → 200 OK, toast affiché
  - Driver peut GET+PUT ses prefs (200/200), Driver bloqué sur POST `/test` (403 attendu)
- **Compatibilité** :
  - Aucun endpoint backend modifié — uniquement consommation
  - PWA `/driver` + app native Expo intactes
  - 83/83 tests Phase A toujours PASS (aucune régression)
- **Lint** : 0 erreur ESLint sur le nouveau composant + la page modifiée.

### Iteration 15 — Refactoring `routes.py` monolithique → package `routes/`
- **Suppression** de `app/routes.py` (1162 lignes monolithique) → remplacé par le package `app/routes/`.
- **Nouveau package `app/routes/`** (11 fichiers, 1368 LOC total réparties) :
  - `__init__.py` — agrégateur, expose `livre_router` (prefix `/livre`) + `auth_router` (prefix `/auth`)
  - `_helpers.py` (170 LOC) — helpers partagés : `parse_iso`, `get_settings_doc`, `apply_privacy`,
    `filter_trips_query`, `resolve_driver_id_for_user`, `fallback_points`, `normalize_schedule`, `filename`
  - `auth.py` (12 LOC) — shim re-exportant `app.auth.router` (utilitaires gardés co-localisés)
  - `ble.py` (138 LOC) — `/ble/tags` CRUD, `/ble/detections`, `/ble/simulate`, `/ble/sessions` + `/resolve`, `/ble/dashboard`, `/ble/settings`
  - `realtime.py` (41 LOC) — WebSocket `/realtime`
  - `identification.py` (110 LOC) — `/driver/current-session`, `/driver/manual-mode`, `/driver/push-token` POST+DELETE
  - `reports.py` (131 LOC) — `/reports/export` (PDF/Excel/CSV) + `/reports/tax-swiss`
  - `settings.py` (171 LOC) — `/settings`, `/schedule/*`, `/privacy/*` (5 endpoints)
  - `dashboard.py` (116 LOC) — `/dashboard` agrégé
  - `notifications.py` (50 LOC) — `/notifications/{catalog,preferences,test}`
  - `misc.py` (389 LOC) — `/bootstrap`, `/navixy/*`, `/assignments`, `/drivers`, `/vehicles*`, `/geofences`,
    `/groups`, `/companies`, `/trips*`, `/audit-log`
- **server.py** : import mis à jour `from app.routes import auth_router, livre_router`. Aucune autre modification.
- **Résultat — zéro breaking change** :
  - Tous les chemins publics inchangés (`/api/auth/*`, `/api/livre/*`)
  - RBAC + multi-tenant intacts (mêmes dépendances `Depends(require_roles(…))`)
  - PWA `/driver` + app native Expo continuent à fonctionner sans modification
  - Tous les tests Phase A passent : **168/170** (2 échecs legacy pré-existants confirmés via `git stash`)
  - 20 endpoints clés smoke-testés à 200 OK (curl)
- **Logique métier non modifiée** : aucun changement de comportement, uniquement réorganisation.
- **Lint** : 0 erreur ruff sur le nouveau package.

### Iteration 14 — Expo Push Notifications + Notification Preferences
- **`backend/app/expo_push.py`** (nouveau, 150 LOC) : client HTTP async vers `exp.host`,
  batches de 100, parsing des tickets, nettoyage automatique des tokens morts
  (`DeviceNotRegistered`, `InvalidCredentials`, `MismatchSenderId`), aucun API key requis.
- **`backend/app/notifications_service.py`** (nouveau, 280 LOC) : dispatcher haut niveau avec
  catalogue d'événements (11 types : 3 actifs `ble.conflict`/`ble.resolved`/`kill_switch` +
  8 stubs business : `contract.renewal`, `insurance.expiring`, `vehicle.inspection_due`,
  `tracker.low_battery`, `tracker.gps_lost`, `driver.unassigned`, `vehicle.incident`,
  `logibus.delay`), résolution audience par `user_ids`/`driver_ids`/`role_filter`, lecture
  des préférences utilisateur, log dans `db.notifications_log`.
- **Templates FR** : « 🚨 Conflit d'identification chauffeur » + « ✅ Conflit résolu » +
  « ⚠️ Tracking désactivé par l'administrateur ».
- **`notification_preferences`** collection MongoDB : `{user_id, channels: {push, email, sms},
  events: {<event>: {push, email, sms}}}`. Email + SMS stubbés (logs uniquement).
- **Endpoints REST** :
  - `GET /api/livre/notifications/catalog` (auth) — liste des événements + défauts
  - `GET /api/livre/notifications/preferences` (auth) — prefs utilisateur courant
  - `PUT /api/livre/notifications/preferences` (auth) — màj prefs (filtre événements inconnus)
  - `POST /api/livre/notifications/test` (admin) — déclenche un event de test
- **Hooks moteur** :
  - `ble_engine._maybe_flag_conflict` → `dispatch('ble.conflict', …)`
  - `ble_engine.resolve_conflict` → `dispatch('ble.resolved', …)`
  - `privacy_enforcer.kill_switch` → WS broadcast `kill_switch` + `dispatch('kill_switch', …)`
- **App Expo native — Actions interactives** :
  - `src/utils/notificationActions.ts` (nouveau, 140 LOC) : enregistre la catégorie iOS
    `BLE_CONFLICT` avec 2 boutons « Je conduisais » / « Ce n'était pas moi », handler qui
    appelle `/driver/manual-mode` directement, file `pending_actions` AsyncStorage si offline
    avec replay automatique au prochain login.
  - `App.tsx` : enregistrement des catégories + handler attaché au démarrage + enregistrement
    automatique du push token Expo dès le login + replay des actions en attente.
- **Tests pytest** : `/app/backend/tests/test_notifications.py` (17 tests, 4 s, 100 % PASS) :
  catalog, préférences GET/PUT, RBAC `/test` (admin only), templates BLE/kill_switch/business,
  unit tests `expo_push` avec mocks (skip tokens invalides, cleanup tokens morts, gestion erreur HTTP),
  intégration end-to-end vérifiant que les conflits écrivent dans `notifications_log`.
- **Total Phase A** : 128/128 tests PASS sur les 5 suites (iteration 3/4/5/8/13/14).
- **Compatibilité** : aucun changement de comportement existant. Le service email/SMS est
  stubbé (logs) — quand un provider (Resend, Twilio) sera ajouté plus tard, seul
  `notifications_service.dispatch` aura besoin d'être complété, sans toucher au reste.

### Iteration 13 — Auth refresh + Push token + Régression pytest
- **`POST /api/auth/refresh`** ajouté dans `auth.py` : accepte refresh token via cookie OU body JSON,
  validation `type=refresh` + signature + expiration, rotation du refresh token, renvoie
  `{access_token, refresh_token, user}`. Erreurs HTTP 401 propres (token manquant / invalide / expiré).
- **`POST /login`** : ajoute `refresh_token` au body de réponse (utilisé par l'app native Expo).
- **`POST /api/auth/logout`** : désactive aussi les push tokens du user (best-effort).
- **`POST /api/livre/driver/push-token`** : enregistre/met à jour un push token Expo,
  idempotent par token, lié à `(user_id, driver_id, tenant_id)`, ré-activation auto si déjà présent.
- **`DELETE /api/livre/driver/push-token?token=...`** : désactivation soft (active=false).
- **Tests pytest régression Phase A** : `/app/backend/tests/test_phase_a_regression.py` (34 tests,
  10,8 s, 100 % PASS) couvrant :
  - 8 tests `TestAuthRefresh` (login, body, cookie, rotation, invalide, expiré, mauvais type, access post-refresh)
  - 7 tests `TestPushToken` (register, idempotence, invalide, RBAC, delete, 404, admin)
  - 6 tests `TestBleConflict` (simulate, flag conflict, RBAC manager/driver refus, résolution admin, 400)
  - 3 tests `TestRealtimeWebSocket` (refus non-auth, événements `conflict_detected` + `conflict_resolved`)
  - 10 tests `TestNonRegression` (auth/me, dashboard, trips, drivers, vehicles, BLE sessions+dashboard, current-session, manual-mode, logout)
- **conftest.py** créé : charge `/app/backend/.env` + `/app/frontend/.env`, ajoute backend dans `sys.path`.
- **Résumé** : 66/66 tests Phase A PASS (34 régression + 32 itération 8). 3 échecs résiduels
  sur tests legacy `test_livre_de_bord.py` et `test_iteration6` — **pré-existants** (modes A/B/C obsolètes
  vs valeur courante "mixte"), aucune régression introduite.
- **Compatibilité** : PWA web `/driver` 100 % conservée (cookie session), app native Expo
  utilise désormais access+refresh via Authorization header.

### Iteration 12 — Phase B Native scaffold (app Expo mobile chauffeur)
- App Expo SDK 51 + TypeScript scaffoldée dans `/app/logitrak-driver-app/` (24 fichiers source, 1 844 LOC)
- Stack : React Navigation 6, Zustand, axios + JWT refresh, expo-secure-store, expo-notifications,
  expo-background-fetch, expo-task-manager, `react-native-ble-plx` 3.x, `@react-native-community/netinfo`
- Écrans : `LoginScreen` (JWT email/password), `DriverScreen` (carte véhicule + boutons PRO/PRIVÉ + scanner BLE),
  `SettingsScreen` (toggle BLE, file hors-ligne, déconnexion)
- BLE : `scanner.ts` (dedupe 2 s, filtre optionnel par identifiers), `queue.ts` (AsyncStorage 24h/5 000 max,
  backoff exponentiel 1 s → 60 s), `background.ts` (BackgroundFetch 15 min flush)
- Hooks : `useRealtime` (WS backoff 1 s → 30 s), `useCurrentSessionPoll` (10 s),
  `useQueueFlusher` (30 s + NetInfo reconnect + AppState focus)
- Permissions iOS (`Info.plist` BG modes bluetooth-central) + Android (BT_SCAN/CONNECT/LOCATION/POST_NOTIFICATIONS)
- `app.json` plugins : `expo-secure-store`, `expo-notifications`, `react-native-ble-plx` (BG enabled)
- `eas.json` avec profils dev / preview / production (env `EXPO_PUBLIC_API_URL` par profil)
- Fallbacks : Bluetooth off, permission refusée, réseau coupé, token expiré, WS fermé
- Logger scopé `[scope][level]` activable via `EXPO_PUBLIC_DEBUG=1`
- README de 250 lignes : pré-requis, install, prebuild, dev client, EAS build, soumission stores
- Backend FastAPI **inchangé** (endpoints Phase A déjà compatibles)
- TypeScript `npx tsc --noEmit` : 0 erreur
- Web app `/driver` PWA conservée — coexiste avec l'app native

## P1 backlog
- Carte Leaflet/Mapbox dans l'historique (polylignes Navixy via `track/read`) — DONE (MapLibre, iteration 7)
- Carburant réel via `tracker/get_diagnostics` au lieu de l'estimation
- Webhook Navixy (push temps réel au lieu de polling APScheduler)
- Page admin pour gérer utilisateurs Logitrak
- CRUD UI pour géofences
- Multi-tenant via header `X-Tenant-ID`
- Tests pytest de régression sur Phase A BLE + Phase B endpoints (option **c** du plan)
- Refactoring `routes.py` monolithique en routers modulaires (option **b** du plan)
- Endpoint backend `POST /api/auth/refresh` (consommé par l'app native)
- Endpoint backend `POST /api/livre/driver/push-token` (Expo Push registration)

## P2 backlog
- Rapports programmés (email)
- Notifications WebSocket nouveaux trajets — DONE (Conflict Inbox, iteration 8)
- Mode sombre
- Tests Pytest/Jest formalisés
- Module "Avantage en nature" (calcul fiscal CHF)
- Phase B production : Apple Developer + Play Console, iOS BG State Restoration, Android Foreground Service BLE
- Tests Detox E2E sur l'app native

## Next tasks
- **(c)** Suite pytest de régression `/app/backend/tests/` couvrant Phase A BLE complet (cascade, RBAC, score) — testable immédiatement
- **(b)** Décomposer `routes.py` en routers modulaires (`ble.py`, `dashboard.py`, `reports.py`, `settings.py`)
- Ajouter endpoints backend `auth/refresh` + `driver/push-token` pour finaliser l'intégration mobile
- Tester l'app native sur device physique (Android/iOS) avec un vrai tag BLE

## Iframe Navixy — Fix session (20 juil. 2026)
- CSP frame-ancestors (craco.config.js): logitrak.fr/.ch, navixy.com/.io, emergentagent.com, emergent.sh
- Cookies auth passes en SameSite=None; Secure (backend/app/auth.py) — requis pour la session dans iframe cross-site Navixy

## SSO Navixy auto-login (20 juil. 2026)
- POST /api/auth/navixy-sso {session_key} : valide via API Navixy user/get_info, find-or-create user (role driver par defaut, jamais admin/manager, password_hash=None => login mot de passe refuse), pose cookies JWT SameSite=None
- Frontend AuthContext.jsx : capture ?session_key= au chargement du module (avant StrictMode), appelle le SSO, nettoie l URL
- Config Navixy requise : application utilisateur avec methode d authentification "Session key"
- MAJ 12 aout 2026 : nouveau sous-utilisateur SSO -> lecture_seule (moindre privilege, plus jamais manager auto) ; compte maitre -> admin ; existant -> role conserve ; jamais superadmin. last_sso_at mis a jour sur le tenant a chaque SSO reussi. Echecs audites en auth.sso_failed avec categorie controlee (invalid_format/navixy_rejected/navixy_timeout/tenant_unmapped/tenant_suspended/internal_error), jamais la cle, tenant_id seulement si identifie serveur, max 5 entrees/IP/10min (IP via X-Forwarded-For du proxy de confiance)

## Onglet Acces Navixy super admin (12 aout 2026) — TESTE (13 scenarios mock Navixy)
- GET /api/admin/tenants/{id}/navixy-access (superadmin) : URL unique (window.location.origin cote front), etat acces calcule (incomplete/untested/configured/error — INDEPENDANT de la synchro), etat synchro separe (never/ok/error + date), compte maitre, last_sso_at, dernier test, erreurs recentes (audit sso_failed du tenant) — AUCUN secret
- POST /api/admin/tenants/{id}/test-navixy (superadmin) : teste la cle API permanente via fetch_navixy_identity (user/get_info accepte cles API permanentes ET session keys — confirme doc Navixy), stocke last_navixy_test_at/status/error (no_key/invalid_key_or_unreachable/master_mismatch), audit tenant.navixy_test ; NE cree ni user ni session ni cookie, NE touche jamais last_sso_at
- Frontend : bouton Link2 par client dans AdminTenantsPage -> NavixyAccessDialog (URL+copier, instructions pas a pas, badges separes acces/synchro, bouton test, erreurs recentes)
- Decision utilisateur : PAS de sous-domaines par client ; PAS de super admin central dans ce workspace (cible = 4e application administrative independante pilotant les 3 apps par API) ; PAS de hub raccourcis

## Page de connexion (12 aout 2026)
- Oeil afficher/masquer sur le champ mot de passe (data-testid login-password-toggle) — teste
- Vignettes "Comptes de demo" affichees uniquement si REACT_APP_SHOW_DEMO_ACCOUNTS=true (frontend/.env preview) ; en production le build Docker n'a pas la variable (.env exclu par .dockerignore et non versionne) -> section masquee automatiquement
- Mot de passe superadmin preview change (voir test_credentials.md) ; production via SUPERADMIN_PASSWORD du .env VPS
- Pas de vignette superadmin sur la page de connexion (volontaire, securite) : connexion via le formulaire standard


## Package deploiement VPS (20 juil. 2026) — Phase 1 mono-client
- Fichiers: docker-compose.yml (projet journal_logitrak, prefixes journal_*, reseau/volume dedies), backend/Dockerfile, frontend/Dockerfile+nginx.conf, mongo-init/create-app-user.sh (user Mongo limite), nginx/journal.logitrak.ch.conf (CSP iframe+WS), .env.example, scripts/deploy|backup|restore.sh, README_DEPLOYMENT.md
- server.py: /api/health renvoie service journal-logitrak; SEED_DEMO_DATA=false desactive les donnees demo en prod
- Ports VPS proposes: 3101 (front) / 8101 (back), bind 127.0.0.1, Mongo non expose
- Phase 2 a faire: refonte multi-tenant (tenant_id partout, 1 tenant = 1 compte maitre Navixy, ecran super-admin, isolation testee A/B, audit log)

## Multi-tenant + Super-Admin + Audit (21 juil. 2026) — TESTE 14/14
- Isolation par tenant_id automatique (proxy TenantScopedDB dans db.py), collections globales: users/tenants/push_tokens/app_state
- Collection tenants {id,name,navixy_hash,navixy_master_user_id,status}; tenant "default"=Logitrak (migration auto au demarrage via tenancy.py)
- Superadmin (superadmin@logitrak.ch, env SUPERADMIN_*): API /api/admin/* (tenants CRUD+suspension, users CRUD+roles, audit global), header X-Tenant-Id pour impersonation
- Frontend: pages /admin/clients, /admin/utilisateurs, /admin/audit + TenantSwitcher (localStorage sa_tenant_id)
- SSO Navixy multi-tenant: mapping via master.id -> tenant; entreprise inconnue = 403
- Sync scheduler par tenant (chaque tenant avec sa cle Navixy); audit: auth.login/login_failed/sso, fine.export, report.export, settings.update, tenant.*, user.*
- Deploiement VPS: SUPERADMIN_EMAIL/PASSWORD ajoutes a .env.example + docker-compose.yml

## Tableau Sante Clients (21 juil. 2026)
- POST /api/admin/tenants/{id}/sync : sync manuelle par tenant (superadmin), stocke last_sync_at/result, audit tenant.sync_manual
- AdminTenantsPage: colonne Synchro Navixy (badges OK/Echec/Jamais/Cle non configuree), banniere alerte rouge si echec, bouton relance par client

## Administration client (22 juil. 2026) — TESTE 16/16
- SSO roles: compte principal Navixy -> admin auto; sous-utilisateur -> manager; existant garde son role
- routes/team.py: /api/livre/team/users (CRUD, admin only, tenant-scope) + /team/drivers (CRUD, actif/inactif, grant-access PWA cree compte driver lie, link/unlink user)
- Chauffeurs = entites separees des comptes (import Navixy sans login, champs manuels: n interne, tel, iButton/RFID/BLE, groupe)
- Frontend: onglet Administration (admin) -> sous-onglets Utilisateurs/Chauffeurs (AdministrationLayout, TeamUsersPage, TeamDriversPage)
- Securite: /auth/register refuse role superadmin; anti auto-suppression/retrogradation
- BACKLOG (spec user non implemente): role lecture_seule, perimetres gestionnaire (groupes/vehicules), file "Trajets a attribuer" avec attribution en masse, proposition de lien chauffeur/utilisateur par email

## Notification critique anomalies carburant + revue E2E finale (31 juil. 2026) — PERIMETRE FUEL FIGE
- Notification in-app immediate des anomalies critiques (tank_overflow, card_inactive) :
  - Declenchement dans fuel_anomalies._create -> dispatch('fuel.anomaly_critical') si severity=critical, jamais bloquant
  - Dedup forte : claim unique notifications_log (tenant_id,event,dedup_key) + user_notifications unique (user_id,dedup_key) — teste retry ET concurrence (asyncio.gather)
  - Destinataires configurables : settings.anomalies.notify_roles (defaut ['admin'], driver jamais par defaut, validation 400 si role hors admin/manager/driver) — UI switches dans FuelSettingsPage
  - E-mail OPTIONNEL et DESACTIVE PAR DEFAUT (catalog email:False) ; SMTP reel seulement si l'utilisateur l'active dans ses preferences
  - Lien direct : /livre/carburant/anomalies?anomaly=<id> avec surlignage ring (FuelAnomaliesPage deep-link)
  - API inbox : GET /api/livre/notifications/inbox, POST .../inbox/{id}/read (404 cross-tenant/cross-user), POST .../inbox/read-all
  - UI : NotificationsBell.jsx (cloche + badge non-lus, panneau, navigation, tout marquer lu) dans AppLayout pour tous les roles
  - ConflictInbox : icone Bell -> Users pour eviter la double cloche
- Correctifs revue E2E iteration_22 (tous retestes) :
  - SECURITE : bypass RBAC chauffeur (users.driver_id manquant -> None==None) corrige via _driver_id_of() (resolution serveur par email drivers) dans get_transaction/my-transactions/upload_doc/download_doc/report-issue + reparation data users.driver_id chauffeur@logitrak.ch -> Jean Dupont
  - fmt=xlsx accepte comme alias de excel sur export decompte
  - Warning React duplicate key null (DashboardPage table key fallback)
- Import XLSX prouve E2E : upload -> mapping auto correct -> confirm (1 importee, 1 doublon en revision sans DuplicateKeyError, 1 invalide) — artefacts nettoyes
- Donnees de demo conservees, clairement identifiees : TEST_ANOM/TEST_NOTIF (aout 2026), DEC-2026-0001 V2 a controler (juillet 2026, intact)
- Rapports : /app/test_reports/iteration_22.json + /app/test_reports/pytest/iteration22.xml (tests=30, failures=0, skipped=1)
- PRECISION 30e CONTROLE BACKEND (29/30) : test_driver_cannot_read_other_tx (backend/tests/test_iteration22_final_review.py:274) — statut xfail (echec attendu, enregistre "skipped" dans le XML), PAS un test reussi et PAS le cycle cloture/reouverture. Raison : defaut RBAC chauffeur reel constate pendant iteration_22 (users.driver_id manquant -> GET /fuel/transactions/{tx sans chauffeur} renvoyait 200 au lieu de 403). Correctif applique apres le rapport (_driver_id_of + reparation data) puis revalide par curl : 403 sur tx d'autrui/sans chauffeur, 200 uniquement sur ses propres tx (Paul Test). Impact residuel sur l'etat final : aucun.
- RESERVES DE VALIDATION DOCUMENTEES (2) :
  1. SMTP reel de l'e-mail d'anomalie non declenche dans la revue finale (e-mail volontairement desactive par defaut ; canal = infra SMTP invitations deja testee)
  2. Cycle cloture/reouverture des decomptes non rejoue dans iteration_22 (preservation de DEC-2026-0001) — couvert par les preuves anterieures iteration_20 (bug PDF corrige et reteste ensuite)
- ETAT FINAL ACCEPTE PAR L'UTILISATEUR : CONFORME AVEC DEUX RESERVES DE VALIDATION DOCUMENTEES. Perimetre Carburant & Decomptes FIGE ET ACCEPTE — archive, aucun developpement/proposition sans demande explicite.

## Seed demo Carburant pour production (31 juil. 2026) — demande utilisateur post-archivage
- Script /app/backend/seed_fuel_demo.py (copie dans l'image backend -> /app/seed_fuel_demo.py dans le conteneur)
- Seed : 3 cartes DEMO (Shell/UTA/Migrol suspendue), 15 tx CHF+EUR (mois precedent + courant), sync BCE, rapprochements, 4 anomalies (2 critiques -> notifications in-app reelles), decompte brouillon du mois precedent — tenant default, stations prefixees "DEMO", motif "Donnee de demonstration (seed)"
- Utilise les vehicules EXISTANTS (rien de supprime) ; pose tank_capacity_l=60 sur le 1er vehicule si absent (retire au clean)
- Reversible : python seed_fuel_demo.py --clean (etat fuel_demo_state dans Mongo, restauration exacte verifiee en preview : baseline 19tx/1carte/8anomalies/2decomptes/5notifs retrouvee a l'identique)
- Idempotent : refuse un second seed tant que --clean n'a pas ete lance
- VPS : docker compose -p journal_logitrak exec journal_backend python seed_fuel_demo.py [--clean]
- AVERTISSEMENT donnees completes : POST /api/livre/bootstrap sans force ne fait rien si des trajets existent ; avec force=true il EFFACE drivers/vehicles/trips/geofences (interdit en prod avec donnees Navixy reelles)
- Backlog conserve par decision utilisateur (NE PAS developper sans demande explicite) : rappel de cloture, tendance carburant 6 mois, taux fournisseur/correction manuelle FX, connecteurs fournisseurs Phase 3, e-mail anomalies reste optionnel/off
