"""Regression tests for the positional gear-slot bug found in production.

gearscore.main() is positional: it unpacks the last 3 entries of the list as
main-hand/off-hand/ranged and zips everything else against a fixed
SLOT_TYPES template by index. Filtering out blank slots (e.g. an unworn
Tabard) before calling it shifts every later item into the wrong category
and silently undercounts the total.

This bit us for real: tools/preload_character_gs.py, tools/filter_high_gs.py
and tools/preload_personaje_cache.py all filtered blanks out, and Veletriel
(a real character) scored 4086 instead of the correct 5896 as a result.
"""

from __future__ import annotations

from unittest.mock import patch

import gearscore

# Real gear_ids for Veletriel/Lordaeron, in armory DOM order (Head..Ranged),
# with the Tabard slot (index 6) unworn — captured live while diagnosing the bug.
VELETRIEL_GEAR_IDS = [
    "51178", "50061", "51175", "53489", "51176", "52019", "", "50032",
    "51179", "50063", "49891", "49893", "50610", "50400", "47041", "50366",
    "51910", "40699", "51326",
]
VELETRIEL_CORRECT_GS = 5896
VELETRIEL_FILTERED_BUG_GS = 4086


class TestGearscoreIsPositional:
    def test_full_list_with_blank_slot_scores_correctly(self):
        assert sum(gearscore.main(VELETRIEL_GEAR_IDS)) == VELETRIEL_CORRECT_GS

    def test_filtering_blank_slots_corrupts_the_score(self):
        """Documents *why* the filter must never come back: dropping the
        blank Tabard entry shifts every following item's assumed category
        and reproduces the exact wrong number seen in production."""
        filtered = [gid for gid in VELETRIEL_GEAR_IDS if gid]
        assert sum(gearscore.main(filtered)) == VELETRIEL_FILTERED_BUG_GS
        assert sum(gearscore.main(filtered)) != VELETRIEL_CORRECT_GS


class TestCalculateCharacterGsDoesNotFilter:
    """tools/preload_character_gs.py — feeds the cached per-spec GS number."""

    @patch("tools.preload_character_gs._fetch_specs")
    @patch("tools.preload_character_gs._fetch_gear_data")
    @patch("tools.preload_character_gs._fetch_summary")
    def test_preload_character_gs_scores_correctly(
        self, mock_summary, mock_gear, mock_specs
    ):
        from tools.preload_character_gs import _calculate_character_gs

        mock_summary.return_value = {
            "name": "Veletriel", "level": 80, "race": "Human",
            "class": "Priest", "guild": "Sin guild", "gearScore": "N/A",
        }
        mock_gear.return_value = [
            {"item": gid, "slot": f"slot{i}", "gems": ["0", "0", "0"], "ench": "0"}
            for i, gid in enumerate(VELETRIEL_GEAR_IDS)
        ]
        mock_specs.return_value = [{"name": "Discipline", "active": True}]

        payload = _calculate_character_gs("Veletriel", "Lordaeron")

        assert payload is not None
        assert payload["gs"] == VELETRIEL_CORRECT_GS


class TestFilterHighGsDoesNotFilter:
    """tools/filter_high_gs.py — decides who makes the priority preload list."""

    @patch("tools.filter_high_gs.SESSION")
    @patch("tools.filter_high_gs.ARMORY_LIMITER")
    def test_fetch_summary_gs_scores_correctly(self, mock_limiter, mock_session):
        from tools.filter_high_gs import _fetch_summary_gs

        mock_limiter.acquire.return_value = None
        mock_response = mock_session.get.return_value
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "equipment": [{"item": gid} if gid else {} for gid in VELETRIEL_GEAR_IDS],
        }

        gs = _fetch_summary_gs("Veletriel", "Lordaeron")

        assert gs == VELETRIEL_CORRECT_GS


class TestPreloadPersonajeCacheDoesNotFilter:
    """tools/preload_personaje_cache.py — feeds the full 25h command_personaje cache."""

    @patch("tools.preload_personaje_cache._fetch_guild_rank")
    @patch("tools.preload_personaje_cache._uwu_icc_bugfix_kills")
    @patch("tools.preload_personaje_cache._fetch_specs")
    @patch("tools.preload_personaje_cache._fetch_professions")
    @patch("tools.preload_personaje_cache._fetch_statistics")
    @patch("tools.preload_personaje_cache._fetch_achievements")
    @patch("tools.preload_personaje_cache._fetch_gear_data")
    @patch("tools.preload_personaje_cache._fetch_summary")
    def test_build_personaje_cache_entry_scores_correctly(
        self,
        mock_summary,
        mock_gear,
        mock_achi,
        mock_stats,
        mock_prof,
        mock_specs,
        mock_uwu,
        mock_rank,
    ):
        from tools.preload_personaje_cache import build_personaje_cache_entry

        mock_summary.return_value = {
            "name": "Veletriel", "level": 80, "race": "Human",
            "class": "Priest", "guild": "Sin guild", "gearScore": "N/A",
        }
        mock_gear.return_value = [
            {"item": gid, "slot": f"slot{i}", "gems": ["0", "0", "0"], "ench": "0"}
            for i, gid in enumerate(VELETRIEL_GEAR_IDS)
        ]
        mock_achi.return_value = {
            "halion_10n_achieved": False, "halion_10h_achieved": False,
            "halion_25n_achieved": False, "halion_25h_achieved": False,
            "completed_ids": set(),
            "storming_10h_achieved": False, "storming_25n_achieved": False,
            "storming_25h_achieved": False,
        }
        mock_stats.return_value = []
        mock_prof.return_value = []
        mock_specs.return_value = [{"name": "Discipline", "active": True}]
        mock_uwu.return_value = {}
        mock_rank.return_value = None

        payload = build_personaje_cache_entry("Veletriel", "Lordaeron")

        assert payload is not None
        assert payload["gs"] == VELETRIEL_CORRECT_GS
