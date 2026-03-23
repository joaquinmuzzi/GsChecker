import asyncio

import discord

import gearscore
import profile_scraper
from src.db.postgres import (
    find_character_spec_gs_by_metadata,
    get_external_cache,
    set_external_cache,
)
from src.schemas.constants import (
    CHARACTER_SPEC_GS_TTL,
    COMMAND_DPS_TTL,
    COMMAND_PERSONAJE_TTL,
    EXECUTOR,
    UWU_SERVER,
    UWU_MODES_ALL,
    UWU_PDPS_BOSS_ORDER,
    LOADING_FRAMES,
    DOCS_NOTAS_URL,
)
from src.functions.warmane import (
    _fetch_summary,
    _fetch_specs,
    _fetch_professions,
    _fetch_achievements,
    _fetch_toc_achievements,
    _fetch_gear_data,
    _fetch_statistics,
    _fetch_guild_rank,
)
from src.functions.uwu import _uwu_icc_bugfix_kills, _build_uwu_dps_summary
from src.functions.embeds import (
    _build_personaje_embed,
    _build_personaje_view,
    _format_uwu_dps_table,
    _extract_icc_boss_kills,
    _render_table,
)


DPS_COMMAND_TIMEOUT_SECONDS = 45
ITEM_SOURCE_TTL = 86400
CONFIRMED_KILLS_TTL = 315360000
ICC_SPECIAL_BOSSES = ("Marrowgar", "Deathwhisper")
ICC_SPECIAL_MODES = ("10H", "25N", "25H")

# Mapeo hardcodeado por ID de objeto (sin inferencia por ilvl en runtime).
# Puedes ampliar estas listas con más IDs de Wowhead/Cavern of Time.
ICC_ITEM_IDS_10H_25N = {str(item_id) for item_id in range(50604, 50618)}
ICC_ITEM_IDS_25H = {str(item_id) for item_id in range(51928, 51939)}


def _build_personaje_cache_key(nombre: str) -> str:
    return f"command:personaje:v7:{nombre.strip().lower()}"


def _build_dps_cache_key(nombre: str, spec: str | None) -> str:
    return f"command:dps:v2:{nombre.strip().lower()}:{(spec or '').strip().lower()}"


def _build_character_spec_gs_key(nombre: str, server: str, spec_name: str) -> str:
    return (
        f"character:spec-gs:{server.strip().lower()}:"
        f"{nombre.strip().lower()}:{spec_name.strip().lower()}"
    )


def _build_character_spec_gs_legacy_key(nombre: str, spec_name: str) -> str:
    return f"character:spec-gs:{nombre.strip().lower()}:{spec_name.strip().lower()}"


def _build_confirmed_icc_kills_key(nombre: str, server: str) -> str:
    return (
        f"character:icc-confirmed-kills:{server.strip().lower()}:"
        f"{nombre.strip().lower()}"
    )


DEFAULT_CHARACTER_REALM = "Lordaeron"
SUPPORTED_CHARACTER_REALMS = {
    "lordaeron": "Lordaeron",
    "icecrown": "Icecrown",
    "blackrock": "Blackrock",
    "onyxia": "Onyxia",
    "frostmourne": "Frostmourne",
}

CLASS_SPEC_FALLBACK = {
    "Death Knight": ["Blood", "Frost", "Unholy"],
    "Druid": ["Balance", "Feral Combat", "Restoration"],
    "Hunter": ["Beast Mastery", "Marksmanship", "Survival"],
    "Mage": ["Arcane", "Fire", "Frost"],
    "Paladin": ["Holy", "Protection", "Retribution"],
    "Priest": ["Discipline", "Holy", "Shadow"],
    "Rogue": ["Assassination", "Combat", "Subtlety"],
    "Shaman": ["Elemental", "Enhancement", "Restoration"],
    "Warlock": ["Affliction", "Demonology", "Destruction"],
    "Warrior": ["Arms", "Fury", "Protection"],
}

SPEC_SYNONYM_GROUPS = [
    ("Retribution", "Retri", "Ret"),
    ("Feral Combat", "Feral"),
    ("Beast Mastery", "BM"),
    ("Marksmanship", "MM"),
    ("Survival", "SV"),
    ("Death Knight", "DK"),
    ("Blood", "BDK"),
    ("Frost", "FDK"),
    ("Unholy", "UDK"),
]


