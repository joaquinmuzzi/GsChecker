import json
import re
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_PATH = BASE_DIR / "static" / "item_sockets_cache.json"
EXTRA_ITEMS_PATH = BASE_DIR / "static" / "raid_items_extra.json"
SETS_PATH = BASE_DIR.parent / "WarmaneProfileParser" / "static" / "sets.json"
GS_PATHS = [
    BASE_DIR / "static" / "GS.json",
    BASE_DIR.parent / "WarmaneProfileParser" / "static" / "GS.json",
]

RAID_ILVLS = {219, 226, 232, 245, 258, 251, 264, 277}
HEADERS = {"User-Agent": "GsChecker item-sockets/1.0"}


def get_raw_stats(page_text: str) -> str:
    try:
        raw_stats = page_text[page_text.index("tooltip_enus") :]
        return raw_stats[: raw_stats.index("_[")]
    except ValueError:
        return page_text


def socket_count_from_text(text: str) -> int:
    raw_stats = get_raw_stats(text)
    sockets = re.findall(r"socket-([a-z]{3,9})", raw_stats)
    return len(sockets)


def load_sets_items() -> set[str]:
    if not SETS_PATH.exists():
        return set()
    with SETS_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    items: set[str] = set()
    for class_sets in data.values():
        if not isinstance(class_sets, dict):
            continue
        for set_data in class_sets.values():
            try:
                for set_entry in set_data.get("sets", []):
                    if set_entry.get("ilvl") in RAID_ILVLS:
                        items.update(set_data.get("items", []))
                        break
            except Exception:
                continue
    return {item for item in items if str(item).isdigit()}


def load_extra_items() -> set[str]:
    if not EXTRA_ITEMS_PATH.exists():
        return set()
    try:
        with EXTRA_ITEMS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {str(x) for x in data if str(x).isdigit()}
    except Exception:
        return set()
    return set()

def load_gs_items() -> set[str]:
    item_ids: set[str] = set()
    for path in GS_PATHS:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        def collect(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(k, str) and k.isdigit():
                        item_ids.add(k)
                    collect(v)
            elif isinstance(obj, list):
                for v in obj:
                    collect(v)
            elif isinstance(obj, str) and obj.isdigit():
                item_ids.add(obj)

        collect(data)
    return item_ids


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    with CACHE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump(cache, f)


def main() -> None:
    raid_items = load_sets_items() | load_extra_items() | load_gs_items()
    cache = load_cache()

    missing = [item_id for item_id in raid_items if item_id not in cache]
    print(f"Raid items: {len(raid_items)} | Missing in cache: {len(missing)}")

    session = requests.Session()
    for idx, item_id in enumerate(missing, 1):
        try:
            url = f"https://wotlk.evowow.com/?item={item_id}"
            resp = session.get(url, headers=HEADERS, timeout=6)
            if resp.status_code != 200:
                cache[item_id] = 0
            else:
                cache[item_id] = socket_count_from_text(resp.text)
        except Exception:
            cache[item_id] = 0

        if idx % 200 == 0:
            print(f"Processed {idx}/{len(missing)}")

    save_cache(cache)
    print(f"Cache size: {len(cache)}")


if __name__ == "__main__":
    main()
