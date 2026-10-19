"""/dps: DPS máximo y promedio por boss desde UwU Logs."""

import asyncio

import discord

from src.controller.commands.interactions import (
    _log_command_usage,
    _reply_command_error,
    _safe_defer,
    _safe_edit_original_response,
)
from src.db.postgres import async_get_external_cache, async_set_external_cache
from src.functions.embeds import _format_uwu_dps_table, _format_uwu_overview_table
from src.functions.uwu import _build_uwu_dps_summary, _fetch_uwu_overview_for_dps
from src.functions.warmane import _fetch_summary
from src.schemas.constants import (
    COMMAND_DPS_TTL,
    DOCS_NOTAS_URL,
    EXECUTOR,
    UWU_MODES_ALL,
    UWU_PDPS_BOSS_ORDER,
    UWU_SERVER,
)
from src.services.cache_keys import _build_dps_cache_key
from src.services.character_input import _normalize_character_name
from src.services.tracking import _track_character

DPS_COMMAND_TIMEOUT_SECONDS = 45


def _group_rows_by_boss(rows: list[dict]) -> list[dict]:
    """Intercala una fila separadora entre bosses y saca la clave interna `_boss`
    de las filas (las modifica)."""
    grouped_rows = []
    for i, row in enumerate(rows):
        grouped_rows.append(row)
        is_last = i == len(rows) - 1
        if is_last:
            continue
        current_boss = row.get("_boss")
        next_boss = rows[i + 1].get("_boss")
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
    return grouped_rows


def _build_dps_embed(
    nombre_char: str,
    spec: str | None,
    spec_display: str,
    grouped_rows: list[dict],
    failed_by_mode,
    timed_out: bool,
    uwu_overview,
) -> discord.Embed:
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
        failed_note = "\n⚠️ Consultas UwU fallidas por mode: " + " | ".join(
            failed_parts
        )

    timeout_note = ""
    if timed_out:
        timeout_note = (
            "\n⚠️ Resultado parcial: se alcanzó el tiempo límite de consulta."
        )

    # Bloque de overview (rank/points/dps por boss), encima de la tabla DPS
    overview_prefix = ""
    if isinstance(uwu_overview, dict) and uwu_overview.get("rows"):
        overview_table = _format_uwu_overview_table(uwu_overview["rows"])
        overall_pts = uwu_overview.get("overall_points", "?")
        overview_prefix = (
            f"**Overall: {overall_pts} pts**\n"
            f"```\n{overview_table}\n```\n"
        )

    embed = discord.Embed(
        title=f"{nombre_char} - Uwulogs DPS{spec_display}",
        description=overview_prefix + table_block + warning_note + failed_note + timeout_note,
        color=0x2B2D31,
    )
    embed.add_field(
        name="Si ves datos vacíos, consulte:",
        value=DOCS_NOTAS_URL,
        inline=True,
    )
    return embed


def _build_dps_embed_from_cache(payload: dict):
    nombre_char = payload["nombre_char"]
    # Copias, como antes: armar el embed no modifica el payload.
    rows = [dict(row) for row in payload.get("uwu_rows", [])]
    return _build_dps_embed(
        nombre_char,
        payload.get("spec"),
        payload.get("spec_display", ""),
        _group_rows_by_boss(rows),
        payload.get("failed_by_mode", {}),
        bool(payload.get("timed_out", False)),
        payload.get("uwu_overview"),
    )


def register(bot):
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
        try:
            nombre = _normalize_character_name(nombre)
            _log_command_usage(interaction, "dps", nombre, "Lordaeron", spec=spec)
            spec_display = f" [{spec.upper()}]" if spec else ""
            await _safe_defer(interaction)

            dps_cache_key = _build_dps_cache_key(nombre, spec)
            cached_payload = await async_get_external_cache(
                "command_dps", dps_cache_key, COMMAND_DPS_TTL
            )
            if isinstance(cached_payload, dict):
                embed_cached = _build_dps_embed_from_cache(cached_payload)
                await _safe_edit_original_response(
                    interaction, content=None, embed=embed_cached
                )
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
            # /dps no exige nivel 80, pero el cron solo puede precargar a los 80.
            if summary.get("level") == 80:
                _track_character(nombre_char, "Lordaeron")

            # --- Fase 1: overview rápido (rank/points/dps por boss) ---
            overview_future = loop.run_in_executor(
                EXECUTOR,
                _fetch_uwu_overview_for_dps,
                nombre_char,
                UWU_SERVER,
                spec,
            )
            try:
                uwu_overview = await asyncio.wait_for(overview_future, timeout=12.0)
            except asyncio.TimeoutError:
                uwu_overview = None

            if uwu_overview and uwu_overview.get("rows"):
                overview_table = _format_uwu_overview_table(uwu_overview["rows"])
                overview_block = f"```\n{overview_table}\n```"
                overall_pts = uwu_overview.get("overall_points", "?")
                overview_embed = discord.Embed(
                    title=f"{nombre_char} - UwU Overview{spec_display}",
                    description=(
                        f"**Overall: {overall_pts} pts**\n"
                        + overview_block
                        + "\n⏳ Calculando tabla DPS detallada..."
                    ),
                    color=0x2B2D31,
                )
                await _safe_edit_original_response(
                    interaction, content=None, embed=overview_embed
                )

            # --- Fase 2: tabla DPS detallada ---
            uwu_dps_future = loop.run_in_executor(
                EXECUTOR,
                _build_uwu_dps_summary,
                nombre_char,
                UWU_SERVER,
                UWU_PDPS_BOSS_ORDER,
                spec,
                30.0,
                summary.get("class"),
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
                    content="⚠️ No se pudo leer respuesta de UwU Logs.",
                    embed=None,
                )
                return

            uwu_rows = uwu_dps_summary.get("rows", [])
            failed_by_mode = uwu_dps_summary.get("failed_by_mode", {})
            timed_out = bool(uwu_dps_summary.get("timed_out", False))
            if uwu_dps_summary.get("uwu_down"):
                await _safe_edit_original_response(
                    interaction,
                    content=uwu_dps_summary.get("__error__"),
                    embed=None,
                )
                return
            if not uwu_rows:
                timeout_note = " (cálculo parcial por timeout)" if timed_out else ""
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

            # Sin copias, como antes: las filas que se guardan en caché (y las de
            # la caché en memoria de uwu.py) quedan sin `_boss`, así que un /dps
            # servido desde caché sale sin las líneas separadoras entre bosses.
            embed = _build_dps_embed(
                nombre_char,
                spec,
                spec_display,
                _group_rows_by_boss(uwu_rows),
                failed_by_mode,
                timed_out,
                uwu_overview,
            )
            await async_set_external_cache(
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
                    "uwu_overview": uwu_overview,
                },
                {"character": nombre_char, "spec": spec or ""},
            )
            await _safe_edit_original_response(interaction, content=None, embed=embed)

        except Exception as exc:
            await _reply_command_error(interaction, exc, "❌ Error al obtener DPS")
