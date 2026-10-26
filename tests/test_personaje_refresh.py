"""Botón Actualizar de /p: rehace el perfil en el momento, sin esperar
a que el cron regenere la caché (pedido de Joaquín, 2026-10-22: a veces alguien
quiere ver un personaje al día y /p muestra el perfil que el cron armó a la
noche)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import discord
import pytest

from src.controller.commands.personaje_refresh import PersonajeRefreshButton
from src.functions.embeds import PERSONAJE_REFRESH_CUSTOM_ID, _build_personaje_view
from src.services.refresh_cooldown import (
    CHARACTER_COOLDOWN_SECONDS,
    USER_COOLDOWN_SECONDS,
    _mark_live_profile,
    _refresh_wait,
)
from tests.conftest import FakeInteraction, FakeMessage, FakeUser, SentPayload
from tests.helpers import _find_command


def _old_profile_embed() -> discord.Embed:
    embed = discord.Embed(title="Samsara")
    embed.add_field(name="GearScore", value="5000 (de anoche)")
    return embed


def _message_with_profile(embed: discord.Embed | None = None) -> FakeMessage:
    return FakeMessage(embeds=[embed or _old_profile_embed()])


def _first_button(view: discord.ui.View) -> discord.ui.Button:
    button = view.children[0]
    assert isinstance(button, discord.ui.Button)
    return button


async def _click_refresh(interaction: Any, nombre: str = "Samsara", realm: str = "Lordaeron"):
    """Como discord.py: el custom_id del botón del mensaje arma el DynamicItem
    y se llama a su callback."""
    button = _first_button(_build_personaje_view(nombre, realm))
    assert button.custom_id is not None
    match = PERSONAJE_REFRESH_CUSTOM_ID.match(button.custom_id)
    assert match is not None, button.custom_id
    item = await PersonajeRefreshButton.from_custom_id(interaction, button, match)
    await item.callback(interaction)


def _text(payload: SentPayload | None) -> str:
    assert payload is not None
    return payload.content or ""


def _edits(interaction: FakeInteraction):
    return [s for s in interaction.sent if s.kind == "edit"]


def test_personaje_view_starts_with_the_refresh_button():
    view = _build_personaje_view("Demmir", "Icecrown")
    button = _first_button(view)
    match = PERSONAJE_REFRESH_CUSTOM_ID.match(button.custom_id or "")
    assert match is not None
    assert (match["name"], match["realm"]) == ("Demmir", "Icecrown")
    assert [getattr(b, "label", None) for b in view.children[1:]] == ["Armory", "Uwulogs", "Donar"]


def test_refresh_button_is_registered_for_messages_sent_before_a_restart(bot):
    # Un DynamicItem atiende el botón por su custom_id: sin registrarlo, los
    # mensajes viejos (o los de antes de un deploy) darían "Interacción fallida".
    dynamic_items = bot._connection._view_store._dynamic_items.values()
    assert PersonajeRefreshButton in dynamic_items


@pytest.mark.asyncio
async def test_refresh_rebuilds_the_profile_in_the_same_message(patched_fetchers):
    # Con estadísticas el perfil está completo y se guarda en caché.
    patched_fetchers["statistics"].return_value = [["Lord Marrowgar kills (Icecrown 25 player)", "3"]]
    interaction = FakeInteraction(message=_message_with_profile())
    old_embed = interaction.message.embeds[0]

    await _click_refresh(interaction)

    assert interaction.sent[0].kind == "defer"
    assert interaction.sent[0].thinking is False, "deferred update: edits go to the button's message"
    patched_fetchers["summary"].assert_called_once_with("Samsara", "Lordaeron")

    edits = _edits(interaction)
    # Mientras calcula, el perfil viejo sigue a la vista con el aviso arriba.
    assert edits[0].content == "⏳ Actualizando perfil de Samsara en Lordaeron..."
    assert edits[0].embed is old_embed
    final = edits[-1]
    assert final.content is None
    assert final.embed is not old_embed
    assert any(f.name == "Icecrown Citadel" for f in final.embed.fields)
    assert _first_button(final.view).custom_id == "personaje:refresh:Lordaeron:Samsara"
    assert not [s for s in interaction.sent if s.kind == "followup"]


@pytest.mark.asyncio
async def test_refresh_ignores_the_cached_profile(patched_fetchers):
    # El botón es para no esperar al cron: nunca lee la caché de Postgres.
    with patch("src.controller.commands.personaje.async_get_external_cache") as cached:
        await _click_refresh(FakeInteraction(message=_message_with_profile()))
    cached.assert_not_called()
    patched_fetchers["summary"].assert_called_once()


@pytest.mark.asyncio
async def test_second_click_on_the_same_character_waits_for_the_cooldown(patched_fetchers):
    await _click_refresh(FakeInteraction(message=_message_with_profile()))
    other_user = FakeInteraction(user=FakeUser(user_id=7, name="Sam"), message=_message_with_profile())

    await _click_refresh(other_user)

    assert patched_fetchers["summary"].call_count == 1, "must not hit the armory again"
    [reply] = other_user.sent
    assert reply.kind == "send_message"
    assert reply.ephemeral
    assert "ya se actualizó hace menos de 5 min" in _text(reply)
    assert not _edits(other_user), "the message must stay as it is"


@pytest.mark.asyncio
async def test_a_user_refreshes_one_character_per_minute(patched_fetchers):
    await _click_refresh(FakeInteraction(message=_message_with_profile()), nombre="Samsara")
    again = FakeInteraction(message=_message_with_profile())

    await _click_refresh(again, nombre="Demmir")

    assert patched_fetchers["summary"].call_count == 1
    [reply] = again.sent
    assert reply.ephemeral
    assert "Ya actualizaste un personaje" in _text(reply)


@pytest.mark.asyncio
async def test_live_p_starts_the_character_cooldown(bot, interaction, patched_fetchers):
    # Un /p que recién armó el perfil en vivo ya está al día: el botón no lo rehace.
    await _find_command(bot, "p").callback(interaction, nombre="Samsara")
    click = FakeInteraction(user=FakeUser(user_id=7), message=_message_with_profile())

    await _click_refresh(click)

    assert patched_fetchers["summary"].call_count == 1
    assert click.sent[0].ephemeral


@pytest.mark.asyncio
async def test_refresh_keeps_the_old_profile_when_the_armory_rate_limits(patched_fetchers):
    patched_fetchers["summary"].return_value = {
        "__error__": "⚠️ El Armory de Warmane nos rate-limitó. Reintentá en ~60s."
    }
    interaction = FakeInteraction(message=_message_with_profile())
    old_embed = interaction.message.embeds[0]

    await _click_refresh(interaction)

    last = interaction.last_edit()
    assert last is not None
    assert last.content is None
    assert last.embed is old_embed, "a failed refresh must not wipe the profile in the channel"
    [notice] = [s for s in interaction.sent if s.kind == "followup"]
    assert notice.ephemeral
    assert "rate-limit" in _text(notice)


@pytest.mark.asyncio
async def test_refresh_warns_when_the_armory_answers_incomplete(patched_fetchers):
    # Sin estadísticas el perfil no se guarda en caché: quien apretó el botón
    # se entera de que puede no estar al día.
    patched_fetchers["statistics"].return_value = []
    interaction = FakeInteraction(message=_message_with_profile())

    await _click_refresh(interaction)

    [notice] = [s for s in interaction.sent if s.kind == "followup"]
    assert notice.ephemeral
    assert "respondió incompleto" in _text(notice)


@pytest.mark.asyncio
async def test_refresh_with_the_circuit_open_does_not_touch_the_armory(patched_fetchers):
    interaction = FakeInteraction(message=_message_with_profile())
    with patch(
        "src.controller.commands.personaje_refresh.ARMORY_CIRCUIT.is_open",
        return_value=True,
    ):
        await _click_refresh(interaction)

    patched_fetchers["summary"].assert_not_called()
    [reply] = interaction.sent
    assert reply.ephemeral
    assert "rate-limitado" in _text(reply)
    # Sin cooldown: cuando cierre el circuito se puede volver a intentar.
    assert _refresh_wait("Samsara", "Lordaeron", interaction.user.id) is None


def test_cooldowns_expire():
    _mark_live_profile("Demmir", "Lordaeron", user_id=1, now=1000.0)

    assert _refresh_wait("demmir", "lordaeron", 2, now=1000.0 + 10) == (
        "character",
        CHARACTER_COOLDOWN_SECONDS - 10,
    )
    assert _refresh_wait("Samsara", "Lordaeron", 1, now=1000.0 + 10) == ("user", USER_COOLDOWN_SECONDS - 10)
    assert _refresh_wait("Samsara", "Lordaeron", 1, now=1000.0 + USER_COOLDOWN_SECONDS) is None
    assert _refresh_wait("Demmir", "Lordaeron", 2, now=1000.0 + CHARACTER_COOLDOWN_SECONDS) is None
    # Otro reino es otro personaje.
    assert _refresh_wait("Demmir", "Icecrown", 2, now=1000.0 + 10) is None
