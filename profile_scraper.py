import json
import os
import re
from functools import lru_cache
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "GsChecker/1.0"}
SESSION = requests.Session()
ITEM_SESSION = requests.Session()

WOW_CLASSIC_CLASSES = {
    "Balance",
    "Feral Combat",
    "Restoration",
    "Arcane",
    "Fire",
    "Frost",
    "Holy",
    "Protection",
    "Retribution",
    "Beast Mastery",
    "Marksmanship",
    "Survival",
    "Assassination",
    "Combat",
    "Subtlety",
    "Arms",
    "Fury",
    "Discipline",
    "Shadow",
    "Elemental",
    "Enhancement",
    "Affliction",
    "Demonology",
    "Destruction",
    "Blood",
    "Unholy",
}

SLOT_FALLBACK_ORDER = [
    "Head",
    "Neck",
    "Shoulder",
    "Back",
    "Chest",
    "Shirt",
    "Tabard",
    "Wrist",
    "Hands",
    "Waist",
    "Legs",
    "Feet",
    "Finger 1",
    "Finger 2",
    "Trinket 1",
    "Trinket 2",
    "Main Hand",
    "Off Hand",
    "Ranged",
]

ENCHANTABLE_SLOTS = {
    "Head",
    "Shoulder",
    "Chest",
    "Legs",
    "Hands",
    "Feet",
    "Wrist",
    "Back",
    "Main Hand",
    "One-Hand",
    "Two-Hand",
}

ITEM_HEADERS = {"User-Agent": "GsChecker item-sockets/1.0"}
CACHE_PATH = os.path.join(
    os.path.dirname(__file__), "static", "item_sockets_cache.json"
)
SLOT_CACHE_PATH = os.path.join(
    os.path.dirname(__file__), "static", "item_slot_cache.json"
)
GEM_DATA_PATH = os.path.join(os.path.dirname(__file__), "static", "gem_data.json")
SOCKET_CACHE_ONLY = False
_SOCKET_CACHE = None
_SLOT_CACHE = None
_GEM_DATA: dict | None = None
# reverse map: enchant_id (str) → {"item_id": str, "name": str, "effect": str, "meta": bool}
_GEM_BY_ENCHANT: dict | None = None

# ── Meta gem IDs (go in a meta socket, skip from quality checks) ─────────────
META_GEM_IDS: frozenset[str] = frozenset(
    {
        "25893",
        "25894",
        "25895",
        "25896",
        "25898",
        "25901",
        "28556",
        "28557",
        "32409",
        "32410",
        "32640",
        "32641",
        "35501",
        "35503",
        "41285",
        "41307",
        "41333",
        "41335",
        "41339",
        "41375",
        "41376",
        "41377",
        "41378",
        "41379",
        "41380",
        "41381",
        "41382",
        "41385",
        "41389",
        "41395",
        "41396",
        "41397",
        "41398",
        "41400",
        "41401",
        "44076",
        "44078",
        "44081",
        "44082",
        "44084",
        "44087",
        "44088",
        "44089",
    }
)

# ── Prismatic gems — always acceptable regardless of spec ────────────────────
_ALWAYS_OK_GEMS: frozenset[str] = frozenset({"49110", "42702"})

# ── Optimal gem sets per role (ICC / WoTLK phase) ────────────────────────────
_STR_DPS_GEMS: frozenset[str] = frozenset(
    {
        "40111",
        "42142",  # Bold Cardinal Ruby / Dragon's Eye (+20/+34 STR)
        "40117",
        "42153",  # Fractured Cardinal Ruby / Dragon's Eye (+20/+34 ArP)
        "40114",
        "36766",  # Bright Cardinal Ruby / Dragon's Eye (+40/+68 AP)
        "40129",  # Sovereign Dreadstone (+10 STR +15 Stam)
        "40140",  # Puissant Dreadstone (+10 ArP +15 Stam)
        "40142",  # Inscribed Ametrine (+10 STR +10 Crit)
        "40143",  # Etched Ametrine (+10 STR +10 Hit)
        "40146",  # Fierce Ametrine (+10 STR +10 Haste)
        "40118",
        "42154",  # Precise Cardinal Ruby / Dragon's Eye (+20/+34 Expertise)
        "40125",
        "42156",  # Rigid King's Amber / Dragon's Eye (+20/+34 Hit)
    }
)

