#!/usr/bin/env python3
"""
Test script for rollback_classification_regression.py

Creates test data with ROLLTEST_ prefix, runs the rollback script in DRY-RUN and --apply modes,
verifies all behaviors, and cleans up.
"""
import asyncio
import os
import sys
import subprocess
import uuid
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

# Test data IDs
TENANT_A = "default"
TENANT_B = "ROLLTEST_TENANT_B"

# Vehicle IDs
VEHICLE_A_ID = "ROLLTEST_VEHICLE_A"
VEHICLE_B_ID = "ROLLTEST_VEHICLE_B"
VEHICLE_MISMATCH_ID = "ROLLTEST_VEHICLE_MISMATCH"

# Trip IDs
TRIP_R1 = str(uuid.uuid4())  # Should restore to professional
TRIP_R2 = str(uuid.uuid4())  # Should restore to personal (tenant B)
TRIP_R3 = str(uuid.uuid4())  # Pilot excluded
TRIP_R4 = str(uuid.uuid4())  # Manual excluded
TRIP_R5 = str(uuid.uuid4())  # Already correct
TRIP_R6 = str(uuid.uuid4())  # Tenant mismatch

async def setup_test_data(db):
    """Create test data with ROLLTEST_ prefix"""
    print("\n=== SETUP: Creating test data ===")
    
    # Create vehicles
    vehicles = [
        {"id": VEHICLE_A_ID, "tenant_id": TENANT_A, "plate": "ROLLTEST-A", "model": "Test A"},
        {"id": VEHICLE_B_ID, "tenant_id": TENANT_B, "plate": "ROLLTEST-B", "model": "Test B"},
        {"id": VEHICLE_MISMATCH_ID, "tenant_id": TENANT_B, "plate": "ROLLTEST-MISMATCH", "model": "Test Mismatch"},
    ]
    for v in vehicles:
        await db.vehicles.insert_one(v)
    print(f"✓ Created {len(vehicles)} test vehicles")
    
    # Create trips
    trips = [
        # R1: tenant='default', vehicle V_A(default), classification=None, should restore to professional
        {
            "id": TRIP_R1,
            "tenant_id": TENANT_A,
            "vehicle_id": VEHICLE_A_ID,
            "classification": None,
            "auto_classified": True,
            "start_time": datetime.now(timezone.utc).isoformat(),
        },
        # R2: tenant='ROLLTEST_TENANT_B', vehicle V_B(ROLLTEST_TENANT_B), classification=None, should restore to personal
        {
            "id": TRIP_R2,
            "tenant_id": TENANT_B,
            "vehicle_id": VEHICLE_B_ID,
            "classification": None,
            "auto_classified": True,
            "start_time": datetime.now(timezone.utc).isoformat(),
        },
        # R3: in PILOT_EXCLUDE_TRIP_IDS, should be excluded
        {
            "id": TRIP_R3,
            "tenant_id": TENANT_A,
            "vehicle_id": VEHICLE_A_ID,
            "classification": None,
            "auto_classified": True,
            "start_time": datetime.now(timezone.utc).isoformat(),
        },
        # R4: auto_classified=False (manual), should be excluded
        {
            "id": TRIP_R4,
            "tenant_id": TENANT_A,
            "vehicle_id": VEHICLE_A_ID,
            "classification": None,
            "auto_classified": False,
            "start_time": datetime.now(timezone.utc).isoformat(),
        },
        # R5: classification == old_classification, already correct
        {
            "id": TRIP_R5,
            "tenant_id": TENANT_A,
            "vehicle_id": VEHICLE_A_ID,
            "classification": "professional",
            "auto_classified": True,
            "start_time": datetime.now(timezone.utc).isoformat(),
        },
        # R6: tenant mismatch (trip tenant='default' but vehicle tenant='ROLLTEST_TENANT_B')
        {
            "id": TRIP_R6,
            "tenant_id": TENANT_A,
            "vehicle_id": VEHICLE_MISMATCH_ID,
            "classification": None,
            "auto_classified": True,
            "start_time": datetime.now(timezone.utc).isoformat(),
        },
    ]
    for t in trips:
        await db.trips.insert_one(t)
    print(f"✓ Created {len(trips)} test trips")
    
    # Create audit_log entries
    # Note: audit_log.tenant_id is INTENTIONALLY WRONG for R2 to test that script uses trips.tenant_id
    audit_entries = [
        # R1: old_classification='professional'
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "scope": "trip_classification",
            "strategy": "privacy_history_strict",
            "tenant_id": TENANT_A,  # Correct for R1
            "trip_id": TRIP_R1,
            "old_classification": "professional",
            "new_classification": None,
        },
        # R2: old_classification='personal', but audit tenant_id is WRONG (should be TENANT_B but is 'default')
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "scope": "trip_classification",
            "strategy": "privacy_history_strict",
            "tenant_id": TENANT_A,  # INTENTIONALLY WRONG - should be TENANT_B
            "trip_id": TRIP_R2,
            "old_classification": "personal",
            "new_classification": None,
        },
        # R3: old_classification='professional' (but will be excluded by PILOT_EXCLUDE_TRIP_IDS)
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "scope": "trip_classification",
            "strategy": "privacy_history_strict",
            "tenant_id": TENANT_A,
            "trip_id": TRIP_R3,
            "old_classification": "professional",
            "new_classification": None,
        },
        # R4: old_classification='professional' (but will be excluded because auto_classified=False)
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "scope": "trip_classification",
            "strategy": "privacy_history_strict",
            "tenant_id": TENANT_A,
            "trip_id": TRIP_R4,
            "old_classification": "professional",
            "new_classification": None,
        },
        # R5: old_classification='professional' (already correct)
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "scope": "trip_classification",
            "strategy": "privacy_history_strict",
            "tenant_id": TENANT_A,
            "trip_id": TRIP_R5,
            "old_classification": "professional",
            "new_classification": "professional",
        },
        # R6: old_classification='personal' (but will be excluded due to tenant mismatch)
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "scope": "trip_classification",
            "strategy": "privacy_history_strict",
            "tenant_id": TENANT_A,
            "trip_id": TRIP_R6,
            "old_classification": "personal",
            "new_classification": None,
        },
    ]
    for e in audit_entries:
        await db.audit_log.insert_one(e)
    print(f"✓ Created {len(audit_entries)} audit_log entries")
    
    print(f"\nTest trip IDs:")
    print(f"  R1 (restore→professional): {TRIP_R1}")
    print(f"  R2 (restore→personal, tenant B): {TRIP_R2}")
    print(f"  R3 (pilot excluded): {TRIP_R3}")
    print(f"  R4 (manual excluded): {TRIP_R4}")
    print(f"  R5 (already correct): {TRIP_R5}")
    print(f"  R6 (tenant mismatch): {TRIP_R6}")
    
    return {
        "R1": TRIP_R1,
        "R2": TRIP_R2,
        "R3": TRIP_R3,
        "R4": TRIP_R4,
        "R5": TRIP_R5,
        "R6": TRIP_R6,
    }

