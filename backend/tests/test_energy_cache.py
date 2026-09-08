"""Cache éphémère du rapprochement Energy — TTL 60 s, tenant-aware, fail-closed.

Partie A : tests unitaires du module app.energy_cache (clé, TTL, non-cacheable, logs).
Partie B : tests e2e contre le backend live (HIT/MISS/BYPASS réels, isolation tenant,
null/STALE/measurement_type/source/timestamp STRICTEMENT conservés depuis le cache,
exports XLSX/PDF réutilisant le cache du preview).

Le token Energy n'est JAMAIS affiché ni loggé.
"""
from __future__ import annotations

import os
import random
import time

import pytest
import requests
from dotenv import dotenv_values

from app import energy_cache

frontend_env = dotenv_values("/app/frontend/.env")
backend_env = dotenv_values("/app/backend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ENERGY_TOKEN = backend_env.get("ENERGY_API_TOKEN") or ""

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
ADMIN_B = {"email": "admin-b@test.ch", "password": "testb123"}

PREVIEW_URL = f"{API}/livre/energy/reconciliation/preview"
XLSX_URL = f"{API}/livre/energy/reconciliation/export.xlsx"
PDF_URL = f"{API}/livre/energy/reconciliation/export.pdf"


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login {creds['email']}: {r.status_code}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_h():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def admin_b_h():
    return _login(ADMIN_B)


def _fresh_period():
    """Période historique unique par run → MISS garanti côté serveur."""
    day = random.randint(1, 25)
    month = random.randint(1, 12)
    return f"2024-{month:02d}-{day:02d}", f"2024-{month:02d}-{day + 2:02d}"


K = ("default", "paas_x", "veh1|ref1", "2026-08-01", "2026-08-31", "vehicle_summary")


# ---------------------------------------------------------------------------
# Partie A — unitaires du module
# ---------------------------------------------------------------------------
class TestCacheModule:
    def setup_method(self):
        energy_cache.clear()

    def test_miss_initial(self):
        state, val = energy_cache.lookup(energy_cache.make_key(*K))
        assert state == "MISS" and val is None

    def test_hit_dans_ttl(self):
        key = energy_cache.make_key(*K)
        payload = {"availability": "STALE", "metrics": {"fuel_liters_total": {
            "value": 28.0, "unit": "L", "availability": "STALE",
            "measurement_type": "MEASURED", "source": "NAVIXY_CAN", "timestamp": "t1"}}}
        assert energy_cache.store(key, payload) == energy_cache.TTL_SECONDS
        state, val = energy_cache.lookup(key)
        assert state == "HIT"
        # valeur strictement identique : STALE + MEASURED + source + timestamp conservés
        assert val == payload
        assert val["metrics"]["fuel_liters_total"]["availability"] == "STALE"
        assert val["metrics"]["fuel_liters_total"]["measurement_type"] == "MEASURED"

    def test_expiration_puis_miss(self, monkeypatch):
        key = energy_cache.make_key(*K)
        monkeypatch.setattr(energy_cache, "TTL_SECONDS", 0.05)
        energy_cache.store(key, {"availability": "AVAILABLE"})
        time.sleep(0.1)
        state, val = energy_cache.lookup(key)
        assert state == "EXPIRED" and val is None
        state2, _ = energy_cache.lookup(key)
        assert state2 == "MISS"

    def test_tenant_journal_different_miss(self):
        energy_cache.store(energy_cache.make_key(*K), {"availability": "AVAILABLE"})
        other = ("tenant_b",) + K[1:]
        state, _ = energy_cache.lookup(energy_cache.make_key(*other))
        assert state == "MISS"

    def test_energy_tenant_different_miss(self):
        energy_cache.store(energy_cache.make_key(*K), {"availability": "AVAILABLE"})
        other = (K[0], "paas_autre") + K[2:]
        state, _ = energy_cache.lookup(energy_cache.make_key(*other))
        assert state == "MISS"

    def test_periode_differente_miss(self):
        energy_cache.store(energy_cache.make_key(*K), {"availability": "AVAILABLE"})
        other = K[:3] + ("2026-07-01", "2026-07-31", K[5])
        state, _ = energy_cache.lookup(energy_cache.make_key(*other))
        assert state == "MISS"

    def test_vehicule_different_miss(self):
        energy_cache.store(energy_cache.make_key(*K), {"availability": "AVAILABLE"})
        other = K[:2] + ("veh2|ref2",) + K[3:]
        state, _ = energy_cache.lookup(energy_cache.make_key(*other))
        assert state == "MISS"

    def test_null_reste_null(self):
        key = energy_cache.make_key(*K)
        payload = {"availability": "AVAILABLE", "metrics": {
            "fuel_liters_total": {"value": None, "unit": "L", "availability": "UNAVAILABLE",
                                  "measurement_type": None, "source": None, "timestamp": None}}}
        energy_cache.store(key, payload)
        _, val = energy_cache.lookup(key)
        assert val["metrics"]["fuel_liters_total"]["value"] is None  # jamais 0

    def test_erreur_energy_jamais_conservee_au_ttl_normal(self, monkeypatch):
        key = energy_cache.make_key(*K)
        for reason in ("energy_unreachable", "energy_not_connected", "energy_invalid_response"):
            energy_cache.clear()
            ttl = energy_cache.store(key, {"availability": "UNAVAILABLE",
                                           "reason": reason, "metrics": None})
            assert ttl == energy_cache.ERROR_TTL_SECONDS
            assert ttl < energy_cache.TTL_SECONDS, "erreur jamais conservée au TTL normal"
        # au-delà du TTL erreur → EXPIRED, même si le TTL normal (60 s) court encore
        energy_cache.clear()
        monkeypatch.setattr(energy_cache, "ERROR_TTL_SECONDS", 0.05)
        energy_cache.store(key, {"availability": "UNAVAILABLE",
                                 "reason": "energy_unreachable", "metrics": None})
        time.sleep(0.1)
        state, _ = energy_cache.lookup(key)
        assert state == "EXPIRED"

    def test_token_jamais_logge(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="energy_cache"):
            key = energy_cache.make_key(*K)
            energy_cache.lookup(key)
            energy_cache.store(key, {"availability": "AVAILABLE"})
            energy_cache.lookup(key)
            energy_cache.mark_bypass(key)
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "HIT" in text and "MISS" in text and "BYPASS" in text
        if ENERGY_TOKEN:
            assert ENERGY_TOKEN not in text
        assert "Bearer" not in text


# ---------------------------------------------------------------------------
# Partie B — e2e backend live (Energy réel)
# ---------------------------------------------------------------------------
class TestCacheE2E:
    @pytest.fixture(scope="class")
    def warm(self, admin_h):
        """MISS initial sur période inédite, puis HIT — réponses conservées."""
        dfrom, dto = _fresh_period()
        p = {"date_from": dfrom, "date_to": dto}
        r1 = requests.get(PREVIEW_URL, headers=admin_h, params=p, timeout=120)
        assert r1.status_code == 200
        r2 = requests.get(PREVIEW_URL, headers=admin_h, params=p, timeout=120)
        assert r2.status_code == 200
        return {"period": p, "miss": r1.json(), "hit": r2.json()}

    def test_miss_initial_e2e(self, warm):
        c = warm["miss"]["cache"]
        assert c["miss"] >= 18, f"MISS attendu sur période inédite : {c}"
        # seul le status /health (clé sans période) peut déjà être en cache
        assert c["bypass"] == 0 and c["hit"] <= 1
        assert c["ttl_seconds"] == 60 and c["persistent"] is False

    def test_hit_dans_ttl_e2e(self, warm):
        c = warm["hit"]["cache"]
        assert c["hit"] >= 18, f"HIT attendu au 2e appel : {c}"
        assert c["miss"] == 0 and c["bypass"] == 0

    def test_rows_strictement_identiques_depuis_cache(self, warm):
        """null reste null, STALE reste STALE, measurement_type/source/timestamp
        inchangés : les rows HIT sont STRICTEMENT égales aux rows MISS."""
        assert warm["hit"]["rows"] == warm["miss"]["rows"]

    def test_null_jamais_zero_e2e(self, warm):
        for tag in ("miss", "hit"):
            for row in warm[tag]["rows"]:
                cf = row.get("consumed_fuel")
                if cf is not None and cf.get("availability") == "UNAVAILABLE":
                    assert cf.get("value") is None
        # au moins un véhicule sans consommation → None conservé dans les deux
        none_miss = [r["vehicle_id"] for r in warm["miss"]["rows"] if r["consumed_fuel"] is None]
        none_hit = [r["vehicle_id"] for r in warm["hit"]["rows"] if r["consumed_fuel"] is None]
        assert none_miss == none_hit

    def test_metriques_intactes_e2e(self, warm):
        for m, h in zip(warm["miss"]["rows"], warm["hit"]["rows"]):
            for field in ("consumed_fuel", "consumed_electric"):
                a, b = m.get(field), h.get(field)
                assert a == b
                if a:
                    for k in ("value", "availability", "measurement_type", "source", "timestamp"):
                        assert a.get(k) == b.get(k)
            assert m["consumption_measurement_type"] == h["consumption_measurement_type"]

    def test_stale_conserve_e2e(self, admin_h):
        """Période campagne août 2026 : si un row est STALE côté Energy, il doit
        rester STALE (+ MEASURED) après passage par le cache."""
        p = {"date_from": "2026-08-01", "date_to": "2026-08-31"}
        r1 = requests.get(PREVIEW_URL, headers=admin_h, params=p, timeout=120).json()
        r2 = requests.get(PREVIEW_URL, headers=admin_h, params=p, timeout=120).json()
        stales = [r for r in r1["rows"]
                  if r.get("consumed_fuel") and r["consumed_fuel"].get("availability") == "STALE"]
        if not stales:
            pytest.skip("Aucune mesure STALE réelle sur la période — rien à vérifier")
        by_id = {r["vehicle_id"]: r for r in r2["rows"]}
        for row in stales:
            again = by_id[row["vehicle_id"]]["consumed_fuel"]
            assert again["availability"] == "STALE"
            assert again["measurement_type"] == row["consumed_fuel"]["measurement_type"]

    def test_refresh_bypass_e2e(self, warm, admin_h):
        r = requests.get(PREVIEW_URL, headers=admin_h,
                         params={**warm["period"], "refresh": "true"}, timeout=120)
        assert r.status_code == 200
        c = r.json()["cache"]
        assert c["bypass"] >= 18, f"refresh doit BYPASS le cache : {c}"
        assert c["hit"] == 0 and c["miss"] == 0

    def test_periode_differente_miss_e2e(self, admin_h):
        dfrom, dto = _fresh_period()
        r = requests.get(PREVIEW_URL, headers=admin_h,
                         params={"date_from": dfrom, "date_to": dto}, timeout=120)
        assert r.json()["cache"]["miss"] >= 18

    def test_vehicule_different_miss_e2e(self, admin_h):
        """Clé par véhicule : chauffer v1 seul ne chauffe pas v2."""
        vids = [r["vehicle_id"] for r in requests.get(
            PREVIEW_URL, headers=admin_h, timeout=120).json()["rows"]]
        assert len(vids) >= 2
        dfrom, dto = _fresh_period()
        p = {"date_from": dfrom, "date_to": dto}
        requests.get(PREVIEW_URL, headers=admin_h,
                     params={**p, "vehicle_id": vids[0]}, timeout=120)
        c2 = requests.get(PREVIEW_URL, headers=admin_h,
                          params={**p, "vehicle_id": vids[1]}, timeout=120).json()["cache"]
        assert c2["miss"] >= 1, f"v2 ne doit pas hériter du cache de v1 : {c2}"

    def test_fail_closed_tenant_b_aucun_cache_vehicule(self, admin_b_h):
        """Tenant B sans mapping Energy : NOT_CONFIGURED, aucun summary véhicule
        demandé ni caché (seul le health non tenant-specific est compté)."""
        r = requests.get(PREVIEW_URL, headers=admin_b_h, timeout=60)
        assert r.status_code == 200
        body = r.json()
        assert body["connected"] is False
        for row in body["rows"]:
            assert row["consumed_fuel"] is None and row["consumed_electric"] is None
            assert row["status"] == "IMPOSSIBLE"
        c = body["cache"]
        assert c["hit"] + c["miss"] + c["expired"] <= 1, \
            f"tenant non mappé : aucune entrée cache véhicule attendue : {c}"
        assert c["bypass"] == 0

    def test_isolation_tenant_b_ne_recupere_jamais_tenant_a(self, warm, admin_b_h):
        """Cache tenant default chaud → tenant B sur la MÊME période n'obtient rien."""
        r = requests.get(PREVIEW_URL, headers=admin_b_h, params=warm["period"], timeout=60)
        body = r.json()
        assert body["connected"] is False
        assert all(row["consumed_fuel"] is None for row in body["rows"])
        assert body["cache"]["hit"] + body["cache"]["miss"] <= 1

    def test_xlsx_reutilise_cache_preview(self, admin_h):
        """preview MISS → XLSX immédiat = rapide (cache réutilisé, pas de refetch)."""
        dfrom, dto = _fresh_period()
        p = {"date_from": dfrom, "date_to": dto}
        t0 = time.monotonic()
        requests.get(PREVIEW_URL, headers=admin_h, params=p, timeout=120)
        miss_s = time.monotonic() - t0
        t1 = time.monotonic()
        r = requests.get(XLSX_URL, headers=admin_h, params=p, timeout=120)
        xlsx_s = time.monotonic() - t1
        assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
        assert xlsx_s < max(miss_s * 0.6, 4.0), \
            f"XLSX doit réutiliser le cache : preview={miss_s:.1f}s xlsx={xlsx_s:.1f}s"

    def test_pdf_reutilise_cache_preview(self, admin_h):
        dfrom, dto = _fresh_period()
        p = {"date_from": dfrom, "date_to": dto}
        t0 = time.monotonic()
        requests.get(PREVIEW_URL, headers=admin_h, params=p, timeout=120)
        miss_s = time.monotonic() - t0
        t1 = time.monotonic()
        r = requests.get(PDF_URL, headers=admin_h, params=p, timeout=120)
        pdf_s = time.monotonic() - t1
        assert r.status_code == 200 and "pdf" in r.headers["content-type"]
        assert pdf_s < max(miss_s * 0.6, 4.0), \
            f"PDF doit réutiliser le cache : preview={miss_s:.1f}s pdf={pdf_s:.1f}s"

    def test_token_absent_des_logs_backend(self, admin_h):
        if not ENERGY_TOKEN:
            pytest.skip("ENERGY_API_TOKEN non configuré")
        requests.get(PREVIEW_URL, headers=admin_h, timeout=120)
        found = False
        for path in ("/var/log/supervisor/backend.err.log",
                     "/var/log/supervisor/backend.out.log"):
            try:
                with open(path, "rb") as f:
                    f.seek(0, 2)
                    f.seek(max(0, f.tell() - 500_000))
                    tail = f.read().decode(errors="replace")
                found = True
                assert ENERGY_TOKEN not in tail, f"token Energy présent dans {path}"
            except FileNotFoundError:
                continue
        if not found:
            pytest.skip("Logs supervisor introuvables")
