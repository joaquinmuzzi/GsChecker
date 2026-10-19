"""Registro de los personajes que el cron tiene que precargar."""

import asyncio

from src.db.postgres import async_track_character_lookup

# El event loop solo guarda referencias débiles a las tareas: sin una referencia
# propia, un registro en curso podía ser recolectado antes de terminar.
_PENDING_TASKS: set[asyncio.Task] = set()


def _track_character(nombre_char: str, realm: str) -> None:
    """Registra el personaje en Postgres para que el cron lo precargue.

    Solo se llama cuando el armory confirmó que existe en ese reino y es 80.
    Antes se registraba al usar el comando y los typos, los reinos equivocados
    y los personajes que no son 80 quedaban en la lista para siempre: el cron
    los reintentaba todos los días (16 SKIP diarios, 2026-10-10).
    Fire-and-forget: los errores de DB nunca frenan el comando.
    """
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(async_track_character_lookup(nombre_char, realm))
    except RuntimeError:
        return
    _PENDING_TASKS.add(task)
    task.add_done_callback(_PENDING_TASKS.discard)
