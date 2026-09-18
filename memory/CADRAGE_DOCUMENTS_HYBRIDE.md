# Cadrage — Transfert fonctionnel « Énergie & carburant » + « Amendes » vers Documents (architecture hybride progressive)

Statut : **CADRAGE — aucun code modifié, aucun déploiement.** En attente GO utilisateur.
Date : 10/09/2026. Chantier indépendant de GitHub / SMTP / Expo Go / rapports hebdo-mensuel.

## 0. Décision de principe (rappel de la commande)
- Documents (plugin Navixy « Gestion administrative de flotte », `login.logitrak.fr/#/user-app/14328`) devient **l'interface unique** d'Énergie & carburant et d'Amendes.
- Journal (ce repo) reste **provisoirement le moteur** : trajets, km PRO/PRIVÉ, conducteurs, sessions BLE, affectations, et — en phase 1 — **aussi les moteurs carburant/amendes/énergie et leurs données** (aucune duplication, aucune migration irréversible).
- Documents appelle Journal en **backend-to-backend sécurisé**. Toutes les fonctions actuelles restent disponibles. Identification automatique du conducteur d'une amende et liens vers les trajets conservés. Coûts carburant + amendes alimentent le **coût annuel flotte** de Documents. RBAC, isolation tenant, audit, tenant 121349 conservés. Anciennes URL redirigées. Onglets Journal retirés **seulement après validation complète**.

---

## 1. Inventaire exact (Journal, état au 10/09/2026)

### 1.1 Frontend — pages et composants (React, `frontend/src`)
| Domaine | Fichiers | Routes actuelles (`/livre/...`) | Rôles |
|---|---|---|---|
| Énergie — layout | `pages/energy/EnergyLayout.jsx` | `/energie` (index → apercu) | admin/manager/lecture_seule (AML) |
| Énergie — vue d'ensemble | `pages/energy/EnergyOverviewPage.jsx` | `/energie/apercu` | AML |
| Énergie — consommations | `pages/energy/EnergyConsumptionPage.jsx` + `components/energy/TripEnergyBlock.jsx`, `EnergyBadge.jsx` | `/energie/consommations` | AML |
| Énergie — rapprochement | `pages/energy/EnergyReconciliationPage.jsx` | `/energie/rapprochement` | AML |
| Énergie — anomalies | `pages/fuel/FuelAnomaliesPage.jsx` | `/energie/anomalies` | AML |
| Approvisionnements — layout | `pages/fuel/FuelLayout.jsx` | `/energie/approvisionnements` (index) | — |
| Approvisionnements — aperçu | `pages/fuel/FuelOverviewPage.jsx` | `/energie/approvisionnements/apercu` | AML |
| Transactions | `pages/fuel/FuelTransactionsPage.jsx` + `components/fuel/TxDetailDialog.jsx`, `ManualTxDialog.jsx` | `/energie/approvisionnements/transactions` | AML |
| Cartes | `pages/fuel/FuelCardsPage.jsx` | `/energie/approvisionnements/cartes` | AML |
| Rapprochements (matching) | `pages/fuel/FuelMatchingPage.jsx` | `/energie/approvisionnements/rapprochements` | admin/manager |
| Décomptes & clôtures | `pages/fuel/FuelStatementsPage.jsx`, `FuelStatementDetailPage.jsx` | `/energie/approvisionnements/decomptes[/:id]` | AML |
| Importations | `pages/fuel/FuelImportsPage.jsx` | `/energie/approvisionnements/importations` | admin |
| Paramètres carburant | `pages/fuel/FuelSettingsPage.jsx` | `/energie/approvisionnements/parametres` | admin |
| Mes transactions (chauffeur) | `pages/fuel/FuelMyTransactionsPage.jsx` | `/energie/approvisionnements/mes-transactions` | driver (+admin/manager) |
| Amendes — liste/dossiers | `pages/FinesPage.jsx` + `components/fines/FineFormDialog.jsx` (OCR, identification, documents), `constants/fines.js` | `/amendes` | admin/manager |
| Amendes — dashboard | `pages/FinesDashboardPage.jsx` | `/amendes/dashboard` | admin/manager |
| Mes amendes (chauffeur) | `pages/DriverFinesPage.jsx` | `/mes-amendes` | driver |
| Redirections legacy | `App.js` : `LegacyFuelRedirect` (`/carburant/*` → `/energie/approvisionnements/*`), `FuelIndexRedirect`, `EnergyIndexRedirect` | | |
| Couplages hors module | `pages/DashboardPage.jsx` (`components/fuel/FuelWidget.jsx`, `components/livre/FinesWidget.jsx`, KPI carburant estimé `fuel_meta`) ; `pages/HistoryPage.jsx` (bouton ⚡ énergie par trajet, colonne « Carb. (est.) », deep-link `?vehicle=&date=` depuis une amende) ; `pages/SettingsPage.jsx` (`EnergyTenantCard`, `ReconciliationSettingsCard`, `ReconciliationAlertsCard`) ; `components/layout/AppLayout.jsx` (onglets `nav-energy`, `nav-fines`, « Mes transactions », « Mes amendes ») | | |

