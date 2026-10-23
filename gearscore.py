import json
import math
import os

# Try common locations for the static data files
STATIC_DIRS = [
    os.path.join(os.path.dirname(__file__), "static"),
    os.path.join(os.getcwd(), "static"),
    os.path.join(os.getcwd(), "WarmaneProfileParser", "static"),
    os.path.join(os.path.dirname(__file__), "..", "WarmaneProfileParser", "static"),
]


def _load_static_json(filename: str):
    possible_paths = [os.path.join(static_dir, filename) for static_dir in STATIC_DIRS]
    for p in possible_paths:
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    raise FileNotFoundError(f"{filename} not found in any of: {possible_paths}")


DATA = _load_static_json("GS.json")

SLOT_TYPES: list[str] = DATA["SLOT_TYPES"]
LEGENDARY: dict[str, int] = DATA["LEGENDARY"]
ITEM_TYPE: dict[str, int] = DATA["ITEM_TYPE"]
ILVL_GS: dict[str, list[int]] = DATA["ILVL_GS"]
GS_DATA: dict[str, dict[str, list[str]]] = DATA["GS_DATA"]

# item_id -> (ilvl, quality, inventory_type) for every equippable 3.3.5a item,
# built by tools/build_item_levels.py. GS.json only lists epics of ilvl >= 200
# (and scores the ilvl-200 blues it does list as epics), so it is now just the
# fallback for IDs missing here.
ITEM_LEVELS: dict[str, tuple[int, int, int]] = {}
for _group, _item_ids in _load_static_json("item_levels.json")["groups"].items():
    _quality, _inventory_type, _ilvl = (int(part) for part in _group.split(":"))
    for _item_id in _item_ids:
        ITEM_LEVELS[str(_item_id)] = (_ilvl, _quality, _inventory_type)

# Same constants as the GearScore/GearScoreLite addon, so the bot matches the
# number players see in game.
GS_SCALE = 1.8618
# rarity -> (A, B) for items above ilvl 120, and for ilvl 120 or below
GS_FORMULA_HIGH_ILVL = {4: (91.45, 0.65), 3: (81.375, 0.8125), 2: (73.0, 1.0)}
GS_FORMULA_LOW_ILVL = {4: (26.0, 1.2), 3: (0.75, 1.8), 2: (8.0, 2.0), 1: (0.0, 2.25)}
# InventoryType -> slot modifier (shirt, tabard, bags and ammo are not listed: 0)
GS_SLOT_MOD = {
    1: 1.0,  # head
    2: 0.5625,  # neck
    3: 0.75,  # shoulder
    5: 1.0,  # chest
    6: 0.75,  # waist
    7: 1.0,  # legs
    8: 0.75,  # feet
    9: 0.5625,  # wrist
    10: 0.75,  # hands
    11: 0.5625,  # finger
    12: 0.5625,  # trinket
    13: 1.0,  # one-hand
    14: 1.0,  # shield
    15: 0.3164,  # ranged (bow)
    16: 0.5625,  # back
    17: 2.0,  # two-hand
    20: 1.0,  # robe
    21: 1.0,  # main hand
    22: 1.0,  # off hand
    23: 1.0,  # held in off hand
    25: 0.3164,  # thrown
    26: 0.3164,  # ranged right (gun, crossbow, wand)
    28: 0.3164,  # relic
}
INVENTORY_TYPE_TWO_HAND = 17


def formula_gs(ilvl: float, quality: int, inventory_type: int) -> int:
    """GearScore of one item, computed like the addon's GearScore_GetItemScore."""
    quality_scale = 1.0
    if quality == 5:
        quality_scale, quality = 1.3, 4
    elif quality in (0, 1):
        quality_scale, quality = 0.005, 2
    elif quality == 7:
        quality, ilvl = 3, 187.05
    slot_mod = GS_SLOT_MOD.get(inventory_type)
    if slot_mod is None or not 2 <= quality <= 4:
        return 0
    a, b = (GS_FORMULA_HIGH_ILVL if ilvl > 120 else GS_FORMULA_LOW_ILVL)[quality]
    return max(0, math.floor(((ilvl - a) / b) * slot_mod * GS_SCALE * quality_scale))


def _table_gs(item_ID: str, categoryName: str) -> int:
    for ilvl, itemIDs in GS_DATA[categoryName].items():
        if item_ID in itemIDs:
            return ILVL_GS[ilvl][ITEM_TYPE[categoryName]]
    return 0


def item_gs(item_ID: str, categoryName: str):
    if item_ID and categoryName != "":
        item_level = ITEM_LEVELS.get(item_ID)
        if item_level is not None:
            return formula_gs(*item_level)
        return _table_gs(item_ID, categoryName)
    return 0


def get_weapon_GS(item_ID):
    """Return (GS, type) of a weapon slot item. The type is "two_hand" only for an
    item known to be a two-hander, and None when the item is unknown."""
    if not item_ID:
        return 0, None
    item_level = ITEM_LEVELS.get(item_ID)
    if item_level is not None:
        item_type = "two_hand" if item_level[2] == INVENTORY_TYPE_TWO_HAND else "high"
        return formula_gs(*item_level), item_type
    if LEGENDARY.get(item_ID):
        return LEGENDARY[item_ID], "Legendary"
    for item_type in ("high", "two_hand"):
        weapon_GS = _table_gs(item_ID, item_type)
        if weapon_GS:
            return weapon_GS, item_type
    # Unknown item: it must not count as a two-hander, or main() would halve the
    # main hand as if this were Titan's Grip.
    return 0, None


def main(gear):
    """Receive a list of item IDs in the order used by WarmaneProfileParser and
    return a list with per-slot GearScore values.
    """
    *armor_IDs, mainhand_item_ID, offhand_item_ID, ranged_item_ID = gear
    armor_GS = [item_gs(itemID, categoryName) for itemID, categoryName in zip(armor_IDs, SLOT_TYPES)]
    mainhand_GS, mainhand_type = get_weapon_GS(mainhand_item_ID)
    offhand_GS, offhand_type = get_weapon_GS(offhand_item_ID)
    # Titan's Grip: like the addon, a two-hander paired with an off-hand item
    # makes both weapons count half.
    if offhand_type == "two_hand" or (mainhand_type == "two_hand" and offhand_item_ID):
        mainhand_GS //= 2
        offhand_GS //= 2
    ranged_GS = item_gs(ranged_item_ID, "ranged")
    return [*armor_GS, mainhand_GS, offhand_GS, ranged_GS]
