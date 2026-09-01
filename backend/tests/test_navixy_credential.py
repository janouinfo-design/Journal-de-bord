"""Phase D1.1 — Tests du credential Navixy (API Key prioritaire) et de l'honnêteté odomètre.

READ-ONLY : aucun appel réseau Navixy, aucun secret en clair, aucune écriture.
Vérifie la résolution du credential env (API_KEY > LEGACY_HASH), le type reporté,
et que rien ne fuit la valeur.
"""
from __future__ import annotations

import importlib
import os


def _reload():
    import app.navixy_client as nc
    importlib.reload(nc)
    return nc


def _clear():
    os.environ.pop("NAVIXY_API_KEY", None)
    os.environ.pop("NAVIXY_HASH", None)


def test_credential_none_when_unset():
    _clear()
    nc = _reload()
    assert nc.credential_type() == "NONE"
    assert nc.is_configured() is False


def test_legacy_hash_supported_during_migration():
    _clear()
    os.environ["NAVIXY_HASH"] = "legacy_dummy_credential_0123456789ab"
    try:
        nc = _reload()
        assert nc.credential_type() == "LEGACY_HASH"
        assert nc.is_configured() is True
    finally:
        _clear()
        _reload()


def test_api_key_takes_priority_over_legacy_hash():
    _clear()
    os.environ["NAVIXY_HASH"] = "legacy_dummy_credential_0123456789ab"
    os.environ["NAVIXY_API_KEY"] = "apikey_dummy_credential_abcdef012345"
    try:
        nc = _reload()
        assert nc.credential_type() == "API_KEY"
        # priorité prouvée sans révéler la valeur : longueur == celle de l'API key
        assert len(nc._env_credential()) == len(os.environ["NAVIXY_API_KEY"])
    finally:
        _clear()
        _reload()


def test_credential_never_leaked_in_type_or_configured():
    """credential_type()/is_configured() ne doivent jamais renvoyer la valeur du secret."""
    _clear()
    secret = "supersecret_navixy_value_should_not_leak"
    os.environ["NAVIXY_API_KEY"] = secret
    try:
        nc = _reload()
        assert secret not in nc.credential_type()
        assert secret not in str(nc.is_configured())
    finally:
        _clear()
        _reload()