_AGI_DPS_GEMS: frozenset[str] = frozenset(
    {
        "40112",
        "42143",  # Delicate Cardinal Ruby / Dragon's Eye (+20/+34 Agi)
        "40117",
        "42153",  # Fractured (+20/+34 ArP) — ArP builds
        "40114",
        "36766",  # Bright (+40/+68 AP)
        "40130",  # Shifting Dreadstone (+10 Agi +15 Stam)
        "40147",  # Deadly Ametrine (+10 Agi +10 Crit)
        "40148",  # Glinting Ametrine (+10 Agi +10 Hit)
        "40150",  # Deft Ametrine (+10 Agi +10 Haste)
        "40118",
        "42154",  # Precise (+20/+34 Expertise)
        "40125",
        "42156",  # Rigid (+20/+34 Hit)
    }
)

_SP_DPS_GEMS: frozenset[str] = frozenset(
    {
        "40113",
        "42144",  # Runed Cardinal Ruby / Dragon's Eye (+23/+39 SP)
        "40152",  # Potent Ametrine (+12 SP +10 Crit)
        "40153",  # Veiled Ametrine (+12 SP +10 Hit)
        "40155",  # Reckless Ametrine (+12 SP +10 Haste)
        "40151",  # Luminous Ametrine (+12 SP +10 Int)
        "40132",  # Glowing Dreadstone (+12 SP +15 Stam)
        "40128",  # Quick King's Amber (+20 Haste)
        "40123",
        "42148",  # Brilliant King's Amber / Dragon's Eye (+20/+34 Int)
        "40125",
        "42156",  # Rigid (+20/+34 Hit)
    }
)

_INT_HEAL_GEMS: frozenset[str] = frozenset(
    {
        "40123",
        "42148",  # Brilliant King's Amber / Dragon's Eye (+20/+34 Int)
        "40113",
        "42144",  # Runed Cardinal Ruby / Dragon's Eye (+23/+39 SP)
        "40151",  # Luminous Ametrine (+12 SP +10 Int)
        "40155",  # Reckless Ametrine (+12 SP +10 Haste)
        "40152",  # Potent Ametrine (+12 SP +10 Crit)
        "40164",  # Timeless Eye of Zul (+10 Int +15 Stam)
        "40175",  # Dazzling Eye of Zul (+10 Int +5 mp5)
        "40132",  # Glowing Dreadstone (+12 SP +15 Stam)
        "40133",  # Purified Dreadstone (+12 SP +10 Spirit)
        "40134",  # Royal Dreadstone (+12 Int +5 mp5)
        "40128",  # Quick King's Amber (+20 Haste)

    }
)

_TANK_GEMS: frozenset[str] = frozenset(
    {
        "40119",
        "36767",  # Solid Majestic Zircon / Dragon's Eye (+30/+51 Stam)
        "40129",  # Sovereign Dreadstone (+10 STR +15 Stam)
        "40130",  # Shifting Dreadstone (+10 Agi +15 Stam)
        "40138",  # Regal Dreadstone (+10 Dodge +15 Stam)
        "40139",  # Defender's Dreadstone (+10 Parry +15 Stam)
        "40167",  # Enduring Eye of Zul (+10 Def +15 Stam)
        "40126",
        "42157",  # Thick King's Amber / Dragon's Eye (+20/+34 Defense)
        "40115",
        "42151",  # Subtle Cardinal Ruby / Dragon's Eye (+20/+34 Dodge)
        "40116",
        "42152",  # Flashing Cardinal Ruby / Dragon's Eye (+20/+34 Parry)
        "40111",
        "42142",  # Bold (+20/+34 STR) — threat
        "40160",  # Stalwart Ametrine (+10 Dodge +10 Defense)
        "40161",  # Glimmering Ametrine (+10 Parry +10 Defense)
        "40118",
        "42154",  # Precise (+20/+34 Expertise) — threat capping
        "40125",
        "42156",  # Rigid (+20/+34 Hit) — threat capping
    }
)

