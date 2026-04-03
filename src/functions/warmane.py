import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

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
    GUILD_RANK_CACHE,
    GUILD_RANK_TTL,
)
from src.functions.cache import _cache_get, _cache_set

WOW_CLASSES = (
    "Death Knight",
    "Paladin",
    "Warrior",
    "Hunter",
    "Rogue",
    "Priest",
    "Shaman",
    "Mage",
    "Warlock",
    "Druid",
)


def _cache_get_stale(cache: dict, key):
    entry = cache.get(key)
    if not entry:
        return None
    return entry[1]


def _warmane_get_with_scheme_fallback(path: str, headers: dict):
    last_status = None
    last_error = None
    for scheme in ("https", "http"):
        url = f"{scheme}://armory.warmane.com{path}"
        try:
            resp = SESSION.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        except Exception as exc:
            last_error = str(exc)
            continue
        last_status = resp.status_code
        if resp.status_code == 200:
            return resp
    print(
        f"[WARN] Warmane request failed for path='{path}' "
        f"(last_status={last_status}, last_error={last_error})"
    )
    return None


def _warmane_post_json_with_scheme_fallback(path: str, headers: dict, data: dict):
    last_status = None
    last_error = None
    for _ in range(2):
        for scheme in ("https", "http"):
            url = f"{scheme}://armory.warmane.com{path}"
            try:
                resp = SESSION.post(
                    url, headers=headers, data=data, timeout=HTTP_TIMEOUT
                )
            except Exception as exc:
                last_error = str(exc)
                continue
            last_status = resp.status_code
            if resp.status_code != 200:
                continue
            try:
                payload = resp.json()
            except Exception as exc:
                last_error = f"json error: {exc}"
                continue
            if isinstance(payload, dict):
                return payload
    return None


_PROFILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": "https://armory.warmane.com/",
}


def _fetch_profile_page_html(nombre: str, server: str) -> str:
    """Fetch and cache the profile page HTML in-memory (shared between summary,
    professions and specs to avoid hitting the same URL multiple times per command)."""
    cache_key = ("profile_html", nombre.lower(), server.lower())
    cached = _cache_get(SUMMARY_CACHE, cache_key, SUMMARY_TTL)
    if cached is not None:
        return cached
    resp = _warmane_get_with_scheme_fallback(
        f"/character/{nombre}/{server}/profile", _PROFILE_HEADERS
    )
    html = resp.text if resp is not None else ""
    _cache_set(SUMMARY_CACHE, cache_key, html)
    return html


