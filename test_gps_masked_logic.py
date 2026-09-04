#!/usr/bin/env python3
"""Unit tests for _gps_masked_from_point function extracted from d3b_snapshot.py"""

def _gps_masked_from_point(lat, lng):
    """Retourne True si la position (lat,lng) est réellement à 0,0 (masquée),
    False si coordonnées réelles, None si indéterminable."""
    if lat is None or lng is None:
        return None
    try:
        return abs(float(lat)) < 1e-6 and abs(float(lng)) < 1e-6
    except (TypeError, ValueError):
        return None


def test_all():
    """Run all 6 test cases"""
    results = []
    
    # Test 1: (0, 0) should return True (masked)
    result1 = _gps_masked_from_point(0, 0)
    expected1 = True
    results.append(("Test 1: (0, 0)", result1, expected1, result1 == expected1))
    
    # Test 2: (0.0000001, 0.0) should return True (within tolerance)
    result2 = _gps_masked_from_point(0.0000001, 0.0)
    expected2 = True
    results.append(("Test 2: (0.0000001, 0.0)", result2, expected2, result2 == expected2))
    
    # Test 3: (46.2, 6.15) should return False (real Geneva coords)
    result3 = _gps_masked_from_point(46.2, 6.15)
    expected3 = False
    results.append(("Test 3: (46.2, 6.15)", result3, expected3, result3 == expected3))
    
    # Test 4: (None, 6.15) should return None (indeterminate)
    result4 = _gps_masked_from_point(None, 6.15)
    expected4 = None
    results.append(("Test 4: (None, 6.15)", result4, expected4, result4 is expected4))
    
    # Test 5: (46.2, None) should return None (indeterminate)
    result5 = _gps_masked_from_point(46.2, None)
    expected5 = None
    results.append(("Test 5: (46.2, None)", result5, expected5, result5 is expected5))
    
    # Test 6: ("abc", "def") should return None (non-numeric, no crash)
    result6 = _gps_masked_from_point("abc", "def")
    expected6 = None
    results.append(("Test 6: ('abc', 'def')", result6, expected6, result6 is expected6))
    
    # Print results
    print("\n" + "="*70)
    print("UNIT TEST RESULTS FOR _gps_masked_from_point")
    print("="*70)
    all_passed = True
    for test_name, result, expected, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} | {test_name}")
        print(f"       Result: {result}, Expected: {expected}")
        if not passed:
            all_passed = False
    
    print("="*70)
    if all_passed:
        print("✓ ALL 6 TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
    print("="*70 + "\n")
    
    return all_passed


if __name__ == "__main__":
    success = test_all()
    exit(0 if success else 1)
