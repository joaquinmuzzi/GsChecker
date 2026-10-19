"""Perfil de /personaje: el payload que se muestra y se guarda en caché.

`_compute_personaje_base` arma todo el perfil a partir de los datos crudos del
armory (menos las kills de UwU Logs, ver `icc_kills`). La usan /p y el cron de
preload; `test_personaje_parity.py` verifica que los dos guarden lo mismo.
"""

import logging

import gearscore
import profile_scraper
from src.db.postgres import set_external_cache
from src.functions.embeds import _extract_icc_boss_kills
from src.functions.warmane import _fetch_guild_rank
from src.services.cache_keys import _build_character_spec_gs_key
from src.services.spec_gearscore import (
    _build_spec_gs_entries,
    _get_known_gs_by_spec,
    _split_active_inactive_specs,
)

# Mismo logger que cuando todo vivía en commands.py: los logs de Railway no cambian.
logger = logging.getLogger("gschecker.commands")


def _serialize_personaje_payload(
    nombre_char,
    server,
    gs,
    nivel,
    raza,
    clase,
    spec_display,
    guild_display,
    guild_rank,
    halion_10n_achieved,
    halion_10h_achieved,
    halion_25n_achieved,
    halion_25h_achieved,
    icc_10,
    icc_25,
    missing_enchants,
    missing_gems,
    uwu_icc_kills,
    spec_gs_entries,
    active_spec_name,
    professions=None,
    suboptimal_gems=None,
    gear_item_count=None,
    data_complete=True,
    uwu_performance=None,
):
    return {
        "nombre_char": nombre_char,
        "server": server,
        "gs": gs,
        "nivel": nivel,
        "raza": raza,
        "clase": clase,
        "spec_display": spec_display,
        "guild_display": guild_display,
        "guild_rank": guild_rank,
        "halion_10n_achieved": halion_10n_achieved,
        "halion_10h_achieved": halion_10h_achieved,
        "halion_25n_achieved": halion_25n_achieved,
        "halion_25h_achieved": halion_25h_achieved,
        "icc_10": icc_10,
        "icc_25": icc_25,
        "missing_enchants": missing_enchants,
        "missing_gems": missing_gems,
        "suboptimal_gems": suboptimal_gems or [],
        "uwu_icc_kills": uwu_icc_kills,
        "spec_gs_entries": spec_gs_entries,
        "active_spec_name": active_spec_name,
        "professions": professions or [],
        "gear_item_count": gear_item_count,
        "data_complete": data_complete,
        "uwu_performance": uwu_performance,
    }


def _is_personaje_data_complete(achi_payload, stats_rows) -> bool:
    """False cuando el armory falló a mitad de camino: con logros o estadísticas
    faltantes el embed mostraría ❌ que en realidad son "no pudimos leerlo"."""
    achievements_ok = isinstance(achi_payload, dict) and achi_payload.get("complete", True)
    return bool(achievements_ok) and bool(stats_rows)


def _is_valid_personaje_payload(payload: dict) -> bool:
    """Return True if the payload has enough quality to be cached.

    Rejects partial armory responses where critical fields are missing or
    nonsensical (e.g. spec names containing GS values, empty boss counts
    when data should exist).  This prevents corrupt data from being served
    for the entire COMMAND_PERSONAJE_TTL window.
    """
    nombre = payload.get("nombre_char")
    if not nombre or not isinstance(nombre, str) or not nombre.strip():
        return False

    nivel = payload.get("nivel")
    if nivel != 80:
        return False

    gs = payload.get("gs")
    if gs is None:
        return False

    clase = payload.get("clase")
    if not clase or not isinstance(clase, str) or clase == "N/A":
        return False

    raza = payload.get("raza")
    if not raza or not isinstance(raza, str) or raza == "N/A":
        return False

    spec_display = payload.get("spec_display")
    if spec_display is None:
        return False

    # A WotLK character has ~18 equippable slots (Tabard/Shirt aside). A page
    # scrape that comes back with far fewer items is a sign of a partial/corrupt
    # armory response (Cloudflare interference, page hiccup) — the GS computed
    # from it undercounts and would otherwise get cached as fact for the whole
    # COMMAND_PERSONAJE_TTL window.
    if payload.get("data_complete") is False:
        return False

    gear_item_count = payload.get("gear_item_count")
    return gear_item_count is None or gear_item_count >= 15


