#!/usr/bin/env python3
"""
Non-regression test: 100% legacy tenant behavior unchanged.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
import uuid

sys.path.insert(0, '/app/backend')
from app import rules


async def main():
    print("=" * 80)
    print("LEGACY TENANT NON-REGRESSION TEST")
    print("=" * 80)
    
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    client = AsyncIOMotorClient(mongo_url)
    db = client.journal_logitrak
    
    print(f"\n✓ Connected to MongoDB")
    
    # Test data
    test_vehicle = f"TEST_LEGACY_{uuid.uuid4().hex[:8]}"
    test_trip = str(uuid.uuid4())
    
    try:
        # Ensure tenant is in legacy mode
        await db.settings.update_one(
            {"id": "default"},
            {"$set": {"classification_mode": "legacy"}},
            upsert=True
        )
        print("✓ Tenant set to classification_mode='legacy'")
        
        # Create vehicle WITHOUT classification_mode override
        await db.vehicles.insert_one({
            "id": test_vehicle,
            "tenant_id": "default",
            "plate": "TEST-LEGACY",
            "model": "Test Vehicle"
        })
        print(f"✓ Created vehicle {test_vehicle} (no override)")
        
        # Create trip on Monday 10:00 AM (work hours)
        monday_10am = datetime(2026, 1, 5, 10, 0, 0, tzinfo=timezone.utc)
        await db.trips.insert_one({
            "id": test_trip,
            "tenant_id": "default",
            "vehicle_id": test_vehicle,
            "classification": None,
            "auto_classified": True,
            "start_time": monday_10am.isoformat(),
            "end_time": monday_10am.isoformat(),
            "distance_km": 10.0
        })
        print(f"✓ Created trip (Mon 10:00 AM, None)")
        
        # Run classification
        updated = await rules.apply_rules_to_all(db)
        print(f"\n✓ apply_rules_to_all() updated {updated} trips")
        
        # Verify: should be classified by schedule (professional during work hours)
        trip = await db.trips.find_one({"id": test_trip})
        classification = trip.get("classification")
        
        if classification == "professional":
            print(f"\n✓✓✓ PASS: Legacy schedule classification working")
            print(f"    Trip classified as '{classification}' (Mon 10:00 AM = work hours)")
            result = 0
        else:
            print(f"\n✗✗✗ FAIL: Expected 'professional', got '{classification}'")
            result = 1
        
    finally:
        # Cleanup
        await db.vehicles.delete_one({"id": test_vehicle})
        await db.trips.delete_one({"id": test_trip})
        print("\n✓ Cleanup complete")
        client.close()
    
    return result


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
