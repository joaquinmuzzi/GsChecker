import discord
from discord.ext import commands
import requests
import os
import sys
import atexit
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
import unicodedata
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

PREFIX = ["/"]

SESSION = requests.Session()
HTTP_TIMEOUT = 8
UWU_BASE = "https://uwu-logs.xyz"
UWU_SERVER = "Lordaeron"

SUMMARY_CACHE = {}
ACHIEVEMENTS_CACHE = {}
GEAR_CACHE = {}
STATS_CACHE = {}
UWU_CHARACTER_CACHE = {}
UWU_TOP_CACHE = {}
SUMMARY_TTL = 120
ACHIEVEMENTS_TTL = 300
GEAR_TTL = 120
STATS_TTL = 300
UWU_CHARACTER_TTL = 120
UWU_TOP_TTL = 180

UWU_BOSS_MODE = {
    "Lord Marrowgar": "25H",
    "Lady Deathwhisper": "25H",
    "Deathbringer Saurfang": "25H",
    "Festergut": "25H",
    "Rotface": "25H",
    "Professor Putricide": "25H",
    "Blood Prince Council": "25H",
    "Blood-Queen Lana'thel": "25H",
    "Sindragosa": "25H",
    "The Lich King": "25H",
    "Toravon the Ice Watcher": "25N",
    "Halion": "25H",
    "Anub'arak": "25H",
    "Valithria Dreamwalker": "25H",
}

UWU_BOSS_SHORT = {
    "Lord Marrowgar": "Marrowgar",
    "Lady Deathwhisper": "Deathwsp",
    "Deathbringer Saurfang": "Saurfang",
    "Festergut": "Festergut",
    "Rotface": "Rotface",
    "Professor Putricide": "Putricide",
    "Blood Prince Council": "B. Prince",
    "Blood-Queen Lana'thel": "B. Queen",
    "Sindragosa": "Sindragosa",
    "The Lich King": "Lich King",
    "Toravon the Ice Watcher": "Toravon",
    "Halion": "Halion",
    "Anub'arak": "Anub'arak",
    "Valithria Dreamwalker": "Valithria",
}
UWU_MODES_ALL = ("10N", "10H", "25N", "25H")

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
        return {
            "__error__": f"⚠️ No se pudo acceder a la API de Warmane (summary). Código {resp_summary.status_code}"
        }
    try:
        summary = resp_summary.json()
    except Exception as e:
        return {"__error__": f"⚠️ Error al leer JSON de Warmane: {e}"}
    _cache_set(SUMMARY_CACHE, cache_key, summary)
    return summary


def _fetch_specs(nombre: str, server: str) -> list[dict]:
    specs = profile_scraper.get_specs(nombre, server)
    return specs


