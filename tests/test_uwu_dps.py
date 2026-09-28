"""/dps con uwu-logs.

Casos reales de Lordaeron (sept. 2026) que mostraron los bugs:
- /character devuelve perfil para las 3 specs aunque no tengan logs
  (Whothefock solo juega Fire), y el bot consultaba /top para las 3: 72 POST
  y corte por timeout a los 30 s.
- /top ordena por DPS útil y con limit=1000 los tanks/healers quedaban afuera:
  Flappyaladin (Prot Pala) tiene 11 raids de LK 25N y el bot veía 2.
"""
from __future__ import annotations

import json

import pytest

import src.functions.uwu as uwu
from src.schemas.constants import UWU_PDPS_BOSS_ORDER, UWU_TOP_PLAYER_LIMIT


class FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}
        self.content = json.dumps(payload).encode()

    def json(self):
        return self._payload

    # _post_json_with_deadline lee la respuesta en streaming.
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size=65536):
        body = json.dumps(self._payload).encode()
        for i in range(0, len(body), chunk_size):
            yield body[i:i + chunk_size]


def _row(name, useful_amount, duration=100.0):
    return ["26-09-07--08-25--X", duration, "0375BA8", name, useful_amount, useful_amount, 2, []]


def _character(spec_with_data: int, spec_i: int, name: str, class_i: int = 3):
    bosses = {"The Lich King": {}, "Lord Marrowgar": {}}
    if spec_i == spec_with_data:
        bosses["The Lich King"] = {"raids": 40, "dps_max": 13713.81}
    return {"name": name, "class_i": class_i, "overall_points": 0, "bosses": bosses}


class FakeSession:
    def __init__(self, name, spec_with_data=2, top_rows=None, class_i=3):
        self.name = name
        self.spec_with_data = spec_with_data
        self.top_rows = top_rows if top_rows is not None else []
        self.class_i = class_i
        self.posts = []

    def get(self, url, timeout=None):
        spec_i = int(url.rsplit("/", 1)[1])
        return FakeResp(_character(self.spec_with_data, spec_i, self.name, self.class_i))

    def post(self, url, json=None, timeout=None, stream=False):
        self.posts.append(json)
        return FakeResp(self.top_rows)


@pytest.fixture(autouse=True)
def _isolated_caches(monkeypatch):
    monkeypatch.setattr(uwu, "get_external_cache", lambda *a, **k: None)
    monkeypatch.setattr(uwu, "set_external_cache", lambda *a, **k: None)
    monkeypatch.setattr(uwu.time, "sleep", lambda s: None)
    for cache in (
        uwu.UWU_CHARACTER_CACHE,
        uwu.UWU_SPEC_PLAYERS_CACHE,
        uwu.UWU_ICC_KILLS_CACHE,
        uwu.UWU_TOP_POINTS_CACHE,
        uwu.UWU_PLAYER_ROWS_CACHE,
        uwu.UWU_PDPS_SUMMARY_CACHE,
    ):
        cache.clear()


def test_only_main_spec_is_queried(monkeypatch):
    session = FakeSession("Whothefock", spec_with_data=2, top_rows=[_row("Whothefock", 1_300_000)])
    monkeypatch.setattr(uwu, "SESSION", session)

    summary = uwu._build_uwu_dps_summary("Whothefock", "Lordaeron", UWU_PDPS_BOSS_ORDER)

    # 6 bosses x 4 modos para una sola spec (antes: x3 specs).
    assert len(session.posts) == len(UWU_PDPS_BOSS_ORDER) * 4
    assert {(p["class_i"], p["spec_i"]) for p in session.posts} == {(3, 2)}
    assert summary["spec_i"] == 2
    assert not summary["timed_out"]
    assert summary["rows"][0]["Max DPS"] == "13000.00"


def test_tank_rows_beyond_first_thousand_are_found(monkeypatch):
    # Flappyaladin (Prot Pala): sus raids de LK 25N están más allá de la fila 1000.
    top_rows = [_row(f"Other{i}", 500_000) for i in range(2000)]
    top_rows += [_row("Flappyaladin", 25_000 + i) for i in range(11)]
    session = FakeSession("Flappyaladin", spec_with_data=2, top_rows=top_rows, class_i=4)
    monkeypatch.setattr(uwu, "SESSION", session)

    result = uwu._fetch_uwu_player_rows("Lordaeron", "The Lich King", "25N", 4, 2, "Flappyaladin")

    assert session.posts[0]["limit"] == str(UWU_TOP_PLAYER_LIMIT)
    assert session.posts[0]["best_only"] is False
    assert len(result["rows"]) == 11
    assert result["truncated"] is False


def test_truncated_list_marks_raids_as_minimum(monkeypatch):
    top_rows = [_row(f"Other{i}", 2_000_000) for i in range(UWU_TOP_PLAYER_LIMIT - 1)]
    top_rows.append(_row("Whothefock", 1_300_000))
    session = FakeSession("Whothefock", spec_with_data=2, top_rows=top_rows)
    monkeypatch.setattr(uwu, "SESSION", session)

    summary = uwu._build_uwu_dps_summary("Whothefock", "Lordaeron", ["The Lich King"])

    assert [r["Raids"] for r in summary["rows"]] == ["1+"] * 4


def test_spec_filter_overrides_main_spec(monkeypatch):
    session = FakeSession("Whothefock", spec_with_data=2)
    monkeypatch.setattr(uwu, "SESSION", session)

    uwu._build_uwu_dps_summary("Whothefock", "Lordaeron", ["The Lich King"], spec_filter="frost")

    assert {p["spec_i"] for p in session.posts} == {3}


