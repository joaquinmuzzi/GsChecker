import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'GsChecker/1.0'}

def parse_slot(slot):
    if not slot.get('rel'):
        return None
    item_properties_list = slot['rel'][0].split('&')
    item_properties = dict(property.split('=') for property in item_properties_list)
    return item_properties.get('item')

def get_gear_ids(char_name: str, server: str = 'Lordaeron'):
    url = f"http://armory.warmane.com/character/{char_name}/{server}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    if resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, 'html.parser')
    # find equipment anchors
    try:
        equipment = soup.find(class_="item-model").find_all('a')
    except Exception:
        return []
    gear_ids = [parse_slot(slot) for slot in equipment]
    # Ensure we return list of strings (or empty strings) same length expected by gears core
    return [gid if gid and gid.isdigit() else '' for gid in gear_ids]
