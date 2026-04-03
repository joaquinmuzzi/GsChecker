"""
Core audit engine for GsChecker.

``audit_character`` is the single entry-point.  It is **async** to stay
compatible with the Discord bot's event loop, even though the heavy lifting is
purely in-memory / CPU-bound (no I/O inside this module).

Scoring rubric (starts at 100, penalties applied)
───────────────────────────────────────────────────
  Item not in acceptable list  → −8 pts  (CRITICAL)
  Empty/missing enchant        → −6 pts  (CRITICAL)
  Wrong enchant id             → −4 pts  (WARNING)
  Non-epic gem                 → −3 pts  (WARNING)
  Missing required gem (count) → −5 pts  (CRITICAL) per missing unit
  Stat cap not reached         → −7 pts  (CRITICAL) per uncapped must-reach stat
  Stat cap overcapped (>20 %)  → −2 pts  (WARNING)  per over-capped optional stat
"""

from __future__ import annotations

import logging
from collections import Counter

from .models import (
    AuditReport,
    AuditSeverity,
    BisGuide,
    CharacterData,
    EnchantAuditIssue,
    GemAuditIssue,
    ItemAuditIssue,
    StatCapAuditResult,
)

log = logging.getLogger(__name__)

# ── constants pulled from profile_scraper at runtime (lazy import) ────────────
_gem_by_enchant: dict | None = None
_wotlk_epic_gems: frozenset[str] | None = None
_meta_gem_ids: frozenset[str] | None = None


def _get_gem_lookups() -> tuple[dict, frozenset[str], frozenset[str]]:
    """Lazily import heavy profile_scraper globals (avoids circular imports)."""
    global _gem_by_enchant, _wotlk_epic_gems, _meta_gem_ids
    if _gem_by_enchant is None:
        try:
            import profile_scraper as ps  # noqa: PLC0415
            _gem_by_enchant  = ps._load_gem_by_enchant()
            _wotlk_epic_gems = ps._WOTLK_EPIC_GEMS
            _meta_gem_ids    = ps.META_GEM_IDS
        except Exception as exc:
            log.warning("Could not import profile_scraper gem data: %s", exc)
            _gem_by_enchant  = {}
            _wotlk_epic_gems = frozenset()
            _meta_gem_ids    = frozenset()
    return _gem_by_enchant, _wotlk_epic_gems, _meta_gem_ids  # type: ignore[return-value]


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_gem_item_id(enchant_id: str) -> str | None:
    """Map an armory enchant ID back to the gem item ID, or None if unknown."""
    gem_by_enchant, _, _ = _get_gem_lookups()
    info = gem_by_enchant.get(str(enchant_id))
    return info["item_id"] if info else None


def _is_meta_enchant_id(enchant_id: str) -> bool:
    """Return True if *enchant_id* corresponds to a meta gem."""
    gem_by_enchant, _, meta_ids = _get_gem_lookups()
    info = gem_by_enchant.get(str(enchant_id))
    if info is None:
        return str(enchant_id) in meta_ids
    return info.get("meta", False) or info["item_id"] in meta_ids


def _gem_name_from_enchant(enchant_id: str) -> str:
    gem_by_enchant, _, _ = _get_gem_lookups()
    info = gem_by_enchant.get(str(enchant_id))
    if info:
        eff = info.get("effect", "")
        return f"{info['name']} ({eff})" if eff else info["name"]
    return f"gem:{enchant_id}"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 – item comparison
# ─────────────────────────────────────────────────────────────────────────────

def _audit_items(
    char: CharacterData,
    guide: BisGuide,
) -> tuple[list[ItemAuditIssue], int]:
    """Return (issues, total_penalty)."""
    issues: list[ItemAuditIssue] = []
    penalty = 0
    items_by_slot = char.items_by_slot

    for slot_name, bis_slot in guide.slots.items():
        equipped = items_by_slot.get(slot_name)
        if equipped is None:
            # Slot not present in the character's gear list – skip silently
            continue

        if not bis_slot.options:
            continue

        if not bis_slot.is_item_acceptable(equipped.item_id):
            bis = bis_slot.bis_item
            if bis is None:
                continue
            msg = (
                f"{slot_name}: equipado '{equipped.item_id}' → "
                f"BiS recomendado '{bis.item_name}' ({bis.item_id}) [{bis.tier_note}]"
            )
            issues.append(
                ItemAuditIssue(
                    slot=slot_name,
                    current_item_id=equipped.item_id,
                    bis_item_id=bis.item_id,
                    bis_item_name=bis.item_name,
                    severity=AuditSeverity.CRITICAL,
                    message=msg,
                )
            )
            penalty += 8

    return issues, penalty


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 – enchant validation
# ─────────────────────────────────────────────────────────────────────────────

