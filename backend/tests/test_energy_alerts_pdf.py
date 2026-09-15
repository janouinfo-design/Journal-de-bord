"""Préparation alertes « À contrôler » (verrou REAL ENERGY) + Export PDF — tests.

ENVOI ALERTES RÉELLES : DÉSACTIVÉ — aucun test n'envoie d'e-mail/SMS/push.
Energy réel : NON TESTÉ (URL manquante) — mode par défaut non connecté.
Les données insérées directement en base utilisent des tenants/clés TEST
explicites, nettoyées en fin de module — jamais de données opérationnelles.
"""
from __future__ import annotations

import os

import fitz  # PyMuPDF — validation réelle des PDF générés
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

frontend_env = dotenv_values("/app/frontend/.env")
backend_env = dotenv_values("/app/backend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = backend_env.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = backend_env.get("DB_NAME") or os.environ.get("DB_NAME")

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
MANAGER = {"email": "manager@logitrak.ch", "password": "manager123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}
LECTURE = {"email": "lecture@logitrak.ch", "password": "lecture123"}
ADMIN_B = {"email": "admin-b@test.ch", "password": "testb123"}

CONFIG_URL = f"{API}/livre/energy/reconciliation/alerts/config"
CAND_URL = f"{API}/livre/energy/reconciliation/alerts/candidates"
GEN_URL = f"{API}/livre/energy/reconciliation/alerts/candidates/generate"
PDF_URL = f"{API}/livre/energy/reconciliation/export.pdf"
PARAMS_YEAR = {"date_from": "2026-01-01", "date_to": "2026-12-31"}

TEST_TENANT = "__test_alerts__"
TEST_KEY_PREFIX = "recon-alert:TEST"


def _login(creds) -> dict:
    r = requests.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login {creds['email']}: {r.status_code}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_h():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def manager_h():
    return _login(MANAGER)


@pytest.fixture(scope="module")
def driver_h():
    return _login(DRIVER)


@pytest.fixture(scope="module")
def lecture_h():
    return _login(LECTURE)


@pytest.fixture(scope="module")
def admin_b_h():
    return _login(ADMIN_B)


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module", autouse=True)
def cleanup(admin_h, admin_b_h, mongo):
    """Fin de module : destinataires vides, aucune donnée TEST résiduelle."""
    yield
    requests.put(CONFIG_URL, json={"recipients": []}, headers=admin_h, timeout=20)
    requests.put(CONFIG_URL, json={"recipients": []}, headers=admin_b_h, timeout=20)
    mongo.reconciliation_alert_candidates.delete_many({"tenant_id": TEST_TENANT})
    mongo.reconciliation_alert_candidates.delete_many(
        {"dedup_key": {"$regex": f"^{TEST_KEY_PREFIX}"}})


# ---------------------------------------------------------------------------
# Verrou d'activation des alertes — real_energy_validated=false par tenant
# ---------------------------------------------------------------------------
class TestAlertsLockConfig:
    def test_default_locked_disabled(self, admin_h):
        r = requests.get(CONFIG_URL, headers=admin_h, timeout=20)
        assert r.status_code == 200
        b = r.json()
        assert b["enabled"] is False
        assert b["real_energy_validated"] is False
        assert b["dispatch"] == "disabled"
        assert b["can_enable"] is False
        assert "REAL ENERGY" in b["lock_reason"]
        assert b["preview_note"] == "APERÇU — AUCUN MESSAGE ENVOYÉ"

    def test_enable_refused_409(self, admin_h):
        r = requests.put(CONFIG_URL, json={"enabled": True}, headers=admin_h, timeout=20)
        assert r.status_code == 409
        assert "REAL ENERGY" in r.json()["detail"]
        b = requests.get(CONFIG_URL, headers=admin_h, timeout=20).json()
        assert b["enabled"] is False, "la tentative refusée ne doit rien activer"

    def test_enable_refused_for_manager_too(self, manager_h):
        r = requests.put(CONFIG_URL, json={"enabled": True}, headers=manager_h, timeout=20)
        assert r.status_code == 409

    def test_disable_is_allowed_noop(self, admin_h):
        r = requests.put(CONFIG_URL, json={"enabled": False}, headers=admin_h, timeout=20)
        assert r.status_code == 200
        assert r.json()["enabled"] is False

    def test_real_energy_validated_never_writable(self, admin_h):
        # Champ hors modèle : ignoré (aucun endpoint ne peut le passer à true)
        r = requests.put(CONFIG_URL, json={"real_energy_validated": True},
                         headers=admin_h, timeout=20)
        assert r.status_code == 200
        b = requests.get(CONFIG_URL, headers=admin_h, timeout=20).json()
        assert b["real_energy_validated"] is False
        # Le verrou tient toujours
        r = requests.put(CONFIG_URL, json={"enabled": True}, headers=admin_h, timeout=20)
        assert r.status_code == 409

    def test_recipients_saved_normalized_no_send(self, admin_h):
        r = requests.put(CONFIG_URL, json={
            "recipients": ["Futur.Contact@Logitrak.CH", "flotte@logitrak.ch",
                           "flotte@logitrak.ch"]}, headers=admin_h, timeout=20)
        assert r.status_code == 200
        b = r.json()
        assert b["recipients"] == ["futur.contact@logitrak.ch", "flotte@logitrak.ch"]
        assert b["dispatch"] == "disabled"
        assert b["enabled"] is False

    def test_recipients_invalid_rejected(self, admin_h):
        for bad in (["pas-un-email"], ["a@b"], ["ok@logitrak.ch", ""]):
            r = requests.put(CONFIG_URL, json={"recipients": bad},
                             headers=admin_h, timeout=20)
            assert r.status_code == 400, f"{bad} aurait dû être rejeté"

    def test_recipients_max_20(self, admin_h):
        many = [f"user{i}@logitrak.ch" for i in range(21)]
        r = requests.put(CONFIG_URL, json={"recipients": many}, headers=admin_h, timeout=20)
        assert r.status_code == 400

    def test_rbac(self, driver_h, lecture_h):
        assert requests.get(CONFIG_URL, headers=driver_h, timeout=20).status_code == 403
        assert requests.put(CONFIG_URL, json={"recipients": []},
                            headers=driver_h, timeout=20).status_code == 403
        assert requests.get(CONFIG_URL, headers=lecture_h, timeout=20).status_code == 200
        assert requests.put(CONFIG_URL, json={"recipients": []},
                            headers=lecture_h, timeout=20).status_code == 403

    def test_tenant_isolation(self, admin_h, admin_b_h):
        b = requests.get(CONFIG_URL, headers=admin_b_h, timeout=20).json()
        assert b["recipients"] == [], "tenant B n'hérite pas des destinataires du tenant default"
        requests.put(CONFIG_URL, json={"recipients": ["contact-b@test.ch"]},
                     headers=admin_b_h, timeout=20)
        assert "contact-b@test.ch" not in requests.get(
            CONFIG_URL, headers=admin_h, timeout=20).json()["recipients"]
        assert requests.get(CONFIG_URL, headers=admin_b_h,
                            timeout=20).json()["recipients"] == ["contact-b@test.ch"]

    def test_config_change_audited(self, admin_h):
        r = requests.get(f"{API}/livre/audit-log", params={"limit": 50},
                         headers=admin_h, timeout=20)
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        hits = [e for e in items
                if e.get("action") == "energy.reconciliation_alerts.config_update"]
        assert hits, "chaque modification de configuration doit être auditée"
        assert hits[0]["details"].get("dispatch") == "disabled"


# ---------------------------------------------------------------------------
# Candidats d'alerte — génération, filtrage strict MEASURED, anti-doublonnage
# ---------------------------------------------------------------------------
def _recon_row(status="A_CONTROLER", mt="MEASURED", mapped=True, vid="veh-test-1"):
    return {"vehicle_id": vid, "plate": "TT 1234", "model": "Test", "mapped": mapped,
            "consumption_measurement_type": mt, "status": status,
            "gap_l": 30.0, "gap_pct": 12.0, "status_reason": "test"}


class TestCandidateBuilder:
    def _build(self, rows):
        from app.routes.energy import _alert_candidates
        return _alert_candidates(rows, "2026-01-01", "2026-01-31")

    def test_a_controler_measured_is_candidate(self):
        out = self._build([_recon_row()])
        assert len(out) == 1
        assert out[0]["dedup_key"] == "recon-alert:veh-test-1:2026-01-01:2026-01-31"
        assert out[0]["measurement_type"] == "MEASURED"

    def test_estimated_never_candidate(self):
        assert self._build([_recon_row(status="INDICATIF", mt="ESTIMATED")]) == []

    def test_reference_never_candidate(self):
        assert self._build([_recon_row(status="INDICATIF", mt="REFERENCE")]) == []

    def test_impossible_none_never_candidate(self):
        assert self._build([_recon_row(status="IMPOSSIBLE", mt="NONE")]) == []

    def test_ok_never_candidate(self):
        assert self._build([_recon_row(status="OK")]) == []

    def test_defense_a_controler_non_measured_excluded(self):
        assert self._build([_recon_row(mt="ESTIMATED")]) == []

    def test_unmapped_never_candidate(self):
        assert self._build([_recon_row(mapped=False)]) == []


class TestCandidatesApi:
    def test_generate_not_connected_zero(self, admin_h):
        r = requests.post(GEN_URL, params=PARAMS_YEAR, headers=admin_h, timeout=120)
        assert r.status_code == 200
        b = r.json()
        assert b["preview"] is True
        assert b["dispatch"] == "disabled"
        assert b["note"] == "APERÇU — AUCUN MESSAGE ENVOYÉ"
        if b["mode"] == "not_connected":
            assert b["candidates"] == 0 and b["created"] == 0, \
                "non connecté → aucune consommation MEASURED → aucun candidat"

    def test_generate_idempotent(self, admin_h):
        r1 = requests.post(GEN_URL, params=PARAMS_YEAR, headers=admin_h, timeout=120)
        r2 = requests.post(GEN_URL, params=PARAMS_YEAR, headers=admin_h, timeout=120)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r2.json()["created"] == 0, "seconde génération : aucun doublon créé"

    def test_list_shape(self, admin_h):
        r = requests.get(CAND_URL, headers=admin_h, timeout=20)
        assert r.status_code == 200
        b = r.json()
        assert b["preview"] is True and b["dispatch"] == "disabled"
        assert b["note"] == "APERÇU — AUCUN MESSAGE ENVOYÉ"
        assert isinstance(b["items"], list)

    def test_rbac(self, driver_h, lecture_h):
        assert requests.post(GEN_URL, headers=driver_h, timeout=30).status_code == 403
        assert requests.get(CAND_URL, headers=driver_h, timeout=20).status_code == 403
        assert requests.post(GEN_URL, headers=lecture_h, timeout=30).status_code == 403
        assert requests.get(CAND_URL, headers=lecture_h, timeout=20).status_code == 200

    def test_generation_audited(self, admin_h):
        r = requests.get(f"{API}/livre/audit-log", params={"limit": 50},
                         headers=admin_h, timeout=20)
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        hits = [e for e in items
                if e.get("action") == "energy.reconciliation_alerts.candidates_generate"]
        assert hits
        assert hits[0]["details"].get("dispatch") == "disabled"

    def test_dedup_unique_index(self, mongo):
        """L'index unique (tenant_id, dedup_key) bloque physiquement les doublons."""
        coll = mongo.reconciliation_alert_candidates
        doc = {"tenant_id": TEST_TENANT,
               "dedup_key": f"{TEST_KEY_PREFIX}:veh:2026-01-01:2026-01-31",
               "vehicle_id": "TESTVEH", "preview_only": True, "dispatched": False}
        coll.delete_many({"tenant_id": TEST_TENANT})
        coll.insert_one(dict(doc))
        with pytest.raises(DuplicateKeyError):
            coll.insert_one(dict(doc))
        # même clé, autre tenant : autorisé (dédoublonnage PAR tenant)
        coll.insert_one({**doc, "tenant_id": TEST_TENANT + "2"})
        coll.delete_many({"tenant_id": {"$in": [TEST_TENANT, TEST_TENANT + "2"]}})

    def test_candidates_tenant_isolation(self, mongo, admin_h, admin_b_h):
        tenant_b = mongo.users.find_one({"email": ADMIN_B["email"]})["tenant_id"]
        doc = {"tenant_id": tenant_b, "id": "test-iso-cand",
               "dedup_key": f"{TEST_KEY_PREFIX}:ISO:2026-01-01:2026-01-31",
               "vehicle_id": "TEST-ISO", "plate": "TEST-ISO", "preview_only": True,
               "dispatched": False, "created_at": "2026-01-01T00:00:00+00:00"}
        mongo.reconciliation_alert_candidates.insert_one(doc)
        try:
            ids_b = {i["id"] for i in requests.get(
                CAND_URL, headers=admin_b_h, timeout=20).json()["items"]}
            ids_default = {i["id"] for i in requests.get(
                CAND_URL, headers=admin_h, timeout=20).json()["items"]}
            assert "test-iso-cand" in ids_b
            assert "test-iso-cand" not in ids_default, \
                "un candidat du tenant B ne doit jamais fuiter vers le tenant default"
        finally:
            mongo.reconciliation_alert_candidates.delete_one({"id": "test-iso-cand"})

    def test_no_dispatch_to_notifications(self, mongo, admin_h):
        """Aucune génération de candidat ne doit créer d'entrée notifications_log."""
        before = mongo.notifications_log.count_documents({})
        requests.post(GEN_URL, params=PARAMS_YEAR, headers=admin_h, timeout=120)
        after = mongo.notifications_log.count_documents({})
        assert after == before, "la préparation d'alertes ne doit RIEN dispatcher"


# ---------------------------------------------------------------------------
# Export PDF — e2e (Energy non connecté)
# ---------------------------------------------------------------------------
def _pdf_text(content: bytes) -> str:
    """Texte du PDF, espaces normalisés (les cellules étroites coupent les mots)."""
    d = fitz.open(stream=content, filetype="pdf")
    return " ".join("".join(p.get_text() for p in d).split())


def _export_pdf(headers, extra=None):
    return requests.get(PDF_URL, params={**PARAMS_YEAR, **(extra or {})},
                        headers=headers, timeout=120)


@pytest.fixture(scope="module")
def preview(admin_h):
    r = requests.get(f"{API}/livre/energy/reconciliation/preview",
                     params=PARAMS_YEAR, headers=admin_h, timeout=120)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def pdf_default(admin_h):
    r = _export_pdf(admin_h)
    assert r.status_code == 200
    return r


class TestPdfExportE2E:
    def test_headers_and_openable(self, pdf_default):
        assert pdf_default.headers["content-type"] == "application/pdf"
        assert "rapprochement_carburant_2026-01-01_2026-12-31.pdf" \
            in pdf_default.headers["content-disposition"]
        d = fitz.open(stream=pdf_default.content, filetype="pdf")
        assert d.page_count >= 1

    def test_metadata_and_disclaimers(self, pdf_default, preview):
        text = _pdf_text(pdf_default.content)
        assert "Rapprochement achats / consommation" in text
        assert "Période : 2026-01-01 au 2026-12-31" in text
        assert "Alertes automatiques : désactivées" in text
        if not preview["connected"]:
            assert "Module Énergie non connecté" in text
        assert "jamais assimilée à zéro" in text

    def test_all_18_vehicles_including_unmapped(self, pdf_default, preview):
        text = _pdf_text(pdf_default.content)
        plates = [r["plate"] for r in preview["rows"] if r.get("plate")]
        assert len(preview["rows"]) == 18
        for p in plates:
            assert p in text, f"plaque {p} absente du PDF"
        assert "Non mappé" in text, "les véhicules non mappés doivent rester visibles"

    def test_disconnected_all_impossible_never_zero(self, pdf_default, preview):
        if preview["mode"] != "not_connected":
            pytest.skip("mode fixture actif")
        text = _pdf_text(pdf_default.content)
        assert "Impossible" in text
        assert "Aucun" in text  # type de mesure NONE → « Aucun »
        assert "—" in text     # null → tiret, jamais 0
        assert "None" not in text

    def test_filter_vehicle(self, admin_h, preview):
        row = preview["rows"][0]
        other = preview["rows"][1]
        text = _pdf_text(_export_pdf(admin_h, {"vehicle_id": row["vehicle_id"]}).content)
        assert row["plate"] in text
        assert other["plate"] not in text
        assert f"véhicule = {row['vehicle_id']}" in text  # filtre affiché

    def test_filter_measurement_measured_disconnected(self, admin_h, preview):
        if preview["mode"] != "not_connected":
            pytest.skip("mode fixture actif")
        text = _pdf_text(_export_pdf(admin_h, {"measurement": "MEASURED"}).content)
        assert "Aucun véhicule ne correspond aux filtres." in text
        for r in preview["rows"]:
            if r.get("plate"):
                assert r["plate"] not in text

    def test_filter_status(self, admin_h):
        r = _export_pdf(admin_h, {"status": "A_CONTROLER"})
        assert r.status_code == 200

    def test_rbac(self, driver_h, lecture_h):
        assert _export_pdf(driver_h).status_code == 403
        assert _export_pdf(lecture_h).status_code == 200

    def test_tenant_isolation(self, admin_b_h, preview):
        r = _export_pdf(admin_b_h)
        assert r.status_code == 200
        text = _pdf_text(r.content)
        for row in preview["rows"]:
            if row.get("plate"):
                assert row["plate"] not in text

    def test_idor_vehicle_param(self, admin_b_h, preview):
        vid = preview["rows"][0]["vehicle_id"]
        text = _pdf_text(_export_pdf(admin_b_h, {"vehicle_id": vid}).content)
        assert preview["rows"][0]["plate"] not in text
        assert "Aucun véhicule ne correspond aux filtres." in text

    def test_pdf_export_audited(self, admin_h):
        r = requests.get(f"{API}/livre/audit-log", params={"limit": 50},
                         headers=admin_h, timeout=20)
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        hits = [e for e in items if e.get("action") == "energy.reconciliation.export"
                and e.get("details", {}).get("format") == "pdf"]
        assert hits, "l'export PDF doit être audité avec format=pdf"


# ---------------------------------------------------------------------------
# Fonction PDF (directe, lignes synthétiques TEST) — null, PHEV, pagination
# ---------------------------------------------------------------------------
def _pdf_row(i=1, **over):
    base = {
        "vehicle_id": f"veh-{i}", "plate": f"TT {1000 + i}", "model": f"Modèle {i}",
        "navixy_tracker_id": 111, "mapped": True, "powertrain": "ICE",
        "purchased": {"liters": 45.0, "kwh": 0.0, "amount_chf": 80.0,
                      "tx_count": 2, "sources": {"csv": 2}},
        "consumed_fuel": {"value": 40.0, "unit": "L", "availability": "AVAILABLE",
                          "measurement_type": "MEASURED", "source": "OBD", "timestamp": None},
        "consumed_electric": None,
        "consumption_measurement_type": "MEASURED", "gap_l": 5.0, "gap_pct": 11.1,
        "reliability": "EXPLOITABLE", "status": "OK", "status_reason": "Test",
    }
    base.update(over)
    return base


_PDF_META = {"tenant": "TEST", "period_from": "2026-01-01", "period_to": "2026-01-31",
             "generated_at": "01/01/2026 00:00 UTC", "filters": [],
             "mode": "not_connected", "connected": False,
             "thresholds": {"configured": False}}


class TestPdfFunction:
    def _text(self, rows):
        from app.reports import reconciliation_to_pdf
        return _pdf_text(reconciliation_to_pdf(rows, dict(_PDF_META)))

    def test_pdf_num_null_dash_zero_kept(self):
        from app.reports import _pdf_num
        assert _pdf_num(None) == "—"
        assert _pdf_num("") == "—"
        assert _pdf_num(0) == "0.00", "un zéro réellement fourni reste un zéro"
        assert _pdf_num(12.345, 1) == "12.3"

    def test_null_consumption_shows_dash(self):
        text = self._text([_pdf_row(consumed_fuel=None, gap_l=None, gap_pct=None,
                                    consumption_measurement_type="NONE",
                                    reliability="IMPOSSIBLE", status="IMPOSSIBLE",
                                    purchased={"liters": 0.0, "kwh": 0.0,
                                               "amount_chf": 0.0, "tx_count": 0,
                                               "sources": {}})])
        assert "—" in text
        assert "None" not in text
        assert "Impossible" in text

    def test_phev_liters_and_kwh_separated(self):
        row = _pdf_row(powertrain="PHEV",
                       purchased={"liters": 45.0, "kwh": 12.3, "amount_chf": 90.0,
                                  "tx_count": 3, "sources": {"card": 3}},
                       consumed_electric={"value": 8.4, "unit": "kWh",
                                          "availability": "AVAILABLE",
                                          "measurement_type": "MEASURED",
                                          "source": "OBD", "timestamp": None})
        text = self._text([row])
        assert "45.00" in text   # litres achetés
        assert "12.30" in text   # kWh achetés — colonne séparée
        assert "8.40" in text    # kWh consommés — jamais fusionnés avec les litres
        assert "Hybride rechargeable" in text

    def test_estimated_labelled(self):
        row = _pdf_row(consumption_measurement_type="ESTIMATED",
                       consumed_fuel={"value": 41.0, "unit": "L",
                                      "availability": "AVAILABLE",
                                      "measurement_type": "ESTIMATED",
                                      "source": "ENERGY_MODEL", "timestamp": None},
                       reliability="INDICATIF", status="INDICATIF")
        text = self._text([row])
        assert "Estimé" in text and "Indicatif" in text

    def test_pagination_with_repeated_header(self):
        from app.reports import reconciliation_to_pdf
        rows = [_pdf_row(i) for i in range(120)]
        d = fitz.open(stream=reconciliation_to_pdf(rows, dict(_PDF_META)), filetype="pdf")
        assert d.page_count >= 2, "120 lignes doivent produire plusieurs pages"
        assert "Raison du statut" in " ".join(d[1].get_text().split()), \
            "l'entête du tableau doit se répéter sur chaque page"
        assert f"Page {d.page_count}" in d[d.page_count - 1].get_text()

    def test_empty_rows_message(self):
        assert "Aucun véhicule ne correspond aux filtres." in self._text([])
