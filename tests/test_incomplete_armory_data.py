"""Cuando el armory responde a medias (429 en logros o estadísticas), el perfil
no debe persistirse: los ❌ que mostraría son "no pudimos leerlo", no "no lo hizo"."""
from unittest.mock import patch

from src.controller.commands import (
    _is_personaje_data_complete,
    _is_valid_personaje_payload,
    _serialize_personaje_payload,
)
from src.functions import warmane
from src.schemas.constants import ACHIEVEMENTS_CACHE


def _payload(data_complete):
    return _serialize_personaje_payload(
        "Srpingu", "Lordaeron", 6291, 80, "Night Elf", "Death Knight",
        "Blood", "<Guild>", None, True, True, True, True, {}, {}, [], [], {},
        [], "Blood", gear_item_count=18, data_complete=data_complete,
    )


def test_incomplete_payload_is_not_cacheable():
    assert _is_valid_personaje_payload(_payload(True))
    assert not _is_valid_personaje_payload(_payload(False))


def test_data_complete_requires_achievements_and_stats():
    rows = [["Lord Marrowgar kills (Icecrown 25 player)", "3"]]
    assert _is_personaje_data_complete({"complete": True}, rows)
    assert not _is_personaje_data_complete({"complete": False}, rows)
    assert not _is_personaje_data_complete({"complete": True}, [])
    assert not _is_personaje_data_complete(None, rows)


@patch("src.functions.warmane.time.sleep")
@patch("src.functions.warmane._warmane_post_json_with_scheme_fallback")
def test_failed_category_marks_achievements_incomplete(mock_post, _sleep):
    ACHIEVEMENTS_CACHE.clear()
    halion_html = '<div class="achievement" id="ach4815"></div>'

    def fake_post(path, headers, data):
        if data["category"] == 14923:
            return {"content": halion_html}
        if data["category"] == 14922:
            return None  # 429 / circuit abierto
        return {"content": ""}

    mock_post.side_effect = fake_post
    payload = warmane._fetch_achievements("Srpingu", "Lordaeron")

    assert payload["complete"] is False
    assert payload["halion_25n_achieved"] is True
    # No se guarda en cache un resultado incompleto.
    assert ("Srpingu", "Lordaeron") not in ACHIEVEMENTS_CACHE


@patch("src.functions.warmane.time.sleep")
@patch("src.functions.warmane._warmane_post_json_with_scheme_fallback")
def test_all_categories_ok_is_complete(mock_post, _sleep):
    ACHIEVEMENTS_CACHE.clear()
    mock_post.return_value = {"content": '<div class="achievement" id="ach4815"></div>'}
    payload = warmane._fetch_achievements("Srpingu", "Lordaeron")
    assert payload["complete"] is True