def _audit_enchants(
    char: CharacterData,
    guide: BisGuide,
) -> tuple[list[EnchantAuditIssue], int]:
    issues: list[EnchantAuditIssue] = []
    penalty = 0
    items_by_slot = char.items_by_slot

    for slot_name, bis_slot in guide.slots.items():
        if not bis_slot.required_enchant_ids:
            continue  # slot has no enchant requirement

        equipped = items_by_slot.get(slot_name)
        if equipped is None:
            continue

        current_eid = equipped.enchant_id  # None if missing

        if current_eid is None:
            # Slot is enchantable but enchant is absent
            issues.append(
                EnchantAuditIssue(
                    slot=slot_name,
                    current_enchant_id=None,
                    expected_enchant_name=bis_slot.enchant_display_name,
                    severity=AuditSeverity.CRITICAL,
                    message=(
                        f"{slot_name}: falta encantamiento → "
                        f"aplicar '{bis_slot.enchant_display_name}'"
                    ),
                )
            )
            penalty += 6
        elif not bis_slot.is_enchant_acceptable(current_eid):
            issues.append(
                EnchantAuditIssue(
                    slot=slot_name,
                    current_enchant_id=current_eid,
                    expected_enchant_name=bis_slot.enchant_display_name,
                    severity=AuditSeverity.WARNING,
                    message=(
                        f"{slot_name}: encantamiento '{current_eid}' no es "
                        f"el óptimo → esperado '{bis_slot.enchant_display_name}'"
                    ),
                )
            )
            penalty += 4

    return issues, penalty


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 – gem quality + required gem audit
# ─────────────────────────────────────────────────────────────────────────────

def _collect_character_gems(
    char: CharacterData,
) -> tuple[
    dict[str, list[str]],   # slot → [gem_item_ids]
    Counter[str],           # gem_item_id → total count across all gear
    str | None,             # detected meta gem item_id
]:
    """
    Iterate every item's ``gem_enchant_ids`` and resolve them to item IDs.

    Returns:
      gems_by_slot   – {slot: [item_id, ...]}  (meta gems excluded)
      gem_counter    – total count of each non-meta gem item_id
      meta_gem_id    – item_id of the first meta gem found, or None
    """
    _, _, meta_ids = _get_gem_lookups()
    gems_by_slot: dict[str, list[str]] = {}
    gem_counter: Counter[str] = Counter()
    found_meta: str | None = None

    for item in char.items:
        slot_gems: list[str] = []
        for eid in item.gem_enchant_ids:
            if _is_meta_enchant_id(eid):
                # Record meta gem item_id once
                item_id = _resolve_gem_item_id(eid) or eid
                if found_meta is None:
                    found_meta = item_id
                continue  # don't add meta to non-meta counter
            item_id = _resolve_gem_item_id(eid)
            if item_id:
                slot_gems.append(item_id)
                gem_counter[item_id] += 1
        gems_by_slot[item.slot] = slot_gems

    return gems_by_slot, gem_counter, found_meta


