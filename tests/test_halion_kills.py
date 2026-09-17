"""Unit tests for the Halion (Ruby Sanctum) achievement/statistics cross-check.

Warmane sometimes grants the Halion kill achievement without a real kill
(same class of bug as the existing Marrowgar/Deathwhisper "bugfix" for ICC).
`_extract_halion_kills` reads the real kill counters from the armory
statistics page, and `_confirm_halion_kill` requires both sources to agree
before trusting a kill.
"""

from __future__ import annotations

from src.functions.embeds import _confirm_halion_kill, _extract_halion_kills


def _row(desc: str, val: str) -> list[str]:
    return [desc, val]


class TestExtractHalionKills:
    def test_all_zero_reproduces_shonau_bug_report(self):
        """Real armory.warmane.com/character/Shonau/Lordaeron/statistics output."""
        stats_rows = [
            _row("Halion kills (Heroic Ruby Sanctum 10 player)", "- -"),
            _row("Halion kills (Heroic Ruby Sanctum 25 player)", "- -"),
            _row("Halion kills (Ruby Sanctum 10 player)", "- -"),
            _row("Halion kills (Ruby Sanctum 25 player)", "- -"),
        ]
        result = _extract_halion_kills(stats_rows)
        assert result == {"10n": False, "10h": False, "25n": False, "25h": False}

    def test_real_kill_counts_as_true(self):
        stats_rows = [
            _row("Halion kills (Ruby Sanctum 25 player)", "3"),
            _row("Halion kills (Heroic Ruby Sanctum 25 player)", "1"),
        ]
        result = _extract_halion_kills(stats_rows)
        assert result["25n"] is True
        assert result["25h"] is True

    def test_missing_row_is_none_not_false(self):
        """No row at all (e.g. statistics fetch failed) must be distinguishable
        from a row that explicitly reports zero kills."""
        result = _extract_halion_kills([])
        assert result == {"10n": None, "10h": None, "25n": None, "25h": None}

    def test_is_case_insensitive_and_ignores_unrelated_rows(self):
        stats_rows = [
            _row("Lich King kills", "5"),
            _row("HALION KILLS (RUBY SANCTUM 10 PLAYER)", "2"),
        ]
        result = _extract_halion_kills(stats_rows)
        assert result["10n"] is True
        assert result["10h"] is None

    def test_malformed_rows_are_ignored(self):
        stats_rows = [["only one column"], None, "not a row", []]
        result = _extract_halion_kills(stats_rows)
        assert result == {"10n": None, "10h": None, "25n": None, "25h": None}


class TestConfirmHalionKill:
    def test_bugged_achievement_without_confirmation_is_rejected(self):
        assert _confirm_halion_kill(True, False) is False

    def test_achievement_confirmed_by_stats_is_accepted(self):
        assert _confirm_halion_kill(True, True) is True

    def test_no_achievement_never_becomes_true_from_stats_alone(self):
        assert _confirm_halion_kill(False, True) is False

    def test_no_stats_data_falls_back_to_trusting_achievement(self):
        assert _confirm_halion_kill(True, None) is True
        assert _confirm_halion_kill(False, None) is False
