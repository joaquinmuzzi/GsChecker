import requests
from concurrent.futures import ThreadPoolExecutor
from discord.ext import commands

from src.functions.rate_limit import CircuitBreaker, TokenBucket

PREFIX = commands.when_mentioned

HTTP_TIMEOUT = 8
UWU_BASE = "https://uwu-logs.xyz"
UWU_SERVER = "Lordaeron"
DOCS_NOTAS_URL = "https://joaquinmuzzi.github.io/GsChecker/#notas"
LOADING_FRAMES = ("⌛", "⏳")

# ---------- Caches ----------
SUMMARY_CACHE: dict = {}
ACHIEVEMENTS_CACHE: dict = {}
GEAR_CACHE: dict = {}
STATS_CACHE: dict = {}
GUILD_RANK_CACHE: dict = {}
UWU_CHARACTER_CACHE: dict = {}
UWU_TOP_CACHE: dict = {}
UWU_PDPS_SUMMARY_CACHE: dict = {}
UWU_ICC_KILLS_CACHE: dict = {}
UWU_PLAYER_ROWS_CACHE: dict = {}
UWU_SPEC_PLAYERS_CACHE: dict = {}
UWU_TOP_POINTS_CACHE: dict = {}
UWU_LOGS_CACHE: dict = {}

# ---------- TTLs (segundos) ----------
SUMMARY_TTL = 120
ACHIEVEMENTS_TTL = 300
GEAR_TTL = 120
STATS_TTL = 300
GUILD_RANK_TTL = 300
UWU_CHARACTER_TTL = 120
UWU_TOP_TTL = 180
UWU_PDPS_SUMMARY_TTL = 180
UWU_ICC_KILLS_TTL = 180
UWU_PLAYER_ROWS_TTL = 180
# Lista de jugadores con kill por spec/boss/modo (kills de ICC en /p y el
# cron): cambia poco y es compartida entre personajes.
UWU_SPEC_PLAYERS_TTL = 3600
# Cantidad de jugadores rankeados por spec (/top_points), para "#37 de 3174".
UWU_TOP_POINTS_TTL = 3600
# /logs: últimos reportes del personaje (con los bosses de cada uno).
UWU_LOGS_TTL = 600
# 25h: cubre el ciclo diario de tools/preload_personaje_cache.py con margen,
# así el cache que deja el cron sigue vivo hasta que corre de nuevo al día siguiente.
COMMAND_PERSONAJE_TTL = 90000
COMMAND_DPS_TTL = 180
CHARACTER_SPEC_GS_TTL = 2592000

# ---------- UwU Boss data ----------
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

# Nombres de spec de uwu-logs por class_i (c_player_classes.CLASSES).
UWU_SPEC_NAMES: dict[int, tuple[str, str, str]] = {
    0: ("Blood", "Frost", "Unholy"),
    1: ("Balance", "Feral Combat", "Restoration"),
    2: ("Beast Mastery", "Marksmanship", "Survival"),
    3: ("Arcane", "Fire", "Frost"),
    4: ("Holy", "Protection", "Retribution"),
    5: ("Discipline", "Holy", "Shadow"),
    6: ("Assassination", "Combat", "Subtlety"),
    7: ("Elemental", "Enhancement", "Restoration"),
    8: ("Affliction", "Demonology", "Destruction"),
    9: ("Arms", "Fury", "Protection"),
}

# class_i de uwu-logs por clase del armory (orden de c_player_classes.CLASSES).
UWU_CLASS_INDEX = {
    "Death Knight": 0,
    "Druid": 1,
    "Hunter": 2,
    "Mage": 3,
    "Paladin": 4,
    "Priest": 5,
    "Rogue": 6,
    "Shaman": 7,
    "Warlock": 8,
    "Warrior": 9,
}

# /top de uwu-logs no filtra por jugador: /dps pide hasta 10000 filas de la
# spec (ordenadas por DPS útil) y busca las del personaje. Con 1000 los
# tanks/healers quedaban afuera y salían con 0 raids.
UWU_TOP_PLAYER_LIMIT = 10000
UWU_TOP_PLAYER_TIMEOUT = 15
# Con 4 consultas en paralelo uwu-logs devolvía 429 en ~40 % de las
# consultas (logs de prod, 2026-09-28): 2 a la vez y reintento con espera.
UWU_TOP_WORKERS = 2
UWU_TOP_MAX_ATTEMPTS = 3

