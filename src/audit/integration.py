"""
Integration helper – bridges profile_scraper output with the audit module.

Usage example (from the Discord bot or a standalone script):

    from src.audit.integration import run_full_audit

    report = await run_full_audit(
        char_name="Arthanor",
        server="Lordaeron",
        char_class="Warrior",
        spec="Fury",
        stats={
            "hit_rating": 245,
            "expertise_rating": 214,
            "armor_penetration_rating": 1388,
        },
    )
    print(report.to_plain_text())
    # or send report.coach_summary to Discord
"""

from __future__ import annotations

import asyncio
import logging
import os

from src.audit.models import CharacterData, CharacterStats, EquippedItem
from src.audit.bis_guides import get_bis_guide
from src.audit.auditor import audit_character
from src.audit.models import AuditReport

log = logging.getLogger(__name__)

_ITEM_NAME_CACHE: dict[str, str] = {}


def _lookup_item_names(item_ids: list[str]) -> dict[str, str]:
    """Nombres de ítems vía tooltips de Wowhead WotLK (Warmane usa los IDs
    originales). Cacheado y tolerante a fallos: si no responde, queda el ID."""
    import requests  # noqa: PLC0415

    for item_id in item_ids:
        if item_id in _ITEM_NAME_CACHE:
            continue
        try:
            resp = requests.get(
                f"https://nether.wowhead.com/wotlk/tooltip/item/{item_id}", timeout=4
            )
            name = resp.json().get("name") if resp.ok else None
        except Exception:
            name = None
        if name:
            _ITEM_NAME_CACHE[item_id] = name
    return {i: _ITEM_NAME_CACHE[i] for i in item_ids if i in _ITEM_NAME_CACHE}


def _gear_data_to_equipped_items(gear_data: list[dict]) -> list[EquippedItem]:
    """
    Convert the list returned by ``profile_scraper.get_gear_data()`` to
    a list of :class:`EquippedItem` Pydantic models.

    ``gear_data`` format (per item)::

        {
            "slot":  "Head",
            "item":  "51253",
            "ench":  "3817",
            "gems":  ["3986", "0", "0"],   # enchant IDs of socketed gems
        }
    """
    items: list[EquippedItem] = []
    for entry in gear_data:
        item_id = str(entry.get("item") or "").strip()
        if not item_id:
            continue

        slot       = str(entry.get("slot") or "Unknown")
        enchant_id = str(entry.get("ench") or "0") or None
        gems_raw   = entry.get("gems") or []

        items.append(
            EquippedItem(
                slot=slot,
                item_id=item_id,
                enchant_id=enchant_id,
                gem_enchant_ids=[str(g) for g in gems_raw],
            )
        )
    return items


async def run_full_audit(
    *,
    char_name: str,
    server: str = "Lordaeron",
    char_class: str,
    spec: str,
    stats: dict[str, float] | None = None,
    gear_data: list[dict] | None = None,
    groq_api_key: str | None = None,
    generate_summary: bool = True,
    role: str = "",
) -> AuditReport | None:
    """
    High-level coroutine that:

    1. Fetches gear from the Warmane armory (if *gear_data* not supplied).
    2. Looks up the BiS guide for ``char_class`` + ``spec``.
    3. Runs :func:`~src.audit.auditor.audit_character`.
    4. Returns the complete :class:`AuditReport`.

    Parameters
    ----------
    char_name:
        Character name (case-insensitive for armory fetch).
    server:
        Realm name (default: ``'Lordaeron'``).
    char_class:
        Character class, e.g. ``'Warrior'``.
    spec:
        Active spec, e.g. ``'Fury'``.
    stats:
        Dict of stat floats matching :class:`CharacterStats` field names.
        Partial dicts are accepted; missing keys default to ``0.0``.
    gear_data:
        Pre-fetched gear list (from ``profile_scraper.get_gear_data``).
        When *None* the function fetches from the armory.
    groq_api_key:
        API key for Groq.  Falls back to the ``GROQ_API_KEY`` env variable.
    generate_summary:
        Pass *False* to skip the Groq API call.

    Returns
    -------
    AuditReport | None
        ``None`` if the BiS guide does not exist for the given spec.
    """
    # 1. Get gear data
    if gear_data is None:
        try:
            from profile_scraper import get_gear_data  # noqa: PLC0415
            # Offload blocking I/O to the default thread-pool executor
            loop = asyncio.get_event_loop()
            gear_data = await loop.run_in_executor(
                None, lambda: get_gear_data(char_name, server)
            )
        except Exception as exc:
            log.error("Failed to fetch gear for %s/%s: %s", char_name, server, exc)
            gear_data = []

    # 2. Resolve BiS guide
    guide = get_bis_guide(char_class, spec, realm=server, role=role)
    if guide is None:
        log.warning(
            "No BiS guide for class='%s' spec='%s' role='%s' realm='%s'",
            char_class,
            spec,
            role,
            server,
        )
        return None

    # 2b. Nombres de lo que tiene puesto y la guía no conoce (items fuera del
    #     equipo de los top), para no mostrar "equipado '51133'".
    equipped_ids = [str(g.get("item")) for g in (gear_data or []) if g.get("item")]
    missing = [i for i in equipped_ids if i not in guide.item_names]
    if missing:
        found = await asyncio.to_thread(_lookup_item_names, missing)
        guide.item_names = {**guide.item_names, **found}

    # 3. Build CharacterData
    char = CharacterData(
        name=char_name,
        server=server,
        char_class=char_class,
        spec=spec,
        items=_gear_data_to_equipped_items(gear_data or []),
        stats=CharacterStats(**(stats or {})),
    )

    # 4. Run audit
    report = await audit_character(
        char,
        guide,
        generate_summary=generate_summary,
        groq_api_key=groq_api_key or os.getenv("GROQ_API_KEY"),
    )

    return report
