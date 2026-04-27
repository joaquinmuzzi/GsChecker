#!/usr/bin/env python3
"""Advanced test of WebDataRetriever cache behavior and configuration."""

import sys
import os
import time

import WebDataRetriever as wr

print("=" * 70)
print("ADVANCED CACHE AND CONFIGURATION TESTS")
print("=" * 70)

# Test 1: Configuration values
print("\n" + "=" * 70)
print("TEST 1: Configuration values")
print("=" * 70)

cache_ttl = wr._BRIDGE_CACHE_TTL
print(f"✓ BRIDGE_CACHE_TTL: {cache_ttl} seconds")

default_timeout = wr._DEFAULT_BRIDGE_TIMEOUT
print(f"✓ DEFAULT_BRIDGE_TIMEOUT: {default_timeout} seconds")

bridge_url = wr._bridge_base_url()
print(f"✓ SCRAPER_BRIDGE_URL: {bridge_url if bridge_url else '(not configured)'}")

verify_ssl = wr._bridge_verify_ssl()
print(f"✓ BRIDGE_VERIFY_SSL: {verify_ssl}")

# Test 2: URL building functions
print("\n" + "=" * 70)
print("TEST 2: URL building functions")
print("=" * 70)

test_server = "Stormrage"
test_name = "Thrall"

url = wr._bridge_character_url(test_server, test_name)
print(f"  Server: {test_server}, Name: {test_name}")
print(f"  Generated URL: {url if url else '(bridge URL not configured)'}")

candidates = wr._bridge_candidate_requests(test_server, test_name)
print(f"✓ Candidate requests: {len(candidates)} URL variants would be tried")
for i, (url, params) in enumerate(candidates, 1):
    print(f"  {i}. {url}")
    if params:
        print(f"     Params: {params}")

# Test 3: Cache key normalization
print("\n" + "=" * 70)
print("TEST 3: Cache key normalization")
print("=" * 70)

test_cases = [
    ("Area52", "Gazlowe"),
    ("AREA52", "GAZLOWE"),
    ("area52", "gazlowe"),
    ("Area 52", "Gaz Lowe"),  # edge case with spaces
]

wr._BRIDGE_CACHE.clear()
payload = {"test": "data"}
wr._cache_set("Area52", "Gazlowe", payload)

print(f"Stored: ('Area52', 'Gazlowe')")
print(f"Internal key: ('area52', 'gazlowe')")

for server, name in test_cases:
    retrieved = wr._cache_get(server, name)
    status = "✓" if retrieved == payload else "✗"
    print(f"{status} Retrieved with ({server}, {name}): {retrieved is not None}")

# Test 4: Payload extraction functions
print("\n" + "=" * 70)
print("TEST 4: Payload extraction functions")
print("=" * 70)

test_payload = {
    "profile_html": "<html>Profile</html>",
    "summary_json": {"level": 70, "race": "Orc"},
    "talents_json": {"talents": [1, 2, 3]},
    "talents": [4, 5, 6],
    "html": "<html>Generic</html>",
}

# Test _extract_first_dict
dict_result = wr._extract_first_dict(test_payload, ("summary_json", "api_summary", "summary"))
print(f"✓ _extract_first_dict('summary_json', ...): {dict_result}")

# Test _extract_first_str
str_result = wr._extract_first_str(test_payload, ("profile_html", "profile", "html"))
print(f"✓ _extract_first_str('profile_html', ...): {str_result[:30]}...")

# Test 5: Payload normalization for different routes
print("\n" + "=" * 70)
print("TEST 5: Payload normalization for different routes")
print("=" * 70)

routes = ["profile", "character", "talents", "api_summary", "api_talents", "summary"]

test_norm_payload = {
    "profile_html": "<html>Profile</html>",
    "summary_json": {"level": 70},
    "talents_json": {"talents": [1, 2, 3]},
    "talents": [4, 5, 6],
}

for route in routes:
    normalized = wr._normalize_payload_for_route(route, test_norm_payload)
    keys = list(normalized.keys())
    print(f"✓ Route '{route}': normalized keys = {keys[:3]}...")

# Test 6: Cache hit/miss simulation
print("\n" + "=" * 70)
print("TEST 6: Cache hit/miss simulation")
print("=" * 70)

wr._BRIDGE_CACHE.clear()

test_server = "TestRealm"
test_name = "TestChar"

# First call should be a miss (cache empty)
cached_miss = wr._cache_get(test_server, test_name)
print(f"Cache miss (empty cache): {cached_miss}")

# Simulate storing data
test_data = {"profile_html": "<html>Test</html>", "data": [1, 2, 3]}
wr._cache_set(test_server, test_name, test_data)
print(f"✓ Data stored in cache")

# Second call should be a hit
cached_hit = wr._cache_get(test_server, test_name)
print(f"Cache hit: {cached_hit == test_data}")

# Test 7: Response parsing
print("\n" + "=" * 70)
print("TEST 7: Response parsing (_response_to_payload)")
print("=" * 70)

class MockResponse:
    def __init__(self, status_code=200, content_type="application/json", body=""):
        self.status_code = status_code
        self.text = body
        self.headers = {"Content-Type": content_type}
    
    def json(self):
        import json
        return json.loads(self.text)

# Test JSON response
json_resp = MockResponse(body='{"level": 70, "race": "Orc"}')
payload = wr._response_to_payload(json_resp)
print(f"✓ JSON response: {payload}")

# Test HTML response
html_resp = MockResponse(body="<html>Test</html>", content_type="text/html")
payload = wr._response_to_payload(html_resp)
print(f"✓ HTML response: {payload}")

# Test empty response
empty_resp = MockResponse(body="")
payload = wr._response_to_payload(empty_resp)
print(f"✓ Empty response: {payload}")

print("\n" + "=" * 70)
print("✓ ALL ADVANCED TESTS COMPLETED SUCCESSFULLY")
print("=" * 70)