def _summary_from_profile_html(nombre: str, server: str):
    html = _fetch_profile_page_html(nombre, server)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    target_server = (server or "").strip()
    target_server_lower = target_server.lower()
    target_name = (nombre or "").strip()
    lower_name = target_name.lower()

    character_sheet = soup.select_one("#character-sheet")
    if character_sheet:
        guild_name = "Sin guild"

        guild_link = character_sheet.select_one(
            ".information .information-left .name .guild-name a"
        )
        if guild_link:
            guild_text = guild_link.get_text(" ", strip=True)
            if guild_text:
                guild_name = " ".join(guild_text.split())

        name_node = character_sheet.select_one(".information .information-left .name")
        parsed_name = target_name
        if name_node:
            for span in name_node.select(".guild-name"):
                span.extract()
            raw_name = name_node.get_text(" ", strip=True)
            if raw_name:
                parsed_name = " ".join(raw_name.split())

        level_node = character_sheet.select_one(
            ".information .information-left .level-race-class"
        )
        if level_node:
            level_text = " ".join(level_node.get_text(" ", strip=True).split())
            level_pattern = re.compile(
                r"Level\s+(?P<level>\d+)\s+(?P<race_class>.+?),\s*(?P<server>.+)$",
                re.IGNORECASE,
            )
            level_match = level_pattern.search(level_text)
            if level_match:
                level_data = {
                    key: " ".join(value.split())
                    for key, value in level_match.groupdict().items()
                }
                if level_data.get("server", "").lower() == target_server_lower:
                    race_class = level_data.get("race_class") or ""
                    parsed_race = "N/A"
                    parsed_class = race_class or "N/A"
                    for wow_class in WOW_CLASSES:
                        suffix = f" {wow_class}"
                        if race_class.endswith(suffix):
                            parsed_race = race_class[: -len(suffix)].strip() or "N/A"
                            parsed_class = wow_class
                            break
                    return {
                        "name": parsed_name or target_name,
                        "level": int(level_data.get("level") or 0),
                        "race": parsed_race,
                        "class": parsed_class,
                        "guild": guild_name,
                        "gearScore": "N/A",
                    }

    guild_name = "Sin guild"
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        href_lower = href.lower()
        if "/guild/" not in href_lower or "/summary/" not in href_lower:
            continue
        if f"/{target_server_lower}/" not in href_lower:
            continue
        if f"/summary/{lower_name}" not in href_lower:
            continue
        text = anchor.get_text(" ", strip=True)
        if text:
            guild_name = " ".join(text.split())
        break

    strict_pattern = re.compile(
        rf"\b{re.escape(target_name)}\b\s+"
        r"(?:\[(?P<guild_bracket>[^\]]{1,80})\]\s+|(?P<guild_plain>[A-Za-zÀ-ÿ0-9'&\- ]{2,80})\s+)?"
        r"Level\s+(?P<level>\d+)\s+"
        r"(?P<race>[A-Za-zÀ-ÿ'\- ]+?)\s+"
        r"(?P<class>[A-Za-zÀ-ÿ'\- ]+?),\s*"
        rf"{re.escape(target_server)}\b",
        re.IGNORECASE,
    )

    match = strict_pattern.search(page_text)
    if match:
        data = {
            k: (" ".join(v.split()) if isinstance(v, str) else v)
            for k, v in match.groupdict().items()
        }
        parsed_guild = (
            data.get("guild_bracket") or data.get("guild_plain") or ""
        ).strip()
        return {
            "name": target_name,
            "level": int(data.get("level") or 0),
            "race": data.get("race") or "N/A",
            "class": data.get("class") or "N/A",
            "guild": parsed_guild or guild_name,
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
        if data.get("server", "").lower() != target_server_lower:
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

    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    not_found_hint = "Character does not exist" in page_text
    return None


def _summary_from_api(nombre: str, server: str):
    api_path = f"/api/character/{nombre}/{server}/summary"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://armory.warmane.com/",
    }
    resp = _warmane_get_with_scheme_fallback(api_path, headers)
    if resp is None:
        return None

    try:
        payload = resp.json()
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get("error"):
        return None

    server_name = str(payload.get("realmName") or payload.get("realm") or "").strip()
    if server_name and server_name.lower() != (server or "").strip().lower():
        return None

    char_name = str(payload.get("name") or "").strip()
    if not char_name:
        return None

    return {
        "name": char_name,
        "level": int(payload.get("level") or 0),
        "race": payload.get("race") or "N/A",
        "class": payload.get("class") or "N/A",
        "guild": payload.get("guild") or "Sin guild",
        "gearScore": payload.get("gearScore") or "N/A",
    }


def _fetch_summary(nombre: str, server: str):
    nombre = (nombre or "").strip()
    server = (server or "").strip()
    cache_key = (nombre.lower(), server.lower())
    cached = _cache_get(SUMMARY_CACHE, cache_key, SUMMARY_TTL)
    if cached is not None:
        return cached

    # Fetch API summary and profile HTML in parallel — both are needed but independent
    with ThreadPoolExecutor(max_workers=2) as pool:
        api_future = pool.submit(_summary_from_api, nombre, server)
        html_future = pool.submit(_fetch_profile_page_html, nombre, server)
        summary = api_future.result()
        html_future.result()  # ensures HTML is cached; _summary_from_profile_html will reuse it

    profile_summary = _summary_from_profile_html(nombre, server)  # instant: HTML already in cache

    if summary is None:
        if profile_summary is not None:
            print(f"[WARN] Falling back to profile summary for '{nombre}'/{server}")
            summary = profile_summary
    elif isinstance(profile_summary, dict):
        if not summary.get("guild") or summary.get("guild") == "Sin guild":
            summary["guild"] = profile_summary.get("guild") or summary.get("guild")
        if summary.get("gearScore") in {None, "", "N/A"}:
            summary["gearScore"] = profile_summary.get("gearScore") or summary.get(
                "gearScore"
            )

    if summary is not None:
        _cache_set(SUMMARY_CACHE, cache_key, summary)
        return summary

    return {"__error__": f"⚠️ No se encontró el personaje '{nombre}' en {server}."}


WOW_CLASSIC_SPEC_NAMES = {
    "Balance", "Feral Combat", "Restoration",
    "Arcane", "Fire", "Frost",
    "Holy", "Protection", "Retribution",
    "Beast Mastery", "Marksmanship", "Survival",
    "Assassination", "Combat", "Subtlety",
    "Arms", "Fury",
    "Discipline", "Shadow",
    "Elemental", "Enhancement",
    "Affliction", "Demonology", "Destruction",
    "Blood", "Unholy",
}


