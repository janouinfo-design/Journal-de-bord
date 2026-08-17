#!/usr/bin/env python3
"""
Backend API Test Suite for Logitrak Chauffeur Proxy
Tests local routes and reverse proxy functionality
"""
import requests
import json
from datetime import datetime

# Backend URL from frontend/.env
BASE_URL = "https://driver-fleet-ble.preview.emergentagent.com/api"

def print_test_header(test_name):
    print(f"\n{'='*80}")
    print(f"TEST: {test_name}")
    print('='*80)

def print_result(status_code, response_body, expected_status=None):
    print(f"Status Code: {status_code}")
    print(f"Response Body: {json.dumps(response_body, indent=2) if isinstance(response_body, dict) else response_body}")
    if expected_status:
        result = "✅ PASS" if status_code == expected_status else "❌ FAIL"
        print(f"Expected: {expected_status} | Result: {result}")

def test_non_regression():
    """Test existing local routes still work"""
    
    # Test 1: GET /api/
    print_test_header("NON-REGRESSION: GET /api/")
    try:
        resp = requests.get(f"{BASE_URL}/", timeout=10)
        body = resp.json()
        print_result(resp.status_code, body, 200)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert body.get("message") == "Hello World", f"Expected 'Hello World', got {body}"
        print("✅ PASS: Root endpoint returns correct message")
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False
    
    # Test 2: POST /api/status
    print_test_header("NON-REGRESSION: POST /api/status")
    try:
        test_client = f"proxy-test-{datetime.now().timestamp()}"
        payload = {"client_name": test_client}
        resp = requests.post(f"{BASE_URL}/status", json=payload, timeout=10)
        body = resp.json()
        print_result(resp.status_code, body, 200)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert "id" in body, "Response missing 'id' field"
        assert body.get("client_name") == test_client, f"Expected client_name '{test_client}', got {body.get('client_name')}"
        assert "timestamp" in body, "Response missing 'timestamp' field"
        print("✅ PASS: Status creation returns correct object with id, client_name, timestamp")
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False
    
    # Test 3: GET /api/status
    print_test_header("NON-REGRESSION: GET /api/status")
    try:
        resp = requests.get(f"{BASE_URL}/status", timeout=10)
        body = resp.json()
        print_result(resp.status_code, body, 200)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert isinstance(body, list), f"Expected list, got {type(body)}"
        print(f"✅ PASS: Status list returns array with {len(body)} items")
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False
    
    return True

def test_proxy_auth():
    """Test proxy forwards auth requests to upstream"""
    
    print_test_header("PROXY AUTH: POST /api/auth/login (wrong credentials)")
    try:
        payload = {"email": "test@logitrak.ch", "password": "wrong"}
        resp = requests.post(f"{BASE_URL}/auth/login", json=payload, timeout=10)
        body = resp.json()
        print_result(resp.status_code, body, 401)
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        assert "detail" in body, "Response missing 'detail' field"
        # Check for French error message from real upstream
        detail = body.get("detail", "")
        assert "mot de passe" in detail.lower() or "email" in detail.lower(), \
            f"Expected French error message, got: {detail}"
        print(f"✅ PASS: Proxy forwards to upstream and returns real 401 error: '{detail}'")
        return True
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False

def test_proxy_livre_no_auth():
    """Test proxy forwards livre requests and enforces auth"""
    
    # Test 1: GET /api/livre/driver/current-session without Authorization
    print_test_header("PROXY LIVRE: GET /api/livre/driver/current-session (no auth)")
    try:
        resp = requests.get(f"{BASE_URL}/livre/driver/current-session", timeout=10)
        body = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text
        print_result(resp.status_code, body, 401)
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("✅ PASS: Upstream enforces authentication (401)")
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False
    
    # Test 2: GET /api/livre/driver/fleet-tags with fake token
    print_test_header("PROXY LIVRE: GET /api/livre/driver/fleet-tags (fake token)")
    try:
        headers = {"Authorization": "Bearer faketoken"}
        resp = requests.get(f"{BASE_URL}/livre/driver/fleet-tags", headers=headers, timeout=10)
        body = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text
        print_result(resp.status_code, body, 401)
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        if isinstance(body, dict) and "detail" in body:
            detail = body.get("detail", "")
            print(f"✅ PASS: Upstream rejects fake token with: '{detail}'")
        else:
            print("✅ PASS: Upstream rejects fake token (401)")
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False
    
    return True

def test_proxy_scoping():
    """Test proxy only forwards allowed namespaces"""
    
    # Test 1: GET /api/random/unknownpath should return 404
    print_test_header("PROXY SCOPING: GET /api/random/unknownpath (should be 404)")
    try:
        resp = requests.get(f"{BASE_URL}/random/unknownpath", timeout=10)
        body = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text
        print_result(resp.status_code, body, 404)
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        print("✅ PASS: Unknown namespace returns 404 (not proxied)")
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False
    
    # Test 2: Verify GET /api/status is NOT proxied (returns local data)
    print_test_header("PROXY SCOPING: GET /api/status (should be local, not proxied)")
    try:
        resp = requests.get(f"{BASE_URL}/status", timeout=10)
        body = resp.json()
        print_result(resp.status_code, body, 200)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert isinstance(body, list), f"Expected list (local response), got {type(body)}"
        print("✅ PASS: /api/status returns local Mongo-backed array (not proxied)")
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False
    
    return True

def main():
    print("\n" + "="*80)
    print("LOGITRAK CHAUFFEUR BACKEND API TEST SUITE")
    print("="*80)
    print(f"Testing backend at: {BASE_URL}")
    print(f"Started at: {datetime.now().isoformat()}")
    
    results = {
        "NON-REGRESSION": test_non_regression(),
        "PROXY AUTH": test_proxy_auth(),
        "PROXY LIVRE": test_proxy_livre_no_auth(),
        "PROXY SCOPING": test_proxy_scoping(),
    }
    
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name}: {status}")
    
    all_passed = all(results.values())
    print("\n" + "="*80)
    if all_passed:
        print("🎉 ALL TESTS PASSED")
    else:
        print("⚠️  SOME TESTS FAILED")
    print("="*80)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    exit(main())