async def cleanup_test_data(db):
    """Remove all test data with ROLLTEST_ prefix"""
    print("\n=== CLEANUP: Removing test data ===")
    
    # Delete trips
    result = await db.trips.delete_many({"id": {"$in": [TRIP_R1, TRIP_R2, TRIP_R3, TRIP_R4, TRIP_R5, TRIP_R6]}})
    print(f"✓ Deleted {result.deleted_count} test trips")
    
    # Delete vehicles
    result = await db.vehicles.delete_many({"id": {"$regex": "^ROLLTEST_"}})
    print(f"✓ Deleted {result.deleted_count} test vehicles")
    
    # Delete audit_log entries (both test and rollback entries)
    result = await db.audit_log.delete_many({"trip_id": {"$in": [TRIP_R1, TRIP_R2, TRIP_R3, TRIP_R4, TRIP_R5, TRIP_R6]}})
    print(f"✓ Deleted {result.deleted_count} audit_log entries")

async def verify_trip_state(db, trip_ids, expected_states):
    """Verify trip classifications match expected states"""
    print("\n=== VERIFICATION: Checking trip states ===")
    all_correct = True
    
    for name, trip_id in trip_ids.items():
        trip = await db.trips.find_one({"id": trip_id}, {"_id": 0, "classification": 1, "tenant_id": 1})
        expected = expected_states.get(name)
        actual = trip.get("classification") if trip else None
        tenant = trip.get("tenant_id") if trip else None
        
        match = actual == expected
        symbol = "✓" if match else "✗"
        print(f"{symbol} {name}: expected={expected}, actual={actual}, tenant={tenant}")
        
        if not match:
            all_correct = False
    
    return all_correct

async def verify_rollback_audit(db, trip_ids):
    """Verify rollback audit entries were created with correct tenant_id"""
    print("\n=== VERIFICATION: Checking rollback audit entries ===")
    
    # Check R1 rollback audit (should have tenant='default')
    r1_audit = await db.audit_log.find_one({
        "scope": "trip_classification_rollback",
        "trip_id": trip_ids["R1"]
    })
    if r1_audit:
        tenant = r1_audit.get("tenant_id")
        if tenant == TENANT_A:
            print(f"✓ R1 rollback audit has correct tenant_id: {tenant}")
        else:
            print(f"✗ R1 rollback audit has WRONG tenant_id: {tenant} (expected {TENANT_A})")
    else:
        print("✗ R1 rollback audit entry NOT FOUND")
    
    # Check R2 rollback audit (should have tenant='ROLLTEST_TENANT_B', NOT 'default')
    r2_audit = await db.audit_log.find_one({
        "scope": "trip_classification_rollback",
        "trip_id": trip_ids["R2"]
    })
    if r2_audit:
        tenant = r2_audit.get("tenant_id")
        if tenant == TENANT_B:
            print(f"✓ R2 rollback audit has correct REAL tenant_id: {tenant} (NOT audit_log.tenant_id)")
        else:
            print(f"✗ R2 rollback audit has WRONG tenant_id: {tenant} (expected {TENANT_B})")
    else:
        print("✗ R2 rollback audit entry NOT FOUND")

