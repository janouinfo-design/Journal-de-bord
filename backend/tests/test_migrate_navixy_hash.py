"""Tests migration navixy_hash — dry-run/apply, idempotence, fail-closed, no-secret.

Aucune écriture réseau. Clé de chiffrement pilotée via env (Fernet).
Aucun secret en clair ne doit apparaître dans les sorties de test.
"""
import asyncio
import importlib
import os
import sys

import pytest
from cryptography.fernet import Fernet

# Import du script (chemin scripts/)
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# --- Mock DB minimal (async) ---
class _Coll:
    def __init__(self):
        self.docs = []

    def find(self, q, proj=None):
        docs = [dict(d) for d in self.docs]

        class _Cur:
            async def to_list(self, n):
                return docs
        return _Cur()

    async def update_one(self, q, upd):
        class _Res:
            matched_count = 0
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(upd.get("$set", {}))
                _Res.matched_count = 1
                return _Res()
        return _Res()

    async def insert_one(self, d):
        self.docs.append(dict(d))


class _DB:
    def __init__(self):
        self.tenants = _Coll()


# --- Fixtures clé ---
_KEY = Fernet.generate_key().decode()
_OTHER_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _set_key(monkeypatch):
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", _KEY)
    # recharger integrations + script pour prendre la clé
    import app.integrations as integ
    importlib.reload(integ)
    import migrate_navixy_hash as mig
    importlib.reload(mig)
    yield


def _mod():
    import migrate_navixy_hash as mig
    return mig


def _integ():
    import app.integrations as integ
    return integ


def _seed(db, tenant_id, value):
    _run(db.tenants.insert_one({"id": tenant_id, "navixy_hash": value}))


# ============================ TESTS ============================
def test_t1_plaintext_legacy_dryrun_no_write():
    db = _DB()
    _seed(db, "t1", "PLAINCRED123")
    res = _run(_mod().migrate_navixy_hash(db, apply=False))
    c = res["counters"]
    assert c["LEGACY_PLAINTEXT"] == 1 and c["to_migrate"] == 1
    assert c["writes"] == 0 and c["migrated"] == 0
    assert db.tenants.docs[0]["navixy_hash"] == "PLAINCRED123"  # inchangé


def test_t2_apply_on_plaintext_encrypts_roundtrip():
    db = _DB()
    _seed(db, "t1", "PLAINCRED123")
    res = _run(_mod().migrate_navixy_hash(db, apply=True))
    assert res["counters"]["migrated"] == 1 and res["counters"]["writes"] == 1
    stored = db.tenants.docs[0]["navixy_hash"]
    assert stored.startswith("enc::")
    # decrypt rend EXACTEMENT la valeur initiale
    assert _integ().decrypt_secret(stored) == "PLAINCRED123"


def test_t3_already_encrypted_valid_skip():
    db = _DB()
    enc = _integ().encrypt_secret("SECRETXYZ")
    _seed(db, "t1", enc)
    res = _run(_mod().migrate_navixy_hash(db, apply=True))
    assert res["counters"]["ENCRYPTED_VALID"] == 1
    assert res["counters"]["to_migrate"] == 0 and res["counters"]["writes"] == 0
    assert db.tenants.docs[0]["navixy_hash"] == enc  # inchangé


def test_t4_idempotent_second_pass():
    db = _DB()
    _seed(db, "t1", "PLAINCRED123")
    _run(_mod().migrate_navixy_hash(db, apply=True))   # 1er passage : chiffre
    res2 = _run(_mod().migrate_navixy_hash(db, apply=True))  # 2e passage : rien
    assert res2["counters"]["to_migrate"] == 0
    assert res2["counters"]["migrated"] == 0 and res2["counters"]["writes"] == 0


def test_t5_invalid_encrypted_no_write():
    db = _DB()
    _seed(db, "t1", "enc::not-a-valid-token")
    res = _run(_mod().migrate_navixy_hash(db, apply=True))
    assert res["counters"]["INVALID_ENCRYPTED"] == 1
    assert res["counters"]["to_migrate"] == 0 and res["counters"]["writes"] == 0
    assert db.tenants.docs[0]["navixy_hash"] == "enc::not-a-valid-token"  # jamais réparé


def test_t6_no_key_failclosed(monkeypatch):
    monkeypatch.delenv("INTEGRATION_ENCRYPTION_KEY", raising=False)
    import app.integrations as integ
    importlib.reload(integ)
    import migrate_navixy_hash as mig
    importlib.reload(mig)
    db = _DB()
    _seed(db, "t1", "PLAINCRED123")
    res = _run(mig.migrate_navixy_hash(db, apply=True))
    assert res["status"] == "FAILED_NO_KEY"
    assert res["counters"]["writes"] == 0
    assert db.tenants.docs[0]["navixy_hash"] == "PLAINCRED123"


