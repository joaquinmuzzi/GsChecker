import asyncio
import logging

import discord

from src.db.postgres import (
    async_get_external_cache,
    async_get_external_cache_stale,
    async_set_external_cache,
)
from src.schemas.constants import (
    ARMORY_CIRCUIT,
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
)
from src.functions.uwu import (
    _uwu_icc_bugfix_kills,
    _fetch_uwu_performance,
    _build_uwu_dps_summary,
    _fetch_uwu_overview_for_dps,
    _fetch_uwu_recent_logs,
    UWU_DOWN_MESSAGE,
)
from src.functions.embeds import (
    _build_personaje_embed,
    _build_personaje_view,
    _build_uwu_logs_embed,
    _build_uwu_logs_view,
    _format_uwu_dps_table,
    _format_uwu_overview_table,
    _render_table,
)
from src.audit.bis_guides import (
    GUIDE_REALMS,
    available_guides,
    detect_role,
    is_caster,
    normalize_realm,
)
from src.audit.integration import run_full_audit
from src.audit.coach import build_fallback_summary
from src.services.cache_keys import _build_dps_cache_key, _build_personaje_cache_key
from src.services.character_input import (
    DEFAULT_CHARACTER_REALM,
    _normalize_character_name,
    _normalize_character_realm,
)
from src.services.icc_kills import (
    _apply_item_drop_fallback_to_uwu,
    _apply_storming_fallback_to_uwu,
    _finalize_special_uwu_kills,
    _load_confirmed_icc_kills,
    _normalize_special_uwu_kills,
    _resolve_uwu_icc_kills,
)
from src.services.profile import (
    _compute_personaje_base,
    _is_valid_personaje_payload,
    _serialize_personaje_payload,
)
from src.services.spec_gearscore import _format_spec_gs_value
from src.services.tracking import _track_character

logger = logging.getLogger("gschecker.commands")


def _log_command_usage(
    interaction: discord.Interaction,
    command_name: str,
    nombre: str,
    realm: str,
    **extra,
) -> None:
    # Single structured entry per command invocation. Appears in Railway Deploy Logs
    # and in logs/bot.log via the root 'gschecker' logger configured in main.py.
    user = interaction.user
    guild = interaction.guild
    extras = "".join(f" {key}={value!r}" for key, value in extra.items() if value is not None)
    logger.info(
        "command=%s user=%s(%s) guild=%s(%s) character=%r realm=%r%s",
        command_name,
        getattr(user, "name", "unknown"),
        getattr(user, "id", "unknown"),
        getattr(guild, "name", "DM"),
        getattr(guild, "id", "dm"),
        nombre,
        realm,
        extras,
    )


DPS_COMMAND_TIMEOUT_SECONDS = 45
# /p: cuánto se espera a uwu-logs para las kills de Marrowgar/Deathwhisper
# antes de mostrar el estado final con "?" en lo que falte.
PERSONAJE_UWU_WAIT_SECONDS = 25
# /p: cuánto después de la edición final se relee el mensaje para confirmar
# que Discord se quedó con el embed final y no con uno de carga.
PERSONAJE_FINAL_CHECK_SECONDS = 3.0


def _build_personaje_embed_from_cache(payload: dict, loading_symbol: str = "?"):
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
        loading_symbol=loading_symbol,
        spec_gs_value=_format_spec_gs_value(payload.get("spec_gs_entries", [])),
        guild_rank=payload.get("guild_rank"),
        professions=payload.get("professions"),
        active_spec_name=payload.get("active_spec_name"),
        suboptimal_gems=payload.get("suboptimal_gems"),
        uwu_performance=payload.get("uwu_performance"),
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
        failed_note = "\n⚠️ Consultas UwU fallidas por mode: " + " | ".join(
            failed_parts
        )

    timeout_note = ""
    if timed_out:
        timeout_note = (
            "\n⚠️ Resultado parcial: se alcanzó el tiempo límite de consulta."
        )

    # Bloque de overview (rank/points/dps por boss) almacenado en caché
    uwu_overview = payload.get("uwu_overview")
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


