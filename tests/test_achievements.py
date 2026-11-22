"""Tests for _fetch_achievements parallel fetching and stale cache fallback."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from src.functions.warmane import _fetch_achievements
from src.schemas.constants import ACHIEVEMENTS_CACHE


@pytest.fixture(autouse=True)
def _clear_cache():
    ACHIEVEMENTS_CACHE.clear()
    yield
    ACHIEVEMENTS_CACHE.clear()


def _make_category_response(*achievement_ids: str) -> dict:
    divs = ""
    for ach_id in achievement_ids:
        divs += f'<div class="achievement" id="ach{ach_id}"></div>'
    return {"content": divs}


def _make_empty_response() -> dict:
    return {"content": ""}


class TestParallelFetching:
    """Warmane sacó el límite por IP (noviembre 2026): las categorías se piden
    juntas y el token bucket del armory es el único que pone el ritmo."""

    @patch("src.functions.warmane._warmane_post_json_with_scheme_fallback")
    @patch("src.functions.warmane.ARMORY_LIMITER")
    @patch("src.functions.warmane.time.sleep")
    def test_categories_fetched_in_parallel(self, mock_sleep, mock_limiter, mock_post):
        # Las 4 llamadas tienen que estar en vuelo a la vez para pasar la
        # barrera; en serie, la primera esperaría sola hasta el timeout.
        barrier = threading.Barrier(4, timeout=5)
        fetched = []

        def track_call(path, headers, data):
            cat = data.get("category")
            fetched.append(cat)
            barrier.wait()
            if cat in (14922, 14923):
                return _make_category_response("4817")
            return _make_category_response("4531")

        mock_post.side_effect = track_call

        payload = _fetch_achievements("Testchar", "Lordaeron")

        assert sorted(fetched) == sorted([15041, 15042, 14922, 14923])
        assert payload["storming_10n_achieved"] is True
        assert payload["halion_10n_achieved"] is True
        assert payload["complete"] is True
        # Sin pausas fijas ni tokens extra entre categorías.
        mock_sleep.assert_not_called()
        mock_limiter.acquire.assert_not_called()

    @patch("src.functions.warmane._warmane_post_json_with_scheme_fallback")
    @patch("src.functions.warmane.ARMORY_LIMITER")
    @patch("src.functions.warmane.time.sleep")
    def test_rescue_refetches_ruby_sanctum_in_parallel(self, mock_sleep, mock_limiter, mock_post):
        """Sin Halion en la primera pasada, se vuelven a pedir las dos
        categorías de Ruby Sanctum, también juntas."""
        rescue_barrier = threading.Barrier(2, timeout=5)
        calls = []

        def side_effect(path, headers, data):
            cat = data.get("category")
            calls.append(cat)
            if cat in (14922, 14923):
                if calls.count(cat) == 1:
                    return _make_empty_response()
                rescue_barrier.wait()
                return _make_category_response("4817")
            return _make_category_response("4531")

        mock_post.side_effect = side_effect

        payload = _fetch_achievements("Testchar", "Lordaeron")

        assert calls.count(14922) == 2
        assert calls.count(14923) == 2
        assert payload["halion_10n_achieved"] is True
        mock_sleep.assert_not_called()

    @patch("src.functions.warmane._warmane_post_json_with_scheme_fallback")
    def test_failed_category_marks_payload_incomplete(self, mock_post):
        def side_effect(path, headers, data):
            if data.get("category") == 15042:
                return None
            return _make_category_response("4531")

        mock_post.side_effect = side_effect

        payload = _fetch_achievements("Testchar", "Lordaeron")

        assert payload["complete"] is False


class TestStaleCacheFallback:
    @patch("src.functions.warmane._cache_get_stale")
    @patch("src.functions.warmane._warmane_post_json_with_scheme_fallback")
    @patch("src.functions.warmane.ARMORY_LIMITER")
    @patch("src.functions.warmane.time.sleep")
    def test_stale_cache_used_when_rs_empty_icc_ok(self, mock_sleep, mock_limiter, mock_post, mock_get_stale):
        def side_effect(path, headers, data):
            cat = data.get("category")
            if cat == 15041:
                return _make_category_response("4531")
            if cat == 15042:
                return _make_category_response("4604")
            return _make_empty_response()

        mock_post.side_effect = side_effect
        mock_limiter.acquire.return_value = None
        mock_get_stale.return_value = {
            "completed_ids": set(),
            "icc_10n_bosses": 4,
            "icc_25n_bosses": 4,
            "icc_10h_bosses": 0,
            "icc_25h_bosses": 0,
            "halion_10n_achieved": True,
            "halion_10h_achieved": False,
            "halion_25n_achieved": True,
            "halion_25h_achieved": False,
            "storming_10n_achieved": True,
            "storming_10h_achieved": False,
            "storming_25n_achieved": True,
            "storming_25h_achieved": False,
        }

        result = _fetch_achievements("Testchar", "Lordaeron")

        assert result["halion_10n_achieved"] is True
        assert result["halion_25n_achieved"] is True
        assert result["storming_10n_achieved"] is True
        mock_get_stale.assert_called_once()

    @patch("src.functions.warmane._cache_get_stale")
    @patch("src.functions.warmane._warmane_post_json_with_scheme_fallback")
    @patch("src.functions.warmane.ARMORY_LIMITER")
    @patch("src.functions.warmane.time.sleep")
    def test_stale_cache_not_used_when_both_empty(self, mock_sleep, mock_limiter, mock_post, mock_get_stale):
        mock_post.return_value = _make_empty_response()
        mock_limiter.acquire.return_value = None
        mock_get_stale.return_value = None

        result = _fetch_achievements("Testchar", "Lordaeron")

        assert result["halion_10n_achieved"] is False
        assert result["storming_10n_achieved"] is False
        mock_get_stale.assert_called_once()


class TestRescuePass:
    @patch("src.functions.warmane._warmane_post_json_with_scheme_fallback")
    @patch("src.functions.warmane.ARMORY_LIMITER")
    @patch("src.functions.warmane.time.sleep")
    def test_rescue_retries_rs_categories(self, mock_sleep, mock_limiter, mock_post):
        call_count = {"n": 0}

        def side_effect(path, headers, data):
            cat = data.get("category")
            call_count["n"] += 1
            if cat in (14922, 14923) and call_count["n"] <= 4:
                return _make_empty_response()
            if cat in (14922, 14923):
                return _make_category_response("4817")
            return _make_category_response("4531")

        mock_post.side_effect = side_effect
        mock_limiter.acquire.return_value = None

        result = _fetch_achievements("Testchar", "Lordaeron")

        assert result["halion_10n_achieved"] is True
