"""/personaje y su alias /p: el resumen completo de un personaje.

El perfil sale de la caché si está (la llena el cron cada noche), de la última
copia guardada si el armory está rate-limitado, o se arma en vivo
(`personaje_live`).
"""

import asyncio
import logging

import discord

from src.controller.commands.interactions import (
    _log_command_usage,
    _reply_command_error,
    _safe_defer,
    _safe_edit_original_response,
)
from src.controller.commands.personaje_live import (
    _build_personaje_embed_from_cache,
    _send_live_profile,
)
from src.db.postgres import async_get_external_cache, async_get_external_cache_stale
from src.functions.embeds import _build_personaje_view
from src.functions.uwu import _fetch_uwu_performance
from src.schemas.constants import ARMORY_CIRCUIT, COMMAND_PERSONAJE_TTL, EXECUTOR
from src.services.cache_keys import _build_personaje_cache_key
from src.services.character_input import (
    DEFAULT_CHARACTER_REALM,
    _normalize_character_name,
    _normalize_character_realm,
)
from src.services.tracking import _track_character

# Mismo logger que antes del split: los logs de Railway no cambian.
logger = logging.getLogger("gschecker.commands")


async def _personaje_impl(
    interaction: discord.Interaction,
    nombre: str,
    command_name: str,
    reino: str | None = None,
):
    try:
        nombre = _normalize_character_name(nombre)
        realm = _normalize_character_realm(reino)
        _log_command_usage(interaction, command_name, nombre, realm)
        await _safe_defer(interaction)

        personaje_cache_key = f"{_build_personaje_cache_key(nombre)}:{realm.lower()}"
        cached_payload = await async_get_external_cache(
            "command_personaje", personaje_cache_key, COMMAND_PERSONAJE_TTL
        )
        if isinstance(cached_payload, dict):
            await _send_cached_profile(interaction, cached_payload, nombre, realm)
            return

        if ARMORY_CIRCUIT.is_open():
            await _send_stale_profile(interaction, personaje_cache_key, nombre, realm)
            return

        await _send_live_profile(interaction, nombre, realm, command_name, personaje_cache_key)

    except Exception as exc:
        if not isinstance(exc, (discord.HTTPException, ValueError)):
            logger.exception("personaje failed for '%s'", nombre)
        await _reply_command_error(interaction, exc, "❌ Error al obtener datos")


async def _send_cached_profile(
    interaction: discord.Interaction, cached_payload: dict, nombre: str, realm: str
) -> None:
    # Un payload cacheado ya pasó _is_valid_personaje_payload (existe y es 80).
    _track_character(cached_payload["nombre_char"], realm)
    if not (cached_payload.get("uwu_performance") or {}).get("rank"):
        # Perfil cacheado sin ranking de uwu-logs (de antes de que /p lo
        # mostrara, o uwu-logs no respondió cuando corrió el cron; dura
        # hasta 25 h): se pide solo el ranking (~1 s, sin armory). No se
        # re-guarda para no estirar el TTL de los datos del armory.
        try:
            cached_payload["uwu_performance"] = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    EXECUTOR,
                    _fetch_uwu_performance,
                    cached_payload.get("nombre_char", nombre),
                    realm,
                    cached_payload.get("clase"),
                ),
                timeout=10.0,
            )
        except Exception:
            logger.warning("uwu performance fetch failed for cached '%s'/%s", nombre, realm)
    embed_cached = _build_personaje_embed_from_cache(cached_payload)
    view_cached = _build_personaje_view(
        cached_payload["nombre_char"],
        cached_payload.get("server", DEFAULT_CHARACTER_REALM),
    )
    await _safe_edit_original_response(interaction, content=None, embed=embed_cached, view=view_cached)


async def _send_stale_profile(
    interaction: discord.Interaction, personaje_cache_key: str, nombre: str, realm: str
) -> None:
    """El armory está rate-limitado (circuit breaker abierto): se muestra la
    última copia guardada aunque esté vencida, o un aviso si no hay ninguna."""
    stale_payload = await async_get_external_cache_stale("command_personaje", personaje_cache_key)
    if isinstance(stale_payload, dict):
        logger.warning(
            "Armory circuit open — serving stale DB cache for '%s'/%s",
            nombre,
            realm,
        )
        _track_character(stale_payload["nombre_char"], realm)
        embed_stale = _build_personaje_embed_from_cache(stale_payload)
        view_stale = _build_personaje_view(
            stale_payload["nombre_char"],
            stale_payload.get("server", DEFAULT_CHARACTER_REALM),
        )
        await _safe_edit_original_response(interaction, content=None, embed=embed_stale, view=view_stale)
        return
    logger.warning(
        "Armory circuit open and no stale cache for '%s'/%s — showing error",
        nombre,
        realm,
    )
    await _safe_edit_original_response(
        interaction,
        content="⚠️ El armory de Warmane está rate-limitado. Intenta de nuevo en ~60s.",
        embed=None,
    )


def register(bot):
    @bot.tree.command(
        name="personaje",
        description="Muestra información del personaje desde la API de Warmane.",
    )
    @discord.app_commands.describe(
        nombre="Nombre del personaje.",
        reino="Reino opcional. Por defecto: Lordaeron.",
    )
    async def personaje(
        interaction: discord.Interaction,
        nombre: str,
        reino: str | None = None,
    ):
        await _personaje_impl(interaction, nombre, "personaje", reino)

    @bot.tree.command(
        name="p",
        description="Alias corto de /personaje para consultar un personaje.",
    )
    @discord.app_commands.describe(
        nombre="Nombre del personaje.",
        reino="Reino opcional. Por defecto: Lordaeron.",
    )
    async def p(
        interaction: discord.Interaction,
        nombre: str,
        reino: str | None = None,
    ):
        await _personaje_impl(interaction, nombre, "p", reino)