Total : **18 pages + 7 composants + 4 points de couplage** (Dashboard, Historique, Paramètres, navigation).

### 1.2 Backend — modules et routes (FastAPI, `backend/app`, tout sous `/api/livre`)
| Module | LOC | Rôle |
|---|---|---|
| `routes/fuel.py` (prefix `/fuel`) | 1333 | 37 endpoints : cartes (CRUD, statuts, affectations, documents), transactions (liste, mine, détail, saisie, match, run, documents, report-issue), imports (fields, upload, mapping, rows, confirm, force, liste), settings, overview, widget, anomalies (liste, scan, decide), capacités véhicules, FX (status, rates, sync), refs |
| `routes/fuel_statements.py` (prefix `/fuel/statements`) | 315 | 9 endpoints : create, list, get, refresh, check, close, reopen, delete, export (pdf/xlsx/csv) |
| `routes/energy.py` (prefix `/energy`) | 669 | 14 endpoints : status, tenant-mapping (get/put), trips (batch énergie), overview, reconciliation preview/settings/alerts config/candidates generate+list/export xlsx+pdf |
| `routes/fines.py` (prefix racine `/fines`) | 921 | 16 endpoints : ocr-extract, mine, export, meta, list, create, identify-driver, identify-candidates, get, patch, delete, stats summary/extended, documents upload/download/delete |
| `fuel_engine.py` | 315 | scoring rapprochement explicable /100, règles A/B |
| `fuel_import.py` | 249 | CSV/XLSX → mapping → aperçu → confirm |
| `fuel_fx.py` | 136 | taux BCE (flux public), conversion CHF, pending |
| `fuel_statements.py` + `fuel_statements_exporter.py` | 229 + 264 | décomptes DEC-YYYY-NNNN, contrôle, clôture/verrouillage, réouverture versionnée, exports |
| `fuel_anomalies.py` | 243 | 4 règles configurables, dédup, décisions |
| `energy_client.py` + `energy_cache.py` | 318 + 76 | client Energy v1 (real/fixture/not_connected), priorité MEASURED>ESTIMATED>REFERENCE, cache TTL 60 s / erreur 30 s |
| `fines_engine.py` | 171 | `identify_driver` : sessions BLE (95 %) > trajet GPS (85 %) > affectation (60 %), bonus multi-source |
| `fines_exporter.py` | 226 | PDF/XLSX/CSV amendes |
| `ocr_engine.py` | — | OCR Gemini (`gemini-3.1-pro-preview`, `EMERGENT_LLM_KEY`) |
| `object_storage.py` | 64 | Emergent Object Storage (justificatifs amendes) |
| Transverses utilisés | — | `auth.py` (JWT, `require_roles`, tenant), `tenant_context.py` (proxy Mongo scopé), `audit.py`, `notifications_service.py` (`fuel.anomaly_critical`), `scheduler.py` (job `fuel_fx_job` 16h20 lun-ven + seed), `reports.py` (helpers), `routes/dashboard.py` (KPI carburant estimé), `routes/reports.py` (PDF fiscal : carburant estimé) |

