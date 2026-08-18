#!/usr/bin/env bash
# Déploiement ciblé du Journal de bord — ne touche à AUCUNE autre application.
set -euo pipefail

APP_DIR="/opt/apps/journal-logitrak"
cd "$APP_DIR"

echo "==> Récupération du code"
git pull

echo "==> Validation de la configuration Compose"
docker compose -p journal_logitrak config -q

echo "==> Build des images (journal_backend, journal_frontend)"
docker compose -p journal_logitrak build

echo "==> Démarrage / mise à jour des conteneurs"
docker compose -p journal_logitrak up -d

echo "==> État des conteneurs"
docker compose -p journal_logitrak ps

echo "==> Health check API"
sleep 5
curl -fsS http://127.0.0.1:${BACKEND_PORT:-8101}/api/health && echo

echo "==> Déploiement terminé. Vérifiez https://journal.logitrak.ch"