def _compute_personaje_base(
    summary: dict,
    realm: str,
    gear_data,
    achi_payload,
    stats_rows,
    professions,
    talents,
    cache_endpoint: str,
) -> dict:
    """Todo el perfil de /personaje salvo las kills de uwu-logs, a partir de los
    datos crudos del armory. Sincrónica (hace I/O de guild rank y Postgres): la
    usan /p (en un thread) y el cron de preload, así un arreglo se hace una vez.

    Devuelve los kwargs de `_serialize_personaje_payload` menos `uwu_icc_kills`.
    """
    nombre_char = summary.get("name")
    clase = summary.get("class", "N/A")
    active_specs, inactive_specs = _split_active_inactive_specs(talents, clase)

    try:
        # gearscore.main() is positional (zips armor slots against a fixed
        # SLOT_TYPES template and unpacks the last 3 as main/off/ranged) — do
        # NOT filter out blank slots (e.g. empty Tabard) or every item after
        # them scores against the wrong slot category.
        gear_ids = profile_scraper.get_gear_ids_from_gear_data(gear_data)
        gs = sum(gearscore.main(gear_ids)) if gear_ids else summary.get("gearScore", "N/A")
    except Exception:
        logger.exception(
            "gearscore calc failed for '%s'/%s — falling back to armory gearScore",
            nombre_char,
            realm,
        )
        gs = summary.get("gearScore", "N/A")

    # Detect whether gear_data came from API stubs (item IDs only,
    # no real gem/enchant data).  In that case, skip ench/gems checks
    # to avoid false positives where stubs use ench="0" and gems=["0"].
    is_stubs = (
        isinstance(gear_data, list)
        and len(gear_data) > 0
        and all(isinstance(item, dict) and item.get("_source") == "api_stubs" for item in gear_data)
    )

    if is_stubs:
        missing_enchants, missing_gems = [], []
        suboptimal_gems = []
    else:
        try:
            missing_enchants, missing_gems = profile_scraper.get_missing_enchants_gems_from_gear_data(
                gear_data
            )
        except Exception:
            logger.exception("missing enchants/gems calc failed for '%s'/%s", nombre_char, realm)
            missing_enchants, missing_gems = [], []

        try:
            suboptimal_gems = profile_scraper.get_suboptimal_gems_from_gear_data(
                gear_data, clase, active_specs[0] if active_specs else ""
            )
        except Exception:
            logger.exception("suboptimal gems calc failed for '%s'/%s", nombre_char, realm)
            suboptimal_gems = []

    guild_obj = summary.get("guild")
    guild = guild_obj if isinstance(guild_obj, str) else "Sin guild"
    guild_rank = None
    if guild and guild != "Sin guild":
        try:
            guild_rank = _fetch_guild_rank(nombre_char, guild, realm)
        except Exception:
            logger.exception(
                "guild rank fetch failed for '%s' guild='%s'/%s",
                nombre_char,
                guild,
                realm,
            )
            guild_rank = None

    for active_spec in active_specs:
        clean_active_spec = str(active_spec or "").strip()
        if not clean_active_spec or clean_active_spec == "N/A":
            continue
        set_external_cache(
            "character_spec_gs",
            cache_endpoint,
            _build_character_spec_gs_key(nombre_char, realm, clean_active_spec),
            {"character": nombre_char, "spec": clean_active_spec, "gs": gs},
            {"character": nombre_char, "spec": clean_active_spec, "server": realm},
        )

    gs_by_spec = _get_known_gs_by_spec(
        nombre_char,
        realm,
        active_specs + inactive_specs,
        gs,
        active_specs,
    )

    # If current gear fetch failed (gs unknown), but we have any cached GS for
    # this character/spec set, reuse it for the active spec instead of showing '?'.
    if active_specs and gs in {None, "N/A", "?"}:
        active_name = str(active_specs[0] or "").strip()
        if active_name and gs_by_spec.get(active_name) in {None, "N/A", "?"}:
            fallback_gs = next(
                (value for value in gs_by_spec.values() if value not in {None, "N/A", "?"}),
                None,
            )
            if fallback_gs is not None:
                gs_by_spec[active_name] = fallback_gs

    spec_gs_entries = _build_spec_gs_entries(
        active_specs + inactive_specs,
        gs_by_spec,
        active_specs,
    )
    if (
        spec_gs_entries
        and not any(entry.get("main") for entry in spec_gs_entries)
        and gs not in {None, "N/A", "?"}
    ):
        spec_gs_entries[0]["main"] = True
        spec_gs_entries[0]["gearscore"] = gs

    # Avoid synthetic ICC counts when statistics are temporarily unavailable.
    # Storming achievements are handled in the special UwU section only.
    icc_10, icc_25 = _extract_icc_boss_kills(stats_rows)

    return {
        "nombre_char": nombre_char,
        "server": realm,
        "gs": gs,
        "nivel": summary.get("level", "N/A"),
        "raza": summary.get("race", "N/A"),
        "clase": clase,
        "spec_display": " - ".join(
            f"**{spec}**" if spec in active_specs else spec for spec in active_specs + inactive_specs
        ),
        "guild_display": f"<{guild}>" if guild and guild != "Sin guild" else "Sin guild",
        "guild_rank": guild_rank,
        # Warmane's Halion statistics are always empty, so trust the achievements.
        "halion_10n_achieved": achi_payload["halion_10n_achieved"],
        "halion_10h_achieved": achi_payload["halion_10h_achieved"],
        "halion_25n_achieved": achi_payload["halion_25n_achieved"],
        "halion_25h_achieved": achi_payload["halion_25h_achieved"],
        "icc_10": icc_10,
        "icc_25": icc_25,
        "missing_enchants": missing_enchants,
        "missing_gems": missing_gems,
        "spec_gs_entries": spec_gs_entries,
        "active_spec_name": active_specs[0] if active_specs else None,
        "professions": professions,
        "suboptimal_gems": suboptimal_gems,
        "gear_item_count": len(gear_data) if isinstance(gear_data, list) else 0,
        "data_complete": _is_personaje_data_complete(achi_payload, stats_rows),
    }
