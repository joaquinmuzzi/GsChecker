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

import gearscore
import profile_scraper
from src.controller.commands import (
    _apply_item_drop_fallback_to_uwu,
    _apply_storming_fallback_to_uwu,
    _build_character_spec_gs_key,
    _build_personaje_cache_key,
    _build_spec_gs_entries,
    _fallback_spec_names_for_class,
    _finalize_special_uwu_kills,
    _get_known_gs_by_spec,
    _is_valid_personaje_payload,
    _load_confirmed_icc_kills,
    _normalize_character_realm,
    _normalize_special_uwu_kills,
    _overlay_persistent_confirmed_kills,
    _persist_new_confirmed_icc_kills,
    _serialize_personaje_payload,
)
from src.db.postgres import (
    init_database,
    list_tracked_characters,
    set_external_cache,
)
from src.functions.embeds import _extract_icc_boss_kills
from src.functions.uwu import _uwu_icc_bugfix_kills
from src.functions.warmane import (
    _fetch_achievements,
    _fetch_gear_data,
    _fetch_guild_rank,
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
    en el cache `command_personaje` — la misma secuencia que `_personaje_impl`,
    pero sincrónica y sin nada de UI de Discord. Devuelve el payload cacheado,
    o None si el personaje no se pudo resolver (no existe, no es nivel 80, etc.).
    """
    summary = _fetch_summary(nombre, server)
    if not isinstance(summary, dict) or summary.get("__error__"):
        return None

    nombre_char = summary.get("name", nombre)
    nivel = summary.get("level", "N/A")
    raza = summary.get("race", "N/A")
    clase = summary.get("class", "N/A")
    if nivel != 80:
        return None

    gear_data = _fetch_gear_data(nombre_char, server)
    achi_payload = _fetch_achievements(nombre_char, server)
    stats_rows = _fetch_statistics(nombre_char, server, ICC_STATS_CATEGORY_ID)
    professions = _fetch_professions(nombre_char, server)
    talents = _fetch_specs(nombre_char, server)

    if isinstance(talents, list) and len(talents) > 0:
        sorted_talents = sorted(talents, key=lambda t: not t.get("active", False))
        active_specs = [
            t.get("name", "N/A") for t in sorted_talents if t.get("active", False)
        ]
        inactive_specs = [
            t.get("name", "N/A") for t in sorted_talents if not t.get("active", False)
        ]
        if not active_specs:
            for talent in sorted_talents:
                candidate = str(talent.get("name") or "").strip()
                if not candidate or candidate == "N/A":
                    continue
                active_specs = [candidate]
                inactive_specs = [
                    name for name in inactive_specs if str(name or "").strip() != candidate
                ]
                break
    else:
        active_specs = []
        inactive_specs = _fallback_spec_names_for_class(clase)

    try:
        gear_ids = profile_scraper.get_gear_ids_from_gear_data(gear_data)
        gear_ids = [gid for gid in gear_ids if gid]
        gs = sum(gearscore.main(gear_ids)) if gear_ids else summary.get("gearScore", "N/A")
    except Exception:
        logger.exception(
            "gearscore calc failed for '%s'/%s — falling back to armory gearScore",
            nombre_char,
            server,
        )
        gs = summary.get("gearScore", "N/A")

    is_stubs = (
        isinstance(gear_data, list)
        and len(gear_data) > 0
        and all(isinstance(item, dict) and item.get("_source") == "api_stubs" for item in gear_data)
    )

    if is_stubs:
        missing_enchants, missing_gems, suboptimal_gems = [], [], []
    else:
        try:
            missing_enchants, missing_gems = (
                profile_scraper.get_missing_enchants_gems_from_gear_data(gear_data)
            )
        except Exception:
            logger.exception("missing enchants/gems calc failed for '%s'/%s", nombre_char, server)
            missing_enchants, missing_gems = [], []

        try:
            suboptimal_gems = profile_scraper.get_suboptimal_gems_from_gear_data(
                gear_data, clase, active_specs[0] if active_specs else ""
            )
        except Exception:
            logger.exception("suboptimal gems calc failed for '%s'/%s", nombre_char, server)
            suboptimal_gems = []

    guild_obj = summary.get("guild")
    guild = guild_obj if isinstance(guild_obj, str) else "Sin guild"
    guild_rank = None
    if guild and guild != "Sin guild":
        try:
            guild_rank = _fetch_guild_rank(nombre_char, guild, server)
        except Exception:
            logger.exception(
                "guild rank fetch failed for '%s' guild='%s'/%s", nombre_char, guild, server
            )
            guild_rank = None

    for active_spec in active_specs:
        clean_active_spec = str(active_spec or "").strip()
        if not clean_active_spec or clean_active_spec == "N/A":
            continue
        set_external_cache(
            "character_spec_gs",
            "/tools/preload_personaje_cache",
            _build_character_spec_gs_key(nombre_char, server, clean_active_spec),
            {"character": nombre_char, "spec": clean_active_spec, "gs": gs},
            {"character": nombre_char, "spec": clean_active_spec, "server": server},
        )

    gs_by_spec = _get_known_gs_by_spec(
        nombre_char, server, active_specs + inactive_specs, gs, active_specs
    )
    if active_specs and gs in {None, "N/A", "?"}:
        active_name = str(active_specs[0] or "").strip()
        if active_name and gs_by_spec.get(active_name) in {None, "N/A", "?"}:
            fallback_gs = next(
                (v for v in gs_by_spec.values() if v not in {None, "N/A", "?"}), None
            )
            if fallback_gs is not None:
                gs_by_spec[active_name] = fallback_gs

    spec_gs_entries = _build_spec_gs_entries(active_specs + inactive_specs, gs_by_spec, active_specs)
    if spec_gs_entries and not any(entry.get("main") for entry in spec_gs_entries):
        if gs not in {None, "N/A", "?"}:
            spec_gs_entries[0]["main"] = True
            spec_gs_entries[0]["gearscore"] = gs
    active_spec_name = active_specs[0] if active_specs else None

    icc_10, icc_25 = _extract_icc_boss_kills(stats_rows)

    guild_display = f"<{guild}>" if guild and guild != "Sin guild" else "Sin guild"
    spec_display = " - ".join(
        f"**{spec}**" if spec in active_specs else spec for spec in active_specs + inactive_specs
    )

    persistent_confirmed = _load_confirmed_icc_kills(nombre_char, server)
    try:
        uwu_icc_kills = _uwu_icc_bugfix_kills(nombre_char, server)
    except Exception:
        logger.exception("uwu icc kills fetch failed for '%s'/%s", nombre_char, server)
        uwu_icc_kills = {}

    uwu_icc_kills = _normalize_special_uwu_kills(uwu_icc_kills)
    uwu_icc_kills = _overlay_persistent_confirmed_kills(uwu_icc_kills, persistent_confirmed)
    uwu_icc_kills = _apply_storming_fallback_to_uwu(uwu_icc_kills, achi_payload)
    uwu_icc_kills = _apply_item_drop_fallback_to_uwu(uwu_icc_kills, gear_data)

    persistent_confirmed = _persist_new_confirmed_icc_kills(nombre_char, server, uwu_icc_kills)
    uwu_icc_kills = _overlay_persistent_confirmed_kills(uwu_icc_kills, persistent_confirmed)
    uwu_icc_kills = _finalize_special_uwu_kills(uwu_icc_kills)

    payload = _serialize_personaje_payload(
        nombre_char,
        server,
        gs,
        nivel,
        raza,
        clase,
        spec_display,
        guild_display,
        guild_rank,
        achi_payload["halion_10n_achieved"],
        achi_payload["halion_10h_achieved"],
        achi_payload["halion_25n_achieved"],
        achi_payload["halion_25h_achieved"],
        icc_10,
        icc_25,
        missing_enchants,
        missing_gems,
        uwu_icc_kills,
        spec_gs_entries,
        active_spec_name,
        professions,
        suboptimal_gems,
    )

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

    pairs = list_tracked_characters()
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