# ── (class_lower, spec_lower) → acceptable gem set ───────────────────────────
OPTIMAL_GEMS_BY_SPEC: dict[tuple[str, str], frozenset[str]] = {
    # STR melee DPS
    ("paladin", "retribution"): _STR_DPS_GEMS,
    ("warrior", "arms"): _STR_DPS_GEMS,
    ("warrior", "fury"): _STR_DPS_GEMS,
    ("death knight", "unholy"): _STR_DPS_GEMS,
    ("death knight", "frost"): _STR_DPS_GEMS,
    ("druid", "feral combat"): _STR_DPS_GEMS,
    # AGI melee DPS
    ("hunter", "beast mastery"): _AGI_DPS_GEMS,
    ("hunter", "marksmanship"): _AGI_DPS_GEMS,
    ("hunter", "survival"): _AGI_DPS_GEMS,
    ("rogue", "assassination"): _AGI_DPS_GEMS,
    ("rogue", "combat"): _AGI_DPS_GEMS,
    ("rogue", "subtlety"): _AGI_DPS_GEMS,
    ("shaman", "enhancement"): _AGI_DPS_GEMS,
    # SP caster DPS
    ("mage", "arcane"): _SP_DPS_GEMS,
    ("mage", "fire"): _SP_DPS_GEMS,
    ("mage", "frost"): _SP_DPS_GEMS,
    ("warlock", "affliction"): _SP_DPS_GEMS,
    ("warlock", "demonology"): _SP_DPS_GEMS,
    ("warlock", "destruction"): _SP_DPS_GEMS,
    ("priest", "shadow"): _SP_DPS_GEMS,
    ("druid", "balance"): _SP_DPS_GEMS,
    ("shaman", "elemental"): _SP_DPS_GEMS,
    # INT/SP healers
    ("paladin", "holy"): _INT_HEAL_GEMS,
    ("priest", "holy"): _INT_HEAL_GEMS,
    ("priest", "discipline"): _INT_HEAL_GEMS,
    ("druid", "restoration"): _INT_HEAL_GEMS,
    ("shaman", "restoration"): _INT_HEAL_GEMS,
    # Tanks
    ("warrior", "protection"): _TANK_GEMS,
    ("paladin", "protection"): _TANK_GEMS,
    ("death knight", "blood"): _TANK_GEMS,
}


def _load_socket_cache() -> dict:
    global _SOCKET_CACHE
    if _SOCKET_CACHE is not None:
        return _SOCKET_CACHE
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            _SOCKET_CACHE = json.load(f)
    except Exception:
        _SOCKET_CACHE = {}
    return _SOCKET_CACHE


def _load_gem_data() -> dict:
    global _GEM_DATA
    if _GEM_DATA is not None:
        return _GEM_DATA
    try:
        with open(GEM_DATA_PATH, "r", encoding="utf-8") as f:
            _GEM_DATA = json.load(f)
    except Exception:
        _GEM_DATA = {}
    return _GEM_DATA


def _load_gem_by_enchant() -> dict:
    """Build and cache a reverse lookup: enchant_id → gem info dict."""
    global _GEM_BY_ENCHANT
    if _GEM_BY_ENCHANT is not None:
        return _GEM_BY_ENCHANT
    gem_data = _load_gem_data()
    _GEM_BY_ENCHANT = {}
    for item_id, info in gem_data.items():
        if not isinstance(info, dict):
            continue
        eid = str(info.get("enchant_id") or "")
        if not eid:
            continue
        _GEM_BY_ENCHANT[eid] = {
            "item_id": item_id,
            "name": info.get("name", item_id),
            "effect": info.get("effect", ""),
            "meta": bool(info.get("colors", {}).get("meta", False)),
        }
    return _GEM_BY_ENCHANT


def _save_socket_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass


def get_specs(char_name: str, server: str) -> list[dict]:
    try:
        profile_url = (
            f"https://armory.warmane.com/character/{char_name}/{server}/profile"
        )
        profile_resp = SESSION.get(profile_url, headers=HEADERS, timeout=8)
        if profile_resp.status_code == 200:
            profile_soup = BeautifulSoup(profile_resp.text, "html.parser")
            profile_specs = []
            for text_node in profile_soup.select(
                "div.specialization div.stub div.text"
            ):
                text_copy = BeautifulSoup(str(text_node), "html.parser")
                for value_span in text_copy.select("span.value"):
                    value_span.extract()
                spec_name = " ".join(text_copy.get_text(" ", strip=True).split())
                if spec_name and spec_name in WOW_CLASSIC_CLASSES:
                    profile_specs.append(spec_name)
            if len(profile_specs) == 1:
                return [{"name": profile_specs[0], "active": True}]

        url = f"https://armory.warmane.com/character/{char_name}/{server}/talents"
        resp = SESSION.get(url, headers=HEADERS, timeout=8)
        if resp.status_code != 200:
            resp = None
        specs = []
        if resp is not None:
            soup = BeautifulSoup(resp.text, "html.parser")
            talents = soup.find_all("td", attrs={"data-spec": True})
            for td in talents:
                specs.append(
                    {
                        "name": td.get_text(strip=True),
                        "active": "selected" in td.get("class", []),
                    }
                )
            if specs:
                return specs

        api_url = (
            f"https://armory.warmane.com/api/character/{char_name}/{server}/talents"
        )
        api_resp = SESSION.get(api_url, headers=HEADERS, timeout=8)
        if api_resp.status_code != 200:
            return []

        payload = api_resp.json()
        talents = payload.get("talents") if isinstance(payload, dict) else None
        if not isinstance(talents, list):
            return []

        specs = []
        for idx, talent in enumerate(talents):
            if not isinstance(talent, dict):
                continue
            name = str(talent.get("tree") or "").strip()
            if not name or name not in WOW_CLASSIC_CLASSES:
                continue
            specs.append(
                {
                    "name": name,
                    "active": idx == 0,
                }
            )
        return specs
    except Exception:
        pass
    return []


