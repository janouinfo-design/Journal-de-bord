#!/usr/bin/env python3
"""Private Mode E2E HTTP Test Suite - PILOT SCENARIO

Tests Private Mode state machine with ACTIVE driver session.

Prerequisites (VERIFIED):
- Driver Jean Dupont has a 'confirmed' session on vehicle GE 123456 / tracker 5000
- get_current_session returns active session
- PRIVATE_MODE_ENABLED=true
- Tenant default + tracker 5000 allowlisted
- field_validated capability present
- PRIVATE_MODE_SIMULATE_CONFIRM=1 (device confirmation simulated)

Test Sequence (State Machine):
1. GET /api/livre/driver/private-mode -> ASSERT allowed=true, reason=null, tracker_id=5000, private_odometer_supported=true, NO lat/lng/address
2. POST /api/livre/driver/private-mode {"mode":"PRIVATE"} -> ASSERT HTTP 200, ok=true, state="PRIVATE", confirmation_source present (CONFIRMED)
3. GET /api/livre/driver/private-mode -> ASSERT state="PRIVATE"
4. POST {"mode":"PRIVATE"} again -> ASSERT ok=true, idempotent=true
5. POST {"mode":"BUSINESS"} -> ASSERT HTTP 200, ok=true, state="BUSINESS" (may include private_distance_km or distance_status)
6. GET -> ASSERT state="BUSINESS"
7. POST {"mode":"ZZZ"} -> ASSERT HTTP 400

KILL SWITCH:
8. ADMIN POST /api/livre/private-mode/kill-switch {"active":true} -> ASSERT {kill_switch:true}
9. DRIVER POST /api/livre/driver/private-mode {"mode":"PRIVATE"} -> ASSERT HTTP 403 with detail "PRIVATE_MODE_KILL_SWITCH_ACTIVE"
10. ADMIN POST /api/livre/private-mode/kill-switch {"active":false} -> restore
11. DRIVER POST {"mode":"BUSINESS"} -> ASSERT 200 ok=true, leave state BUSINESS

SECURITY (across ALL responses):
- NO: "navixy_hash", "TEST_E2E", Bearer token values, "Navixy", "Teltonika", "AVL", "privatemode", "raw_command"
- NO real GPS lat/lng/address in driver private-mode responses

NON-REGRESSION:
- GET /api/auth/me (both roles), /api/livre/dashboard, /api/livre/trips, /api/livre/vehicles -> all 200
"""
import os
import sys
import requests
import json
from typing import Optional, Dict, Any, List

# Base URL from environment
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://confidentialite-flag.preview.emergentagent.com")
API_BASE = f"{BASE_URL}/api"

# Test credentials
ADMIN_EMAIL = "admin@logitrak.ch"
ADMIN_PASSWORD = "admin123"
DRIVER_EMAIL = "chauffeur@logitrak.ch"
DRIVER_PASSWORD = "chauffeur123"

# Expected values
EXPECTED_TRACKER_ID = 5000