def run_rollback_script(dry_run=True, pilot_exclude_ids=""):
    """Run the rollback script"""
    script_path = "/app/deliverables/git/rollback_classification_regression.py"
    
    env = os.environ.copy()
    env["MONGO_URL"] = "mongodb://localhost:27017"
    env["DB_NAME"] = "journal_logitrak"
    env["PILOT_EXCLUDE_TRIP_IDS"] = pilot_exclude_ids
    
    args = ["python3", script_path]
    if not dry_run:
        args.append("--apply")
    
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n=== Running rollback script ({mode}) ===")
    if pilot_exclude_ids:
        print(f"PILOT_EXCLUDE_TRIP_IDS: {pilot_exclude_ids[:50]}...")
    
    result = subprocess.run(args, env=env, capture_output=True, text=True)
    
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    return result.stdout, result.returncode

async def main():
    # Connect to database
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "journal_logitrak")
    
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    print(f"Connected to MongoDB: {mongo_url}/{db_name}")
    
    try:
        # Step a: Create test data
        trip_ids = await setup_test_data(db)
        
        # Step b: Run DRY-RUN with PILOT_EXCLUDE_TRIP_IDS containing R3
        print("\n" + "="*70)
        print("STEP B: DRY-RUN with PILOT_EXCLUDE_TRIP_IDS")
        print("="*70)
        stdout, returncode = run_rollback_script(dry_run=True, pilot_exclude_ids=trip_ids["R3"])
        
        # Verify DRY-RUN report
        print("\n=== VERIFICATION: DRY-RUN Report ===")
        checks = {
            "PILOT_EXCLUDED": "Should be >= 1 (R3)",
            "MANUAL_EXCLUDED": "Should be >= 1 (R4)",
            "ALREADY_CORRECT": "Should be >= 1 (R5)",
            "TENANT_MISMATCH": "Should be >= 1 (R6)",
            "APPLICABLE_TOTAL": "Should be 2 (R1 + R2)",
            "PAR_TENANT_REEL": "Should contain both 'default' and 'ROLLTEST_TENANT_B'",
        }
        
        for key, description in checks.items():
            if key in stdout:
                print(f"✓ {key} found in report - {description}")
            else:
                print(f"✗ {key} NOT found in report")
        
        # Verify no writes in DRY-RUN
        print("\n=== VERIFICATION: No writes in DRY-RUN ===")
        initial_states = {
            "R1": None,
            "R2": None,
            "R3": None,
            "R4": None,
            "R5": "professional",
            "R6": None,
        }
        if await verify_trip_state(db, trip_ids, initial_states):
            print("✓ DRY-RUN did not modify any trips")
        else:
            print("✗ DRY-RUN modified trips (SHOULD NOT HAPPEN)")
        
        # Step c: Run with --apply
        print("\n" + "="*70)
        print("STEP C: APPLY with PILOT_EXCLUDE_TRIP_IDS")
        print("="*70)
        stdout, returncode = run_rollback_script(dry_run=False, pilot_exclude_ids=trip_ids["R3"])
        
        # Verify results after --apply
        expected_after_apply = {
            "R1": "professional",  # Restored
            "R2": "personal",      # Restored
            "R3": None,            # Excluded (pilot)
            "R4": None,            # Excluded (manual)
            "R5": "professional",  # Already correct
            "R6": None,            # Excluded (tenant mismatch)
        }
        
        if await verify_trip_state(db, trip_ids, expected_after_apply):
            print("✓ All trips in expected state after --apply")
        else:
            print("✗ Some trips NOT in expected state after --apply")
        
        # Verify rollback audit entries
        await verify_rollback_audit(db, trip_ids)
        
        # Step d: Run --apply again (idempotence test)
        print("\n" + "="*70)
        print("STEP D: APPLY again (idempotence test)")
        print("="*70)
        stdout, returncode = run_rollback_script(dry_run=False, pilot_exclude_ids=trip_ids["R3"])
        
        # Verify idempotence
        print("\n=== VERIFICATION: Idempotence ===")
        if "0 trajet(s) restauré(s)" in stdout or "APPLICABLE_TOTAL    = 0" in stdout:
            print("✓ Idempotence verified: 0 modifications on second run")
        else:
            print("✗ Idempotence FAILED: Script modified trips on second run")
        
        # Verify state unchanged
        if await verify_trip_state(db, trip_ids, expected_after_apply):
            print("✓ Trip states unchanged after second --apply")
        else:
            print("✗ Trip states changed after second --apply")
        
        # Step e: Cleanup
        print("\n" + "="*70)
        print("STEP E: CLEANUP")
        print("="*70)
        await cleanup_test_data(db)
        
        print("\n" + "="*70)
        print("TEST COMPLETE")
        print("="*70)
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        
        # Attempt cleanup even on error
        try:
            await cleanup_test_data(db)
        except:
            pass
        
        sys.exit(1)
    finally:
        client.close()

if __name__ == "__main__":
    asyncio.run(main())
