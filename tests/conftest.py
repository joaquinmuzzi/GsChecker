"""Fixtures compartidas para tests de comandos.

Como el bot usa solo slash commands (bot.tree.command) y dpytest no
soporta interactions (v0.7 sigue centrado en el prefix commands API),
implementamos un FakeInteraction que captura todas las llamadas que
los handlers hacen sobre `interaction.*` y las expone en `.sent` para
que los tests hagan assertions sobre lo que el bot habría enviado.
"""

from __future__ import annotations

import copy
import os
import sys
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import discord
import pytest
from discord.ext import commands as discord_commands

from src.controller.commands import register_commands
from src.services.refresh_cooldown import _reset_refresh_cooldowns
from tests.helpers import _happy_achievements, _happy_gear_data, _happy_summary

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DISCORD_TOKEN", "test-token-not-used")


@dataclass
class SentPayload:
    """Representa un send/edit capturado, con los kwargs relevantes."""

    kind: str
    content: str | None = None
    embed: Any = None
    view: Any = None
    ephemeral: bool = False
    thinking: bool = False


class FakeUser:
    def __init__(self, user_id: int = 42, name: str = "Frodo"):
        self.id = user_id
        self.name = name


class FakeGuild:
    def __init__(self, guild_id: int = 100, name: str = "Testguild"):
        self.id = guild_id
        self.name = name


class FakeResponse:
    def __init__(self, parent: FakeInteraction) -> None:
        self._parent = parent
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def defer(self, thinking: bool = False) -> None:
        self._done = True
        self._parent.sent.append(SentPayload(kind="defer", thinking=thinking))

    async def send_message(
        self,
        content: str | None = None,
        *,
        embed: Any = None,
        view: Any = None,
        ephemeral: bool = False,
    ) -> None:
        self._done = True
        self._parent.sent.append(
            SentPayload(
                kind="send_message",
                content=content,
                embed=embed,
                view=view,
                ephemeral=ephemeral,
            )
        )


class FakeFollowup:
    def __init__(self, parent: FakeInteraction) -> None:
        self._parent = parent

    async def send(
        self,
        content: str | None = None,
        *,
        embed: Any = None,
        view: Any = None,
        ephemeral: bool = False,
    ) -> None:
        self._parent.sent.append(
            SentPayload(
                kind="followup",
                content=content,
                embed=embed,
                view=view,
                ephemeral=ephemeral,
            )
        )


@dataclass
class FakeMessage:
    content: str | None = None
    embeds: list[Any] = field(default_factory=list)
    edited_at: Any = None


def _stored_message(payload: SentPayload) -> FakeMessage:
    """El mensaje como lo devuelve Discord: otro objeto Embed, con los
    valores de los campos recortados."""
    embeds = []
    if payload.embed is not None:
        # to_dict() comparte los dicts de los campos: copiar antes de tocar.
        data = copy.deepcopy(payload.embed.to_dict())
        for f in data.get("fields", []):
            f["value"] = f["value"].strip()
        embeds.append(discord.Embed.from_dict(data))
    return FakeMessage(content=payload.content, embeds=embeds)


@dataclass
class FakeInteraction:
    user: FakeUser = field(default_factory=FakeUser)
    guild: FakeGuild = field(default_factory=FakeGuild)
    sent: list[SentPayload] = field(default_factory=list)
    response: FakeResponse = field(init=False)
    followup: FakeFollowup = field(init=False)
    command: Any = None
    # El mensaje que tiene el botón, en las interacciones de componentes.
    message: Any = None
    # Simula que Discord se quedó con la anteúltima edición (/p Kuvez,
    # 2026-10-07).
    keeps_previous_edit: bool = False
    _original: FakeMessage | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.response = FakeResponse(self)
        self.followup = FakeFollowup(self)

    async def edit_original_response(
        self,
        *,
        content: str | None = None,
        embed: Any = None,
        view: Any = None,
    ) -> FakeMessage:
        payload = SentPayload(kind="edit", content=content, embed=embed, view=view)
        self.sent.append(payload)
        return _stored_message(payload)

    async def original_response(self) -> FakeMessage:
        # Como discord.py: solo la primera llamada lee de Discord.
        if self._original is None:
            edits = [s for s in self.sent if s.kind == "edit"]
            stored = edits[-2] if self.keeps_previous_edit else edits[-1]
            self._original = _stored_message(stored)
        return self._original

    def last_edit(self) -> SentPayload | None:
        for s in reversed(self.sent):
            if s.kind == "edit":
                return s
        return None

    def last_sent(self) -> SentPayload | None:
        return self.sent[-1] if self.sent else None


