"""/p y el cron tienen que producir exactamente el mismo payload cacheado para
los mismos datos del armory. Antes eran dos copias de la lógica y los arreglos
había que hacerlos dos veces (el de Halion se aplicó en ambas por separado)."""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from tests.test_personaje import (
    _find_command,
    _happy_achievements,
    _happy_gear_data,
    _happy_summary,
    bot,  # noqa: F401  (fixture)
)

STATS_ROWS = [
    ["Lord Marrowgar kills (Icecrown 25 player)", "7"],
    ["Lord Marrowgar kills (Icecrown 10 player)", "12"],
    ["Victories over the Lich King (Icecrown 25 player)", "2"],
    ["Halion kills (Ruby Sanctum 25 player)", "- -"],
]

FETCHERS = {
    "_fetch_summary": _happy_summary(),
    "_fetch_specs": [{"name": "Blood", "active": True}, {"name": "Frost", "active": False}],
    "_fetch_professions": ["Engineering 450", "Enchanting 450"],
    "_fetch_gear_data": _happy_gear_data(),
    "_fetch_achievements": {**_happy_achievements(), "halion_25n_achieved": True},
    "_fetch_statistics": STATS_ROWS,
    "_fetch_guild_rank": "Officer",
    "_uwu_icc_bugfix_kills": {"25H": {"Lord Marrowgar": True}},
}


def _patch_fetchers(stack: ExitStack, module: str) -> None:
    import importlib

    mod = importlib.import_module(module)
    for name, value in FETCHERS.items():
        if hasattr(mod, name):
            stack.enter_context(patch(f"{module}.{name}", return_value=value))


def _cron_payload() -> dict:
    from tools.preload_personaje_cache import build_personaje_cache_entry

    with ExitStack() as stack:
        _patch_fetchers(stack, "tools.preload_personaje_cache")
        # El guild rank lo pide la lógica compartida en commands.py.
        _patch_fetchers(stack, "src.controller.commands")
        stack.enter_context(patch("tools.preload_personaje_cache.set_external_cache"))
        payload = build_personaje_cache_entry("Samsara", "Lordaeron")
    assert payload is not None
    return payload


@pytest.mark.asyncio
async def test_live_and_cron_cache_the_same_payload(bot, interaction):  # noqa: F811
    with ExitStack() as stack:
        _patch_fetchers(stack, "src.controller.commands")
        mock_set = stack.enter_context(
            patch("src.controller.commands.async_set_external_cache", new_callable=AsyncMock)
        )
        await _find_command(bot, "p").callback(interaction, nombre="Samsara")

    live_payloads = [c.args[3] for c in mock_set.await_args_list if c.args[0] == "command_personaje"]
    assert len(live_payloads) == 1, mock_set.await_args_list
    assert live_payloads[0] == _cron_payload()
