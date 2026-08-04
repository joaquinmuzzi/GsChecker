"""End-to-end del /p command con todo el fetch armory + uwu mockeado.

Cubre los 3 escenarios que corresponden a los bugs que ya vimos:

  1. Happy path — datos válidos → embed final con nombre/GS/etc.
  2. Rate-limited — _fetch_summary devuelve __error__ 'rate-limitó' →
     el usuario ve ese mensaje textual, no un embed corrupto.
  3. Personaje no existe — _fetch_summary devuelve __error__ 'No se
     encontró...' → mensaje textual correcto (no falso positivo).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import discord
from discord.ext import commands as discord_commands

from src.controller.commands import register_commands


@pytest.fixture
def bot() -> discord_commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    b = discord_commands.Bot(command_prefix="!", intents=intents)
    register_commands(b)
    return b


def _find_command(bot: discord_commands.Bot, name: str):
    for cmd in bot.tree.walk_commands():
        if cmd.name == name:
            return cmd
    raise LookupError(f"slash command '{name}' not found")


def _happy_summary() -> dict:
    return {
        "name": "Samsara",
        "level": 80,
        "race": "Draenei",
        "class": "Death Knight",
        "guild": "Newbie Ink",
        "gearScore": "N/A",
    }


def _happy_gear_data() -> list[dict]:
    slots = [
        "Head", "Neck", "Shoulder", "Back", "Chest", "Wrist", "Hands", "Waist",
        "Legs", "Feet", "Finger 1", "Finger 2", "Trinket 1", "Trinket 2",
        "Ranged", "Main Hand", "Off Hand", "Sigil", "Tabard",
    ]
    return [
        {
            "item": str(49986 + i),
            "slot": slot,
            "gems": ["0", "0", "0"],
            "ench": "0",
        }
        for i, slot in enumerate(slots)
    ]


def _happy_achievements() -> dict:
    return {
        "completed_ids": {"4531", "4604"},
        "icc_10n_bosses": 4,
        "icc_25n_bosses": 4,
        "icc_10h_bosses": 0,
        "icc_25h_bosses": 0,
        "halion_10n_achieved": False,
        "halion_10h_achieved": False,
        "halion_25n_achieved": False,
        "halion_25h_achieved": False,
        "storming_10n_achieved": True,
        "storming_10h_achieved": False,
        "storming_25n_achieved": True,
        "storming_25h_achieved": False,
    }


@pytest.fixture
def patched_fetchers():
    """Patchea todas las funciones armory + uwu que /p invoca por executor.

    Los tests solo tienen que sobrescribir el retorno de la función que
    les interesa (ej: patched_fetchers['summary'].return_value = ...) y
    ejecutar el comando.
    """
    targets = {
        "summary": "src.controller.commands._fetch_summary",
        "specs": "src.controller.commands._fetch_specs",
        "professions": "src.controller.commands._fetch_professions",
        "gear": "src.controller.commands._fetch_gear_data",
        "achievements": "src.controller.commands._fetch_achievements",
        "statistics": "src.controller.commands._fetch_statistics",
        "guild_rank": "src.controller.commands._fetch_guild_rank",
        "uwu_icc": "src.controller.commands._uwu_icc_bugfix_kills",
    }
    with (
        patch(targets["summary"]) as m_summary,
        patch(targets["specs"]) as m_specs,
        patch(targets["professions"]) as m_prof,
        patch(targets["gear"]) as m_gear,
        patch(targets["achievements"]) as m_achi,
        patch(targets["statistics"]) as m_stats,
        patch(targets["guild_rank"]) as m_rank,
        patch(targets["uwu_icc"]) as m_uwu,
    ):
        m_summary.return_value = _happy_summary()
        m_specs.return_value = [
            {"name": "Blood", "active": True},
            {"name": "Frost", "active": False},
        ]
        m_prof.return_value = ["Engineering 450", "Enchanting 450"]
        m_gear.return_value = _happy_gear_data()
        m_achi.return_value = _happy_achievements()
        m_stats.return_value = []
        m_rank.return_value = "Gran Canciller"
        m_uwu.return_value = {}
        yield {
            "summary": m_summary,
            "specs": m_specs,
            "professions": m_prof,
            "gear": m_gear,
            "achievements": m_achi,
            "statistics": m_stats,
            "guild_rank": m_rank,
            "uwu_icc": m_uwu,
        }


@pytest.mark.asyncio
async def test_personaje_happy_path_ships_embed_with_character_data(
    bot, interaction, patched_fetchers
):
    p_cmd = _find_command(bot, "p")
    await p_cmd.callback(interaction, nombre="Samsara")

    edit = interaction.last_edit()
    assert edit is not None, f"expected an edit, got sent={interaction.sent}"
    assert edit.embed is not None, "final edit should carry the character embed"
    assert edit.content is None

    author_name = (
        edit.embed.author.name if edit.embed.author is not None else ""
    ) or ""
    text = (
        f"{author_name} {edit.embed.title or ''} {edit.embed.description or ''}"
    )
    for field in getattr(edit.embed, "fields", []):
        text += f" {field.name} {field.value}"

    assert "Samsara" in text
    assert "Death Knight" in text or "Draenei" in text


@pytest.mark.asyncio
async def test_personaje_rate_limited_shows_rate_limit_message(
    bot, interaction, patched_fetchers
):
    """Regression: reported bug where existing characters showed 'no existe'
    because the circuit breaker was open. Now they should see a rate-limit
    message with a wait hint."""
    patched_fetchers["summary"].return_value = {
        "__error__": "⚠️ El Armory de Warmane nos rate-limitó. Reintentá en ~60s."
    }

    p_cmd = _find_command(bot, "p")
    await p_cmd.callback(interaction, nombre="Novatizimu")

    edit = interaction.last_edit()
    assert edit is not None
    assert edit.embed is None, "rate-limit message must be plain content, not an embed"
    assert edit.content is not None
    assert "rate-limit" in edit.content.lower()
    assert "no se encontr" not in edit.content.lower(), (
        "must not falsely claim the character doesn't exist"
    )


@pytest.mark.asyncio
async def test_personaje_not_found_shows_not_found_message(
    bot, interaction, patched_fetchers
):
    patched_fetchers["summary"].return_value = {
        "__error__": "⚠️ No se encontró el personaje 'Xxxxx' en Lordaeron."
    }

    p_cmd = _find_command(bot, "p")
    await p_cmd.callback(interaction, nombre="Xxxxx")

    edit = interaction.last_edit()
    assert edit is not None
    assert edit.embed is None
    assert edit.content is not None
    assert "no se encontr" in edit.content.lower()


@pytest.mark.asyncio
async def test_personaje_rejects_invalid_realm(bot, interaction, patched_fetchers):
    p_cmd = _find_command(bot, "p")
    await p_cmd.callback(interaction, nombre="Samsara", reino="Nagrand")

    sent = interaction.last_sent()
    assert sent is not None
    text = (sent.content or "") + str(sent.embed or "")
    assert "reino inválido" in text.lower() or "reino invalido" in text.lower()


@pytest.mark.asyncio
async def test_personaje_non_80_short_circuits(
    bot, interaction, patched_fetchers
):
    """A level 79 character shouldn't reach the achievements/gear pipeline —
    /p only supports 80s."""
    patched_fetchers["summary"].return_value = {
        **_happy_summary(),
        "level": 79,
    }

    p_cmd = _find_command(bot, "p")
    await p_cmd.callback(interaction, nombre="Samsara")

    edit = interaction.last_edit()
    assert edit is not None
    assert edit.embed is None
    assert edit.content is not None
    assert "no es nivel 80" in edit.content.lower()
