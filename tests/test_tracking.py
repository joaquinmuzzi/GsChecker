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

from src.services import tracking
from src.services.tracking import _track_character
from tests.helpers import _find_command


@pytest.fixture
def tracked():
    with patch("src.services.tracking.async_track_character_lookup", new_callable=AsyncMock) as m:
        yield m


async def _run(bot, command, interaction, **kwargs):
    await _find_command(bot, command).callback(interaction, **kwargs)
    # El registro es fire-and-forget: se deja correr la task pendiente.
    await asyncio.sleep(0)


def _summary(name: str, level: int) -> dict:
    return {
        "name": name,
        "level": level,
        "race": "Night Elf",
        "class": "Rogue",
        "guild": "The Order of the Ring",
        "gearScore": "N/A",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("nombre", "reino", "summary"),
    [
        ("Zzqxwvut", "Lordaeron", {"__error__": "⚠️ No se encontró el personaje 'Zzqxwvut' en Lordaeron."}),
        ("Herbbz", "Lordaeron", {"__error__": "⚠️ No se encontró el personaje 'Herbbz' en Lordaeron."}),
        ("Zolan", "Lordaeron", _summary("Zolan", 56)),
        ("Srpingu", "Icecrown", _summary("Srpingu", 1)),
    ],
)
async def test_p_does_not_track_missing_or_low_level(
    bot,
    interaction,
    patched_fetchers,
    tracked,
    nombre,
    reino,
    summary,
):
    patched_fetchers["summary"].return_value = summary
    await _run(bot, "p", interaction, nombre=nombre, reino=reino)

    tracked.assert_not_called()


@pytest.mark.asyncio
async def test_p_tracks_found_character_with_armory_name(
    bot,
    interaction,
    patched_fetchers,
    tracked,
):
    await _run(bot, "p", interaction, nombre="samsara")

    tracked.assert_called_once_with("Samsara", "Lordaeron")


@pytest.mark.asyncio
async def test_dps_does_not_track_missing_character(
    bot,
    interaction,
    patched_fetchers,
    tracked,
):
    patched_fetchers["summary"].return_value = {
        "__error__": "⚠️ No se encontró el personaje 'Veleriel' en Lordaeron."
    }
    await _run(bot, "dps", interaction, nombre="Veleriel")

    tracked.assert_not_called()


@pytest.mark.asyncio
async def test_ptoc_does_not_track(bot, interaction, tracked):
    toc = {"toc_10n": False, "toc_10h": False, "toc_25n": False, "toc_25h": False}
    with patch("src.controller.commands.ptoc._fetch_toc_achievements", return_value=toc):
        await _run(bot, "ptoc", interaction, nombre="Kynrwe")

    tracked.assert_not_called()


@pytest.mark.asyncio
async def test_tracking_task_is_kept_until_it_finishes(tracked):
    # asyncio solo guarda referencias débiles a las tareas: si nadie más la
    # referencia, el garbage collector puede cortar el registro a la mitad.
    release = asyncio.Event()

    async def slow_insert(*args):
        await release.wait()

    tracked.side_effect = slow_insert
    _track_character("Samsara", "Lordaeron")
    await asyncio.sleep(0)
    assert len(tracking._PENDING_TASKS) == 1

    release.set()
    for _ in range(3):
        await asyncio.sleep(0)
    assert not tracking._PENDING_TASKS
    tracked.assert_awaited_once_with("Samsara", "Lordaeron")
