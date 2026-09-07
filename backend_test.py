#!/usr/bin/env python3
"""Backend API test suite for Private Mode authorization layer.

Tests the newly added Private Mode security/authorization endpoints:
- GET /api/livre/driver/private-mode (driver auth)
- POST /api/livre/driver/private-mode (driver auth)
- GET /api/livre/private-mode/status (admin auth)
- POST /api/livre/private-mode/kill-switch (admin auth)

Security checks:
- No secrets/credentials in responses
- Fail-closed by default (PRIVATE_MODE_ENABLED not set)
- Proper HTTP status codes for authorization failures

Non-regression:
- Existing endpoints still work (auth, dashboard, trips, vehicles, drivers)
"""
import os
import sys
import requests
import json
from typing import Optional

# Base URL from environment
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://confidentialite-flag.preview.emergentagent.com")
API_BASE = f"{BASE_URL}/api"

# Test credentials
ADMIN_EMAIL = "admin@logitrak.ch"
ADMIN_PASSWORD = "admin123"
DRIVER_EMAIL = "chauffeur@logitrak.ch"
DRIVER_PASSWORD = "chauffeur123"

# Color codes for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.failures = []
        self.security_issues = []

    def pass_test(self, name: str):
        self.passed += 1
        print(f"{GREEN}✓{RESET} {name}")

    def fail_test(self, name: str, reason: str):
        self.failed += 1
        self.failures.append(f"{name}: {reason}")
        print(f"{RED}✗{RESET} {name}")
        print(f"  {RED}Reason: {reason}{RESET}")

    def warn(self, message: str):
        self.warnings += 1
        print(f"{YELLOW}⚠{RESET} {message}")

    def security_issue(self, message: str):
        self.security_issues.append(message)
        print(f"{RED}🔒 SECURITY ISSUE: {message}{RESET}")

    def summary(self):
        print(f"\n{'='*70}")
        print(f"TEST SUMMARY")
        print(f"{'='*70}")
        print(f"{GREEN}Passed:{RESET} {self.passed}")
        print(f"{RED}Failed:{RESET} {self.failed}")
        print(f"{YELLOW}Warnings:{RESET} {self.warnings}")
        
        if self.security_issues:
            print(f"\n{RED}SECURITY ISSUES ({len(self.security_issues)}):{RESET}")
            for issue in self.security_issues:
                print(f"  {RED}•{RESET} {issue}")
        
        if self.failures:
            print(f"\n{RED}FAILURES:{RESET}")
            for failure in self.failures:
                print(f"  {RED}•{RESET} {failure}")
        
        print(f"{'='*70}\n")
        return self.failed == 0 and len(self.security_issues) == 0


