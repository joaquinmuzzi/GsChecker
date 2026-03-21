import asyncio

import discord

import gearscore
import profile_scraper
from src.db.postgres import get_external_cache, set_external_cache
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
    _fetch_achievements,
    _fetch_toc_achievements,
    _fetch_gear_data,
    _fetch_statistics,
)
from src.functions.uwu import _uwu_icc_bugfix_kills, _build_uwu_dps_summary
from src.functions.embeds import (
    _build_personaje_embed,
    _format_uwu_dps_table,
    _extract_icc_boss_kills,
    _render_table,
)


def _build_personaje_cache_key(nombre: str) -> str:
    return f"command:personaje:{nombre.strip().lower()}"


def _build_dps_cache_key(nombre: str, spec: str | None) -> str:
    return f"command:dps:{nombre.strip().lower()}:{(spec or '').strip().lower()}"


def _build_character_spec_gs_key(nombre: str, spec_name: str) -> str:
    return f"character:spec-gs:{nombre.strip().lower()}:{spec_name.strip().lower()}"


def _get_known_gs_by_spec(nombre: str, spec_names: list[str], current_gs=None, active_specs=None):
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
        cached = get_external_cache(
            "character_spec_gs",
            _build_character_spec_gs_key(nombre, clean_name),
            CHARACTER_SPEC_GS_TTL,
        )
        if isinstance(cached, dict) and cached.get("gs") not in {None, "N/A"}:
            result[clean_name] = cached.get("gs")
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
    return entries


def _format_spec_gs_value(spec_gs_entries: list[dict]) -> str:
    lines = []
    for entry in spec_gs_entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        suffix = "(Main)" if entry.get("main") else "(Off-spec)"
        lines.append(f"{name} {suffix}:\n{entry.get('gearscore', '?')}")
    return "\n".join(lines) if lines else "?"


def _serialize_personaje_payload(
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
    uwu_icc_kills,
    spec_gs_entries,
):
    return {
        "nombre_char": nombre_char,
        "gs": gs,
        "nivel": nivel,
        "raza": raza,
        "clase": clase,
        "spec_display": spec_display,
        "guild_display": guild_display,
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
    )


def _build_dps_embed_from_cache(payload: dict):
    nombre_char = payload["nombre_char"]
    spec_display = payload.get("spec_display", "")
    uwu_rows = payload.get("uwu_rows", [])
    failed_by_mode = payload.get("failed_by_mode", {})

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

    embed = discord.Embed(
        title=f"{nombre_char} - Uwulogs DPS{spec_display}",
        description=table_block + warning_note + failed_note,
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
    interaction: discord.Interaction, *, content=None, embed=None
) -> None:
    last_exc = None
    for attempt in range(4):
        try:
            await interaction.edit_original_response(content=content, embed=embed)
            return
        except discord.HTTPException as exc:
            if getattr(exc, "status", None) != 429:
                raise
            last_exc = exc
            wait_for = _http_retry_after(exc) or min(2**attempt, 8)
            print(f"[WARN] Discord rate limit on edit_original_response, retry in {wait_for:.2f}s")
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
        print(f"[WARN] Discord rate limit on error message send, retry in {wait_for:.2f}s")
        await asyncio.sleep(wait_for)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message)
            else:
                await interaction.response.send_message(message)
        except Exception:
            print("[WARN] Failed to send error message after retry.")