def _normalize_character_realm(reino: str | None) -> str:
    clean_realm = str(reino or "").strip()
    if not clean_realm:
        return DEFAULT_CHARACTER_REALM

    normalized = SUPPORTED_CHARACTER_REALMS.get(clean_realm.lower())
    if normalized:
        return normalized

    title_realm = clean_realm.title()
    normalized = SUPPORTED_CHARACTER_REALMS.get(title_realm.lower())
    if normalized:
        return normalized

    valid_realms = ", ".join(SUPPORTED_CHARACTER_REALMS.values())
    raise ValueError(
        f"⚠️ Reino inválido: '{clean_realm}'. Reinos válidos: {valid_realms}."
    )


def _fallback_spec_names_for_class(class_name: str) -> list[str]:
    clean_class_name = str(class_name or "").strip()
    return list(CLASS_SPEC_FALLBACK.get(clean_class_name, []))


def _spec_lookup_candidates(spec_name: str) -> list[str]:
    clean_name = str(spec_name or "").strip()
    if not clean_name:
        return []

    lowered = clean_name.lower()
    candidates = [clean_name]
    for group in SPEC_SYNONYM_GROUPS:
        group_lower = [entry.lower() for entry in group]
        if lowered in group_lower:
            for entry in group:
                if entry.lower() not in {value.lower() for value in candidates}:
                    candidates.append(entry)
            break
    return candidates


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
        from src.schemas.constants import SESSION, HTTP_TIMEOUT

        resp = SESSION.get(url, timeout=min(HTTP_TIMEOUT, 5))
        if resp.status_code == 200:
            text = resp.text
            lowered = text.lower()
            payload = {
                "marrowgar": "lord marrowgar" in lowered,
                "deathwhisper": "lady deathwhisper" in lowered,
            }
    except Exception:
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

    completed_ids = achi_payload.get("completed_ids", set())
    if isinstance(completed_ids, list):
        completed_ids = set(str(x) for x in completed_ids)
    elif isinstance(completed_ids, set):
        completed_ids = set(str(x) for x in completed_ids)
    else:
        completed_ids = set()

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


def _get_known_gs_by_spec(
    nombre: str,
    server: str,
    spec_names: list[str],
    current_gs=None,
    active_specs=None,
):
    active_specs = set(active_specs or [])
    result = {}
    seen = set()
    for spec_name in spec_names:
        clean_name = str(spec_name or "").strip()
        if not clean_name or clean_name == "N/A" or clean_name in seen:
            continue
        seen.add(clean_name)
        if clean_name in active_specs and current_gs not in {None, "N/A"}:
            result[clean_name] = current_gs
            continue

        cache_payload = None
        for lookup_spec_name in _spec_lookup_candidates(clean_name):
            cached = get_external_cache(
                "character_spec_gs",
                _build_character_spec_gs_key(nombre, server, lookup_spec_name),
                CHARACTER_SPEC_GS_TTL,
            )
            if isinstance(cached, dict) and cached.get("gs") not in {None, "N/A"}:
                cache_payload = cached
                break

            legacy_cached = get_external_cache(
                "character_spec_gs",
                _build_character_spec_gs_legacy_key(nombre, lookup_spec_name),
                CHARACTER_SPEC_GS_TTL,
            )
            if isinstance(legacy_cached, dict) and legacy_cached.get("gs") not in {None, "N/A"}:
                legacy_server = str(legacy_cached.get("server") or "").strip().lower()
                if legacy_server == str(server or "").strip().lower():
                    cache_payload = legacy_cached
                    break

        if cache_payload is None:
            metadata_cached = find_character_spec_gs_by_metadata(
                nombre,
                server,
                _spec_lookup_candidates(clean_name),
                CHARACTER_SPEC_GS_TTL,
            )
            if isinstance(metadata_cached, dict) and metadata_cached.get("gs") not in {None, "N/A"}:
                cache_payload = metadata_cached

        if isinstance(cache_payload, dict):
            result[clean_name] = cache_payload.get("gs")
    return result