@pytest.fixture
def interaction() -> FakeInteraction:
    return FakeInteraction()


@pytest.fixture(autouse=True)
def _no_final_edit_check_wait(monkeypatch):
    monkeypatch.setattr("src.controller.commands.personaje_live.PERSONAJE_FINAL_CHECK_SECONDS", 0)


@pytest.fixture(autouse=True)
def _fresh_refresh_cooldowns():
    # Cada /p en vivo arranca el cooldown del botón Actualizar: no se arrastra entre tests.
    _reset_refresh_cooldowns()
    yield
    _reset_refresh_cooldowns()


@pytest.fixture
def bot() -> discord_commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    b = discord_commands.Bot(command_prefix="!", intents=intents)
    register_commands(b)
    return b


# Cada comando importa los fetchers por nombre, así que se patchean en cada
# módulo que los usa (el mismo mock en todos, como cuando había un solo
# commands.py).
_COMMANDS = "src.controller.commands"
FETCHER_TARGETS = {
    "summary": ("_fetch_summary", ("personaje_live", "dps", "ia")),
    "specs": ("_fetch_specs", ("personaje_live", "ia")),
    "professions": ("_fetch_professions", ("personaje_live",)),
    "gear": ("_fetch_gear_data", ("personaje_live", "ia")),
    "achievements": ("_fetch_achievements", ("personaje_live",)),
    "statistics": ("_fetch_statistics", ("personaje_live",)),
    "uwu_icc": ("_uwu_icc_bugfix_kills", ("personaje_live",)),
    "uwu_perf": ("_fetch_uwu_performance", ("personaje", "personaje_live")),
}


@pytest.fixture
def patched_fetchers():
    """Patchea todas las funciones armory + uwu que /p invoca por executor.

    Los tests solo tienen que sobrescribir el retorno de la función que
    les interesa (ej: patched_fetchers['summary'].return_value = ...) y
    ejecutar el comando.
    """
    mocks = {key: MagicMock(name=attr) for key, (attr, _) in FETCHER_TARGETS.items()}
    # El guild rank lo pide la lógica del perfil compartida con el cron.
    mocks["guild_rank"] = MagicMock(name="_fetch_guild_rank")
    with ExitStack() as stack:
        for key, (attr, modules) in FETCHER_TARGETS.items():
            for module in modules:
                stack.enter_context(patch(f"{_COMMANDS}.{module}.{attr}", mocks[key]))
        stack.enter_context(patch("src.services.profile._fetch_guild_rank", mocks["guild_rank"]))

        mocks["summary"].return_value = _happy_summary()
        mocks["specs"].return_value = [
            {"name": "Blood", "active": True},
            {"name": "Frost", "active": False},
        ]
        mocks["professions"].return_value = ["Engineering 450", "Enchanting 450"]
        mocks["gear"].return_value = _happy_gear_data()
        mocks["achievements"].return_value = _happy_achievements()
        mocks["statistics"].return_value = []
        mocks["guild_rank"].return_value = "Gran Canciller"
        mocks["uwu_icc"].return_value = {}
        mocks["uwu_perf"].return_value = {}
        yield mocks