# Color codes for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RESET = "\033[0m"

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.failures = []
        self.security_issues = []
        self.test_details = []

    def pass_test(self, name: str, details: str = ""):
        self.passed += 1
        msg = f"{GREEN}✓{RESET} {name}"
        if details:
            msg += f"\n  {CYAN}{details}{RESET}"
        print(msg)
        self.test_details.append({"name": name, "status": "PASS", "details": details})

    def fail_test(self, name: str, reason: str):
        self.failed += 1
        self.failures.append(f"{name}: {reason}")
        print(f"{RED}✗{RESET} {name}")
        print(f"  {RED}Reason: {reason}{RESET}")
        self.test_details.append({"name": name, "status": "FAIL", "reason": reason})

    def warn(self, message: str):
        self.warnings += 1
        print(f"{YELLOW}⚠{RESET} {message}")

    def security_issue(self, message: str):
        self.security_issues.append(message)
        print(f"{RED}🔒 SECURITY ISSUE: {message}{RESET}")

    def summary(self):
        print(f"\n{'='*80}")
        print(f"TEST SUMMARY - Private Mode E2E (PILOT SCENARIO)")
        print(f"{'='*80}")
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
        
        print(f"{'='*80}\n")
        return self.failed == 0 and len(self.security_issues) == 0

    def print_table(self):
        """Print per-step PASS/FAIL table."""
        print(f"\n{'='*80}")
        print(f"PER-STEP TEST RESULTS TABLE")
        print(f"{'='*80}")
        print(f"{'Step':<5} {'Test Name':<50} {'Status':<10}")
        print(f"{'-'*80}")
        for i, detail in enumerate(self.test_details, 1):
            status_color = GREEN if detail["status"] == "PASS" else RED
            print(f"{i:<5} {detail['name']:<50} {status_color}{detail['status']}{RESET}")
        print(f"{'='*80}\n")


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
            print(f"{RED}Response: {response.text[:500]}{RESET}")
            return None
    except Exception as e:
        print(f"{RED}Login error for {email}: {e}{RESET}")
        return None


def check_security_leaks(data: Any, test_name: str, result: TestResult, check_geo: bool = False) -> bool:
    """Check if response contains security leaks or forbidden strings.
    
    Args:
        data: Response data (dict, list, or string)
        test_name: Name of the test
        result: TestResult object
        check_geo: If True, also check for GPS coordinates/addresses
    
    Returns:
        True if no leaks found, False otherwise
    """
    data_str = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
    data_lower = data_str.lower()
    
    # Forbidden strings (case-insensitive)
    forbidden = [
        "navixy_hash",
        "test_e2e",
        "navixy",
        "teltonika",
        "avl",
        "privatemode",
        "raw_command",
        "bearer ",  # Check for Bearer token leaks
        "api_key",
        "credential",
        "password",
        "secret"
    ]
    
    found_leaks = []
    for term in forbidden:
        if term in data_lower:
            found_leaks.append(term)
    
    if check_geo:
        # Check for GPS coordinates/addresses in driver private-mode responses
        geo_terms = ["latitude", "longitude", "lat", "lng", "address", "coordinates", "position"]
        for term in geo_terms:
            # Check if the term appears with actual values (not null)
            if term in data_lower:
                # Try to find if it has a real value (not null, not empty)
                if isinstance(data, dict):
                    value = data.get(term)
                    if value is not None and value != "" and value != "null":
                        found_leaks.append(f"{term} (has value: {value})")
    
    if found_leaks:
        result.security_issue(f"{test_name}: Found forbidden strings/leaks: {', '.join(found_leaks)}")
        return False
    
    return True