def _parse_specs_from_html(html: str) -> list[dict]:
    """Parse spec names from the armory profile HTML.
    The first spec in the specialization section is the active one.
    Returns [] if no specs are found so the caller can fall back.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    stubs = soup.select("div.specialization div.stub")
    specs = []
    for stub in stubs:
        text_node = stub.select_one("div.text")
        if not text_node:
            continue
        text_copy = BeautifulSoup(str(text_node), "html.parser")
        for value_span in text_copy.select("span.value"):
            value_span.extract()
        spec_name = " ".join(text_copy.get_text(" ", strip=True).split())
        if spec_name and spec_name in WOW_CLASSIC_SPEC_NAMES:
            stub_classes = stub.get("class") or []
            is_active = "active" in stub_classes or "selected" in stub_classes
            specs.append({"name": spec_name, "_active_flag": is_active})

    if not specs:
        return []

    # If any stub has an explicit active marker, use that; otherwise first = active
    has_explicit_active = any(s["_active_flag"] for s in specs)
    result = []
    for i, s in enumerate(specs):
        active = s["_active_flag"] if has_explicit_active else (i == 0)
        result.append({"name": s["name"], "active": active})
    return result


def _fetch_specs(nombre: str, server: str) -> list[dict]:
    nombre = (nombre or "").strip()
    server = (server or "").strip()
    cache_key = ("specs", nombre.lower(), server.lower())
    cached = _cache_get(SUMMARY_CACHE, cache_key, SUMMARY_TTL)
    if cached is not None:
        return cached

    # 1st attempt: reuse the profile HTML already fetched/cached by _fetch_summary
    #   (no extra HTTP request if we're running concurrently with summary task)
    html = _fetch_profile_page_html(nombre, server)
    result = _parse_specs_from_html(html)
    if result:
        _cache_set(SUMMARY_CACHE, cache_key, result)
        return result

    # 2nd attempt: dedicated talents page (has explicit "selected" class per spec)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp = _warmane_get_with_scheme_fallback(
        f"/character/{nombre}/{server}/talents", headers
    )
    if resp is not None:
        soup = BeautifulSoup(resp.text, "html.parser")
        result = [
            {
                "name": td.get_text(strip=True),
                "active": "selected" in (td.get("class") or []),
            }
            for td in soup.find_all("td", attrs={"data-spec": True})
            if td.get_text(strip=True) in WOW_CLASSIC_SPEC_NAMES
        ]
        if result:
            _cache_set(SUMMARY_CACHE, cache_key, result)
            return result

    # 3rd attempt: JSON API
    api_resp = _warmane_get_with_scheme_fallback(
        f"/api/character/{nombre}/{server}/talents",
        {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
         "Accept": "application/json"},
    )
    if api_resp is not None:
        try:
            payload = api_resp.json()
            talents = payload.get("talents") if isinstance(payload, dict) else None
            if isinstance(talents, list):
                result = [
                    {"name": str(t.get("tree") or "").strip(), "active": idx == 0}
                    for idx, t in enumerate(talents)
                    if isinstance(t, dict)
                    and str(t.get("tree") or "").strip() in WOW_CLASSIC_SPEC_NAMES
                ]
                if result:
                    _cache_set(SUMMARY_CACHE, cache_key, result)
                    return result
        except Exception:
            pass

    return []


def _fetch_professions(nombre: str, server: str) -> list[str]:
    nombre = (nombre or "").strip()
    server = (server or "").strip()
    cache_key = ("professions", nombre.lower(), server.lower())
    cached = _cache_get(SUMMARY_CACHE, cache_key, SUMMARY_TTL)
    if cached is not None:
        return cached

    html = _fetch_profile_page_html(nombre, server)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    prof_section = soup.find(class_="profskills")
    if not prof_section:
        return []

    result = []
    for stub in prof_section.find_all(class_="stub"):
        parts = [
            p.strip() for p in stub.get_text("\n", strip=True).split("\n") if p.strip()
        ]
        if len(parts) < 2:
            continue
        name = parts[0].capitalize()
        value = parts[1].replace(" ", "")
        result.append(f"{name} {value}")

    _cache_set(SUMMARY_CACHE, cache_key, result)
    return result


def _fetch_guild_rank(nombre: str, guild: str, server: str):
    clean_name = str(nombre or "").strip()
    clean_guild = str(guild or "").strip()
    clean_server = str(server or "").strip()
    if not clean_name or not clean_guild or clean_guild == "Sin guild":
        return None

    cache_key = (clean_name.lower(), clean_guild.lower(), clean_server.lower())
    cached = _cache_get(GUILD_RANK_CACHE, cache_key, GUILD_RANK_TTL)
    if cached is not None:
        return cached or None

    guild_slug = quote_plus(clean_guild)
    guild_path = f"/guild/{guild_slug}/{clean_server}/summary/{clean_name}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://armory.warmane.com/",
    }

    resp = _warmane_get_with_scheme_fallback(guild_path, headers)
    if resp is None:
        print(
            f"[WARN] Guild rank request failed for '{clean_name}' guild='{clean_guild}'"
        )
        return None

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        target_name = clean_name.lower()
        rank_index = None
        header_cells = soup.select("table thead th")
        for idx, header in enumerate(header_cells):
            header_text = " ".join(header.get_text(" ", strip=True).split()).lower()
            if header_text == "rank":
                rank_index = idx
                break

        for row in soup.select("#data-table-list tr"):
            link = row.select_one("td a[href*='/character/'][href*='/profile']")
            if not link:
                continue
            row_name = link.get_text(" ", strip=True).lower()
            if row_name != target_name:
                continue
            cells = row.find_all("td")
            if not cells:
                break

            candidate_indexes = []
            if rank_index is not None:
                candidate_indexes.append(rank_index)
            candidate_indexes.extend([5, len(cells) - 1])

            rank_text = ""
            for idx in candidate_indexes:
                if idx < 0 or idx >= len(cells):
                    continue
                candidate = " ".join(cells[idx].get_text(" ", strip=True).split())
                if candidate and not candidate.isdigit():
                    rank_text = candidate
                    break

            rank_text = " ".join(rank_text.split())
            if rank_text:
                _cache_set(GUILD_RANK_CACHE, cache_key, rank_text)
                return rank_text
            break
    except Exception:
        print(
            f"[WARN] Guild rank BeautifulSoup parsing failed for '{clean_name}' guild='{clean_guild}'"
        )

    _cache_set(GUILD_RANK_CACHE, cache_key, "")
    print(f"[WARN] Guild rank not found for '{clean_name}' guild='{clean_guild}'")
    return None


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
        achi_json = _warmane_post_json_with_scheme_fallback(
            f"/character/{nombre}/{server}/achievements",
            headers,
            {"category": category_id},
        )
        if not isinstance(achi_json, dict):
            return []
        if "content" not in achi_json:
            return []
        soup = BeautifulSoup(achi_json["content"], "html.parser")
        all_achievements = soup.find_all("div", class_="achievement")
        completed_achievements = []
        for ach in all_achievements:
            classes = ach.get("class") or []
            if isinstance(classes, str):
                class_list = classes.split()
            elif isinstance(classes, list):
                class_list = [str(value) for value in classes]
            else:
                class_list = []
            if "locked" not in class_list:
                completed_achievements.append(ach)
        ids = []
        for ach_div in completed_achievements:
            ach_id_raw = ach_div.get("id")
            if isinstance(ach_id_raw, list):
                ach_id_raw = ach_id_raw[0] if ach_id_raw else ""
            ach_id_full = str(ach_id_raw or "")
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
        "storming_10n_achieved": "4531" in completed_ids,
        "storming_10h_achieved": "4628" in completed_ids,
        "storming_25n_achieved": "4604" in completed_ids,
        "storming_25h_achieved": "4632" in completed_ids,
    }
    _cache_set(ACHIEVEMENTS_CACHE, cache_key, payload)
    return payload


def _fetch_toc_achievements(nombre: str, server: str):
    cache_key = ("toc", nombre, server)
    cached = _cache_get(ACHIEVEMENTS_CACHE, cache_key, ACHIEVEMENTS_TTL)
    if cached is not None:
        return cached

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    achi_path = f"/character/{nombre}/{server}/achievements"

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
        achi_json = _warmane_post_json_with_scheme_fallback(
            achi_path,
            headers=headers,
            data={"category": category_id},
        )
        if not isinstance(achi_json, dict):
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
            classes = ach_div.get("class") or []
            if isinstance(classes, str):
                class_list = classes.split()
            elif isinstance(classes, list):
                class_list = [str(value) for value in classes]
            else:
                class_list = []
            achieved = "locked" not in class_list
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

    stats_path = f"/character/{nombre}/{server}/statistics"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    js = _warmane_post_json_with_scheme_fallback(
        stats_path,
        headers,
        {"category": category_id},
    )
    if not isinstance(js, dict):
        stale = _cache_get_stale(STATS_CACHE, cache_key)
        if stale is not None:
            print(
                f"[WARN] Using stale statistics cache for '{nombre}'/{server} category={category_id}"
            )
            return stale
        return []
    content = js.get("content", "")
    if not content:
        stale = _cache_get_stale(STATS_CACHE, cache_key)
        if stale is not None:
            print(
                f"[WARN] Empty statistics content, using stale cache for '{nombre}'/{server} category={category_id}"
            )
            return stale
        return []

    soup = BeautifulSoup(content, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if tds:
            rows.append(tds)

    if not rows:
        stale = _cache_get_stale(STATS_CACHE, cache_key)
        if stale is not None:
            print(
                f"[WARN] No statistics rows parsed, using stale cache for '{nombre}'/{server} category={category_id}"
            )
            return stale

    _cache_set(STATS_CACHE, cache_key, rows)
    return rows
