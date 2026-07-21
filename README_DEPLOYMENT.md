# Journal de bord Logitrak — Guide de déploiement VPS

Application **totalement isolée** des autres applications du VPS :
conteneurs, réseau, volumes, base de données, variables d'environnement,
logs et sauvegardes dédiés, tous préfixés `journal_`.

- **URL publique** : https://journal.logitrak.ch
- **Projet Docker Compose** : `journal_logitrak`
- **Dossier sur le VPS** : `/opt/apps/journal-logitrak`
- **Ports hôte (127.0.0.1 uniquement, jamais publics)** : frontend `3101`, backend `8101`
- **Base de données** : MongoDB 7 dans le conteneur `journal_database` — **non exposée** sur Internet, utilisateur limité `journal_logitrak_user` (readWrite sur la base `journal_logitrak` seulement)

---

## 0. Analyse préalable du VPS (OBLIGATOIRE avant toute action)

```bash
# Conteneurs et ports Docker existants
sudo docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}"

# Ports déjà écoutés sur l'hôte
sudo ss -tlnp | grep LISTEN

# Sites Nginx existants
ls -la /etc/nginx/sites-enabled/

# Réseaux et volumes Docker existants (vérifier qu'aucun ne s'appelle journal_*)
sudo docker network ls
sudo docker volume ls
```

✅ Vérifier que les ports **3101** et **8101** sont libres. Sinon, changer
`FRONTEND_PORT` / `BACKEND_PORT` dans le `.env` (aucun autre fichier à modifier).

✅ Vérifier que le DNS `journal.logitrak.ch` pointe vers l'IP du VPS :
```bash
dig +short journal.logitrak.ch
```

⛔ **Commandes interdites** (affectent les autres applications) :
`docker system prune`, `docker volume prune`, `docker network prune`,
`docker stop $(docker ps -q)`, `docker rm $(docker ps -aq)`,
`docker compose down` hors du dossier `/opt/apps/journal-logitrak`.

---

## 1. Installation initiale

```bash
# 1.1 Cloner le dépôt dans le dossier dédié
sudo mkdir -p /opt/apps
sudo git clone https://github.com/VOTRE-USERNAME/Journal-de-bord.git /opt/apps/journal-logitrak
cd /opt/apps/journal-logitrak

# 1.2 Créer les dossiers de données/logs/sauvegardes
mkdir -p data/storage backups logs

# 1.3 Créer le fichier d'environnement à partir du modèle
cp env.example .env
chmod 600 .env
nano .env
```

Dans `.env`, renseigner **obligatoirement** :

| Variable | Valeur |
|---|---|
| `MONGO_ROOT_PASSWORD` | mot de passe fort (généré : `openssl rand -hex 24`) |
| `MONGO_APP_PASSWORD` | mot de passe fort différent |
| `JWT_SECRET` | `openssl rand -hex 32` — **ne jamais réutiliser celui d'une autre app** |
| `ADMIN_PASSWORD` / `MANAGER_PASSWORD` / `DRIVER_PASSWORD` | mots de passe des comptes initiaux |
| `NAVIXY_HASH` | clé API Navixy du compte maître |
| `EMERGENT_LLM_KEY` | clé pour l'OCR Gemini (scan des amendes) |
| `SEED_DEMO_DATA` | `false` en production (pas de données de démonstration) |

```bash
# 1.4 Build + démarrage (ciblé sur le projet journal_logitrak uniquement)
docker compose -p journal_logitrak config -q     # valide la config
docker compose -p journal_logitrak build
docker compose -p journal_logitrak up -d

# 1.5 Vérifications
docker compose -p journal_logitrak ps            # 3 conteneurs "healthy"
docker compose -p journal_logitrak logs --tail=100
curl -s http://127.0.0.1:8101/api/health         # {"status":"ok","service":"journal-logitrak"}
curl -sI http://127.0.0.1:3101/ | head -1        # HTTP/1.1 200 OK

# 1.6 Vérifier que les AUTRES applications tournent toujours
sudo docker ps --format "table {{.Names}}\t{{.Status}}"
```

