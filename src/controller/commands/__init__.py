"""Slash commands del bot: un módulo por comando.

Cada módulo expone `register(bot)`; `register_commands` los registra todos en
`bot.tree`, en el mismo orden de siempre. `personaje_refresh` registra el botón
Actualizar de /p.
"""

from src.controller.commands import dps, ia, logs, personaje, personaje_refresh, ping, ptoc


def register_commands(bot):
    for module in (ping, personaje, personaje_refresh, dps, logs, ptoc, ia):
        module.register(bot)