def login(email: str, password: str) -> Optional[str]:
    """Login and return access token."""
    try:
        response = requests.post(
            f"{API_BASE}/auth/login",
            json={"email": email, "password": password},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("access_token")
        else:
            print(f"{RED}Login failed for {email}: {response.status_code}{RESET}")
            return None
    except Exception as e:
        print(f"{RED}Login error for {email}: {e}{RESET}")
        return None


def check_for_secrets(data: dict, test_name: str, result: TestResult) -> bool:
    """Check if response contains any secrets/credentials."""
    data_str = json.dumps(data).lower()
    forbidden_keys = ["navixy_hash", "api_key", "credential", "token", "password", "secret"]
    
    found_secrets = []
    for key in forbidden_keys:
        if key in data_str:
            found_secrets.append(key)
    
    if found_secrets:
        result.security_issue(f"{test_name}: Response contains forbidden keys: {', '.join(found_secrets)}")
        return False
    return True


def test_driver_private_mode_get(driver_token: str, result: TestResult):
    """Test GET /api/livre/driver/private-mode (driver auth)."""
    print(f"\n{BLUE}Testing GET /api/livre/driver/private-mode (driver auth){RESET}")
    
    try:
        response = requests.get(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "GET /api/livre/driver/private-mode",
                f"Expected 200, got {response.status_code}: {response.text[:200]}"
            )
            return
        
        data = response.json()
        
        # Check required fields
        required_fields = ["state", "allowed", "reason", "vehicle_id", "tracker_id", 
                          "private_odometer_supported", "last_transition_at"]
        missing_fields = [f for f in required_fields if f not in data]
        
        if missing_fields:
            result.fail_test(
                "GET /api/livre/driver/private-mode - response structure",
                f"Missing fields: {', '.join(missing_fields)}"
            )
            return
        
        # Check fail-closed: with default env (PRIVATE_MODE_ENABLED not set), allowed MUST be false
        if data.get("allowed") is not False:
            result.fail_test(
                "GET /api/livre/driver/private-mode - fail-closed",
                f"Expected allowed=false (feature disabled by default), got allowed={data.get('allowed')}"
            )
            return
        
        # Check reason is PRIVATE_MODE_FEATURE_DISABLED
        if data.get("reason") != "PRIVATE_MODE_FEATURE_DISABLED":
            result.fail_test(
                "GET /api/livre/driver/private-mode - reason",
                f"Expected reason='PRIVATE_MODE_FEATURE_DISABLED', got reason='{data.get('reason')}'"
            )
            return
        
        # Check no GPS coordinates/address/lat/lng in response
        forbidden_geo_keys = ["lat", "lng", "latitude", "longitude", "address", "coordinates", "position"]
        data_str = json.dumps(data).lower()
        found_geo = [k for k in forbidden_geo_keys if k in data_str]
        
        if found_geo:
            result.security_issue(
                f"GET /api/livre/driver/private-mode: Response contains geo data: {', '.join(found_geo)}"
            )
            return
        
        # Check for secrets
        if not check_for_secrets(data, "GET /api/livre/driver/private-mode", result):
            return
        
        result.pass_test("GET /api/livre/driver/private-mode - returns correct fail-closed response")
        
    except Exception as e:
        result.fail_test("GET /api/livre/driver/private-mode", f"Exception: {str(e)}")


def test_driver_private_mode_post(driver_token: str, result: TestResult):
    """Test POST /api/livre/driver/private-mode (driver auth)."""
    print(f"\n{BLUE}Testing POST /api/livre/driver/private-mode (driver auth){RESET}")
    
    # Test 1: Try to set PRIVATE mode (should be refused with 403)
    try:
        response = requests.post(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"mode": "PRIVATE"},
            timeout=10
        )
        
        if response.status_code != 403:
            result.fail_test(
                "POST /api/livre/driver/private-mode (PRIVATE) - HTTP status",
                f"Expected 403 (feature disabled), got {response.status_code}: {response.text[:200]}"
            )
        else:
            data = response.json()
            detail = data.get("detail", "")
            if "PRIVATE_MODE_FEATURE_DISABLED" not in detail:
                result.fail_test(
                    "POST /api/livre/driver/private-mode (PRIVATE) - error detail",
                    f"Expected detail containing 'PRIVATE_MODE_FEATURE_DISABLED', got: {detail}"
                )
            else:
                result.pass_test("POST /api/livre/driver/private-mode (PRIVATE) - correctly refused with 403")
    except Exception as e:
        result.fail_test("POST /api/livre/driver/private-mode (PRIVATE)", f"Exception: {str(e)}")
    
    # Test 2: Try to set BUSINESS mode (should also be refused with 403)
    try:
        response = requests.post(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"mode": "BUSINESS"},
            timeout=10
        )
        
        if response.status_code != 403:
            result.fail_test(
                "POST /api/livre/driver/private-mode (BUSINESS) - HTTP status",
                f"Expected 403 (feature disabled), got {response.status_code}: {response.text[:200]}"
            )
        else:
            result.pass_test("POST /api/livre/driver/private-mode (BUSINESS) - correctly refused with 403")
    except Exception as e:
        result.fail_test("POST /api/livre/driver/private-mode (BUSINESS)", f"Exception: {str(e)}")
    
    # Test 3: Try invalid mode "XXX" (should return 400)
    try:
        response = requests.post(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"mode": "XXX"},
            timeout=10
        )
        
        if response.status_code != 400:
            result.fail_test(
                "POST /api/livre/driver/private-mode (mode=XXX) - HTTP status",
                f"Expected 400, got {response.status_code}: {response.text[:200]}"
            )
        else:
            result.pass_test("POST /api/livre/driver/private-mode (mode=XXX) - correctly rejected with 400")
    except Exception as e:
        result.fail_test("POST /api/livre/driver/private-mode (mode=XXX)", f"Exception: {str(e)}")


