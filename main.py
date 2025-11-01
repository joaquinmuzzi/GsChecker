import discord
from discord.ext import commands
import json
import requests
from bs4 import BeautifulSoup
from warmane_armory_parser import armory_parser

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
    data = armory_parser.parse_character(nombre, "Lordaeron")
    with open("mi_archivo.txt", "w") as archivo:
        archivo.write(data.to_json())
    
    # Extract ICC and RS achievements from data
    try:
        stats = data.to_json()
        if isinstance(stats, str):
            stats = json.loads(stats)
            
        icc_stats = {}
        rs_stats = {}

        # Known ICC bosses (except Lich King which is handled specially)
        known_icc_bosses = {
            "lord marrowgar", "gunship battle", "lady deathwhisper", "deathbringer",
            "festergut", "rotface", "blood prince council", "valithria dreamwalker",
            "professor putricide", "blood queen lana'thel", "sindragosa"
        }

        # verbs that indicate relevant stats
        relevant_verbs = ("kills", "victories", "rescue", "rescues", "victories over")

        # Collect all relevant statistics across all categories/subcategories
        for category in stats.get("statistics", []):
            for stat in category.get("statistics", []):
                name = stat.get("name", "")
                value = stat.get("value", "0")
                lc_name = name.lower()
                print(lc_name)

                # Ruby Sanctum / Halion: collect regardless of category
                if "ruby sanctum" in lc_name or "halion" in lc_name or "halion" in lc_name or "twilight" in lc_name:
                    rs_stats[name] = value
                    continue

                # Direct Icecrown entries are always ICC
                if "icecrown" in lc_name:
                    icc_stats[name] = value
                    continue

                # Lich King: only accept the actual "Victories over the Lich King" stat,
                # reject unrelated dungeon lines like "Lich King escapes (Halls of Reflection)"
                if "lich king" in lc_name:
                    if "victories" in lc_name and "lich king" in lc_name:
                        icc_stats[name] = value
                    # otherwise skip this stat (likely a dungeon-specific line)
                    continue

                # For other known bosses: require a relevant verb (kills/victories/rescue)
                matched = False
                for boss in known_icc_bosses:
                    if boss in lc_name and any(v in lc_name for v in relevant_verbs):
                        icc_stats[name] = value
                        matched = True
                        break
                if matched:
                    continue

                # Defensive: if stat mentions a known boss without region but contains a verb, accept it
                if any(boss in lc_name for boss in known_icc_bosses) and any(v in lc_name for v in relevant_verbs):
                    icc_stats[name] = value
                    continue

    except Exception as e:
        print(f"Error parsing ICC stats: {e}")

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


        def safe_int(value):
            """Return int(value) or 0 if not numeric."""
            if not isinstance(value, str):
                try:
                    return int(value)
                except Exception:
                    return 0
            cleaned = value.strip().replace(",", "")
            if cleaned == "- -" or cleaned == "":
                return 0
            try:
                return int(cleaned)
            except Exception:
                return 0

        def calculate_progress(stats_dict, bosses, region_indicator, difficulty):
            """Calculate progress for given bosses list and region substring and difficulty string ('10' or '25')."""
            killed = 0
            for boss in bosses:
                lower_boss = boss.lower()
                found = False
                for name, value in stats_dict.items():
                    lc_name = name.lower()
                    # match if boss present and difficulty/region present or verbs present
                    if lower_boss in lc_name:
                        # prefer specific difficulty mention
                        if f"{region_indicator.lower()} {difficulty} player" in lc_name or f"{difficulty} player" in lc_name or any(v in lc_name for v in ("kills", "victories", "rescue", "rescues")):
                            if safe_int(value) > 0:
                                killed += 1
                            found = True
                            break
                # no rigid match found -> assume not killed
            return f"{killed}/{len(bosses)}"

        icc_bosses = [
            "Lord Marrowgar",
            "Gunship Battle",
            "Lady Deathwhisper",
            "Deathbringer",
            "Festergut",
            "Rotface",
            "Blood Prince Council",
            "Valithria Dreamwalker",
            "Professor Putricide",
            "Blood Queen Lana'thel",
            "Sindragosa",
            "Victories over the Lich King"
        ]

        rs_bosses = ["Halion"]

        icc10 = calculate_progress(icc_stats, icc_bosses, "Icecrown", "10")
        icc25 = calculate_progress(icc_stats, icc_bosses, "Icecrown", "25")
        rs10 = calculate_progress(rs_stats if rs_stats else icc_stats, rs_bosses, "Ruby Sanctum", "10")
        rs25 = calculate_progress(rs_stats if rs_stats else icc_stats, rs_bosses, "Ruby Sanctum", "25")

        # Split the message into two parts
        mensaje_basico = (
            f"🧙 **{nombre_char}**\n"
            f"🏅 Nivel: {nivel}\n"
            f"⚔️ Clase: {clase}\n"
            f"💫 Especialización: {especializacion}\n"
            f"🏰 Guild: {guild}\n"
            f"💎 GearScore: {gs}\n"
        )

        mensaje_raid = (
            f"\n🧊 *ICC* — 10N: {icc10} | 25N: {icc25}\n"
            f"🔥 *RS* — 10N: {rs10} | 25N: {rs25}\n"
        )

        # Send messages separately to avoid length limit
        await ctx.send(mensaje_basico)
        await ctx.send(mensaje_raid)

    except Exception as e:
        await ctx.send(f"❌ Error al obtener datos: {e}")

bot.run(TOKEN)