def _fetch_achievements(nombre: str, server: str):
    cache_key = (nombre, server)
    cached = _cache_get(ACHIEVEMENTS_CACHE, cache_key, ACHIEVEMENTS_TTL)
    if cached is not None:
        return cached

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    raid_categories = [15041, 15042, 14922, 14923]

    icc_sections = {
        "4531": 4,
        "4528": 3,
        "4529": 2,
        "4527": 2,
        "4532": 1,
        "4604": 4,
        "4605": 3,
        "4606": 2,
        "4607": 2,
        "4608": 1,
        "4628": 4,
        "4629": 3,
        "4630": 2,
        "4631": 2,
        "4636": 1,
        "4632": 4,
        "4633": 3,
        "4634": 2,
        "4635": 2,
        "4637": 1,
    }

    target_achievements = {
        "4817": ("halion_10n", "The Twilight Destroyer (10)"),
        "4818": ("halion_10h", "Heroic: The Twilight Destroyer (10)"),
        "4815": ("halion_25n", "The Twilight Destroyer (25)"),
        "4816": ("halion_25h", "Heroic: The Twilight Destroyer (25)"),
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
        url_achi_post = (
            f"https://armory.warmane.com/character/{nombre}/{server}/achievements"
        )
        data = {"category": category_id}
        resp_achi = SESSION.post(
            url_achi_post, headers=headers, data=data, timeout=HTTP_TIMEOUT
        )
        if resp_achi.status_code != 200:
            return []
        try:
            achi_json = resp_achi.json()
        except Exception:
            return []
        if "content" not in achi_json:
            return []
        soup = BeautifulSoup(achi_json["content"], "html.parser")
        all_achievements = soup.find_all("div", class_="achievement")
        completed_achievements = [
            ach for ach in all_achievements if "locked" not in ach.get("class", [])
        ]
        ids = []
        for ach_div in completed_achievements:
            ach_id_full = ach_div.get("id", "")
            if ach_id_full.startswith("ach"):
                ids.append(ach_id_full.replace("ach", ""))
        return ids

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch_category, raid_categories))

    for ids in results:
        for ach_id in ids:
            completed_ids.add(ach_id)
            if ach_id in icc_sections:
                bosses = icc_sections[ach_id]
                if ach_id in ["4531", "4528", "4529", "4527", "4532"]:
                    icc_10n_bosses += bosses
                elif ach_id in ["4604", "4605", "4606", "4607", "4608"]:
                    icc_25n_bosses += bosses
                elif ach_id in ["4628", "4629", "4630", "4631", "4636"]:
                    icc_10h_bosses += bosses
                elif ach_id in ["4632", "4633", "4634", "4635", "4637"]:
                    icc_25h_bosses += bosses

            if ach_id in target_achievements:
                key = target_achievements[ach_id][0]
                if key == "halion_10n":
                    halion_10n_achieved = True
                elif key == "halion_10h":
                    halion_10h_achieved = True
                elif key == "halion_25n":
                    halion_25n_achieved = True
                elif key == "halion_25h":
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


def _fetch_toc_achievements(nombre: str, server: str):
    cache_key = ("toc", nombre, server)
    cached = _cache_get(ACHIEVEMENTS_CACHE, cache_key, ACHIEVEMENTS_TTL)
    if cached is not None:
        return cached

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    url_achi_post = (
        f"https://armory.warmane.com/character/{nombre}/{server}/achievements"
    )

    target_titles = {
        "Call of the Crusade (10 player)": "toc_10n",
        "Call of the Crusade (25 player)": "toc_25n",
        "Call of the Grand Crusade (10 player)": "toc_10h",
        "Call of the Grand Crusade (25 player)": "toc_25h",
    }

    payload = {
        "toc_10n": False,
        "toc_10h": False,
        "toc_25n": False,
        "toc_25h": False,
    }

    for category_id in [15001, 15002]:
        resp_achi = SESSION.post(
            url_achi_post,
            headers=headers,
            data={"category": category_id},
            timeout=HTTP_TIMEOUT,
        )
        if resp_achi.status_code != 200:
            continue
        try:
            achi_json = resp_achi.json()
        except Exception:
            continue
        content = achi_json.get("content", "")
        if not content:
            continue

        soup = BeautifulSoup(content, "html.parser")
        for ach_div in soup.find_all("div", class_="achievement"):
            title_el = ach_div.find("div", class_="title")
            if not title_el:
                continue
            title = title_el.get_text(" ", strip=True)
            key = target_titles.get(title)
            if not key:
                continue
            achieved = "locked" not in ach_div.get("class", [])
            payload[key] = achieved

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


