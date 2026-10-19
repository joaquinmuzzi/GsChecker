"""/ping: la latencia del bot con Discord."""

import discord

from src.controller.commands.interactions import _log_command_usage


def register(bot):
    @bot.tree.command(name="ping", description="Muestra la latencia actual del bot.")
    async def ping(interaction: discord.Interaction):
        _log_command_usage(interaction, "ping", "-", "-")
        latency = bot.latency
        if not isinstance(latency, float) or latency != latency or latency < 0:
            latency_display = "n/a"
        else:
            latency_display = f"{round(latency * 1000)}ms"
        await interaction.response.send_message(f"Pong! Latencia: {latency_display}")
