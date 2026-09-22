#!/usr/bin/env bash
# =============================================================================
# LOGITRAK — apply_and_test_0009_preview.sh
# Applique le patch 0009 sur le repo PREVIEW (/opt/apps/journal-preview),
# rebuild UNIQUEMENT le service backend Preview, puis lance les tests DEDANS.
#
# CIBLE PREVIEW UNIQUEMENT. LA PROD (journal_backend / /opt/apps/journal-logitrak)
# N'EST JAMAIS TOUCHEE. DEVICE_WRITE reste OFF. Aucun write device.
#
# Usage :
#   cd /opt/apps/journal-preview
#   bash apply_and_test_0009_preview.sh
#
# Variables optionnelles :
#   PATCH_FILE   defaut: deliverables/git/0009-...patch  (ou ~/0009.patch)
#   WORK_BRANCH  defaut: preview/0009-confirm-stale
# =============================================================================
set -euo pipefail

PREVIEW_DIR="/opt/apps/journal-preview"
CTN="journal_preview_backend"
COMPOSE="docker compose -f docker-compose.preview.yml -f docker-compose.private-mode-rollout.yml"
PATCH_FILE="${PATCH_FILE:-deliverables/git/0009-fix-confirm-matcher-remove-success-true-plus-stale-exposure.patch}"
WORK_BRANCH="${WORK_BRANCH:-preview/0009-confirm-stale}"
EXPECTED_SHA="62f11878dc1cb35774ca87d9648258783ffb07d94b3065019d2885f7d3bfaa32"

say() { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }
die() { printf "\n\033[1;31mERREUR: %s\033[0m\n" "$*" >&2; exit 1; }

# 0. On DOIT etre dans le repo PREVIEW (securite anti-PROD)
cd "$PREVIEW_DIR" 2>/dev/null || die "Dossier PREVIEW introuvable: $PREVIEW_DIR"
[ -f docker-compose.preview.yml ] || die "docker-compose.preview.yml absent : mauvais dossier ?"
CURDIR="$(pwd)"
case "$CURDIR" in
  *journal-preview*) : ;;
  *) die "Refus : ce script doit tourner dans /opt/apps/journal-preview (actuel: $CURDIR)";;
esac
echo "Repo PREVIEW : $CURDIR (PROD /opt/apps/journal-logitrak NON touchee)"

# 1. Patch present + integrite
say "1. Patch : $PATCH_FILE"
[ -f "$PATCH_FILE" ] || die "Patch introuvable. Faites 'Save to GitHub' + recuperez-le, ou copiez ~/0009.patch et exportez PATCH_FILE=~/0009.patch"
if command -v sha256sum >/dev/null 2>&1; then
  GOT="$(sha256sum "$PATCH_FILE" | awk '{print $1}')"
  echo "   sha256 = $GOT"
  [ "$GOT" = "$EXPECTED_SHA" ] || echo "   ATTENTION: sha256 != attendu ($EXPECTED_SHA)."
fi

# 2. Branche de travail (HEAD detache -> on cree une branche propre)
say "2. Branche de travail : $WORK_BRANCH"
git rev-parse --abbrev-ref HEAD || true
git checkout -b "$WORK_BRANCH" 2>/dev/null || git checkout "$WORK_BRANCH"

# 3. Application patch (dry-run -> reel -> fallback 3way)
say "3. Application du patch"
if git apply --check "$PATCH_FILE" 2>/dev/null; then
  git apply "$PATCH_FILE"; echo "   OK (git apply)."
else
  echo "   dry-run KO -> tentative 3-way"
  git apply --3way "$PATCH_FILE" || die "Echec application patch. STOP."
fi
git status --short

# 4. GARDE-FOU DEVICE_WRITE = 0 (fichier .env.preview)
say "4. Verification DEVICE_WRITE (.env.preview)"
if [ -f .env.preview ]; then
  grep -E 'PRIVATE_MODE_DEVICE_WRITE|PRIVATE_MODE_ENABLED' .env.preview || true
  DW="$(grep -E '^PRIVATE_MODE_DEVICE_WRITE=' .env.preview | head -1 | cut -d= -f2 | tr -d '[:space:]')"
  [ "${DW:-0}" = "0" ] || die "PRIVATE_MODE_DEVICE_WRITE=${DW} != 0. STOP (remettez a 0)."
  echo "   OK : DEVICE_WRITE=0."
else
  echo "   .env.preview absent sur l'hote — verification faite cote conteneur au point 6."
fi

# 5. REBUILD + restart du SEUL service backend Preview
say "5. Rebuild image backend Preview (build: ./backend)"
$COMPOSE build "$CTN"
say "5b. Restart backend Preview"
$COMPOSE up -d "$CTN"
sleep 4
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E "$CTN|NAMES" || true

# 6. Verif runtime DEVICE_WRITE (dans le conteneur) + tests
say "6. DEVICE_WRITE vu par le process Preview"
docker exec -i "$CTN" sh -lc 'env | grep -E "PRIVATE_MODE_DEVICE_WRITE|PRIVATE_MODE_ENABLED|DB_NAME"'
DWC="$(docker exec -i "$CTN" sh -lc 'echo -n "$PRIVATE_MODE_DEVICE_WRITE"')"
[ "${DWC:-0}" = "0" ] || die "Conteneur: DEVICE_WRITE=${DWC} != 0. STOP."

say "7. Tests fix + non-regression ciblee (dans le conteneur Preview)"
docker exec -i "$CTN" sh -lc '
  cd /app/backend &&
  PYTHONPATH=/app/backend python -m pytest \
    tests/test_fmc130_confirmation_fix.py \
    tests/test_private_mode_stale_exposure.py \
    tests/test_private_mode_phase2.py -q
'
echo
say "8. Non-regression elargie (optionnel)"
docker exec -i "$CTN" sh -lc '
  cd /app/backend &&
  PYTHONPATH=/app/backend python -m pytest tests/ -q \
    -k "private or fmc130 or confirmation or mileage or reports" || true
'

say "TERMINE."
echo "Attendu etape 7 : 67 passed  |  etape 8 : 183 passed / 1 skipped."
echo "Les 8 'errors' 401 login = env pre-existant (NON bloquant)."
echo "PROD (journal_backend) NON touchee. DEVICE_WRITE reste 0. Aucun deploiement PROD."