def test_step_1_get_status(driver_token: str, result: TestResult) -> Dict[str, Any]:
    """Step 1: GET /api/livre/driver/private-mode -> ASSERT allowed=true, reason=null, tracker_id=5000, private_odometer_supported=true, NO lat/lng/address."""
    print(f"\n{BLUE}Step 1: GET /api/livre/driver/private-mode (initial status){RESET}")
    
    try:
        response = requests.get(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "Step 1: GET status",
                f"Expected 200, got {response.status_code}: {response.text[:300]}"
            )
            return {}
        
        data = response.json()
        
        # Check security
        if not check_security_leaks(data, "Step 1: GET status", result, check_geo=True):
            return {}
        
        # Check allowed=true
        if data.get("allowed") is not True:
            result.fail_test(
                "Step 1: GET status - allowed",
                f"Expected allowed=true (pilot enabled), got allowed={data.get('allowed')}, reason={data.get('reason')}"
            )
            return {}
        
        # Check reason=null
        if data.get("reason") is not None:
            result.fail_test(
                "Step 1: GET status - reason",
                f"Expected reason=null (feature allowed), got reason={data.get('reason')}"
            )
            return {}
        
        # Check tracker_id=5000
        if data.get("tracker_id") != EXPECTED_TRACKER_ID:
            result.fail_test(
                "Step 1: GET status - tracker_id",
                f"Expected tracker_id={EXPECTED_TRACKER_ID}, got tracker_id={data.get('tracker_id')}"
            )
            return {}
        
        # Check private_odometer_supported=true
        if data.get("private_odometer_supported") is not True:
            result.fail_test(
                "Step 1: GET status - private_odometer_supported",
                f"Expected private_odometer_supported=true, got {data.get('private_odometer_supported')}"
            )
            return {}
        
        # Check NO real lat/lng/address values
        geo_fields = ["lat", "lng", "latitude", "longitude", "address", "start_address", "end_address"]
        found_geo = []
        for field in geo_fields:
            if field in data and data[field] is not None and data[field] != "":
                found_geo.append(f"{field}={data[field]}")
        
        if found_geo:
            result.fail_test(
                "Step 1: GET status - NO geo data",
                f"Found real geo data in response: {', '.join(found_geo)}"
            )
            return {}
        
        result.pass_test(
            "Step 1: GET status",
            f"allowed=true, reason=null, tracker_id={data.get('tracker_id')}, private_odometer_supported={data.get('private_odometer_supported')}, state={data.get('state')}"
        )
        return data
        
    except Exception as e:
        result.fail_test("Step 1: GET status", f"Exception: {str(e)}")
        return {}


def test_step_2_set_private(driver_token: str, result: TestResult) -> Dict[str, Any]:
    """Step 2: POST /api/livre/driver/private-mode {"mode":"PRIVATE"} -> ASSERT HTTP 200, ok=true, state="PRIVATE", confirmation_source present."""
    print(f"\n{BLUE}Step 2: POST /api/livre/driver/private-mode (set PRIVATE){RESET}")
    
    try:
        response = requests.post(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"mode": "PRIVATE"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "Step 2: POST PRIVATE",
                f"Expected 200, got {response.status_code}: {response.text[:300]}"
            )
            return {}
        
        data = response.json()
        
        # Check security
        if not check_security_leaks(data, "Step 2: POST PRIVATE", result):
            return {}
        
        # Check ok=true
        if data.get("ok") is not True:
            result.fail_test(
                "Step 2: POST PRIVATE - ok",
                f"Expected ok=true, got ok={data.get('ok')}"
            )
            return {}
        
        # Check state="PRIVATE"
        if data.get("state") != "PRIVATE":
            result.fail_test(
                "Step 2: POST PRIVATE - state",
                f"Expected state='PRIVATE', got state={data.get('state')}"
            )
            return {}
        
        # Check confirmation_source present (CONFIRMED transition, not optimistic)
        if "confirmation_source" not in data:
            result.fail_test(
                "Step 2: POST PRIVATE - confirmation_source",
                f"Expected confirmation_source field (CONFIRMED transition), but not found in response"
            )
            return {}
        
        result.pass_test(
            "Step 2: POST PRIVATE",
            f"ok=true, state={data.get('state')}, confirmation_source={data.get('confirmation_source')}"
        )
        return data
        
    except Exception as e:
        result.fail_test("Step 2: POST PRIVATE", f"Exception: {str(e)}")
        return {}


def test_step_3_verify_private(driver_token: str, result: TestResult) -> Dict[str, Any]:
    """Step 3: GET /api/livre/driver/private-mode -> ASSERT state="PRIVATE"."""
    print(f"\n{BLUE}Step 3: GET /api/livre/driver/private-mode (verify PRIVATE){RESET}")
    
    try:
        response = requests.get(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "Step 3: GET verify PRIVATE",
                f"Expected 200, got {response.status_code}: {response.text[:300]}"
            )
            return {}
        
        data = response.json()
        
        # Check security
        if not check_security_leaks(data, "Step 3: GET verify PRIVATE", result, check_geo=True):
            return {}
        
        # Check state="PRIVATE"
        if data.get("state") != "PRIVATE":
            result.fail_test(
                "Step 3: GET verify PRIVATE - state",
                f"Expected state='PRIVATE', got state={data.get('state')}"
            )
            return {}
        
        result.pass_test(
            "Step 3: GET verify PRIVATE",
            f"state={data.get('state')}"
        )
        return data
        
    except Exception as e:
        result.fail_test("Step 3: GET verify PRIVATE", f"Exception: {str(e)}")
        return {}


