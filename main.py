import atexit
import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler

import discord
from discord.ext import commands
from dotenv import load_dotenv

from src.controller.commands import register_commands
from src.db.postgres import init_database
from src.schemas.constants import PREFIX


LOCK_PATH = "/tmp/gschecker.lock"


def configure_logging() -> logging.Logger:
    os.makedirs("logs", exist_ok=True)
    logger = logging.getLogger("gschecker")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    info_handler = RotatingFileHandler(
        "logs/bot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)

    error_handler = RotatingFileHandler(
        "logs/bot-errors.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(info_handler)
    logger.addHandler(error_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False

    return logger


def acquire_lock(lock_path: str) -> None:
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                pid_str = f.read().strip()
            if pid_str:
                pid = int(pid_str)
                os.kill(pid, 0)
                print(f"Otro proceso del bot ya esta corriendo (PID {pid}). Saliendo.")
                sys.exit(1)
        except ProcessLookupError:
            pass
        except Exception:
            pass

    with open(lock_path, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    def _cleanup() -> None:
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except Exception:
            pass

    atexit.register(_cleanup)


load_dotenv()
init_database()
logger = configure_logging()
acquire_lock(LOCK_PATH)

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN no encontrado en .env")

intents = discord.Intents.default()
intents.message_content = True


class GsCheckerBot(commands.Bot):
    async def setup_hook(self):
        synced = await self.tree.sync()
        logger.info("Slash commands sincronizados: %s", len(synced))


bot = GsCheckerBot(command_prefix=PREFIX, intents=intents)
register_commands(bot)


@bot.event
async def on_ready():
    logger.info("Bot conectado como %s", bot.user)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error("Error en comando de texto: %s", error, exc_info=error)
    raise error


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    logger.error(
        "Error en slash command user=%s guild=%s command=%s",
        getattr(interaction.user, "id", "unknown"),
        getattr(interaction.guild, "id", "dm"),
        getattr(getattr(interaction, "command", None), "name", "unknown"),
        exc_info=error,
    )

    message = "⚠️ Ocurrió un error interno procesando el comando."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception:
        logger.error("No se pudo enviar feedback de error al usuario", exc_info=True)


@bot.event
async def on_error(event, *args, **kwargs):
    logger.error("Error no manejado en evento Discord: %s", event, exc_info=True)


def _log_uncaught_exception(exc_type, exc, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        return
    logger.error(
        "Excepción no capturada: %s",
        "".join(traceback.format_exception(exc_type, exc, exc_tb)),
    )


sys.excepthook = _log_uncaught_exception

bot.run(TOKEN)
