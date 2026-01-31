import discord
from discord.ext import commands
import requests
import os
import sys
import atexit
from bs4 import BeautifulSoup
import gearscore
import profile_scraper

# Cargar configuración desde .env
from dotenv import load_dotenv
load_dotenv()

LOCK_PATH = "/tmp/gschecker.lock"

def acquire_lock(lock_path: str) -> None:
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r") as f:
                pid_str = f.read().strip()
            if pid_str:
                pid = int(pid_str)
                os.kill(pid, 0)
                print(f"Otro proceso del bot ya está corriendo (PID {pid}). Saliendo.")
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

PREFIX = ["!", "/"]

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

@bot.command(aliases=["p", "per"])
async def personaje(ctx, nombre: str):
    """Muestra información del personaje desde la API de Warmane."""
    
    # Normalizar nombre: primera letra mayúscula
    nombre = nombre.capitalize()
    
    
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }

        # URLs de la API y páginas HTML
        url_summary = f"https://armory.warmane.com/api/character/{nombre}/Lordaeron/summary"
        # Petición HTTP con headers
        resp_summary = requests.get(url_summary, headers=headers)

        # Validar si devolvió algo
        if resp_summary.status_code != 200:
            await ctx.send(f"⚠️ No se pudo acceder a la API de Warmane (summary). Código {resp_summary.status_code}")
            return

        # Intentar parsear JSON
        try:
            summary = resp_summary.json()
        except Exception as e:
            await ctx.send(f"⚠️ Error al leer JSON de Warmane: {e}")
            return
        
        if not isinstance(summary, dict):
            await ctx.send("⚠️ Formato inesperado en 'summary' (no es JSON objeto). Revisa la respuesta en la consola.")
            return

        # Extraer datos básicos de forma segura
        nombre_char = summary.get("name", nombre)
        nivel = summary.get("level", "N/A")
        raza = summary.get("race", "N/A")
        clase = summary.get("class", "N/A")
        
        talents = summary.get("talents") or []
        if isinstance(talents, list) and len(talents) > 0 and isinstance(talents[0], dict):
            especializacion = talents[0].get("tree", "N/A")
        else:
            especializacion = "N/A"

        # Try to compute GearScore locally using Warmane armory scraping + local table
        try:
            gear_ids = profile_scraper.get_gear_ids(nombre, "Lordaeron")
            if gear_ids:
                gs_values = gearscore.main(gear_ids)
                gs = sum(gs_values)
            else:
                gs = summary.get("gearScore", "N/A")
        except Exception as e:
            gs = summary.get("gearScore", "N/A")


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
        halion_10n_achieved = False
        halion_10h_achieved = False
        halion_25n_achieved = False
        halion_25h_achieved = False
        
        # Categories de Warmane para raids Wrath of the Lich King
        # Source: WarmaneProfileParser/static/categories.json
        # 15041 = ICC 10-player, 15042 = ICC 25-player
        # 14922 = Naxx/RS 10-player, 14923 = Naxx/RS 25-player
        raid_categories = [15041, 15042, 14922, 14923]
        
        # Los logros importantes de ICC y RS (IDs de achievement)
        # Source: WarmaneProfileParser/static/achievements.json
        target_achievements = {
            '4817': ('halion_10n', 'The Twilight Destroyer (10)'),
            '4818': ('halion_10h', 'Heroic: The Twilight Destroyer (10)'),
            '4815': ('halion_25n', 'The Twilight Destroyer (25)'),
            '4816': ('halion_25h', 'Heroic: The Twilight Destroyer (25)')
        }

        icc_wing_pairs = {
            '10M': [
                ('Storming the Citadel', '4531', '4628'),
                ('Plagueworks', '4528', '4629'),
                ('Crimson Hall', '4529', '4630'),
                ('Frostwing Halls', '4527', '4631'),
                ('Fall of the Lich King', '4532', '4636'),
            ],
            '25M': [
                ('Storming the Citadel', '4604', '4632'),
                ('Plagueworks', '4605', '4633'),
                ('Crimson Hall', '4606', '4634'),
                ('Frostwing Halls', '4607', '4635'),
                ('Fall of the Lich King', '4608', '4637'),
            ],
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
                                        key = target_achievements[ach_id][0]
                                        
                                        if key == 'halion_10n':
                                            halion_10n_achieved = True
                                        elif key == 'halion_10h':
                                            halion_10h_achieved = True
                                        elif key == 'halion_25n':
                                            halion_25n_achieved = True
                                        elif key == 'halion_25h':
                                            halion_25h_achieved = True
                    except Exception as e:
                        print(f"Error parsing achievements JSON for category {category_id}: {e}")
                        
            except Exception as e:
                print(f"Error fetching achievements for category {category_id}: {e}")
        
        def format_wing_rows(mode_key: str) -> str:
            width = 26
            rows = []
            for name, nm_id, hc_id in icc_wing_pairs[mode_key]:
                nm = '✅' if nm_id in completed_ids else '❌'
                hc = '✅' if hc_id in completed_ids else '❌'
                rows.append(f"{name:<{width}} NM: {nm}  | HC: {hc}")
            return "\n".join(rows)

        # Construir embed con los datos solicitados
        guild_display = f"<{guild}>" if guild and guild != "Sin guild" else "Sin guild"

        embed = discord.Embed(
            title=f"Summary: {nombre_char}",
            color=0x2B2D31,
        )
        embed.add_field(name="GearScore", value=str(gs), inline=True)
        embed.add_field(name="Level | Race | Class", value=f"Level {nivel} {raza} {clase}", inline=True)
        embed.add_field(name="Spec", value=especializacion, inline=True)
        embed.add_field(name="Guild", value=guild_display, inline=True)

        embed.add_field(
            name="ICC 10M",
            value=(
                "```\n"
                f"{format_wing_rows('10M')}\n"
                "```"
            ),
            inline=False,
        )
        embed.add_field(
            name="ICC 25M",
            value=(
                "```\n"
                f"{format_wing_rows('25M')}\n"
                "```"
            ),
            inline=False,
        )

        embed.add_field(
            name="Ruby Sanctum (Normal | Heroic)",
            value=(
                "```\n"
                "       Normal    Heroic\n"
                f"10M:   {'✅' if halion_10n_achieved else '❌'}       {'✅' if halion_10h_achieved else '❌'}\n"
                f"25M:   {'✅' if halion_25n_achieved else '❌'}       {'✅' if halion_25h_achieved else '❌'}\n"
                "```"
            ),
            inline=False,
        )

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error al obtener datos: {e}")

bot.run(TOKEN)
