"""Fixtures compartidas para tests de comandos.

Como el bot usa solo slash commands (bot.tree.command) y dpytest no
soporta interactions (v0.7 sigue centrado en el prefix commands API),
implementamos un FakeInteraction que captura todas las llamadas que
los handlers hacen sobre `interaction.*` y las expone en `.sent` para
que los tests hagan assertions sobre lo que el bot habría enviado.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

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
        self._parent.sent.append(SentPayload(kind="defer"))

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
class FakeInteraction:
    user: FakeUser = field(default_factory=FakeUser)
    guild: FakeGuild = field(default_factory=FakeGuild)
    sent: list[SentPayload] = field(default_factory=list)
    response: FakeResponse = field(init=False)
    followup: FakeFollowup = field(init=False)
    command: Any = None

    def __post_init__(self) -> None:
        self.response = FakeResponse(self)
        self.followup = FakeFollowup(self)

    async def edit_original_response(
        self,
        *,
        content: str | None = None,
        embed: Any = None,
        view: Any = None,
    ) -> None:
        self.sent.append(
            SentPayload(kind="edit", content=content, embed=embed, view=view)
        )

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
