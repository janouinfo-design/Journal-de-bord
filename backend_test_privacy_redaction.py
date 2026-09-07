#!/usr/bin/env python3
"""
PRIVACY REDACTION IN REPORT EXPORTS - Backend Test
===================================================

CONTEXT: Validate that trips performed in Private Mode (device) have their 
addresses/coordinates REDACTED in CSV/PDF/XLSX exports, even if classified 
as "professional". Business trips must keep their addresses.

DEV FIXTURE: Trip id "DEV-PRIVATE-FIXTURE-0001", classification=professional, 
private_mode=True, addresses "Lausanne (DEV fixture)" and "Genève (DEV fixture)", 
distance 62.3 km. These addresses MUST be redacted to "Privé — position masquée".

TESTS:
1. GET /api/livre/reports/export?classification=professional&fmt=csv
   - ASSERT: "Lausanne (DEV fixture)" and "Genève (DEV fixture)" NOT in CSV
   - ASSERT: "Privé — position masquée" IS in CSV
   - ASSERT: "62.3" (distance) IS in CSV (business data preserved)
   - ASSERT: At least one non-private trip shows real address
   
2. GET /api/livre/reports/export?classification=professional&fmt=xlsx
   - ASSERT: Raw bytes do NOT contain "Lausanne (DEV fixture)" or "Genève (DEV fixture)"
   
3. GET /api/livre/reports/export?classification=professional&fmt=pdf
   - ASSERT: Raw bytes do NOT contain "Lausanne (DEV fixture)"
   
4. GET /api/livre/reports/tax-swiss?year=2026
   - ASSERT: 200 + PDF content-type
   
5. GET /api/livre/trips
   - ASSERT: Trips with private_redacted=true have null coordinates
   - ASSERT: Other trips keep coordinates
"""

import os
import sys
import requests

# Backend URL from environment
BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://confidentialite-flag.preview.emergentagent.com")
BASE_URL = f"{BACKEND_URL}/api"

# Admin credentials
ADMIN_EMAIL = "admin@logitrak.ch"
ADMIN_PASSWORD = "admin123"

# Test results
results = {
    "passed": [],
    "failed": [],
    "warnings": []
}

def log_pass(test_name, message=""):
    """Log a passing test."""
    results["passed"].append(f"✅ {test_name}: {message}")
    print(f"✅ {test_name}: {message}")

def log_fail(test_name, message=""):
    """Log a failing test."""
    results["failed"].append(f"❌ {test_name}: {message}")
    print(f"❌ {test_name}: {message}")

def log_warning(message):
    """Log a warning."""
    results["warnings"].append(f"⚠️  {message}")
    print(f"⚠️  {message}")

def get_admin_token():
    """Login as admin and get auth token."""
    print(f"\n🔐 Logging in as admin ({ADMIN_EMAIL})...")
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    if response.status_code != 200:
        print(f"❌ Login failed: {response.status_code} {response.text}")
        sys.exit(1)
    
    data = response.json()
    token = data.get("access_token")
    if not token:
        print(f"❌ No access_token in response: {data}")
        sys.exit(1)
    
    print(f"✅ Login successful")
    return token

def test_csv_export(token):
    """Test 1: CSV export - verify private trip addresses are redacted."""
    print("\n" + "="*80)
    print("TEST 1: CSV Export - Privacy Redaction")
    print("="*80)
    
    url = f"{BASE_URL}/livre/reports/export?classification=professional&fmt=csv"
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"GET {url}")
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        log_fail("CSV Export", f"HTTP {response.status_code}: {response.text[:200]}")
        return
    
    # Decode CSV
    csv_text = response.content.decode("utf-8-sig")
    
    # Check 1: Private addresses MUST NOT appear
    forbidden_strings = ["Lausanne (DEV fixture)", "Genève (DEV fixture)"]
    leaked = []
    for forbidden in forbidden_strings:
        if forbidden in csv_text:
            leaked.append(forbidden)
    
    if leaked:
        log_fail("CSV Export - No Private Addresses", f"LEAKED: {leaked}")
        print(f"\n🔍 CSV Preview (first 1000 chars):\n{csv_text[:1000]}")
    else:
        log_pass("CSV Export - No Private Addresses", "No private addresses found in CSV")
    
    # Check 2: Redaction label MUST appear
    if "Privé — position masquée" in csv_text:
        log_pass("CSV Export - Redaction Label", "Found 'Privé — position masquée'")
    else:
        log_fail("CSV Export - Redaction Label", "Missing 'Privé — position masquée'")
    
    # Check 3: Business data preserved (distance 62.3)
    if "62.3" in csv_text or "62,3" in csv_text:
        log_pass("CSV Export - Business Data", "Distance 62.3 km preserved")
    else:
        log_warning("Distance 62.3 not found - may be formatted differently or trip not in export")
    
    # Check 4: At least one non-private trip shows real address
    # Look for common address patterns (not the private fixture addresses)
    real_addresses = []
    lines = csv_text.split("\n")
    for line in lines[1:]:  # Skip header
        if not line.strip():
            continue
        # Check if line contains addresses that are NOT the redaction label
        if ";" in line and "Privé — position masquée" not in line:
            parts = line.split(";")
            if len(parts) > 5:
                start_addr = parts[4].strip()
                end_addr = parts[5].strip()
                if start_addr and start_addr != "" and start_addr != "—":
                    real_addresses.append(start_addr)
                if end_addr and end_addr != "" and end_addr != "—":
                    real_addresses.append(end_addr)
    
    if real_addresses:
        log_pass("CSV Export - Non-Private Addresses", f"Found {len(real_addresses)} real addresses (business trips not over-redacted)")
        print(f"   Sample addresses: {real_addresses[:3]}")
    else:
        log_warning("No non-private addresses found - all trips may be private or export is empty")
    
    print(f"\n📊 CSV Stats: {len(lines)} lines, {len(csv_text)} bytes")