async def _personaje_impl(
    interaction: discord.Interaction, nombre: str, command_name: str
):
    server_name = interaction.guild.name if interaction.guild else "DM"
    print(
        f"[LOG] Comando '{command_name}' usado por {interaction.user} "
        f"para personaje: {nombre} desde servidor: {server_name}"
    )
    try:
        nombre = nombre.capitalize()
        await _safe_defer(interaction)

        personaje_cache_key = _build_personaje_cache_key(nombre)
        cached_payload = get_external_cache(
            "command_personaje", personaje_cache_key, COMMAND_PERSONAJE_TTL
        )
        if isinstance(cached_payload, dict):
            embed_cached = _build_personaje_embed_from_cache(cached_payload)
            await _safe_edit_original_response(interaction, content=None, embed=embed_cached)
            print(f"[INFO] Cache hit /{command_name} para '{nombre}'")
            return

        await _safe_edit_original_response(
            interaction,
            content=f"⏳ Calculando perfil de {nombre}...", embed=None
        )

        loop = asyncio.get_running_loop()

        uwu_icc_task = loop.run_in_executor(
            EXECUTOR, _uwu_icc_bugfix_kills, nombre, UWU_SERVER
        )
        summary_task = loop.run_in_executor(
            EXECUTOR, _fetch_summary, nombre, "Lordaeron"
        )
        gear_task = loop.run_in_executor(
            EXECUTOR, _fetch_gear_data, nombre, "Lordaeron"
        )
        achi_task = loop.run_in_executor(
            EXECUTOR, _fetch_achievements, nombre, "Lordaeron"
        )
        stats_task = loop.run_in_executor(
            EXECUTOR, _fetch_statistics, nombre, "Lordaeron", 15062
        )

        summary, gear_data, achi_payload, stats_rows = await asyncio.gather(
            summary_task, gear_task, achi_task, stats_task
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

        talents = _fetch_specs(nombre, "Lordaeron")
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
            active_specs = ["N/A"]
            inactive_specs = ["N/A"]

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

        for active_spec in active_specs:
            clean_active_spec = str(active_spec or "").strip()
            if not clean_active_spec or clean_active_spec == "N/A":
                continue
            set_external_cache(
                "character_spec_gs",
                "/personaje",
                _build_character_spec_gs_key(nombre_char, clean_active_spec),
                {"character": nombre_char, "spec": clean_active_spec, "gs": gs},
                {"character": nombre_char, "spec": clean_active_spec},
            )

        gs_by_spec = _get_known_gs_by_spec(
            nombre_char,
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
            uwu_icc_kills=None,
            loading_symbol=LOADING_FRAMES[0],
            spec_gs_value=_format_spec_gs_value(spec_gs_entries),
        )
        await _safe_edit_original_response(interaction, content=None, embed=embed_initial)

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
                uwu_icc_kills=None,
                loading_symbol=LOADING_FRAMES[frame_idx % len(LOADING_FRAMES)],
                spec_gs_value=_format_spec_gs_value(spec_gs_entries),
            )
            frame_idx += 1
            await _safe_edit_original_response(interaction, content=None, embed=embed_loading)

        try:
            uwu_icc_kills = await uwu_icc_task
        except Exception:
            uwu_icc_kills = {}

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
        )
        set_external_cache(
            "command_personaje",
            f"/{command_name}",
            personaje_cache_key,
            _serialize_personaje_payload(
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
                uwu_icc_kills,
                spec_gs_entries,
            ),
            {"character": nombre_char, "command": command_name},
        )
        await _safe_edit_original_response(interaction, content=None, embed=embed_final)

    except discord.NotFound:
        return
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
    @discord.app_commands.describe(nombre="Nombre del personaje en Lordaeron.")
    async def personaje(interaction: discord.Interaction, nombre: str):
        await _personaje_impl(interaction, nombre, "personaje")

    @bot.tree.command(
        name="p",
        description="Alias corto de /personaje para consultar un personaje.",
    )
    @discord.app_commands.describe(nombre="Nombre del personaje en Lordaeron.")
    async def p(interaction: discord.Interaction, nombre: str):
        await _personaje_impl(interaction, nombre, "p")

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
                print(f"[INFO] Cache hit /dps para '{nombre}' spec='{spec or ''}'")
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

            uwu_dps_summary = await loop.run_in_executor(
                EXECUTOR,
                _build_uwu_dps_summary,
                nombre_char,
                UWU_SERVER,
                UWU_PDPS_BOSS_ORDER,
                spec,
            )

            if not isinstance(uwu_dps_summary, dict):
                await _safe_edit_original_response(
                    interaction,
                    content="⚠️ No se pudo leer respuesta de UwU Logs.", embed=None
                )
                return

            uwu_rows = uwu_dps_summary.get("rows", [])
            failed_by_mode = uwu_dps_summary.get("failed_by_mode", {})
            if not uwu_rows:
                await _safe_edit_original_response(
                    interaction,
                    content=f"⚠️ No hay datos DPS en UwU Logs para {nombre_char}.",
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
                print(
                    f"[WARN] UwU consultas fallidas para {nombre_char}: "
                    + " | ".join(failed_parts)
                )

            embed = discord.Embed(
                title=f"{nombre_char} - Uwulogs DPS{spec_display}",
                description=table_block + warning_note + failed_note,
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