def test_t7_wrong_key_makes_encrypted_invalid(monkeypatch):
    # chiffrer avec _KEY
    db = _DB()
    enc = _integ().encrypt_secret("SECRETXYZ")
    _seed(db, "t1", enc)
    # basculer sur une AUTRE clé -> enc:: devient indéchiffrable = INVALID_ENCRYPTED
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", _OTHER_KEY)
    import app.integrations as integ
    importlib.reload(integ)
    import migrate_navixy_hash as mig
    importlib.reload(mig)
    res = _run(mig.migrate_navixy_hash(db, apply=True))
    assert res["counters"]["INVALID_ENCRYPTED"] == 1
    assert res["counters"]["writes"] == 0
    assert db.tenants.docs[0]["navixy_hash"] == enc  # inchangé


def test_t8_null_and_empty_no_migration():
    db = _DB()
    _seed(db, "t_null", None)
    _seed(db, "t_empty", "")
    _seed(db, "t_blank", "   ")
    res = _run(_mod().migrate_navixy_hash(db, apply=True))
    c = res["counters"]
    assert c["to_migrate"] == 0 and c["writes"] == 0
    assert c["ABSENT"] + c["EMPTY"] == 3


def test_t9_concurrent_change_skip_conflict():
    db = _DB()
    _seed(db, "t1", "PLAINCRED123")

    # Simuler un changement concurrent : update_one ne matchera pas la valeur auditée
    orig_update = db.tenants.update_one

    async def _racing_update(q, upd):
        # la valeur en base a "changé" entre-temps -> matched_count = 0
        class _Res:
            matched_count = 0
        return _Res()
    db.tenants.update_one = _racing_update
    res = _run(_mod().migrate_navixy_hash(db, apply=True))
    db.tenants.update_one = orig_update
    assert res["counters"]["skipped_conflict"] == 1
    assert res["counters"]["migrated"] == 0


def test_t10_multitenant_independent():
    db = _DB()
    _seed(db, "t1", "PLAIN_A")
    _seed(db, "t2", _integ().encrypt_secret("SECRET_B"))
    _seed(db, "t3", None)
    _seed(db, "t4", "enc::corrupt")
    res = _run(_mod().migrate_navixy_hash(db, apply=True))
    c = res["counters"]
    assert c["analyzed"] == 4
    assert c["migrated"] == 1                 # seul t1
    assert c["ENCRYPTED_VALID"] == 1          # t2
    assert c["INVALID_ENCRYPTED"] == 1        # t4
    # t1 chiffré et round-trip
    d1 = next(d for d in db.tenants.docs if d["id"] == "t1")
    assert d1["navixy_hash"].startswith("enc::")
    assert _integ().decrypt_secret(d1["navixy_hash"]) == "PLAIN_A"


def test_t11_no_secret_in_output():
    db = _DB()
    _seed(db, "t1", "SUPER_SECRET_PLAINTEXT")
    res = _run(_mod().migrate_navixy_hash(db, apply=True))
    # Le rapport/compteurs ne contiennent JAMAIS le secret en clair ni le ciphertext
    import json
    blob = json.dumps(res, default=str)
    assert "SUPER_SECRET_PLAINTEXT" not in blob
    stored = db.tenants.docs[0]["navixy_hash"]
    assert stored not in blob  # pas de ciphertext non plus dans le rapport


def test_t12_regression_decrypt_still_used_by_integration():
    """Après migration, get_integration_credential doit toujours retrouver le clair."""
    db = _DB()
    _seed(db, "t1", "PLAINCRED123")
    _run(_mod().migrate_navixy_hash(db, apply=True))
    stored = db.tenants.docs[0]["navixy_hash"]
    # simulate integration decrypt path
    assert _integ().decrypt_secret(stored) == "PLAINCRED123"


def test_classify_all_formats():
    integ = _integ()
    assert integ.classify_secret(None) == integ.FMT_ABSENT
    assert integ.classify_secret("") == integ.FMT_EMPTY
    assert integ.classify_secret("   ") == integ.FMT_EMPTY
    assert integ.classify_secret("plaincred") == integ.FMT_LEGACY_PLAINTEXT
    assert integ.classify_secret(integ.encrypt_secret("x")) == integ.FMT_ENCRYPTED_VALID
    assert integ.classify_secret("enc::garbage") == integ.FMT_INVALID_ENCRYPTED
