"""Phase D1.4 — Provisioning credential tenant : chiffrement au repos + non-fuite.

READ-ONLY sur Navixy. Vérifie que :
- _tenant_out ne renvoie jamais la valeur du secret (même chiffrée), seulement masque/état ;
- un credential chiffré au repos (enc::) est correctement déchiffré par le résolveur central
  quand il est lu dans le contexte du tenant ;
- decrypt défensif idempotent sur une valeur legacy en clair.
"""
from __future__ import annotations

import importlib
import os


def test_tenant_out_never_leaks_secret():
    from app.routes.admin import _tenant_out
    t = {"id": "tenantA", "name": "A", "navixy_hash": "enc::supersecretvalue", "navixy_api_url": "https://a"}
    out = _tenant_out(t)
    # La valeur brute ne doit jamais apparaître
    assert "navixy_hash" not in out
    assert "supersecretvalue" not in str(out)
    assert out["has_navixy_hash"] is True
    assert out["navixy_credential_encrypted"] is True
    assert out["navixy_hash_masked"] and out["navixy_hash_masked"].startswith("••••")


def test_encrypted_tenant_credential_resolved_by_central_resolver():
    from cryptography.fernet import Fernet
    os.environ["INTEGRATION_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    os.environ.pop("NAVIXY_API_KEY", None)
    os.environ.pop("NAVIXY_HASH", None)
    import app.tenant_context as tc
    import app.integrations as ig
    importlib.reload(tc)
    importlib.reload(ig)
    try:
        stored = ig.encrypt_secret("tenantA_real_navixy_key")
        assert stored.startswith("enc::")
        tc._tenant_cache = {"tenantA": {"id": "tenantA", "navixy_hash": stored}}
        tok = tc.set_current_tenant("tenantA")
        try:
            cred = ig.get_integration_credential(provider="NAVIXY")
            assert cred and cred["source"] == "TENANT"
            assert cred["credential"] == "tenantA_real_navixy_key"  # déchiffré
        finally:
            tc.reset_current_tenant(tok)
    finally:
        os.environ.pop("INTEGRATION_ENCRYPTION_KEY", None)
        importlib.reload(ig)


def test_defensive_decrypt_idempotent_on_plaintext():
    import app.integrations as ig
    importlib.reload(ig)
    # Sans clé, une valeur en clair legacy reste inchangée (zéro régression).
    assert ig.decrypt_secret("legacy_plaintext_key") == "legacy_plaintext_key"