**76 endpoints** au total, ~5 500 LOC de code métier + routes.

### 1.3 Collections Mongo (toutes scopées `tenant_id`, sauf mention)
`fuel_transactions` (62 docs), `fuel_cards` (1), `fuel_card_assignments`, `fuel_transaction_matches`, `fuel_import_jobs`, `fuel_import_rows`, `fuel_import_mappings`, `fuel_statements` (2) + `fuel_statement_lines` (snapshots), `fuel_anomalies` (8), `fuel_exchange_rates` (**globale**, date+devise), `fines` (49, sous-doc `documents[]` → `storage_path` Object Storage), `reconciliation_alert_candidates`, `settings` (clés : `anomalies.*`, `reconciliation_threshold_*`, `reconciliation_gap_alert_pct`, alertes recon, fuel settings, `energy_tenant_id`), `audit_log` (scopes `fines`, `fuel.*`, `energy.*`), `app_state`. Lectures : `vehicles` (19, dont 13 avec `navixy_tracker_id`, `fuel_type`, `tank_capacity_l`, `battery_capacity_kwh`), `drivers` (12 avec `navixy_employee_id`), `trips`, `driver_sessions`, `assignments`, `tenants` (`navixy_master_user_id = 121349`).
Fichiers : justificatifs **carburant** (cartes + transactions) sur **disque local** `backend/storage/fuel/...` ; justificatifs **amendes** sur **Object Storage**.

### 1.4 Tests existants (à conserver comme filet de non-régression)
| Fichier | Tests |
|---|---|
| `test_fuel_phase1.py` | 26 |
| `test_fuel_anomalies_regression.py` | 9 |
| `test_fines_phase1.py` / `phase2_identify` / `phase3_5_6` | 26 / 14 / 21 |
| `test_energy_contract.py` / `real_prep` / `reconciliation` / `settings_export` / `tenant_mapping` / `alerts_pdf` / `cache` / `iteration25_energy_fixture` | 9 / 23 / 22 / 28 / 17 / 43 / 25 / 13 |
| `test_legacy_fuel_guard.py`, `test_vehicle_fuel_type.py` | 22 / 17 |
| **Total** | **315 tests** (sur 882) |

### 1.5 Hors périmètre du transfert (reste dans Journal)
- Console chauffeur / app mobile Expo : `fuel_l` estimé affiché sur le détail trajet (2 références), « Mes transactions » et « Mes amendes » (self-service chauffeur — Documents est un outil gestionnaire ; **décision D7**).
- Rapport fiscal suisse PDF et exports Livre (colonnes « carburant estimé » = legacy `fuel_l`, étiqueté ESTIMATED).
- Tout le socle : trajets, classification PRO/PRIVÉ, BLE, privacy, odomètre, rapports hebdo/mensuel.

---

## 2. Dépendances Journal ↔ Energy ↔ Documents

```
Documents (UI unique)  ──B2B──▶  Journal API service  ──▶  moteurs fuel / fines / energy (Journal)
                                       │                         │
                                       │                         └──▶ Energy API v1 (energy_client, tenant_id = settings.energy_tenant_id, fail-closed)
                                       └──▶ trajets · km PRO/PRIVÉ · drivers · driver_sessions · assignments · vehicles (Journal Mongo)
```
- **Amendes → Journal** : `identify_driver` (BLE + GPS + affectations), deep-link trajet (`vehicle_id` + `infraction_at`), véhicules/chauffeurs du tenant, Object Storage, OCR Gemini.
- **Carburant → Journal** : véhicules (capacités, `fuel_type`), chauffeurs, affectations cartes, scoring rapprochement (géo trajets), notifications anomalies, scheduler FX.
- **Énergie → Journal → Energy** : Journal reste **le seul** à parler à Energy (invariant : Documents ne doit **pas** appeler Energy directement, sinon on recrée un 2e consommateur, clé véhicule, `energy_tenant_id`…). Rapprochement achats↔consommation = jointure Journal.
- **Documents ← Journal (coûts)** : coût annuel flotte = agrégat carburant (CHF, `amount_chf`, date comptable) + amendes (montant, statut payé/à payer) → **nouvel endpoint** agrégé.
- **Clés d'identité communes** : tenant = `tenants.navixy_master_user_id` (121349) ↔ compte Navixy de Documents ; véhicule = `navixy_tracker_id` (13/19 en Journal — 6 véhicules sans traceur nécessitent une table de correspondance explicite ; **jamais** plaque/nom/modèle) ; chauffeur = `navixy_employee_id` (12) ; utilisateur = e-mail (à confirmer côté Documents).