def _load_slot_cache() -> dict:
    global _SLOT_CACHE
    if _SLOT_CACHE is not None:
        return _SLOT_CACHE
    try:
        with open(SLOT_CACHE_PATH, "r", encoding="utf-8") as f:
            _SLOT_CACHE = json.load(f)
    except Exception:
        _SLOT_CACHE = {}
    return _SLOT_CACHE


def _save_slot_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SLOT_CACHE_PATH), exist_ok=True)
        with open(SLOT_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _get_raw_stats(page_text: str) -> str:
    try:
        raw_stats = page_text[page_text.index("tooltip_enus") :]
        return raw_stats[: raw_stats.index("_[")]
    except ValueError:
        return page_text


def _normalize_slot_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().replace("-", " "))


@lru_cache(maxsize=4096)
def get_item_equip_slot(item_id: str) -> str:
    try:
        cache = _load_slot_cache()
        cached = cache.get(item_id)
        if isinstance(cached, str):
            return cached
        if SOCKET_CACHE_ONLY:
            return ""
        item_url = f"https://wotlk.evowow.com/?item={item_id}"
        resp = ITEM_SESSION.get(item_url, headers=ITEM_HEADERS, timeout=6)
        if resp.status_code != 200:
            return ""
        raw_stats = _get_raw_stats(resp.text)
        slot_texts = re.findall(r"td>([^<]+)<", raw_stats)
        candidates = {
            "one hand",
            "two hand",
            "main hand",
            "off hand",
            "held in off hand",
        }
        equip_slot = ""
        for text in slot_texts:
            norm = _normalize_slot_text(text)
            if norm in candidates:
                equip_slot = norm
                break
        cache[item_id] = equip_slot
        _save_slot_cache(cache)
        return equip_slot
    except Exception:
        return ""


def is_enchantable_slot(slot: str, item_id: str) -> bool:
    if slot != "Off Hand":
        return slot in ENCHANTABLE_SLOTS

    equip_slot = get_item_equip_slot(str(item_id))
    weapon_slots = {"one hand", "two hand", "main hand", "off hand"}
    if equip_slot in weapon_slots:
        return True
    if equip_slot == "held in off hand":
        return False
    return False


@lru_cache(maxsize=4096)
def get_item_socket_count(item_id: str) -> int:
    try:
        cache = _load_socket_cache()
        cached = cache.get(item_id)
        if isinstance(cached, int):
            return cached
        if SOCKET_CACHE_ONLY:
            return 0
        item_url = f"https://wotlk.evowow.com/?item={item_id}"
        resp = ITEM_SESSION.get(item_url, headers=ITEM_HEADERS, timeout=6)
        if resp.status_code != 200:
            return 0
        raw_stats = _get_raw_stats(resp.text)
        sockets = re.findall("socket-([a-z]{3,9})", raw_stats)
        count = len(sockets)
        cache[item_id] = count
        _save_socket_cache(cache)
        return count
    except Exception:
        return 0


def _extract_slot_name(slot, index: int) -> str:
    for key in ("data-slot-name", "data-slot", "data-item-slot", "data-slotname"):
        val = slot.get(key)
        if isinstance(val, list):
            val = val[0] if val else ""
        if val:
            if str(val).isdigit():
                break
            return str(val).strip().replace("_", " ").replace("-", " ").title()

    classes = slot.get("class", []) or []
    for cls in classes:
        if cls.startswith("slot-"):
            return cls.replace("slot-", "").replace("-", " ").title()

    if index < len(SLOT_FALLBACK_ORDER):
        return SLOT_FALLBACK_ORDER[index]
    return f"Slot {index + 1}"


