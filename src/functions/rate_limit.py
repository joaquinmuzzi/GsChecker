"""Token bucket + circuit breaker para armory.warmane.com.

El armory de Warmane rate-limita agresivamente por IP:
- ~5-6 requests en 10s → HTTP 429
- Abuso sostenido → "error code: 1015" (IP temporalmente baneada por Cloudflare)

Este módulo provee dos primitivas thread-safe que usa `src/functions/warmane.py` y
`profile_scraper.py` a través de la instancia global en `src/schemas/constants.py`:

- `TokenBucket`: espacia las llamadas salientes (ej: 1 request cada 2s con burst 3)
  para no llegar al 429 en primer lugar.
- `CircuitBreaker`: si detectamos 1015 en el body o varios 429 seguidos, "abrimos"
  el circuito durante N segundos; mientras esté abierto, los callers caen
  inmediatamente a stale cache sin tocar la red — así no prolongamos el ban.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("gschecker.rate_limit")


class TokenBucket:
    """Token bucket clásico. `acquire()` bloquea hasta que haya un token.

    Ejemplo: `TokenBucket(rate=0.5, capacity=3)` regenera 1 token cada 2s y
    permite ráfagas de hasta 3 tokens (útil para el primer `/personaje` del día,
    que se dispara con la cache vacía).
    """

    def __init__(self, rate: float, capacity: int) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._rate = float(rate)
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    def acquire(self, timeout: float | None = None) -> bool:
        """Bloquea hasta obtener 1 token. Retorna True si obtuvo token,
        False si expiró el timeout (None = espera indefinida)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                # tokens_needed = 1 - self._tokens → tiempo hasta tener 1 token
                wait = (1.0 - self._tokens) / self._rate

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait = min(wait, remaining)

            # cap para no dormir 30s de un tirón si algo se descalibra
            time.sleep(min(wait, 5.0))


class CircuitBreaker:
    """Circuit breaker minimalista con estado (closed | open).

    - `record_success()`: resetea el contador de fallos.
    - `record_failure(fatal=False)`: si `fatal=True` (ej: 1015), abre el
      circuito inmediatamente. Si no, cuenta un fallo y abre cuando llega
      al umbral.
    - `is_open()`: True mientras el ban de la IP siga vigente. El caller
      debería devolver stale cache y no tocar la red.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        open_duration_s: float = 60.0,
        fatal_open_duration_s: float = 90.0,
        failure_window_s: float = 30.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._open_duration_s = open_duration_s
        self._fatal_open_duration_s = fatal_open_duration_s
        self._failure_window_s = failure_window_s
        self._failures: list[float] = []
        self._open_until: float = 0.0
        self._lock = threading.Lock()

    def is_open(self) -> bool:
        with self._lock:
            return time.monotonic() < self._open_until

    def seconds_until_close(self) -> float:
        with self._lock:
            remaining = self._open_until - time.monotonic()
            return max(remaining, 0.0)

    def record_success(self) -> None:
        with self._lock:
            self._failures.clear()

    def record_failure(self, *, fatal: bool = False, reason: str = "") -> None:
        with self._lock:
            now = time.monotonic()
            if fatal:
                self._open_until = now + self._fatal_open_duration_s
                self._failures.clear()
                logger.warning(
                    "circuit tripped (fatal=%s reason=%s) — open for %.0fs",
                    fatal,
                    reason or "unspecified",
                    self._fatal_open_duration_s,
                )
                return

            # descartar fallos fuera de la ventana
            cutoff = now - self._failure_window_s
            self._failures = [ts for ts in self._failures if ts >= cutoff]
            self._failures.append(now)

            if len(self._failures) >= self._failure_threshold:
                self._open_until = now + self._open_duration_s
                self._failures.clear()
                logger.warning(
                    "circuit tripped (threshold reason=%s) — open for %.0fs",
                    reason or "unspecified",
                    self._open_duration_s,
                )


def is_cf_1015(body: str | bytes | None) -> bool:
    """Detecta la firma "error code: 1015" en el body de una respuesta.

    Cloudflare 1015 = "You are being rate limited". Ya no hay reintentos
    razonables: la IP está temporalmente baneada. El body puede venir con
    status 200, 403 o 503 dependiendo del contexto — por eso miramos el body.
    """
    if not body:
        return False
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8", errors="ignore")
        except Exception:
            return False
    return "error code: 1015" in body.lower()
