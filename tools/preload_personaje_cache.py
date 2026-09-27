"""Cron job entrypoint: precarga el cache completo de `/personaje` (`command_personaje`)
para los personajes que la gente realmente consultó, así un lookup repetido es
instantáneo en vez de rehacer todo el scraping en vivo.

A diferencia de `preload_character_gs` (que solo calcula un número de GS por spec
tocando summary+specs+gear), este trae TODO lo que `/personaje` necesita —
achievements, stats, profesiones, guild rank, DPS de uwu-logs — así que se limita
a los personajes efectivamente buscados (tabla `tracked_characters`, alimentada por
cada uso real del comando), no a la lista semilla completa de miles de nombres.
Ampliar el scope a esa lista completa multiplicaría por ~5 el volumen de requests
al armory del preload diario.

Uso:
    python -m tools.preload_personaje_cache

Configurable por env vars:
    PERSONAJE_CACHE_DELAY_SECONDS   Pausa entre personajes (default: 2.0)
    PERSONAJE_CACHE_MAX_CHARACTERS  Corte duro (default: 0 = sin límite)
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from src.controller.commands import (
    _build_personaje_cache_key,
    _compute_personaje_base,
    _is_valid_personaje_payload,
    _load_confirmed_icc_kills,
    _normalize_character_realm,
    _resolve_uwu_icc_kills,
    _serialize_personaje_payload,
)
from src.db.postgres import (
    init_database,
    list_tracked_characters,
    set_external_cache,
)
from src.functions.names import is_valid_character_name
from src.functions.uwu import _uwu_icc_bugfix_kills
from src.functions.warmane import (
    _fetch_achievements,
    _fetch_gear_data,
    _fetch_professions,
    _fetch_specs,
    _fetch_statistics,
    _fetch_summary,
)
from src.schemas.constants import ARMORY_CIRCUIT, COMMAND_PERSONAJE_TTL

logger = logging.getLogger("gschecker.preload_personaje_cache")

DEFAULT_DELAY = 2.0
ICC_STATS_CATEGORY_ID = 15062


def build_personaje_cache_entry(nombre: str, server: str) -> dict | None:
    """Calcula el payload completo de `/personaje` para un personaje y lo guarda
    en el cache `command_personaje`. Usa la misma lógica que `/p`
    (`_compute_personaje_base` + `_resolve_uwu_icc_kills`), sin UI de Discord.
    Devuelve el payload cacheado, o None si el personaje no se pudo resolver
    (no existe, no es nivel 80, datos incompletos, etc.).
    """
    summary = _fetch_summary(nombre, server)
    if not isinstance(summary, dict) or summary.get("__error__"):
        return None

    nombre_char = summary.get("name", nombre)
    if summary.get("level", "N/A") != 80:
        return None

    gear_data = _fetch_gear_data(nombre_char, server)
    achi_payload = _fetch_achievements(nombre_char, server)
    stats_rows = _fetch_statistics(nombre_char, server, ICC_STATS_CATEGORY_ID)
    professions = _fetch_professions(nombre_char, server)
    talents = _fetch_specs(nombre_char, server)

    base = _compute_personaje_base(
        {**summary, "name": nombre_char},
        server,
        gear_data,
        achi_payload,
        stats_rows,
        professions,
        talents,
        "/tools/preload_personaje_cache",
    )

    persistent_confirmed = _load_confirmed_icc_kills(nombre_char, server)
    try:
        raw_uwu_kills = _uwu_icc_bugfix_kills(nombre_char, server)
    except Exception:
        logger.exception("uwu icc kills fetch failed for '%s'/%s", nombre_char, server)
        raw_uwu_kills = {}

    uwu_icc_kills = _resolve_uwu_icc_kills(
        nombre_char, server, raw_uwu_kills, persistent_confirmed, achi_payload, gear_data
    )
    payload = _serialize_personaje_payload(**base, uwu_icc_kills=uwu_icc_kills)

    if not _is_valid_personaje_payload(payload):
        return None

    personaje_cache_key = f"{_build_personaje_cache_key(nombre_char)}:{server.lower()}"
    set_external_cache(
        "command_personaje",
        "/tools/preload_personaje_cache",
        personaje_cache_key,
        payload,
        {"character": nombre_char, "command": "preload", "server": server},
    )
    return payload


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    load_dotenv()

    delay = float(os.getenv("PERSONAJE_CACHE_DELAY_SECONDS", str(DEFAULT_DELAY)))
    max_characters = int(os.getenv("PERSONAJE_CACHE_MAX_CHARACTERS", "0"))

    init_database()

    pairs = [(n, r) for n, r in list_tracked_characters() if is_valid_character_name(n)]
    if max_characters and max_characters > 0:
        pairs = pairs[:max_characters]

    if not pairs:
        logger.info("No hay personajes trackeados todavía (tabla tracked_characters vacía).")
        return 0

    logger.info(
        "Precarga command_personaje: %d personajes trackeados (delay=%.1fs, ttl=%ds)",
        len(pairs),
        delay,
        COMMAND_PERSONAJE_TTL,
    )

    ok = 0
    skipped = 0
    run_start = time.time()

    for idx, (nombre, server) in enumerate(pairs, start=1):
        while ARMORY_CIRCUIT.is_open():
            wait_s = int(ARMORY_CIRCUIT.seconds_until_close()) + 1
            logger.warning("Circuit abierto, esperando %ss antes de continuar...", wait_s)
            time.sleep(min(wait_s, 30))

        try:
            realm = _normalize_character_realm(server)
        except ValueError:
            skipped += 1
            continue

        try:
            payload = build_personaje_cache_entry(nombre, realm)
        except Exception:
            logger.exception("Fallo precargando '%s'/%s", nombre, realm)
            payload = None

        if payload:
            ok += 1
            logger.info("[%s/%s] [OK] %s/%s | gs=%s", idx, len(pairs), nombre, realm, payload.get("gs"))
        else:
            skipped += 1
            logger.info("[%s/%s] [SKIP] %s/%s", idx, len(pairs), nombre, realm)

        if idx != len(pairs):
            time.sleep(delay)

    logger.info(
        "Finalizado: ok=%s skip=%s duración=%ds", ok, skipped, int(time.time() - run_start)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
