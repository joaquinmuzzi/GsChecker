import discord
from discord.ext import commands
import json
import requests
from bs4 import BeautifulSoup

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
        url_achievements = f"https://armory.warmane.com/character/{nombre}/Lordaeron/achievements"

        # Peticiones HTTP con headers
        resp_summary = requests.get(url_summary, headers=headers)
        resp_achievements = requests.get(url_achievements, headers=headers)

        # Mostrar códigos de estado para debug

        # Validar si devolvió algo
        if resp_summary.status_code != 200:
            await ctx.send(f"⚠️ No se pudo acceder a la API de Warmane (summary). Código {resp_summary.status_code}")
            return

        # Intentar parsear JSON
        try:
            summary = resp_summary.json()
        except Exception as e:
            await ctx.send(f"⚠️ Error al leer JSON de Warmane: {e}")
            print("Respuesta summary:", resp_summary.text[:200])
            return
        
        # DEBUG: ensure we have the expected types
        if not isinstance(summary, dict):
            await ctx.send("⚠️ Formato inesperado en 'summary' (no es JSON objeto). Revisa la respuesta en la consola.")
            print("summary raw:", summary)
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
        guild = guild_obj if isinstance(guild_obj, str) else "Sin guild"


        # Obtener la página
        resp = requests.get(url_achievements, headers=headers)
        html = resp.text

        soup = BeautifulSoup(html, "lxml")

        # Buscar las secciones "Fall of the Lich King"
        sections = soup.find_all("div", class_="selected", string=lambda s: s and "Fall of the Lich King" in s)

        icc10_progress = "0/12"
        icc25_progress = "0/12"
        rs10_progress = "0/4"
        rs25_progress = "0/4"

        for section in sections:
            # Buscar el siguiente contenedor con logros
            container = section.find_next("div", class_="achievements")
            if not container:
                continue

            achievements = container.find_all("div", class_="achievement")

            for ach in achievements:
                name = ach.find("div", class_="title").get_text(strip=True)
                complete = "completed" in ach.get("class", [])

                # Detectar los logros de ICC o RS
                if "The Frozen Throne (10 player)" in name:
                    icc10_progress = "12/12" if complete else icc10_progress
                elif "The Frozen Throne (25 player)" in name:
                    icc25_progress = "12/12" if complete else icc25_progress
                elif "The Twilight Destroyer (10 player)" in name:
                    rs10_progress = "4/4" if complete else rs10_progress
                elif "The Twilight Destroyer (25 player)" in name:
                    rs25_progress = "4/4" if complete else rs25_progress

        icc10 = icc10_progress
        icc25 = icc25_progress
        rs10 = rs10_progress
        rs25 = rs25_progress

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