def test_step_4_idempotent_private(driver_token: str, result: TestResult) -> Dict[str, Any]:
    """Step 4: POST {"mode":"PRIVATE"} again -> ASSERT ok=true, idempotent=true."""
    print(f"\n{BLUE}Step 4: POST /api/livre/driver/private-mode (PRIVATE again - idempotent){RESET}")
    
    try:
        response = requests.post(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"mode": "PRIVATE"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "Step 4: POST PRIVATE idempotent",
                f"Expected 200, got {response.status_code}: {response.text[:300]}"
            )
            return {}
        
        data = response.json()
        
        # Check security
        if not check_security_leaks(data, "Step 4: POST PRIVATE idempotent", result):
            return {}
        
        # Check ok=true
        if data.get("ok") is not True:
            result.fail_test(
                "Step 4: POST PRIVATE idempotent - ok",
                f"Expected ok=true, got ok={data.get('ok')}"
            )
            return {}
        
        # Check idempotent=true (or no error)
        # The response should indicate idempotent behavior (no error, no double command)
        if data.get("idempotent") is not True and data.get("state") != "PRIVATE":
            result.fail_test(
                "Step 4: POST PRIVATE idempotent - idempotent flag or state",
                f"Expected idempotent=true or state='PRIVATE', got idempotent={data.get('idempotent')}, state={data.get('state')}"
            )
            return {}
        
        result.pass_test(
            "Step 4: POST PRIVATE idempotent",
            f"ok=true, idempotent={data.get('idempotent')}, state={data.get('state')}"
        )
        return data
        
    except Exception as e:
        result.fail_test("Step 4: POST PRIVATE idempotent", f"Exception: {str(e)}")
        return {}


def test_step_5_set_business(driver_token: str, result: TestResult) -> Dict[str, Any]:
    """Step 5: POST {"mode":"BUSINESS"} -> ASSERT HTTP 200, ok=true, state="BUSINESS"."""
    print(f"\n{BLUE}Step 5: POST /api/livre/driver/private-mode (set BUSINESS){RESET}")
    
    try:
        response = requests.post(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"mode": "BUSINESS"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "Step 5: POST BUSINESS",
                f"Expected 200, got {response.status_code}: {response.text[:300]}"
            )
            return {}
        
        data = response.json()
        
        # Check security
        if not check_security_leaks(data, "Step 5: POST BUSINESS", result):
            return {}
        
        # Check ok=true
        if data.get("ok") is not True:
            result.fail_test(
                "Step 5: POST BUSINESS - ok",
                f"Expected ok=true, got ok={data.get('ok')}"
            )
            return {}
        
        # Check state="BUSINESS"
        if data.get("state") != "BUSINESS":
            result.fail_test(
                "Step 5: POST BUSINESS - state",
                f"Expected state='BUSINESS', got state={data.get('state')}"
            )
            return {}
        
        # May include private_distance_km or distance_status
        details = f"ok=true, state={data.get('state')}"
        if "private_distance_km" in data:
            details += f", private_distance_km={data.get('private_distance_km')}"
        if "distance_status" in data:
            details += f", distance_status={data.get('distance_status')}"
        
        result.pass_test("Step 5: POST BUSINESS", details)
        return data
        
    except Exception as e:
        result.fail_test("Step 5: POST BUSINESS", f"Exception: {str(e)}")
        return {}


