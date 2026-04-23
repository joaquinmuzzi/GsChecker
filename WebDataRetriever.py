import os

import requests


BRIDGE_UNAVAILABLE_ERROR = "Error: El puente de scraping local no está disponible"


def fetch_html_via_bridge(target_url: str, timeout: int = 8) -> str:
    """Fetch HTML through the local scraping bridge.

    Returns the html string from the bridge JSON response (`html` field),
    or a clean error message when the bridge is unavailable.
    """
    bridge_url = (os.getenv("SCRAPER_BRIDGE_URL") or "").strip()
    api_secret = os.getenv("API_SECRET") or ""

    if not bridge_url:
        return BRIDGE_UNAVAILABLE_ERROR

    headers = {"X-API-KEY": api_secret}
    try:
        resp = requests.get(
            bridge_url,
            params={"url": target_url},
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        html = payload.get("html") if isinstance(payload, dict) else None
        if isinstance(html, str):
            return html
    except requests.RequestException:
        return BRIDGE_UNAVAILABLE_ERROR
    except ValueError:
        return BRIDGE_UNAVAILABLE_ERROR

    return BRIDGE_UNAVAILABLE_ERROR
