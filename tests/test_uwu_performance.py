"""Performance Points de uwu-logs en /p.

Datos reales de Lordaeron (2026-09-28): Whothefock (Fire) tiene
overall_points=9869.3 y overall_rank=37 en /character, y /top_points de Fire
devuelve 3174 jugadores.
"""
from __future__ import annotations

import src.functions.uwu as uwu
from src.functions.embeds import _build_personaje_embed, _format_uwu_performance
from tests.test_uwu_dps import FakeResp, FakeSession, _isolated_caches  # noqa: F401


class PointsSession(FakeSession):
    def __init__(self, name, total_players=3174):
        super().__init__(name, spec_with_data=2)
        self.total_players = total_players

    def get(self, url, timeout=None):
        spec_i = int(url.rsplit("/", 1)[1])
        points = 9869.29607804684 if spec_i == 2 else 0.0
        return FakeResp({
            "name": self.name,
            "class_i": 3,
            "overall_points": points,
            "overall_rank": 37 if spec_i == 2 else 0,
            "bosses": {"The Lich King": {"raids": 40} if spec_i == 2 else {}},
        })

    def post(self, url, json=None, timeout=None, stream=False):
        self.posts.append((url, json))
        return FakeResp([[f"P{i}", 50.0, 5000] for i in range(self.total_players)])


def test_performance_uses_main_spec_and_ranked_total(monkeypatch):
    session = PointsSession("Whothefock")
    monkeypatch.setattr(uwu, "SESSION", session)

    perf = uwu._fetch_uwu_performance("Whothefock", "Lordaeron")

    assert perf == {"spec": "Fire", "points": 98.69, "rank": 37, "total": 3174}
    assert session.posts[0][0].endswith("/top_points")
    assert session.posts[0][1] == {"server": "Lordaeron", "class_i": 3, "spec_i": 2}


def test_ranked_total_is_shared_between_characters(monkeypatch):
    session = PointsSession("Whothefock")
    monkeypatch.setattr(uwu, "SESSION", session)

    uwu._fetch_uwu_performance("Whothefock", "Lordaeron")
    session.name = "Harryplones"
    uwu._fetch_uwu_performance("Harryplones", "Lordaeron")

    assert len(session.posts) == 1


def test_performance_unknown_when_uwu_is_down(monkeypatch):
    class DownSession(FakeSession):
        def get(self, url, timeout=None):
            raise ConnectionError("uwu-logs caído")

    monkeypatch.setattr(uwu, "SESSION", DownSession("Whothefock"))

    assert uwu._fetch_uwu_performance("Whothefock", "Lordaeron") is None


def test_format_line():
    perf = {"spec": "Fire", "points": 98.69, "rank": 37, "total": 3174}
    assert _format_uwu_performance(perf) == "Fire · **#37** (top 1,2 %)"
    assert _format_uwu_performance({**perf, "total": None}) == "Fire · **#37**"
    assert _format_uwu_performance({**perf, "rank": None}) == ""
    assert _format_uwu_performance({}) == ""
    assert _format_uwu_performance(None) == ""


def test_embed_shows_field_only_with_points():
    args = ("Whothefock", 6000, 80, "Gnome", "Mage", "Fire", "<Guild>",
            False, False, False, False, {}, {}, [], [])
    with_perf = _build_personaje_embed(
        *args, uwu_performance={"spec": "Fire", "points": 98.69, "rank": 37, "total": 3174}
    )
    without = _build_personaje_embed(*args, uwu_performance={})

    assert "UwU Logs" in [f.name for f in with_perf.fields]
    assert "UwU Logs" not in [f.name for f in without.fields]
