"""End-to-end del /p command con todo el fetch armory + uwu mockeado.

Cubre los 3 escenarios que corresponden a los bugs que ya vimos:

  1. Happy path — datos válidos → embed final con nombre/GS/etc.
  2. Rate-limited — _fetch_summary devuelve __error__ 'rate-limitó' →
     el usuario ve ese mensaje textual, no un embed corrupto.
  3. Personaje no existe — _fetch_summary devuelve __error__ 'No se
     encontró...' → mensaje textual correcto (no falso positivo).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tests.helpers import _find_command, _happy_achievements, _happy_summary


@pytest.mark.asyncio
async def test_personaje_happy_path_ships_embed_with_character_data(bot, interaction, patched_fetchers):
    p_cmd = _find_command(bot, "p")
    await p_cmd.callback(interaction, nombre="Samsara")

    edit = interaction.last_edit()
    assert edit is not None, f"expected an edit, got sent={interaction.sent}"
    assert edit.embed is not None, "final edit should carry the character embed"
    assert edit.content is None

    author_name = (edit.embed.author.name if edit.embed.author is not None else "") or ""
    text = f"{author_name} {edit.embed.title or ''} {edit.embed.description or ''}"
    for field in getattr(edit.embed, "fields", []):
        text += f" {field.name} {field.value}"

    assert "Samsara" in text
    assert "Death Knight" in text or "Draenei" in text


@pytest.mark.asyncio
async def test_personaje_rate_limited_shows_rate_limit_message(bot, interaction, patched_fetchers):
    """Regression: reported bug where existing characters showed 'no existe'
    because the circuit breaker was open. Now they should see a rate-limit
    message with a wait hint."""
    patched_fetchers["summary"].return_value = {
        "__error__": "⚠️ El Armory de Warmane nos rate-limitó. Reintentá en ~60s."
    }

    p_cmd = _find_command(bot, "p")
    await p_cmd.callback(interaction, nombre="Novatizimu")

    edit = interaction.last_edit()
    assert edit is not None
    assert edit.embed is None, "rate-limit message must be plain content, not an embed"
    assert edit.content is not None
    assert "rate-limit" in edit.content.lower()
    assert "no se encontr" not in edit.content.lower(), "must not falsely claim the character doesn't exist"


@pytest.mark.asyncio
async def test_personaje_not_found_shows_not_found_message(bot, interaction, patched_fetchers):
    patched_fetchers["summary"].return_value = {
        "__error__": "⚠️ No se encontró el personaje 'Xxxxx' en Lordaeron."
    }

    p_cmd = _find_command(bot, "p")
    await p_cmd.callback(interaction, nombre="Xxxxx")

    edit = interaction.last_edit()
    assert edit is not None
    assert edit.embed is None
    assert edit.content is not None
    assert "no se encontr" in edit.content.lower()


@pytest.mark.asyncio
async def test_personaje_rejects_invalid_realm(bot, interaction, patched_fetchers):
    p_cmd = _find_command(bot, "p")
    await p_cmd.callback(interaction, nombre="Samsara", reino="Nagrand")

    sent = interaction.last_sent()
    assert sent is not None
    text = (sent.content or "") + str(sent.embed or "")
    assert "reino inválido" in text.lower() or "reino invalido" in text.lower()


@pytest.mark.asyncio
async def test_personaje_non_80_short_circuits(bot, interaction, patched_fetchers):
    """A level 79 character shouldn't reach the achievements/gear pipeline —
    /p only supports 80s."""
    patched_fetchers["summary"].return_value = {
        **_happy_summary(),
        "level": 79,
    }

    p_cmd = _find_command(bot, "p")
    await p_cmd.callback(interaction, nombre="Samsara")

    edit = interaction.last_edit()
    assert edit is not None
    assert edit.embed is None
    assert edit.content is not None
    assert "no es nivel 80" in edit.content.lower()


def _ruby_sanctum_field_value(embed):
    for field in embed.fields:
        if field.name == "Ruby Sanctum":
            return field.value
    raise LookupError("Ruby Sanctum field not found in embed")


def _empty_halion_statistics_rows() -> list[list[str]]:
    """Warmane's /statistics page reports "- -" for every Halion row even for
    characters with dated Halion achievements (e.g. Srpingu/Lordaeron earned
    Heroic 25 on 07/06/2026), so these counters can't be used as a kill check."""
    return [
        ["Halion kills (Ruby Sanctum 25 player)", "- -"],
        ["Halion kills (Ruby Sanctum 10 player)", "- -"],
        ["Halion kills (Heroic Ruby Sanctum 10 player)", "- -"],
        ["Halion kills (Heroic Ruby Sanctum 25 player)", "- -"],
    ]


