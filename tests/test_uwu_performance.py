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

    ranking = [f for f in with_perf.fields if "(top " in f.value]
    assert len(ranking) == 1 and ranking[0].name == "Leaderboard"
    assert not [f for f in without.fields if "(top " in f.value]


class MultiSpecSession(FakeSession):
    """Flappyaladin (pala): más logs de Holy (14 bosses) que de Ret (13)."""

    def __init__(self, name, specs):
        super().__init__(name, class_i=4)
        self.specs = specs  # spec_i -> (bosses_with_data, overall_points, rank)

    def get(self, url, timeout=None):
        spec_i = int(url.rsplit("/", 1)[1])
        n_bosses, points, rank = self.specs.get(spec_i, (0, 0.0, 0))
        bosses = {f"Boss{i}": {"raids": 1} for i in range(n_bosses)}
        return FakeResp({
            "name": self.name, "class_i": 4, "overall_points": points,
            "overall_rank": rank, "bosses": bosses,
        })

    def post(self, url, json=None, timeout=None, stream=False):
        self.posts.append((url, json))
        return FakeResp([["P", 50.0, 5000]] * 1000)


def test_dps_spec_preferred_over_healer(monkeypatch):
    specs = {1: (14, 8523.6, 220), 2: (11, 8877.4, 106), 3: (13, 6695.7, 672)}
    monkeypatch.setattr(uwu, "SESSION", MultiSpecSession("Flappyaladin", specs))

    perf = uwu._fetch_uwu_performance("Flappyaladin", "Lordaeron")

    assert perf["spec"] == "Retribution"
    assert perf["rank"] == 672


def test_healer_only_keeps_healer_spec(monkeypatch):
    specs = {1: (12, 7810.4, 363)}
    monkeypatch.setattr(uwu, "SESSION", MultiSpecSession("Soloholy", specs))

    perf = uwu._fetch_uwu_performance("Soloholy", "Lordaeron")

    assert perf["spec"] == "Holy"


class UnknownSession(FakeSession):
    """Ganji (2026-09-28): /character devuelve "Unknown-Ganji" en las 3 specs,
    pero figura en los rankings de Fire."""

    def get(self, url, timeout=None):
        return FakeResp({"name": f"Unknown-{self.name}", "class_i": 0, "bosses": {}})

    def post(self, url, json=None, timeout=None, stream=False):
        self.posts.append((url, json))
        if url.endswith("/top_points"):
            names = [f"P{i}" for i in range(3000)]
            if json["spec_i"] == 2:
                names.insert(1499, self.name)
            return FakeResp([[n, 50.0, 5000] for n in names])
        rows = [["26-09-07--08-25--X", 100.0, "0000001", f"Other{i}", 1_000_000, 1_000_000, 2, []]
                for i in range(2000)]
        if json["spec_i"] == 2:
            rows.append(["26-09-07--08-25--X", 100.0, "0000002", self.name, 500_000, 500_000, 2, []])
        return FakeResp(rows)


def test_unknown_profile_ranking_uses_armory_class(monkeypatch):
    monkeypatch.setattr(uwu, "SESSION", UnknownSession("Ganji"))

    perf = uwu._fetch_uwu_performance("Ganji", "Lordaeron", "Mage")

    assert perf == {"spec": "Fire", "points": None, "rank": 1500, "total": 3001}
    assert uwu._fetch_uwu_performance("Ganji", "Lordaeron") == {}


def test_unknown_profile_icc_kills_use_armory_class(monkeypatch):
    session = UnknownSession("Ganji")
    monkeypatch.setattr(uwu, "SESSION", session)

    kills = uwu._uwu_icc_bugfix_kills("Ganji", "Lordaeron", "Mage")

    assert kills["Marrowgar"]["25N"] == "✅"
    assert {p[1]["class_i"] for p in session.posts} == {3}


def test_unknown_profile_dps_uses_armory_class(monkeypatch):
    session = UnknownSession("Ganji")
    monkeypatch.setattr(uwu, "SESSION", session)

    summary = uwu._build_uwu_dps_summary("Ganji", "Lordaeron", ["The Lich King"], char_class="Mage")

    assert {(p[1]["class_i"], p[1]["spec_i"]) for p in session.posts} == {(3, 1), (3, 2), (3, 3)}
    assert any(r["Raids"] == "1" for r in summary["rows"])


def test_partial_uwu_failure_is_unknown_not_unranked(monkeypatch):
    # Cron del 2026-09-28: a Epillef (druida) le dio timeout /character de Balance
    # (su única spec con puntos) y respondieron Feral y Resto con 0 puntos; se
    # guardó "sin ranking" ({}) por 25 h. Tiene que ser None: dato desconocido.
    class PartialSession(FakeSession):
        def get(self, url, timeout=None):
            spec_i = int(url.rsplit("/", 1)[1])
            if spec_i == 1:
                raise TimeoutError("Read timed out")
            return FakeResp({"name": self.name, "class_i": 1, "overall_points": 0.0,
                             "overall_rank": 1355, "bosses": {}})

    monkeypatch.setattr(uwu, "SESSION", PartialSession("Epillef"))

    assert uwu._fetch_uwu_performance("Epillef", "Lordaeron", "Druid") is None