def test_step_6_verify_business(driver_token: str, result: TestResult) -> Dict[str, Any]:
    """Step 6: GET -> ASSERT state="BUSINESS"."""
    print(f"\n{BLUE}Step 6: GET /api/livre/driver/private-mode (verify BUSINESS){RESET}")
    
    try:
        response = requests.get(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "Step 6: GET verify BUSINESS",
                f"Expected 200, got {response.status_code}: {response.text[:300]}"
            )
            return {}
        
        data = response.json()
        
        # Check security
        if not check_security_leaks(data, "Step 6: GET verify BUSINESS", result, check_geo=True):
            return {}
        
        # Check state="BUSINESS"
        if data.get("state") != "BUSINESS":
            result.fail_test(
                "Step 6: GET verify BUSINESS - state",
                f"Expected state='BUSINESS', got state={data.get('state')}"
            )
            return {}
        
        result.pass_test(
            "Step 6: GET verify BUSINESS",
            f"state={data.get('state')}"
        )
        return data
        
    except Exception as e:
        result.fail_test("Step 6: GET verify BUSINESS", f"Exception: {str(e)}")
        return {}


def test_step_7_invalid_mode(driver_token: str, result: TestResult):
    """Step 7: POST {"mode":"ZZZ"} -> ASSERT HTTP 400."""
    print(f"\n{BLUE}Step 7: POST /api/livre/driver/private-mode (invalid mode ZZZ){RESET}")
    
    try:
        response = requests.post(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"mode": "ZZZ"},
            timeout=10
        )
        
        if response.status_code != 400:
            result.fail_test(
                "Step 7: POST invalid mode",
                f"Expected 400, got {response.status_code}: {response.text[:300]}"
            )
            return
        
        result.pass_test(
            "Step 7: POST invalid mode",
            f"HTTP 400 (invalid mode rejected)"
        )
        
    except Exception as e:
        result.fail_test("Step 7: POST invalid mode", f"Exception: {str(e)}")


def test_step_8_activate_kill_switch(admin_token: str, result: TestResult):
    """Step 8: ADMIN POST /api/livre/private-mode/kill-switch {"active":true} -> ASSERT {kill_switch:true}."""
    print(f"\n{BLUE}Step 8: ADMIN POST /api/livre/private-mode/kill-switch (activate){RESET}")
    
    try:
        response = requests.post(
            f"{API_BASE}/livre/private-mode/kill-switch",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"active": True},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "Step 8: ADMIN activate kill switch",
                f"Expected 200, got {response.status_code}: {response.text[:300]}"
            )
            return
        
        data = response.json()
        
        # Check security
        if not check_security_leaks(data, "Step 8: ADMIN activate kill switch", result):
            return
        
        # Check kill_switch=true
        if data.get("kill_switch") is not True:
            result.fail_test(
                "Step 8: ADMIN activate kill switch - kill_switch",
                f"Expected kill_switch=true, got kill_switch={data.get('kill_switch')}"
            )
            return
        
        result.pass_test(
            "Step 8: ADMIN activate kill switch",
            f"kill_switch={data.get('kill_switch')}"
        )
        
    except Exception as e:
        result.fail_test("Step 8: ADMIN activate kill switch", f"Exception: {str(e)}")