class TestHalionIgnoresBrokenStatistics:
    """Regression: the bot used to require a non-zero Halion statistic on top of
    the achievement, which turned every real Halion kill into ❌."""

    @pytest.mark.asyncio
    async def test_achievement_shows_check_even_with_empty_statistics(
        self, bot, interaction, patched_fetchers
    ):
        patched_fetchers["achievements"].return_value = {
            **_happy_achievements(),
            "halion_10n_achieved": True,
            "halion_10h_achieved": True,
            "halion_25n_achieved": True,
            "halion_25h_achieved": True,
        }
        patched_fetchers["statistics"].return_value = _empty_halion_statistics_rows()

        p_cmd = _find_command(bot, "p")
        await p_cmd.callback(interaction, nombre="Srpingu")

        edit = interaction.last_edit()
        assert edit is not None
        assert edit.embed is not None
        rs_value = _ruby_sanctum_field_value(edit.embed)
        halion_row = next(line for line in rs_value.splitlines() if line.startswith("Halion"))
        assert "❌" not in halion_row, rs_value
        assert halion_row.count("✅") == 4, rs_value


@pytest.mark.asyncio
async def test_cached_profile_without_ranking_gets_it(bot, interaction, patched_fetchers):
    # Novatizimu (2026-09-28): perfil cacheado por el cron antes del deploy del
    # ranking de uwu-logs; /p lo servía sin el campo hasta que venciera (25 h).
    old_payload = {
        "nombre_char": "Novatizimu",
        "server": "Lordaeron",
        "gs": 6398,
        "nivel": 80,
        "raza": "Human",
        "clase": "Warlock",
        "spec_display": "Affliction",
        "guild_display": "<The Order of the Ring>",
        "guild_rank": "Officer",
        "halion_10n_achieved": True,
        "halion_10h_achieved": True,
        "halion_25n_achieved": True,
        "halion_25h_achieved": True,
        "icc_10": {},
        "icc_25": {},
        "missing_enchants": [],
        "missing_gems": [],
        "uwu_icc_kills": {},
        "spec_gs_entries": [],
        "active_spec_name": "Affliction",
    }
    patched_fetchers["uwu_perf"].return_value = {
        "spec": "Demonology",
        "points": 44.65,
        "rank": 895,
        "total": 1869,
    }
    with patch(
        "src.controller.commands.personaje.async_get_external_cache",
        new_callable=AsyncMock,
        return_value=old_payload,
    ):
        await _find_command(bot, "p").callback(interaction, nombre="Novatizimu")

    embed = interaction.last_edit().embed
    values = {f.name: f.value for f in embed.fields}
    assert values["Leaderboard"] == "Demonology · **#895** (top 47,9 %)"
    patched_fetchers["summary"].assert_not_called()