async def _safe_defer(interaction: discord.Interaction) -> None:
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(thinking=True)
    except discord.HTTPException as exc:
        if getattr(exc, "code", None) != 40060:
            raise
        # Otro proceso con el mismo token ya respondió esta interacción: los
        # dos editarían el mismo mensaje.
        logger.warning("defer: interacción ya respondida (40060): %s", exc)


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


def _is_expired_token(exc: discord.HTTPException) -> bool:
    return getattr(exc, "status", None) == 401 and getattr(exc, "code", None) == 50027


async def _safe_edit_original_response(
    interaction: discord.Interaction, *, content=None, embed=None, view=None
):
    """Devuelve el mensaje que respondió Discord, o None si no se pudo editar."""
    last_exc = None
    for attempt in range(4):
        try:
            kwargs = {"content": content, "embed": embed}
            if view is not None:
                kwargs["view"] = view
            return await interaction.edit_original_response(**kwargs)
        except discord.NotFound:
            logger.warning(
                "edit_original_response NotFound (mensaje o interacción inexistente) "
                "command=%s", getattr(getattr(interaction, "command", None), "name", "?"),
            )
            return
        except discord.HTTPException as exc:
            if _is_expired_token(exc):
                logger.warning("edit_original_response con token vencido: %s", exc)
                return
            if getattr(exc, "status", None) != 429:
                raise
            last_exc = exc
            wait_for = _http_retry_after(exc) or min(2**attempt, 8)
            await asyncio.sleep(wait_for)
    if last_exc:
        raise last_exc


def _embed_fields_signature(embed) -> list[tuple[str, str]]:
    # Discord recorta espacios al final de los valores: se comparan sin ellos.
    return [(str(f.name), " ".join(str(f.value).split())) for f in embed.fields]


def _message_has_embed(message, embed: discord.Embed) -> bool:
    embeds = getattr(message, "embeds", None) or []
    return bool(embeds) and _embed_fields_signature(embeds[0]) == _embed_fields_signature(
        embed
    )


async def _ensure_final_edit_landed(
    interaction: discord.Interaction, embed: discord.Embed, view, patched=None
) -> None:
    """/p Kuvez (2026-10-07): Discord aceptó la edición final sin error (el
    edited_timestamp del mensaje es de ese momento) pero el mensaje quedó con
    el embed de carga (⌛). Se relee el mensaje y, si no tiene el embed final,
    se lo vuelve a mandar una vez. `patched` es la respuesta de Discord a la
    edición final: el log dice si ya venía mal o si se pisó después."""
    try:
        await asyncio.sleep(PERSONAJE_FINAL_CHECK_SECONDS)
        message = await interaction.original_response()
        if _message_has_embed(message, embed):
            return
        stored = message.embeds[0] if message.embeds else None
        stored_text = (
            " ".join(str(f.value) for f in stored.fields) if stored else message.content
        )
        logger.warning(
            "final edit not kept by Discord edited_at=%s loading=%s content=%r "
            "patch_response_final=%s patch_edited_at=%s — re-sending",
            message.edited_at,
            any(frame in str(stored_text) for frame in LOADING_FRAMES),
            message.content,
            _message_has_embed(patched, embed),
            getattr(patched, "edited_at", None),
        )
        await _safe_edit_original_response(
            interaction, content=None, embed=embed, view=view
        )
    except discord.NotFound:
        return
    except Exception as exc:
        if isinstance(exc, discord.HTTPException) and _is_expired_token(exc):
            return
        logger.exception("final edit check failed")


async def _safe_send_error(interaction: discord.Interaction, message: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message)
        else:
            await interaction.response.send_message(message)
    except discord.NotFound:
        return
    except discord.HTTPException as exc:
        if _is_expired_token(exc):
            return
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
            logger.exception("_safe_send_error: retry send failed")


