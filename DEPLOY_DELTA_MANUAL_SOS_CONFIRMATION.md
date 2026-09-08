# DEPLOY DELTA — Lot « Mode manuel + confirmation réelle + Km + SOS »

> Re-déploiement du **nouveau code** par-dessus le GO 2 (commit prod actuel `dbf7e6f`).
> Objectif : que l'app Orhan passe à l'écran MANUEL et que le bouton PRIVÉ déclenche le
> VRAI Mode Privé device (via télémétrie), au lieu de l'ancien `manual-mode` (classification).
>
> ⚠️ NE RIEN EXÉCUTER SANS GO. Exécution par l'opérateur sur le VPS, phase par phase.

## DELTA vs prod actuelle (dbf7e6f -> HEAD)
```text
BACKEND (3 fichiers ; aucun nouveau module ; aucune migration ; aucune nouvelle var OBLIGATOIRE)
- app/private_mode_engine.py   : PENDING_CONFIRMATION + télémétrie (fin du faux FAILED)
- app/routes/identification.py : endpoints /driver/my-vehicles, /driver/km-summary, /driver/sos
                                 + GET /driver/private-mode enrichi (pending/confirmation_source)
- app/notifications_service.py : event "sos.triggered" (réutilise le pipeline existant)

EXPO (app chauffeur)
- écran manuel (sans BLE) + Km Pro/Privé + bouton SOS + gestion PENDING
- nouvelle var d'AFFICHAGE (optionnelle) : EXPO_PUBLIC_VEHICLE_SELECTION_MODE=manual (défaut manual)

ENV BACKEND : INCHANGÉ (les vars pilote sont déjà en place depuis GO4)
- PRIVATE_MODE_ENABLED=true (pilote actif) · PILOT_TENANTS=default · PILOT_TRACKERS=3657864
- PRIVATE_MODE_DEVICE_WRITE=0 (fermé) · APP_ENV=production · ALLOW_GLOBAL_NAVIXY_FALLBACK=false
- INTEGRATION_ENCRYPTION_KEY renseignée
- (optionnel) PRIVATE_MODE_PENDING_TIMEOUT_S=300 (défaut si absent)
```

## STOP / garde-fous
```text
- Pas de migration DB (aucune). L'état FAILED résiduel du GO5 sera nettoyé (voir PHASE 4).
- DEVICE_WRITE reste 0 après déploiement -> le bouton PRIVÉ enverra en SIMULATION tant que
  DEVICE_WRITE=1 n'est pas ré-ouvert (comme GO5) pour un envoi device réel.
- Fail-closed inchangé.
```

## PHASES (opérateur, sur GO)

### PHASE 1 — BACKUP
```bash
cd /opt/apps/journal-logitrak
git rev-parse HEAD | tee backups/rollback_commit_$(date +%F_%H%M).txt   # = dbf7e6f (rollback code)
cp .env backups/journal.env.pre-delta_$(date +%F_%H%M) && chmod 600 backups/journal.env.pre-delta_*
set -a; . ./.env; set +a
docker exec journal_database mongodump --username "$MONGO_APP_USER" --password "$MONGO_APP_PASSWORD" \
  --authenticationDatabase "$DB_NAME" --db "$DB_NAME" --archive \
  > backups/mongo_${DB_NAME}_$(date +%F_%H%M).archive
ls -lh backups/mongo_*.archive | tail -1
```

### PHASE 2 — CODE (après « Save to Github » de la branche)
```bash
cd /opt/apps/journal-logitrak
git fetch origin --prune
git checkout feat/private-mode-pilot
git pull --ff-only origin feat/private-mode-pilot
git rev-parse HEAD          # doit être le nouveau commit du lot
git status --short          # attendu : vide (hors backups/ untracked)
```