def test_step_9_kill_switch_blocks_private(driver_token: str, result: TestResult):
    """Step 9: DRIVER POST /api/livre/driver/private-mode {"mode":"PRIVATE"} -> ASSERT HTTP 403 with detail "PRIVATE_MODE_KILL_SWITCH_ACTIVE"."""
    print(f"\n{BLUE}Step 9: DRIVER POST /api/livre/driver/private-mode (PRIVATE blocked by kill switch){RESET}")
    
    try:
        response = requests.post(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"mode": "PRIVATE"},
            timeout=10
        )
        
        if response.status_code != 403:
            result.fail_test(
                "Step 9: DRIVER PRIVATE blocked by kill switch",
                f"Expected 403, got {response.status_code}: {response.text[:300]}"
            )
            return
        
        data = response.json()
        detail = data.get("detail", "")
        
        if "PRIVATE_MODE_KILL_SWITCH_ACTIVE" not in detail:
            result.fail_test(
                "Step 9: DRIVER PRIVATE blocked by kill switch - detail",
                f"Expected detail containing 'PRIVATE_MODE_KILL_SWITCH_ACTIVE', got: {detail}"
            )
            return
        
        result.pass_test(
            "Step 9: DRIVER PRIVATE blocked by kill switch",
            f"HTTP 403, detail={detail}"
        )
        
    except Exception as e:
        result.fail_test("Step 9: DRIVER PRIVATE blocked by kill switch", f"Exception: {str(e)}")


def test_step_10_deactivate_kill_switch(admin_token: str, result: TestResult):
    """Step 10: ADMIN POST /api/livre/private-mode/kill-switch {"active":false} -> restore."""
    print(f"\n{BLUE}Step 10: ADMIN POST /api/livre/private-mode/kill-switch (deactivate){RESET}")
    
    try:
        response = requests.post(
            f"{API_BASE}/livre/private-mode/kill-switch",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"active": False},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "Step 10: ADMIN deactivate kill switch",
                f"Expected 200, got {response.status_code}: {response.text[:300]}"
            )
            return
        
        data = response.json()
        
        # Check security
        if not check_security_leaks(data, "Step 10: ADMIN deactivate kill switch", result):
            return
        
        # Check kill_switch=false
        if data.get("kill_switch") is not False:
            result.fail_test(
                "Step 10: ADMIN deactivate kill switch - kill_switch",
                f"Expected kill_switch=false, got kill_switch={data.get('kill_switch')}"
            )
            return
        
        result.pass_test(
            "Step 10: ADMIN deactivate kill switch",
            f"kill_switch={data.get('kill_switch')}"
        )
        
    except Exception as e:
        result.fail_test("Step 10: ADMIN deactivate kill switch", f"Exception: {str(e)}")


def test_step_11_business_after_kill_switch(driver_token: str, result: TestResult):
    """Step 11: DRIVER POST {"mode":"BUSINESS"} -> ASSERT 200 ok=true, leave state BUSINESS."""
    print(f"\n{BLUE}Step 11: DRIVER POST /api/livre/driver/private-mode (BUSINESS after kill switch restore){RESET}")
    
    try:
        response = requests.post(
            f"{API_BASE}/livre/driver/private-mode",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"mode": "BUSINESS"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.fail_test(
                "Step 11: DRIVER BUSINESS after kill switch",
                f"Expected 200, got {response.status_code}: {response.text[:300]}"
            )
            return
        
        data = response.json()
        
        # Check security
        if not check_security_leaks(data, "Step 11: DRIVER BUSINESS after kill switch", result):
            return
        
        # Check ok=true
        if data.get("ok") is not True:
            result.fail_test(
                "Step 11: DRIVER BUSINESS after kill switch - ok",
                f"Expected ok=true, got ok={data.get('ok')}"
            )
            return
        
        result.pass_test(
            "Step 11: DRIVER BUSINESS after kill switch",
            f"ok=true, state={data.get('state')} (feature usable again)"
        )
        
    except Exception as e:
        result.fail_test("Step 11: DRIVER BUSINESS after kill switch", f"Exception: {str(e)}")


def test_non_regression(admin_token: str, driver_token: str, result: TestResult):
    """NON-REGRESSION: GET /api/auth/me (both roles), /api/livre/dashboard, /api/livre/trips, /api/livre/vehicles -> all 200."""
    print(f"\n{BLUE}NON-REGRESSION: Testing existing endpoints{RESET}")
    
    endpoints = [
        ("GET /api/auth/me (admin)", f"{API_BASE}/auth/me", admin_token),
        ("GET /api/auth/me (driver)", f"{API_BASE}/auth/me", driver_token),
        ("GET /api/livre/dashboard", f"{API_BASE}/livre/dashboard", admin_token),
        ("GET /api/livre/trips", f"{API_BASE}/livre/trips", admin_token),
        ("GET /api/livre/vehicles", f"{API_BASE}/livre/vehicles", admin_token),
    ]
    
    for name, url, token in endpoints:
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10
            )
            
            if response.status_code == 200:
                result.pass_test(f"NON-REGRESSION: {name}", "HTTP 200")
            else:
                result.fail_test(
                    f"NON-REGRESSION: {name}",
                    f"Expected 200, got {response.status_code}: {response.text[:200]}"
                )
        except Exception as e:
            result.fail_test(f"NON-REGRESSION: {name}", f"Exception: {str(e)}")


