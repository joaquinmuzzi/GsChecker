import re
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup

import gearscore
import profile_scraper
from src.schemas.constants import (
    SESSION,
    HTTP_TIMEOUT,
    SUMMARY_CACHE,
    SUMMARY_TTL,
    ACHIEVEMENTS_CACHE,
    ACHIEVEMENTS_TTL,
    GEAR_CACHE,
    GEAR_TTL,
    STATS_CACHE,
    STATS_TTL,
)
from src.functions.cache import _cache_get, _cache_set


def _summary_from_profile_html(nombre: str, server: str):
    profile_url = f"https://armory.warmane.com/character/{nombre}/{server}/profile"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://armory.warmane.com/",
    }

    try:
        resp = SESSION.get(profile_url, headers=headers, timeout=HTTP_TIMEOUT)
    except Exception:
        return None

    if resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    target_server = (server or "").strip().lower()
    target_name = (nombre or "").strip()
    lower_text = page_text.lower()
    lower_name = target_name.lower()

    guild_name = "Sin guild"
    summary_name = target_name

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if "/guild/" not in href or "/summary/" not in href:
            continue
        if f"/{target_server}/" not in href.lower():
            continue
        if f"/summary/{lower_name}" not in href.lower():
            continue

        text = anchor.get_text(" ", strip=True)
        if text:
            guild_name = " ".join(text.split())
        break

    header_pattern = re.compile(
        r"Level\s+(?P<level>\d+)\s+"
        r"(?P<race>[A-Za-zÀ-ÿ'\- ]+?)\s+"
        r"(?P<class>[A-Za-zÀ-ÿ'\- ]+?),\s*"
        r"(?P<server>[A-Za-zÀ-ÿ'\-]+)",
        re.IGNORECASE,
    )

    for match in header_pattern.finditer(page_text):
        data = {
            k: (" ".join(v.split()) if isinstance(v, str) else v)
            for k, v in match.groupdict().items()
        }
        if data.get("server", "").lower() != target_server:
            continue

        start = match.start()
        window_start = max(0, start - 200)
        left_window = page_text[window_start:start]
        left_window_lower = left_window.lower()

        idx = left_window_lower.rfind(lower_name)
        if idx == -1:
            continue

        summary_name = left_window[idx : idx + len(target_name)]
        return {
            "name": summary_name or target_name,
            "level": int(data.get("level") or 0),
            "race": data.get("race") or "N/A",
            "class": data.get("class") or "N/A",
            "guild": guild_name,
            "gearScore": "N/A",
        }

    legacy_pattern = re.compile(
        r"(?P<name>[A-Za-zÀ-ÿ'\- ]+)\s+"
        r"(?:\[(?P<guild>[^\]]+)\]\s+)?"
        r"Level\s+(?P<level>\d+)\s+"
        r"(?P<race>[A-Za-zÀ-ÿ'\- ]+?)\s+"
        r"(?P<class>[A-Za-zÀ-ÿ'\- ]+?),\s*"
        r"(?P<server>[A-Za-zÀ-ÿ'\-]+)"
    )

    for match in legacy_pattern.finditer(page_text):
        data = {
            k: (" ".join(v.split()) if isinstance(v, str) else v)
            for k, v in match.groupdict().items()
        }
        if data.get("server", "").lower() != target_server:
            continue
        if data.get("name", "").lower() != nombre.lower():
            continue

        return {
            "name": data.get("name") or nombre,
            "level": int(data.get("level") or 0),
            "race": data.get("race") or "N/A",
            "class": data.get("class") or "N/A",
            "guild": data.get("guild") or guild_name,
            "gearScore": "N/A",
        }

    return None


def _fetch_summary(nombre: str, server: str):
    cache_key = (nombre, server)
    cached = _cache_get(SUMMARY_CACHE, cache_key, SUMMARY_TTL)
    if cached is not None:
        return cached

    summary = _summary_from_profile_html(nombre, server)
    if summary is not None:
        _cache_set(SUMMARY_CACHE, cache_key, summary)
        return summary

    return {"__error__": f"⚠️ No se encontró el personaje '{nombre}' en {server}."}


def _fetch_specs(nombre: str, server: str) -> list[dict]:
    return profile_scraper.get_specs(nombre, server)


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
        url = f"https://armory.warmane.com/character/{nombre}/{server}/achievements"
        resp_achi = SESSION.post(
            url, headers=headers, data={"category": category_id}, timeout=HTTP_TIMEOUT
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
