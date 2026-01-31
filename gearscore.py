import json
import os

# Try common locations for the static data file
possible_paths = [
    os.path.join(os.getcwd(), "static", "GS.json"),
    os.path.join(os.getcwd(), "WarmaneProfileParser", "static", "GS.json"),
    os.path.join(os.path.dirname(__file__), "..", "WarmaneProfileParser", "static", "GS.json"),
]
DATA = None
for p in possible_paths:
    try:
        with open(p, 'r') as f:
            DATA = json.load(f)
            break
    except Exception:
        continue
if DATA is None:
    raise FileNotFoundError(f"GS.json not found in any of: {possible_paths}")

SLOT_TYPES: list[str] = DATA['SLOT_TYPES']
LEGENDARY: dict[str, int] = DATA['LEGENDARY']
ITEM_TYPE: dict[str, int] = DATA['ITEM_TYPE']
ILVL_GS: dict[str, list[int]] = DATA['ILVL_GS']
GS_DATA: dict[str, dict[str, list[str]]] = DATA['GS_DATA']

def item_gs(item_ID: str, categoryName: str):
    if item_ID and categoryName != "":
        for ilvl, itemIDs in GS_DATA[categoryName].items():
            if item_ID in itemIDs:
                return ILVL_GS[ilvl][ITEM_TYPE[categoryName]]
    return 0

def get_weapon_GS(item_ID):
    if not item_ID:
        return 0, None
    item_type = 'Legendary'
    weapon_GS = LEGENDARY.get(item_ID)
    if not weapon_GS:
        item_type = 'high'
        weapon_GS = item_gs(item_ID, item_type)
    if not weapon_GS:
        item_type = 'two_hand'
        weapon_GS = item_gs(item_ID, item_type)
    return weapon_GS, item_type

def main(gear):
    """Receive a list of item IDs in the order used by WarmaneProfileParser and
    return a list with per-slot GearScore values.
    """
    *armor_IDs, mainhand_item_ID, offhand_item_ID, ranged_item_ID = gear
    armor_GS = [item_gs(itemID, categoryName) for itemID, categoryName in zip(armor_IDs, SLOT_TYPES)]
    mainhand_GS, mainhand_type = get_weapon_GS(mainhand_item_ID)
    offhand_GS, offhand_type = get_weapon_GS(offhand_item_ID)
    if offhand_type == 'two_hand':
        mainhand_GS //= 2
        offhand_GS //= 2
    ranged_GS = item_gs(ranged_item_ID, 'ranged')
    return armor_GS + [mainhand_GS, offhand_GS, ranged_GS]