def _build_spec_gs_entries(
    spec_names: list[str],
    gs_by_spec: dict,
    active_specs: list[str] | None = None,
):
    active_spec_names = set(active_specs or [])
    entries = []
    seen = set()
    for spec_name in spec_names:
        clean_name = str(spec_name or "").strip()
        if not clean_name or clean_name == "N/A" or clean_name in seen:
            continue
        seen.add(clean_name)
        entries.append(
            {
                "name": clean_name,
                "main": clean_name in active_spec_names,
                "gearscore": gs_by_spec.get(clean_name, "?"),
            }
        )
    return sorted(entries, key=lambda entry: (not entry.get("main", False), entry.get("name", "")))


def _format_spec_gs_value(spec_gs_entries: list[dict]) -> str:
    lines = []
    for entry in spec_gs_entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        label = f"**{name}**" if entry.get("main") else name
        lines.append(f"{label}: {entry.get('gearscore', '?')}")
    return "\n".join(lines) if lines else "?"


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
    professions=None,
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
        "uwu_icc_kills": uwu_icc_kills,
        "spec_gs_entries": spec_gs_entries,
        "professions": professions or [],
    }


def _build_personaje_embed_from_cache(payload: dict):
    return _build_personaje_embed(
        payload["nombre_char"],
        payload["gs"],
        payload["nivel"],
        payload["raza"],
        payload["clase"],
        payload["spec_display"],
        payload["guild_display"],
        payload["halion_10n_achieved"],
        payload["halion_10h_achieved"],
        payload["halion_25n_achieved"],
        payload["halion_25h_achieved"],
        payload["icc_10"],
        payload["icc_25"],
        payload["missing_enchants"],
        payload["missing_gems"],
        payload.get("uwu_icc_kills"),
        spec_gs_value=_format_spec_gs_value(payload.get("spec_gs_entries", [])),
        guild_rank=payload.get("guild_rank"),
        professions=payload.get("professions"),
    )


def _build_dps_embed_from_cache(payload: dict):
    nombre_char = payload["nombre_char"]
    spec_display = payload.get("spec_display", "")
    uwu_rows = payload.get("uwu_rows", [])
    failed_by_mode = payload.get("failed_by_mode", {})
    timed_out = bool(payload.get("timed_out", False))

    grouped_rows = []
    for i, row in enumerate(uwu_rows):
        grouped_rows.append(dict(row))
        is_last = i == len(uwu_rows) - 1
        if is_last:
            continue
        current_boss = row.get("_boss")
        next_boss = uwu_rows[i + 1].get("_boss")
        if current_boss != next_boss:
            grouped_rows.append(
                {
                    "Boss": "---------",
                    "Mode": "--",
                    "Raids": "--",
                    "Max DPS": "---------",
                    "Avg DPS": "---------",
                    "_boss": "__sep__",
                    "_sep": True,
                }
            )

    for row in grouped_rows:
        row.pop("_boss", None)

    has_any_logs = any(
        row.get("Raids") not in {"0", "--"}
        for row in grouped_rows
        if not row.get("_sep")
    )

    uwu_table = _format_uwu_dps_table(grouped_rows)
    table_block = f"```\n{uwu_table}\n```"
    if len(table_block) > 3900:
        table_block = f"```\n{uwu_table[:3880]}\n...\n```"

    warning_note = ""
    if not has_any_logs:
        warning_note = (
            "\n⚠️ No se encontraron logs para este personaje"
            f"{' con esa spec' if payload.get('spec') else ''} en UwU Logs."
        )

    failed_parts = []
    if isinstance(failed_by_mode, dict):
        for mode in UWU_MODES_ALL:
            value = failed_by_mode.get(mode, 0)
            if isinstance(value, int) and value > 0:
                failed_parts.append(f"{mode}:{value}")
    failed_note = ""
    if failed_parts:
        failed_note = "\n⚠️ Consultas UwU fallidas por mode: " + " | ".join(failed_parts)

    timeout_note = ""
    if timed_out:
        timeout_note = "\n⚠️ Resultado parcial: se alcanzó el tiempo límite de consulta."

    embed = discord.Embed(
        title=f"{nombre_char} - Uwulogs DPS{spec_display}",
        description=table_block + warning_note + failed_note + timeout_note,
        color=0x2B2D31,
    )
    embed.add_field(
        name="Si ves datos vacíos, consulte:",
        value=DOCS_NOTAS_URL,
        inline=True,
    )
    return embed


