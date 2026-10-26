"""Autocompletado del nombre de personaje en los slash commands.

Sugiere hasta 3 personajes de `tracked_characters`, los más consultados primero.
Discord da ~3 s para responder, así que la lista vive en memoria y se refresca
cada tanto en segundo plano: nunca se toca el armory ni se espera a la DB más
de lo justo.
"""

import asyncio
import logging
import time

import discord

from src.db.postgres import list_autocomplete_characters
from src.services.character_input import SUPPORTED_CHARACTER_REALMS

logger = logging.getLogger("gschecker.autocomplete")

MAX_SUGGESTIONS = 3
REFRESH_SECONDS = 300
FIRST_LOAD_TIMEOUT = 2.0

_CHARACTERS: list[tuple[str, str, int]] = []
_LOADED_AT: float | None = None
_REFRESH_TASK: asyncio.Task | None = None


async def _refresh() -> None:
    global _CHARACTERS, _LOADED_AT
    rows = await asyncio.to_thread(list_autocomplete_characters)
    if rows:
        _CHARACTERS = rows
        _LOADED_AT = time.monotonic()


async def _ensure_loaded() -> None:
    """Primera vez: espera la carga (con tope). Después sirve lo que hay y, si
    está vencido, refresca en segundo plano."""
    global _REFRESH_TASK
    if _LOADED_AT is not None and time.monotonic() - _LOADED_AT < REFRESH_SECONDS:
        return
    if _REFRESH_TASK is None or _REFRESH_TASK.done():
        _REFRESH_TASK = asyncio.create_task(_refresh())
    if _LOADED_AT is None:
        try:
            await asyncio.wait_for(asyncio.shield(_REFRESH_TASK), FIRST_LOAD_TIMEOUT)
        except Exception as exc:
            logger.warning("Autocompletado sin lista todavía: %r", exc)


def suggest_characters(current: str, realm: str | None) -> list[tuple[str, str]]:
    """[(texto visible, valor)] con hasta 3 personajes que empiezan con `current`.

    Con reino elegido filtra por ese reino y el valor es el nombre solo. Sin
    reino muestra y devuelve "Nombre (Reino)" para distinguir homónimos.
    """
    prefix = (current or "").strip().lower()
    realm_key = (realm or "").strip().lower()
    realm_key = realm_key if realm_key in SUPPORTED_CHARACTER_REALMS else ""
    result: list[tuple[str, str]] = []
    for name, server, _count in _CHARACTERS:
        if not name.lower().startswith(prefix):
            continue
        if realm_key:
            if server.lower() != realm_key:
                continue
            result.append((name, name))
        else:
            label = f"{name} ({server})"
            result.append((label, label))
        if len(result) >= MAX_SUGGESTIONS:
            break
    return result


def make_name_autocomplete(fixed_realm: str | None = None):
    """Crea el callback de autocompletado para el parámetro `nombre`.

    `fixed_realm`: para comandos que solo trabajan con un reino (/dps, /ptoc);
    si no, se usa el parámetro `reino` que el usuario ya haya completado.
    """

    async def autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[discord.app_commands.Choice[str]]:
        try:
            await _ensure_loaded()
            realm = fixed_realm or getattr(interaction.namespace, "reino", None)
            return [
                discord.app_commands.Choice(name=label, value=value)
                for label, value in suggest_characters(current, realm)
            ]
        except Exception:
            logger.exception("Autocompletado falló para '%s'", current)
            return []

    return autocomplete
