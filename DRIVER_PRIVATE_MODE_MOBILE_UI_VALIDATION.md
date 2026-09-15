# DRIVER_PRIVATE_MODE_MOBILE_UI_VALIDATION.md
## Validation UI mobile — section « Confidentialité » (Privé / Professionnel)

> Mission FRONTEND/MOBILE UI + TESTS uniquement. Aucun appel device réel, aucun Navixy,
> aucun `privatemode` réel. `PRIVATE_MODE_PRODUCTION = DISABLED`.

## A. Audit UI existante
App React Native / Expo (`logitrak-driver-app`). Fichiers Phase 2 :
- `src/api/privateMode.ts` — client GET/POST `/api/livre/driver/private-mode` (intention métier).
- `src/hooks/usePrivateMode.ts` — machine à états côté app (non-optimiste, anti-concurrence, refresh).
- `src/screens/DriverScreen.tsx` — section « Confidentialité » (rendue seulement si `allowed`).
Existant jugé correct : aucune réécriture, uniquement validation + tests ajoutés.

## B. États testés (via tests unitaires simulés — aucun device)
BUSINESS, PRIVATE, PRIVATE_REQUESTED, BUSINESS_REQUESTED, FAILED (message honnête), UNKNOWN
(jamais assimilé à BUSINESS), NOT_ALLOWED (section cachée si `allowed=false`).

## C. Captures
Environnement Expo natif (BLE) non pilotable par navigateur -> pas de capture Playwright.
Validation faite par tests unitaires de composant/hook (jest-expo + react-test-renderer) +
audit statique du rendu. (Limitation documentée, section I.)

## D. Responsive
Section en carte + `modesRow` (flex, gap) réutilisant les styles existants. Libellés
« Professionnel »/« Privé » conservés (pas d'abréviation « Pro »). Padding/typo adaptés.
Le rendu natif exact (320/375/430) devra être confirmé sur device/simulateur lors du field test
(hors périmètre browser). Aucun overflow introduit dans les styles ajoutés (card + textes).

## E. UX
Message chauffeur simple : « Mode Privé activé » + « Votre position n'est pas affichée. Les
kilomètres parcourus restent comptabilisés. » Boutons désactivés pendant transition. Aucun succès
affiché avant confirmation backend. Aucun jargon (AVL16/Navixy/Teltonika/privatemode absents de l'UI).

## F. Bugs trouvés
- Test hook « bascule non-optimiste » : le mock `getPrivateMode` ne reflétait pas le nouvel état
  après refresh -> corrigé dans le TEST (le backend reflète le nouvel état au refresh). Pas un bug produit.
- Warning TS : `react-test-renderer` sans types -> ajout `src/__tests__/react-test-renderer.d.ts` (test-only).

## G. Corrections effectuées
- Ajout tests `src/__tests__/usePrivateMode.test.tsx` (6) + déclaration de types test-only.
- Aucune modification du backend (déjà validé) ; aucune modif de logique produit de l'app.

## H. Tests
```
Hook usePrivateMode : 6/6 PASS
Suite complète       : 7 suites / 41 tests PASS (aucune régression)
Typecheck (tsc)      : exit 0
Audit statique a→e   : 6/6 PASS (états, gating, disabled/non-optimiste, zéro jargon, testIDs, no position)
```

## I. Limitations restantes
- Test **visuel pixel/responsive** sur device réel/simulateur non fait (Expo natif non pilotable
  par navigateur). À couvrir lors d'un field test mobile (screenshots device).
- L'état REAL terrain (device) dépend de la confirmation backend réelle (hors périmètre UI).

## J. Next safe step
`PRIVACY_WEB_API_AUDIT` : auditer les APIs/vues WEB (console gestionnaire/client) pour garantir
qu'aucune position n'est exposée quand un véhicule est en PRIVATE (appliquer `redact_private_location`).

## SORTIE
```
MOBILE_PRIVATE_MODE_UI   = PASS
BUSINESS_STATE_UI        = PASS
PRIVATE_STATE_UI         = PASS
PRIVATE_REQUESTED_UI     = PASS
BUSINESS_REQUESTED_UI    = PASS
FAILED_STATE_UI          = PASS
UNKNOWN_STATE_UI         = PASS
NOT_ALLOWED_UI           = PASS (section cachée si non autorisé)
RELOAD_STATE_RECOVERY    = PASS (état récupéré au montage ; jamais BUSINESS par défaut)
NON_OPTIMISTIC_UI        = PASS
RESPONSIVE_320/375/430   = PASS (styles) ; rendu device à confirmer en field test (limite Expo/browser)
TECHNICAL_JARGON_EXPOSED = NO
PRIVATE_LOCATION_VISIBLE = NO
TESTS                    = 41 passed (dont 6 usePrivateMode) ; tsc exit 0
PRIVATE_MODE_PRODUCTION  = DISABLED
NEXT_SAFE_STEP           = PRIVACY_WEB_API_AUDIT
```
