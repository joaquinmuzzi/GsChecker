"""Kills de Marrowgar y Deathwhisper en ICC 10H, 25N y 25H.

Las estadísticas de Warmane no las cuentan bien, así que se combinan otras
fuentes: UwU Logs, el logro Storming the Citadel, los ítems equipados que solo
dropean esos bosses y las kills ya confirmadas antes (guardadas en Postgres).
"""

import logging

from src.db.postgres import get_external_cache, set_external_cache
from src.schemas.constants import HTTP_TIMEOUT, SESSION
from src.services.cache_keys import _build_confirmed_icc_kills_key

# Mismo logger que cuando todo vivía en commands.py: los logs de Railway no cambian.
logger = logging.getLogger("gschecker.commands")

ITEM_SOURCE_TTL = 86400
CONFIRMED_KILLS_TTL = 315360000
ICC_SPECIAL_BOSSES = ("Marrowgar", "Deathwhisper")
ICC_SPECIAL_MODES = ("10H", "25N", "25H")

# Mapeo hardcodeado por ID de objeto (sin inferencia por ilvl en runtime).
# Puedes ampliar estas listas con más IDs de Wowhead/Cavern of Time.
ICC_ITEM_IDS_10H_25N = {str(item_id) for item_id in range(50604, 50618)}
ICC_ITEM_IDS_25H = {str(item_id) for item_id in range(51928, 51939)}


def _normalize_special_uwu_kills(uwu_icc_kills):
    base = uwu_icc_kills if isinstance(uwu_icc_kills, dict) else {}
    for boss_name in ICC_SPECIAL_BOSSES:
        boss_modes = base.setdefault(boss_name, {})
        if not isinstance(boss_modes, dict):
            boss_modes = {}
            base[boss_name] = boss_modes
        for mode in ICC_SPECIAL_MODES:
            boss_modes.setdefault(mode, None)
    return base


def _load_confirmed_icc_kills(nombre: str, server: str) -> dict:
    cached = get_external_cache(
        "character_icc_confirmed_kills",
        _build_confirmed_icc_kills_key(nombre, server),
        CONFIRMED_KILLS_TTL,
    )
    return _normalize_special_uwu_kills(cached if isinstance(cached, dict) else {})


def _overlay_persistent_confirmed_kills(uwu_icc_kills, persistent_confirmed: dict):
    uwu_icc_kills = _normalize_special_uwu_kills(uwu_icc_kills)
    persistent_confirmed = _normalize_special_uwu_kills(persistent_confirmed)
    for boss_name in ICC_SPECIAL_BOSSES:
        for mode in ICC_SPECIAL_MODES:
            if persistent_confirmed.get(boss_name, {}).get(mode) == "✅":
                uwu_icc_kills[boss_name][mode] = "✅"
    return uwu_icc_kills


def _finalize_special_uwu_kills(uwu_icc_kills):
    uwu_icc_kills = _normalize_special_uwu_kills(uwu_icc_kills)
    for boss_name in ICC_SPECIAL_BOSSES:
        boss_modes = uwu_icc_kills.setdefault(boss_name, {})
        if not isinstance(boss_modes, dict):
            boss_modes = {}
            uwu_icc_kills[boss_name] = boss_modes
        for mode in ICC_SPECIAL_MODES:
            value = boss_modes.get(mode)
            if value not in {"✅", "❌"}:
                boss_modes[mode] = "?"
    return uwu_icc_kills


def _persist_new_confirmed_icc_kills(nombre: str, server: str, uwu_icc_kills):
    uwu_icc_kills = _normalize_special_uwu_kills(uwu_icc_kills)
    persistent_confirmed = _load_confirmed_icc_kills(nombre, server)
    changed = False

    for boss_name in ICC_SPECIAL_BOSSES:
        for mode in ICC_SPECIAL_MODES:
            if (
                uwu_icc_kills.get(boss_name, {}).get(mode) == "✅"
                and persistent_confirmed.get(boss_name, {}).get(mode) != "✅"
            ):
                persistent_confirmed[boss_name][mode] = "✅"
                changed = True

    if changed:
        set_external_cache(
            "character_icc_confirmed_kills",
            "/personaje/confirmed-kills",
            _build_confirmed_icc_kills_key(nombre, server),
            persistent_confirmed,
            {"character": nombre, "server": server},
        )

    return persistent_confirmed


def _fetch_item_source_hint(item_id: str) -> dict:
    clean_item_id = str(item_id or "").strip()
    if not clean_item_id.isdigit():
        return {"marrowgar": False, "deathwhisper": False}

    cache_key = f"wowhead:item-source:{clean_item_id}"
    cached = get_external_cache("wowhead_item_source", cache_key, ITEM_SOURCE_TTL)
    if isinstance(cached, dict):
        return cached

    url = f"https://www.wowhead.com/wotlk/item={clean_item_id}&xml"
    payload = {"marrowgar": False, "deathwhisper": False}

    try:
        resp = SESSION.get(url, timeout=min(HTTP_TIMEOUT, 5))
        if resp.status_code == 200:
            text = resp.text
            lowered = text.lower()
            payload = {
                "marrowgar": "lord marrowgar" in lowered,
                "deathwhisper": "lady deathwhisper" in lowered,
            }
    except Exception:
        logger.exception("wowhead item-source hint failed for item_id=%s", clean_item_id)
        payload = {"marrowgar": False, "deathwhisper": False}

    set_external_cache(
        "wowhead_item_source",
        url,
        cache_key,
        payload,
        {"item_id": clean_item_id},
    )
    return payload


