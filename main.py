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
        raza = summary.get("race", "N/A")
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
        # ICC boss counts (cada achievement de sección representa ciertos bosses)
        icc_sections = {
            '4531': 4,  # ICC10N Storming the Citadel (4 bosses)
            '4528': 3,  # ICC10N Plagueworks (3 bosses)
            '4529': 2,  # ICC10N Crimson Hall (2 bosses)
            '4527': 2,  # ICC10N Frostwing Halls (2 bosses)
            '4532': 1,  # ICC10N Fall of Lich King (1 boss)
            '4604': 4,  # ICC25N Storming the Citadel
            '4605': 3,  # ICC25N Plagueworks
            '4606': 2,  # ICC25N Crimson Hall
            '4607': 2,  # ICC25N Frostwing Halls
            '4608': 1,  # ICC25N Fall of Lich King
            '4628': 4,  # ICC10HC Storming the Citadel
            '4629': 3,  # ICC10HC Plagueworks
            '4630': 2,  # ICC10HC Crimson Hall
            '4631': 2,  # ICC10HC Frostwing Halls
            '4636': 1,  # ICC10HC Fall of Lich King
            '4632': 4,  # ICC25HC Storming the Citadel
            '4633': 3,  # ICC25HC Plagueworks
            '4634': 2,  # ICC25HC Crimson Hall
            '4635': 2,  # ICC25HC Frostwing Halls
            '4637': 1,  # ICC25HC Fall of Lich King
        }
        
        icc_10n_bosses = 0
        icc_25n_bosses = 0
        icc_10h_bosses = 0
        icc_25h_bosses = 0
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
            '4817': ('halion_10h', 'The Twilight Destroyer (10)'),
            '4818': ('halion_10h', 'Heroic: The Twilight Destroyer (10)'),
            '4815': ('halion_25h', 'The Twilight Destroyer (25)'),
            '4816': ('halion_25h', 'Heroic: The Twilight Destroyer (25)')
        }

        icc_wing_achievements = {
            '10N': {
                '4531': 'Storming the Citadel',
                '4528': 'The Plagueworks',
                '4529': 'The Crimson Hall',
                '4527': 'The Frostwing Halls',
                '4532': 'Fall of the Lich King'
            },
            '10H': {
                '4628': 'Heroic: Storming the Citadel',
                '4629': 'Heroic: The Plagueworks',
                '4630': 'Heroic: The Crimson Hall',
                '4631': 'Heroic: The Frostwing Halls',
                '4636': 'Heroic: Fall of the Lich King'
            },
            '25N': {
                '4604': 'Storming the Citadel',
                '4605': 'The Plagueworks',
                '4606': 'The Crimson Hall',
                '4607': 'The Frostwing Halls',
                '4608': 'Fall of the Lich King'
            },
            '25H': {
                '4632': 'Heroic: Storming the Citadel',
                '4633': 'Heroic: The Plagueworks',
                '4634': 'Heroic: The Crimson Hall',
                '4635': 'Heroic: The Frostwing Halls',
                '4637': 'Heroic: Fall of the Lich King'
            }
        }

        completed_ids = set()
        
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
                                    completed_ids.add(ach_id)
                                    
                                    # Contar bosses de ICC por sección
                                    if ach_id in icc_sections:
                                        bosses = icc_sections[ach_id]
                                        if ach_id in ['4531', '4528', '4529', '4527', '4532']:
                                            icc_10n_bosses += bosses
                                        elif ach_id in ['4604', '4605', '4606', '4607', '4608']:
                                            icc_25n_bosses += bosses
                                        elif ach_id in ['4628', '4629', '4630', '4631', '4636']:
                                            icc_10h_bosses += bosses
                                        elif ach_id in ['4632', '4633', '4634', '4635', '4637']:
                                            icc_25h_bosses += bosses
                                    
                                    # Detectar Halion
                                    if ach_id in target_achievements:
                                        key, name = target_achievements[ach_id]
                                        print(f"✓ Logro encontrado: {name} (ID: {ach_id})")
                                        
                                        if key == 'halion_10h':
                                            halion_10h_achieved = True
                                        elif key == 'halion_25h':
                                            halion_25h_achieved = True
                    except Exception as e:
                        print(f"Error parsing achievements JSON for category {category_id}: {e}")
                        
            except Exception as e:
                print(f"Error fetching achievements for category {category_id}: {e}")
        
        print(f"\nProgreso ICC/RS:")
        print(f"  ICC 10N: {icc_10n_bosses}/12 bosses")
        print(f"  ICC 25N: {icc_25n_bosses}/12 bosses")
        print(f"  ICC 10HC: {icc_10h_bosses}/12 bosses")
        print(f"  ICC 25HC: {icc_25h_bosses}/12 bosses")
        print(f"  Halion 10HC: {'✅' if halion_10h_achieved else '❌'}")
        print(f"  Halion 25HC: {'✅' if halion_25h_achieved else '❌'}")


        def format_wing_list(mode_key: str) -> list[str]:
            lines = []
            for ach_id, name in icc_wing_achievements[mode_key].items():
                status = '✅' if ach_id in completed_ids else '❌'
                lines.append(f"{status} {name}")
            return lines

        def format_two_column(normal_key: str, heroic_key: str) -> str:
            normal_lines = format_wing_list(normal_key)
            heroic_lines = format_wing_list(heroic_key)
            width = 34
            rows = []
            max_len = max(len(normal_lines), len(heroic_lines))
            for i in range(max_len):
                left = normal_lines[i] if i < len(normal_lines) else ""
                right = heroic_lines[i] if i < len(heroic_lines) else ""
                rows.append(f"{left:<{width}}  {right}")
            return "\n".join(rows)

        # Construir embed con los datos solicitados
        guild_display = f"<{guild}>" if guild and guild != "Sin guild" else "Sin guild"

        embed = discord.Embed(
            title=f"Summary: {nombre_char}-Lordaeron",
            color=0x2B2D31,
        )
        embed.add_field(name="GearScore", value=str(gs), inline=True)
        embed.add_field(name="Level | Race | Class", value=f"Level {nivel} {raza} {clase}", inline=True)
        embed.add_field(name="Spec", value=especializacion, inline=True)
        embed.add_field(name="Guild", value=guild_display, inline=True)

        embed.add_field(
            name="Icecrown Citadel (ICC) - Progress",
            value=(
                "```\n"
                "       Normal    Heroic\n"
                f"10M:   {icc_10n_bosses:2}/12      {icc_10h_bosses:2}/12\n"
                f"25M:   {icc_25n_bosses:2}/12      {icc_25h_bosses:2}/12\n"
                "```"
            ),
            inline=False,
        )

        embed.add_field(
            name="ICC 10M (Normal | Heroic)",
            value=(
                "```\n"
                f"{format_two_column('10N', '10H')}\n"
                "```"
            ),
            inline=False,
        )
        embed.add_field(
            name="ICC 25M (Normal | Heroic)",
            value=(
                "```\n"
                f"{format_two_column('25N', '25H')}\n"
                "```"
            ),
            inline=False,
        )

        embed.add_field(
            name="Ruby Sanctum (Halion HC)",
            value=(
                "```\n"
                f"10HC: {'✅' if halion_10h_achieved else '❌'}\n"
                f"25HC: {'✅' if halion_25h_achieved else '❌'}\n"
                "```"
            ),
            inline=False,
        )

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error al obtener datos: {e}")

bot.run(TOKEN)
