"""Cooldown de los perfiles de /p armados en vivo (botón Actualizar).

Rehacer un perfil gasta ~15 requests del armory, y su rate limit lo comparten
todos los usuarios del bot: un botón que cualquiera puede apretar muchas veces
podía dejar al bot bloqueado para todos (429 o 1015 de Cloudflare).
El estado vive en memoria: alcanza con un solo proceso del bot, y un reinicio
solo lo vacía.
"""

import math
import time

# Un perfil recién armado en vivo no se vuelve a armar antes de esto. Cubre
# también los cachés en memoria del armory (hasta 300 s): pasado este tiempo,
# actualizar vuelve a leer el armory de verdad.
CHARACTER_COOLDOWN_SECONDS = 300
# Cada usuario puede actualizar un personaje por minuto.
USER_COOLDOWN_SECONDS = 60

_last_by_character: dict[tuple[str, str], float] = {}
_last_by_user: dict[int, float] = {}


def _character_key(nombre: str, realm: str) -> tuple[str, str]:
    return nombre.strip().lower(), realm.strip().lower()


def _refresh_wait(
    nombre: str, realm: str, user_id: int | None, now: float | None = None
) -> tuple[str, int] | None:
    """`("character" | "user", segundos que faltan)` si todavía no se puede
    actualizar el personaje, o None si ya se puede."""
    now = time.monotonic() if now is None else now
    last = _last_by_character.get(_character_key(nombre, realm))
    if last is not None and now - last < CHARACTER_COOLDOWN_SECONDS:
        return "character", math.ceil(CHARACTER_COOLDOWN_SECONDS - (now - last))
    last = _last_by_user.get(user_id) if user_id is not None else None
    if last is not None and now - last < USER_COOLDOWN_SECONDS:
        return "user", math.ceil(USER_COOLDOWN_SECONDS - (now - last))
    return None


def _mark_live_profile(nombre: str, realm: str, user_id: int | None = None, now: float | None = None) -> None:
    """Arranca el cooldown del personaje (y del usuario que apretó el botón)."""
    now = time.monotonic() if now is None else now
    # Se descarta lo vencido para que los dicts no crezcan sin límite.
    for key, last in list(_last_by_character.items()):
        if now - last >= CHARACTER_COOLDOWN_SECONDS:
            del _last_by_character[key]
    for uid, last in list(_last_by_user.items()):
        if now - last >= USER_COOLDOWN_SECONDS:
            del _last_by_user[uid]
    _last_by_character[_character_key(nombre, realm)] = now
    if user_id is not None:
        _last_by_user[user_id] = now


def _reset_refresh_cooldowns() -> None:
    """Solo para tests."""
    _last_by_character.clear()
    _last_by_user.clear()
