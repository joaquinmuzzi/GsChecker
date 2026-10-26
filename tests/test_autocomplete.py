"""Autocompletado del nombre de personaje: máximo 3 sugerencias, desde memoria.

El valor que devuelve sin reino ("Nombre (Reino)") tiene que seguir siendo
parseable por /p, /ia y /logs, o el personaje de Icecrown se buscaría en
Lordaeron.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.services import autocomplete
from src.services.character_input import split_name_and_realm
from tests.helpers import _find_command

ROWS = [
    ("Demmir", "Lordaeron", 30),
    ("Demonio", "Icecrown", 20),
    ("Demetra", "Lordaeron", 10),
    ("Demian", "Lordaeron", 5),
    ("Kuvez", "Icecrown", 3),
]


@pytest.fixture(autouse=True)
def loaded(monkeypatch):
    monkeypatch.setattr(autocomplete, "_CHARACTERS", ROWS)
    monkeypatch.setattr(autocomplete, "_LOADED_AT", 10**12)


def test_at_most_three_suggestions_ordered_by_lookups():
    got = autocomplete.suggest_characters("dem", None)
    assert [v for _, v in got] == ["Demmir (Lordaeron)", "Demonio (Icecrown)", "Demetra (Lordaeron)"]


def test_chosen_realm_filters_and_returns_plain_name():
    got = autocomplete.suggest_characters("dem", "icecrown")
    assert got == [("Demonio", "Demonio")]


def test_invalid_realm_is_ignored():
    assert len(autocomplete.suggest_characters("k", "Nope")) == 1


def test_value_is_parseable_by_the_commands():
    assert split_name_and_realm("Demonio (Icecrown)") == ("Demonio", "Icecrown")
    assert split_name_and_realm("Demonio (Icecrown)", "Onyxia") == ("Demonio", "Onyxia")
    assert split_name_and_realm("Demonio") == ("Demonio", None)
    assert split_name_and_realm("Foo (Bar)") == ("Foo (Bar)", None)


@pytest.mark.parametrize("name", ["p", "personaje", "dps", "ia", "logs", "ptoc"])
def test_every_command_autocompletes_the_name(bot, name):
    assert _find_command(bot, name).get_parameter("nombre") is not None
    assert _find_command(bot, name)._params["nombre"].autocomplete is not None


async def test_uses_realm_already_typed():
    choices = await autocomplete.make_name_autocomplete()(
        SimpleNamespace(namespace=SimpleNamespace(reino="Icecrown")), "d"
    )
    assert [c.value for c in choices] == ["Demonio"]


async def test_fixed_realm_for_dps():
    choices = await autocomplete.make_name_autocomplete("Lordaeron")(
        SimpleNamespace(namespace=SimpleNamespace()), "dem"
    )
    assert [c.value for c in choices] == ["Demmir", "Demetra", "Demian"]


async def test_first_load_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(autocomplete, "_CHARACTERS", [])
    monkeypatch.setattr(autocomplete, "_LOADED_AT", None)
    with patch("src.services.autocomplete.list_autocomplete_characters", return_value=[]):
        choices = await autocomplete.make_name_autocomplete()(
            SimpleNamespace(namespace=SimpleNamespace()), "d"
        )
    assert choices == []
