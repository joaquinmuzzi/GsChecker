import re
from functools import lru_cache
import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'GsChecker/1.0'}

SLOT_FALLBACK_ORDER = [
    "Head", "Neck", "Shoulder", "Back", "Chest", "Shirt", "Tabard",
    "Wrist", "Hands", "Waist", "Legs", "Feet", "Finger 1", "Finger 2",
    "Trinket 1", "Trinket 2", "Main Hand", "Off Hand", "Ranged"
]

ENCHANTABLE_SLOTS = {
    "Head", "Shoulder", "Chest", "Legs", "Hands", "Feet", "Wrist",
    "Back", "Main Hand", "Off Hand", "One-Hand", "Two-Hand"
}

ITEM_HEADERS = {"User-Agent": "GsChecker item-sockets/1.0"}

def _get_raw_stats(page_text: str) -> str:
    try:
        raw_stats = page_text[page_text.index("tooltip_enus") :]
        return raw_stats[: raw_stats.index("_[")]
    except ValueError:
        return page_text

@lru_cache(maxsize=512)
def get_item_socket_count(item_id: str) -> int:
    try:
        item_url = f"https://wotlk.evowow.com/?item={item_id}"
        resp = requests.get(item_url, headers=ITEM_HEADERS, timeout=10)
        if resp.status_code != 200:
            return 0
        raw_stats = _get_raw_stats(resp.text)
        sockets = re.findall("socket-([a-z]{3,9})", raw_stats)
        return len(sockets)
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
    if not slot.get('rel'):
        return {}
    item_properties_list = slot['rel'][0].split('&')
    item_properties = dict(property.split('=') for property in item_properties_list)
    if 'gems' in item_properties:
        item_properties['gems'] = item_properties.get('gems', '0:0:0').split(':')
    return item_properties

def get_gear_data(char_name: str, server: str = 'Lordaeron'):
    url = f"http://armory.warmane.com/character/{char_name}/{server}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    if resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, 'html.parser')
    try:
        equipment = soup.find(class_="item-model").find_all('a')
    except Exception:
        return []
    gear_data = []
    for idx, slot in enumerate(equipment):
        item_properties = parse_slot(slot)
        item_properties["slot"] = _extract_slot_name(slot, idx)
        gear_data.append(item_properties)
    return gear_data

def get_gear_ids(char_name: str, server: str = 'Lordaeron'):
    gear_data = get_gear_data(char_name, server)
    gear_ids = [item.get('item') for item in gear_data]
    return [gid if gid and str(gid).isdigit() else '' for gid in gear_ids]

def get_missing_enchants_gems(char_name: str, server: str = 'Lordaeron'):
    gear_data = get_gear_data(char_name, server)
    missing_enchants = []
    missing_gems = []

    for item in gear_data:
        slot = item.get("slot", "Unknown")
        item_id = item.get("item")
        if not item_id:
            continue

        ench_id = item.get("ench")
        if slot in ENCHANTABLE_SLOTS and (not ench_id or str(ench_id) == "0"):
            missing_enchants.append(slot)

        if "gems" in item:
            gems = item.get("gems") or []
            socket_count = get_item_socket_count(str(item_id))
            if socket_count > 0:
                filled_gems = sum(1 for g in gems if g and str(g) != "0")
                missing_count = max(0, socket_count - filled_gems)
                if missing_count > 0:
                    missing_gems.append(f"{slot} ({missing_count})")

    return missing_enchants, missing_gems