@pytest.mark.asyncio
async def test_cached_profile_with_empty_ranking_is_refetched(bot, interaction, patched_fetchers):
    # Epillef (2026-09-28): el cron guardó uwu_performance={} porque uwu-logs no
    # respondió; /p lo servía sin Leaderboard hasta que venciera la caché.
    payload = {
        "nombre_char": "Epillef",
        "server": "Lordaeron",
        "gs": 6072,
        "nivel": 80,
        "raza": "Night Elf",
        "clase": "Druid",
        "spec_display": "Balance",
        "guild_display": "<Brotherhood Of Silence>",
        "guild_rank": "Member",
        "halion_10n_achieved": False,
        "halion_10h_achieved": False,
        "halion_25n_achieved": False,
        "halion_25h_achieved": False,
        "icc_10": {},
        "icc_25": {},
        "missing_enchants": [],
        "missing_gems": [],
        "uwu_icc_kills": {},
        "spec_gs_entries": [],
        "active_spec_name": "Balance",
        "uwu_performance": {},
    }
    patched_fetchers["uwu_perf"].return_value = {
        "spec": "Balance",
        "points": 29.69,
        "rank": 2034,
        "total": 3143,
    }
    with patch(
        "src.controller.commands.personaje.async_get_external_cache",
        new_callable=AsyncMock,
        return_value=payload,
    ):
        await _find_command(bot, "p").callback(interaction, nombre="Epillef")

    values = {f.name: f.value for f in interaction.last_edit().embed.fields}
    assert values["Leaderboard"] == "Balance · **#2034** (top 64,7 %)"
    patched_fetchers["uwu_perf"].assert_called_once_with("Epillef", "Lordaeron", "Druid")


def _icc_line(embed, boss):
    icc = next(f.value for f in embed.fields if f.name == "Icecrown Citadel")
    return next(line for line in icc.splitlines() if line.startswith(boss))


@pytest.mark.asyncio
async def test_hung_uwu_lookup_still_ends_in_final_state(bot, interaction, patched_fetchers, monkeypatch):
    # /p Suramar (2026-09-28): Marrowgar/Deathwhisper quedaron en ⌛ para siempre.
    # Aunque uwu-logs no termine, el embed tiene que llegar a un estado final.
    import threading

    release = threading.Event()
    patched_fetchers["uwu_icc"].side_effect = lambda *a, **k: release.wait(10) or {}
    monkeypatch.setattr("src.controller.commands.personaje_live.PERSONAJE_UWU_WAIT_SECONDS", 0.1)
    try:
        await _find_command(bot, "p").callback(interaction, nombre="Suramar")
    finally:
        release.set()

    final = interaction.last_edit().embed
    for boss in ("Marrowgar", "Deathwhisper"):
        line = _icc_line(final, boss)
        assert "⌛" not in line, line
        assert "⏳" not in line, line


@pytest.mark.asyncio
async def test_storming_the_citadel_marks_kills_without_waiting_uwu(bot, interaction, patched_fetchers):
    # Storming the Citadel 25N (4604) completo: Marrowgar/Deathwhisper 25N ✅ ya
    # en el primer embed, antes de que responda uwu-logs.
    patched_fetchers["achievements"].return_value = {
        **_happy_achievements(),
        "storming_25n_achieved": True,
    }
    await _find_command(bot, "p").callback(interaction, nombre="Suramar")

    first_embed = next(s.embed for s in interaction.sent if s.kind == "edit" and s.embed)
    for boss in ("Marrowgar", "Deathwhisper"):
        cells = [c.strip() for c in _icc_line(first_embed, boss).split("|")]
        assert cells[3].startswith("✅"), cells  # columna 25N


@pytest.mark.asyncio
async def test_final_embed_is_resent_when_discord_keeps_the_loading_one(bot, interaction, patched_fetchers):
    # /p Kuvez (2026-10-07): Discord aceptó la edición final sin error, pero el
    # mensaje quedó con el embed de carga (⌛ en Marrowgar/Deathwhisper).
    interaction.keeps_previous_edit = True
    await _find_command(bot, "p").callback(interaction, nombre="Kuvez")

    edits = [s for s in interaction.sent if s.kind == "edit"]
    assert edits[-1].embed is edits[-2].embed, "the final embed should be re-sent"
    for boss in ("Marrowgar", "Deathwhisper"):
        line = _icc_line(edits[-1].embed, boss)
        assert "⌛" not in line, line
        assert "⏳" not in line, line


@pytest.mark.asyncio
async def test_final_embed_is_sent_once_when_discord_keeps_it(bot, interaction, patched_fetchers):
    await _find_command(bot, "p").callback(interaction, nombre="Kuvez")

    edits = [s for s in interaction.sent if s.kind == "edit"]
    assert edits[-1].embed is not edits[-2].embed
