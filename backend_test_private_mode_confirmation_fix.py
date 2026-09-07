#!/usr/bin/env python3
"""
Backend test for Private Mode REAL CONFIRMATION FIX validation.

CONTEXT: Refactored confirmation logic so REAL device commands that aren't immediately
confirmed become PENDING_CONFIRMATION (not FAILED), resolved asynchronously via telemetry.
New engine states: PENDING_CONFIRMATION, SRC_TELEMETRY, SRC_UNCONFIRMED, SRC_SIMULATED.
New helper: resolve_pending_confirmation().
GET /driver/private-mode now returns: pending, confirmation_source, private_distance_km.

TEST ENV: PRIVATE_MODE_ENABLED NOT set (fail-closed), DEVICE_WRITE=0 (no real commands).

TESTS:
1. GET /api/livre/driver/private-mode (driver): feature disabled -> allowed=false, 
   reason="PRIVATE_MODE_FEATURE_DISABLED"
2. POST /api/livre/driver/private-mode {"mode":"PRIVATE"} (driver): feature disabled -> 
   403 "PRIVATE_MODE_FEATURE_DISABLED" (NOT 500, NOT FAILED)
3. Admin kill switch endpoints: POST /api/livre/private-mode/kill-switch, 
   GET /api/livre/private-mode/status
4. Import/health: backend healthy, no 500 on any private-mode endpoint
5. Security: NO secrets (navixy_hash, api_key, credential, token, Bearer, Navixy, 
   Teltonika, AVL, privatemode, raw_command, SIMULATED_CONFIRMED), NO GPS coords
6. Non-regression: /api/auth/me, /api/livre/dashboard, /api/livre/trips, 
   /api/livre/vehicles -> 200

Credentials: admin@logitrak.ch / admin123, chauffeur@logitrak.ch / chauffeur123
Backend URL: https://confidentialite-flag.preview.emergentagent.com
"""

import httpx
import json
import sys
from typing import Optional

# Backend URL from environment
BACKEND_URL = "https://confidentialite-flag.preview.emergentagent.com"
BASE_URL = f"{BACKEND_URL}/api/livre"

# Test credentials
ADMIN_EMAIL = "admin@logitrak.ch"
ADMIN_PASSWORD = "admin123"
DRIVER_EMAIL = "chauffeur@logitrak.ch"
DRIVER_PASSWORD = "chauffeur123"

# Security forbidden strings (must NOT appear in any response)
FORBIDDEN_STRINGS = [
    "navixy_hash", "api_key", "credential", "Bearer", "token",
    "Navixy", "Teltonika", "AVL", "privatemode", "raw_command",
    "SIMULATED_CONFIRMED", "11813", "11000", "INTEGRATION_ENCRYPTION_KEY",
]

# GPS coordinate patterns (must NOT appear in driver responses)
GPS_PATTERNS = ["lat", "lng", "latitude", "longitude", "address", "coordinates", "position"]

# Test results
test_results = []
security_issues = []


def log_test(name: str, passed: bool, details: str = ""):
    """Log a test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    test_results.append({"name": name, "passed": passed, "details": details})
    print(f"{status}: {name}")
    if details:
        print(f"  {details}")


def check_security(response_text: str, response_json: dict, context: str):
    """Check for security issues in response."""
    # Check forbidden strings
    for forbidden in FORBIDDEN_STRINGS:
        if forbidden.lower() in response_text.lower():
            issue = f"SECURITY LEAK in {context}: Found forbidden string '{forbidden}'"
            security_issues.append(issue)
            print(f"  ⚠️  {issue}")
    
    # Check GPS coordinates in driver responses (only for driver endpoints)
    if "driver" in context.lower():
        response_str = json.dumps(response_json).lower()
        for pattern in GPS_PATTERNS:
            # Check if pattern exists with a non-null value
            if f'"{pattern}":' in response_str:
                # Extract value after the pattern
                idx = response_str.find(f'"{pattern}":')
                value_part = response_str[idx:idx+100]
                # If value is not null/None, it's a leak
                if not any(x in value_part for x in [':null', ':none', ':"null"', ':""']):
                    issue = f"SECURITY LEAK in {context}: GPS data '{pattern}' may be exposed"
                    security_issues.append(issue)
                    print(f"  ⚠️  {issue}")


async def login(email: str, password: str) -> Optional[str]:
    """Login and return JWT token."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(
                f"{BACKEND_URL}/api/auth/login",
                json={"email": email, "password": password}
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("access_token")
            else:
                print(f"Login failed for {email}: {resp.status_code} {resp.text}")
                return None
        except Exception as e:
            print(f"Login error for {email}: {e}")
            return None


