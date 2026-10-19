"""Slash commands del bot: un módulo por comando.

Cada módulo expone `register(bot)`; `register_commands` los registra todos en
`bot.tree`, en el mismo orden de siempre.
"""

from src.controller.commands import dps, ia, logs, personaje, ping, ptoc


def register_commands(bot):
    for module in (ping, personaje, dps, logs, ptoc, ia):
        module.register(bot)