---

## 2. Reverse proxy Nginx (uniquement journal.logitrak.ch)

```bash
# 2.1 Copier la config dédiée (ne modifie aucun autre site)
sudo cp nginx/journal.logitrak.ch.conf /etc/nginx/sites-available/journal.logitrak.ch
sudo ln -s /etc/nginx/sites-available/journal.logitrak.ch /etc/nginx/sites-enabled/

# 2.2 TOUJOURS tester avant de recharger
sudo nginx -t

# 2.3 Recharger uniquement si le test est OK
sudo systemctl reload nginx
```

La config inclut :
- proxy `/api/` → backend `127.0.0.1:8101` (avec support WebSocket pour `/api/livre/realtime`)
- proxy `/` → frontend `127.0.0.1:3101`
- header `Content-Security-Policy: frame-ancestors` autorisant l'iframe Navixy
  (`*.logitrak.fr`, `*.logitrak.ch`, `*.navixy.com`)
- `client_max_body_size 25m` (upload de documents d'amendes)
- logs dédiés : `/var/log/nginx/journal.logitrak.ch.*.log`

## 3. HTTPS (certificat pour journal.logitrak.ch uniquement)

```bash
# Vérifier le DNS d'abord (doit renvoyer l'IP du VPS)
dig +short journal.logitrak.ch

# Certificat + redirection HTTP→HTTPS automatique (ne touche pas les autres domaines)
sudo certbot --nginx -d journal.logitrak.ch

sudo nginx -t && sudo systemctl reload nginx
```

Test final : ouvrir https://journal.logitrak.ch → page de connexion du Journal de bord.

---

## 4. Connexion automatique depuis Navixy (SSO)

1. Dans Navixy (panneau d'administration), éditer l'application utilisateur « Journal de bord »
2. **URL** : `https://journal.logitrak.ch`
3. **Méthode d'authentification** : `Session key` → Navixy ajoute `?session_key=...` à l'iframe
4. **Open in** : `Embedded`

Fonctionnement : le backend valide la `session_key` auprès de l'API Navixy
(`user/get_info`), retrouve ou crée l'utilisateur (rôle limité `driver` par
défaut, jamais admin), pose des cookies `HttpOnly; Secure; SameSite=None`
(compatibles iframe). La clé Navixy n'est **jamais** stockée ni journalisée.

---

## 5. Mises à jour (déploiement courant)

```bash
# Depuis Emergent : "Save to GitHub" (dépôt Journal-de-bord), puis sur le VPS :
/opt/apps/journal-logitrak/scripts/deploy.sh
```

Le script fait : `git pull` → `config -q` → `build` → `up -d` → `ps` → health
check, **toujours ciblé** sur le projet `journal_logitrak`.

---

## 6. Sauvegardes

```bash
# Manuelle
/opt/apps/journal-logitrak/scripts/backup.sh

# Automatique quotidienne à 02h30 (crontab -e sous root ou l'utilisateur docker)
30 2 * * * /opt/apps/journal-logitrak/scripts/backup.sh >> /opt/apps/journal-logitrak/logs/backup.log 2>&1
```

Contenu de chaque sauvegarde dans `/opt/apps/journal-logitrak/backups/` :
- `journal_db_<date>.archive.gz` — dump MongoDB (base `journal_logitrak` uniquement)
- `journal_storage_<date>.tar.gz` — fichiers uploadés (documents d'amendes)
- `journal_env_<date>.env` — configuration (permissions 600)

Rotation automatique : 14 jours. **Recommandé** : copier régulièrement le
dossier `backups/` hors du VPS (rsync/scp vers un autre serveur ou stockage).

### Restauration

```bash
/opt/apps/journal-logitrak/scripts/restore.sh \
  backups/journal_db_YYYYMMDD_HHMMSS.archive.gz \
  backups/journal_storage_YYYYMMDD_HHMMSS.tar.gz
```

---

## 7. Procédure de rollback (retour arrière)

```bash
cd /opt/apps/journal-logitrak

# 1. Identifier le commit précédent
git log --oneline -5

# 2. Revenir dessus
git checkout <hash_du_commit_precedent>

# 3. Rebuild + redémarrage ciblés (les autres apps ne sont pas touchées)
docker compose -p journal_logitrak build
docker compose -p journal_logitrak up -d

# 4. Si la base doit aussi être restaurée
./scripts/restore.sh backups/journal_db_<derniere_sauvegarde_saine>.archive.gz

# 5. Conserver les logs de l'incident
docker compose -p journal_logitrak logs --tail=500 > logs/incident_$(date +%Y%m%d_%H%M).log

# Retour à la dernière version : git checkout main && ./scripts/deploy.sh
```

---

## 8. Exploitation courante

```bash
# État / logs (toujours ciblés)
docker compose -p journal_logitrak ps
docker compose -p journal_logitrak logs -f journal_backend
docker compose -p journal_logitrak logs -f journal_frontend

# Redémarrer un seul service
docker compose -p journal_logitrak restart journal_backend

# Arrêter UNIQUEMENT le Journal de bord (jamais docker compose down ailleurs)
cd /opt/apps/journal-logitrak && docker compose -p journal_logitrak down
```

Logs applicatifs : `docker logs journal_backend` (stdout, rotation gérée par
Docker). Ajouter dans `/etc/docker/daemon.json` si pas déjà fait (global,
vérifier l'impact avant) ou par service via `logging:` dans le compose.
Logs Nginx dédiés : `/var/log/nginx/journal.logitrak.ch.*.log` (rotation
logrotate standard de Nginx).

---

## 9. Checklist avant mise en production

- [ ] `journal.logitrak.ch` pointe vers le VPS (`dig +short`)
- [ ] Certificat HTTPS valide (`curl -sI https://journal.logitrak.ch | head -1`)
- [ ] Ports 3101/8101 sans conflit (`sudo ss -tlnp | grep -E '3101|8101'`)
- [ ] 3 conteneurs `journal_*` en état `healthy` (`docker compose -p journal_logitrak ps`)
- [ ] Réseau `journal_network` et volume `journal_db_data` dédiés (`docker network ls`, `docker volume ls`)
- [ ] Base `journal_logitrak` indépendante, non exposée (`sudo ss -tlnp | grep 27017` → rien de public)
- [ ] `.env` en permissions 600, secrets uniques (pas réutilisés d'une autre app)
- [ ] Aucun fichier d'une autre application modifié
- [ ] Aucun autre conteneur redémarré (`sudo docker ps` : uptime des autres apps inchangé)
- [ ] Connexion classique fonctionne (login admin)
- [ ] Connexion auto Navixy fonctionne (iframe avec Session key)
- [ ] `scripts/backup.sh` exécuté avec succès + cron en place
- [ ] Restauration testée sur une sauvegarde
- [ ] Les autres applications du VPS répondent toujours

---

## 10. Limites actuelles et Phase 2 (multi-tenant)

⚠️ **Version actuelle : mono-client.** Un seul compte maître Navixy
(`NAVIXY_HASH`), collections partagées, pas de `tenant_id`.

La Phase 2 (prévue) apportera :
- `tenant_id` sur toutes les données métier (véhicules, trajets, amendes, utilisateurs…)
- rattachement du tenant depuis la session authentifiée (jamais depuis le frontend)
- écran super-admin Logitrak : gestion des clients + clé API Navixy par client
- isolation stricte testée côté backend (Client A ne voit jamais Client B)
- journal d'audit des actions sensibles

Le déploiement actuel est conçu pour accueillir cette évolution sans
changement d'infrastructure (même base, mêmes conteneurs).