async def test_1_driver_get_private_mode_feature_disabled():
    """Test 1: GET /driver/private-mode with feature disabled -> allowed=false, 
    reason='PRIVATE_MODE_FEATURE_DISABLED'"""
    print("\n=== TEST 1: GET /driver/private-mode (feature disabled) ===")
    
    token = await login(DRIVER_EMAIL, DRIVER_PASSWORD)
    if not token:
        log_test("Test 1: Driver login", False, "Failed to login")
        return
    
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(
                f"{BASE_URL}/driver/private-mode",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            # Should return 200 with allowed=false
            if resp.status_code != 200:
                log_test("Test 1: GET /driver/private-mode status code", False, 
                        f"Expected 200, got {resp.status_code}")
                return
            
            data = resp.json()
            check_security(resp.text, data, "Test 1: GET /driver/private-mode")
            
            # Check allowed=false
            if data.get("allowed") is not False:
                log_test("Test 1: allowed field", False, 
                        f"Expected allowed=false, got {data.get('allowed')}")
                return
            
            # Check reason='PRIVATE_MODE_FEATURE_DISABLED'
            reason = data.get("reason")
            if reason != "PRIVATE_MODE_FEATURE_DISABLED":
                log_test("Test 1: reason field", False, 
                        f"Expected 'PRIVATE_MODE_FEATURE_DISABLED', got '{reason}'")
                return
            
            # Verify new fields are present (may be null/false when disabled)
            new_fields = ["pending", "confirmation_source", "private_distance_km"]
            for field in new_fields:
                if field not in data:
                    print(f"  ℹ️  Note: New field '{field}' not present (acceptable when disabled)")
            
            log_test("Test 1: GET /driver/private-mode (feature disabled)", True,
                    f"allowed=false, reason={reason}, state={data.get('state')}")
            
        except Exception as e:
            log_test("Test 1: GET /driver/private-mode", False, f"Exception: {e}")


async def test_2_driver_post_private_mode_feature_disabled():
    """Test 2: POST /driver/private-mode with feature disabled -> 403 
    'PRIVATE_MODE_FEATURE_DISABLED'"""
    print("\n=== TEST 2: POST /driver/private-mode (feature disabled) ===")
    
    token = await login(DRIVER_EMAIL, DRIVER_PASSWORD)
    if not token:
        log_test("Test 2: Driver login", False, "Failed to login")
        return
    
    async with httpx.AsyncClient(timeout=30) as client:
        # Test 2a: POST mode=PRIVATE
        try:
            resp = await client.post(
                f"{BASE_URL}/driver/private-mode",
                headers={"Authorization": f"Bearer {token}"},
                json={"mode": "PRIVATE"}
            )
            
            # Should return 403 (NOT 200, NOT 500)
            if resp.status_code != 403:
                log_test("Test 2a: POST PRIVATE status code", False, 
                        f"Expected 403, got {resp.status_code}")
            else:
                data = resp.json()
                check_security(resp.text, data, "Test 2a: POST PRIVATE")
                
                detail = data.get("detail", "")
                if "PRIVATE_MODE_FEATURE_DISABLED" not in detail:
                    log_test("Test 2a: POST PRIVATE detail", False, 
                            f"Expected 'PRIVATE_MODE_FEATURE_DISABLED' in detail, got '{detail}'")
                else:
                    log_test("Test 2a: POST PRIVATE (feature disabled)", True,
                            f"403 with detail={detail}")
        except Exception as e:
            log_test("Test 2a: POST PRIVATE", False, f"Exception: {e}")
        
        # Test 2b: POST mode=BUSINESS
        try:
            resp = await client.post(
                f"{BASE_URL}/driver/private-mode",
                headers={"Authorization": f"Bearer {token}"},
                json={"mode": "BUSINESS"}
            )
            
            if resp.status_code != 403:
                log_test("Test 2b: POST BUSINESS status code", False, 
                        f"Expected 403, got {resp.status_code}")
            else:
                data = resp.json()
                check_security(resp.text, data, "Test 2b: POST BUSINESS")
                
                detail = data.get("detail", "")
                if "PRIVATE_MODE_FEATURE_DISABLED" not in detail:
                    log_test("Test 2b: POST BUSINESS detail", False, 
                            f"Expected 'PRIVATE_MODE_FEATURE_DISABLED' in detail, got '{detail}'")
                else:
                    log_test("Test 2b: POST BUSINESS (feature disabled)", True,
                            f"403 with detail={detail}")
        except Exception as e:
            log_test("Test 2b: POST BUSINESS", False, f"Exception: {e}")
        
        # Test 2c: POST mode=XXX (invalid)
        try:
            resp = await client.post(
                f"{BASE_URL}/driver/private-mode",
                headers={"Authorization": f"Bearer {token}"},
                json={"mode": "XXX"}
            )
            
            # Should return 400 (invalid mode)
            if resp.status_code != 400:
                log_test("Test 2c: POST invalid mode status code", False, 
                        f"Expected 400, got {resp.status_code}")
            else:
                log_test("Test 2c: POST invalid mode", True, "400 for invalid mode")
        except Exception as e:
            log_test("Test 2c: POST invalid mode", False, f"Exception: {e}")


async def test_3_admin_kill_switch():
    """Test 3: Admin kill switch endpoints"""
    print("\n=== TEST 3: Admin kill switch endpoints ===")
    
    admin_token = await login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        log_test("Test 3: Admin login", False, "Failed to login")
        return
    
    driver_token = await login(DRIVER_EMAIL, DRIVER_PASSWORD)
    
    async with httpx.AsyncClient(timeout=30) as client:
        # Test 3a: POST kill-switch active=true (admin)
        try:
            resp = await client.post(
                f"{BASE_URL}/private-mode/kill-switch",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"active": True}
            )
            
            if resp.status_code != 200:
                log_test("Test 3a: POST kill-switch active=true", False, 
                        f"Expected 200, got {resp.status_code}")
            else:
                data = resp.json()
                check_security(resp.text, data, "Test 3a: POST kill-switch")
                
                if data.get("kill_switch") is not True:
                    log_test("Test 3a: kill_switch field", False, 
                            f"Expected kill_switch=true, got {data.get('kill_switch')}")
                else:
                    log_test("Test 3a: POST kill-switch active=true", True,
                            f"kill_switch={data.get('kill_switch')}")
        except Exception as e:
            log_test("Test 3a: POST kill-switch active=true", False, f"Exception: {e}")
        
        # Test 3b: GET status (admin)
        try:
            resp = await client.get(
                f"{BASE_URL}/private-mode/status",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            
            if resp.status_code != 200:
                log_test("Test 3b: GET status", False, 
                        f"Expected 200, got {resp.status_code}")
            else:
                data = resp.json()
                check_security(resp.text, data, "Test 3b: GET status")
                
                if data.get("kill_switch_active") is not True:
                    log_test("Test 3b: kill_switch_active field", False, 
                            f"Expected kill_switch_active=true, got {data.get('kill_switch_active')}")
                else:
                    log_test("Test 3b: GET status (kill switch active)", True,
                            f"feature_enabled={data.get('feature_enabled')}, "
                            f"kill_switch_active={data.get('kill_switch_active')}")
        except Exception as e:
            log_test("Test 3b: GET status", False, f"Exception: {e}")
        
        # Test 3c: POST kill-switch active=false (admin)
        try:
            resp = await client.post(
                f"{BASE_URL}/private-mode/kill-switch",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"active": False}
            )
            
            if resp.status_code != 200:
                log_test("Test 3c: POST kill-switch active=false", False, 
                        f"Expected 200, got {resp.status_code}")
            else:
                data = resp.json()
                check_security(resp.text, data, "Test 3c: POST kill-switch")
                
                if data.get("kill_switch") is not False:
                    log_test("Test 3c: kill_switch field", False, 
                            f"Expected kill_switch=false, got {data.get('kill_switch')}")
                else:
                    log_test("Test 3c: POST kill-switch active=false", True,
                            f"kill_switch={data.get('kill_switch')}")
        except Exception as e:
            log_test("Test 3c: POST kill-switch active=false", False, f"Exception: {e}")
        
        # Test 3d: Driver cannot access admin endpoints (403)
        if driver_token:
            try:
                resp = await client.get(
                    f"{BASE_URL}/private-mode/status",
                    headers={"Authorization": f"Bearer {driver_token}"}
                )
                
                if resp.status_code != 403:
                    log_test("Test 3d: Driver GET status (should be 403)", False, 
                            f"Expected 403, got {resp.status_code}")
                else:
                    log_test("Test 3d: Driver GET status (403)", True, "Driver blocked from admin endpoint")
            except Exception as e:
                log_test("Test 3d: Driver GET status", False, f"Exception: {e}")
            
            try:
                resp = await client.post(
                    f"{BASE_URL}/private-mode/kill-switch",
                    headers={"Authorization": f"Bearer {driver_token}"},
                    json={"active": True}
                )
                
                if resp.status_code != 403:
                    log_test("Test 3e: Driver POST kill-switch (should be 403)", False, 
                            f"Expected 403, got {resp.status_code}")
                else:
                    log_test("Test 3e: Driver POST kill-switch (403)", True, "Driver blocked from admin endpoint")
            except Exception as e:
                log_test("Test 3e: Driver POST kill-switch", False, f"Exception: {e}")


