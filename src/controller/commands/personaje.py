"""/personaje y su alias /p: el resumen completo de un personaje."""

import asyncio
import logging

import discord

from src.controller.commands.interactions import (
    _is_expired_token,
    _log_command_usage,
    _message_has_embed,
    _safe_defer,
    _safe_edit_original_response,
    _safe_send_error,
)
from src.db.postgres import (
    async_get_external_cache,
    async_get_external_cache_stale,
    async_set_external_cache,
)
from src.functions.embeds import _build_personaje_embed, _build_personaje_view
from src.functions.uwu import _fetch_uwu_performance, _uwu_icc_bugfix_kills
from src.functions.warmane import (
    _fetch_achievements,
    _fetch_gear_data,
    _fetch_professions,
    _fetch_specs,
    _fetch_statistics,
    _fetch_summary,
)
from src.schemas.constants import (
    ARMORY_CIRCUIT,
    COMMAND_PERSONAJE_TTL,
    EXECUTOR,
    LOADING_FRAMES,
)
from src.services.cache_keys import _build_personaje_cache_key
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

# Mismo logger que antes del split: los logs de Railway no cambian.
logger = logging.getLogger("gschecker.commands")

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


def register(bot):
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