def _apply_item_drop_fallback_to_uwu(uwu_icc_kills, gear_data):
    uwu_icc_kills = _normalize_special_uwu_kills(uwu_icc_kills)

    if not isinstance(gear_data, list) or not gear_data:
        return uwu_icc_kills

    unresolved = False
    for boss_name in ICC_SPECIAL_BOSSES:
        boss_modes = uwu_icc_kills.get(boss_name, {})
        if not isinstance(boss_modes, dict):
            continue
        if any(boss_modes.get(mode) != "✅" for mode in ICC_SPECIAL_MODES):
            unresolved = True
            break

    if not unresolved:
        return uwu_icc_kills

    item_ids = {
        str(item.get("item"))
        for item in gear_data
        if isinstance(item, dict) and str(item.get("item") or "").isdigit()
    }

    found_modes = {
        "Marrowgar": {"10H": False, "25N": False, "25H": False},
        "Deathwhisper": {"10H": False, "25N": False, "25H": False},
    }

    def infer_modes_from_item_id(item_id: str):
        if item_id in ICC_ITEM_IDS_25H:
            return ("25H",)
        if item_id in ICC_ITEM_IDS_10H_25N:
            return ("10H", "25N")
        return ()

    for item_id in item_ids:
        inferred_modes = infer_modes_from_item_id(item_id)
        if not inferred_modes:
            continue

        hint = _fetch_item_source_hint(item_id)
        if not isinstance(hint, dict):
            continue

        if hint.get("marrowgar"):
            for mode in inferred_modes:
                found_modes["Marrowgar"][mode] = True
        if hint.get("deathwhisper"):
            for mode in inferred_modes:
                found_modes["Deathwhisper"][mode] = True

    for boss_name in ICC_SPECIAL_BOSSES:
        boss_modes = uwu_icc_kills.setdefault(boss_name, {})
        if not isinstance(boss_modes, dict):
            boss_modes = {}
            uwu_icc_kills[boss_name] = boss_modes
        for mode in ICC_SPECIAL_MODES:
            if boss_modes.get(mode) != "✅" and found_modes.get(boss_name, {}).get(mode):
                boss_modes[mode] = "✅"

    return uwu_icc_kills


def _apply_storming_fallback_to_uwu(uwu_icc_kills, achi_payload: dict):
    uwu_icc_kills = _normalize_special_uwu_kills(uwu_icc_kills)

    if not isinstance(achi_payload, dict):
        return uwu_icc_kills

    raw_completed_ids = achi_payload.get("completed_ids", set())
    completed_ids = (
        {str(x) for x in raw_completed_ids} if isinstance(raw_completed_ids, (list, set)) else set()
    )

    mode_to_achievement = {
        "10H": bool(achi_payload.get("storming_10h_achieved") or "4628" in completed_ids),
        "25N": bool(achi_payload.get("storming_25n_achieved") or "4604" in completed_ids),
        "25H": bool(achi_payload.get("storming_25h_achieved") or "4632" in completed_ids),
    }

    for boss_name in ICC_SPECIAL_BOSSES:
        boss_modes = uwu_icc_kills.setdefault(boss_name, {})
        if not isinstance(boss_modes, dict):
            boss_modes = {}
            uwu_icc_kills[boss_name] = boss_modes
        for mode, achieved in mode_to_achievement.items():
            if boss_modes.get(mode) != "✅" and achieved:
                boss_modes[mode] = "✅"

    return uwu_icc_kills


def _resolve_uwu_icc_kills(nombre_char, realm, raw_uwu_kills, persistent_confirmed, achi_payload, gear_data):
    """Kills especiales de ICC combinando fuentes, en este orden:
    1) UwU Logs, 2) Storming the Citadel, 3) ítems equipados del boss.
    Persiste las kills nuevas confirmadas (Postgres, sincrónico)."""
    uwu_icc_kills = _normalize_special_uwu_kills(raw_uwu_kills)
    uwu_icc_kills = _overlay_persistent_confirmed_kills(uwu_icc_kills, persistent_confirmed)
    uwu_icc_kills = _apply_storming_fallback_to_uwu(uwu_icc_kills, achi_payload)
    uwu_icc_kills = _apply_item_drop_fallback_to_uwu(uwu_icc_kills, gear_data)

    persistent_confirmed = _persist_new_confirmed_icc_kills(nombre_char, realm, uwu_icc_kills)
    uwu_icc_kills = _overlay_persistent_confirmed_kills(uwu_icc_kills, persistent_confirmed)
    return _finalize_special_uwu_kills(uwu_icc_kills)
