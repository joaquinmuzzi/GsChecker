import discord
from discord.ext import commands
import json
import requests

# Cargar configuración
with open("config.json", "r") as f:
    config = json.load(f)

TOKEN = config["TOKEN"]
PREFIX = "!"

# Crear el bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")

@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong! Latencia: {round(bot.latency * 1000)}ms")

@bot.command()
async def personaje(ctx, nombre: str):
    """Muestra información del personaje desde la API de Warmane."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }

        # URLs de la API
        url_summary = f"https://armory.warmane.com/api/character/{nombre}/Lordaeron/summary"
        url_achievements = f"https://armory.warmane.com/api/character/{nombre}/Lordaeron/achievements"

        # Peticiones HTTP con headers
        resp_summary = requests.get(url_summary, headers=headers)
        resp_achievements = requests.get(url_achievements, headers=headers)

        # Mostrar códigos de estado para debug

        # Validar si devolvió algo
        if resp_summary.status_code != 200:
            await ctx.send(f"⚠️ No se pudo acceder a la API de Warmane (summary). Código {resp_summary.status_code}")
            return
        if resp_achievements.status_code != 200:
            await ctx.send(f"⚠️ No se pudo acceder a la API de Warmane (achievements). Código {resp_achievements.status_code}")
            return

        # Intentar parsear JSON
        try:
            summary = resp_summary.json()
            achievements = resp_achievements.json()
        except Exception as e:
            await ctx.send(f"⚠️ Error al leer JSON de Warmane: {e}")
            print("Respuesta summary:", resp_summary.text[:200])
            print("Respuesta achievements:", resp_achievements.text[:200])
            return
        
        # DEBUG: ensure we have the expected types
        if not isinstance(summary, dict):
            await ctx.send("⚠️ Formato inesperado en 'summary' (no es JSON objeto). Revisa la respuesta en la consola.")
            print("summary raw:", summary)
            return
        if not isinstance(achievements, dict):
            # try to recover if achievements contains a JSON string
            if isinstance(achievements, str):
                import json as _json
                try:
                    achievements = _json.loads(achievements)
                except Exception:
                    await ctx.send("⚠️ Formato inesperado en 'achievements'. Revisa la respuesta en la consola.")
                    print("achievements raw:", achievements)
                    return
            else:
                await ctx.send("⚠️ Formato inesperado en 'achievements'. Revisa la respuesta en la consola.")
                print("achievements raw:", achievements)
                return

        # Extraer datos básicos de forma segura
        nombre_char = summary.get("name", nombre)
        nivel = summary.get("level", "N/A")
        clase = summary.get("class", "N/A")

        talents = summary.get("talents") or []
        if isinstance(talents, list) and len(talents) > 0 and isinstance(talents[0], dict):
            especializacion = talents[0].get("tree", "N/A")
        else:
            especializacion = "N/A"

        gs = summary.get("gearScore", "N/A")

        guild_obj = summary.get("guild")
        guild = guild_obj.get("name", "Sin guild") if isinstance(guild_obj, dict) else "Sin guild"

        # Progreso ICC / RS (si existen) — acceder de forma segura
        instances = achievements.get("instances", {}) if isinstance(achievements, dict) else {}
        if isinstance(instances, str):
            import json as _json
            try:
                instances = _json.loads(instances)
            except Exception:
                instances = {}

        def inst_progress(name, default):
            if isinstance(instances, dict):
                return instances.get(name, {}).get("progress", default)
            return default

        icc10 = inst_progress("Icecrown Citadel 10 Player", "0/12")
        icc25 = inst_progress("Icecrown Citadel 25 Player", "0/12")
        rs10 = inst_progress("The Ruby Sanctum 10 Player", "0/4")
        rs25 = inst_progress("The Ruby Sanctum 25 Player", "0/4")

        mensaje = (
            f"🧙 **{nombre_char}**\n"
            f"🏅 Nivel: {nivel}\n"
            f"⚔️ Clase: {clase}\n"
            f"💫 Especialización: {especializacion}\n"
            f"🏰 Guild: {guild}\n"
            f"💎 GearScore: {gs}\n\n"
            f"🧊 *ICC* — 10N: {icc10} | 25N: {icc25}\n"
            f"🔥 *RS* — 10N: {rs10} | 25N: {rs25}\n"
        )

        await ctx.send(mensaje)

    except Exception as e:
        await ctx.send(f"❌ Error al obtener datos: {e}")

bot.run(TOKEN)
