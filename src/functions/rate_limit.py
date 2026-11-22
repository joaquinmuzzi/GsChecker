"""Token bucket + circuit breaker para armory.warmane.com.

El armory de Warmane rate-limita agresivamente por IP:
- ~5-6 requests en 10s → HTTP 429
- Abuso sostenido → "error code: 1015" (IP temporalmente baneada por Cloudflare)

Este módulo provee dos primitivas thread-safe que usa `src/functions/warmane.py` y
`profile_scraper.py` a través de la instancia global en `src/schemas/constants.py`:

- `TokenBucket`: espacia las llamadas salientes (ej: 1 request cada 2s con burst 3)
  para no llegar al 429 en primer lugar.
- `AdaptiveTokenBucket`: el mismo bucket con dos ritmos. Va rápido mientras el
  armory responde bien y, ante el primer 429/1015, frena solo al ritmo lento
  durante un rato (`slow_down()`); después vuelve al rápido.
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


class AdaptiveTokenBucket(TokenBucket):
    """Token bucket que alterna entre un ritmo rápido y uno lento.

    Arranca en el rápido. `slow_down()` (lo llaman los clientes del armory al
    ver un 429, un 5xx o un 1015) pasa al lento, vacía los tokens para cortar
    la ráfaga en curso y lo mantiene `slow_period_s` segundos; cada nuevo
    rate limit en ese lapso lo extiende. Pasado el lapso vuelve solo al rápido.

    Con `fast_rate == slow_rate` y `fast_capacity == slow_capacity` se comporta
    como el `TokenBucket` lento de siempre (así se apaga el modo rápido).
    """

    def __init__(
        self,
        *,
        fast_rate: float,
        fast_capacity: int,
        slow_rate: float,
        slow_capacity: int,
        slow_period_s: float,
    ) -> None:
        # Valida los dos juegos de parámetros con las reglas de TokenBucket.
        TokenBucket(rate=slow_rate, capacity=slow_capacity)
        super().__init__(rate=fast_rate, capacity=fast_capacity)
        self._fast_rate = float(fast_rate)
        self._fast_capacity = float(fast_capacity)
        self._slow_rate = float(slow_rate)
        self._slow_capacity = float(slow_capacity)
        self._slow_period_s = float(slow_period_s)
        self._slow_until = 0.0

    def _refill(self) -> None:
        # Se llama con el lock tomado (desde acquire).
        if self._slow_until and time.monotonic() >= self._slow_until:
            self._slow_until = 0.0
            self._rate = self._fast_rate
            self._capacity = self._fast_capacity
            logger.info(
                "armory throttle back to fast mode (%.2f req/s, burst %d)",
                self._fast_rate,
                self._fast_capacity,
            )
        super()._refill()

    def is_slow(self) -> bool:
        with self._lock:
            return time.monotonic() < self._slow_until

    def slow_down(self, reason: str = "") -> None:
        with self._lock:
            now = time.monotonic()
            was_slow = now < self._slow_until
            self._slow_until = now + self._slow_period_s
            self._rate = self._slow_rate
            self._capacity = self._slow_capacity
            self._tokens = 0.0
            self._last_refill = now
        if not was_slow:
            logger.warning(
                "armory throttle slowed down (reason=%s): %.2f req/s for %.0fs",
                reason or "unspecified",
                self._slow_rate,
                self._slow_period_s,
            )


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

    def recent_failure_count(self) -> int:
        """Cuenta de failures dentro de la ventana actual (para diferenciar
        'no hubo respuesta por rate limit' de 'la respuesta dijo que no existe')."""
        with self._lock:
            cutoff = time.monotonic() - self._failure_window_s
            return sum(1 for ts in self._failures if ts >= cutoff)

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
