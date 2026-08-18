#!/bin/bash
# Exécuté UNIQUEMENT à la première initialisation du volume journal_db_data.
# Crée un utilisateur applicatif limité à la base du Journal de bord.
set -e

mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin <<EOF
use $MONGO_APP_DB
db.createUser({
  user: "$MONGO_APP_USER",
  pwd: "$MONGO_APP_PASSWORD",
  roles: [{ role: "readWrite", db: "$MONGO_APP_DB" }]
})
EOF

echo "Utilisateur applicatif '$MONGO_APP_USER' créé (base $MONGO_APP_DB uniquement)."
