"""Cache éphémère en mémoire des réponses Energy — TTL court, tenant-aware, fail-closed.

- Jamais persistant (disparaît au redémarrage, sans conséquence métier).
- La clé inclut le tenant Journal ET le tenant Energy : aucun partage cross-tenant.
- Les réponses cachées sont les enveloppes Energy brutes sanitizées, JAMAIS modifiées
  (null reste null, STALE reste STALE, measurement_type/source/timestamp intacts).
- Les erreurs transport Energy ne sont jamais conservées.
- Instrumentation non sensible : HIT / MISS / EXPIRED / BYPASS (aucun token, aucun payload).
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("energy_cache")

TTL_SECONDS = 60
# Erreur Energy (transport) : JAMAIS conservée au TTL normal — TTL court dédié,
# le bouton Actualiser (bypass) force de toute façon un appel réel. 30 s : la
# fenêtre 15 s expirait pendant les MISS lents (>13 s), refaisant les appels
# en erreur dans l'export qui suit immédiatement le preview.
ERROR_TTL_SECONDS = 30
_NON_CACHEABLE_REASONS = ("energy_unreachable", "energy_not_connected",
                          "energy_invalid_response")

_store: dict[tuple, tuple[float, float, dict]] = {}
_stats = {"hit": 0, "miss": 0, "expired": 0, "bypass": 0}


def make_key(journal_tenant_id, energy_tenant_id, ref, date_from, date_to,
             summary_type) -> tuple:
    return (str(journal_tenant_id), str(energy_tenant_id), str(ref),
            str(date_from), str(date_to), str(summary_type))


def lookup(key: tuple):
    """→ ("HIT", valeur) | ("EXPIRED", None) | ("MISS", None)."""
    entry = _store.get(key)
    if entry is None:
        _record("MISS", key)
        return "MISS", None
    stored_at, ttl, value = entry
    if time.monotonic() - stored_at > ttl:
        _store.pop(key, None)
        _record("EXPIRED", key)
        return "EXPIRED", None
    _record("HIT", key)
    return "HIT", value


def store(key: tuple, value) -> float:
    """Stocke une réponse Energy brute. Une erreur transport n'est JAMAIS
    conservée au TTL normal : TTL erreur court. Retourne le TTL appliqué."""
    is_error = isinstance(value, dict) and value.get("reason") in _NON_CACHEABLE_REASONS
    ttl = ERROR_TTL_SECONDS if is_error else TTL_SECONDS
    _store[key] = (time.monotonic(), ttl, value)
    return ttl


def mark_bypass(key: tuple) -> None:
    _record("BYPASS", key)


def clear() -> None:
    _store.clear()


def stats() -> dict:
    return dict(_stats)


def _record(state: str, key: tuple) -> None:
    _stats[state.lower()] += 1
    # Clé non sensible : tenant Journal, type, ref, période — jamais de token.
    logger.info("energy_cache %s tenant=%s type=%s ref=%s period=%s..%s",
                state, key[0], key[5], key[2], key[3], key[4])
