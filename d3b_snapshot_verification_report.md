# D3B_SNAPSHOT.PY BUG FIX VERIFICATION REPORT

**Date:** 2026
**Script:** `/app/backend/scripts/d3b_snapshot.py`
**Bug Fixed:** GPS masking detection always returned `True` (false positive)

---

## VERIFICATION RESULTS: ✓ ALL CHECKS PASSED

### ✓ CHECK 1: COMPILATION
**Status:** PASS

```
python3 -m py_compile /app/backend/scripts/d3b_snapshot.py
✓ COMPILATION SUCCESS
```

**Evidence:** Script compiles without syntax errors.

---

### ✓ CHECK 2: UNIT TESTS FOR _gps_masked_from_point()
**Status:** PASS (6/6 tests passed)

| Test Case | Input | Expected | Result | Status |
|-----------|-------|----------|--------|--------|
| Test 1 | (0, 0) | True | True | ✓ PASS |
| Test 2 | (0.0000001, 0.0) | True | True | ✓ PASS |
| Test 3 | (46.2, 6.15) | False | False | ✓ PASS |
| Test 4 | (None, 6.15) | None | None | ✓ PASS |
| Test 5 | (46.2, None) | None | None | ✓ PASS |
| Test 6 | ("abc", "def") | None | None | ✓ PASS |

**Evidence:**
- Function correctly identifies masked GPS (0,0) → True
- Function correctly identifies real coordinates → False
- Function correctly handles None values → None (indeterminate)
- Function correctly handles non-numeric input → None (no crash)
- Tolerance check (< 1e-6) works correctly

---

### ✓ CHECK 3: OLD FAULTY LOGIC REMOVED, NEW LOGIC VERIFIED
**Status:** PASS

#### Old Faulty Pattern (REMOVED):
```
Searching for: gps.get('lat') or gps.get('lng')
Result: ✓ NOT FOUND (good - old pattern removed)
```

#### New Correct Logic (PRESENT):
```python
# Line 105-118: New function _last_gps_point()
async def _last_gps_point():
    """Lit la DERNIÈRE position réelle via track/read (get_state n'expose pas lat/lng directs).
    Retourne (lat, lng, ts) ou (None, None, None)."""
    ...
    r = await raw("track/read", {"tracker_id": TID, "from": d_from, "to": d_to,
                                 "simplify": False, "point_limit": 5})
    pts = r.get("list") or []
    if not pts:
        return None, None, None
    p = pts[-1]
    return p.get("lat"), p.get("lng"), p.get("get_time") or p.get("time")

# Line 136-137: Usage in capture()
lat, lng, pt_ts = await _last_gps_point()
gps_masked = _gps_masked_from_point(lat, lng)
```

**Evidence:**
- Line 106: Comment explicitly states "track/read (get_state n'expose pas lat/lng directs)"
- Line 112: Uses `track/read` endpoint which DOES expose lat/lng
- Line 135: Comment confirms "Masquage jugé sur la VRAIE position (track/read), PAS sur gps.lat/lng"
- Line 136: Calls `_last_gps_point()` to get real coordinates
- Line 137: Passes those coordinates to `_gps_masked_from_point()`

---

### ✓ CHECK 4: READ-ONLY VERIFICATION
**Status:** PASS

#### Forbidden Device Commands (NOT FOUND):
```
1. raw_command:   ✓ NOT FOUND in executable code
2. privatemode:   ✓ NOT FOUND in executable code
3. setparam:      ✓ NOT FOUND in executable code
```

#### Allowed READ-ONLY Endpoints (VERIFIED):
```python
Line 112: await raw("track/read", ...)              # ✓ READ-ONLY
Line 123: await raw("tracker/get_state", ...)       # ✓ READ-ONLY
Line 124: await raw("tracker/readings/list", ...)   # ✓ READ-ONLY
Line 125: await raw("tracker/get_counters", ...)    # ✓ READ-ONLY
Line 196: await raw("user/get_info", {})            # ✓ READ-ONLY
```

**Evidence:**
- Only 5 API calls in the entire script
- All 5 are READ-ONLY endpoints (user/get_info, tracker/get_state, tracker/readings/list, tracker/get_counters, track/read)
- No device command endpoints found
- Script header (lines 3-4) confirms: "ce script NE FAIT QUE LIRE. Il n'envoie AUCUNE commande"
- Multiple comments throughout confirm read-only nature (lines 234, 225)

---

## SUMMARY

### Bug Description:
The script always reported `gps_masked=True` because it tried to read `state.gps.lat` and `state.gps.lng` from the `tracker/get_state` endpoint, which does NOT expose these fields. This resulted in `lat=None, lng=None`, causing the old logic to incorrectly return `True` (masked) for all cases.

### Fix Applied:
1. Created new function `_gps_masked_from_point(lat, lng)` with proper logic:
   - Returns `True` only if both lat and lng are ~0,0 (within 1e-6 tolerance)
   - Returns `False` if real coordinates present
   - Returns `None` if indeterminate (None values or non-numeric)

2. Created new function `_last_gps_point()` that reads from `track/read` endpoint, which DOES expose `lat`/`lng` fields

3. Updated `capture()` function to use the new logic chain:
   - Call `_last_gps_point()` to get real coordinates from `track/read`
   - Pass those coordinates to `_gps_masked_from_point()`
   - Store result in `gps_masked` field

### Verification Results:
- ✓ Script compiles successfully
- ✓ All 6 unit tests pass for `_gps_masked_from_point()`
- ✓ Old faulty logic completely removed
- ✓ New correct logic properly implemented using `track/read`
- ✓ Script remains READ-ONLY (no device commands)

### Conclusion:
**ALL 4 VERIFICATION CHECKS PASSED**

The bug fix is correct and complete. The script now properly detects GPS masking by reading actual coordinates from the `track/read` endpoint instead of the non-existent fields in `tracker/get_state`.
