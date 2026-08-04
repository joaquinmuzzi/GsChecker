"""Tests para src.functions.rate_limit (TokenBucket + CircuitBreaker + is_cf_1015).

Estos tests son los que respaldan el fix del bug de 'no se encontró' —
si el circuit deja de abrirse cuando debe, o si is_cf_1015 deja de
detectar la firma, /p vuelve a mostrar falsos positivos.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.functions.rate_limit import CircuitBreaker, TokenBucket, is_cf_1015


class TestTokenBucket:
    def test_initial_burst_is_immediate(self):
        """capacity=3 tokens should be acquirable back-to-back with no wait."""
        tb = TokenBucket(rate=100.0, capacity=3)
        t0 = time.monotonic()
        for _ in range(3):
            assert tb.acquire(timeout=0.1) is True
        elapsed = time.monotonic() - t0
        assert elapsed < 0.05, f"burst took too long: {elapsed:.3f}s"

    def test_beyond_burst_waits_for_refill(self):
        """After draining the bucket, the next acquire waits for a refill."""
        tb = TokenBucket(rate=10.0, capacity=1)
        assert tb.acquire()
        t0 = time.monotonic()
        assert tb.acquire()
        elapsed = time.monotonic() - t0
        assert 0.05 <= elapsed <= 0.5, f"expected ~0.1s wait, got {elapsed:.3f}s"

    def test_acquire_respects_timeout(self):
        tb = TokenBucket(rate=0.1, capacity=1)
        tb.acquire()
        t0 = time.monotonic()
        got = tb.acquire(timeout=0.2)
        elapsed = time.monotonic() - t0
        assert got is False
        assert 0.15 <= elapsed <= 0.4

    def test_invalid_rate_and_capacity_rejected(self):
        with pytest.raises(ValueError):
            TokenBucket(rate=0, capacity=1)
        with pytest.raises(ValueError):
            TokenBucket(rate=-1, capacity=1)
        with pytest.raises(ValueError):
            TokenBucket(rate=1, capacity=0)

    def test_thread_safety_no_over_issue(self):
        """Given capacity=5 and rate=0, 10 threads racing must acquire at most 5."""
        tb = TokenBucket(rate=0.001, capacity=5)
        results = []
        lock = threading.Lock()

        def worker():
            got = tb.acquire(timeout=0.05)
            with lock:
                results.append(got)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        wins = sum(1 for r in results if r)
        assert wins == 5, f"expected 5 wins with capacity=5, got {wins}"


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.is_open() is False
        assert cb.recent_failure_count() == 0

    def test_fatal_opens_immediately(self):
        cb = CircuitBreaker(fatal_open_duration_s=0.5)
        cb.record_failure(fatal=True, reason="1015")
        assert cb.is_open() is True
        assert 0 < cb.seconds_until_close() <= 0.5

    def test_recovers_after_open_duration(self):
        cb = CircuitBreaker(fatal_open_duration_s=0.1)
        cb.record_failure(fatal=True, reason="test")
        assert cb.is_open()
        time.sleep(0.15)
        assert cb.is_open() is False

    def test_threshold_opens_only_after_N_failures(self):
        cb = CircuitBreaker(
            failure_threshold=3, open_duration_s=0.5, failure_window_s=10
        )
        cb.record_failure(reason="429")
        cb.record_failure(reason="429")
        assert cb.is_open() is False
        assert cb.recent_failure_count() == 2

        cb.record_failure(reason="429")
        assert cb.is_open() is True

    def test_failures_outside_window_dont_count(self):
        cb = CircuitBreaker(
            failure_threshold=3, open_duration_s=0.5, failure_window_s=0.1
        )
        cb.record_failure(reason="429")
        cb.record_failure(reason="429")
        time.sleep(0.15)

        cb.record_failure(reason="429")
        assert cb.is_open() is False, "old failures should have expired"
        assert cb.recent_failure_count() == 1

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3, failure_window_s=10)
        cb.record_failure(reason="429")
        cb.record_failure(reason="429")
        cb.record_success()
        assert cb.recent_failure_count() == 0

        cb.record_failure(reason="429")
        cb.record_failure(reason="429")
        assert cb.is_open() is False


class TestIsCf1015:
    @pytest.mark.parametrize(
        "body",
        [
            "error code: 1015",
            "some html\nerror code: 1015\nmore",
            "ERROR CODE: 1015",
            "Error Code: 1015 (rate limited)",
            b"error code: 1015",
        ],
    )
    def test_positive_cases(self, body):
        assert is_cf_1015(body) is True

    @pytest.mark.parametrize(
        "body",
        [
            "all good",
            "",
            None,
            "error code: 1020",
            "some other cloudflare page",
            b"",
        ],
    )
    def test_negative_cases(self, body):
        assert is_cf_1015(body) is False

    def test_invalid_bytes_dont_raise(self):
        """Malformed bytes must not propagate an exception."""
        assert is_cf_1015(b"\xff\xfe not utf8 error code: 1015") is True
        assert is_cf_1015(b"\xff\xfe not utf8") is False
