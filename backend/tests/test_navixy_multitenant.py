"""Tests architecture credential Navixy multi-tenant (fail-closed, chiffrement, fallback).

READ-ONLY : aucun appel réseau Navixy, aucun secret en clair dans les assertions de sortie,
aucune écriture. Vérifie l'isolation par tenant et la gouvernance du fallback global.
"""
from __future__ import annotations

import importlib
import os


def _fresh():
    import app.tenant_context as tc
    import app.integrations as ig
    importlib.reload(tc)
    importlib.reload(ig)
    return tc, ig


def _clear_env():
    for k in ("NAVIXY_API_KEY", "NAVIXY_HASH", "ALLOW_GLOBAL_NAVIXY_FALLBACK",
              "INTEGRATION_ENCRYPTION_KEY"):
        os.environ.pop(k, None)


def _set_cache(tc, mapping):
    # Injecte un cache tenant en mémoire (pas de DB).
    tc._tenant_cache = mapping


def test_per_tenant_credential_isolation():
    _clear_env()
    tc, ig = _fresh()
    _set_cache(tc, {
        "tenantA": {"id": "tenantA", "navixy_hash": "credA_xxxxxxxxxxxxxxxx", "navixy_api_url": "https://a"},
        "tenantB": {"id": "tenantB", "navixy_hash": "credB_yyyyyyyyyyyyyyyy", "navixy_api_url": "https://b"},
    })
    # Tenant A -> credential A
    tok = tc.set_current_tenant("tenantA")
    try:
        credA = ig.get_integration_credential(provider="NAVIXY")
        assert credA and credA["source"] == "TENANT"
        assert credA["credential"] == "credA_xxxxxxxxxxxxxxxx"
        assert credA["api_url"] == "https://a"
    finally:
        tc.reset_current_tenant(tok)
    # Tenant B -> credential B (jamais A)
    tok = tc.set_current_tenant("tenantB")
    try:
        credB = ig.get_integration_credential(provider="NAVIXY")
        assert credB["credential"] == "credB_yyyyyyyyyyyyyyyy"
    finally:
        tc.reset_current_tenant(tok)


def test_fail_closed_no_cross_tenant_and_no_global_when_disabled():
    _clear_env()
    os.environ["ALLOW_GLOBAL_NAVIXY_FALLBACK"] = "false"
    os.environ["NAVIXY_API_KEY"] = "global_env_key_should_not_be_used"
    tc, ig = _fresh()
    _set_cache(tc, {
        "tenantA": {"id": "tenantA", "navixy_hash": "credA_xxxxxxxxxxxxxxxx"},
        "tenantC": {"id": "tenantC"},  # pas de credential
    })
    # Tenant C sans credential + fallback global désactivé -> NONE (jamais A ni env)
    tok = tc.set_current_tenant("tenantC")
    try:
        assert ig.get_integration_credential(provider="NAVIXY") is None
        assert ig.integration_status(provider="NAVIXY") == "NONE"
    finally:
        tc.reset_current_tenant(tok)
    _clear_env()


def test_global_fallback_allowed_only_when_flag_true():
    _clear_env()
    os.environ["ALLOW_GLOBAL_NAVIXY_FALLBACK"] = "true"
    os.environ["NAVIXY_API_KEY"] = "global_dev_pilot_key_1234567890"
    tc, ig = _fresh()
    _set_cache(tc, {})
    # Hors contexte tenant (ex. scheduler global) + flag true -> fallback env autorisé
    cred = ig.get_integration_credential(provider="NAVIXY")
    assert cred and cred["source"] == "ENV_API_KEY"
    _clear_env()


def test_encryption_roundtrip_and_legacy_plaintext():
    _clear_env()
    from cryptography.fernet import Fernet
    os.environ["INTEGRATION_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    tc, ig = _fresh()
    enc = ig.encrypt_secret("supersecretkey")
    assert enc.startswith("enc::")           # chiffré
    assert ig.decrypt_secret(enc) == "supersecretkey"
    # valeur legacy en clair -> tolérée
    assert ig.decrypt_secret("plainlegacy") == "plainlegacy"
    _clear_env()


def test_tenant_encrypted_credential_resolved():
    _clear_env()
    from cryptography.fernet import Fernet
    os.environ["INTEGRATION_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    tc, ig = _fresh()
    stored = ig.encrypt_secret("tenantA_real_key")
    _set_cache(tc, {"tenantA": {"id": "tenantA", "navixy_hash": stored}})
    tok = tc.set_current_tenant("tenantA")
    try:
        cred = ig.get_integration_credential(provider="NAVIXY")
        assert cred and cred["credential"] == "tenantA_real_key"
        assert cred["source"] == "TENANT"
    finally:
        tc.reset_current_tenant(tok)
    _clear_env()


def test_status_never_returns_secret_value():
    _clear_env()
    os.environ["ALLOW_GLOBAL_NAVIXY_FALLBACK"] = "true"
    secret = "should_not_leak_navixy_secret_value"
    os.environ["NAVIXY_API_KEY"] = secret
    tc, ig = _fresh()
    _set_cache(tc, {})
    assert secret not in ig.integration_status(provider="NAVIXY")
    _clear_env()
