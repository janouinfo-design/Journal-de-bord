#!/usr/bin/env bash
# =============================================================================
# LOGITRAK — apply_and_test_0009.sh
# Applique le patch 0009 sur une branche Preview, verifie DEVICE_WRITE=OFF,
# puis lance les tests backend DANS le conteneur. AUCUN deploiement PROD.
#
# Usage (depuis la racine du repo, ex: /opt/apps/journal-logitrak) :
#   bash apply_and_test_0009.sh
#
# Variables optionnelles :
#   PATCH_FILE     chemin du patch (defaut: deliverables/git/0009-*.patch)
#   BACKEND_CTN    nom du conteneur backend (defaut: journal_backend)
#   BASE_BRANCH    branche de base Preview (defaut: main)
#   WORK_BRANCH    branche de travail (defaut: preview/0009-confirm-stale)
# =============================================================================
set -euo pipefail

PATCH_FILE="${PATCH_FILE:-deliverables/git/0009-fix-confirm-matcher-remove-success-true-plus-stale-exposure.patch}"
BACKEND_CTN="${BACKEND_CTN:-journal_backend}"
BASE_BRANCH="${BASE_BRANCH:-main}"
WORK_BRANCH="${WORK_BRANCH:-preview/0009-confirm-stale}"
EXPECTED_SHA="62f11878dc1cb35774ca87d9648258783ffb07d94b3065019d2885f7d3bfaa32"

say() { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }
die() { printf "\n\033[1;31mERREUR: %s\033[0m\n" "$*" >&2; exit 1; }

# 0. Sanity : on est bien a la racine d'un repo git
[ -d .git ] || die "Lancez ce script a la RACINE du repo (ou se trouve .git)."

# 1. Patch present ?
say "1. Verification du patch : $PATCH_FILE"
[ -f "$PATCH_FILE" ] || die "Patch introuvable: $PATCH_FILE (faites 'git pull' ou copiez le .patch)."
if command -v sha256sum >/dev/null 2>&1; then
  GOT="$(sha256sum "$PATCH_FILE" | awk '{print $1}')"
  echo "   sha256 = $GOT"
  [ "$GOT" = "$EXPECTED_SHA" ] || echo "   ATTENTION: sha256 different de l'attendu ($EXPECTED_SHA). Verifiez le fichier."
fi

# 2. Working tree propre
say "2. Etat du working tree"
git status --short
if [ -n "$(git status --porcelain)" ]; then
  die "Working tree non propre. Committez/stashez avant d'appliquer le patch."
fi

# 3. Branche de travail
say "3. Creation de la branche de travail : $WORK_BRANCH (base $BASE_BRANCH)"
git checkout "$BASE_BRANCH"
git pull --ff-only || true
git checkout -b "$WORK_BRANCH" || git checkout "$WORK_BRANCH"

# 4. Application du patch (dry-run puis reel, fallback 3way)
say "4. Application du patch (dry-run)"
if git apply --check "$PATCH_FILE"; then
  git apply "$PATCH_FILE"
  echo "   Patch applique (git apply)."
else
  echo "   Dry-run KO -> tentative 3-way (fusion sur base legerement differente)."
  git apply --3way "$PATCH_FILE" || die "Echec application patch (meme en 3-way). STOP."
fi

say "4b. Fichiers modifies/ajoutes"
git status --short

# 5. GARDE-FOU : DEVICE_WRITE doit rester OFF
say "5. Verification DEVICE_WRITE (backend/.env)"
if [ -f backend/.env ]; then
  grep -E 'PRIVATE_MODE_DEVICE_WRITE|PRIVATE_MODE_ENABLED' backend/.env || true
  DW="$(grep -E '^PRIVATE_MODE_DEVICE_WRITE=' backend/.env | head -1 | cut -d= -f2 | tr -d '[:space:]')"
  if [ "${DW:-0}" != "0" ]; then
    die "PRIVATE_MODE_DEVICE_WRITE=${DW} != 0. Remettez-le a 0 AVANT de continuer. STOP."
  fi
  echo "   OK : DEVICE_WRITE=0 (aucune ecriture device)."
else
  echo "   (backend/.env non present sur l'hote — verifiez dans le conteneur au point 6.)"
fi

# 6. Tests DANS le conteneur backend
say "6. Tests backend dans le conteneur ($BACKEND_CTN)"
docker exec -i "$BACKEND_CTN" sh -lc '
  echo "   DEVICE_WRITE (conteneur) :"; grep -E "PRIVATE_MODE_DEVICE_WRITE|PRIVATE_MODE_ENABLED" /app/backend/.env || true
  cd /app/backend &&
  PYTHONPATH=/app/backend python -m pytest \
    tests/test_fmc130_confirmation_fix.py \
    tests/test_private_mode_stale_exposure.py \
    tests/test_private_mode_phase2.py -q
'

say "7. Non-regression elargie (private/fmc130/mileage/reports)"
docker exec -i "$BACKEND_CTN" sh -lc '
  cd /app/backend &&
  PYTHONPATH=/app/backend python -m pytest tests/ -q \
    -k "private or fmc130 or confirmation or mileage or reports" || true
'

say "TERMINE. Attendu : 67 passed (etape 6) ; 183 passed / 1 skipped (etape 7)."
echo "Les 8 'errors' 401 login = probleme d'environnement PRE-EXISTANT (non bloquant)."
echo "Si tout est vert -> rebuild Preview : docker compose up -d --build $BACKEND_CTN"
echo "NE RIEN DEPLOYER EN PROD. DEVICE_WRITE reste 0."
