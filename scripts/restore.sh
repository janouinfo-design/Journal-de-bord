#!/usr/bin/env bash
# Restauration du Journal de bord depuis une sauvegarde.
# Usage :
#   ./restore.sh backups/journal_db_YYYYMMDD_HHMMSS.archive.gz [backups/journal_storage_YYYYMMDD_HHMMSS.tar.gz]
# ATTENTION : écrase la base journal_logitrak actuelle (--drop). Aucune autre application n'est touchée.
set -euo pipefail

APP_DIR="/opt/apps/journal-logitrak"
DB_ARCHIVE="${1:?Usage: restore.sh <archive_db.gz> [archive_storage.tar.gz]}"
STORAGE_ARCHIVE="${2:-}"

set -a; source "$APP_DIR/.env"; set +a

read -r -p "Restaurer la base '$DB_NAME' depuis $DB_ARCHIVE ? (oui/non) " CONFIRM
[ "$CONFIRM" = "oui" ] || { echo "Abandon."; exit 1; }

echo "==> Restauration base de données..."
docker exec -i journal_database sh -c \
  "mongorestore --archive --gzip --drop -u '$MONGO_ROOT_USER' -p '$MONGO_ROOT_PASSWORD' --authenticationDatabase admin --nsInclude '$DB_NAME.*'" \
  < "$DB_ARCHIVE"

if [ -n "$STORAGE_ARCHIVE" ]; then
  echo "==> Restauration fichiers uploadés..."
  mkdir -p "$APP_DIR/data"
  tar -xzf "$STORAGE_ARCHIVE" -C "$APP_DIR/data"
fi

echo "==> Redémarrage ciblé du backend..."
docker compose -p journal_logitrak restart journal_backend

echo "==> Restauration terminée."
