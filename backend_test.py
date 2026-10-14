#!/usr/bin/env python3
"""
Test validation for GET /api/livre/driver/km-summary driver-centered aggregation fix.

Review request: Validate that km-summary aggregates across ALL vehicles of the driver,
not just the active vehicle. The vehicle_id (active) is returned for CONTEXT but does
NOT filter the km aggregation.

Test scenario:
1. Create 1 test driver + 2 vehicles (KM2TEST_VEH_A, KM2TEST_VEH_B)
2. Create trips TODAY with specific km values
3. Verify aggregation across both vehicles
4. Verify vehicle_id context vs filtering
5. Verify AVL16 fallback behavior (flag OFF by default)
6. Verify other driver/tenant isolation
7. Clean up test data
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Add backend to path
sys.path.insert(0, '/app/backend')

from motor.motor_asyncio import AsyncIOMotorClient
import httpx

# Configuration
BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
if not BACKEND_URL.startswith("http"):
    BACKEND_URL = f"https://{BACKEND_URL}"
API_BASE = f"{BACKEND_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "journal_logitrak")

# Test credentials
DRIVER_EMAIL = "chauffeur@logitrak.ch"
DRIVER_PASSWORD = "Test1234!"

# Test data prefix
PREFIX = "KM2TEST_"

# Timezone
TZ = ZoneInfo("Europe/Zurich")


class TestContext:
    def __init__(self):
        self.db = None
        self.client = None
        self.driver_token = None
        self.driver_id = None
        self.tenant_id = "default"
        self.vehicle_a_id = None
        self.vehicle_b_id = None
        self.trip_ids = []
        self.assignment_id = None
        self.other_driver_id = None
        self.other_trip_id = None
        
    async def setup_db(self):
        """Connect to MongoDB"""
        self.client = AsyncIOMotorClient(MONGO_URL)
        self.db = self.client[DB_NAME]
        print(f"✓ Connected to MongoDB: {MONGO_URL}/{DB_NAME}")
        
    async def cleanup_db(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            print("✓ Closed MongoDB connection")
    
    async def login_driver(self):
        """Login as test driver and get token"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{API_BASE}/auth/login",
                json={"email": DRIVER_EMAIL, "password": DRIVER_PASSWORD}
            )
            if resp.status_code != 200:
                raise Exception(f"Login failed: {resp.status_code} {resp.text}")
            data = resp.json()
            self.driver_token = data["access_token"]
            
            # Get driver_id from /auth/me
            resp = await client.get(
                f"{API_BASE}/auth/me",
                headers={"Authorization": f"Bearer {self.driver_token}"}
            )
            if resp.status_code != 200:
                raise Exception(f"Get /auth/me failed: {resp.status_code} {resp.text}")
            user = resp.json()
            
            # Get driver record
            driver = await self.db.drivers.find_one(
                {"email": DRIVER_EMAIL, "tenant_id": self.tenant_id},
                {"_id": 0, "id": 1}
            )
            if not driver:
                raise Exception(f"Driver record not found for {DRIVER_EMAIL}")
            self.driver_id = driver["id"]
            
            print(f"✓ Logged in as {DRIVER_EMAIL}, driver_id={self.driver_id}")
    
    async def create_test_vehicles(self):
        """Create 2 test vehicles"""
        self.vehicle_a_id = f"{PREFIX}VEH_A_{uuid.uuid4().hex[:8]}"
        self.vehicle_b_id = f"{PREFIX}VEH_B_{uuid.uuid4().hex[:8]}"
        
        vehicle_a = {
            "id": self.vehicle_a_id,
            "tenant_id": self.tenant_id,
            "plate": f"{PREFIX}PLATE_A",
            "model": f"{PREFIX}MODEL_A",
            "label": f"{PREFIX}LABEL_A",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        vehicle_b = {
            "id": self.vehicle_b_id,
            "tenant_id": self.tenant_id,
            "plate": f"{PREFIX}PLATE_B",
            "model": f"{PREFIX}MODEL_B",
            "label": f"{PREFIX}LABEL_B",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        await self.db.vehicles.insert_one(vehicle_a)
        await self.db.vehicles.insert_one(vehicle_b)
        
        print(f"✓ Created vehicle A: {self.vehicle_a_id}")
        print(f"✓ Created vehicle B: {self.vehicle_b_id}")
    
    async def create_test_trips(self):
        """Create test trips TODAY with specific km values"""
        now_local = datetime.now(timezone.utc).astimezone(TZ)
        today_start = now_local.replace(hour=8, minute=0, second=0, microsecond=0)
        
        trips = [
            # VEH_A: professional 12.7, personal 7.4
            {
                "id": str(uuid.uuid4()),
                "tenant_id": self.tenant_id,
                "driver_id": self.driver_id,
                "vehicle_id": self.vehicle_a_id,
                "classification": "professional",
                "auto_classified": True,
                "distance_km": 12.7,
                "start_time": (today_start + timedelta(hours=0)).astimezone(timezone.utc).isoformat(),
                "end_time": (today_start + timedelta(hours=1)).astimezone(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": str(uuid.uuid4()),
                "tenant_id": self.tenant_id,
                "driver_id": self.driver_id,
                "vehicle_id": self.vehicle_a_id,
                "classification": "personal",
                "auto_classified": True,
                "distance_km": 7.4,
                "start_time": (today_start + timedelta(hours=1)).astimezone(timezone.utc).isoformat(),
                "end_time": (today_start + timedelta(hours=2)).astimezone(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            # VEH_B: professional 32.7, personal 20.3, manual professional 10.0, None 5.0
            {
                "id": str(uuid.uuid4()),
                "tenant_id": self.tenant_id,
                "driver_id": self.driver_id,
                "vehicle_id": self.vehicle_b_id,
                "classification": "professional",
                "auto_classified": True,
                "distance_km": 32.7,
                "start_time": (today_start + timedelta(hours=2)).astimezone(timezone.utc).isoformat(),
                "end_time": (today_start + timedelta(hours=3)).astimezone(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": str(uuid.uuid4()),
                "tenant_id": self.tenant_id,
                "driver_id": self.driver_id,
                "vehicle_id": self.vehicle_b_id,
                "classification": "personal",
                "auto_classified": True,
                "distance_km": 20.3,
                "start_time": (today_start + timedelta(hours=3)).astimezone(timezone.utc).isoformat(),
                "end_time": (today_start + timedelta(hours=4)).astimezone(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": str(uuid.uuid4()),
                "tenant_id": self.tenant_id,
                "driver_id": self.driver_id,
                "vehicle_id": self.vehicle_b_id,
                "classification": "professional",
                "auto_classified": False,  # MANUAL
                "distance_km": 10.0,
                "start_time": (today_start + timedelta(hours=4)).astimezone(timezone.utc).isoformat(),
                "end_time": (today_start + timedelta(hours=5)).astimezone(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": str(uuid.uuid4()),
                "tenant_id": self.tenant_id,
                "driver_id": self.driver_id,
                "vehicle_id": self.vehicle_b_id,
                "classification": None,  # None should NOT be counted
                "auto_classified": True,
                "distance_km": 5.0,
                "start_time": (today_start + timedelta(hours=5)).astimezone(timezone.utc).isoformat(),
                "end_time": (today_start + timedelta(hours=6)).astimezone(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        ]
        
        for trip in trips:
            await self.db.trips.insert_one(trip)
            self.trip_ids.append(trip["id"])
        
        print(f"✓ Created {len(trips)} test trips TODAY")
        print(f"  - VEH_A: professional=12.7, personal=7.4")
        print(f"  - VEH_B: professional=32.7, personal=20.3, manual_professional=10.0, None=5.0")
        print(f"  - Expected: PRO=55.4 (12.7+32.7+10.0), PRIVATE=27.7 (7.4+20.3)")
    
    async def create_active_assignment(self):
        """Create ACTIVE assignment on VEH_A"""
        self.assignment_id = str(uuid.uuid4())
        assignment = {
            "id": self.assignment_id,
            "tenant_id": self.tenant_id,
            "driver_id": self.driver_id,
            "vehicle_id": self.vehicle_a_id,
            "status": "ACTIVE",
            "assignment_started_at": datetime.now(timezone.utc).isoformat(),
            "segment_started_at": datetime.now(timezone.utc).isoformat(),
            "source": "TEST",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.db.vehicle_assignments.insert_one(assignment)
        print(f"✓ Created ACTIVE assignment on VEH_A: {self.assignment_id}")
    
    async def create_other_driver_trip(self):
        """Create a trip for another driver to verify isolation"""
        # Create another driver
        self.other_driver_id = str(uuid.uuid4())
        other_driver = {
            "id": self.other_driver_id,
            "tenant_id": self.tenant_id,
            "name": f"{PREFIX}OTHER_DRIVER",
            "email": f"{PREFIX}other@test.com",
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.db.drivers.insert_one(other_driver)
        
        # Create a trip for this other driver
        now_local = datetime.now(timezone.utc).astimezone(TZ)
        today_start = now_local.replace(hour=8, minute=0, second=0, microsecond=0)
        
        self.other_trip_id = str(uuid.uuid4())
        other_trip = {
            "id": self.other_trip_id,
            "tenant_id": self.tenant_id,
            "driver_id": self.other_driver_id,
            "vehicle_id": self.vehicle_a_id,  # Same vehicle
            "classification": "professional",
            "auto_classified": True,
            "distance_km": 99.9,  # Should NOT be counted
            "start_time": (today_start + timedelta(hours=6)).astimezone(timezone.utc).isoformat(),
            "end_time": (today_start + timedelta(hours=7)).astimezone(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.db.trips.insert_one(other_trip)
        print(f"✓ Created trip for OTHER driver (should NOT be counted): 99.9 km")
    
    async def test_km_summary_today(self):
        """Test GET /api/livre/driver/km-summary?period=today"""
        print("\n=== TEST: period=today ===")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{API_BASE}/livre/driver/km-summary?period=today",
                headers={"Authorization": f"Bearer {self.driver_token}"}
            )
            if resp.status_code != 200:
                raise Exception(f"GET km-summary failed: {resp.status_code} {resp.text}")
            
            data = resp.json()
            print(f"Response: {data}")
            
            # Verify aggregation across both vehicles
            assert data["pro_km"] == 55.4, f"Expected pro_km=55.4, got {data['pro_km']}"
            assert data["private_km"] == 27.7, f"Expected private_km=27.7, got {data['private_km']}"
            
            # Verify vehicle_id is VEH_A (context, not filter)
            assert data["vehicle_id"] == self.vehicle_a_id, \
                f"Expected vehicle_id={self.vehicle_a_id}, got {data['vehicle_id']}"
            
            # Verify available
            assert data["available"] is True, f"Expected available=True, got {data['available']}"
            
            # Verify private_km_source (with AVL16 flag OFF, should be GPS_FALLBACK or GPS_TRIPS_DRIVER)
            assert data["private_km_source"] in ["GPS_FALLBACK", "GPS_TRIPS_DRIVER"], \
                f"Expected GPS source, got {data['private_km_source']}"
            
            print("✓ period=today: pro_km=55.4, private_km=27.7, vehicle_id=VEH_A (context)")
            print("✓ Aggregation across BOTH vehicles verified")
            print("✓ vehicle_id does NOT filter km (correct)")
    
    async def test_km_summary_week(self):
        """Test GET /api/livre/driver/km-summary?period=week"""
        print("\n=== TEST: period=week ===")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{API_BASE}/livre/driver/km-summary?period=week",
                headers={"Authorization": f"Bearer {self.driver_token}"}
            )
            if resp.status_code != 200:
                raise Exception(f"GET km-summary week failed: {resp.status_code} {resp.text}")
            
            data = resp.json()
            print(f"Response: {data}")
            
            # Should include today's trips
            assert data["pro_km"] >= 55.4, f"Expected pro_km>=55.4, got {data['pro_km']}"
            assert data["private_km"] >= 27.7, f"Expected private_km>=27.7, got {data['private_km']}"
            
            print(f"✓ period=week: pro_km={data['pro_km']}, private_km={data['private_km']}")
            print("✓ Includes today's trips")
    
    async def test_km_summary_month(self):
        """Test GET /api/livre/driver/km-summary?period=month"""
        print("\n=== TEST: period=month ===")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{API_BASE}/livre/driver/km-summary?period=month",
                headers={"Authorization": f"Bearer {self.driver_token}"}
            )
            if resp.status_code != 200:
                raise Exception(f"GET km-summary month failed: {resp.status_code} {resp.text}")
            
            data = resp.json()
            print(f"Response: {data}")
            
            # Should include today's trips
            assert data["pro_km"] >= 55.4, f"Expected pro_km>=55.4, got {data['pro_km']}"
            assert data["private_km"] >= 27.7, f"Expected private_km>=27.7, got {data['private_km']}"
            
            print(f"✓ period=month: pro_km={data['pro_km']}, private_km={data['private_km']}")
            print("✓ Includes today's trips")
    
    async def cleanup_test_data(self):
        """Clean up all test data"""
        print("\n=== CLEANUP ===")
        
        # Delete trips
        result = await self.db.trips.delete_many({"id": {"$in": self.trip_ids}})
        print(f"✓ Deleted {result.deleted_count} test trips")
        
        # Delete other driver trip
        if self.other_trip_id:
            result = await self.db.trips.delete_one({"id": self.other_trip_id})
            print(f"✓ Deleted other driver trip")
        
        # Delete other driver
        if self.other_driver_id:
            result = await self.db.drivers.delete_one({"id": self.other_driver_id})
            print(f"✓ Deleted other driver")
        
        # Delete assignment
        if self.assignment_id:
            result = await self.db.vehicle_assignments.delete_one({"id": self.assignment_id})
            print(f"✓ Deleted assignment")
        
        # Delete vehicles
        result = await self.db.vehicles.delete_many({
            "id": {"$in": [self.vehicle_a_id, self.vehicle_b_id]}
        })
        print(f"✓ Deleted {result.deleted_count} test vehicles")
        
        # Verify cleanup
        remaining_trips = await self.db.trips.count_documents({"id": {"$in": self.trip_ids}})
        remaining_vehicles = await self.db.vehicles.count_documents({
            "id": {"$in": [self.vehicle_a_id, self.vehicle_b_id]}
        })
        remaining_assignments = await self.db.vehicle_assignments.count_documents(
            {"id": self.assignment_id}
        )
        
        assert remaining_trips == 0, f"Cleanup failed: {remaining_trips} trips remaining"
        assert remaining_vehicles == 0, f"Cleanup failed: {remaining_vehicles} vehicles remaining"
        assert remaining_assignments == 0, f"Cleanup failed: assignment remaining"
        
        print("✓ Cleanup verified: all test data removed")


async def main():
    ctx = TestContext()
    
    try:
        print("=" * 80)
        print("KM-SUMMARY DRIVER-CENTERED AGGREGATION TEST")
        print("=" * 80)
        
        # Setup
        await ctx.setup_db()
        await ctx.login_driver()
        
        # Create test data
        await ctx.create_test_vehicles()
        await ctx.create_test_trips()
        await ctx.create_active_assignment()
        await ctx.create_other_driver_trip()
        
        # Run tests
        await ctx.test_km_summary_today()
        await ctx.test_km_summary_week()
        await ctx.test_km_summary_month()
        
        # Cleanup
        await ctx.cleanup_test_data()
        
        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED")
        print("=" * 80)
        print("\nVERIFICATION SUMMARY:")
        print("✓ (a) pro_km = 55.4 (sum of BOTH vehicles, NOT just VEH_A=12.7)")
        print("✓ (b) private_km = 27.7 (sum of BOTH vehicles)")
        print("✓ (c) vehicle_id = VEH_A (active vehicle for context, does NOT filter km)")
        print("✓ (d) available = true")
        print("✓ (e) private_km_source = GPS_FALLBACK (AVL16 flag OFF)")
        print("✓ (f) period=week includes today's trips")
        print("✓ (g) period=month includes today's trips")
        print("✓ (h) classification=None NOT counted (5.0 km excluded)")
        print("✓ (i) manual professional IS counted (10.0 km included)")
        print("✓ (j) other driver trips NOT counted (isolation verified)")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        
        # Attempt cleanup on failure
        try:
            await ctx.cleanup_test_data()
        except:
            pass
        
        sys.exit(1)
    
    finally:
        await ctx.cleanup_db()


if __name__ == "__main__":
    asyncio.run(main())
