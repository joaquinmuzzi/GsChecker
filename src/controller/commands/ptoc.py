"""/ptoc: logros de Trial of the Crusader en una tabla."""

import asyncio

import discord

from src.controller.commands.interactions import (
    _log_command_usage,
    _reply_command_error,
    _safe_defer,
    _safe_edit_original_response,
)
from src.functions.embeds import _render_table
from src.functions.warmane import _fetch_toc_achievements
from src.schemas.constants import EXECUTOR
from src.services.character_input import _normalize_character_name


def register(bot):
    @bot.tree.command(
        name="ptoc",
        description="Muestra logros de Trial of the Crusader (TOC) en formato tabla.",
    )
    @discord.app_commands.describe(nombre="Nombre del personaje en Lordaeron.")
    async def ptoc(interaction: discord.Interaction, nombre: str):
        try:
            nombre = _normalize_character_name(nombre)
            _log_command_usage(interaction, "ptoc", nombre, "Lordaeron")
            await _safe_defer(interaction)

            loop = asyncio.get_running_loop()
            toc_payload = await loop.run_in_executor(
                EXECUTOR, _fetch_toc_achievements, nombre, "Lordaeron"
            )

            def toc_status(done: bool) -> str:
                return "✅" if done else "❌"

            toc_rows = [
                {
                    "Boss": "Trial of the Crusader",
                    "10N": toc_status(toc_payload["toc_10n"]),
                    "10H": toc_status(toc_payload["toc_10h"]),
                    "25N": toc_status(toc_payload["toc_25n"]),
                    "25H": toc_status(toc_payload["toc_25h"]),
                }
            ]

            toc_table = _render_table(
                toc_rows,
                ["Boss", "10N", "10H", "25N", "25H"],
                {
                    "10N": f"{toc_status(toc_payload['toc_10n'])}10N",
                    "10H": f"{toc_status(toc_payload['toc_10h'])}10H",
                    "25N": f"{toc_status(toc_payload['toc_25n'])}25N",
                    "25H": f"{toc_status(toc_payload['toc_25h'])}25H",
                },
            )

            embed = discord.Embed(
                title=f"{nombre} - Trial of the Crusader",
                color=0x2B2D31,
            )
            embed.add_field(
                name="Trial of the Crusader",
                value=f"```\n{toc_table}\n```",
                inline=False,
            )
            embed.add_field(
                name="Armory",
                value=f"https://armory.warmane.com/character/{nombre}/Lordaeron/achievements",
                inline=False,
            )

            await _safe_edit_original_response(interaction, content=None, embed=embed)

        except Exception as exc:
            await _reply_command_error(interaction, exc, "❌ Error al obtener datos")
