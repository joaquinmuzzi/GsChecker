"""Guías BiS por reino generadas desde el armory (static/bis/<reino>.json)."""
from __future__ import annotations

import json

import pytest

from src.audit import bis_guides
from src.audit.auditor import _audit_gems, _audit_items
from src.audit.models import CharacterData, EquippedItem

REALM_DATA = {
    "realm": "Lordaeron",
    "generated": "2026-09-27",
    "guides": {
        "Death Knight|Blood|Tank": {
            "sample_size": 12,
            "gs_range": [6520, 6899],
            "players": ["Camunga"],
            "slots": {
                "Head": {
                    "options": [
                        {"item_id": "50640", "item_name": "Broken Ram Skull Helm", "used_by": 6},
                        {"item_id": "51306", "item_name": "Sanctified Scourgelord Faceguard", "used_by": 6},
                    ],
                    "enchant_ids": ["3818"],
                    "enchant_label": "+37 Stamina and +20 Defense Rating",
                },
                "Trinket": {
                    "options": [{"item_id": "54591", "item_name": "Petrified Twilight Scale", "used_by": 10}],
                    "enchant_ids": [],
                    "enchant_label": "",
                },
            },
            "meta_gem": {"item_id": "41380", "name": "Austere Earthsiege Diamond", "used_by": 12},
            "nightmare_tear_share": 0.75,
            "stat_caps": [],
        }
    },
    "item_names": {"51133": "Sanctified Scourgelord Faceguard (tank helm)"},
}


@pytest.fixture
def realm_files(tmp_path, monkeypatch):
    (tmp_path / "lordaeron.json").write_text(json.dumps(REALM_DATA), encoding="utf-8")
    monkeypatch.setattr(bis_guides, "BIS_DIR", tmp_path)
    bis_guides._load_realm.cache_clear()
    yield
    bis_guides._load_realm.cache_clear()


def test_guide_is_per_realm_and_role(realm_files):
    guide = bis_guides.get_bis_guide("Death Knight", "Blood", realm="lordaeron", role="Tank")
    assert guide is not None
    assert guide.spec_name == "Death Knight Blood (Tank) · Lordaeron"
    # Anillos/trinkets vienen agrupados y se expanden a los dos slots.
    assert set(guide.slots) == {"Head", "Trinket 1", "Trinket 2"}
    assert guide.slots["Head"].options[0].tier_note == "lo usan 6/12 top de Lordaeron"
    assert guide.meta_gem_name == "Austere Earthsiege Diamond"
    assert guide.nightmare_tear_required

    assert bis_guides.get_bis_guide("Death Knight", "Blood", realm="Lordaeron", role="DPS") is None
    assert bis_guides.get_bis_guide("Death Knight", "Blood", realm="Icecrown", role="Tank") is None
    assert bis_guides.get_bis_guide("Death Knight", "Blood", realm="Onyxia", role="Tank") is None


def test_available_guides_labels(realm_files):
    assert bis_guides.available_guides("Lordaeron") == ["Death Knight Blood (Tank)"]


def _char(items):
    return CharacterData(name="Srpingu", server="Lordaeron", char_class="Death Knight",
                         spec="Blood", items=items)


def test_item_issue_shows_equipped_item_name(realm_files):
    guide = bis_guides.get_bis_guide("Death Knight", "Blood", role="Tank")
    issues, _ = _audit_items(_char([EquippedItem(slot="Head", item_id="51133")]), guide)
    assert "Sanctified Scourgelord Faceguard (tank helm)" in issues[0].message


def test_nightmare_tear_is_recognised(realm_files):
    """El auditor buscaba Nightmare Tear como 44342 (unas piernas de cuero) y le
    marcaba a todos que les faltaba."""
    guide = bis_guides.get_bis_guide("Death Knight", "Blood", role="Tank")
    head = EquippedItem(slot="Head", item_id="51306", gem_enchant_ids=["3637", "3879"])
    issues, _ = _audit_gems(_char([head]), guide)
    messages = " ".join(i.issue for i in issues)
    assert "Nightmare Tear" not in messages
    assert "Meta gema" not in messages and "No hay meta" not in messages


def test_lower_version_of_any_option_is_reported_as_upgrade(realm_files):
    """Srpingu tiene el Faceguard normal (51133); los top usan el heroico, que es
    la opción 2 del slot: el mensaje tiene que decir "versión de mayor nivel",
    no "cambialo por la opción 1"."""
    guide = bis_guides.get_bis_guide("Death Knight", "Blood", role="Tank")
    guide.item_names = {"51133": "Sanctified Scourgelord Faceguard"}
    issues, _ = _audit_items(_char([EquippedItem(slot="Head", item_id="51133")]), guide)
    assert "versión de mayor nivel (51306)" in issues[0].message