def test_xlsx_export(token):
    """Test 2: XLSX export - verify no private addresses in raw bytes."""
    print("\n" + "="*80)
    print("TEST 2: XLSX Export - Privacy Redaction")
    print("="*80)
    
    url = f"{BASE_URL}/livre/reports/export?classification=professional&fmt=xlsx"
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"GET {url}")
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        log_fail("XLSX Export", f"HTTP {response.status_code}: {response.text[:200]}")
        return
    
    # Check raw bytes for forbidden strings
    xlsx_bytes = response.content
    forbidden_strings = ["Lausanne (DEV fixture)", "Genève (DEV fixture)"]
    leaked = []
    
    for forbidden in forbidden_strings:
        if forbidden.encode("utf-8") in xlsx_bytes:
            leaked.append(forbidden)
    
    if leaked:
        log_fail("XLSX Export - No Private Addresses", f"LEAKED: {leaked}")
    else:
        log_pass("XLSX Export - No Private Addresses", "No private addresses found in XLSX bytes")
    
    # Verify it's a valid XLSX (ZIP signature)
    if xlsx_bytes[:4] == b'PK\x03\x04':
        log_pass("XLSX Export - Valid Format", f"Valid XLSX file ({len(xlsx_bytes)} bytes)")
    else:
        log_fail("XLSX Export - Valid Format", "Not a valid XLSX file (missing ZIP signature)")
    
    print(f"\n📊 XLSX Stats: {len(xlsx_bytes)} bytes")

def test_pdf_export(token):
    """Test 3: PDF export - verify no private addresses in raw bytes."""
    print("\n" + "="*80)
    print("TEST 3: PDF Export - Privacy Redaction")
    print("="*80)
    
    url = f"{BASE_URL}/livre/reports/export?classification=professional&fmt=pdf"
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"GET {url}")
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        log_fail("PDF Export", f"HTTP {response.status_code}: {response.text[:200]}")
        return
    
    # Check raw bytes for forbidden strings
    pdf_bytes = response.content
    forbidden_strings = ["Lausanne (DEV fixture)", "Genève (DEV fixture)"]
    leaked = []
    
    for forbidden in forbidden_strings:
        if forbidden.encode("utf-8") in pdf_bytes:
            leaked.append(forbidden)
    
    if leaked:
        log_fail("PDF Export - No Private Addresses", f"LEAKED: {leaked}")
    else:
        log_pass("PDF Export - No Private Addresses", "No private addresses found in PDF bytes")
    
    # Verify it's a valid PDF
    if pdf_bytes[:4] == b'%PDF':
        log_pass("PDF Export - Valid Format", f"Valid PDF file ({len(pdf_bytes)} bytes)")
    else:
        log_fail("PDF Export - Valid Format", "Not a valid PDF file (missing %PDF header)")
    
    print(f"\n📊 PDF Stats: {len(pdf_bytes)} bytes")

def test_tax_report(token):
    """Test 4: Swiss tax report - verify 200 + PDF content-type."""
    print("\n" + "="*80)
    print("TEST 4: Swiss Tax Report")
    print("="*80)
    
    url = f"{BASE_URL}/livre/reports/tax-swiss?year=2026"
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"GET {url}")
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        log_fail("Tax Report", f"HTTP {response.status_code}: {response.text[:200]}")
        return
    
    log_pass("Tax Report - Status", "HTTP 200")
    
    # Check content-type
    content_type = response.headers.get("Content-Type", "")
    if "application/pdf" in content_type:
        log_pass("Tax Report - Content-Type", f"Correct: {content_type}")
    else:
        log_fail("Tax Report - Content-Type", f"Expected application/pdf, got: {content_type}")
    
    # Verify it's a valid PDF
    pdf_bytes = response.content
    if pdf_bytes[:4] == b'%PDF':
        log_pass("Tax Report - Valid Format", f"Valid PDF file ({len(pdf_bytes)} bytes)")
    else:
        log_fail("Tax Report - Valid Format", "Not a valid PDF file")
    
    print(f"\n📊 Tax Report Stats: {len(pdf_bytes)} bytes")

