"""Regeneración mensual del BiS: el cron publica en Postgres (su disco no le
llega al bot) y nunca pisa guías buenas con una corrida incompleta."""
from __future__ import annotations

from unittest.mock import patch

from src.audit import bis_guides
from tools import build_bis_from_armory as tool


def _data(n):
    return {"realm": "Lordaeron", "generated": "2026-10-15",
            "guides": {f"Class{i}|Spec|": {} for i in range(n)}}


def test_publish_stores_a_complete_run():
    with patch.object(tool, "get_app_state", return_value=_data(27)), \
         patch.object(tool, "set_app_state", return_value=True) as mock_set:
        assert tool.publish("Lordaeron", _data(26))
    mock_set.assert_called_once_with("bis_guides:lordaeron", _data(26))


def test_publish_refuses_an_incomplete_run():
    """Ej. uwu-logs caído: 10 guías contra 27 publicadas."""
    with patch.object(tool, "get_app_state", return_value=_data(27)), \
         patch.object(tool, "set_app_state") as mock_set:
        assert not tool.publish("Lordaeron", _data(10))
        assert not tool.publish("Lordaeron", _data(0))
    mock_set.assert_not_called()


def test_bot_prefers_postgres_and_falls_back_to_repo_files():
    bis_guides._load_realm.cache_clear()
    with patch.object(bis_guides, "get_app_state", return_value=_data(3)):
        assert len(bis_guides._load_realm("Lordaeron")["guides"]) == 3

    bis_guides._load_realm.cache_clear()
    with patch.object(bis_guides, "get_app_state", return_value=None):
        # static/bis/lordaeron.json versionado en el repo
        assert len(bis_guides._load_realm("Lordaeron")["guides"]) > 20
    bis_guides._load_realm.cache_clear()