### PHASE 3 — BUILD + RESTART BACKEND
```bash
cd /opt/apps/journal-logitrak
docker compose build journal_backend
docker compose up -d journal_backend
docker compose ps journal_backend       # Up (healthy)
docker exec -w /app journal_backend python3 -c "import app.private_mode_engine, app.routes.identification, app.notifications_service; print('IMPORTS OK')"
docker logs --tail 40 journal_backend    # pas de traceback
```

### PHASE 4 — NETTOYAGE état FAILED résiduel (cohérence)
```bash
docker exec -w /app journal_backend python3 -c "
import asyncio, datetime
from app.db import init_db, get_db
async def m():
    init_db(); db=get_db()
    await db.private_mode_state.update_one(
        {'vehicle_id':'c9b049c5-7444-4cf0-a697-978e4a090405'},
        {'\$set':{'state':'BUSINESS','confirmation_source':'MANUAL_RESET',
                  'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}})
    st=await db.private_mode_state.find_one({'vehicle_id':'c9b049c5-7444-4cf0-a697-978e4a090405'},{'_id':0,'state':1})
    print('state ->', st.get('state'))
asyncio.run(m())
"
```

### PHASE 5 — REBUILD FRONTEND EXPO (écran manuel)
```bash
cd /opt/apps/journal-logitrak
# s'assurer que le mode manuel est actif pour le build Expo (défaut = manual de toute façon)
grep -q '^EXPO_PUBLIC_VEHICLE_SELECTION_MODE=' .env || echo 'EXPO_PUBLIC_VEHICLE_SELECTION_MODE=manual' >> .env
docker compose build journal_frontend
docker compose up -d journal_frontend
docker compose ps journal_frontend
```
> Note : selon la conf, le service `journal_frontend` peut servir l'app web ET/OU l'app chauffeur.
> Vérifier que l'app chauffeur (journal.logitrak.ch/driver) recharge bien le nouvel écran.

### PHASE 6 — VÉRIF UI + fail-closed
```bash
# fail-closed backend inchangé
docker exec -w /app journal_backend python3 -c "
import app.private_mode_gate as g, app.private_mode_engine as pm
print('feature:', g.feature_enabled(), '| device_write:', pm.device_write_enabled(), '| simulate:', pm.simulate_confirm_enabled())
"
# nouveaux endpoints répondent (via un token driver, ou vérif 401 sans token)
curl -s -o /dev/null -w "km-summary sans token: HTTP %{http_code}\n" http://127.0.0.1:8101/api/livre/driver/km-summary
```
Dans l'app d'Orhan (journal.logitrak.ch/driver) : l'écran doit devenir ÉPURÉ
(Véhicule actuel + Changer + PRO/PRIVÉ + Km Pro/Privé + SOS), SANS widgets BLE.

### PHASE 7 — (optionnel, plus tard) ENVOI DEVICE RÉEL
Le bouton PRIVÉ enverra en SIMULATION tant que DEVICE_WRITE=0. Pour un envoi réel (comme GO5),
ré-ouvrir DEVICE_WRITE=1 le temps de l'usage/test, véhicule en ligne, puis refermer à 0.

## ROLLBACK
```text
Code   : git checkout dbf7e6f && docker compose build journal_backend journal_frontend && up -d
Feature: PRIVATE_MODE_ENABLED reste géré par flag ; kill switch dispo si besoin
DB     : restaurer backups/mongo_*.archive uniquement si écriture problématique (aucune migration ici)
```

## MATRICE GO/NO-GO
```text
CODE DELTA PRÊT          : GO (backend 3 fichiers + Expo ; 73 backend + 58 Expo tests verts ;
                           testing_agent : confirmation 16/16, my-vehicles/km 16/16, SOS 7/7)
BACKUP                   : à faire PHASE 1
BUILD/HEALTH             : à valider PHASE 3
FAIL-CLOSED PRÉSERVÉ     : oui (aucun changement de garde-fou)
ENVOI DEVICE RÉEL        : NON (DEVICE_WRITE reste 0 ; ré-ouverture séparée)
```