def _audit_gems(
    char: CharacterData,
    guide: BisGuide,
) -> tuple[list[GemAuditIssue], int]:
    _, epic_gems, _ = _get_gem_lookups()
    issues: list[GemAuditIssue] = []
    penalty = 0

    gems_by_slot, gem_counter, meta_gem_found = _collect_character_gems(char)

    # ── 3a. Meta gem ────────────────────────────────────────────────────────
    if guide.meta_gem_id:
        if meta_gem_found is None:
            issues.append(GemAuditIssue(
                slot="Meta Socket",
                gem_id="",
                gem_name="(ninguna)",
                issue="No hay meta gema equipada",
                suggestion=f"Equipa Chaotic Skyflare Diamond (item {guide.meta_gem_id})",
                severity=AuditSeverity.CRITICAL,
            ))
            penalty += 10
        elif meta_gem_found != guide.meta_gem_id:
            issues.append(GemAuditIssue(
                slot="Meta Socket",
                gem_id=meta_gem_found,
                gem_name=f"item:{meta_gem_found}",
                issue=f"Meta gema incorrecta (encontrada: {meta_gem_found})",
                suggestion=f"Reemplaza por el item {guide.meta_gem_id}",
                severity=AuditSeverity.WARNING,
            ))
            penalty += 5

    # ── 3b. Nightmare Tear (meta activation) ────────────────────────────────
    NIGHTMARE_TEAR_ID = "44342"
    if guide.nightmare_tear_required and gem_counter.get(NIGHTMARE_TEAR_ID, 0) == 0:
        issues.append(GemAuditIssue(
            slot="Socket (blue/prismático)",
            gem_id=NIGHTMARE_TEAR_ID,
            gem_name="Nightmare Tear",
            issue="Falta Nightmare Tear para activar la meta gema",
            suggestion=(
                "Coloca 1× Nightmare Tear (44342) en un socket azul o prismático. "
                "Esto activa el Chaotic Skyflare Diamond sin sacrificar slots rojos."
            ),
            severity=AuditSeverity.CRITICAL,
        ))
        penalty += 8

    # ── 3c. Required gem minimums ────────────────────────────────────────────
    for req in guide.gem_requirements:
        if req.gem_item_id in (NIGHTMARE_TEAR_ID, guide.meta_gem_id):
            # Already checked above
            continue
        have = gem_counter.get(req.gem_item_id, 0)
        if have < req.required_count:
            missing = req.required_count - have
            issues.append(GemAuditIssue(
                slot="Multiple slots",
                gem_id=req.gem_item_id,
                gem_name=req.gem_name,
                issue=(
                    f"Faltan {missing}× {req.gem_name} "
                    f"(tienes {have}, mínimo {req.required_count})"
                ),
                suggestion=req.description,
                severity=AuditSeverity.CRITICAL if have == 0 else AuditSeverity.WARNING,
            ))
            penalty += 5 * missing

    # ── 3d. Non-epic gems per slot ───────────────────────────────────────────
    for slot_name, gem_ids in gems_by_slot.items():
        for gid in gem_ids:
            if gid not in epic_gems:
                display = f"item:{gid}"  # best-effort; no name lookup needed for penalty
                issues.append(GemAuditIssue(
                    slot=slot_name,
                    gem_id=gid,
                    gem_name=display,
                    issue=f"Gema de calidad no-épica detectada ({display})",
                    suggestion="Reemplaza por una Cardinal Ruby, King's Amber o equivalente épico",
                    severity=AuditSeverity.WARNING,
                ))
                penalty += 3

    return issues, penalty


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 – stat caps
# ─────────────────────────────────────────────────────────────────────────────

def _audit_stat_caps(
    char: CharacterData,
    guide: BisGuide,
) -> tuple[list[StatCapAuditResult], int]:
    results: list[StatCapAuditResult] = []
    penalty = 0

    for cap in guide.stat_caps:
        current = float(getattr(char.stats, cap.stat_key, 0.0) or 0.0)
        delta   = cap.cap_value - current
        is_cap  = current >= cap.cap_value

        if not is_cap and cap.must_reach:
            penalty += 7
        elif is_cap and not cap.must_reach:
            # over-capped by more than 20% → wasteful
            if current > cap.cap_value * 1.20:
                penalty += 2

        results.append(StatCapAuditResult(
            stat_key=cap.stat_key,
            display_name=cap.display_name,
            current_value=current,
            cap_value=cap.cap_value,
            cap_label=cap.cap_label,
            is_capped=is_cap,
            delta=delta,
            must_reach=cap.must_reach,
        ))

    return results, penalty


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def audit_character(
    char_data: CharacterData,
    bis_guide: BisGuide,
    *,
    generate_summary: bool = True,
    groq_api_key: str | None = None,
) -> AuditReport:
    """
    Compare *char_data* against *bis_guide* and return a complete
    :class:`AuditReport`.

    Parameters
    ----------
    char_data:
        Populated :class:`CharacterData` from the armory scraper.
    bis_guide:
        :class:`BisGuide` instance (use :func:`~src.audit.get_bis_guide`).
    generate_summary:
        When *True* (default), calls :func:`~src.audit.coach.generate_coach_summary`
        to produce the Groq narrative.  Pass *False* to skip the API call.
    groq_api_key:
        Override the key used for Groq.  Falls back to the ``GROQ_API_KEY``
        environment variable when *None*.
    """
    # Run all four audit phases
    item_issues,    pen_items    = _audit_items(char_data, bis_guide)
    enchant_issues, pen_enchants = _audit_enchants(char_data, bis_guide)
    gem_issues,     pen_gems     = _audit_gems(char_data, bis_guide)
    stat_results,   pen_stats    = _audit_stat_caps(char_data, bis_guide)

    total_penalty = pen_items + pen_enchants + pen_gems + pen_stats
    overall_score = max(0, 100 - total_penalty)

    report = AuditReport(
        character_name=char_data.name,
        spec_name=bis_guide.spec_name,
        server=char_data.server,
        item_issues=item_issues,
        enchant_issues=enchant_issues,
        gem_issues=gem_issues,
        stat_caps=stat_results,
        overall_score=overall_score,
    )

    if generate_summary:
        try:
            from .coach import generate_coach_summary  # noqa: PLC0415
            report.coach_summary = await generate_coach_summary(
                report, bis_guide, api_key=groq_api_key
            )
        except Exception as exc:
            log.warning("Groq summary generation failed: %s", exc)
            report.coach_summary = None

    return report