async def _personaje_impl(
    interaction: discord.Interaction,
    nombre: str,
    command_name: str,
    reino: str | None = None,
):
    try:
        nombre = _normalize_character_name(nombre)
        realm = _normalize_character_realm(reino)
        _log_command_usage(interaction, command_name, nombre, realm)
        await _safe_defer(interaction)

        personaje_cache_key = f"{_build_personaje_cache_key(nombre)}:{realm.lower()}"
        cached_payload = await async_get_external_cache(
            "command_personaje", personaje_cache_key, COMMAND_PERSONAJE_TTL
        )
        if isinstance(cached_payload, dict):
            # Un payload cacheado ya pasó _is_valid_personaje_payload (existe y es 80).
            _track_character(cached_payload["nombre_char"], realm)
            if not (cached_payload.get("uwu_performance") or {}).get("rank"):
                # Perfil cacheado sin ranking de uwu-logs (de antes de que /p lo
                # mostrara, o uwu-logs no respondió cuando corrió el cron; dura
                # hasta 25 h): se pide solo el ranking (~1 s, sin armory). No se
                # re-guarda para no estirar el TTL de los datos del armory.
                try:
                    cached_payload["uwu_performance"] = await asyncio.wait_for(
                        asyncio.get_running_loop().run_in_executor(
                            EXECUTOR,
                            _fetch_uwu_performance,
                            cached_payload.get("nombre_char", nombre),
                            realm,
                            cached_payload.get("clase"),
                        ),
                        timeout=10.0,
                    )
                except Exception:
                    logger.warning(
                        "uwu performance fetch failed for cached '%s'/%s", nombre, realm
                    )
            embed_cached = _build_personaje_embed_from_cache(cached_payload)
            view_cached = _build_personaje_view(
                cached_payload["nombre_char"],
                cached_payload.get("server", DEFAULT_CHARACTER_REALM),
            )
            await _safe_edit_original_response(
                interaction, content=None, embed=embed_cached, view=view_cached
            )
            return

        if ARMORY_CIRCUIT.is_open():
            stale_payload = await async_get_external_cache_stale(
                "command_personaje", personaje_cache_key
            )
            if isinstance(stale_payload, dict):
                logger.warning(
                    "Armory circuit open — serving stale DB cache for '%s'/%s",
                    nombre,
                    realm,
                )
                _track_character(stale_payload["nombre_char"], realm)
                embed_stale = _build_personaje_embed_from_cache(stale_payload)
                view_stale = _build_personaje_view(
                    stale_payload["nombre_char"],
                    stale_payload.get("server", DEFAULT_CHARACTER_REALM),
                )
                await _safe_edit_original_response(
                    interaction, content=None, embed=embed_stale, view=view_stale
                )
                return
            logger.warning(
                "Armory circuit open and no stale cache for '%s'/%s — showing error",
                nombre,
                realm,
            )
            await _safe_edit_original_response(
                interaction,
                content=f"⚠️ El armory de Warmane está rate-limitado. Intenta de nuevo en ~60s.",
                embed=None,
            )
            return

        await _safe_edit_original_response(
            interaction,
            content=f"⏳ Calculando perfil de {nombre} en {realm}...",
            embed=None,
        )

        loop = asyncio.get_running_loop()
        started_at = loop.time()

        # Summary primero: si el personaje no existe o no es 80 se responde en
        # segundos, sin gastar ~15 requests del armory en logros/estadísticas.
        summary = await loop.run_in_executor(EXECUTOR, _fetch_summary, nombre, realm)

        if isinstance(summary, dict) and summary.get("__error__"):
            await _safe_edit_original_response(
                interaction, content=summary["__error__"], embed=None
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

        if nivel != 80:
            await _safe_edit_original_response(
                interaction,
                content=f"⚠️ **{nombre_char}** no es nivel 80.",
                embed=None,
            )
            return

        _track_character(nombre_char, realm)

        # uwu-logs en paralelo con el resto del armory. Va después del summary
        # porque usa la clase del armory cuando uwu-logs no tiene perfil.
        uwu_icc_task = loop.run_in_executor(
            EXECUTOR,
            _uwu_icc_bugfix_kills,
            nombre_char,
            realm,
            summary.get("class"),
        )

        gear_data, achi_payload, stats_rows, professions, talents = await asyncio.gather(
            loop.run_in_executor(EXECUTOR, _fetch_gear_data, nombre_char, realm),
            loop.run_in_executor(EXECUTOR, _fetch_achievements, nombre_char, realm),
            loop.run_in_executor(EXECUTOR, _fetch_statistics, nombre_char, realm, 15062),
            loop.run_in_executor(EXECUTOR, _fetch_professions, nombre_char, realm),
            loop.run_in_executor(EXECUTOR, _fetch_specs, nombre_char, realm),
        )

        base = await asyncio.to_thread(
            _compute_personaje_base,
            {**summary, "name": nombre_char},
            realm,
            gear_data,
            achi_payload,
            stats_rows,
            professions,
            talents,
            "/personaje",
        )

        # Cargar kills confirmadas del DB antes del embed inicial,
        # así los ✅ ya guardados aparecen de inmediato sin loading.
        persistent_confirmed = await asyncio.to_thread(_load_confirmed_icc_kills, nombre_char, realm)
        # Storming the Citadel y los ítems del boss ya confirman kills: se
        # muestran ✅ desde el primer embed, sin esperar a uwu-logs.
        initial_kills = _apply_item_drop_fallback_to_uwu(
            _apply_storming_fallback_to_uwu(
                _normalize_special_uwu_kills(dict(persistent_confirmed)), achi_payload
            ),
            gear_data,
        )
        initial_payload = _serialize_personaje_payload(**base, uwu_icc_kills=initial_kills)

        personaje_view = _build_personaje_view(nombre_char, realm)
        await _safe_edit_original_response(
            interaction,
            content=None,
            embed=_build_personaje_embed_from_cache(
                initial_payload, loading_symbol=LOADING_FRAMES[0]
            ),
            view=personaje_view,
        )

        frame_idx = 1
        uwu_deadline = loop.time() + PERSONAJE_UWU_WAIT_SECONDS
        while not uwu_icc_task.done() and loop.time() < uwu_deadline:
            await asyncio.sleep(2.0)
            if uwu_icc_task.done():
                break
            embed_loading = _build_personaje_embed_from_cache(
                initial_payload,
                loading_symbol=LOADING_FRAMES[frame_idx % len(LOADING_FRAMES)],
            )
            frame_idx += 1
            await _safe_edit_original_response(
                interaction, content=None, embed=embed_loading, view=personaje_view
            )

        if not uwu_icc_task.done():
            # uwu-logs no terminó a tiempo: esos modos quedan en "?" (sigue
            # corriendo de fondo y deja la caché lista para el próximo /p).
            logger.warning(
                "uwu icc kills timeout (%ss) for '%s'/%s",
                PERSONAJE_UWU_WAIT_SECONDS, nombre_char, realm,
            )
            raw_uwu_kills = {}
        else:
            try:
                raw_uwu_kills = uwu_icc_task.result()
            except Exception:
                logger.exception(
                    "uwu icc kills fetch failed for '%s'/%s", nombre_char, realm
                )
                raw_uwu_kills = {}

        try:
            uwu_icc_kills = await asyncio.to_thread(
                _resolve_uwu_icc_kills,
                nombre_char,
                realm,
                raw_uwu_kills,
                persistent_confirmed,
                achi_payload,
                gear_data,
            )
        except Exception:
            logger.exception("icc kills resolve failed for '%s'/%s", nombre_char, realm)
            uwu_icc_kills = _finalize_special_uwu_kills(initial_kills)
        try:
            # Después de las kills: reusa los /character que ya quedaron en caché.
            uwu_performance = await asyncio.wait_for(
                loop.run_in_executor(
                    EXECUTOR,
                    _fetch_uwu_performance,
                    nombre_char,
                    realm,
                    summary.get("class"),
                ),
                timeout=10.0,
            )
        except Exception:
            logger.exception(
                "uwu performance fetch failed for '%s'/%s", nombre_char, realm
            )
            uwu_performance = None

        _payload_to_cache = _serialize_personaje_payload(
            **base, uwu_icc_kills=uwu_icc_kills, uwu_performance=uwu_performance
        )
        embed_final = _build_personaje_embed_from_cache(_payload_to_cache)
        if _is_valid_personaje_payload(_payload_to_cache):
            try:
                await asyncio.wait_for(
                    async_set_external_cache(
                        "command_personaje",
                        f"/{command_name}",
                        personaje_cache_key,
                        _payload_to_cache,
                        {"character": nombre_char, "command": command_name, "server": realm},
                    ),
                    timeout=10.0,
                )
            except Exception:
                logger.exception("personaje cache write failed for '%s'/%s", nombre_char, realm)
        else:
            logger.warning(
                "Skipping cache write for '%s'/%s — payload failed validation",
                nombre_char,
                realm,
            )
            if not _payload_to_cache["data_complete"]:
                # Mejor mostrar el último perfil bueno que ❌ falsos por un 429.
                stale_payload = await async_get_external_cache_stale(
                    "command_personaje", personaje_cache_key
                )
                if isinstance(stale_payload, dict):
                    logger.warning(
                        "Armory respondió incompleto — serving stale DB cache for '%s'/%s",
                        nombre_char,
                        realm,
                    )
                    embed_final = _build_personaje_embed_from_cache(stale_payload)
        patched = await _safe_edit_original_response(
            interaction, content=None, embed=embed_final, view=personaje_view
        )
        logger.info(
            "personaje done character='%s' realm='%s' elapsed=%.1fs",
            nombre_char, realm, loop.time() - started_at,
        )
        await _ensure_final_edit_landed(
            interaction, embed_final, personaje_view, patched
        )

    except discord.NotFound:
        return
    except discord.HTTPException as e:
        if _is_expired_token(e):
            return
        await _safe_send_error(interaction, f"❌ Error de red: {e}")
    except ValueError as e:
        await _safe_send_error(interaction, str(e))
    except Exception as e:
        logger.exception("personaje failed for '%s'", nombre)
        await _safe_send_error(interaction, f"❌ Error al obtener datos: {e}")


def register_commands(bot):
    @bot.tree.command(name="ping", description="Muestra la latencia actual del bot.")
    async def ping(interaction: discord.Interaction):
        _log_command_usage(interaction, "ping", "-", "-")
        latency = bot.latency
        if not isinstance(latency, float) or latency != latency or latency < 0:
            latency_display = "n/a"
        else:
            latency_display = f"{round(latency * 1000)}ms"
        await interaction.response.send_message(f"Pong! Latencia: {latency_display}")

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
                failed_note = "\n⚠️ Consultas UwU fallidas por mode: " + " | ".join(
                    failed_parts
                )

            timeout_note = ""
            if timed_out:
                timeout_note = (
                    "\n⚠️ Resultado parcial: se alcanzó el tiempo límite de consulta."
                )

            # --- Bloque de overview (va encima de la tabla DPS) ---
            overview_prefix = ""
            if uwu_overview and uwu_overview.get("rows"):
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

        except discord.NotFound:
            return
        except discord.HTTPException as e:
            if _is_expired_token(e):
                return
            await _safe_send_error(interaction, f"❌ Error de red: {e}")
        except ValueError as e:
            await _safe_send_error(interaction, str(e))
        except Exception as e:
            await _safe_send_error(interaction, f"❌ Error al obtener DPS: {e}")

    @bot.tree.command(
        name="logs",
        description="Últimos reportes de UwU Logs donde aparece el personaje.",
    )
    @discord.app_commands.describe(
        nombre="Nombre del personaje.",
        reino="Reino opcional. Por defecto: Lordaeron.",
    )
    async def logs(
        interaction: discord.Interaction,
        nombre: str,
        reino: str | None = None,
    ):
        try:
            nombre = _normalize_character_name(nombre)
            realm = _normalize_character_realm(reino)
            _log_command_usage(interaction, "logs", nombre, realm)
            await _safe_defer(interaction)
            await _safe_edit_original_response(
                interaction,
                content=f"⏳ Buscando logs de **{nombre}** en UwU Logs...",
                embed=None,
            )

            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(
                EXECUTOR, _fetch_uwu_recent_logs, nombre, realm
            )
            if data is None:
                await _safe_edit_original_response(
                    interaction, content=UWU_DOWN_MESSAGE, embed=None
                )
                return
            if not data.get("reports"):
                await _safe_edit_original_response(
                    interaction,
                    content=f"⚠️ No hay logs en UwU Logs para {nombre} en {realm}.",
                    embed=None,
                )
                return

            await _safe_edit_original_response(
                interaction,
                content=None,
                embed=_build_uwu_logs_embed(nombre, realm, data),
                view=_build_uwu_logs_view(nombre, realm),
            )

        except discord.NotFound:
            return
        except discord.HTTPException as e:
            if _is_expired_token(e):
                return
            await _safe_send_error(interaction, f"❌ Error de red: {e}")
        except ValueError as e:
            await _safe_send_error(interaction, str(e))
        except Exception as e:
            await _safe_send_error(interaction, f"❌ Error al obtener datos: {e}")

    @bot.tree.command(
        name="ptoc",
        description="Muestra logros de Trial of the Crusader (TOC) en formato tabla.",
    )
    @discord.app_commands.describe(nombre="Nombre del personaje en Lordaeron.")
    async def ptoc(interaction: discord.Interaction, nombre: str):
        try:
            nombre = _normalize_character_name(nombre)
            _log_command_usage(interaction, "ptoc", nombre, "Lordaeron")
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
        except discord.HTTPException as e:
            if _is_expired_token(e):
                return
            await _safe_send_error(interaction, f"❌ Error de red: {e}")
        except ValueError as e:
            await _safe_send_error(interaction, str(e))
        except Exception as e:
            await _safe_send_error(interaction, f"❌ Error al obtener datos: {e}")

    @bot.tree.command(
        name="ia",
        description="Análisis BiS + resumen de coach por IA (Groq) para el personaje.",
    )
    @discord.app_commands.describe(
        nombre="Nombre del personaje.",
        reino="Reino opcional. Por defecto: Lordaeron.",
    )
    async def ia(
        interaction: discord.Interaction,
        nombre: str,
        reino: str | None = None,
    ):
        try:
            nombre = _normalize_character_name(nombre)
            realm = _normalize_character_realm(reino)
            _log_command_usage(interaction, "ia", nombre, realm)
            await _safe_defer(interaction)

            if normalize_realm(realm) is None:
                await _safe_edit_original_response(
                    interaction,
                    content=(
                        f"⚠️ Todavía no hay guías BiS para {realm}: solo para "
                        f"{' e '.join(GUIDE_REALMS)}, armadas con lo que usan los "
                        "mejores jugadores de cada reino."
                    ),
                    embed=None,
                )
                return

            await _safe_edit_original_response(
                interaction,
                content=f"⏳ Analizando a **{nombre}** en {realm} con IA...",
                embed=None,
            )

            loop = asyncio.get_running_loop()

            # Fetch summary (class + spec) y gear en paralelo
            summary_task = loop.run_in_executor(
                EXECUTOR, _fetch_summary, nombre, realm
            )
            gear_task = loop.run_in_executor(
                EXECUTOR, _fetch_gear_data, nombre, realm
            )
            summary, gear_data = await asyncio.gather(summary_task, gear_task)

            if isinstance(summary, dict) and summary.get("__error__"):
                await _safe_edit_original_response(
                    interaction, content=summary["__error__"], embed=None
                )
                return

            if not isinstance(summary, dict):
                await _safe_edit_original_response(
                    interaction,
                    content="⚠️ No se pudo obtener información del personaje en Armory.",
                    embed=None,
                )
                return

            nivel = summary.get("level", 0)
            if nivel != 80:
                await _safe_edit_original_response(
                    interaction,
                    content=f"⚠️ **{nombre}** no es nivel 80.",
                    embed=None,
                )
                return

            char_class = str(summary.get("class") or "")
            nombre_char = str(summary.get("name") or nombre)
            _track_character(nombre_char, realm)

            # Determinar spec activa y stats del personaje en paralelo
            from profile_scraper import get_character_stats as _ps_get_char_stats
            specs_task2 = loop.run_in_executor(
                EXECUTOR, _fetch_specs, nombre_char, realm
            )
            stats_task2 = loop.run_in_executor(
                EXECUTOR, _ps_get_char_stats, nombre_char, realm
            )
            specs_raw, raw_stats = await asyncio.gather(specs_task2, stats_task2)

            active_spec = ""
            if isinstance(specs_raw, list):
                for t in specs_raw:
                    if isinstance(t, dict) and t.get("active"):
                        active_spec = str(t.get("name") or "")
                        break
                if not active_spec and specs_raw:
                    active_spec = str(specs_raw[0].get("name") or "")

            # Casters: el hit que importa es el de la sección Spell. Se decide por
            # clase + spec ("Frost" es caster para Mage pero no para Death Knight).
            char_stats: dict = dict(raw_stats or {})
            spell_hit = char_stats.pop("spell_hit_rating", None)
            if is_caster(char_class, active_spec) and spell_hit is not None:
                char_stats["hit_rating"] = spell_hit
            role = detect_role(char_class, active_spec, char_stats)

            # Ejecutar auditoría + Groq
            import os as _os
            report = await run_full_audit(
                char_name=nombre_char,
                server=realm,
                char_class=char_class,
                spec=active_spec,
                stats=char_stats,
                gear_data=gear_data or [],
                generate_summary=True,
                groq_api_key=_os.getenv("GROQ_API_KEY"),
                role=role,
            )

            if report is None:
                await _safe_edit_original_response(
                    interaction,
                    content=(
                        f"⚠️ Todavía no hay suficientes jugadores de **{char_class} "
                        f"{active_spec}{f' ({role})' if role else ''}** con buen equipo "
                        f"en {realm} para armar su BiS.\n"
                        f"Hay guías para {len(available_guides(realm))} specs de {realm}."
                    ),
                    embed=None,
                )
                return

            # Si Groq falló, usar el fallback de texto plano
            coach_text = report.coach_summary or build_fallback_summary(report)

            # Color por score
            if report.overall_score >= 80:
                color = 0x57F287   # verde
            elif report.overall_score >= 50:
                color = 0xFEE75C   # amarillo
            else:
                color = 0xED4245   # rojo

            embed = discord.Embed(
                title=f"🤖 Análisis IA · {nombre_char} ({report.spec_name})",
                color=color,
            )
            embed.add_field(
                name=(
                    f"Score: {report.overall_score}/100  |  "
                    f"{report.critical_count} crítico(s) · {report.warning_count} aviso(s)"
                ),
                value=coach_text[:1020] if coach_text else "Sin análisis disponible.",
                inline=False,
            )

            # Caps de estadísticas compactos
            if report.stat_caps:
                cap_lines = []
                for s in report.stat_caps:
                    if s.is_capped:
                        icon = "✅"
                    elif s.must_reach:
                        icon = "❌"
                    else:
                        icon = "ℹ️"
                    line = f"{icon} **{s.display_name}**: {s.current_value:.0f}/{s.cap_value:.0f}"
                    if not s.is_capped and s.must_reach:
                        line += f" *(falta {s.delta:.0f})*"
                    cap_lines.append(line)
                embed.add_field(
                    name="Caps de estadísticas",
                    value="\n".join(cap_lines),
                    inline=False,
                )

            # Resumen rápido de problemas críticos
            crit_lines = (
                [f"• {i.message}" for i in report.item_issues if i.severity.value == "critical"]
                + [f"• {e.message}" for e in report.enchant_issues if e.severity.value == "critical"]
                + [f"• {g.slot}: {g.issue}" for g in report.gem_issues if g.severity.value == "critical"]
            )
            if crit_lines:
                embed.add_field(
                    name="🚨 Críticos",
                    value="\n".join(crit_lines[:8])[:1020],
                    inline=False,
                )

            embed.set_footer(
                text="Fuente: Armory Warmane · IA: Groq llama-3.3-70b · /p para resumen completo"
            )

            await _safe_edit_original_response(
                interaction, content=None, embed=embed
            )

        except discord.NotFound:
            return
        except discord.HTTPException as e:
            if _is_expired_token(e):
                return
            await _safe_send_error(interaction, f"❌ Error de red: {e}")
        except ValueError as e:
            await _safe_send_error(interaction, str(e))
        except Exception as e:
            await _safe_send_error(interaction, f"❌ Error en /ia: {e}")
