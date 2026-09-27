"""/ia no debe evaluar a un Blood DK tanque con la guía BiS de Blood DPS: le
recomendaba cambiar todo su set de tanque y le daba score 0/100."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from profile_scraper import _parse_character_stats_html
from src.controller.commands import _is_tanking_blood_dk
from tests.test_personaje import (  # noqa: F401  (fixtures)
    _find_command,
    bot,
    patched_fetchers,
)

SRPINGU_STATS_HTML = """
<div class="character-stats">Character Stats Melee Damage: 2176 - 2605 Power: 4096
Hit rating: 7.47% Critical: 11.45% Attributes Strength: 1938 Expertise: 18
Ranged Hit rating: 7.47% Defense Armor: 35022 Dodge: 24.84% Parry: 23.65% Block: 0%
Spell Power: 0 Haste: 0% Hit rating: 9.34%</div>
"""


def test_parses_dodge_and_parry():
    stats = _parse_character_stats_html(SRPINGU_STATS_HTML)
    assert stats["dodge_pct"] == 24.84
    assert stats["parry_pct"] == 23.65


@pytest.mark.parametrize(
    "char_class,spec,dodge,expected",
    [
        ("Death Knight", "Blood", 24.84, True),   # Srpingu, tanque
        ("Death Knight", "Blood", 8.25, False),   # Blood DPS
        ("Death Knight", "Frost", 25.0, False),   # no hay guía de Frost, no aplica
        ("Warrior", "Fury", 30.0, False),
        ("Death Knight", "Blood", None, False),   # sin dato: se evalúa como antes
    ],
)
def test_is_tanking_blood_dk(char_class, spec, dodge, expected):
    assert _is_tanking_blood_dk(char_class, spec, dodge) is expected


@pytest.mark.asyncio
async def test_ia_skips_dps_guide_for_blood_tank(bot, interaction, patched_fetchers):  # noqa: F811
    patched_fetchers["summary"].return_value = {
        "name": "Srpingu", "level": 80, "race": "Night Elf", "class": "Death Knight",
        "guild": "Sin guild", "gearScore": "N/A",
    }
    patched_fetchers["specs"].return_value = [{"name": "Blood", "active": True}]
    audit = AsyncMock()
    with patch("profile_scraper.get_character_stats",
               return_value={"hit_rating": 244.9, "dodge_pct": 24.84}), \
         patch("src.controller.commands.run_full_audit", audit):
        await _find_command(bot, "ia").callback(interaction, nombre="Srpingu")

    audit.assert_not_awaited()
    content = interaction.last_edit().content or ""
    assert "tanque" in content and "24.8" in content
