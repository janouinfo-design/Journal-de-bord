"""Regression tests after requirements.txt fix (iteration_15).

Ensures backend still runs correctly post-regeneration and multi-tenant paths remain healthy.
"""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    # Fallback: read from frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.strip().split("=", 1)[1]
                break
BASE_URL = BASE_URL.rstrip("/")


# --- Health ---
def test_health():
    r = requests.get(f"{BASE_URL}/api/health", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert data.get("service") == "journal-logitrak"


# --- Admin login (tenant default) ---
def test_login_admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "admin@logitrak.ch", "password": "admin123"},
               timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data
    assert data["user"]["email"] == "admin@logitrak.ch"
    # httpOnly cookies must be set
    assert s.cookies.get("access_token") or s.cookies.get("refresh_token")


# --- Superadmin login (tenant_id=None) ---
def test_login_superadmin_and_list_tenants():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "superadmin@logitrak.ch", "password": "superadmin123"},
               timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    token = data["access_token"]
    assert data["user"]["email"] == "superadmin@logitrak.ch"

    # List tenants
    r2 = s.get(f"{BASE_URL}/api/admin/tenants",
               headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r2.status_code == 200, r2.text
    tenants = r2.json()
    # Expect a list or object containing 'default' or Logitrak
    payload_str = str(tenants).lower()
    assert "logitrak" in payload_str or "default" in payload_str, tenants
