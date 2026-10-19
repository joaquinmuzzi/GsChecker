"""/ia: análisis BiS del equipo y resumen de coach por IA (Groq)."""

import asyncio
import os

import discord

from profile_scraper import get_character_stats
from src.audit.bis_guides import (
    GUIDE_REALMS,
    available_guides,
    detect_role,
    is_caster,
    normalize_realm,
)
from src.audit.coach import build_fallback_summary
from src.audit.integration import run_full_audit
from src.audit.models import AuditReport
from src.controller.commands.interactions import (
    _log_command_usage,
    _reply_command_error,
    _safe_defer,
    _safe_edit_original_response,
)
from src.functions.warmane import _fetch_gear_data, _fetch_specs, _fetch_summary
from src.schemas.constants import EXECUTOR
from src.services.character_input import (
    _normalize_character_name,
    _normalize_character_realm,
)
from src.services.tracking import _track_character


def _build_ia_embed(report: AuditReport, nombre_char: str) -> discord.Embed:
    # Si Groq falló, usar el fallback de texto plano
    coach_text = report.coach_summary or build_fallback_summary(report)

    # Color por score
    if report.overall_score >= 80:
        color = 0x57F287  # verde
    elif report.overall_score >= 50:
        color = 0xFEE75C  # amarillo
    else:
        color = 0xED4245  # rojo

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

    embed.set_footer(text="Fuente: Armory Warmane · IA: Groq llama-3.3-70b · /p para resumen completo")
    return embed


def register(bot):
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
            summary_task = loop.run_in_executor(EXECUTOR, _fetch_summary, nombre, realm)
            gear_task = loop.run_in_executor(EXECUTOR, _fetch_gear_data, nombre, realm)
            summary, gear_data = await asyncio.gather(summary_task, gear_task)

            if isinstance(summary, dict) and summary.get("__error__"):
                await _safe_edit_original_response(interaction, content=summary["__error__"], embed=None)
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
            specs_task2 = loop.run_in_executor(EXECUTOR, _fetch_specs, nombre_char, realm)
            stats_task2 = loop.run_in_executor(EXECUTOR, get_character_stats, nombre_char, realm)
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
            report = await run_full_audit(
                char_name=nombre_char,
                server=realm,
                char_class=char_class,
                spec=active_spec,
                stats=char_stats,
                gear_data=gear_data or [],
                generate_summary=True,
                groq_api_key=os.getenv("GROQ_API_KEY"),
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

            embed = _build_ia_embed(report, nombre_char)

            await _safe_edit_original_response(interaction, content=None, embed=embed)

        except Exception as exc:
            await _reply_command_error(interaction, exc, "❌ Error en /ia")