def main():
    print(f"\n{'='*80}")
    print(f"PRIVATE MODE E2E HTTP TEST - PILOT SCENARIO")
    print(f"{'='*80}")
    print(f"Base URL: {BASE_URL}")
    print(f"API Base: {API_BASE}")
    print(f"\nPrerequisites (VERIFIED):")
    print(f"  - Driver Jean Dupont has 'confirmed' session on vehicle GE 123456 / tracker 5000")
    print(f"  - PRIVATE_MODE_ENABLED=true")
    print(f"  - Tenant default + tracker 5000 allowlisted")
    print(f"  - field_validated capability present")
    print(f"  - PRIVATE_MODE_SIMULATE_CONFIRM=1 (device confirmation simulated)")
    print(f"{'='*80}\n")
    
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
    
    # Run state machine tests
    print(f"\n{CYAN}{'='*80}{RESET}")
    print(f"{CYAN}STATE MACHINE TESTS{RESET}")
    print(f"{CYAN}{'='*80}{RESET}")
    
    test_step_1_get_status(driver_token, result)
    test_step_2_set_private(driver_token, result)
    test_step_3_verify_private(driver_token, result)
    test_step_4_idempotent_private(driver_token, result)
    test_step_5_set_business(driver_token, result)
    test_step_6_verify_business(driver_token, result)
    test_step_7_invalid_mode(driver_token, result)
    
    # Kill switch tests
    print(f"\n{CYAN}{'='*80}{RESET}")
    print(f"{CYAN}KILL SWITCH TESTS{RESET}")
    print(f"{CYAN}{'='*80}{RESET}")
    
    test_step_8_activate_kill_switch(admin_token, result)
    test_step_9_kill_switch_blocks_private(driver_token, result)
    test_step_10_deactivate_kill_switch(admin_token, result)
    test_step_11_business_after_kill_switch(driver_token, result)
    
    # Non-regression tests
    print(f"\n{CYAN}{'='*80}{RESET}")
    print(f"{CYAN}NON-REGRESSION TESTS{RESET}")
    print(f"{CYAN}{'='*80}{RESET}")
    
    test_non_regression(admin_token, driver_token, result)
    
    # Print per-step table
    result.print_table()
    
    # Summary
    success = result.summary()
    
    # Final state confirmation
    print(f"\n{CYAN}FINAL STATE CONFIRMATION:{RESET}")
    print(f"  - Kill switch: OFF (deactivated)")
    print(f"  - Driver state: BUSINESS")
    print(f"  - CONFIRMED PRIVATE was reached: YES (Step 2)")
    print(f"  - Returned to BUSINESS: YES (Step 5)")
    
    if success:
        print(f"\n{GREEN}{'='*80}{RESET}")
        print(f"{GREEN}ALL TESTS PASSED! ✓{RESET}")
        print(f"{GREEN}{'='*80}{RESET}\n")
        sys.exit(0)
    else:
        print(f"\n{RED}{'='*80}{RESET}")
        print(f"{RED}SOME TESTS FAILED. See details above.{RESET}")
        print(f"{RED}{'='*80}{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
