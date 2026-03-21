import discord
from discord.ext import commands
import os
import sys
import atexit

from dotenv import load_dotenv

from src.db.postgres import init_database
from src.schemas.constants import PREFIX
from src.controller.commands import register_commands

load_dotenv()
init_database()

LOCK_PATH = "/tmp/gschecker.lock"


def acquire_lock(lock_path: str) -> None:
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r") as f:
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

    with open(lock_path, "w") as f:
        f.write(str(os.getpid()))

    def _cleanup() -> None:
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except Exception:
            pass

    atexit.register(_cleanup)


acquire_lock(LOCK_PATH)

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN no encontrado en .env")

intents = discord.Intents.default()
intents.message_content = True


class GsCheckerBot(commands.Bot):
    async def setup_hook(self):
        synced = await self.tree.sync()
        print(f"Slash commands sincronizados: {len(synced)}")


bot = GsCheckerBot(command_prefix=PREFIX, intents=intents)
register_commands(bot)


@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    raise error


bot.run(TOKEN)
