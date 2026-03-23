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
SOCKET_CACHE_ONLY = False
_SOCKET_CACHE = None
_SLOT_CACHE = None


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


def _save_socket_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass


def get_specs(char_name: str, server: str) -> list[dict]:
    try:
        profile_url = f"https://armory.warmane.com/character/{char_name}/{server}/profile"
        profile_resp = SESSION.get(profile_url, headers=HEADERS, timeout=8)
        if profile_resp.status_code == 200:
            profile_soup = BeautifulSoup(profile_resp.text, "html.parser")
            profile_specs = []
            for text_node in profile_soup.select("div.specialization div.stub div.text"):
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

        api_url = f"https://armory.warmane.com/api/character/{char_name}/{server}/talents"
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
