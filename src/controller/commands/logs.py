"""/logs: los últimos reportes de UwU Logs donde aparece el personaje."""

import asyncio

import discord

from src.controller.commands.interactions import (
    _log_command_usage,
    _reply_command_error,
    _safe_defer,
    _safe_edit_original_response,
)
from src.functions.embeds import _build_uwu_logs_embed, _build_uwu_logs_view
from src.functions.uwu import UWU_DOWN_MESSAGE, _fetch_uwu_recent_logs
from src.schemas.constants import EXECUTOR
from src.services.character_input import (
    _normalize_character_name,
    _normalize_character_realm,
)


def register(bot):
    @bot.tree.command(
        name="logs",
        description="Últimos reportes de UwU Logs donde aparece el personaje.",
    )
    @discord.app_commands.describe(
        nombre="Nombre del personaje.",
        reino="Reino opcional. Por defecto: Lordaeron.",
    )
    async def logs(
        interaction: discord.Interaction,
        nombre: str,
        reino: str | None = None,
    ):
        try:
            nombre = _normalize_character_name(nombre)
            realm = _normalize_character_realm(reino)
            _log_command_usage(interaction, "logs", nombre, realm)
            await _safe_defer(interaction)
            await _safe_edit_original_response(
                interaction,
                content=f"⏳ Buscando logs de **{nombre}** en UwU Logs...",
                embed=None,
            )

            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(EXECUTOR, _fetch_uwu_recent_logs, nombre, realm)
            if data is None:
                await _safe_edit_original_response(interaction, content=UWU_DOWN_MESSAGE, embed=None)
                return
            if not data.get("reports"):
                await _safe_edit_original_response(
                    interaction,
                    content=f"⚠️ No hay logs en UwU Logs para {nombre} en {realm}.",
                    embed=None,
                )
                return

            await _safe_edit_original_response(
                interaction,
                content=None,
                embed=_build_uwu_logs_embed(nombre, realm, data),
                view=_build_uwu_logs_view(nombre, realm),
            )

        except Exception as exc:
            await _reply_command_error(interaction, exc, "❌ Error al obtener datos")