**Inconnues côté Documents (à lever en Phase 0)** : stack (frontend/backend/DB), modèle d'auth (session Navixy ? comptes propres ?), rôles disponibles, identifiants véhicule/chauffeur utilisés, capacité de deep-link entrant (`#/user-app/14328?route=...`), hébergement (même VPS ? réseau privé ?), format actuel des « Coûts » (postes actifs, 157'370 CHF/an).

---

## 3. Architecture cible (phase hybride) et contrats API

### 3.1 Principe
- **Journal expose une façade « Service API » versionnée** : `/api/service/v1/...`, réservée aux appels backend-to-backend (Documents). Elle **réutilise les handlers existants** (pas de duplication de logique) en injectant un contexte utilisateur « pour compte de ».
- **Documents** : un **BFF** (backend-for-frontend) unique qui porte le secret de service, mappe l'utilisateur Documents → contexte Journal, et sert le frontend Documents. Le frontend Documents **n'appelle jamais Journal directement**.
- **Données** : restent dans Mongo Journal. Documents ne stocke que : mapping tenant/utilisateur/véhicule, éventuel cache court, et ses propres postes de coût dérivés (lecture seule, recalculables).

### 3.2 Contrats (familles)
| Famille | Endpoints service (Journal) | Source |
|---|---|---|
| Carburant | `/api/service/v1/fuel/**` = miroir 1:1 des 37 + 9 endpoints existants | wrappers `routes/fuel.py`, `fuel_statements.py` |
| Amendes | `/api/service/v1/fines/**` = miroir des 16 endpoints (dont `ocr-extract`, documents upload/download) | wrappers `routes/fines.py` |
| Énergie | `/api/service/v1/energy/**` = miroir des 14 endpoints | wrappers `routes/energy.py` |
| Référentiels | `GET /api/service/v1/refs/vehicles`, `/refs/drivers` (avec `navixy_tracker_id`, `navixy_employee_id`) | `vehicles`, `drivers` |
| Trajets (lecture) | `GET /api/service/v1/trips?vehicle_ref&from&to&classification` (respecte mode masqué / privé : redaction existante) ; `GET /trips/{id}` | `filter_trips_query`, `private_mode_engine.redact_private_trip` |
| Identification | `POST /api/service/v1/identify-driver {vehicle_ref, at}` → candidats + confiance + sources | `fines_engine.identify_driver` |
| Coûts (nouveau) | `GET /api/service/v1/costs/summary?year=&group_by=month|vehicle` → `{fuel: {amount_chf, tx_count, by_month[], by_vehicle[]}, fines: {amount_total, paid, open, by_month[], by_vehicle[]}, currency:"CHF", generated_at}` | agrégat `fuel_transactions` (date comptable sinon transaction, Europe/Zurich, `fx_status=pending` exclu et signalé) + `fines` |
| Santé | `GET /api/service/v1/health` → version contrat, tenant résolu, energy status | |

Règles de contrat : `null` ≠ `0` conservé partout ; litres et kWh jamais fusionnés ; champs `measurement_type`/`source` transmis tels quels ; erreurs HTTP existantes (400/403/404/409/422) propagées sans réécriture ; téléchargements binaires streamés (PDF/XLSX/CSV/justificatifs) avec `Content-Disposition` d'origine.