async def _safe_defer(interaction: discord.Interaction) -> None:
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(thinking=True)
    except discord.HTTPException as exc:
        if getattr(exc, "code", None) != 40060:
            raise


def _http_retry_after(exc: discord.HTTPException) -> float:
    retry_after = 0.0
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            header_val = response.headers.get("Retry-After")
            if header_val:
                retry_after = float(header_val)
        except Exception:
            retry_after = 0.0
    return max(retry_after, 0.0)


async def _safe_edit_original_response(
    interaction: discord.Interaction, *, content=None, embed=None, view=None
) -> None:
    last_exc = None
    for attempt in range(4):
        try:
            kwargs = {"content": content, "embed": embed}
            if view is not None:
                kwargs["view"] = view
            await interaction.edit_original_response(**kwargs)
            return
        except discord.HTTPException as exc:
            if getattr(exc, "status", None) != 429:
                raise
            last_exc = exc
            wait_for = _http_retry_after(exc) or min(2**attempt, 8)
            await asyncio.sleep(wait_for)
    if last_exc:
        raise last_exc


async def _safe_send_error(interaction: discord.Interaction, message: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message)
        else:
            await interaction.response.send_message(message)
    except discord.HTTPException as exc:
        if getattr(exc, "status", None) != 429:
            raise
        wait_for = _http_retry_after(exc) or 3
        await asyncio.sleep(wait_for)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message)
            else:
                await interaction.response.send_message(message)
        except Exception:
            pass


