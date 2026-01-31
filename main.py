import discord
from discord.ext import commands
import requests
import os
import sys
import atexit
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
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

SESSION = requests.Session()
HTTP_TIMEOUT = 8

SUMMARY_CACHE = {}
ACHIEVEMENTS_CACHE = {}
GEAR_CACHE = {}
SUMMARY_TTL = 120
ACHIEVEMENTS_TTL = 300
GEAR_TTL = 120

EXECUTOR = ThreadPoolExecutor(max_workers=6)

def _cache_get(cache: dict, key, ttl: int):
    entry = cache.get(key)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > ttl:
        cache.pop(key, None)
        return None
    return value

def _cache_set(cache: dict, key, value):
    cache[key] = (time.time(), value)

def _fetch_summary(nombre: str, server: str):
    cache_key = (nombre, server)
    cached = _cache_get(SUMMARY_CACHE, cache_key, SUMMARY_TTL)
    if cached is not None:
        return cached

    url_summary = f"https://armory.warmane.com/api/character/{nombre}/{server}/summary"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp_summary = SESSION.get(url_summary, headers=headers, timeout=HTTP_TIMEOUT)
    if resp_summary.status_code != 200:
        return {"__error__": f"⚠️ No se pudo acceder a la API de Warmane (summary). Código {resp_summary.status_code}"}
    try:
        summary = resp_summary.json()
    except Exception as e:
        return {"__error__": f"⚠️ Error al leer JSON de Warmane: {e}"}
    _cache_set(SUMMARY_CACHE, cache_key, summary)
    return summary

def _fetch_achievements(nombre: str, server: str):
    cache_key = (nombre, server)
    cached = _cache_get(ACHIEVEMENTS_CACHE, cache_key, ACHIEVEMENTS_TTL)
    if cached is not None:
        return cached

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    raid_categories = [15041, 15042, 14922, 14923]

    icc_sections = {
        '4531': 4,
        '4528': 3,
        '4529': 2,
        '4527': 2,
        '4532': 1,
        '4604': 4,
        '4605': 3,
        '4606': 2,
        '4607': 2,
        '4608': 1,
        '4628': 4,
        '4629': 3,
        '4630': 2,
        '4631': 2,
        '4636': 1,
        '4632': 4,
        '4633': 3,
        '4634': 2,
        '4635': 2,
        '4637': 1,
    }

    target_achievements = {
        '4817': ('halion_10n', 'The Twilight Destroyer (10)'),
        '4818': ('halion_10h', 'Heroic: The Twilight Destroyer (10)'),
        '4815': ('halion_25n', 'The Twilight Destroyer (25)'),
        '4816': ('halion_25h', 'Heroic: The Twilight Destroyer (25)')
    }

    completed_ids = set()
    icc_10n_bosses = 0
    icc_25n_bosses = 0
    icc_10h_bosses = 0
    icc_25h_bosses = 0
    halion_10n_achieved = False
    halion_10h_achieved = False
    halion_25n_achieved = False
    halion_25h_achieved = False

    def fetch_category(category_id: int):
        url_achi_post = f"https://armory.warmane.com/character/{nombre}/{server}/achievements"
        data = {"category": category_id}
        resp_achi = SESSION.post(url_achi_post, headers=headers, data=data, timeout=HTTP_TIMEOUT)
        if resp_achi.status_code != 200:
            return []
        try:
            achi_json = resp_achi.json()
        except Exception:
            return []
        if 'content' not in achi_json:
            return []
        soup = BeautifulSoup(achi_json['content'], 'html.parser')
        all_achievements = soup.find_all('div', class_='achievement')
        completed_achievements = [
            ach for ach in all_achievements
            if 'locked' not in ach.get('class', [])
        ]
        ids = []
        for ach_div in completed_achievements:
            ach_id_full = ach_div.get('id', '')
            if ach_id_full.startswith('ach'):
                ids.append(ach_id_full.replace('ach', ''))
        return ids

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch_category, raid_categories))

    for ids in results:
        for ach_id in ids:
            completed_ids.add(ach_id)
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

    payload = {
        "completed_ids": completed_ids,
        "icc_10n_bosses": icc_10n_bosses,
        "icc_25n_bosses": icc_25n_bosses,
        "icc_10h_bosses": icc_10h_bosses,
        "icc_25h_bosses": icc_25h_bosses,
        "halion_10n_achieved": halion_10n_achieved,
        "halion_10h_achieved": halion_10h_achieved,
        "halion_25n_achieved": halion_25n_achieved,
        "halion_25h_achieved": halion_25h_achieved,
    }
    _cache_set(ACHIEVEMENTS_CACHE, cache_key, payload)
    return payload