### 3.3 Correspondance pages actuelles → emplacement dans Documents
| Aujourd'hui (Journal) | Cible Documents | Remarque |
|---|---|---|
| Énergie › Vue d'ensemble | **Énergie & carburant › Vue d'ensemble** (nouvel onglet principal de Documents) | KPI conso (Energy via Journal) + approvisionnements + non connecté honnête |
| Énergie › Consommations | Énergie & carburant › Consommations | bloc énergie par trajet, lien trajet → Journal (deep-link) |
| Énergie › Rapprochement | Énergie & carburant › Rapprochement | statuts/seuils/exports inchangés |
| Énergie › Anomalies | Énergie & carburant › Anomalies | + lien vers **Alertes** Documents |
| Approvisionnements › Aperçu / Transactions / Cartes / Rapprochements / Décomptes / Importations / Paramètres | Énergie & carburant › Approvisionnements (sous-onglets identiques) | Paramètres carburant + seuils recon + `energy_tenant_id` regroupés dans un « Paramètres » du module |
| Amendes / Amendes › Dashboard | **Amendes** (nouvel onglet principal) : Dossiers · Tableau de bord | OCR, identification, documents, exports conservés |
| Coûts (Documents existant) | + lignes « Carburant » et « Amendes » alimentées par `/costs/summary` | contribue au « Coût annuel flotte » |
| Échéances (Documents existant) | + amendes à payer (date limite de paiement) — **optionnel**, décision D8 | |
| Dashboard Journal : FuelWidget, FinesWidget | Supprimés à la bascule (remplacés par lien « Voir dans Documents ») | |
| Historique Journal : ⚡ énergie par trajet | **Conservé** dans Journal (centré trajet) — décision D9 | |
| Paramètres Journal : EnergyTenantCard, ReconciliationSettingsCard, ReconciliationAlertsCard | Déplacés dans Paramètres du module côté Documents | |
| Mes transactions / Mes amendes (chauffeur) | **Restent dans Journal** (console/mobile) — décision D7 | |

### 3.4 Redirections (à la bascule, Phase 4)
`/livre/energie/**`, `/livre/carburant/**` (déjà legacy), `/livre/amendes/**` → page Documents correspondante (URL Navixy user-app + route interne, query préservée). Nécessite que Documents accepte un deep-link entrant (inconnue Phase 0). Tant que ce n'est pas possible : page intermédiaire Journal « Ce module a déménagé » avec bouton.

---

## 4. Authentification backend-to-backend et isolation des tenants

- **Identité du service** : jeton **JWT signé** émis par Documents (clé asymétrique RS256/ES256, clé publique connue de Journal via env `DOCUMENTS_SERVICE_JWKS`/`_PUBLIC_KEY`), durée courte (≤ 5 min), `aud=journal`, `iss=documents`. Alternative plus simple si même réseau privé : secret partagé HMAC (`DOCUMENTS_SERVICE_SECRET`) + rotation. **Décision D1.**
- **Contexte « pour compte de »** dans les claims : `tenant_ref` (= `navixy_master_user_id`, ex. 121349), `acting_user` `{email, documents_role, display}`. Journal résout : `tenant_ref → tenants.id` (**fail-closed** : inconnu ou `status ≠ active` → 403, jamais de repli sur `default`) ; `documents_role → rôle Journal` via table de mapping fixe (ex. admin→admin, gestionnaire→manager, lecture→lecture_seule ; **aucun** mapping vers `superadmin`).
- **Réutilisation de la chaîne existante** : un dépendance `get_service_user()` construit un objet utilisateur équivalent à `get_current_user()` (rôle, tenant, `auth_source="documents"`), puis `set_current_tenant()` → le **proxy Mongo scopé** et `require_roles` s'appliquent sans changement. **Le blocage global d'écriture `lecture_seule` reste actif.**
- **Audit** : chaque action loggée avec `auth_source: "documents"`, `acting_user`, `service_token_id` (jti) — même mécanisme que l'aperçu (`impersonated_by`).
- **Garde-fous** : liste blanche d'IP/CIDR optionnelle (`DOCUMENTS_ALLOWED_CIDR`), rate-limit par tenant, refus des jetons sans `tenant_ref`, journalisation des refus, aucun secret dans les logs, TLS obligatoire. Interdit : header `X-Tenant-Id` libre (réservé superadmin humain), appel direct frontend Documents → Journal.
- **Feature flag Journal** `SERVICE_API_ENABLED=false` par défaut : rollback instantané.

