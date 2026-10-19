"""Helpers sobre `discord.Interaction` que comparten todos los comandos.

Responder, editar y mandar errores sin que un 404, un 429 o un token vencido
de Discord rompan el comando.
"""

import asyncio
import logging

import discord

# Mismo logger que antes del split: los logs de Railway no cambian.
logger = logging.getLogger("gschecker.commands")


def _log_command_usage(
    interaction: discord.Interaction,
    command_name: str,
    nombre: str,
    realm: str,
    **extra,
) -> None:
    # Single structured entry per command invocation. Appears in Railway Deploy Logs
    # and in logs/bot.log via the root 'gschecker' logger configured in main.py.
    user = interaction.user
    guild = interaction.guild
    extras = "".join(f" {key}={value!r}" for key, value in extra.items() if value is not None)
    logger.info(
        "command=%s user=%s(%s) guild=%s(%s) character=%r realm=%r%s",
        command_name,
        getattr(user, "name", "unknown"),
        getattr(user, "id", "unknown"),
        getattr(guild, "name", "DM"),
        getattr(guild, "id", "dm"),
        nombre,
        realm,
        extras,
    )


async def _safe_defer(interaction: discord.Interaction) -> None:
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(thinking=True)
    except discord.HTTPException as exc:
        if getattr(exc, "code", None) != 40060:
            raise
        # Otro proceso con el mismo token ya respondió esta interacción: los
        # dos editarían el mismo mensaje.
        logger.warning("defer: interacción ya respondida (40060): %s", exc)


def _http_retry_after(exc: discord.HTTPException) -> float:
    retry_after = 0.0
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            header_val = response.headers.get("Retry-After")
            if header_val:
                retry_after = float(header_val)
        except Exception:
            retry_after = 0.0
    return max(retry_after, 0.0)


def _is_expired_token(exc: discord.HTTPException) -> bool:
    return getattr(exc, "status", None) == 401 and getattr(exc, "code", None) == 50027


async def _safe_edit_original_response(
    interaction: discord.Interaction, *, content=None, embed=None, view=None
):
    """Devuelve el mensaje que respondió Discord, o None si no se pudo editar."""
    last_exc = None
    for attempt in range(4):
        try:
            kwargs = {"content": content, "embed": embed}
            if view is not None:
                kwargs["view"] = view
            return await interaction.edit_original_response(**kwargs)
        except discord.NotFound:
            logger.warning(
                "edit_original_response NotFound (mensaje o interacción inexistente) command=%s",
                getattr(getattr(interaction, "command", None), "name", "?"),
            )
            return
        except discord.HTTPException as exc:
            if _is_expired_token(exc):
                logger.warning("edit_original_response con token vencido: %s", exc)
                return
            if getattr(exc, "status", None) != 429:
                raise
            last_exc = exc
            wait_for = _http_retry_after(exc) or min(2**attempt, 8)
            await asyncio.sleep(wait_for)
    if last_exc:
        raise last_exc


def _embed_fields_signature(embed) -> list[tuple[str, str]]:
    # Discord recorta espacios al final de los valores: se comparan sin ellos.
    return [(str(f.name), " ".join(str(f.value).split())) for f in embed.fields]


def _message_has_embed(message, embed: discord.Embed) -> bool:
    embeds = getattr(message, "embeds", None) or []
    return bool(embeds) and _embed_fields_signature(embeds[0]) == _embed_fields_signature(embed)


async def _safe_send_error(interaction: discord.Interaction, message: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message)
        else:
            await interaction.response.send_message(message)
    except discord.NotFound:
        return
    except discord.HTTPException as exc:
        if _is_expired_token(exc):
            return
        if getattr(exc, "status", None) != 429:
            raise
        wait_for = _http_retry_after(exc) or 3
        await asyncio.sleep(wait_for)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message)
            else:
                await interaction.response.send_message(message)
        except Exception:
            logger.exception("_safe_send_error: retry send failed")


async def _reply_command_error(interaction: discord.Interaction, exc: Exception, fallback: str) -> None:
    """La respuesta de todos los comandos cuando algo falla: Discord ya no tiene
    el mensaje o el token venció (nada que responder), error de red de Discord,
    `ValueError` con un mensaje para el usuario (nombre o reino inválido) o
    cualquier otro error, que se muestra como `{fallback}: {exc}`."""
    if isinstance(exc, discord.NotFound):
        return
    if isinstance(exc, discord.HTTPException):
        if not _is_expired_token(exc):
            await _safe_send_error(interaction, f"❌ Error de red: {exc}")
        return
    if isinstance(exc, ValueError):
        await _safe_send_error(interaction, str(exc))
        return
    await _safe_send_error(interaction, f"{fallback}: {exc}")
