"""/ia usa el BiS del reino y del rol: un Blood DK tanque se evalúa con la guía
de tanque (antes se lo evaluaba con la de Blood DPS, que le recomendaba cambiar
todo su set y le daba 0/100), y los reinos sin guía se avisan sin tocar el
armory."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from profile_scraper import _parse_character_stats_html
from src.audit.bis_guides import detect_role, is_caster
from tests.test_personaje import (  # noqa: F401  (fixtures)
    _find_command,
    bot,
    patched_fetchers,
)

SRPINGU_STATS_HTML = """
<div class="character-stats">Character Stats Melee Damage: 2176 - 2605 Power: 4096
Hit rating: 7.47% Critical: 11.45% Attributes Strength: 1938 Stamina: 4087 Expertise: 18
Ranged Hit rating: 7.47% Defense Armor: 35022 Dodge: 24.84% Parry: 23.65% Block: 0%
Spell Power: 0 Haste: 0% Hit rating: 9.34%</div>
"""


def test_parses_dodge_parry_and_stamina():
    stats = _parse_character_stats_html(SRPINGU_STATS_HTML)
    assert stats["dodge_pct"] == 24.84
    assert stats["parry_pct"] == 23.65
    assert stats["stamina"] == 4087


@pytest.mark.parametrize(
    "char_class,spec,stats,expected",
    [
        ("Death Knight", "Blood", {"dodge_pct": 24.84}, "Tank"),   # Srpingu
        ("Death Knight", "Blood", {"dodge_pct": 8.25}, "DPS"),     # Blood DPS
        ("Death Knight", "Frost", {"dodge_pct": 25.0}, "Tank"),    # Frost tank
        ("Death Knight", "Unholy", {}, "DPS"),                     # sin dato
        ("Druid", "Feral Combat", {"stamina": 4200}, "Tank"),      # oso
        ("Druid", "Feral Combat", {"stamina": 2300}, "DPS"),       # gato
        ("Paladin", "Protection", {}, "Tank"),
        ("Warrior", "Fury", {"dodge_pct": 30.0}, ""),
    ],
)
def test_detect_role(char_class, spec, stats, expected):
    assert detect_role(char_class, spec, stats) == expected


def test_frost_is_caster_only_for_mages():
    assert is_caster("Mage", "Frost")
    assert not is_caster("Death Knight", "Frost")


def _srpingu_fetchers(patched_fetchers):
    patched_fetchers["summary"].return_value = {
        "name": "Srpingu", "level": 80, "race": "Night Elf", "class": "Death Knight",
        "guild": "Sin guild", "gearScore": "N/A",
    }
    patched_fetchers["specs"].return_value = [{"name": "Blood", "active": True}]


@pytest.mark.asyncio
async def test_ia_audits_blood_tank_with_tank_guide(bot, interaction, patched_fetchers):  # noqa: F811
    _srpingu_fetchers(patched_fetchers)
    audit = AsyncMock(return_value=None)
    with patch("profile_scraper.get_character_stats",
               return_value={"hit_rating": 244.9, "dodge_pct": 24.84}), \
         patch("src.controller.commands.run_full_audit", audit):
        await _find_command(bot, "ia").callback(interaction, nombre="Srpingu")

    audit.assert_awaited_once()
    kwargs = audit.await_args.kwargs
    assert kwargs["role"] == "Tank"
    assert kwargs["server"] == "Lordaeron"


@pytest.mark.asyncio
async def test_ia_realm_without_guides_skips_armory(bot, interaction, patched_fetchers):  # noqa: F811
    await _find_command(bot, "ia").callback(interaction, nombre="Srpingu", reino="Onyxia")

    assert "Todavía no hay guías BiS para Onyxia" in (interaction.last_edit().content or "")
    patched_fetchers["summary"].assert_not_called()
