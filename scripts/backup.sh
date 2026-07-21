#!/usr/bin/env bash
# Sauvegarde quotidienne du Journal de bord (base + fichiers + config).
# Cron suggéré : 30 2 * * * /opt/apps/journal-logitrak/scripts/backup.sh >> /opt/apps/journal-logitrak/logs/backup.log 2>&1
set -euo pipefail

APP_DIR="/opt/apps/journal-logitrak"
BACKUP_DIR="$APP_DIR/backups"
RETENTION_DAYS=14
STAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"
set -a; source "$APP_DIR/.env"; set +a

echo "[$STAMP] Sauvegarde base de données ($DB_NAME)..."
docker exec journal_database sh -c \
  "mongodump --archive --gzip -u '$MONGO_ROOT_USER' -p '$MONGO_ROOT_PASSWORD' --authenticationDatabase admin --db '$DB_NAME'" \
  > "$BACKUP_DIR/journal_db_$STAMP.archive.gz"

echo "[$STAMP] Sauvegarde fichiers uploadés..."
if [ -d "$APP_DIR/data/storage" ]; then
  tar -czf "$BACKUP_DIR/journal_storage_$STAMP.tar.gz" -C "$APP_DIR/data" storage
fi

echo "[$STAMP] Sauvegarde configuration (.env)..."
cp "$APP_DIR/.env" "$BACKUP_DIR/journal_env_$STAMP.env"
chmod 600 "$BACKUP_DIR/journal_env_$STAMP.env"

echo "[$STAMP] Rotation (> $RETENTION_DAYS jours)..."
find "$BACKUP_DIR" -type f -name 'journal_*' -mtime +"$RETENTION_DAYS" -delete

echo "[$STAMP] Sauvegarde terminée : $(ls -1 "$BACKUP_DIR" | grep "$STAMP" | wc -l) fichiers."