def test_prot_keyword_is_class_aware(monkeypatch):
    # "prot" es spec 3 en Warrior pero 2 en Paladin: antes le pedía Ret a un pala.
    session = FakeSession("Flappyaladin", spec_with_data=1, class_i=4)
    monkeypatch.setattr(uwu, "SESSION", session)

    uwu._build_uwu_dps_summary("Flappyaladin", "Lordaeron", ["The Lich King"], spec_filter="prot")

    assert {(p["class_i"], p["spec_i"]) for p in session.posts} == {(4, 2)}


def test_no_default_mode_data_queries_all_three_specs(monkeypatch):
    # Sin datos en el modo por defecto (25H) no se sabe la spec: se piden las 3.
    # No spec_i=-1: la clase entera pierde jugadores (Flappyaladin, pala/Marrowgar 25H).
    session = FakeSession("Solo10n", spec_with_data=0, top_rows=[_row("Solo10n", 900_000)])
    monkeypatch.setattr(uwu, "SESSION", session)

    summary = uwu._build_uwu_dps_summary("Solo10n", "Lordaeron", ["The Lich King"])

    assert {(p["class_i"], p["spec_i"]) for p in session.posts} == {(3, 1), (3, 2), (3, 3)}
    assert summary["rows"][0]["Raids"] == "3"


def test_unknown_character_skips_top(monkeypatch):
    class UnknownSession(FakeSession):
        def get(self, url, timeout=None):
            return FakeResp({"name": "Unknown-0000000", "class_i": -1, "bosses": {}})

    session = UnknownSession("Nadie")
    monkeypatch.setattr(uwu, "SESSION", session)

    summary = uwu._build_uwu_dps_summary("Nadie", "Lordaeron", UWU_PDPS_BOSS_ORDER)

    assert summary["rows"] == []
    assert summary["__error__"]
    assert session.posts == []


def test_uwu_down_is_not_reported_as_no_data(monkeypatch):
    # 01:31 del 2026-09-28: uwu-logs no respondía y /dps dijo "No hay datos".
    class DownSession(FakeSession):
        def get(self, url, timeout=None):
            raise ConnectionError("uwu-logs caído")

    session = DownSession("Flappyaladin")
    monkeypatch.setattr(uwu, "SESSION", session)

    summary = uwu._build_uwu_dps_summary("Flappyaladin", "Lordaeron", UWU_PDPS_BOSS_ORDER)

    assert summary["uwu_down"] is True
    assert "no responde" in summary["__error__"]
    assert session.posts == []
    # No queda cacheado: el próximo /dps vuelve a intentar.
    assert not uwu.UWU_PDPS_SUMMARY_CACHE


def test_slow_download_is_cut_by_total_deadline(monkeypatch):
    class SlowResp(FakeResp):
        def iter_content(self, chunk_size=65536):
            while True:
                yield b" "

    class SlowSession(FakeSession):
        def post(self, url, json=None, timeout=None, stream=False):
            return SlowResp([])

    monkeypatch.setattr(uwu, "SESSION", SlowSession("Konomi"))
    clock = iter(range(0, 10_000))
    monkeypatch.setattr(uwu.time, "monotonic", lambda: next(clock))

    result = uwu._fetch_uwu_player_rows(
        "Lordaeron", "The Lich King", "25N", 0, 1, "Konomi", timeout_override=5
    )

    assert "cortada" in result["__error__"]


def test_rate_limited_request_is_retried(monkeypatch):
    # Logs de prod 01:48 del 2026-09-28: con 4 consultas en paralelo uwu-logs
    # devolvió 429 en 9 de 24 y esas filas salieron vacías.
    class RateLimitedSession(FakeSession):
        def post(self, url, json=None, timeout=None, stream=False):
            self.posts.append(json)
            if len(self.posts) == 1:
                return FakeResp([], status_code=429)
            return FakeResp(self.top_rows)

    session = RateLimitedSession("Flappyaladin", top_rows=[_row("Flappyaladin", 25_000)])
    monkeypatch.setattr(uwu, "SESSION", session)

    result = uwu._fetch_uwu_player_rows("Lordaeron", "The Lich King", "25N", 4, 2, "Flappyaladin")

    assert len(session.posts) == 2
    assert len(result["rows"]) == 1


def test_icc_kill_found_beyond_first_thousand_players(monkeypatch):
    # /p: en Lordaeron Fire tiene 3227 jugadores en Marrowgar 25N; con
    # limit=1000 el que estaba más abajo salía ❌ aunque tuviera el kill.
    top_rows = [_row(f"Other{i}", 2_000_000) for i in range(3000)]
    top_rows.append(_row("Lentito", 500_000))
    session = FakeSession("Lentito", spec_with_data=0, top_rows=top_rows)
    monkeypatch.setattr(uwu, "SESSION", session)

    kills = uwu._uwu_icc_bugfix_kills("Lentito", "Lordaeron")

    assert kills["Marrowgar"] == {"10H": "✅", "25N": "✅", "25H": "✅"}
    assert all(p["limit"] == "10000" and p["best_only"] is True for p in session.posts)


def test_icc_kills_unknown_when_uwu_is_down(monkeypatch):
    class DownSession(FakeSession):
        def get(self, url, timeout=None):
            raise ConnectionError("uwu-logs caído")

    monkeypatch.setattr(uwu, "SESSION", DownSession("Flappyaladin"))

    kills = uwu._uwu_icc_bugfix_kills("Flappyaladin", "Lordaeron")

    # Sin dato (None), no ❌, y sin cachear.
    assert kills["Marrowgar"] == {"10H": None, "25N": None, "25H": None}
    assert not uwu.UWU_ICC_KILLS_CACHE
