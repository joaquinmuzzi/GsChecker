"""El diagnóstico de latencia de uwu-logs corre al arrancar el bot: si uwu-logs
está caído no puede romper el arranque."""
from __future__ import annotations

import src.functions.uwu as uwu


class BrokenSession:
    def request(self, *args, **kwargs):
        raise ConnectionError("uwu-logs caído")


def test_probe_never_raises(monkeypatch, caplog):
    monkeypatch.setattr(uwu, "SESSION", BrokenSession())
    with caplog.at_level("INFO", logger="gschecker.uwu"):
        uwu.probe_uwu_latency()
    assert caplog.text.count("uwu_probe") == 3
    assert "uwu-logs caído" in caplog.text
