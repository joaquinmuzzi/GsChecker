"""/logs: últimos reportes de uwu-logs de un personaje.

Datos reales (2026-09-28): POST /logs_list {"server", "player"} devuelve los
ids de los 479 reportes de Flappyaladin, sin orden y sin bosses; con "fight"
filtra los que tienen esa pelea.
"""
from __future__ import annotations

import pytest

import src.functions.uwu as uwu
from src.functions.embeds import _build_uwu_logs_embed, _build_uwu_logs_view
from tests.test_personaje import _find_command, bot  # noqa: F401
from tests.test_uwu_dps import FakeResp, FakeSession, _isolated_caches  # noqa: F401

REPORTS = {
    "26-09-21--23-00--Chiy--Lordaeron": set(),
    "26-09-27--19-01--Myamoto--Lordaeron": set(uwu.UWU_LOGS_ICC_FIGHTS),
    "26-09-27--19-00--Tyreliaqt--Lordaeron": set(uwu.UWU_LOGS_ICC_FIGHTS[:10]),
    "24-08-31--19-53--Deion--Lordaeron": set(uwu.UWU_LOGS_ICC_FIGHTS) | {"Halion"},
}


class LogsSession(FakeSession):
    def post(self, url, json=None, timeout=None, stream=False):
        self.posts.append((url, json))
        fight = json.get("fight")
        return FakeResp([r for r, fights in REPORTS.items() if not fight or fight in fights])


class DownSession(FakeSession):
    def post(self, url, json=None, timeout=None, stream=False):
        raise ConnectionError("uwu-logs caído")


def test_recent_logs_sorted_with_raid_labels(monkeypatch):
    session = LogsSession("Flappyaladin")
    monkeypatch.setattr(uwu, "SESSION", session)

    data = uwu._fetch_uwu_recent_logs("Flappyaladin", "Lordaeron")

    assert data["total"] == 4
    assert [(r["date"], r["label"], r["author"]) for r in data["reports"]] == [
        ("27-09-26", "ICC 12/12", "Myamoto"),
        ("27-09-26", "ICC 10/12", "Tyreliaqt"),
        ("21-09-26", "otro raid", "Chiy"),
        ("31-08-24", "ICC 12/12 + Halion", "Deion"),
    ]
    assert all(p[0].endswith("/logs_list") for p in session.posts)
    assert all(p[1]["player"] == "Flappyaladin" for p in session.posts)

    # Cacheado: la segunda vez no consulta uwu-logs.
    session.posts.clear()
    uwu._fetch_uwu_recent_logs("Flappyaladin", "Lordaeron")
    assert session.posts == []


def test_recent_logs_none_when_uwu_is_down(monkeypatch):
    monkeypatch.setattr(uwu, "SESSION", DownSession("Flappyaladin"))
    assert uwu._fetch_uwu_recent_logs("Flappyaladin", "Lordaeron") is None


def test_embed_and_view():
    data = {"total": 479, "reports": [{
        "id": "26-09-27--19-01--Myamoto--Lordaeron", "date": "27-09-26",
        "author": "Myamoto", "label": "ICC 12/12",
    }]}
    embed = _build_uwu_logs_embed("Flappyaladin", "Lordaeron", data)
    view = _build_uwu_logs_view("Flappyaladin", "Lordaeron")

    assert embed.description == (
        "`27-09-26` · ICC 12/12 · por Myamoto · "
        "[ver](https://uwu-logs.xyz/reports/26-09-27--19-01--Myamoto--Lordaeron/)"
    )
    assert embed.footer.text == "Lordaeron · 479 reportes en total"
    assert view.children[0].url == (
        "https://uwu-logs.xyz/logs_list?server=Lordaeron&player=Flappyaladin"
    )


@pytest.mark.asyncio
async def test_command_without_logs(bot, interaction, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        "src.controller.commands._fetch_uwu_recent_logs",
        lambda nombre, server: {"total": 0, "reports": []},
    )
    await _find_command(bot, "logs").callback(interaction, nombre="nadie")

    assert "No hay logs en UwU Logs para Nadie" in interaction.last_edit().content


@pytest.mark.asyncio
async def test_command_when_uwu_is_down(bot, interaction, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        "src.controller.commands._fetch_uwu_recent_logs", lambda nombre, server: None
    )
    await _find_command(bot, "logs").callback(interaction, nombre="Flappyaladin")

    assert "no responde" in interaction.last_edit().content