# /logs: cuántos reportes se muestran y con qué peleas se arma la etiqueta
# (nombres de fight de uwu-logs, c_bosses.py).
UWU_LOGS_LIMIT = 10
UWU_LOGS_ICC_FIGHTS = (
    "Lord Marrowgar",
    "Lady Deathwhisper",
    "Gunship",
    "Deathbringer Saurfang",
    "Festergut",
    "Rotface",
    "Professor Putricide",
    "Blood Prince Council",
    "Blood-Queen Lana'thel",
    "Valithria Dreamwalker",
    "Sindragosa",
    "The Lich King",
)
UWU_LOGS_OTHER_FIGHTS = {"Halion": "Halion", "Toravon the Ice Watcher": "Toravon"}

UWU_PDPS_BOSS_ORDER = [
    "Lord Marrowgar",
    "Deathbringer Saurfang",
    "Festergut",
    "Rotface",
    "Professor Putricide",
    "The Lich King",
]

# ---------- Spec keywords ----------
UWU_SPEC_KEYWORDS: dict[str, list[int]] = {
    # Death Knight
    "bdk": [1],
    "blood": [1],
    "fdk": [2],
    "udk": [3],
    "unholy": [3],
    # Warrior
    "arms": [1],
    "fury": [2],
    "prot": [3],
    # Paladin
    "holy": [1],
    "protection": [2],
    "ret": [3],
    "retri": [3],
    "retribution": [3],
    # Hunter
    "bm": [1],
    "beastmastery": [1],
    "beast": [1],
    "mm": [2],
    "marks": [2],
    "marksmanship": [2],
    "sv": [3],
    "survival": [3],
    # Rogue
    "assassination": [1],
    "mut": [1],
    "mutilate": [1],
    "combat": [2],
    "sub": [3],
    "subtlety": [3],
    # Priest
    "disc": [1],
    "discipline": [1],
    "spriest": [3],
    "shadow": [3],
    # Shaman
    "ele": [1],
    "elemental": [1],
    "enh": [2],
    "enhancement": [2],
    "resto": [3],
    "restoration": [3],
    # Mage
    "arcane": [1],
    "fire": [2],
    # "frost" abarca DK spec_i=2 y Mage spec_i=3
    "frost": [2, 3],
    # Warlock
    "affli": [1],
    "affliction": [1],
    "demo": [2],
    "demonology": [2],
    "destro": [3],
    "destruction": [3],
    "dest": [3],
    # Druid
    "boomkin": [1],
    "balance": [1],
    "feral": [2],
    "rdruid": [3],
}

# Specs de healer/tank de uwu-logs como (class_i, spec_i). Blood DK y Feral
# quedan como DPS porque uwu-logs no separa tank de DPS en esas specs.
UWU_NON_DPS_SPECS = {
    (1, 3),  # Druid Restoration
    (4, 1),  # Paladin Holy
    (4, 2),  # Paladin Protection
    (5, 1),  # Priest Discipline
    (5, 2),  # Priest Holy
    (7, 3),  # Shaman Restoration
    (9, 3),  # Warrior Protection
}

# Keywords cuya spec depende de la clase. Orden de clases de uwu-logs
# (c_player_classes.CLASSES): DK 0, Druid 1, Hunter 2, Mage 3, Paladin 4,
# Priest 5, Rogue 6, Shaman 7, Warlock 8, Warrior 9.
UWU_SPEC_KEYWORDS_BY_CLASS: dict[str, dict[int, int]] = {
    "frost": {0: 2, 3: 3},
    "holy": {4: 1, 5: 2},
    "prot": {4: 2, 9: 3},
    "protection": {4: 2, 9: 3},
}

# ---------- Shared HTTP session / executor ----------
SESSION = requests.Session()
EXECUTOR = ThreadPoolExecutor(max_workers=6)

# ---------- Armory throttle + circuit breaker ----------
# Medición en vivo (Cloudflare del armory): ~5-6 requests / 10s por IP antes de 429.
# Con rate=0.5 (1 req / 2s) y burst=3 nunca deberíamos disparar el rate limit.
ARMORY_LIMITER = TokenBucket(rate=0.5, capacity=3)

# El circuit se abre 60s tras 3× 429/5xx en 30s, o 90s inmediatamente si
# detectamos "error code: 1015" en el body (IP baneada por Cloudflare).
ARMORY_CIRCUIT = CircuitBreaker(
    failure_threshold=3,
    open_duration_s=60.0,
    fatal_open_duration_s=90.0,
    failure_window_s=30.0,
)

# ---------- Backoff cuando el armory devuelve 429 / 5xx ----------
# Antes: 3-5s / 3 intentos. Medido en vivo: cuando llega 1015, el desbloqueo
# tarda ~30-60s, así que reintentar rápido solo prolonga el ban.
ARMORY_BACKOFF_MIN = 8.0
ARMORY_BACKOFF_MAX = 20.0
ARMORY_MAX_ATTEMPTS = 4