async def test_4_import_health():
    """Test 4: Backend healthy, no 500 on any private-mode endpoint"""
    print("\n=== TEST 4: Import/Health check ===")
    
    # If endpoints respond with 200/403/400 (not 500), imports are OK
    all_ok = True
    for result in test_results:
        if "500" in result.get("details", ""):
            all_ok = False
            break
    
    if all_ok:
        log_test("Test 4: Import/Health (no 500 errors)", True,
                "All private-mode endpoints responded without 500 errors")
    else:
        log_test("Test 4: Import/Health", False,
                "Some endpoints returned 500 errors")


async def test_5_security():
    """Test 5: Security - no secrets, no GPS coords"""
    print("\n=== TEST 5: Security verification ===")
    
    if security_issues:
        log_test("Test 5: Security", False, 
                f"Found {len(security_issues)} security issues")
        for issue in security_issues:
            print(f"  - {issue}")
    else:
        log_test("Test 5: Security", True,
                "No secrets or GPS coordinates leaked in any response")


async def test_6_non_regression():
    """Test 6: Non-regression - other endpoints still work"""
    print("\n=== TEST 6: Non-regression ===")
    
    admin_token = await login(ADMIN_EMAIL, ADMIN_PASSWORD)
    driver_token = await login(DRIVER_EMAIL, DRIVER_PASSWORD)
    
    if not admin_token or not driver_token:
        log_test("Test 6: Login", False, "Failed to login")
        return
    
    async with httpx.AsyncClient(timeout=30) as client:
        # Test 6a: GET /auth/me (admin)
        try:
            resp = await client.get(
                f"{BACKEND_URL}/api/auth/me",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            
            if resp.status_code != 200:
                log_test("Test 6a: GET /auth/me (admin)", False, 
                        f"Expected 200, got {resp.status_code}")
            else:
                log_test("Test 6a: GET /auth/me (admin)", True, "200 OK")
        except Exception as e:
            log_test("Test 6a: GET /auth/me (admin)", False, f"Exception: {e}")
        
        # Test 6b: GET /auth/me (driver)
        try:
            resp = await client.get(
                f"{BACKEND_URL}/api/auth/me",
                headers={"Authorization": f"Bearer {driver_token}"}
            )
            
            if resp.status_code != 200:
                log_test("Test 6b: GET /auth/me (driver)", False, 
                        f"Expected 200, got {resp.status_code}")
            else:
                log_test("Test 6b: GET /auth/me (driver)", True, "200 OK")
        except Exception as e:
            log_test("Test 6b: GET /auth/me (driver)", False, f"Exception: {e}")
        
        # Test 6c: GET /livre/dashboard
        try:
            resp = await client.get(
                f"{BASE_URL}/dashboard",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            
            if resp.status_code != 200:
                log_test("Test 6c: GET /dashboard", False, 
                        f"Expected 200, got {resp.status_code}")
            else:
                log_test("Test 6c: GET /dashboard", True, "200 OK")
        except Exception as e:
            log_test("Test 6c: GET /dashboard", False, f"Exception: {e}")
        
        # Test 6d: GET /livre/trips
        try:
            resp = await client.get(
                f"{BASE_URL}/trips",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            
            if resp.status_code != 200:
                log_test("Test 6d: GET /trips", False, 
                        f"Expected 200, got {resp.status_code}")
            else:
                data = resp.json()
                # Check if any trip has private_redacted=true with null coords
                trips = data.get("trips", [])
                private_trips = [t for t in trips if t.get("private_redacted") is True]
                if private_trips:
                    # Verify null coords/addresses
                    for trip in private_trips[:3]:  # Check first 3
                        if any(trip.get(k) is not None for k in 
                               ["start_lat", "start_lng", "start_address", "end_address"]):
                            log_test("Test 6d: GET /trips (private redaction)", False,
                                    "Private trip has non-null coordinates/addresses")
                            break
                    else:
                        log_test("Test 6d: GET /trips", True, 
                                f"200 OK, {len(private_trips)} private trips with null coords")
                else:
                    log_test("Test 6d: GET /trips", True, "200 OK")
        except Exception as e:
            log_test("Test 6d: GET /trips", False, f"Exception: {e}")
        
        # Test 6e: GET /livre/vehicles
        try:
            resp = await client.get(
                f"{BASE_URL}/vehicles",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            
            if resp.status_code != 200:
                log_test("Test 6e: GET /vehicles", False, 
                        f"Expected 200, got {resp.status_code}")
            else:
                log_test("Test 6e: GET /vehicles", True, "200 OK")
        except Exception as e:
            log_test("Test 6e: GET /vehicles", False, f"Exception: {e}")


async def main():
    """Run all tests."""
    print("=" * 80)
    print("PRIVATE MODE REAL CONFIRMATION FIX - Backend Validation")
    print("=" * 80)
    print(f"Backend URL: {BACKEND_URL}")
    print(f"Admin: {ADMIN_EMAIL}")
    print(f"Driver: {DRIVER_EMAIL}")
    print()
    
    # Run all tests
    await test_1_driver_get_private_mode_feature_disabled()
    await test_2_driver_post_private_mode_feature_disabled()
    await test_3_admin_kill_switch()
    await test_4_import_health()
    await test_5_security()
    await test_6_non_regression()
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for r in test_results if r["passed"])
    total = len(test_results)
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if security_issues:
        print(f"\n⚠️  SECURITY ISSUES: {len(security_issues)}")
        for issue in security_issues:
            print(f"  - {issue}")
    else:
        print("\n✅ NO SECURITY ISSUES")
    
    # Failed tests
    failed = [r for r in test_results if not r["passed"]]
    if failed:
        print(f"\n❌ FAILED TESTS ({len(failed)}):")
        for r in failed:
            print(f"  - {r['name']}: {r['details']}")
    else:
        print("\n✅ ALL TESTS PASSED")
    
    print("\n" + "=" * 80)
    
    # Exit code
    sys.exit(0 if passed == total and not security_issues else 1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
