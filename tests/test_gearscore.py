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
    "51178",
    "50061",
    "51175",
    "53489",
    "51176",
    "52019",
    "",
    "50032",
    "51179",
    "50063",
    "49891",
    "49893",
    "50610",
    "50400",
    "47041",
    "50366",
    "51910",
    "40699",
    "51326",
]
VELETRIEL_CORRECT_GS = 5896
# Production showed 4086 back when every slot was scored by its position. Items
# are now scored by their own slot type, but the shift still drops the wrists:
# they land on the Tabard position, which never counts.
VELETRIEL_FILTERED_BUG_GS = 5618


class TestGearscoreIsPositional:
    def test_full_list_with_blank_slot_scores_correctly(self):
        assert sum(gearscore.main(VELETRIEL_GEAR_IDS)) == VELETRIEL_CORRECT_GS

    def test_filtering_blank_slots_corrupts_the_score(self):
        """Documents *why* the filter must never come back: dropping the
        blank Tabard entry shifts every following item one position up and
        the total comes out wrong."""
        filtered = [gid for gid in VELETRIEL_GEAR_IDS if gid]
        assert sum(gearscore.main(filtered)) == VELETRIEL_FILTERED_BUG_GS
        assert sum(gearscore.main(filtered)) != VELETRIEL_CORRECT_GS


# Real gear_ids for Demmir/Lordaeron (Priest), armory DOM order, captured live on
# 2026-10-23 00:05 UTC. The off-hand Tome of Salramm (37086) is a blue of ilvl 187
# that GS.json does not list: the bot scored it 0 and, taking the unknown item for
# a Titan's Grip two-hander, also halved the main hand. It showed 4427 while the
# player saw 4.8k in game.
DEMMIR_GEAR_IDS = [
    "46197",
    "50182",
    "50449",
    "40723",
    "47936",
    "53",
    "",
    "47173",
    "47982",
    "50263",
    "50769",
    "50286",
    "49967",
    "49486",
    "47215",
    "50260",
    "45612",
    "37086",
    "45257",
]
DEMMIR_CORRECT_GS = 4880
DEMMIR_OLD_BUG_GS = 4427

# Real gear_ids for Kuvez/Lordaeron (Fury Warrior), captured the same day: two
# Tyrannical Beheader (50267, two-hander of ilvl 232) with Titan's Grip.
KUVEZ_GEAR_IDS = [
    "50311",
    "50452",
    "48374",
    "51354",
    "48372",
    "2575",
    "",
    "50230",
    "48375",
    "50270",
    "48373",
    "49906",
    "52569",
    "50453",
    "49074",
    "47214",
    "50267",
    "50267",
    "47659",
]


class TestOffHandOutsideTheOldTable:
    def test_demmir_scores_like_the_addon(self):
        total = sum(gearscore.main(DEMMIR_GEAR_IDS))
        assert total == DEMMIR_CORRECT_GS
        assert total != DEMMIR_OLD_BUG_GS

    def test_blue_off_hand_is_scored_by_the_formula(self):
        assert gearscore.main(DEMMIR_GEAR_IDS)[17] == 242

    def test_unknown_off_hand_does_not_halve_the_main_hand(self):
        gear = list(DEMMIR_GEAR_IDS)
        gear[17] = "999999"  # not an item
        values = gearscore.main(gear)
        assert values[16] == 422  # Constellus, epic main hand of ilvl 239
        assert values[17] == 0
        assert gearscore.get_weapon_GS("999999") == (0, None)


class TestTitansGrip:
    def test_two_two_handers_count_half_each(self):
        values = gearscore.main(KUVEZ_GEAR_IDS)
        assert values[16] == values[17] == 402
        assert sum(values) == 5087

    def test_a_two_hander_alone_counts_full(self):
        gear = list(KUVEZ_GEAR_IDS)
        gear[17] = ""
        assert gearscore.main(gear)[16] == 805


class TestItemLevelData:
    """static/item_levels.json comes from the 3.3.5a item DB of AzerothCore."""

    def test_epics_match_the_old_table(self):
        checked = 0
        for category, by_ilvl in gearscore.GS_DATA.items():
            for ilvl, item_ids in by_ilvl.items():
                expected = gearscore.ILVL_GS[ilvl][gearscore.ITEM_TYPE[category]]
                for item_id in item_ids:
                    item_level = gearscore.ITEM_LEVELS.get(item_id)
                    if item_level is not None and item_level[1] == 4:
                        assert gearscore.formula_gs(*item_level) == expected, item_id
                        checked += 1
        assert checked > 5000

    def test_legendaries_match_the_old_table(self):
        for item_id, expected in gearscore.LEGENDARY.items():
            assert gearscore.get_weapon_GS(item_id)[0] == expected

    def test_ulduar_items_have_their_335a_item_level(self):
        # Wowhead /wotlk is Wrath Classic, where these are 252 and 232
        assert gearscore.ITEM_LEVELS["45612"] == (239, 4, 21)  # Constellus
        assert gearscore.ITEM_LEVELS["46197"] == (226, 4, 1)  # Conqueror's Cowl of Sanctification

    def test_ilvl_200_blue_scores_as_blue(self):
        # GS.json listed the heroic dungeon blues of ilvl 200 with the epic value (310)
        assert gearscore.item_gs("37135", "high") == 271  # Arcane-Shielded Helm


class TestCalculateCharacterGsDoesNotFilter:
    """tools/preload_character_gs.py — feeds the cached per-spec GS number."""

    @patch("tools.preload_character_gs._fetch_specs")
    @patch("tools.preload_character_gs._fetch_gear_data")
    @patch("tools.preload_character_gs._fetch_summary")
    def test_preload_character_gs_scores_correctly(self, mock_summary, mock_gear, mock_specs):
        from tools.preload_character_gs import _calculate_character_gs

        mock_summary.return_value = {
            "name": "Veletriel",
            "level": 80,
            "race": "Human",
            "class": "Priest",
            "guild": "Sin guild",
            "gearScore": "N/A",
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

    @patch("tools.preload_personaje_cache._fetch_uwu_performance", return_value={})
    @patch("src.services.profile._fetch_guild_rank")
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
        mock_perf,
    ):
        from tools.preload_personaje_cache import build_personaje_cache_entry

        mock_summary.return_value = {
            "name": "Veletriel",
            "level": 80,
            "race": "Human",
            "class": "Priest",
            "guild": "Sin guild",
            "gearScore": "N/A",
        }
        mock_gear.return_value = [
            {"item": gid, "slot": f"slot{i}", "gems": ["0", "0", "0"], "ench": "0"}
            for i, gid in enumerate(VELETRIEL_GEAR_IDS)
        ]
        mock_achi.return_value = {
            "halion_10n_achieved": False,
            "halion_10h_achieved": False,
            "halion_25n_achieved": False,
            "halion_25h_achieved": False,
            "completed_ids": set(),
            "storming_10h_achieved": False,
            "storming_25n_achieved": False,
            "storming_25h_achieved": False,
        }
        mock_stats.return_value = [["Lord Marrowgar kills (Icecrown 25 player)", "- -"]]
        mock_prof.return_value = []
        mock_specs.return_value = [{"name": "Discipline", "active": True}]
        mock_uwu.return_value = {}
        mock_rank.return_value = None

        payload = build_personaje_cache_entry("Veletriel", "Lordaeron")

        assert payload is not None
        assert payload["gs"] == VELETRIEL_CORRECT_GS