def _fetch_gear_data(nombre: str, server: str):
    cache_key = (nombre, server)
    cached = _cache_get(GEAR_CACHE, cache_key, GEAR_TTL)
    if cached is not None:
        return cached
    gear_data = profile_scraper.get_gear_data(nombre, server)
    _cache_set(GEAR_CACHE, cache_key, gear_data)
    return gear_data

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
        loop = asyncio.get_running_loop()

        summary_task = loop.run_in_executor(EXECUTOR, _fetch_summary, nombre, "Lordaeron")
        gear_task = loop.run_in_executor(EXECUTOR, _fetch_gear_data, nombre, "Lordaeron")
        achi_task = loop.run_in_executor(EXECUTOR, _fetch_achievements, nombre, "Lordaeron")

        summary, gear_data, achi_payload = await asyncio.gather(
            summary_task, gear_task, achi_task
        )

        if isinstance(summary, dict) and summary.get("__error__"):
            await ctx.send(summary["__error__"])
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
            gear_ids = profile_scraper.get_gear_ids_from_gear_data(gear_data)
            if gear_ids:
                gs_values = gearscore.main(gear_ids)
                gs = sum(gs_values)
            else:
                gs = summary.get("gearScore", "N/A")
        except Exception:
            gs = summary.get("gearScore", "N/A")

        # Missing enchants and gems
        try:
            missing_enchants, missing_gems = profile_scraper.get_missing_enchants_gems_from_gear_data(gear_data)
        except Exception:
            missing_enchants, missing_gems = [], []


        guild_obj = summary.get("guild")
        guild = guild_obj if isinstance(guild_obj, str) else "Sin guild"

        icc_10n_bosses = achi_payload["icc_10n_bosses"]
        icc_25n_bosses = achi_payload["icc_25n_bosses"]
        icc_10h_bosses = achi_payload["icc_10h_bosses"]
        icc_25h_bosses = achi_payload["icc_25h_bosses"]
        halion_10n_achieved = achi_payload["halion_10n_achieved"]
        halion_10h_achieved = achi_payload["halion_10h_achieved"]
        halion_25n_achieved = achi_payload["halion_25n_achieved"]
        halion_25h_achieved = achi_payload["halion_25h_achieved"]

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
        completed_ids = set(achi_payload["completed_ids"])
        
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
            name="Armory",
            value=(f"https://armory.warmane.com/character/{nombre_char}/Lordaeron/profile"),
            inline=False,
        )

        embed.add_field(
            name="Uwulogs",
            value=(f"https://uwu-logs.xyz/character?name={nombre_char}&server=Lordaeron"),
            inline=False,
        )

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
            name="Ruby Sanctum",
            value=(
                "```\n"
                "       Normal    Heroic\n"
                f"10M:   {'✅' if halion_10n_achieved else '❌'}       {'✅' if halion_10h_achieved else '❌'}\n"
                f"25M:   {'✅' if halion_25n_achieved else '❌'}       {'✅' if halion_25h_achieved else '❌'}\n"
                "```"
            ),
            inline=False,
        )

        if missing_enchants or missing_gems:
            missing_lines = []
            if missing_enchants:
                missing_lines.append("Enchants Missing:")
                missing_lines.extend(f"- {slot}" for slot in missing_enchants)

            if missing_gems:
                missing_lines.append("Gems Missing:")
                missing_lines.extend(f"- {slot}" for slot in missing_gems)

            embed.add_field(
                name="Enchants / Gems",
                value=(
                    "```\n"
                    + "\n".join(missing_lines)
                    + "\n```"
                ),
                inline=False,
            )


        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error al obtener datos: {e}")

bot.run(TOKEN)