def _fetch_statistics(nombre: str, server: str, category_id: int):
    cache_key = (nombre, server, category_id)
    cached = _cache_get(STATS_CACHE, cache_key, STATS_TTL)
    if cached is not None:
        return cached

    url_stats = f"https://armory.warmane.com/character/{nombre}/{server}/statistics"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp = SESSION.post(
        url_stats, headers=headers, data={"category": category_id}, timeout=HTTP_TIMEOUT
    )
    if resp.status_code != 200:
        return []
    try:
        js = resp.json()
        content = js.get("content", "")
    except Exception:
        return []

    soup = BeautifulSoup(content, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if tds:
            rows.append(tds)

    _cache_set(STATS_CACHE, cache_key, rows)
    return rows


def _fetch_uwu_character(nombre: str, server: str, spec_i: int):
    cache_key = (nombre, server, spec_i)
    cached = _cache_get(UWU_CHARACTER_CACHE, cache_key, UWU_CHARACTER_TTL)
    if cached is not None:
        return cached

    url = f"{UWU_BASE}/character/{server}/{nombre}/{spec_i}"
    try:
        resp = SESSION.get(url, timeout=HTTP_TIMEOUT)
    except Exception as e:
        return {"__error__": f"uwu character error: {e}"}

    if resp.status_code != 200:
        return {"__error__": f"uwu character status: {resp.status_code}"}

    try:
        payload = resp.json()
    except Exception as e:
        return {"__error__": f"uwu character json error: {e}"}

    _cache_set(UWU_CHARACTER_CACHE, cache_key, payload)
    return payload


def _fetch_uwu_top(server: str, boss: str, mode: str, class_i: int, spec_i: int):
    cache_key = (server, boss, mode, class_i, spec_i)
    cached = _cache_get(UWU_TOP_CACHE, cache_key, UWU_TOP_TTL)
    if cached is not None:
        return cached

    payload = {
        "server": server,
        "boss": boss,
        "mode": mode,
        "class_i": class_i,
        "spec_i": spec_i,
        "sort_by": "head-date",
        "limit": 50000,
        "best_only": False,
        "externals": True,
    }
    try:
        resp = SESSION.post(
            f"{UWU_BASE}/top",
            json=payload,
            timeout=HTTP_TIMEOUT,
        )
    except Exception as e:
        return {"__error__": f"uwu top error: {e}"}

    if resp.status_code != 200:
        return {"__error__": f"uwu top status: {resp.status_code}"}

    try:
        rows = resp.json()
    except Exception as e:
        return {"__error__": f"uwu top json error: {e}"}

    _cache_set(UWU_TOP_CACHE, cache_key, rows)
    return rows


def _pick_uwu_spec(nombre: str, server: str):
    payloads = []
    for spec_i in (1, 2, 3):
        data = _fetch_uwu_character(nombre, server, spec_i)
        if isinstance(data, dict) and not data.get("__error__"):
            payloads.append((spec_i, data))

    if not payloads:
        return None, None

    def sort_key(item):
        spec_i, data = item
        bosses = data.get("bosses", {}) if isinstance(data, dict) else {}
        bosses_with_data = sum(1 for v in bosses.values() if isinstance(v, dict) and v)
        points = float(data.get("overall_points") or 0)
        return (bosses_with_data, points, -spec_i)

    best_spec_i, best_payload = max(payloads, key=sort_key)
    return best_spec_i, best_payload


def _uwu_row_dps(entry):
    try:
        duration = float(entry[1])
        useful_amount = float(entry[4])
    except Exception:
        return None
    if duration <= 0:
        return None
    return useful_amount / duration


def _build_uwu_dps_summary(nombre: str, server: str):
    bosses = {}
    for candidate_spec in (1, 2, 3):
        data = _fetch_uwu_character(nombre, server, candidate_spec)
        if isinstance(data, dict) and not data.get("__error__"):
            _bosses = data.get("bosses", {})
            if isinstance(_bosses, dict):
                bosses.update(_bosses)

    if not bosses:
        bosses = {boss_name: {} for boss_name in UWU_BOSS_SHORT}

    rows = []
    lower_name = nombre.lower()

    boss_names = sorted(bosses.keys(), key=lambda x: UWU_BOSS_SHORT.get(x, x))
    for boss_name in boss_names:
        boss_short = UWU_BOSS_SHORT.get(boss_name, boss_name[:10])

        for mode in UWU_MODES_ALL:
            top_rows = _fetch_uwu_top(server, boss_name, mode, -1, -1)
            if not isinstance(top_rows, list):
                rows.append(
                    {
                        "Boss": boss_short,
                        "Md": mode,
                        "R": "0",
                        "Max": "-",
                        "Avg": "-",
                        "_boss": boss_name,
                    }
                )
                continue

            player_rows = []
            for row in top_rows:
                if not isinstance(row, list) or len(row) < 6:
                    continue
                row_name = str(row[3]).lower() if len(row) > 3 else ""
                if row_name == lower_name:
                    player_rows.append(row)

            dps_values = [x for x in (_uwu_row_dps(x) for x in player_rows) if x is not None]
            if not dps_values:
                rows.append(
                    {
                        "Boss": boss_short,
                        "Md": mode,
                        "R": "0",
                        "Max": "-",
                        "Avg": "-",
                        "_boss": boss_name,
                    }
                )
                continue

            dps_avg = round(sum(dps_values) / len(dps_values), 2)
            dps_max = round(max(dps_values), 2)

            rows.append(
                {
                    "Boss": boss_short,
                    "Md": mode,
                    "R": str(len(dps_values)),
                    "Max": f"{dps_max:.2f}",
                    "Avg": f"{dps_avg:.2f}",
                    "_boss": boss_name,
                }
            )

    if not rows:
        return {"rows": [], "__error__": "No hay datos de uwu-logs para el personaje."}

    return {"rows": rows, "spec_i": "all"}


def _format_uwu_dps_table(rows):
    headers = ["Boss", "Md", "R", "Max", "Avg"]
    return _render_table(rows, headers)


def _extract_icc_boss_kills(stats_rows):
    boss_patterns = {
        "Marrowgar": ["Lord Marrowgar"],
        "Deathwhisper": ["Lady Deathwhisper"],
        "Gunship": ["Gunship Battle"],
        "Saurfang": ["Deathbringer"],
        "Festergut": ["Festergut"],
        "Rotface": ["Rotface"],
        "Putricide": ["Professor Putricide"],
        "Blood Prince": ["Blood Prince Council"],
        "Blood Queen": ["Blood Queen Lana'thel"],
        "Valithria": ["Valithria Dreamwalker"],
        "Sindragosa": ["Sindragosa"],
        "Lich King": ["Victories over the Lich King", "Lich King"],
    }

    def parse_value(val: str) -> int:
        if not val or val.strip() in {"- -", "--"}:
            return 0
        try:
            return int(val.replace(",", ""))
        except Exception:
            return 0

    icc_10 = {name: {"nm": 0, "hc": 0} for name in boss_patterns}
    icc_25 = {name: {"nm": 0, "hc": 0} for name in boss_patterns}

    for desc, val in stats_rows:
        if "Icecrown" not in desc:
            continue
        value = parse_value(val)
        if value <= 0:
            continue

        is_10 = "Icecrown 10 player" in desc
        is_25 = "Icecrown 25 player" in desc
        is_hc = "Heroic" in desc
        if not (is_10 or is_25):
            continue

        for boss_name, patterns in boss_patterns.items():
            if any(pat in desc for pat in patterns):
                if is_10:
                    key = "hc" if is_hc else "nm"
                    icc_10[boss_name][key] = max(icc_10[boss_name][key], value)
                if is_25:
                    key = "hc" if is_hc else "nm"
                    icc_25[boss_name][key] = max(icc_25[boss_name][key], value)
                break

    return icc_10, icc_25


def _extract_toc_boss_kills(stats_rows):
    boss_patterns = {
        "Beasts": ["Beasts of Northrend"],
        "Jaraxxus": ["Lord Jaraxxus"],
        "Faction Champs": ["Faction Champions"],
        "Val'kyr Twins": ["Val'kyr Twins", "Valkyr Twins"],
        "Anub'arak": ["Anub'arak", "Anubarak"],
    }

    def parse_value(val: str) -> int:
        if not val or val.strip() in {"- -", "--"}:
            return 0
        try:
            return int(val.replace(",", ""))
        except Exception:
            return 0

    toc_10 = {name: {"nm": 0, "hc": 0} for name in boss_patterns}
    toc_25 = {name: {"nm": 0, "hc": 0} for name in boss_patterns}

    for desc, val in stats_rows:
        if (
            "Trial of the Crusader" not in desc
            and "Trial of the Grand Crusader" not in desc
        ):
            continue
        if "Trial of the Champion" in desc:
            continue

        value = parse_value(val)
        if value <= 0:
            continue

        is_10 = "10 player" in desc
        is_25 = "25 player" in desc
        is_hc = "Trial of the Grand Crusader" in desc
        if not (is_10 or is_25):
            continue

        if (
            "Times completed the Trial of the Crusader" in desc
            or "Times completed the Trial of the Grand Crusader" in desc
        ):
            if is_10:
                key = "hc" if is_hc else "nm"
                toc_10["Anub'arak"][key] = max(toc_10["Anub'arak"][key], value)
            if is_25:
                key = "hc" if is_hc else "nm"
                toc_25["Anub'arak"][key] = max(toc_25["Anub'arak"][key], value)
            continue

        for boss_name, patterns in boss_patterns.items():
            if any(pat in desc for pat in patterns):
                if is_10:
                    key = "hc" if is_hc else "nm"
                    toc_10[boss_name][key] = max(toc_10[boss_name][key], value)
                if is_25:
                    key = "hc" if is_hc else "nm"
                    toc_25[boss_name][key] = max(toc_25[boss_name][key], value)
                break

    return toc_10, toc_25


def _cell(v):
    mark = "✅" if v > 0 else "❌"
    return f"{mark} {v}" if isinstance(v, int) else str(v)


def _calc_widths(rows, headers, header_labels=None):
    header_labels = header_labels or {}
    widths = {}

    def display_width(text):
        text = str(text)
        width = 0
        for ch in text:
            width += 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
        return width

    for key in headers:
        label = header_labels.get(key, key)
        max_cell = max((display_width(row[key]) for row in rows), default=0)
        widths[key] = max(display_width(label), max_cell)
    return widths


def _render_table(rows, headers, header_labels=None, widths=None):
    header_labels = header_labels or {}
    widths = widths or _calc_widths(rows, headers, header_labels)

    def display_width(text):
        text = str(text)
        width = 0
        for ch in text:
            width += 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
        return width

    def pad(text, width):
        text = str(text)
        if display_width(text) > width:
            return text
        return text + " " * (width - display_width(text))

    header_line = " | ".join(pad(header_labels.get(h, h), widths[h]) for h in headers)
    total_width = sum(widths[h] for h in headers) + (len(headers)) * 3
    sep_line = "-" * total_width
    body_lines = [" | ".join(pad(row[h], widths[h]) for h in headers) for row in rows]
    return "\n".join([header_line, sep_line] + body_lines)


def _format_boss_rows(bosses_10: dict, bosses_25: dict):
    rows = []
    for name in bosses_10.keys():
        c10 = bosses_10[name]
        c25 = bosses_25.get(name, {"nm": 0, "hc": 0})
        row = {"Boss": name}
        row["10N"] = _cell(c10["nm"])
        # Mostrar '?' en 10H, 25N y 25H para Marrowgar y Deathwhisper
        if name in ("Marrowgar", "Deathwhisper"):
            row["10H"] = "?"
            row["25N"] = "?"
            row["25H"] = "?"
        else:
            row["10H"] = _cell(c10["hc"])
            row["25N"] = _cell(c25["nm"])
            row["25H"] = _cell(c25["hc"])
        rows.append(row)

    def header_status(values):
        if all(values):
            return "✅"
        if any(values):
            return "⚠️"
        return "❌"

    col_status = {
        "10N": header_status([bosses_10[b]["nm"] > 0 for b in bosses_10]),
        "10H": header_status([bosses_10[b]["hc"] > 0 for b in bosses_10]),
        "25N": header_status([bosses_25[b]["nm"] > 0 for b in bosses_25]),
        "25H": header_status([bosses_25[b]["hc"] > 0 for b in bosses_25]),
    }

    headers = ["Boss", "10N", "10H", "25N", "25H"]
    header_labels = {
        "10N": f"{col_status['10N']}10N",
        "10H": f"{col_status['10H']}10H",
        "25N": f"{col_status['25N']}25N",
        "25H": f"{col_status['25H']}25H",
    }
    widths = _calc_widths(rows, headers, header_labels)
    table = _render_table(rows, headers, header_labels, widths)
    return table, widths


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


@bot.command(aliases=["p"])
async def personaje(ctx, nombre: str):
    """Muestra información del personaje desde la API de Warmane."""
    print(f"[LOG] Comando 'personaje' usado por {ctx.author} para personaje: {nombre}")
    # Normalizar nombre: primera letra mayúscula
    nombre = nombre.capitalize()
    try:
        loop = asyncio.get_running_loop()

        summary_task = loop.run_in_executor(
            EXECUTOR, _fetch_summary, nombre, "Lordaeron"
        )
        gear_task = loop.run_in_executor(
            EXECUTOR, _fetch_gear_data, nombre, "Lordaeron"
        )
        achi_task = loop.run_in_executor(
            EXECUTOR, _fetch_achievements, nombre, "Lordaeron"
        )
        stats_task = loop.run_in_executor(
            EXECUTOR, _fetch_statistics, nombre, "Lordaeron", 15062
        )

        summary, gear_data, achi_payload, stats_rows = await asyncio.gather(
            summary_task, gear_task, achi_task, stats_task
        )

        if isinstance(summary, dict) and summary.get("__error__"):
            await ctx.send(summary["__error__"])
            return

        if not isinstance(summary, dict):
            await ctx.send(
                "⚠️ Formato inesperado en 'summary' (no es JSON objeto). Revisa la respuesta en la consola."
            )
            return

        # Extraer datos básicos de forma segura
        nombre_char = summary.get("name", nombre)
        nivel = summary.get("level", "N/A")
        raza = summary.get("race", "N/A")
        clase = summary.get("class", "N/A")
        active_specs = []
        inactive_specs = []

        talents = _fetch_specs(nombre, "Lordaeron")
        if isinstance(talents, list) and len(talents) > 0:
            # unir varias especializaciones con comas si hay más de una, siempre poniendo la activa primera
            sorted_talents = sorted(talents, key=lambda t: not t.get("active", False))
            active_specs = [
                t.get("name", "N/A") for t in sorted_talents if t.get("active", False)
            ]
            inactive_specs = [
                t.get("name", "N/A")
                for t in sorted_talents
                if not t.get("active", False)
            ]
        else:
            active_specs = ["N/A"]
            inactive_specs = ["N/A"]

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
            missing_enchants, missing_gems = (
                profile_scraper.get_missing_enchants_gems_from_gear_data(gear_data)
            )
        except Exception:
            missing_enchants, missing_gems = [], []

        guild_obj = summary.get("guild")
        guild = guild_obj if isinstance(guild_obj, str) else "Sin guild"

        halion_10n_achieved = achi_payload["halion_10n_achieved"]
        halion_10h_achieved = achi_payload["halion_10h_achieved"]
        halion_25n_achieved = achi_payload["halion_25n_achieved"]
        halion_25h_achieved = achi_payload["halion_25h_achieved"]

        icc_10, icc_25 = _extract_icc_boss_kills(stats_rows)
        # Construir embed con los datos solicitados
        guild_display = f"<{guild}>" if guild and guild != "Sin guild" else "Sin guild"
        spec_display = " - ".join(
            f"**{spec}**" if spec in active_specs else spec
            for spec in active_specs + inactive_specs
        )

        embed = discord.Embed(
            title=nombre_char,
            color=0x2B2D31,
        )
        embed.add_field(name="GearScore", value=str(gs), inline=True)
        embed.add_field(
            name="Level | Race | Class",
            value=f"Level {nivel} {raza} {clase}",
            inline=True,
        )
        embed.add_field(name="Spec", value=spec_display, inline=True)
        embed.add_field(name="Guild", value=guild_display, inline=True)
        embed.add_field(
            name="Armory",
            value=(
                f"https://armory.warmane.com/character/{nombre_char}/Lordaeron/profile"
            ),
            inline=False,
        )

        embed.add_field(
            name="Uwulogs",
            value=(
                f"https://uwu-logs.xyz/character?name={nombre_char}&server=Lordaeron"
            ),
            inline=False,
        )

        icc_table, icc_widths = _format_boss_rows(icc_10, icc_25)
        rs_rows = [
            {
                "Boss": "Halion",
                "10N": "✅" if halion_10n_achieved else "❌",
                "10H": "✅" if halion_10h_achieved else "❌",
                "25N": "✅" if halion_25n_achieved else "❌",
                "25H": "✅" if halion_25h_achieved else "❌",
            }
        ]

        def rs_header_status(done: bool) -> str:
            return "✅" if done else "❌"

        rs_table = _render_table(
            rs_rows,
            ["Boss", "10N", "10H", "25N", "25H"],
            {
                "10N": f"{rs_header_status(halion_10n_achieved)}10N",
                "10H": f"{rs_header_status(halion_10h_achieved)}10H",
                "25N": f"{rs_header_status(halion_25n_achieved)}25N",
                "25H": f"{rs_header_status(halion_25h_achieved)}25H",
            },
            icc_widths,
        )

        embed.add_field(
            name="Icecrown Citadel",
            value=("```\n" f"{icc_table}\n" "```\n"),
            inline=False,
        )

        embed.add_field(
            name="Ruby Sanctum",
            value=("```\n" + rs_table + "```"),
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
                value=("```\n" + "\n".join(missing_lines) + "\n```"),
                inline=False,
            )

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error al obtener datos: {e}")


@bot.command()
async def pdps(ctx, nombre: str):
    """Muestra DPS max/avg por boss desde UwU Logs."""
    print(f"[LOG] Comando 'pdps' usado por {ctx.author} para personaje: {nombre}")
    nombre = nombre.capitalize()
    try:
        loop = asyncio.get_running_loop()
        uwu_dps_summary = await loop.run_in_executor(
            EXECUTOR, _build_uwu_dps_summary, nombre, UWU_SERVER
        )

        if not isinstance(uwu_dps_summary, dict):
            await ctx.send("⚠️ No se pudo leer respuesta de UwU Logs.")
            return

        uwu_rows = uwu_dps_summary.get("rows", [])
        if not uwu_rows:
            await ctx.send(f"⚠️ No hay datos DPS en UwU Logs para {nombre}.")
            return

        uwu_rows = sorted(uwu_rows, key=lambda x: x.get("_boss", x.get("Boss", "")))
        for row in uwu_rows:
            row.pop("_boss", None)

        uwu_table = _format_uwu_dps_table(uwu_rows)
        table_block = f"```\n{uwu_table}\n```"
        if len(table_block) > 3900:
            table_block = f"```\n{uwu_table[:3880]}\n...\n```"

        embed = discord.Embed(
            title=f"{nombre} - Uwulogs DPS (all bosses/modes)",
            description=table_block,
            color=0x2B2D31,
        )
        embed.add_field(
            name="Uwulogs",
            value=f"https://uwu-logs.xyz/character?name={nombre}&server={UWU_SERVER}",
            inline=False,
        )
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error al obtener DPS: {e}")


@bot.command()
async def ptoc(ctx, nombre: str):
    """Muestra logros de Trial of the Crusader (TOC) con formato de tabla."""
    print(f"[LOG] Comando 'ptoc' usado por {ctx.author} para personaje: {nombre}")
    nombre = nombre.capitalize()
    try:
        loop = asyncio.get_running_loop()
        toc_payload = await loop.run_in_executor(
            EXECUTOR, _fetch_toc_achievements, nombre, "Lordaeron"
        )

        def toc_status(done: bool) -> str:
            return "✅" if done else "❌"

        toc_rows = [
            {
                "Boss": "Trial of the Crusader",
                "10N": toc_status(toc_payload["toc_10n"]),
                "10H": toc_status(toc_payload["toc_10h"]),
                "25N": toc_status(toc_payload["toc_25n"]),
                "25H": toc_status(toc_payload["toc_25h"]),
            }
        ]

        toc_table = _render_table(
            toc_rows,
            ["Boss", "10N", "10H", "25N", "25H"],
            {
                "10N": f"{toc_status(toc_payload['toc_10n'])}10N",
                "10H": f"{toc_status(toc_payload['toc_10h'])}10H",
                "25N": f"{toc_status(toc_payload['toc_25n'])}25N",
                "25H": f"{toc_status(toc_payload['toc_25h'])}25H",
            },
        )

        embed = discord.Embed(
            title=f"{nombre} - Trial of the Crusader",
            color=0x2B2D31,
        )
        embed.add_field(
            name="Trial of the Crusader",
            value=("```\n" f"{toc_table}\n" "```"),
            inline=False,
        )
        embed.add_field(
            name="Armory",
            value=(
                f"https://armory.warmane.com/character/{nombre}/Lordaeron/achievements"
            ),
            inline=False,
        )

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error al obtener datos: {e}")


bot.run(TOKEN)