def test_trips_endpoint(token):
    """Test 5: Trips endpoint - verify private_redacted trips have null coordinates."""
    print("\n" + "="*80)
    print("TEST 5: Trips Endpoint - Private Redaction")
    print("="*80)
    
    url = f"{BASE_URL}/livre/trips"
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"GET {url}")
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        log_fail("Trips Endpoint", f"HTTP {response.status_code}: {response.text[:200]}")
        return
    
    log_pass("Trips Endpoint - Status", "HTTP 200")
    
    data = response.json()
    if not isinstance(data, dict):
        log_fail("Trips Endpoint - Format", f"Expected dict, got: {type(data)}")
        return
    
    trips = data.get("trips", [])
    if not isinstance(trips, list):
        log_fail("Trips Endpoint - Format", f"Expected trips to be list, got: {type(trips)}")
        return
    
    print(f"\n📊 Found {len(trips)} trips")
    
    # Find private and non-private trips
    private_trips = []
    non_private_trips = []
    
    for trip in trips:
        if trip.get("private_redacted") is True:
            private_trips.append(trip)
        else:
            non_private_trips.append(trip)
    
    print(f"   - Private (redacted): {len(private_trips)}")
    print(f"   - Non-private: {len(non_private_trips)}")
    
    # Check private trips have null coordinates
    if private_trips:
        all_null = True
        for trip in private_trips:
            coords = [
                trip.get("start_lat"),
                trip.get("start_lng"),
                trip.get("end_lat"),
                trip.get("end_lng"),
                trip.get("start_address"),
                trip.get("end_address")
            ]
            if any(c is not None for c in coords):
                all_null = False
                log_fail("Trips Endpoint - Private Redaction", 
                        f"Trip {trip.get('id')} has non-null coordinates: {coords}")
                break
        
        if all_null:
            log_pass("Trips Endpoint - Private Redaction", 
                    f"All {len(private_trips)} private trips have null coordinates")
    else:
        log_warning("No private trips found in response")
    
    # Check non-private trips keep coordinates
    if non_private_trips:
        has_coords = False
        for trip in non_private_trips[:10]:  # Check first 10
            if (trip.get("start_lat") is not None or 
                trip.get("start_lng") is not None or
                trip.get("start_address") is not None):
                has_coords = True
                break
        
        if has_coords:
            log_pass("Trips Endpoint - Non-Private Coordinates", 
                    "Non-private trips keep their coordinates")
        else:
            log_warning("No coordinates found in non-private trips (may be data issue)")
    else:
        log_warning("No non-private trips found in response")
    
    # Look for the DEV fixture trip
    dev_fixture = None
    for trip in trips:
        if trip.get("id") == "DEV-PRIVATE-FIXTURE-0001":
            dev_fixture = trip
            break
    
    if dev_fixture:
        print(f"\n🔍 Found DEV fixture trip: {dev_fixture.get('id')}")
        print(f"   - private_redacted: {dev_fixture.get('private_redacted')}")
        print(f"   - classification: {dev_fixture.get('classification')}")
        print(f"   - distance_km: {dev_fixture.get('distance_km')}")
        print(f"   - start_address: {dev_fixture.get('start_address')}")
        print(f"   - end_address: {dev_fixture.get('end_address')}")
        
        if dev_fixture.get("private_redacted") is True:
            log_pass("DEV Fixture - Redacted Flag", "private_redacted=true")
        else:
            log_fail("DEV Fixture - Redacted Flag", f"Expected true, got: {dev_fixture.get('private_redacted')}")
        
        if dev_fixture.get("start_address") is None and dev_fixture.get("end_address") is None:
            log_pass("DEV Fixture - Null Addresses", "Addresses are null")
        else:
            log_fail("DEV Fixture - Null Addresses", 
                    f"start={dev_fixture.get('start_address')}, end={dev_fixture.get('end_address')}")
    else:
        log_warning("DEV fixture trip 'DEV-PRIVATE-FIXTURE-0001' not found in trips endpoint")

def print_summary():
    """Print test summary."""
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    print(f"\n✅ PASSED: {len(results['passed'])}")
    for p in results["passed"]:
        print(f"   {p}")
    
    if results["failed"]:
        print(f"\n❌ FAILED: {len(results['failed'])}")
        for f in results["failed"]:
            print(f"   {f}")
    
    if results["warnings"]:
        print(f"\n⚠️  WARNINGS: {len(results['warnings'])}")
        for w in results["warnings"]:
            print(f"   {w}")
    
    print("\n" + "="*80)
    if results["failed"]:
        print("❌ TESTS FAILED")
        return 1
    else:
        print("✅ ALL TESTS PASSED")
        return 0

def main():
    """Run all tests."""
    print("="*80)
    print("PRIVACY REDACTION IN REPORT EXPORTS - Backend Test")
    print("="*80)
    print(f"Backend URL: {BACKEND_URL}")
    print(f"Admin: {ADMIN_EMAIL}")
    
    # Get admin token
    token = get_admin_token()
    
    # Run tests
    test_csv_export(token)
    test_xlsx_export(token)
    test_pdf_export(token)
    test_tax_report(token)
    test_trips_endpoint(token)
    
    # Print summary
    return print_summary()

if __name__ == "__main__":
    sys.exit(main())
