"""Résolution centralisée des credentials d'intégration (multi-tenant, fail-closed).

Principe métier : CHAQUE tenant peut avoir son propre compte / sa propre clé Navixy.
Le credential est résolu à partir du **tenant_id du contexte d'auth serveur** — jamais
d'un tenant_id fourni librement par le mobile.

Priorité de résolution (voir §4) :
  1. Credential spécifique au tenant (doc tenant : `navixy_hash`, déchiffré si chiffré).
  2. NAVIXY_API_KEY (env)  — FALLBACK DEV/PILOT UNIQUEMENT, gouverné par ALLOW_GLOBAL_NAVIXY_FALLBACK.
  3. NAVIXY_HASH (env)     — LEGACY FALLBACK, même gouvernance.
  4. NONE.

FAIL-CLOSED (§5) : si un tenant est en contexte et n'a pas de credential, on NE retombe
JAMAIS sur celui d'un autre tenant. Le fallback GLOBAL (env) n'est autorisé que si
`ALLOW_GLOBAL_NAVIXY_FALLBACK=true` (dev/pilote). En production : `false`.

SÉCURITÉ : le secret n'est jamais loggé, jamais renvoyé au frontend, jamais dans un rapport,
jamais commité. Les fonctions publiques ne renvoient QUE le credential côté serveur
(consommé par NavixyClient) ou des métadonnées non sensibles.
"""
from __future__ import annotations

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _global_fallback_allowed() -> bool:
    """Le fallback credential GLOBAL (env) est-il autorisé ? (DEV/PILOT uniquement)."""
    return os.environ.get("ALLOW_GLOBAL_NAVIXY_FALLBACK", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _fernet():
    """Retourne un Fernet si INTEGRATION_ENCRYPTION_KEY est configurée, sinon None.
    L'absence de clé => stockage en clair conservé (rétro-compat), sans chiffrement."""
    key = os.environ.get("INTEGRATION_ENCRYPTION_KEY", "").strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode())
    except Exception as e:  # clé invalide -> on n'expose jamais la valeur
        logger.warning("INTEGRATION_ENCRYPTION_KEY invalide (chiffrement désactivé): %s", type(e).__name__)
        return None


def encrypt_secret(plaintext: str) -> str:
    """Chiffre un secret pour stockage. Si aucune clé serveur -> renvoie tel quel (clair).
    Préfixe `enc::` pour distinguer une valeur chiffrée d'une valeur en clair legacy."""
    if not plaintext:
        return plaintext
    f = _fernet()
    if not f:
        return plaintext
    return "enc::" + f.encrypt(plaintext.encode()).decode()


def decrypt_secret(stored: Optional[str]) -> Optional[str]:
    """Déchiffre un secret stocké. Tolère les valeurs legacy en clair (sans préfixe)."""
    if not stored:
        return stored
    if not stored.startswith("enc::"):
        return stored  # valeur legacy en clair
    f = _fernet()
    if not f:
        # Valeur chiffrée mais pas de clé pour déchiffrer -> indisponible (fail-closed).
        logger.warning("Credential chiffré mais INTEGRATION_ENCRYPTION_KEY absente.")
        return None
    try:
        return f.decrypt(stored[len("enc::"):].encode()).decode()
    except Exception:
        logger.warning("Échec de déchiffrement d'un credential d'intégration.")
        return None


def get_integration_credential(tenant_id: Optional[str] = None,
                               provider: str = "NAVIXY") -> Optional[dict]:
    """Résout le credential d'intégration pour (tenant, provider). Fail-closed.

    Retour : {"credential": <str>, "source": "TENANT"|"ENV_API_KEY"|"ENV_LEGACY_HASH",
              "api_url": <str|None>} ou None si non configuré.
    Le tenant_id vient du contexte serveur (jamais du mobile).
    """
    if provider != "NAVIXY":
        # Architecture prête pour d'autres providers (MAPON, FLESPI) — non implémentés ici.
        return None

    from app.tenant_context import get_tenant_doc, get_tenant_id

    ctx_tenant = tenant_id or get_tenant_id()

    # 1) Credential SPÉCIFIQUE au tenant (source normale en production).
    if ctx_tenant:
        t = get_tenant_doc(ctx_tenant)
        if t and t.get("navixy_hash"):
            cred = decrypt_secret(t.get("navixy_hash"))
            if cred:
                return {
                    "credential": cred,
                    "source": "TENANT",
                    "api_url": t.get("navixy_api_url"),
                }
        # FAIL-CLOSED : tenant en contexte SANS credential -> on n'emprunte JAMAIS
        # celui d'un autre tenant. On n'autorise le fallback global que si le flag DEV l'permet.
        if not _global_fallback_allowed():
            return None

    # 2/3) Fallback GLOBAL env (DEV/PILOT uniquement).
    if _global_fallback_allowed():
        api_key = os.environ.get("NAVIXY_API_KEY", "").strip()
        if api_key:
            return {"credential": api_key, "source": "ENV_API_KEY",
                    "api_url": os.environ.get("NAVIXY_API_URL")}
        legacy = os.environ.get("NAVIXY_HASH", "").strip()
        if legacy:
            return {"credential": legacy, "source": "ENV_LEGACY_HASH",
                    "api_url": os.environ.get("NAVIXY_API_URL")}
    return None


def integration_status(tenant_id: Optional[str] = None,
                       provider: str = "NAVIXY") -> str:
    """État NON sensible du credential (pour rapport/admin) — jamais la valeur.
    NONE / TENANT / ENV_API_KEY / ENV_LEGACY_HASH."""
    cred = get_integration_credential(tenant_id, provider)
    return cred["source"] if cred else "NONE"


# ---------------------------------------------------------------------------
# Classification (NON destructive, NON sensible) d'une valeur stockée.
# Utilisée par l'audit / la migration. Ne renvoie JAMAIS la valeur elle-même.
# ---------------------------------------------------------------------------
FMT_ABSENT = "ABSENT"                    # champ absent / None
FMT_EMPTY = "EMPTY"                      # chaîne vide / blancs
FMT_LEGACY_PLAINTEXT = "LEGACY_PLAINTEXT"  # credential en clair (sans préfixe enc::)
FMT_ENCRYPTED_VALID = "ENCRYPTED_VALID"    # enc:: déchiffrable avec la clé courante
FMT_INVALID_ENCRYPTED = "INVALID_ENCRYPTED"  # enc:: NON déchiffrable (clé absente/mauvaise/corrompu)


def classify_secret(stored, *, key_available: Optional[bool] = None) -> str:
    """Classe une valeur stockée SANS l'exposer. Ne déchiffre que pour VÉRIFIER
    la validité (le clair n'est jamais retourné/loggé).

    - None                         -> ABSENT
    - "" / blancs                  -> EMPTY
    - ne commence pas par enc::     -> LEGACY_PLAINTEXT
    - enc:: + déchiffrable          -> ENCRYPTED_VALID
    - enc:: + non déchiffrable      -> INVALID_ENCRYPTED
    """
    if stored is None:
        return FMT_ABSENT
    if not isinstance(stored, str) or stored.strip() == "":
        return FMT_EMPTY
    if not stored.startswith("enc::"):
        return FMT_LEGACY_PLAINTEXT
    # enc:: -> vérifier la déchiffrabilité réelle (jamais présumer valide)
    plain = decrypt_secret(stored)
    return FMT_ENCRYPTED_VALID if plain else FMT_INVALID_ENCRYPTED


def encryption_key_available() -> bool:
    """True si INTEGRATION_ENCRYPTION_KEY est configurée et valide (Fernet)."""
    return _fernet() is not None
