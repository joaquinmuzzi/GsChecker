"""Botón 🔄 Actualizar ahora del mensaje de /p.

Rehace el perfil contra el armory y UwU Logs en el momento, sin esperar a que
el cron regenere la caché a la noche, y edita el mismo mensaje con el
resultado. Cualquiera que vea el mensaje puede apretarlo: hay un cooldown por
personaje y otro por usuario (`refresh_cooldown`) para no gastar el rate limit
del armory, que comparten todos.
"""

import logging
import math
import re

import discord

from src.controller.commands.interactions import _log_command_usage, _reply_command_error
from src.controller.commands.personaje_live import _send_live_profile
from src.functions.embeds import PERSONAJE_REFRESH_CUSTOM_ID, _build_personaje_refresh_button
from src.schemas.constants import ARMORY_CIRCUIT
from src.services.cache_keys import _build_personaje_cache_key
from src.services.character_input import _normalize_character_name, _normalize_character_realm
from src.services.refresh_cooldown import (
    CHARACTER_COOLDOWN_SECONDS,
    USER_COOLDOWN_SECONDS,
    _mark_live_profile,
    _refresh_wait,
)

# Mismo logger que el resto de los comandos: los logs de Railway no cambian.
logger = logging.getLogger("gschecker.commands")


class PersonajeRefreshButton(discord.ui.DynamicItem[discord.ui.Button], template=PERSONAJE_REFRESH_CUSTOM_ID):
    """Atiende el botón de cualquier mensaje de /p, aunque sea de antes de un
    reinicio del bot: el personaje y el reino salen del custom_id."""

    def __init__(self, nombre_char: str, realm: str) -> None:
        super().__init__(_build_personaje_refresh_button(nombre_char, realm))
        self.nombre_char = nombre_char
        self.realm = realm

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item,
        match: re.Match[str],
        /,
    ) -> "PersonajeRefreshButton":
        return cls(match["name"], match["realm"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await _refresh_personaje_impl(interaction, self.nombre_char, self.realm)


def _format_wait(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} s"
    return f"{math.ceil(seconds / 60)} min"


def _cooldown_message(nombre: str, reason: str, seconds: int) -> str:
    if reason == "character":
        return (
            f"🔄 **{nombre}** ya se actualizó hace menos de {CHARACTER_COOLDOWN_SECONDS // 60} min. "
            f"Podés volver a actualizarlo en {_format_wait(seconds)}."
        )
    return (
        f"🔄 Ya actualizaste un personaje hace menos de {USER_COOLDOWN_SECONDS // 60} min. "
        f"Probá de nuevo en {_format_wait(seconds)}."
    )


async def _refresh_personaje_impl(interaction: discord.Interaction, nombre: str, reino: str) -> None:
    try:
        nombre = _normalize_character_name(nombre)
        realm = _normalize_character_realm(reino)
        _log_command_usage(interaction, "actualizar", nombre, realm)

        user_id = getattr(interaction.user, "id", None)
        wait = _refresh_wait(nombre, realm, user_id)
        if wait is not None:
            await interaction.response.send_message(_cooldown_message(nombre, *wait), ephemeral=True)
            return
        if ARMORY_CIRCUIT.is_open():
            await interaction.response.send_message(
                "⚠️ El armory de Warmane está rate-limitado. Intenta de nuevo en ~60s.", ephemeral=True
            )
            return

        # Antes de responder: un segundo click mientras se calcula ya choca
        # con el cooldown.
        _mark_live_profile(nombre, realm, user_id)
        # Deferred update: las ediciones de `_send_live_profile` van al mismo
        # mensaje que tiene el botón, no a uno nuevo.
        await interaction.response.defer()
        personaje_cache_key = f"{_build_personaje_cache_key(nombre)}:{realm.lower()}"
        await _send_live_profile(interaction, nombre, realm, "actualizar", personaje_cache_key, refresh=True)

    except Exception as exc:
        if not isinstance(exc, (discord.HTTPException, ValueError)):
            logger.exception("personaje refresh failed for '%s'/%s", nombre, reino)
        await _reply_command_error(interaction, exc, "❌ Error al actualizar el perfil", ephemeral=True)


def register(bot):
    bot.add_dynamic_items(PersonajeRefreshButton)
