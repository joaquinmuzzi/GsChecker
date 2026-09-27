"""El estado del cron (índice rotativo, lista de GS alto) debe vivir en Postgres:
el filesystem de Railway se resetea en cada deploy y el índice volvía a 0."""
from unittest.mock import patch

from tools import run_scheduled_preload as cron


def test_rotation_index_prefers_postgres(tmp_path):
    with patch.object(cron, "get_app_state", return_value=4500):
        assert cron._read_rotation_index() == 4500


def test_rotation_index_falls_back_to_file_without_db(tmp_path):
    with patch.object(cron, "get_app_state", return_value=None), \
         patch.object(cron, "PROJECT_ROOT", tmp_path):
        assert cron._read_rotation_index() == 0
        (tmp_path / "data").mkdir()
        (tmp_path / cron.ROTATION_INDEX_PATH).write_text("1500", encoding="utf-8")
        assert cron._read_rotation_index() == 1500


def test_save_rotation_index_writes_postgres(tmp_path):
    with patch.object(cron, "set_app_state") as mock_set, \
         patch.object(cron, "PROJECT_ROOT", tmp_path):
        cron._save_rotation_index(5000)
    mock_set.assert_called_once_with(cron.ROTATION_INDEX_STATE_KEY, 5000)


def test_rotation_batch_continues_from_stored_index(tmp_path):
    names = [(f"Char{i}", "Lordaeron") for i in range(10)]
    with patch.object(cron, "get_app_state", return_value=4), \
         patch.object(cron, "set_app_state") as mock_set, \
         patch.object(cron, "PROJECT_ROOT", tmp_path):
        batch = cron._load_rotation_batch(names, set(), 3)
    assert batch == names[4:7]
    mock_set.assert_called_once_with(cron.ROTATION_INDEX_STATE_KEY, 7)


def test_filtered_list_prefers_postgres(tmp_path):
    stored = [["Srpingu", "Lordaeron"], ["Frodo", "Icecrown"]]
    with patch.object(cron, "get_app_state", return_value=stored):
        pairs = cron._load_filtered(tmp_path / "missing.txt", "Lordaeron")
    assert pairs == [("Srpingu", "Lordaeron"), ("Frodo", "Icecrown")]


def test_filtered_list_falls_back_to_txt(tmp_path):
    txt = tmp_path / "high.txt"
    txt.write_text("# header\nSrpingu, Lordaeron\n", encoding="utf-8")
    with patch.object(cron, "get_app_state", return_value=None):
        assert cron._load_filtered(txt, "Lordaeron") == [("Srpingu", "Lordaeron")]
