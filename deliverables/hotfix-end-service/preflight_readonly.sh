#!/usr/bin/env bash
# =====================================================================
# GO 1 — PRÉFLIGHT / AUDIT READ-ONLY (hotfix « Fin de service »)
#
# READ-ONLY vis-à-vis de la PROD applicative, de la DB, des conteneurs et
# des services. N'écrit RIEN dans /opt/apps/journal-logitrak. N'applique
# AUCUN patch (git apply --check UNIQUEMENT). Ne build/recreate rien.
#
# Les artefacts vivent dans un dossier ISOLÉ hors repo :
#   /home/ubuntu/hotfix-end-service/
# À lancer depuis ce dossier.
# =====================================================================
set -u

HOTFIX_DIR="/home/ubuntu/hotfix-end-service"
APP_DIR="/opt/apps/journal-logitrak"
BACKEND="${APP_DIR}/backend"
ID_FILE="${BACKEND}/app/routes/identification.py"
POLICY_FILE="${BACKEND}/app/end_service_policy.py"
PATCH="${HOTFIX_DIR}/identification.py.patch"   # reste HORS repo

echo "==================================================================="
echo "PREFLIGHT READ-ONLY — hotfix Fin de service"
echo "HOTFIX_DIR=${HOTFIX_DIR}"
echo "APP_DIR=${APP_DIR}"
echo "date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "==================================================================="

echo ""
echo "--- [1] SHA256 ACTUEL identification.py (PROD hote) ---"
if [ -f "${ID_FILE}" ]; then
  sha256sum "${ID_FILE}"
else
  echo "ABSENT: ${ID_FILE}"
fi

echo ""
echo "--- [2] end_service_policy.py (PROD hote) : presence + SHA256 ---"
if [ -f "${POLICY_FILE}" ]; then
  echo "PRESENT"
  sha256sum "${POLICY_FILE}"
else
  echo "ABSENT (sera ajoute au GO 2)"
fi

echo ""
echo "--- [3] SHA256 RUNTIME identification.py DANS le conteneur journal_backend ---"
docker exec -i journal_backend sh -c '
  for p in /app/app/routes/identification.py /app/backend/app/routes/identification.py; do
    if [ -f "$p" ]; then echo "PATH=$p"; sha256sum "$p"; fi
  done
  echo "--- policy runtime ---"
  for p in /app/app/end_service_policy.py /app/backend/app/end_service_policy.py; do
    if [ -f "$p" ]; then echo "PATH=$p"; sha256sum "$p"; else echo "ABSENT=$p"; fi
  done
' 2>/dev/null || echo "docker exec indisponible"

echo ""
echo "--- [4] Le hotfix est-il DEJA present (hote) ? ---"
if grep -q "_resolve_end_service_decision" "${ID_FILE}" 2>/dev/null; then
  echo "DEJA_APPLIQUE=OUI (_resolve_end_service_decision presente)"
else
  echo "DEJA_APPLIQUE=NON"
fi

echo ""
echo "--- [5] Ancres de contexte attendues par le patch (hote) ---"
grep -n '@router.post("/driver/vehicle-assignment/end")' "${ID_FILE}" 2>/dev/null \
  || echo "ANCRE_END=INTROUVABLE"
grep -n 'res.get("result") in ("ok", "noop")' "${ID_FILE}" 2>/dev/null \
  || echo "ANCRE_RETOUR=INTROUVABLE"

echo ""
echo "--- [6] git apply --check (JAMAIS git apply) ---"
if [ ! -f "${PATCH}" ]; then
  echo "PATCH_ABSENT=${PATCH} (deposez-le d'abord en base64)"
elif [ -d "${APP_DIR}/.git" ]; then
  echo "Depot git detecte dans ${APP_DIR}. Test SANS ecriture :"
  ( cd "${APP_DIR}" && git apply --check -p1 "${PATCH}" 2>&1 ) \
    && echo "GIT_APPLY_CHECK=OK" \
    || echo "GIT_APPLY_CHECK=FAIL (contexte PROD divergent -> patch chirurgical adapte requis, PAS de contournement auto)"
else
  echo "GIT_APPLY_CHECK=SKIP (pas de .git exploitable dans ${APP_DIR})"
fi

echo ""
echo "--- [7] Etat du worktree cible (READ-ONLY, informatif) ---"
if [ -d "${APP_DIR}/.git" ]; then
  ( cd "${APP_DIR}" && echo "HEAD=$(git rev-parse HEAD 2>/dev/null)" \
    && echo "--- git status --porcelain (identification.py / end_service_policy.py) ---" \
    && git status --porcelain backend/app/routes/identification.py backend/app/end_service_policy.py 2>/dev/null )
else
  echo "WORKTREE=non-git ou non standard"
fi

echo ""
echo "--- [8] Image / conteneur actuellement execute ---"
docker ps --filter "name=journal_backend" --format "NAME={{.Names}} IMAGE={{.Image}} STATUS={{.Status}} ID={{.ID}}" 2>/dev/null \
  || echo "docker ps indisponible"

echo ""
echo "--- [9] /api/health ---"
code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8101/api/health 2>/dev/null)
echo "HEALTH_HTTP=${code:-NO_RESPONSE}"

echo ""
echo "--- [10] DB_WRITE ---"
echo "DB_WRITE=0  (ce preflight n'execute aucune ecriture Mongo ni applicative)"

echo ""
echo "==================================================================="
echo "PREFLIGHT TERMINE — AUCUNE ECRITURE PROD/DB/CONTENEUR/SERVICE."
echo "Collez la sortie complete. En cas de GIT_APPLY_CHECK=FAIL :"
echo "aucune tentative de contournement — patch chirurgical adapte au GO 2."
echo "==================================================================="
