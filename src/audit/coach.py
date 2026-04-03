"""
Groq-powered raid-coach narrative generator.

Uses the ``groq`` Python SDK (async client) to turn an :class:`AuditReport`
into a short expert paragraph written from the perspective of a seasoned
WotLK raid leader.

Model selection
───────────────
``llama-3.3-70b-versatile`` is used by default (fast, cheap, strong reasoning).
Override via the ``GROQ_MODEL`` environment variable.

Environment variables
─────────────────────
  GROQ_API_KEY   – required unless passed explicitly
  GROQ_MODEL     – optional model override (default: llama-3.3-70b-versatile)
  GROQ_MAX_TOKENS – maximum response tokens (default: 300)
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import AuditReport, BisGuide

log = logging.getLogger(__name__)

_DEFAULT_MODEL      = "llama-3.3-70b-versatile"
_DEFAULT_MAX_TOKENS = 300

_SYSTEM_PROMPT = """\
Eres un raid leader veterano de World of Warcraft (parche WotLK 3.3.5a en \
servidor Warmane/Lordaeron). Tu rol es el de coach técnico de DPS/tanque. \
Analiza los datos de auditoría del personaje y produce un resumen narrativo \
breve (3–5 oraciones), directo, experto y sin relleno. \
Usa terminología de WoW real (BiS, ArP cap, meta gem, enchant, tier set, etc.). \
Responde SIEMPRE en español. No uses bullet points, sólo prosa.\
"""


def _build_audit_prompt(report: "AuditReport", guide: "BisGuide") -> str:
    """Serialise the audit results into a compact prompt for the LLM."""

    lines: list[str] = [
        f"Personaje: {report.character_name} ({report.spec_name}) – "
        f"Score actual: {report.overall_score}/100",
        f"Nota de prioridad de la guía: {guide.priority_note}",
        "",
    ]

    # Stat caps
    if report.stat_caps:
        lines.append("=== Caps de estadísticas ===")
        for s in report.stat_caps:
            status = "ALCANZADO" if s.is_capped else f"FALTA {s.delta:.0f}"
            lines.append(f"  {s.display_name}: {s.current_value:.0f}/{s.cap_value:.0f} [{status}]")

    # Item issues
    if report.item_issues:
        lines.append("")
        lines.append("=== Problemas de ítem ===")
        for i in report.item_issues[:6]:   # cap to avoid prompt bloat
            lines.append(f"  [{i.severity.value.upper()}] {i.message}")

    # Enchant issues
    if report.enchant_issues:
        lines.append("")
        lines.append("=== Encantamientos faltantes/incorrectos ===")
        for e in report.enchant_issues[:6]:
            lines.append(f"  [{e.severity.value.upper()}] {e.message}")

    # Gem issues
    if report.gem_issues:
        lines.append("")
        lines.append("=== Gemas ===")
        for g in report.gem_issues[:8]:
            lines.append(f"  [{g.severity.value.upper()}] {g.slot}: {g.issue}")

    lines.append("")
    lines.append(
        "Basándote únicamente en los datos anteriores, escribe el resumen del coach."
    )
    return "\n".join(lines)


async def generate_coach_summary(
    report: "AuditReport",
    guide: "BisGuide",
    *,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """
    Call the Groq API and return the narrative coach summary string.

    Parameters
    ----------
    report:
        The :class:`AuditReport` produced by :func:`~src.audit.auditor.audit_character`.
    guide:
        The :class:`BisGuide` used in the audit (for priority context).
    api_key:
        Groq API key.  Falls back to the ``GROQ_API_KEY`` env variable.
    model:
        Groq model ID.  Falls back to ``GROQ_MODEL`` env variable,
        then ``llama-3.3-70b-versatile``.
    max_tokens:
        Max output tokens.  Falls back to ``GROQ_MAX_TOKENS`` env variable,
        then ``300``.

    Returns
    -------
    str
        Narrative text produced by the LLM, or a fallback plain-text
        summary if the API call fails.

    Raises
    ------
    ImportError
        If the ``groq`` package is not installed.
    """
    try:
        from groq import AsyncGroq  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "The 'groq' package is required for coach summaries. "
            "Install it with: pip install groq"
        ) from exc

    resolved_key = api_key or os.getenv("GROQ_API_KEY")
    if not resolved_key:
        raise ValueError(
            "No Groq API key provided.  Set the GROQ_API_KEY environment variable "
            "or pass api_key= to generate_coach_summary()."
        )

    resolved_model = model or os.getenv("GROQ_MODEL", _DEFAULT_MODEL)
    resolved_max   = max_tokens or int(os.getenv("GROQ_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS)))

    client = AsyncGroq(api_key=resolved_key)
    user_prompt = _build_audit_prompt(report, guide)

    log.debug(
        "Calling Groq model %s for %s (%s)",
        resolved_model,
        report.character_name,
        report.spec_name,
    )

    chat_completion = await client.chat.completions.create(
        messages=[
            {"role": "system",  "content": _SYSTEM_PROMPT},
            {"role": "user",    "content": user_prompt},
        ],
        model=resolved_model,
        max_tokens=resolved_max,
        temperature=0.4,   # low variance – we want factual, reproducible output
    )

    content = chat_completion.choices[0].message.content or ""
    return content.strip()


def build_fallback_summary(report: "AuditReport") -> str:
    """
    Plain-text fallback used when the Groq API is unavailable.

    Returns a single compact paragraph without any external calls.
    """
    critical = report.critical_count
    warnings = report.warning_count
    uncapped = [s for s in report.stat_caps if not s.is_capped and s.must_reach]

    parts: list[str] = [
        f"{report.character_name} ({report.spec_name}) – Score {report.overall_score}/100."
    ]

    if critical == 0 and warnings == 0 and not uncapped:
        parts.append("El personaje está completamente optimizado: ítems BiS, gemas épicas y encantamientos correctos.")
    else:
        if uncapped:
            caps_str = ", ".join(
                f"{s.display_name} (falta {s.delta:.0f})" for s in uncapped
            )
            parts.append(f"⚠ Caps no alcanzados: {caps_str}.")
        if critical:
            parts.append(f"{critical} problema(s) crítico(s) requieren atención inmediata.")
        if warnings:
            parts.append(f"{warnings} aviso(s) de optimización detectados.")

    return " ".join(parts)
