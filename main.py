import discord
from discord.ext import commands
import json
import requests
import os
from bs4 import BeautifulSoup
import gearscore
import profile_scraper

# Cargar configuración desde .env
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN no encontrado en .env")

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
    
    # Normalizar nombre: primera letra mayúscula
    nombre = nombre.capitalize()
    
    icc_stats = {}
    rs_stats = {}
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }

        # URLs de la API y páginas HTML
        url_summary = f"https://armory.warmane.com/api/character/{nombre}/Lordaeron/summary"
        url_achievements = f"https://armory.warmane.com/character/{nombre}/Lordaeron/achievements"

        print(f"\n=== DEBUG: Consultando {nombre} ===")
        print(f"URL summary: {url_summary}")
        print(f"URL achievements: {url_achievements}")

        # Peticiones HTTP con headers
        resp_summary = requests.get(url_summary, headers=headers)
        resp_achievements = requests.get(url_achievements, headers=headers)

        print(f"Status summary: {resp_summary.status_code}")
        print(f"Status achievements: {resp_achievements.status_code}")

        # Validar si devolvió algo
        if resp_summary.status_code != 200:
            await ctx.send(f"⚠️ No se pudo acceder a la API de Warmane (summary). Código {resp_summary.status_code}")
            return

        # Intentar parsear JSON
        try:
            summary = resp_summary.json()
            print(f"Summary JSON keys: {summary.keys() if isinstance(summary, dict) else 'Not a dict'}")
            print(f"Summary content: {json.dumps(summary, indent=2)[:500]}")
        except Exception as e:
            await ctx.send(f"⚠️ Error al leer JSON de Warmane: {e}")
            print("Respuesta summary:", resp_summary.text[:500])
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
        
        print(f"Nombre: {nombre_char}, Nivel: {nivel}, Clase: {clase}")

        talents = summary.get("talents") or []
        if isinstance(talents, list) and len(talents) > 0 and isinstance(talents[0], dict):
            especializacion = talents[0].get("tree", "N/A")
        else:
            especializacion = "N/A"

        # Try to compute GearScore locally using Warmane armory scraping + local table
        try:
            print(f"Intentando obtener gear IDs para {nombre}...")
            gear_ids = profile_scraper.get_gear_ids(nombre, "Lordaeron")
            print(f"Gear IDs obtenidos: {gear_ids}")
            if gear_ids:
                gs_values = gearscore.main(gear_ids)
                gs = sum(gs_values)
                print(f"GearScore calculado: {gs} (valores por slot: {gs_values})")
            else:
                gs = summary.get("gearScore", "N/A")
                print(f"No se obtuvieron gear IDs, usando summary GS: {gs}")
        except Exception as e:
            gs = summary.get("gearScore", "N/A")
            print(f"Error calculando GS: {e}, usando summary GS: {gs}")


        guild_obj = summary.get("guild")
        guild = guild_obj if isinstance(guild_obj, str) else "Sin guild"

        # Parse achievements using POST requests (same method as WarmaneProfileParser)
        icc_10n_achieved = False
        icc_25n_achieved = False
        icc_10h_achieved = False
        icc_25h_achieved = False
        halion_10h_achieved = False
        halion_25h_achieved = False
        
        # Categories de Warmane para raids Wrath of the Lich King
        # Source: WarmaneProfileParser/static/categories.json
        # 15041 = ICC 10-player, 15042 = ICC 25-player
        # 14922 = Naxx/RS 10-player, 14923 = Naxx/RS 25-player
        raid_categories = [15041, 15042, 14922, 14923]
        
        # Los logros importantes de ICC y RS (IDs de achievement)
        # Source: WarmaneProfileParser/static/achievements.json
        target_achievements = {
            '4530': ('icc_10n', 'The Frozen Throne (10)'),
            '4597': ('icc_25n', 'The Frozen Throne (25)'),  
            '4583': ('icc_10h', 'Bane of the Fallen King (10 HC)'),
            '4584': ('icc_25h', 'The Light of Dawn (25 HC)'),
            '4817': ('halion_10n', 'The Twilight Destroyer (10)'),
            '4818': ('halion_10h', 'The Twilight Destroyer (10 HC)'),
            '4815': ('halion_25n', 'The Twilight Destroyer (25)'),
            '4816': ('halion_25h', 'The Twilight Destroyer (25 HC)')
        }
        
        for category_id in raid_categories:
            try:
                url_achi_post = f"https://armory.warmane.com/character/{nombre}/Lordaeron/achievements"
                data = {"category": category_id}
                resp_achi = requests.post(url_achi_post, headers=headers, data=data)
                
                if resp_achi.status_code == 200:
                    try:
                        achi_json = resp_achi.json()
                        if 'content' in achi_json:
                            soup = BeautifulSoup(achi_json['content'], 'html.parser')
                            all_achievements = soup.find_all('div', class_='achievement')
                            
                            # Filtrar solo los achievements completados (sin la clase 'locked')
                            completed_achievements = [
                                ach for ach in all_achievements 
                                if 'locked' not in ach.get('class', [])
                            ]
                            
                            print(f"Category {category_id}: {len(all_achievements)} total, {len(completed_achievements)} completados")
                            
                            for ach_div in completed_achievements:
                                # El ID está en el atributo id como "ach4530"
                                ach_id_full = ach_div.get('id', '')
                                if ach_id_full.startswith('ach'):
                                    ach_id = ach_id_full.replace('ach', '')
                                    
                                    if ach_id in target_achievements:
                                        key, name = target_achievements[ach_id]
                                        print(f"✓ Logro encontrado: {name} (ID: {ach_id})")
                                        
                                        if key == 'icc_10n':
                                            icc_10n_achieved = True
                                        elif key == 'icc_25n':
                                            icc_25n_achieved = True
                                        elif key == 'icc_10h':
                                            icc_10h_achieved = True
                                        elif key == 'icc_25h':
                                            icc_25h_achieved = True
                                        elif key == 'halion_10h':
                                            halion_10h_achieved = True
                                        elif key == 'halion_25h':
                                            halion_25h_achieved = True
                    except Exception as e:
                        print(f"Error parsing achievements JSON for category {category_id}: {e}")
                        
            except Exception as e:
                print(f"Error fetching achievements for category {category_id}: {e}")
        
        print(f"\nLogros ICC/RS:")
        print(f"  ICC 10N: {'✅' if icc_10n_achieved else '❌'}")
        print(f"  ICC 25N: {'✅' if icc_25n_achieved else '❌'}")
        print(f"  ICC 10HC: {'✅' if icc_10h_achieved else '❌'}")
        print(f"  ICC 25HC: {'✅' if icc_25h_achieved else '❌'}")
        print(f"  Halion 10HC: {'✅' if halion_10h_achieved else '❌'}")
        print(f"  Halion 25HC: {'✅' if halion_25h_achieved else '❌'}")


        # Construir mensaje con logros de ICC/RS
        mensaje_basico = (
            f"💎 **GearScore: {gs}**\n"
            f"🧙 **{nombre_char}** - Lvl {nivel} {clase}\n"
            f"💫 {especializacion}\n"
            f"🏰 {guild}\n"
        )

        # Usar emojis para mostrar completado/no completado
        mensaje_raid = (
            f"\n🧊 **Icecrown Citadel:**\n"
            f"  10N: {'✅' if icc_10n_achieved else '❌'} | "
            f"25N: {'✅' if icc_25n_achieved else '❌'} | "
            f"10HC: {'✅' if icc_10h_achieved else '❌'} | "
            f"25HC: {'✅' if icc_25h_achieved else '❌'}\n"
            f"🔥 **Ruby Sanctum (Halion HC):**\n"
            f"  10HC: {'✅' if halion_10h_achieved else '❌'} | "
            f"25HC: {'✅' if halion_25h_achieved else '❌'}\n"
        )

        # Send messages separately to avoid length limit
        await ctx.send(mensaje_basico)
        await ctx.send(mensaje_raid)

    except Exception as e:
        await ctx.send(f"❌ Error al obtener datos: {e}")

bot.run(TOKEN)
