"""Solo se registran en `tracked_characters` los personajes que el armory
confirma que existen en ese reino y son 80.

Antes se registraba cualquier nombre al usar el comando, y el cron reintentaba
todos los días 16 que no podía precargar (2026-10-10): typos (Veleriel por
Veletriel), reinos equivocados (Herbbz es de Icecrown), personajes que no son 80
(Zolan, nivel 56; Srpingu de Icecrown, nivel 1) y nombres de prueba (Zzqxwvut).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tests.test_personaje import (  # noqa: F401  (fixtures)
    _find_command,
    bot,
    patched_fetchers,
)


@pytest.fixture
def tracked():
    with patch(
        "src.services.tracking.async_track_character_lookup", new_callable=AsyncMock
    ) as m:
        yield m


async def _run(bot, command, interaction, **kwargs):  # noqa: F811
    await _find_command(bot, command).callback(interaction, **kwargs)
    # El registro es fire-and-forget: se deja correr la task pendiente.
    await asyncio.sleep(0)


def _summary(name: str, level: int) -> dict:
    return {
        "name": name, "level": level, "race": "Night Elf", "class": "Rogue",
        "guild": "The Order of the Ring", "gearScore": "N/A",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "nombre, reino, summary",
    [
        ("Zzqxwvut", "Lordaeron", {"__error__": "⚠️ No se encontró el personaje 'Zzqxwvut' en Lordaeron."}),
        ("Herbbz", "Lordaeron", {"__error__": "⚠️ No se encontró el personaje 'Herbbz' en Lordaeron."}),
        ("Zolan", "Lordaeron", _summary("Zolan", 56)),
        ("Srpingu", "Icecrown", _summary("Srpingu", 1)),
    ],
)
async def test_p_does_not_track_missing_or_low_level(
    bot, interaction, patched_fetchers, tracked, nombre, reino, summary  # noqa: F811
):
    patched_fetchers["summary"].return_value = summary
    await _run(bot, "p", interaction, nombre=nombre, reino=reino)

    tracked.assert_not_called()


@pytest.mark.asyncio
async def test_p_tracks_found_character_with_armory_name(
    bot, interaction, patched_fetchers, tracked  # noqa: F811
):
    await _run(bot, "p", interaction, nombre="samsara")

    tracked.assert_called_once_with("Samsara", "Lordaeron")


@pytest.mark.asyncio
async def test_dps_does_not_track_missing_character(
    bot, interaction, patched_fetchers, tracked  # noqa: F811
):
    patched_fetchers["summary"].return_value = {
        "__error__": "⚠️ No se encontró el personaje 'Veleriel' en Lordaeron."
    }
    await _run(bot, "dps", interaction, nombre="Veleriel")

    tracked.assert_not_called()


@pytest.mark.asyncio
async def test_ptoc_does_not_track(bot, interaction, tracked):  # noqa: F811
    toc = {"toc_10n": False, "toc_10h": False, "toc_25n": False, "toc_25h": False}
    with patch("src.controller.commands.ptoc._fetch_toc_achievements", return_value=toc):
        await _run(bot, "ptoc", interaction, nombre="Kynrwe")

    tracked.assert_not_called()