---

## 5. Plan de migration par phases (avec retour arrière)

| Phase | Contenu | Livrables / tests | Rollback |
|---|---|---|---|
| **0 — Découverte & décisions** | Accès lecture au repo Documents ; réponses aux inconnues §2 ; décisions D1–D10 ; contrat API figé (OpenAPI) | Ce document complété, OpenAPI v1, tableau de mapping identités | — |
| **1 — Journal : Service API** (aucun changement UI) | `get_service_user`, résolution tenant/rôle, façade `/api/service/v1/**` (wrappers), `/costs/summary`, `/identify-driver`, `/trips` lecture, flag `SERVICE_API_ENABLED` | Tests : auth (jeton invalide/expiré/aud/tenant inconnu/rôle inconnu → 401/403), isolation tenant A/B, parité réponse façade = route native (snapshot), `lecture_seule` bloqué en écriture, audit `auth_source`, `null≠0` ; régression complète Journal 0 FAIL | flag off → façade 404, zéro impact |
| **2 — Documents : BFF + pages** | Client B2B, mapping utilisateurs/véhicules, onglets « Énergie & carburant » et « Amendes » (portage des pages React si Documents est React ; sinon réécriture), intégration Coûts, Alertes (anomalies critiques, amendes échues) | Tests Documents (unitaires + e2e 4 rôles), tests de contrat consommateur contre la façade | masquer les onglets dans Documents |
| **3 — Double-run & validation** | Les deux UI actives sur les **mêmes données** ; recette utilisateur écran par écran (parité §3.3) ; perf (latence B2B, cache), sécurité (pentest léger façade), RBAC, tenant B | Checklist de parité signée ; journaux d'audit comparés | rester sur Journal |
| **4 — Bascule** | Journal : onglets/widgets/cartes Paramètres masqués derrière `ENERGY_FINES_UI_IN_JOURNAL=false`, redirections `/livre/energie/**`, `/livre/amendes/**` ; « Mes transactions/Mes amendes » chauffeur inchangés | Tests redirections + non-régression complète Journal ; smoke prod | flag → onglets réapparaissent immédiatement, aucune donnée déplacée |
| **5 — (ultérieur, hors périmètre)** | Migration éventuelle des moteurs/données vers Documents | — | — |

Aucune phase ne déplace ni ne duplique de donnée métier : le retour arrière est toujours un **flag** ou un **masquage**.

---

## 6. Risques, éléments manquants, décisions nécessaires

