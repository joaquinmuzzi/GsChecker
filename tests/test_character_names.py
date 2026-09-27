from unittest.mock import patch

import pytest

from src.db import postgres
from src.functions.names import is_valid_character_name
from tools import run_scheduled_preload as cron


@pytest.mark.parametrize("name", ["Srpingu", "Shonau", "Añoranza", "Ël", "Abcdefghijkl"])
def test_valid_names(name):
    assert is_valid_character_name(name)


@pytest.mark.parametrize(
    "name", ["C_7119121", "Veletriel\\", "", "A", "Abcdefghijklm", "Frodo2", "-", None]
)
def test_invalid_names(name):
    assert not is_valid_character_name(name)


def test_seed_parser_skips_junk_names():
    assert cron._parse_txt_line("C_7119121", "Lordaeron") is None
    assert cron._parse_txt_line("Srpingu, Icecrown", "Lordaeron") == ("Srpingu", "Icecrown")


def test_track_lookup_ignores_junk_names():
    with patch.object(postgres, "db_enabled", return_value=True), \
         patch.object(postgres, "_get_connection") as mock_conn:
        postgres.track_character_lookup("Veletriel\\", "Lordaeron")
    mock_conn.assert_not_called()