async def _personaje_impl(
    interaction: discord.Interaction,
    nombre: str,
    command_name: str,
    reino: str | None = None,
):
    server_name = interaction.guild.name if interaction.guild else "DM"
    print(
        f"[LOG] Comando '{command_name}' usado por {interaction.user} "
        f"para personaje: {nombre} desde servidor: {server_name}"
    )
    try:
        nombre = nombre.capitalize()
        realm = _normalize_character_realm(reino)
        await _safe_defer(interaction)

        personaje_cache_key = f"{_build_personaje_cache_key(nombre)}:{realm.lower()}"
        cached_payload = get_external_cache(
            "command_personaje", personaje_cache_key, COMMAND_PERSONAJE_TTL
        )
        if isinstance(cached_payload, dict):
            embed_cached = _build_personaje_embed_from_cache(cached_payload)
            view_cached = _build_personaje_view(
                cached_payload["nombre_char"],
                cached_payload.get("server", DEFAULT_CHARACTER_REALM),
            )
            await _safe_edit_original_response(interaction, content=None, embed=embed_cached, view=view_cached)
            return

        await _safe_edit_original_response(
            interaction,
            content=f"⏳ Calculando perfil de {nombre} en {realm}...", embed=None
        )

        loop = asyncio.get_running_loop()

        uwu_icc_task = loop.run_in_executor(
            EXECUTOR, _uwu_icc_bugfix_kills, nombre, realm
        )
        prof_task = loop.run_in_executor(
            EXECUTOR, _fetch_professions, nombre, realm
        )
        summary_task = loop.run_in_executor(
            EXECUTOR, _fetch_summary, nombre, realm
        )
        gear_task = loop.run_in_executor(
            EXECUTOR, _fetch_gear_data, nombre, realm
        )
        achi_task = loop.run_in_executor(
            EXECUTOR, _fetch_achievements, nombre, realm
        )
        stats_task = loop.run_in_executor(
            EXECUTOR, _fetch_statistics, nombre, realm, 15062
        )

        summary, gear_data, achi_payload, stats_rows, professions = await asyncio.gather(
            summary_task, gear_task, achi_task, stats_task, prof_task
        )

        if isinstance(summary, dict) and summary.get("__error__"):
            await _safe_edit_original_response(
                interaction,
                content=summary["__error__"], embed=None
            )
            return

        if not isinstance(summary, dict):
            await _safe_edit_original_response(
                interaction,
                content="⚠️ Formato inesperado en 'summary'. Revisa la consola.",
                embed=None,
            )
            return

        nombre_char = summary.get("name", nombre)
        nivel = summary.get("level", "N/A")
        raza = summary.get("race", "N/A")
        clase = summary.get("class", "N/A")

        if nivel != 80:
            await _safe_edit_original_response(
                interaction,
                content=f"⚠️ **{nombre_char}** no es nivel 80.",
                embed=None,
            )
            return

        talents = _fetch_specs(nombre_char, realm)
        if isinstance(talents, list) and len(talents) > 0:
            sorted_talents = sorted(talents, key=lambda t: not t.get("active", False))
            active_specs = [
                t.get("name", "N/A") for t in sorted_talents if t.get("active", False)
            ]
            inactive_specs = [
                t.get("name", "N/A")
                for t in sorted_talents
                if not t.get("active", False)
            ]
        else:
            active_specs = []
            inactive_specs = _fallback_spec_names_for_class(clase)

        try:
            gear_ids = profile_scraper.get_gear_ids_from_gear_data(gear_data)
            if gear_ids:
                gs_values = gearscore.main(gear_ids)
                gs = sum(gs_values)
            else:
                gs = summary.get("gearScore", "N/A")
        except Exception:
            gs = summary.get("gearScore", "N/A")

        try:
            missing_enchants, missing_gems = (
                profile_scraper.get_missing_enchants_gems_from_gear_data(gear_data)
            )
        except Exception:
            missing_enchants, missing_gems = [], []

        guild_obj = summary.get("guild")
        guild = guild_obj if isinstance(guild_obj, str) else "Sin guild"
        guild_rank = None
        if guild and guild != "Sin guild":
            try:
                guild_rank = await loop.run_in_executor(
                    EXECUTOR,
                    _fetch_guild_rank,
                    nombre_char,
                    guild,
                    realm,
                )
            except Exception:
                guild_rank = None

        for active_spec in active_specs:
            clean_active_spec = str(active_spec or "").strip()
            if not clean_active_spec or clean_active_spec == "N/A":
                continue
            set_external_cache(
                "character_spec_gs",
                "/personaje",
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
        spec_gs_entries = _build_spec_gs_entries(
            active_specs + inactive_specs,
            gs_by_spec,
            active_specs,
        )

        halion_10n_achieved = achi_payload["halion_10n_achieved"]
        halion_10h_achieved = achi_payload["halion_10h_achieved"]
        halion_25n_achieved = achi_payload["halion_25n_achieved"]
        halion_25h_achieved = achi_payload["halion_25h_achieved"]

        icc_10, icc_25 = _extract_icc_boss_kills(stats_rows)
        guild_display = f"<{guild}>" if guild and guild != "Sin guild" else "Sin guild"
        spec_display = " - ".join(
            f"**{spec}**" if spec in active_specs else spec
            for spec in active_specs + inactive_specs
        )

        # Cargar kills confirmadas del DB antes del embed inicial,
        # así los ✅ ya guardados aparecen de inmediato sin loading.
        persistent_confirmed = _load_confirmed_icc_kills(nombre_char, realm)
        initial_uwu_kills = _normalize_special_uwu_kills(dict(persistent_confirmed))

        personaje_view = _build_personaje_view(nombre_char, realm)
        embed_initial = _build_personaje_embed(
            nombre_char,
            gs,
            nivel,
            raza,
            clase,
            spec_display,
            guild_display,
            halion_10n_achieved,
            halion_10h_achieved,
            halion_25n_achieved,
            halion_25h_achieved,
            icc_10,
            icc_25,
            missing_enchants,
            missing_gems,
            uwu_icc_kills=initial_uwu_kills,
            loading_symbol=LOADING_FRAMES[0],
            spec_gs_value=_format_spec_gs_value(spec_gs_entries),
            guild_rank=guild_rank,
            professions=professions,
        )
        await _safe_edit_original_response(interaction, content=None, embed=embed_initial, view=personaje_view)

        frame_idx = 1
        while not uwu_icc_task.done():
            await asyncio.sleep(2.0)
            if uwu_icc_task.done():
                break
            embed_loading = _build_personaje_embed(
                nombre_char,
                gs,
                nivel,
                raza,
                clase,
                spec_display,
                guild_display,
                halion_10n_achieved,
                halion_10h_achieved,
                halion_25n_achieved,
                halion_25h_achieved,
                icc_10,
                icc_25,
                missing_enchants,
                missing_gems,
                uwu_icc_kills=initial_uwu_kills,
                loading_symbol=LOADING_FRAMES[frame_idx % len(LOADING_FRAMES)],
                spec_gs_value=_format_spec_gs_value(spec_gs_entries),
                guild_rank=guild_rank,
                professions=professions,
            )
            frame_idx += 1
            await _safe_edit_original_response(interaction, content=None, embed=embed_loading, view=personaje_view)

        try:
            uwu_icc_kills = await uwu_icc_task
        except Exception:
            uwu_icc_kills = {}

        uwu_icc_kills = _normalize_special_uwu_kills(uwu_icc_kills)
        uwu_icc_kills = _overlay_persistent_confirmed_kills(
            uwu_icc_kills,
            persistent_confirmed,
        )

        # Orden requerido:
        # 1) UwU Logs
        # 2) Storming the Citadel
        # 3) Ítems equipados del boss
        uwu_icc_kills = _apply_storming_fallback_to_uwu(uwu_icc_kills, achi_payload)
        uwu_icc_kills = _apply_item_drop_fallback_to_uwu(uwu_icc_kills, gear_data)

        persistent_confirmed = _persist_new_confirmed_icc_kills(
            nombre_char,
            realm,
            uwu_icc_kills,
        )
        uwu_icc_kills = _overlay_persistent_confirmed_kills(
            uwu_icc_kills,
            persistent_confirmed,
        )

        embed_final = _build_personaje_embed(
            nombre_char,
            gs,
            nivel,
            raza,
            clase,
            spec_display,
            guild_display,
            halion_10n_achieved,
            halion_10h_achieved,
            halion_25n_achieved,
            halion_25h_achieved,
            icc_10,
            icc_25,
            missing_enchants,
            missing_gems,
            uwu_icc_kills=uwu_icc_kills,
            spec_gs_value=_format_spec_gs_value(spec_gs_entries),
            guild_rank=guild_rank,
            professions=professions,
        )
        set_external_cache(
            "command_personaje",
            f"/{command_name}",
            personaje_cache_key,
            _serialize_personaje_payload(
                nombre_char,
                realm,
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
                professions,
            ),
            {"character": nombre_char, "command": command_name, "server": realm},
        )
        await _safe_edit_original_response(interaction, content=None, embed=embed_final, view=personaje_view)

    except discord.NotFound:
        return
    except ValueError as e:
        await _safe_send_error(interaction, str(e))
    except Exception as e:
        await _safe_send_error(interaction, f"❌ Error al obtener datos: {e}")


def register_commands(bot):
    @bot.tree.command(name="ping", description="Muestra la latencia actual del bot.")
    async def ping(interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Pong! Latencia: {round(bot.latency * 1000)}ms"
        )

    @bot.tree.command(
        name="personaje",
        description="Muestra información del personaje desde la API de Warmane.",
    )
    @discord.app_commands.describe(
        nombre="Nombre del personaje.",
        reino="Reino opcional. Por defecto: Lordaeron.",
    )
    async def personaje(
        interaction: discord.Interaction,
        nombre: str,
        reino: str | None = None,
    ):
        await _personaje_impl(interaction, nombre, "personaje", reino)

    @bot.tree.command(
        name="p",
        description="Alias corto de /personaje para consultar un personaje.",
    )
    @discord.app_commands.describe(
        nombre="Nombre del personaje.",
        reino="Reino opcional. Por defecto: Lordaeron.",
    )
    async def p(
        interaction: discord.Interaction,
        nombre: str,
        reino: str | None = None,
    ):
        await _personaje_impl(interaction, nombre, "p", reino)

    @bot.tree.command(
        name="dps",
        description="Muestra DPS máximo/promedio por boss desde UwU Logs.",
    )
    @discord.app_commands.describe(
        nombre="Nombre del personaje en Lordaeron.",
        spec="Filtro opcional por spec (ej: fury, udk, frost).",
    )
    async def dps(
        interaction: discord.Interaction, nombre: str, spec: str | None = None
    ):
        server_name = interaction.guild.name if interaction.guild else "DM"
        print(
            f"[LOG] Comando 'dps' usado por {interaction.user} "
            f"para personaje: {nombre} DESDE SERVIDOR: {server_name}"
        )
        try:
            nombre = nombre.capitalize()
            spec_display = f" [{spec.upper()}]" if spec else ""
            await _safe_defer(interaction)

            dps_cache_key = _build_dps_cache_key(nombre, spec)
            cached_payload = get_external_cache(
                "command_dps", dps_cache_key, COMMAND_DPS_TTL
            )
            if isinstance(cached_payload, dict):
                embed_cached = _build_dps_embed_from_cache(cached_payload)
                await _safe_edit_original_response(interaction, content=None, embed=embed_cached)
                return

            await _safe_edit_original_response(
                interaction,
                content=f"⏳ Calculando DPS de {nombre}{spec_display}... esto puede tardar unos segundos",
                embed=None,
            )

            loop = asyncio.get_running_loop()

            summary = await loop.run_in_executor(
                EXECUTOR, _fetch_summary, nombre, "Lordaeron"
            )
            if isinstance(summary, dict) and summary.get("__error__"):
                await _safe_edit_original_response(
                    interaction,
                    content=summary["__error__"],
                    embed=None,
                )
                return
            if not isinstance(summary, dict):
                await _safe_edit_original_response(
                    interaction,
                    content="⚠️ No se pudo validar el personaje en Armory.",
                    embed=None,
                )
                return

            nombre_char = str(summary.get("name") or nombre)

            uwu_dps_future = loop.run_in_executor(
                EXECUTOR,
                _build_uwu_dps_summary,
                nombre_char,
                UWU_SERVER,
                UWU_PDPS_BOSS_ORDER,
                spec,
            )
            try:
                uwu_dps_summary = await asyncio.wait_for(
                    uwu_dps_future,
                    timeout=DPS_COMMAND_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                await _safe_edit_original_response(
                    interaction,
                    content=(
                        "⚠️ UwU Logs está respondiendo lento y el cálculo excedió el tiempo límite. "
                        "Intenta de nuevo en unos segundos."
                    ),
                    embed=None,
                )
                return

            if not isinstance(uwu_dps_summary, dict):
                await _safe_edit_original_response(
                    interaction,
                    content="⚠️ No se pudo leer respuesta de UwU Logs.", embed=None
                )
                return

            uwu_rows = uwu_dps_summary.get("rows", [])
            failed_by_mode = uwu_dps_summary.get("failed_by_mode", {})
            timed_out = bool(uwu_dps_summary.get("timed_out", False))
            if not uwu_rows:
                timeout_note = (
                    " (cálculo parcial por timeout)" if timed_out else ""
                )
                await _safe_edit_original_response(
                    interaction,
                    content=f"⚠️ No hay datos DPS en UwU Logs para {nombre_char}{timeout_note}.",
                    embed=None,
                )
                return

            boss_order = {name: idx for idx, name in enumerate(UWU_PDPS_BOSS_ORDER)}
            mode_order = {mode: idx for idx, mode in enumerate(UWU_MODES_ALL)}

            uwu_rows = sorted(
                uwu_rows,
                key=lambda x: (
                    boss_order.get(x.get("_boss"), 999),
                    mode_order.get(x.get("Mode", ""), 999),
                    x.get("_boss", x.get("Boss", "")),
                ),
            )

            grouped_rows = []
            for i, row in enumerate(uwu_rows):
                grouped_rows.append(row)
                is_last = i == len(uwu_rows) - 1
                if is_last:
                    continue
                current_boss = row.get("_boss")
                next_boss = uwu_rows[i + 1].get("_boss")
                if current_boss != next_boss:
                    grouped_rows.append(
                        {
                            "Boss": "---------",
                            "Mode": "--",
                            "Raids": "--",
                            "Max DPS": "---------",
                            "Avg DPS": "---------",
                            "_boss": "__sep__",
                            "_sep": True,
                        }
                    )

            uwu_rows = grouped_rows
            for row in uwu_rows:
                row.pop("_boss", None)

            has_any_logs = any(
                row.get("Raids") not in {"0", "--"}
                for row in uwu_rows
                if not row.get("_sep")
            )

            uwu_table = _format_uwu_dps_table(uwu_rows)
            table_block = f"```\n{uwu_table}\n```"
            if len(table_block) > 3900:
                table_block = f"```\n{uwu_table[:3880]}\n...\n```"

            warning_note = ""
            if not has_any_logs:
                warning_note = (
                    "\n⚠️ No se encontraron logs para este personaje"
                    f"{' con esa spec' if spec else ''} en UwU Logs."
                )

            failed_parts = []
            if isinstance(failed_by_mode, dict):
                for mode in UWU_MODES_ALL:
                    value = failed_by_mode.get(mode, 0)
                    if isinstance(value, int) and value > 0:
                        failed_parts.append(f"{mode}:{value}")
            failed_note = ""
            if failed_parts:
                failed_note = "\n⚠️ Consultas UwU fallidas por mode: " + " | ".join(failed_parts)

            timeout_note = ""
            if timed_out:
                timeout_note = "\n⚠️ Resultado parcial: se alcanzó el tiempo límite de consulta."

            embed = discord.Embed(
                title=f"{nombre_char} - Uwulogs DPS{spec_display}",
                description=table_block + warning_note + failed_note + timeout_note,
                color=0x2B2D31,
            )
            embed.add_field(
                name="Si ves datos vacíos, consulte:",
                value=DOCS_NOTAS_URL,
                inline=True,
            )
            set_external_cache(
                "command_dps",
                "/dps",
                dps_cache_key,
                {
                    "nombre_char": nombre_char,
                    "spec": spec,
                    "spec_display": spec_display,
                    "uwu_rows": uwu_dps_summary.get("rows", []),
                    "failed_by_mode": failed_by_mode,
                    "timed_out": timed_out,
                },
                {"character": nombre_char, "spec": spec or ""},
            )
            await _safe_edit_original_response(interaction, content=None, embed=embed)

        except discord.NotFound:
            return
        except Exception as e:
            await _safe_send_error(interaction, f"❌ Error al obtener DPS: {e}")

    @bot.tree.command(
        name="ptoc",
        description="Muestra logros de Trial of the Crusader (TOC) en formato tabla.",
    )
    @discord.app_commands.describe(nombre="Nombre del personaje en Lordaeron.")
    async def ptoc(interaction: discord.Interaction, nombre: str):
        server_name = interaction.guild.name if interaction.guild else "DM"
        print(
            f"[LOG] Comando 'ptoc' usado por {interaction.user} "
            f"para personaje: {nombre} DESDE SERVIDOR: {server_name}"
        )
        try:
            nombre = nombre.capitalize()
            await _safe_defer(interaction)

            loop = asyncio.get_running_loop()
            toc_payload = await loop.run_in_executor(
                EXECUTOR, _fetch_toc_achievements, nombre, "Lordaeron"
            )

            def toc_status(done: bool) -> str:
                return "✅" if done else "❌"

            toc_rows = [
                {
                    "Boss": "Trial of the Crusader",
                    "10N": toc_status(toc_payload["toc_10n"]),
                    "10H": toc_status(toc_payload["toc_10h"]),
                    "25N": toc_status(toc_payload["toc_25n"]),
                    "25H": toc_status(toc_payload["toc_25h"]),
                }
            ]

            toc_table = _render_table(
                toc_rows,
                ["Boss", "10N", "10H", "25N", "25H"],
                {
                    "10N": f"{toc_status(toc_payload['toc_10n'])}10N",
                    "10H": f"{toc_status(toc_payload['toc_10h'])}10H",
                    "25N": f"{toc_status(toc_payload['toc_25n'])}25N",
                    "25H": f"{toc_status(toc_payload['toc_25h'])}25H",
                },
            )

            embed = discord.Embed(
                title=f"{nombre} - Trial of the Crusader",
                color=0x2B2D31,
            )
            embed.add_field(
                name="Trial of the Crusader",
                value=f"```\n{toc_table}\n```",
                inline=False,
            )
            embed.add_field(
                name="Armory",
                value=f"https://armory.warmane.com/character/{nombre}/Lordaeron/achievements",
                inline=False,
            )

            await _safe_edit_original_response(interaction, content=None, embed=embed)

        except discord.NotFound:
            return
        except Exception as e:
            await _safe_send_error(interaction, f"❌ Error al obtener datos: {e}")