def test_admin_private_mode_status(admin_token: str, result: TestResult):
    """Test GET /api/livre/private-mode/status (admin auth)."""
    print(f"\n{BLUE}Testing GET /api/livre/private-mode/status (admin auth){RESET}")
    
    try:
        response = requests.get(
            f"{API_BASE}/livre/private-mode/status",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "GET /api/livre/private-mode/status",
                f"Expected 200, got {response.status_code}: {response.text[:200]}"
            )
            return
        
        data = response.json()
        
        # Check required fields
        required_fields = ["feature_enabled", "kill_switch_active"]
        missing_fields = [f for f in required_fields if f not in data]
        
        if missing_fields:
            result.fail_test(
                "GET /api/livre/private-mode/status - response structure",
                f"Missing fields: {', '.join(missing_fields)}"
            )
            return
        
        # Check feature_enabled is false (default)
        if data.get("feature_enabled") is not False:
            result.warn(
                f"GET /api/livre/private-mode/status: feature_enabled={data.get('feature_enabled')} "
                "(expected false by default, but may be set in env)"
            )
        
        # Check for secrets
        if not check_for_secrets(data, "GET /api/livre/private-mode/status", result):
            return
        
        result.pass_test("GET /api/livre/private-mode/status - returns correct status")
        
    except Exception as e:
        result.fail_test("GET /api/livre/private-mode/status", f"Exception: {str(e)}")


def test_admin_kill_switch(admin_token: str, result: TestResult):
    """Test POST /api/livre/private-mode/kill-switch (admin auth)."""
    print(f"\n{BLUE}Testing POST /api/livre/private-mode/kill-switch (admin auth){RESET}")
    
    # Test 1: Activate kill switch
    try:
        response = requests.post(
            f"{API_BASE}/livre/private-mode/kill-switch",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"active": True},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "POST /api/livre/private-mode/kill-switch (activate)",
                f"Expected 200, got {response.status_code}: {response.text[:200]}"
            )
            return
        
        data = response.json()
        if data.get("kill_switch") is not True:
            result.fail_test(
                "POST /api/livre/private-mode/kill-switch (activate) - response",
                f"Expected kill_switch=true, got {data.get('kill_switch')}"
            )
            return
        
        result.pass_test("POST /api/livre/private-mode/kill-switch (activate) - success")
        
    except Exception as e:
        result.fail_test("POST /api/livre/private-mode/kill-switch (activate)", f"Exception: {str(e)}")
        return
    
    # Test 2: Verify kill switch is active in status
    try:
        response = requests.get(
            f"{API_BASE}/livre/private-mode/status",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("kill_switch_active") is not True:
                result.fail_test(
                    "GET /api/livre/private-mode/status (after activation)",
                    f"Expected kill_switch_active=true, got {data.get('kill_switch_active')}"
                )
            else:
                result.pass_test("GET /api/livre/private-mode/status - kill switch active confirmed")
        else:
            result.fail_test(
                "GET /api/livre/private-mode/status (after activation)",
                f"Expected 200, got {response.status_code}"
            )
    except Exception as e:
        result.fail_test("GET /api/livre/private-mode/status (after activation)", f"Exception: {str(e)}")
    
    # Test 3: Deactivate kill switch
    try:
        response = requests.post(
            f"{API_BASE}/livre/private-mode/kill-switch",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"active": False},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "POST /api/livre/private-mode/kill-switch (deactivate)",
                f"Expected 200, got {response.status_code}: {response.text[:200]}"
            )
            return
        
        data = response.json()
        if data.get("kill_switch") is not False:
            result.fail_test(
                "POST /api/livre/private-mode/kill-switch (deactivate) - response",
                f"Expected kill_switch=false, got {data.get('kill_switch')}"
            )
            return
        
        result.pass_test("POST /api/livre/private-mode/kill-switch (deactivate) - success")
        
    except Exception as e:
        result.fail_test("POST /api/livre/private-mode/kill-switch (deactivate)", f"Exception: {str(e)}")