### Risques
1. **Stack Documents inconnue** → coût de la Phase 2 très variable (portage React quasi direct vs réécriture complète).
2. **Identité véhicule** : 6/19 véhicules Journal sans `navixy_tracker_id` → table de correspondance manuelle obligatoire, sinon coûts/amendes de ces véhicules invisibles dans Documents.
3. **Latence B2B** : écrans lourds (rapprochement Energy jusqu'à ~30 s en preview quand Energy timeoute) → cache côté Documents + timeouts explicites ; ne jamais afficher 0 en cas d'erreur.
4. **Uploads** : justificatifs carburant sur disque local Journal (pas Object Storage) → pérennité VPS à vérifier ; téléchargements streamés via BFF (taille 20 MB).
5. **OCR** : `EMERGENT_LLM_KEY` reste côté Journal (pas de 2e clé côté Documents) → coût/latence via façade.
6. **Redirection cross-app** : dépend du deep-link Navixy user-app.
7. **Double-run** : risque d'incohérence perçue si un utilisateur agit dans les deux UI (données identiques, mais caches).
8. **Dette existante** : `fuel_l` legacy estimé (Dashboard/PDF fiscal) reste dans Journal — hors périmètre mais visible.

### Éléments manquants
Accès au repo Documents ; modèle d'auth et de rôles Documents ; identifiants véhicule/chauffeur Documents ; format des « postes de coût » ; capacité deep-link ; topologie réseau (VPS/ports) ; politique de secrets (KMS/env).

### Décisions nécessaires (GO explicite requis)
- **D1** Mécanisme d'auth B2B : JWT asymétrique (recommandé) vs secret HMAC partagé.
- **D2** Clé tenant : `navixy_master_user_id` (recommandé) vs identifiant Documents dédié.
- **D3** Clé véhicule : `navixy_tracker_id` + table de correspondance pour les 6 sans traceur (recommandé) ; interdiction plaque/nom confirmée.
- **D4** Mapping rôles Documents → Journal (table fixe, pas de superadmin).
- **D5** Portage frontend : réutiliser les composants React Journal (si compatible) vs réécriture native Documents.
- **D6** Coûts : lecture temps réel via `/costs/summary` (recommandé) vs snapshot mensuel stocké côté Documents.
- **D7** Self-service chauffeur (« Mes transactions », « Mes amendes ») : reste dans Journal/mobile (recommandé).
- **D8** Amendes dans « Échéances » Documents (date limite de paiement) : oui/non.
- **D9** Bloc énergie par trajet dans l'Historique Journal : conservé (recommandé) ou retiré.
- **D10** Stratégie de redirection si deep-link impossible : page intermédiaire Journal.

---

## 7. Stratégie de tests

- **Fonctionnels (parité)** : pour chaque page §3.3, scénario identique joué sur Journal et Documents → mêmes chiffres (KPI, totaux, statuts), mêmes fichiers (hash PDF/XLSX/CSV), mêmes erreurs (400/403/409). Scénarios clés : import CSV → doublons → confirm ; rapprochement → run → attribution manuelle ; décompte → contrôle → clôture refusée (bloquants) → exception admin → réouverture V2 ; anomalie critique → décision ; amende → OCR → identification auto (BLE/GPS/affectation) → documents → export ; conversion FX EUR/USD/pending.
- **Sécurité** : jeton absent/expiré/mauvais `aud`/signature invalide → 401 ; tenant inconnu/suspendu → 403 ; rôle non mappé → 403 ; `lecture_seule` → toute écriture 403 ; IDOR cross-tenant (ids tenant B via tenant A) → 404 ; header `X-Tenant-Id` ignoré en mode service ; aucun secret dans logs/audit ; rate-limit ; upload MIME/taille.
- **Non-régression Journal** : les **315 tests** existants inchangés + nouveaux tests façade ; **régression complète unique et séquentielle** à la fin de chaque phase Journal (règle en vigueur), avec la barrière sinkhole Navixy et les contrôles post-run habituels (real+success = 0, private = 0, URL restaurée, assignments intacts).
- **Contrat** : tests consommateur (Documents) contre OpenAPI v1 ; test « `null` jamais `0` » sur toutes les métriques ; PHEV électrique/carburant séparés.
- **Performance** : p95 par écran via BFF ; comportement Energy indisponible (« Non disponible », jamais 0).
- **Recette utilisateur** : checklist de parité signée avant Phase 4 ; tenant B (isolation) inclus.

---

## 8. Estimation réaliste (jours-personne, hors attente de décisions)

| Phase | Journal | Documents | Total | Conditions |
|---|---|---|---|---|
| 0 Découverte & décisions | 0,5 | 1–2 | **1,5–2,5 j** | accès repo Documents |
| 1 Service API Journal | 5–7 | — | **5–7 j** | inclut tests + régression complète |
| 2 BFF + pages Documents | 0,5 (support) | **8–12 j** si portage React / **20–30 j** si réécriture | **9–31 j** | D5 |
| 3 Double-run & validation | 1 | 2 | **3 j** + 2–4 semaines calendaires de double-run | recette utilisateur |
| 4 Bascule + redirections | 1–2 | 0,5 | **1,5–2,5 j** | D10 |
| **Total** | | | **≈ 20 j (portage) à ≈ 45 j (réécriture)** | |

Marges : +20 % si auth Documents non standard ; +2 j si table de correspondance véhicules à construire manuellement ; Phase 5 (migration moteurs) non estimée.

---

## 9. Ce qui n'est PAS dans ce cadrage
GitHub / Save to GitHub, SMTP prod, déploiement VPS, Expo Go / EAS, rapports hebdomadaire et mensuel — chantiers séparés.
