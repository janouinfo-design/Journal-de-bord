"""Iteration 4 — groups, companies, dashboard/trips/export filters, masked privacy, vehicle mode."""
import os
import pytest
import requests


def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not configured")


BASE = _load_backend_url()
API = f"{BASE}/api"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {email} failed {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def admin():
    return _login("admin@logitrak.ch", "admin123")


@pytest.fixture(scope="module")
def manager():
    return _login("manager@logitrak.ch", "manager123")


@pytest.fixture(scope="module")
def groups(admin):
    r = admin.get(f"{API}/livre/groups", timeout=15)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def companies(admin):
    r = admin.get(f"{API}/livre/companies", timeout=15)
    assert r.status_code == 200
    return r.json()


# ---------------- Groups & Companies endpoints ----------------
class TestGroupsCompanies:
    def test_groups_shape_nonempty(self, groups):
        assert isinstance(groups, list)
        assert len(groups) >= 1, "expected at least 1 group derived from vehicle plates"
        for g in groups:
            assert set(g.keys()) >= {"id", "name"}
            assert isinstance(g["id"], str) and g["id"]
            assert isinstance(g["name"], str) and g["name"]

    def test_companies_shape_nonempty(self, companies):
        assert isinstance(companies, list)
        assert len(companies) >= 1
        ids = {c["id"] for c in companies}
        names = {c["name"] for c in companies}
        # mono-tenant: tenant_id 'default' labeled 'Logitrak'
        assert "default" in ids
        assert "Logitrak" in names

    def test_manager_can_list_groups_and_companies(self, manager):
        r1 = manager.get(f"{API}/livre/groups", timeout=15)
        r2 = manager.get(f"{API}/livre/companies", timeout=15)
        assert r1.status_code == 200 and r2.status_code == 200


# ---------------- Dashboard filters ----------------
class TestDashboardFilters:
    def test_dashboard_kpi_new_fields(self, admin):
        r = admin.get(f"{API}/livre/dashboard", timeout=20)
        assert r.status_code == 200
        d = r.json()
        kpi = d["kpi"]
        for k in ("pro_km", "perso_km", "total_km", "unclassified_km",
                  "pct_pro", "pct_perso", "pro_fuel", "perso_fuel"):
            assert k in kpi, f"missing kpi {k}"
            assert isinstance(kpi[k], (int, float)), f"{k} not numeric: {kpi[k]!r}"

    def test_dashboard_group_filter_valid_200(self, admin, groups):
        g = groups[0]["id"]
        r = admin.get(f"{API}/livre/dashboard", params={"group": g}, timeout=20)
        assert r.status_code == 200
        assert "kpi" in r.json()

    def test_dashboard_company_filter_logitrak(self, admin):
        # Both 'Logitrak' label and 'default' tenant id should resolve
        r1 = admin.get(f"{API}/livre/dashboard", params={"company": "Logitrak"}, timeout=20)
        r2 = admin.get(f"{API}/livre/dashboard", params={"company": "default"}, timeout=20)
        assert r1.status_code == 200 and r2.status_code == 200

    def test_dashboard_group_changes_results_or_at_least_valid(self, admin, groups):
        """If multiple groups exist, filter should narrow down vs no-filter total."""
        base = admin.get(f"{API}/livre/dashboard", timeout=20).json()
        total_no_filter = base["kpi"]["total_km"]
        if len(groups) >= 2:
            r = admin.get(f"{API}/livre/dashboard", params={"group": groups[0]["id"]}, timeout=20)
            assert r.status_code == 200
            filtered = r.json()["kpi"]["total_km"]
            assert filtered <= total_no_filter + 0.01, (
                f"filtered total ({filtered}) should be <= unfiltered ({total_no_filter})"
            )


# ---------------- Trips filters ----------------
class TestTripsFilters:
    def test_trips_group_filter_returns_only_matching_plates(self, admin, groups):
        g = groups[0]["id"]
        r = admin.get(f"{API}/livre/trips",
                      params={"classification": "professional", "group": g}, timeout=20)
        assert r.status_code == 200
        trips = r.json()["trips"]
        for t in trips:
            plate = t.get("vehicle_plate") or ""
            assert plate.startswith(g + " ") or plate.startswith(g), (
                f"trip vehicle_plate {plate!r} does not start with group prefix {g!r}"
            )

    def test_trips_company_logitrak_and_default(self, admin):
        r1 = admin.get(f"{API}/livre/trips", params={"company": "Logitrak"}, timeout=20)
        r2 = admin.get(f"{API}/livre/trips", params={"company": "default"}, timeout=20)
        assert r1.status_code == 200 and r2.status_code == 200
        assert isinstance(r1.json()["trips"], list)
        assert isinstance(r2.json()["trips"], list)


# ---------------- Reports export with filters ----------------
class TestExportFilters:
    @pytest.mark.parametrize("fmt,ct", [
        ("csv", "text/csv"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("pdf", "application/pdf"),
    ])
    def test_export_pro_with_filters(self, admin, groups, fmt, ct):
        g = groups[0]["id"]
        r = admin.get(f"{API}/livre/reports/export",
                      params={"classification": "professional", "fmt": fmt,
                              "group": g, "company": "Logitrak"}, timeout=30)
        assert r.status_code == 200, r.text[:200]
        assert ct in r.headers.get("content-type", ""), (
            f"unexpected content-type {r.headers.get('content-type')} for fmt={fmt}"
        )
        assert len(r.content) > 0


# ---------------- Masked privacy invariant ----------------
class TestMaskedPrivacy:
    @pytest.fixture(scope="class", autouse=True)
    def _restore(self, admin):
        # ensure starting state and restore
        admin.put(f"{API}/livre/settings", json={"mode": "masked"}, timeout=15)
        yield
        admin.put(f"{API}/livre/settings", json={"mode": "mixte"}, timeout=15)

    def test_manager_personal_trips_anonymised(self, manager):
        r = manager.get(f"{API}/livre/trips",
                        params={"classification": "personal"}, timeout=20)
        assert r.status_code == 200
        body = r.json()
        assert body["settings_mode"] == "masked"
        trips = body["trips"]
        if not trips:
            pytest.skip("no personal trips in current seed — invariant trivially true")
        forbidden = {"start_address", "end_address", "start_time", "end_time",
                     "driver_name", "vehicle_plate", "avg_speed", "max_speed",
                     "duration_min"}
        for t in trips:
            assert t.get("masked") is True, f"trip not flagged masked: {t}"
            present = set(t.keys())
            leak = forbidden & present
            assert not leak, f"masked trip leaks fields: {leak} -> {t}"
            assert set(t.keys()) <= {"id", "classification", "distance_km", "masked"}

    def test_manager_personal_export_csv_aggregate_only(self, manager):
        r = manager.get(f"{API}/livre/reports/export",
                        params={"classification": "personal", "fmt": "csv"}, timeout=30)
        assert r.status_code == 200
        text = r.content.decode("utf-8", errors="ignore")
        # CSV must not contain any real address / driver name / plate. Helper exports use '—' placeholder.
        assert "—" in text, f"expected anonymised placeholder '—' in masked CSV, got:\n{text[:500]}"
        # Count non-empty rows (header + 1 aggregate)
        rows = [ln for ln in text.splitlines() if ln.strip()]
        assert len(rows) <= 3, (
            f"masked personal export should contain only header + 1 aggregate row, got {len(rows)}:\n{text[:800]}"
        )

    def test_admin_still_sees_full_details_in_masked_mode(self, admin):
        r = admin.get(f"{API}/livre/trips",
                      params={"classification": "personal"}, timeout=20)
        assert r.status_code == 200
        trips = r.json()["trips"]
        if trips:
            t = trips[0]
            # admin must keep full visibility
            assert "start_time" in t and "driver_name" in t


# ---------------- Vehicle mode always_perso ----------------
class TestVehicleAlwaysPerso:
    def test_always_perso_reclassifies(self, admin):
        vehicles = admin.get(f"{API}/livre/vehicles", timeout=15).json()
        # pick a vehicle that currently has trips
        target = None
        for v in vehicles:
            r = admin.get(f"{API}/livre/trips",
                          params={"vehicle_id": v["id"], "limit": 1}, timeout=20)
            if r.status_code == 200 and r.json()["trips"]:
                target = v
                break
        if not target:
            pytest.skip("no vehicle with trips in seed")
        vid = target["id"]
        original_mode = target.get("mode", "mixte")
        try:
            r = admin.put(f"{API}/livre/vehicles/{vid}/mode",
                          json={"mode": "always_perso"}, timeout=60)
            assert r.status_code == 200, r.text

            # All trips of that vehicle must be 'personal'
            r_perso = admin.get(f"{API}/livre/trips",
                                params={"vehicle_id": vid,
                                        "classification": "personal", "limit": 1000}, timeout=20)
            r_pro = admin.get(f"{API}/livre/trips",
                              params={"vehicle_id": vid,
                                      "classification": "professional", "limit": 1000}, timeout=20)
            assert r_perso.status_code == 200 and r_pro.status_code == 200
            perso_trips = r_perso.json()["trips"]
            pro_trips = r_pro.json()["trips"]
            assert len(perso_trips) >= 1, "expected vehicle trips reclassified to personal"
            # NOTE: apply_rules_to_all() only re-runs the engine for auto_classified=True trips.
            # Trips that were manually overridden (auto_classified=False) are intentionally preserved.
            # So we tolerate manually-overridden pro trips, but no auto-classified pro trip should remain.
            stale_auto = [t for t in pro_trips if t.get("auto_classified") is True]
            assert len(stale_auto) == 0, (
                f"auto-classified pro trips remained after always_perso: {len(stale_auto)}"
            )
        finally:
            admin.put(f"{API}/livre/vehicles/{vid}/mode",
                      json={"mode": original_mode if original_mode in ("always_pro", "always_perso", "mixte") else "mixte"},
                      timeout=60)