def test_driver_cannot_access_admin_endpoints(driver_token: str, result: TestResult):
    """Test that driver cannot access admin endpoints."""
    print(f"\n{BLUE}Testing driver cannot access admin endpoints{RESET}")
    
    # Test 1: Driver tries to get status
    try:
        response = requests.get(
            f"{API_BASE}/livre/private-mode/status",
            headers={"Authorization": f"Bearer {driver_token}"},
            timeout=10
        )
        
        if response.status_code == 403:
            result.pass_test("Driver cannot access GET /api/livre/private-mode/status (403)")
        else:
            result.fail_test(
                "Driver access to GET /api/livre/private-mode/status",
                f"Expected 403, got {response.status_code}"
            )
    except Exception as e:
        result.fail_test("Driver access to GET /api/livre/private-mode/status", f"Exception: {str(e)}")
    
    # Test 2: Driver tries to set kill switch
    try:
        response = requests.post(
            f"{API_BASE}/livre/private-mode/kill-switch",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"active": True},
            timeout=10
        )
        
        if response.status_code == 403:
            result.pass_test("Driver cannot access POST /api/livre/private-mode/kill-switch (403)")
        else:
            result.fail_test(
                "Driver access to POST /api/livre/private-mode/kill-switch",
                f"Expected 403, got {response.status_code}"
            )
    except Exception as e:
        result.fail_test("Driver access to POST /api/livre/private-mode/kill-switch", f"Exception: {str(e)}")


def test_non_regression(admin_token: str, driver_token: str, result: TestResult):
    """Test that existing endpoints still work."""
    print(f"\n{BLUE}Testing non-regression endpoints{RESET}")
    
    endpoints = [
        ("GET /api/auth/me (admin)", f"{API_BASE}/auth/me", admin_token),
        ("GET /api/auth/me (driver)", f"{API_BASE}/auth/me", driver_token),
        ("GET /api/livre/dashboard", f"{API_BASE}/livre/dashboard", admin_token),
        ("GET /api/livre/trips", f"{API_BASE}/livre/trips", admin_token),
        ("GET /api/livre/vehicles", f"{API_BASE}/livre/vehicles", admin_token),
        ("GET /api/livre/drivers", f"{API_BASE}/livre/drivers", admin_token),
    ]
    
    for name, url, token in endpoints:
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                # Basic sanity check - response should be valid JSON
                if isinstance(data, (dict, list)):
                    result.pass_test(f"{name} - returns 200 with valid JSON")
                else:
                    result.fail_test(f"{name}", f"Invalid response type: {type(data)}")
            else:
                result.fail_test(f"{name}", f"Expected 200, got {response.status_code}: {response.text[:200]}")
        except Exception as e:
            result.fail_test(f"{name}", f"Exception: {str(e)}")


def main():
    print(f"\n{'='*70}")
    print(f"BACKEND API TEST - Private Mode Authorization Layer")
    print(f"{'='*70}")
    print(f"Base URL: {BASE_URL}")
    print(f"API Base: {API_BASE}")
    print(f"{'='*70}\n")
    
    result = TestResult()
    
    # Login
    print(f"{BLUE}Logging in...{RESET}")
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    driver_token = login(DRIVER_EMAIL, DRIVER_PASSWORD)
    
    if not admin_token:
        print(f"{RED}Failed to login as admin. Aborting tests.{RESET}")
        sys.exit(1)
    
    if not driver_token:
        print(f"{RED}Failed to login as driver. Aborting tests.{RESET}")
        sys.exit(1)
    
    print(f"{GREEN}✓ Admin login successful{RESET}")
    print(f"{GREEN}✓ Driver login successful{RESET}")
    
    # Run tests
    test_driver_private_mode_get(driver_token, result)
    test_driver_private_mode_post(driver_token, result)
    test_admin_private_mode_status(admin_token, result)
    test_admin_kill_switch(admin_token, result)
    test_driver_cannot_access_admin_endpoints(driver_token, result)
    test_non_regression(admin_token, driver_token, result)
    
    # Summary
    success = result.summary()
    
    if success:
        print(f"{GREEN}All tests passed!{RESET}")
        sys.exit(0)
    else:
        print(f"{RED}Some tests failed. See details above.{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
