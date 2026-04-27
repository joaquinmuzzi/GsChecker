import os
import json
import time
from urllib.parse import quote_plus

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


BRIDGE_UNAVAILABLE_ERROR = "Error: El puente de scraping local no está disponible"

# ── In-process cache: one bridge call per (character, route) per TTL ────────
_BRIDGE_CACHE: dict[tuple[str, str, str], tuple[float, dict]] = {}
_BRIDGE_CACHE_TTL = int(os.getenv("BRIDGE_CACHE_TTL", "120"))


def _route_cache_key(route: str, extra_params: dict | None = None) -> str:
    base = str(route or "").strip().lower()
    if not isinstance(extra_params, dict) or not extra_params:
        return base

    parts = []
    for key in sorted(extra_params.keys()):
        value = extra_params.get(key)
        if value is None:
            continue
        parts.append(f"{str(key).strip().lower()}={str(value).strip()}")

    if not parts:
        return base
    return f"{base}?{'&'.join(parts)}"


def _cache_get(server: str, name: str, route: str = "") -> dict | None:
    entry = _BRIDGE_CACHE.get((server.lower(), name.lower(), route.lower()))
    if entry and (time.monotonic() - entry[0]) < _BRIDGE_CACHE_TTL:
        return entry[1]
    return None


def _cache_set(server: str, name: str, payload: dict, route: str = "") -> None:
    _BRIDGE_CACHE[(server.lower(), name.lower(), route.lower())] = (time.monotonic(), payload)


def _is_cloudflare_payload(payload: dict) -> bool:
    """Return True if the bridge payload contains a Cloudflare challenge page."""
    html = payload.get("html") or ""
    if not isinstance(html, str) or not html.strip():
        return False
    low = html.lower()
    # If armory markers are present, it's real content.
    if any(m in low for m in ("character-sheet", "item-model", "profile-content", "level-race-class")):
        return False
    # Cloudflare challenge markers.
    return any(m in low for m in (
        "challenges.cloudflare.com", "cf-challenge", "cf-turnstile",
        "just a moment", "un momento", "verify you are human",
    ))