def parse_slot(slot):
    if not slot.get("rel"):
        return {}
    item_properties_list = slot["rel"][0].split("&")
    item_properties = dict(property.split("=") for property in item_properties_list)
    item_properties["gems"] = item_properties.get("gems", "0:0:0").split(":")
    return item_properties


def get_gear_data(char_name: str, server: str = "Lordaeron"):
    url = f"http://armory.warmane.com/character/{char_name}/{server}"
    resp = SESSION.get(url, headers=HEADERS, timeout=8)
    if resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    try:
        equipment = soup.find(class_="item-model").find_all("a")
    except Exception:
        return []
    gear_data = []
    for idx, slot in enumerate(equipment):
        item_properties = parse_slot(slot)
        item_properties["slot"] = _extract_slot_name(slot, idx)
        gear_data.append(item_properties)
    return gear_data


def get_gear_ids_from_gear_data(gear_data):
    gear_ids = [item.get("item") for item in gear_data]
    return [gid if gid and str(gid).isdigit() else "" for gid in gear_ids]


def get_gear_ids(char_name: str, server: str = "Lordaeron"):
    gear_data = get_gear_data(char_name, server)
    return get_gear_ids_from_gear_data(gear_data)


def get_missing_enchants_gems_from_gear_data(gear_data):
    missing_enchants = []
    missing_gems = []

    for item in gear_data:
        slot = item.get("slot", "Unknown")
        item_id = item.get("item")
        if not item_id:
            continue

        ench_id = item.get("ench")
        if is_enchantable_slot(slot, item_id) and (not ench_id or str(ench_id) == "0"):
            missing_enchants.append(slot)

        if "gems" in item:
            gems = item.get("gems") or []
            filled_gems = sum(1 for g in gems if g and str(g) != "0")
            has_zeros = any(not g or str(g) == "0" for g in gems)
            socket_count = get_item_socket_count(str(item_id))
            if socket_count > 0:
                missing_count = max(0, socket_count - filled_gems)
                if missing_count > 0 and (has_zeros or len(gems) < socket_count):
                    missing_gems.append(f"{slot} ({missing_count})")

    return missing_enchants, missing_gems


def get_missing_enchants_gems(char_name: str, server: str = "Lordaeron"):
    gear_data = get_gear_data(char_name, server)
    return get_missing_enchants_gems_from_gear_data(gear_data)


def get_gem_name(gem_id: str) -> str:
    """Return a human-readable gem name from gem_data.json (lookup by item ID), or the raw ID as fallback."""
    gem_data = _load_gem_data()
    gem_info = gem_data.get(str(gem_id))
    if isinstance(gem_info, dict):
        return gem_info.get("name", str(gem_id))
    return str(gem_id)


def get_suboptimal_gems_from_gear_data(
    gear_data: list, clase: str, spec: str
) -> list[str]:
    """
    For each filled (non-meta) gem slot, check whether the gem is in the
    recommended set for the given class/spec.  Returns a list of short
    description strings such as ``"Head: Brilliant Autumn's Glow (+16 Int)"``
    for every gem that does not match the expected role.

    The values in gear_data[*]["gems"] are **enchant IDs** (as returned by
    the Warmane armory), so we resolve them via the enchant→item reverse map
    before comparing against the optimal item-ID sets.

    Returns an empty list when the spec is unknown or no suboptimal gems
    are found.
    """
    clean_class = str(clase or "").strip().lower()
    clean_spec = str(spec or "").strip().lower()
    if not clean_class or not clean_spec:
        return []

    acceptable = OPTIMAL_GEMS_BY_SPEC.get((clean_class, clean_spec))
    if acceptable is None:
        return []

    combined_ok = acceptable | _ALWAYS_OK_GEMS
    by_enchant = _load_gem_by_enchant()
    results: list[str] = []

    for item in gear_data:
        slot = item.get("slot", "Unknown")
        gems = item.get("gems") or []
        for enchant_id in gems:
            eid_str = str(enchant_id or "").strip()
            if not eid_str or eid_str == "0":
                continue

            gem_info = by_enchant.get(eid_str)
            if gem_info is None:
                # Unknown enchant_id — skip silently
                continue

            # Skip meta gems (they go in a dedicated meta socket)
            if gem_info["meta"]:
                continue

            item_id = gem_info["item_id"]

            # Also skip via item_id-based meta set (belt buckle etc.)
            if item_id in META_GEM_IDS:
                continue

            if item_id not in combined_ok:
                name = gem_info["name"]
                effect = gem_info["effect"]
                label = f"{name} ({effect})" if effect else name
                results.append(f"{slot}: {label}")

    return results
