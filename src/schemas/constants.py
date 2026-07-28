import requests
from concurrent.futures import ThreadPoolExecutor
from discord.ext import commands

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
COMMAND_PERSONAJE_TTL = 180
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

# ---------- Shared HTTP session / executor ----------
SESSION = requests.Session()
EXECUTOR = ThreadPoolExecutor(max_workers=6)
