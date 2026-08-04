"""Smoke test end-to-end del bot: instancia real, registro real de comandos,
invocación directa del handler /ping con una FakeInteraction."""

from __future__ import annotations

from unittest.mock import PropertyMock, patch

import pytest

import discord
from discord.ext import commands

from src.controller.commands import register_commands


@pytest.fixture
def bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    b = commands.Bot(command_prefix="!", intents=intents)
    register_commands(b)
    return b


def _find_command(bot: commands.Bot, name: str):
    for cmd in bot.tree.walk_commands():
        if cmd.name == name:
            return cmd
    raise LookupError(f"slash command '{name}' not found")


@pytest.mark.asyncio
async def test_ping_responds_with_latency(bot, interaction):
    ping_cmd = _find_command(bot, "ping")

    with patch.object(
        commands.Bot, "latency", new_callable=PropertyMock, return_value=0.042
    ):
        await ping_cmd.callback(interaction)

    sent = interaction.last_sent()
    assert sent is not None, "ping did not respond"
    assert sent.kind == "send_message"
    assert sent.content is not None
    assert "Pong" in sent.content
    assert "42ms" in sent.content