def _bridge_verify_ssl() -> bool:
    raw = (os.getenv("BRIDGE_VERIFY_SSL") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False

    # LocalTunnel subdomains often have certificate mismatches.
    base = _bridge_base_url().lower()
    if ".loca.lt" in base or "localhost" in base or "127.0.0.1" in base:
        return False
    return True


# Headed-browser scraping can take 30–60 s. Use a generous default.
_DEFAULT_BRIDGE_TIMEOUT = int(os.getenv("BRIDGE_TIMEOUT", "60"))


def _extract_first_dict(payload: dict, keys: tuple[str, ...]):
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return None


def _extract_first_str(payload: dict, keys: tuple[str, ...]):
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _normalize_payload_for_route(route: str, payload: dict) -> dict:
    normalized = dict(payload)

    route_to_html_keys = {
        "profile": ("profile_html", "profile", "html"),
        "talents": ("talents_html", "talents_page", "talents", "html"),
        "summary": ("summary_html", "summary", "html"),
        "character": ("character_html", "profile_html", "profile", "html"),
    }
    route_to_json_keys = {
        "api_summary": ("summary_json", "api_summary", "summary"),
        "api_talents": ("talents_json", "api_talents", "talents_data"),
    }

    html_keys = route_to_html_keys.get(route)
    if html_keys:
        html = _extract_first_str(payload, html_keys)
        if isinstance(html, str):
            normalized["html"] = html

    json_keys = route_to_json_keys.get(route)
    if json_keys:
        js = _extract_first_dict(payload, json_keys)
        if isinstance(js, dict):
            normalized["json"] = js
        elif route == "api_talents":
            talents = payload.get("talents")
            if isinstance(talents, list):
                normalized["json"] = {"talents": talents}

    return normalized


def _bridge_base_url() -> str:
    return (os.getenv("SCRAPER_BRIDGE_URL") or "").strip().rstrip("/")


def _bridge_character_url(server: str, name: str) -> str:
    base = _bridge_base_url()
    if not base:
        return ""
    return (
        f"{base}/get_char/"
        f"{quote_plus(str(server or '').strip())}/"
        f"{quote_plus(str(name or '').strip())}"
    )


def _bridge_candidate_requests(server: str, name: str):
    base = _bridge_base_url()
    clean_server = quote_plus(str(server or "").strip())
    clean_name = quote_plus(str(name or "").strip())
    if not base:
        return []

    # Only the primary contract. No fallbacks to incompatible routes.
    candidates = [
        (f"{base}/get_char/{clean_server}/{clean_name}", None),
    ]
    return candidates


def _bridge_requests_for_route(
    route: str,
    server: str,
    name: str,
    extra_params: dict | None = None,
):
    """Build candidate bridge requests for a logical route.

    The bridge exposes separate endpoints for profile/talents/statistics, while
    callers in this project use higher-level route names.
    """
    base = _bridge_base_url()
    clean_server = quote_plus(str(server or "").strip())
    clean_name = quote_plus(str(name or "").strip())
    if not base:
        return []

    route = (route or "character").strip().lower()
    params = dict(extra_params or {})

    if route == "character":
        # Gear score parsing needs equipped items rendered.
        params.setdefault("wait_selector", ".item-model")
        return [(f"{base}/get_char/{clean_server}/{clean_name}", params or None)]

    if route in {"profile", "summary", "api_summary"}:
        params.setdefault("wait_selector", "#character-sheet")
        return [(f"{base}/get_char/{clean_server}/{clean_name}", params or None)]

    if route in {"talents", "api_talents"}:
        params.setdefault("wait_selector", "[data-spec]")
        return [
            (f"{base}/get_char_talents/{clean_server}/{clean_name}", params or None)
        ]

    if route in {"statistics"}:
        params.setdefault("wait_selector", "#data-table-list")
        return [
            (f"{base}/get_char_statistics/{clean_server}/{clean_name}", params or None)
        ]

    if route in {"achievements"}:
        params.setdefault("wait_selector", ".achievement-list")
        return [
            (
                f"{base}/get_char_achievements/{clean_server}/{clean_name}",
                params or None,
            )
        ]

    if route == "guild_summary":
        guild = quote_plus(str((extra_params or {}).get("guild") or "").strip())
        if guild:
            return [
                (
                    f"{base}/get_guild_summary/{clean_server}/{guild}/{clean_name}",
                    params or None,
                )
            ]

    # Fallback to the primary route contract.
    return _bridge_candidate_requests(server, name)


def _response_to_payload(resp):
    content_type = str(resp.headers.get("Content-Type") or "").lower()
    body = resp.text if isinstance(resp.text, str) else ""

    if "application/json" in content_type:
        try:
            data = resp.json()
            if isinstance(data, dict):
                return data
        except ValueError:
            pass

    if body.strip().startswith("{"):
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                return data
        except ValueError:
            pass

    if body.strip():
        return {"html": body}

    return None


def fetch_bridge_payload(
    server: str,
    name: str,
    route: str,
    extra_params: dict | None = None,
    timeout: int | None = None,
):
    """Fetch bridge payload using SCRAPER_BRIDGE_URL/get_char/<realm>/<name>.

    Returns a dict payload on success, or None when bridge is unavailable.
    The response is cached in-process for BRIDGE_CACHE_TTL seconds (default 120)
    so every function that parses the same character reuses one single HTTP call.
    """
    # ── Cache hit: return stored payload immediately ─────────────────────────
    cache_key = _route_cache_key(route, extra_params)
    cached = _cache_get(server, name, cache_key)
    if cached is not None:
        return _normalize_payload_for_route(route, cached)

    api_secret = os.getenv("API_SECRET") or ""
    candidates = _bridge_requests_for_route(route, server, name, extra_params)

    if not candidates:
        return None

    effective_timeout = timeout if timeout is not None else _DEFAULT_BRIDGE_TIMEOUT
    headers = {"X-API-KEY": api_secret, "Accept": "application/json"}
    verify_ssl = _bridge_verify_ssl()
    for url, params in candidates:
        try:
            resp = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=effective_timeout,
                verify=verify_ssl,
            )
            if resp.status_code >= 500:
                continue
            payload = _response_to_payload(resp)
            if isinstance(payload, dict):
                # ── Cache miss resolved: store raw payload ────────────────
                if _is_cloudflare_payload(payload):
                    continue
                # ── Cache miss resolved: store raw payload ────────────────
                _cache_set(server, name, payload, cache_key)
                return _normalize_payload_for_route(route, payload)
        except requests.RequestException:
            continue

    return None


def fetch_html_via_bridge(
    server: str,
    name: str,
    route: str,
    extra_params: dict | None = None,
    timeout: int | None = None,
) -> str:
    """Return payload['html'] from bridge, or a clean bridge error message."""
    payload = fetch_bridge_payload(server, name, route, extra_params, timeout)
    if not isinstance(payload, dict):
        return BRIDGE_UNAVAILABLE_ERROR

    html = payload.get("html")
    if isinstance(html, str):
        return html
    return BRIDGE_UNAVAILABLE_ERROR
