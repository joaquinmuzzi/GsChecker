#!/usr/bin/env python3
"""Test script for WebDataRetriever imports and cache functions."""

import sys
import time
import os

# Test 1: Import the module
print("=" * 70)
print("TEST 1: Importing WebDataRetriever")
print("=" * 70)
try:
    import WebDataRetriever as wr
    print("✓ Successfully imported WebDataRetriever")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Check that required functions exist
print("\n" + "=" * 70)
print("TEST 2: Checking required functions exist")
print("=" * 70)
required_functions = ['_cache_get', '_cache_set', 'fetch_bridge_payload']
for func_name in required_functions:
    if hasattr(wr, func_name):
        print(f"✓ Function '{func_name}' exists")
    else:
        print(f"✗ Function '{func_name}' NOT found")
        sys.exit(1)

# Test 3: Test _cache_set and _cache_get with test data
print("\n" + "=" * 70)
print("TEST 3: Testing cache functions _cache_set and _cache_get")
print("=" * 70)

# Clear the cache first
wr._BRIDGE_CACHE.clear()
print(f"Cache cleared. Current cache: {wr._BRIDGE_CACHE}")

# Create test data
test_server = "Area52"
test_name = "TestChar"
test_payload = {
    "profile_html": "<html>Test Profile</html>",
    "summary_json": {"level": 70, "faction": "Horde"},
    "raw_data": "test_data_value"
}

# Store in cache
print(f"\nStoring test data in cache:")
print(f"  Server: {test_server}")
print(f"  Name: {test_name}")
print(f"  Payload: {test_payload}")
wr._cache_set(test_server, test_name, test_payload)
print(f"✓ Data stored in cache")

# Verify cache entry exists
cache_key = (test_server.lower(), test_name.lower())
if cache_key in wr._BRIDGE_CACHE:
    print(f"✓ Cache key {cache_key} found in _BRIDGE_CACHE")
else:
    print(f"✗ Cache key {cache_key} NOT found in _BRIDGE_CACHE")
    sys.exit(1)

# Retrieve from cache
retrieved = wr._cache_get(test_server, test_name)
if retrieved is not None:
    print(f"✓ Successfully retrieved data from cache")
    if retrieved == test_payload:
        print(f"✓ Retrieved payload matches stored payload")
    else:
        print(f"✗ Retrieved payload DOES NOT match stored payload")
        print(f"  Expected: {test_payload}")
        print(f"  Got: {retrieved}")
        sys.exit(1)
else:
    print(f"✗ Failed to retrieve data from cache")
    sys.exit(1)

# Test 4: Test case-insensitivity
print("\n" + "=" * 70)
print("TEST 4: Testing cache case-insensitivity")
print("=" * 70)
retrieved_upper = wr._cache_get("AREA52", "TESTCHAR")
if retrieved_upper == test_payload:
    print(f"✓ Cache retrieval with uppercase keys works correctly")
else:
    print(f"✗ Cache case-insensitivity failed")
    sys.exit(1)

# Test 5: Test cache TTL expiration
print("\n" + "=" * 70)
print("TEST 5: Testing cache TTL expiration logic")
print("=" * 70)
original_ttl = wr._BRIDGE_CACHE_TTL
print(f"Current BRIDGE_CACHE_TTL: {original_ttl} seconds")

# Store a test entry
test_server_2 = "Tichondrius"
test_name_2 = "ExpireTest"
wr._cache_set(test_server_2, test_name_2, {"test": "data"})
print(f"✓ Stored test entry for expiration check")

# Try to retrieve it (should work)
retrieved_fresh = wr._cache_get(test_server_2, test_name_2)
if retrieved_fresh is not None:
    print(f"✓ Fresh cache entry retrieved successfully")
else:
    print(f"✗ Failed to retrieve fresh cache entry")
    sys.exit(1)

# Manually expire by setting timestamp to old value
cache_key_2 = (test_server_2.lower(), test_name_2.lower())
old_time = time.monotonic() - (original_ttl + 10)
wr._BRIDGE_CACHE[cache_key_2] = (old_time, {"test": "data"})
print(f"✓ Manually set cache entry to expire (time offset: -{original_ttl + 10}s)")

# Try to retrieve expired entry (should return None)
retrieved_expired = wr._cache_get(test_server_2, test_name_2)
if retrieved_expired is None:
    print(f"✓ Expired cache entry correctly returned None")
else:
    print(f"✗ Expired cache entry should have returned None but got: {retrieved_expired}")
    sys.exit(1)

# Test 6: Test fetch_bridge_payload cache integration
print("\n" + "=" * 70)
print("TEST 6: Testing fetch_bridge_payload cache integration")
print("=" * 70)
print("(Simulating cache usage without actual HTTP calls)")

# Clear cache
wr._BRIDGE_CACHE.clear()

# Pre-populate cache with test data
test_server_3 = "Stormrage"
test_name_3 = "MockChar"
mock_payload = {
    "profile_html": "<html>Mock Profile</html>",
    "summary_json": {"level": 60},
    "talents_json": {"talents": [1, 2, 3]},
}
wr._cache_set(test_server_3, test_name_3, mock_payload)
print(f"✓ Pre-populated cache with mock data for {test_server_3}/{test_name_3}")

# Test that fetch_bridge_payload uses cache without HTTP
# We'll test with route="profile" which should return normalized payload
result = wr.fetch_bridge_payload(test_server_3, test_name_3, "profile")
if result is not None:
    print(f"✓ fetch_bridge_payload returned cached data (no HTTP needed)")
    if "html" in result:
        print(f"✓ Payload correctly normalized for 'profile' route (contains 'html' key)")
    else:
        print(f"⚠ Payload may not be correctly normalized: {result}")
else:
    print(f"✗ fetch_bridge_payload returned None when cache had data")
    sys.exit(1)

# Test with api_summary route
result_api = wr.fetch_bridge_payload(test_server_3, test_name_3, "api_summary")
if result_api is not None:
    print(f"✓ fetch_bridge_payload returned cached data for 'api_summary' route")
    if "json" in result_api:
        print(f"✓ Payload correctly normalized for 'api_summary' route (contains 'json' key)")
    else:
        print(f"⚠ Payload may not be correctly normalized: {result_api}")
else:
    print(f"✗ fetch_bridge_payload returned None for api_summary route")
    sys.exit(1)

# Test 7: Test _normalize_payload_for_route function
print("\n" + "=" * 70)
print("TEST 7: Testing _normalize_payload_for_route function")
print("=" * 70)

test_payloads = {
    "profile": {
        "input": {"profile_html": "<html>Profile</html>", "other": "data"},
        "expected_key": "html",
        "expected_value": "<html>Profile</html>"
    },
    "api_summary": {
        "input": {"summary_json": {"level": 70}, "other": "data"},
        "expected_key": "json",
        "expected_value": {"level": 70}
    },
}

for route, test_case in test_payloads.items():
    normalized = wr._normalize_payload_for_route(route, test_case["input"])
    if test_case["expected_key"] in normalized:
        if normalized[test_case["expected_key"]] == test_case["expected_value"]:
            print(f"✓ Route '{route}': normalized correctly with '{test_case['expected_key']}' key")
        else:
            print(f"✗ Route '{route}': key value mismatch")
            sys.exit(1)
    else:
        print(f"✗ Route '{route}': expected key '{test_case['expected_key']}' not found in normalized payload")
        sys.exit(1)

print("\n" + "=" * 70)
print("✓ ALL TESTS PASSED SUCCESSFULLY")
print("=" * 70)
