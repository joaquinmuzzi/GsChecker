"""El freno automático del armory: cualquier señal de rate limit (429, 5xx,
1015 o el "Too many requests" del API) tiene que pasar el token bucket al
ritmo lento. Si alguna se escapa, el modo rápido sigue pegándole al armory
mientras nos limita, y un 429 bloquea el bot para todos."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import profile_scraper
from src.functions import warmane
from src.schemas.constants import SUMMARY_CACHE


def _resp(status: int, text: str = "", json_payload=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.headers = {}
    resp.json.return_value = json_payload if json_payload is not None else {}
    return resp


@pytest.fixture
def armory_mocks():
    """Limiter y circuit falsos: los reales son globales y no deben quedar
    en modo lento ni abiertos para el resto de los tests."""
    limiter = MagicMock(name="ARMORY_LIMITER")
    api_limiter = MagicMock(name="ARMORY_API_LIMITER")
    circuit = MagicMock(name="ARMORY_CIRCUIT")
    circuit.is_open.return_value = False
    with (
        patch("src.functions.warmane.ARMORY_LIMITER", limiter),
        patch("src.functions.warmane.ARMORY_API_LIMITER", api_limiter),
        patch("src.functions.warmane.ARMORY_CIRCUIT", circuit),
        patch("src.functions.warmane._sleep_backoff"),
        patch("profile_scraper.ARMORY_LIMITER", limiter),
        patch("profile_scraper.ARMORY_API_LIMITER", api_limiter),
        patch("profile_scraper.ARMORY_CIRCUIT", circuit),
        patch("profile_scraper.time.sleep"),
    ):
        yield limiter, circuit, api_limiter


@pytest.fixture(autouse=True)
def _clear_summary_cache():
    SUMMARY_CACHE.clear()
    yield
    SUMMARY_CACHE.clear()


@pytest.mark.parametrize("status", [429, 503])
def test_armory_request_slows_down_on_rate_limit_status(armory_mocks, status):
    limiter, _, _ = armory_mocks
    with patch("src.functions.warmane.SESSION") as session:
        session.get.return_value = _resp(status)
        assert warmane._armory_request("GET", "/character/Kuvez/Lordaeron/profile", {}) is None

    limiter.slow_down.assert_called()
    assert str(status) in limiter.slow_down.call_args.kwargs["reason"]


def test_armory_request_slows_down_on_cloudflare_1015(armory_mocks):
    limiter, circuit, _ = armory_mocks
    with patch("src.functions.warmane.SESSION") as session:
        session.get.return_value = _resp(403, text="error code: 1015")
        assert warmane._armory_request("GET", "/character/Kuvez/Lordaeron/profile", {}) is None

    limiter.slow_down.assert_called_once()
    circuit.record_failure.assert_called_once()
    assert circuit.record_failure.call_args.kwargs["fatal"] is True


def test_armory_request_success_keeps_fast_mode(armory_mocks):
    limiter, _, _ = armory_mocks
    with patch("src.functions.warmane.SESSION") as session:
        session.get.return_value = _resp(200, text="<html></html>")
        assert warmane._armory_request("GET", "/character/Kuvez/Lordaeron/profile", {}) is not None

    limiter.slow_down.assert_not_called()
    limiter.acquire.assert_called_once()


def test_api_summary_too_many_requests_slows_down_only_the_api(armory_mocks):
    """Caso de la prueba del 2026-11-22: un /summary 0,5 s después de otro
    respondió HTTP 200 con {"error": "Too many requests."} mientras las páginas
    HTML seguían andando. Se frena el bucket del API, no el general."""
    limiter, _, api_limiter = armory_mocks
    with patch("src.functions.warmane.SESSION") as session:
        session.get.return_value = _resp(200, json_payload={"error": "Too many requests."})
        assert warmane._fetch_api_summary("Kuvez", "Lordaeron") is None

    api_limiter.slow_down.assert_called_once()
    limiter.slow_down.assert_not_called()


def test_api_summary_not_found_does_not_slow_down(armory_mocks):
    limiter, _, api_limiter = armory_mocks
    with patch("src.functions.warmane.SESSION") as session:
        session.get.return_value = _resp(200, json_payload={"error": "Character not found."})
        assert warmane._fetch_api_summary("Zzqxwvut", "Lordaeron") is None

    limiter.slow_down.assert_not_called()
    api_limiter.slow_down.assert_not_called()


def test_api_requests_also_wait_for_the_api_bucket(armory_mocks):
    limiter, _, api_limiter = armory_mocks
    with patch("src.functions.warmane.SESSION") as session:
        session.get.return_value = _resp(200, json_payload={"name": "Kuvez", "realm": "Lordaeron"})
        warmane._armory_request("GET", "/api/character/Kuvez/Lordaeron/summary", {})

    api_limiter.acquire.assert_called_once()
    limiter.acquire.assert_called_once()


def test_html_pages_skip_the_api_bucket(armory_mocks):
    limiter, _, api_limiter = armory_mocks
    with patch("src.functions.warmane.SESSION") as session:
        session.get.return_value = _resp(200, text="<html></html>")
        warmane._armory_request("GET", "/character/Kuvez/Lordaeron/profile", {})

    api_limiter.acquire.assert_not_called()
    limiter.acquire.assert_called_once()


@pytest.mark.parametrize(
    "resp",
    [_resp(429), _resp(502), _resp(200, text="error code: 1015")],
    ids=["429", "502", "1015"],
)
def test_profile_scraper_get_slows_down_on_rate_limit(armory_mocks, resp):
    limiter, _, _ = armory_mocks
    with patch("profile_scraper.SESSION") as session:
        session.get.return_value = resp
        profile_scraper._armory_get("http://armory.warmane.com/character/Kuvez/Lordaeron")

    limiter.slow_down.assert_called()
