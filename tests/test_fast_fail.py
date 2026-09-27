"""Un nombre inválido, un personaje inexistente o uno que no es 80 tienen que
responder sin disparar las consultas pesadas del armory (logros, estadísticas,
gear...). Antes cada uno tardaba 30-50 s y gastaba ~15 requests del rate limit
compartido, lo que llegó a abrir el circuit breaker para todos los usuarios."""
from __future__ import annotations

import pytest

from tests.test_personaje import (  # noqa: F401  (fixtures)
    _find_command,
    bot,
    patched_fetchers,
)

HEAVY = ("gear", "achievements", "statistics", "specs", "professions")


@pytest.mark.asyncio
async def test_invalid_name_is_rejected_without_armory(bot, interaction, patched_fetchers):  # noqa: F811
    await _find_command(bot, "p").callback(interaction, nombre="C_123")

    last = interaction.last_sent()
    assert last is not None and "no es un nombre de personaje válido" in (last.content or "")
    patched_fetchers["summary"].assert_not_called()
    for name in HEAVY:
        patched_fetchers[name].assert_not_called()


@pytest.mark.asyncio
async def test_missing_character_skips_heavy_fetches(bot, interaction, patched_fetchers):  # noqa: F811
    patched_fetchers["summary"].return_value = {
        "__error__": "⚠️ No se encontró el personaje 'Zzqxwvut' en Lordaeron."
    }
    await _find_command(bot, "p").callback(interaction, nombre="Zzqxwvut")

    assert "No se encontró" in (interaction.last_edit().content or "")
    for name in HEAVY:
        patched_fetchers[name].assert_not_called()


@pytest.mark.asyncio
async def test_low_level_character_skips_heavy_fetches(bot, interaction, patched_fetchers):  # noqa: F811
    patched_fetchers["summary"].return_value = {
        "name": "Srpingu", "level": 1, "race": "Night Elf", "class": "Warrior",
        "guild": "Sin guild", "gearScore": "N/A",
    }
    await _find_command(bot, "p").callback(interaction, nombre="Srpingu", reino="Icecrown")

    assert "no es nivel 80" in (interaction.last_edit().content or "")
    for name in HEAVY:
        patched_fetchers[name].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["dps", "ptoc", "ia"])
async def test_other_commands_reject_invalid_names(bot, interaction, command):  # noqa: F811
    await _find_command(bot, command).callback(interaction, nombre="C_123")

    last = interaction.last_sent()
    assert last is not None and "no es un nombre de personaje válido" in (last.content or "")
