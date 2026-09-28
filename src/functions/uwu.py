import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait

from src.schemas.constants import (
    SESSION,
    HTTP_TIMEOUT,
    UWU_BASE,
    UWU_BOSS_MODE,
    UWU_BOSS_SHORT,
    UWU_CLASS_INDEX,
    UWU_MODES_ALL,
    UWU_SPEC_KEYWORDS,
    UWU_SPEC_KEYWORDS_BY_CLASS,
    UWU_CHARACTER_CACHE,
    UWU_CHARACTER_TTL,
    UWU_TOP_CACHE,
    UWU_TOP_TTL,
    UWU_PDPS_SUMMARY_CACHE,
    UWU_PDPS_SUMMARY_TTL,
    UWU_ICC_KILLS_CACHE,
    UWU_ICC_KILLS_TTL,
    UWU_PLAYER_ROWS_CACHE,
    UWU_PLAYER_ROWS_TTL,
    UWU_TOP_MAX_ATTEMPTS,
    UWU_TOP_PLAYER_LIMIT,
    UWU_SPEC_PLAYERS_CACHE,
    UWU_SPEC_PLAYERS_TTL,
    UWU_NON_DPS_SPECS,
    UWU_SPEC_NAMES,
    UWU_TOP_POINTS_CACHE,
    UWU_TOP_POINTS_TTL,
    UWU_LOGS_CACHE,
    UWU_LOGS_ICC_FIGHTS,
    UWU_LOGS_LIMIT,
    UWU_LOGS_OTHER_FIGHTS,
    UWU_LOGS_TTL,
    UWU_TOP_PLAYER_TIMEOUT,
    UWU_TOP_WORKERS,
)
from src.db.postgres import get_external_cache, set_external_cache
from src.functions.cache import _cache_get, _cache_set

logger = logging.getLogger("gschecker.uwu")


def _fetch_uwu_character(nombre: str, server: str, spec_i: int):
    cache_key = (nombre, server, spec_i)
    cached = _cache_get(UWU_CHARACTER_CACHE, cache_key, UWU_CHARACTER_TTL)
    if cached is not None:
        return cached

    persistent_cache_key = f"uwu:character:{server}:{nombre.lower()}:{spec_i}"
    cached = get_external_cache(
        "uwu_character", persistent_cache_key, UWU_CHARACTER_TTL
    )
    if cached is not None:
        _cache_set(UWU_CHARACTER_CACHE, cache_key, cached)
        return cached

    url = f"{UWU_BASE}/character/{server}/{nombre}/{spec_i}"
    started = time.monotonic()
    try:
        resp = SESSION.get(url, timeout=HTTP_TIMEOUT)
    except Exception as e:
        logger.info(
            "uwu_character name=%s spec=%s error=%r elapsed=%.2fs",
            nombre, spec_i, e, time.monotonic() - started,
        )
        return {"__error__": f"uwu character error: {e}"}
    logger.info(
        "uwu_character name=%s spec=%s status=%s bytes=%s elapsed=%.2fs",
        nombre, spec_i, resp.status_code, len(resp.content),
        time.monotonic() - started,
    )

    if resp.status_code != 200:
        return {"__error__": f"uwu character status: {resp.status_code}"}

    try:
        payload = resp.json()
    except Exception as e:
        return {"__error__": f"uwu character json error: {e}"}

    _cache_set(UWU_CHARACTER_CACHE, cache_key, payload)
    set_external_cache(
        "uwu_character",
        url,
        persistent_cache_key,
        payload,
        {
            "server": server,
            "name": nombre,
            "spec_i": spec_i,
        },
    )
    return payload


def _fetch_uwu_top(
    server: str,
    boss: str,
    mode: str,
    class_i: int,
    spec_i: int,
    best_only: bool = True,
    timeout_override: float | None = None,
    max_attempts: int = 2,
):
    cache_key = ("v4", server, boss, mode, class_i, spec_i, best_only)
    cached = _cache_get(UWU_TOP_CACHE, cache_key, UWU_TOP_TTL)
    if cached is not None:
        return cached

    persistent_cache_key = (
        f"uwu:v4:top:{server}:{boss}:{mode}:{class_i}:{spec_i}:{int(best_only)}"
    )
    cached = get_external_cache("uwu_top", persistent_cache_key, UWU_TOP_TTL)
    if cached is not None:
        _cache_set(UWU_TOP_CACHE, cache_key, cached)
        return cached

    payload = {
        "server": server,
        "boss": boss,
        "mode": mode,
        "class_i": class_i,
        "spec_i": spec_i,
        "sort_by": "head-useful-dps",
        "limit": "1000",
        "best_only": best_only,
        "externals": True,
    }
    last_error = None
    timeout_value = timeout_override if timeout_override is not None else HTTP_TIMEOUT
    for _ in range(max_attempts):
        started = time.monotonic()
        try:
            resp = SESSION.post(f"{UWU_BASE}/top", json=payload, timeout=timeout_value)
        except Exception as e:
            last_error = f"uwu top error: {e}"
            logger.info(
                "uwu_top boss=%s mode=%s class=%s spec=%s best_only=%s "
                "timeout=%.1f error=%r elapsed=%.2fs",
                boss, mode, class_i, spec_i, best_only, timeout_value, e,
                time.monotonic() - started,
            )
            continue
        logger.info(
            "uwu_top boss=%s mode=%s class=%s spec=%s best_only=%s "
            "status=%s bytes=%s elapsed=%.2fs",
            boss, mode, class_i, spec_i, best_only, resp.status_code,
            len(resp.content), time.monotonic() - started,
        )

        if resp.status_code != 200:
            last_error = f"uwu top status: {resp.status_code}"
            continue

        try:
            rows = resp.json()
        except Exception as e:
            last_error = f"uwu top json error: {e}"
            continue

        _cache_set(UWU_TOP_CACHE, cache_key, rows)
        set_external_cache(
            "uwu_top",
            f"{UWU_BASE}/top",
            persistent_cache_key,
            rows,
            {
                "server": server,
                "boss": boss,
                "mode": mode,
                "class_i": class_i,
                "spec_i": spec_i,
                "best_only": best_only,
            },
        )
        return rows

    return {"__error__": last_error or "uwu top unknown error"}


def _uwu_row_dps(entry):
    try:
        duration = float(entry[1])
        useful_amount = float(entry[4])
    except Exception:
        return None
    if duration <= 0:
        return None
    return useful_amount / duration


def _uwu_profiles(nombre: str, server: str):
    profiles = []
    for spec_i in (1, 2, 3):
        data = _fetch_uwu_character(nombre, server, spec_i)
        if not isinstance(data, dict) or data.get("__error__"):
            continue
        profile_name = str(data.get("name") or "")
        if profile_name.startswith("Unknown-"):
            continue
        class_i = int(data.get("class_i", -1))
        profiles.append((spec_i, class_i, data))
    return profiles


def _uwu_dps_profiles(nombre: str, server: str):
    """
    Como _uwu_profiles, pero devuelve None si uwu-logs no respondió (ninguna
    spec se pudo leer), para no confundirlo con "el personaje no está".
    Reintenta una vez las specs que fallaron.
    """
    profiles = []
    failed = 0
    for spec_i in (1, 2, 3):
        data = _fetch_uwu_character(nombre, server, spec_i)
        if not isinstance(data, dict) or data.get("__error__"):
            time.sleep(1.5)
            data = _fetch_uwu_character(nombre, server, spec_i)
        if not isinstance(data, dict) or data.get("__error__"):
            failed += 1
            continue
        profile_name = str(data.get("name") or "")
        if profile_name.startswith("Unknown-"):
            continue
        class_i = int(data.get("class_i", -1))
        profiles.append((spec_i, class_i, data))
    if not profiles and failed:
        return None
    return profiles


def _post_json_with_deadline(url: str, payload: dict, total_timeout: float):
    """
    POST que corta a los total_timeout segundos contando la descarga entera.
    El timeout de requests es por lectura: una respuesta que llega de a poco
    nunca lo dispara. Devuelve (status, bytes, json) o levanta excepción; si
    el status no es 200, el tercer valor es el header Retry-After.
    """
    started = time.monotonic()
    with SESSION.post(
        url, json=payload, timeout=(5, total_timeout), stream=True
    ) as resp:
        if resp.status_code != 200:
            return resp.status_code, 0, resp.headers.get("Retry-After")
        chunks = []
        for chunk in resp.iter_content(chunk_size=65536):
            chunks.append(chunk)
            if time.monotonic() - started > total_timeout:
                raise TimeoutError(f"descarga cortada a los {total_timeout:.1f} s")
    body = b"".join(chunks)
    return 200, len(body), json.loads(body)


def _post_top_with_retry(payload: dict, timeout_value: float, path: str = "/top"):
    """
    POST a uwu-logs (por defecto /top) con deadline total. uwu-logs
    rate-limita las ráfagas (429): espera (Retry-After o 1,5 s, 3 s) y
    reintenta mientras quede tiempo. Devuelve (status, bytes, json) como
    _post_json_with_deadline.
    """
    started = time.monotonic()
    for attempt in range(1, UWU_TOP_MAX_ATTEMPTS + 1):
        remaining = timeout_value - (time.monotonic() - started)
        status, size, data = _post_json_with_deadline(
            f"{UWU_BASE}{path}", payload, max(remaining, 1.0)
        )
        if status != 429 or attempt == UWU_TOP_MAX_ATTEMPTS:
            break
        try:
            wait_s = float(data)
        except (TypeError, ValueError):
            wait_s = 1.5 * attempt
        remaining = timeout_value - (time.monotonic() - started)
        logger.info(
            "uwu_top_retry boss=%s mode=%s class=%s spec=%s status=429 "
            "attempt=%s wait=%.1fs",
            payload.get("boss"), payload.get("mode"), payload.get("class_i"),
            payload.get("spec_i"), attempt, wait_s,
        )
        if wait_s >= remaining - 1.0:
            break
        time.sleep(wait_s)
    return status, size, data


def _fetch_uwu_spec_players(
    server: str, boss: str, mode: str, class_i: int, spec_i: int
):
    """
    Nombres (en minúscula) de todos los jugadores de una spec con al menos un
    kill válido del boss en ese modo. Es la misma lista para todos los
    personajes, así que se cachea compartida (sirve para /p y para el cron).
    Con limit=1000 los jugadores más allá del puesto 1000 salían sin kill: en
    Lordaeron casi todas las specs populares superan los 1000 en Marrowgar y
    Deathwhisper. Devuelve None si uwu-logs no respondió.
    """
    cache_key = (server, boss, mode, class_i, spec_i)
    cached = _cache_get(UWU_SPEC_PLAYERS_CACHE, cache_key, UWU_SPEC_PLAYERS_TTL)
    if cached is not None:
        return cached

    persistent_cache_key = (
        f"uwu:spec_players:{server}:{boss}:{mode}:{class_i}:{spec_i}"
    )
    cached = get_external_cache(
        "uwu_spec_players", persistent_cache_key, UWU_SPEC_PLAYERS_TTL
    )
    if cached is not None:
        _cache_set(UWU_SPEC_PLAYERS_CACHE, cache_key, cached)
        return cached

    payload = {
        "server": server,
        "boss": boss,
        "mode": mode,
        "class_i": class_i,
        "spec_i": spec_i,
        "sort_by": "head-useful-dps",
        "limit": str(UWU_TOP_PLAYER_LIMIT),
        "best_only": True,
        "externals": True,
    }
    started = time.monotonic()
    try:
        status, size, top_rows = _post_top_with_retry(
            payload, UWU_TOP_PLAYER_TIMEOUT
        )
    except Exception as e:
        logger.info(
            "uwu_spec_players boss=%s mode=%s class=%s spec=%s error=%r elapsed=%.2fs",
            boss, mode, class_i, spec_i, e, time.monotonic() - started,
        )
        return None
    if status != 200 or not isinstance(top_rows, list):
        logger.info(
            "uwu_spec_players boss=%s mode=%s class=%s spec=%s status=%s elapsed=%.2fs",
            boss, mode, class_i, spec_i, status, time.monotonic() - started,
        )
        return None

    names = sorted({
        str(row[3]).lower()
        for row in top_rows
        if isinstance(row, list) and len(row) > 4 and _uwu_row_dps(row) is not None
    })
    logger.info(
        "uwu_spec_players boss=%s mode=%s class=%s spec=%s status=200 bytes=%s "
        "players=%s elapsed=%.2fs",
        boss, mode, class_i, spec_i, size, len(names), time.monotonic() - started,
    )
    _cache_set(UWU_SPEC_PLAYERS_CACHE, cache_key, names)
    set_external_cache(
        "uwu_spec_players",
        f"{UWU_BASE}/top",
        persistent_cache_key,
        names,
        {"server": server, "boss": boss, "mode": mode, "class_i": class_i, "spec_i": spec_i},
    )
    return names


def _fetch_uwu_player_rows(
    server: str,
    boss: str,
    mode: str,
    class_i: int,
    spec_i: int,
    nombre: str,
    timeout_override: float | None = None,
):
    """
    Filas de /top (todas las raids, no solo la mejor) de un jugador.

    /top no filtra por nombre: trae la spec entera ordenada por DPS útil, así
    que se piden UWU_TOP_PLAYER_LIMIT filas y se quedan solo las del jugador.
    Se cachean esas filas y no la lista completa (pesa ~1-2 MB).
    "truncated" indica que la spec tiene más filas que el límite, así que al
    jugador le pueden faltar sus raids de menor DPS.
    """
    lower_name = nombre.lower()
    cache_key = (server, boss, mode, class_i, spec_i, lower_name)
    cached = _cache_get(UWU_PLAYER_ROWS_CACHE, cache_key, UWU_PLAYER_ROWS_TTL)
    if cached is not None:
        return cached

    persistent_cache_key = (
        f"uwu:player_rows:{server}:{boss}:{mode}:{class_i}:{spec_i}:{lower_name}"
    )
    cached = get_external_cache(
        "uwu_player_rows", persistent_cache_key, UWU_PLAYER_ROWS_TTL
    )
    if cached is not None:
        _cache_set(UWU_PLAYER_ROWS_CACHE, cache_key, cached)
        return cached

    payload = {
        "server": server,
        "boss": boss,
        "mode": mode,
        "class_i": class_i,
        "spec_i": spec_i,
        "sort_by": "head-useful-dps",
        "limit": str(UWU_TOP_PLAYER_LIMIT),
        "best_only": False,
        "externals": True,
    }
    timeout_value = (
        timeout_override if timeout_override is not None else UWU_TOP_PLAYER_TIMEOUT
    )
    started = time.monotonic()
    try:
        status, size, top_rows = _post_top_with_retry(payload, timeout_value)
    except Exception as e:
        logger.info(
            "uwu_player_rows boss=%s mode=%s class=%s spec=%s timeout=%.1f "
            "error=%r elapsed=%.2fs",
            boss, mode, class_i, spec_i, timeout_value, e,
            time.monotonic() - started,
        )
        return {"__error__": f"uwu top error: {e}"}

    if status != 200:
        logger.info(
            "uwu_player_rows boss=%s mode=%s class=%s spec=%s status=%s elapsed=%.2fs",
            boss, mode, class_i, spec_i, status, time.monotonic() - started,
        )
        return {"__error__": f"uwu top status: {status}"}
    if not isinstance(top_rows, list):
        return {"__error__": "uwu top: respuesta inesperada"}

    result = {
        "rows": [
            row
            for row in top_rows
            if isinstance(row, list)
            and len(row) > 4
            and str(row[3]).lower() == lower_name
        ],
        "truncated": len(top_rows) >= UWU_TOP_PLAYER_LIMIT,
    }
    logger.info(
        "uwu_player_rows boss=%s mode=%s class=%s spec=%s status=200 bytes=%s "
        "rows=%s player_rows=%s elapsed=%.2fs",
        boss, mode, class_i, spec_i, size, len(top_rows), len(result["rows"]),
        time.monotonic() - started,
    )
    _cache_set(UWU_PLAYER_ROWS_CACHE, cache_key, result)
    set_external_cache(
        "uwu_player_rows",
        f"{UWU_BASE}/top",
        persistent_cache_key,
        result,
        {
            "server": server,
            "boss": boss,
            "mode": mode,
            "class_i": class_i,
            "spec_i": spec_i,
            "name": nombre,
        },
    )
    return result


def _uwu_spec_sort_key(spec_i: int, data: dict):
    """
    Spec principal: una spec de DPS con datos antes que healer/tank (a casi
    todos les interesa ver el DPS; Flappyaladin tiene más logs de Holy pero
    se lo busca por Ret). Después, más bosses con datos y más puntos.
    """
    bosses = data.get("bosses", {}) if isinstance(data, dict) else {}
    if not isinstance(bosses, dict):
        bosses = {}
    bosses_with_data = sum(1 for v in bosses.values() if isinstance(v, dict) and v)
    points = float(data.get("overall_points") or 0)
    class_i = data.get("class_i") if isinstance(data, dict) else None
    is_dps = (class_i, spec_i) not in UWU_NON_DPS_SPECS
    has_data = bosses_with_data > 0 or points > 0
    return (is_dps and has_data, bosses_with_data, points, -spec_i)


def _uwu_spec_ids_for_filter(spec_filter: str | None, class_i: int | None):
    """spec_i de uwu-logs para la spec pedida, desambiguada por clase si se conoce."""
    if not spec_filter:
        return None
    kw = spec_filter.strip().lower()
    by_class = UWU_SPEC_KEYWORDS_BY_CLASS.get(kw, {})
    if class_i in by_class:
        return [by_class[class_i]]
    return UWU_SPEC_KEYWORDS.get(kw)


def _uwu_dps_spec_pairs(
    profiles, spec_filter: str | None = None, char_class: str | None = None
):
    """
    Pares (spec_i, class_i) a consultar en /top para /dps.

    /character devuelve perfil para las 3 specs aunque el personaje no tenga
    logs en ellas, así que sin filtro se usa solo la spec principal (no se
    mezclan, por ejemplo, las raids de prot y de ret). Si ninguna spec tiene
    datos en el modo por defecto de /character, se piden las 3 specs: pedir
    la clase entera (spec_i=-1) pierde jugadores (en pala/Marrowgar 25H
    devuelve 5215 contra 5379 sumando las specs, y falta Flappyaladin).
    Sin perfil en /character (sale "Unknown-...", aunque el personaje figure
    en los rankings, como Ganji) se usa la clase del armory si se conoce.
    """
    valid = [(s, c, d) for s, c, d in profiles if c >= 0]
    if not valid:
        class_i = UWU_CLASS_INDEX.get(char_class or "")
        if class_i is None:
            return []
        spec_ids = _uwu_spec_ids_for_filter(spec_filter, class_i) or [1, 2, 3]
        return [(s, class_i) for s in spec_ids]
    class_i = valid[0][1]

    allowed_spec_ids = _uwu_spec_ids_for_filter(spec_filter, class_i)
    if allowed_spec_ids:
        return [(s, class_i) for s in allowed_spec_ids]

    spec_i, class_i, data = max(
        valid, key=lambda item: _uwu_spec_sort_key(item[0], item[2])
    )
    if _uwu_spec_sort_key(spec_i, data)[0] == 0:
        return [(s, class_i) for s in (1, 2, 3)]
    return [(spec_i, class_i)]


def _pick_uwu_spec(nombre: str, server: str):
    payloads = []
    for spec_i in (1, 2, 3):
        data = _fetch_uwu_character(nombre, server, spec_i)
        if isinstance(data, dict) and not data.get("__error__"):
            payloads.append((spec_i, data))

    if not payloads:
        return None, None

    best_spec_i, best_payload = max(
        payloads, key=lambda item: _uwu_spec_sort_key(item[0], item[1])
    )
    return best_spec_i, best_payload


def _extract_character_overview(data: dict, nombre: str) -> dict | None:
    """Extrae filas de resumen por boss de un payload JSON de UwU character."""
    if not isinstance(data, dict) or data.get("__error__"):
        return None
    profile_name = str(data.get("name") or "")
    if profile_name.startswith("Unknown-"):
        return None
    bosses = data.get("bosses") or {}
    if not isinstance(bosses, dict):
        return None

    rows = []
    for boss_name in UWU_BOSS_SHORT:
        boss_short = UWU_BOSS_SHORT[boss_name]
        bd = bosses.get(boss_name)
        if not isinstance(bd, dict) or not bd:
            rows.append({
                "boss": boss_short, "rank": "-", "points": "0.00",
                "best_dps": "-", "duration": "-", "kills": "-", "date": "-",
            })
            continue
        rank = bd.get("rank_players")
        pts = bd.get("points")
        dps_max = bd.get("dps_max")
        dur_s = bd.get("fastest_kill_duration")
        kills = bd.get("raids")
        raid_id = str(bd.get("raid_id") or "")

        pts_str = f"{pts / 100:.2f}" if pts is not None else "0.00"
        dps_str = f"{dps_max:,.1f}".replace(",", " ") if dps_max is not None else "-"
        if dur_s is not None:
            m, s = divmod(int(dur_s), 60)
            dur_str = f"{m:02d}:{s:02d}"
        else:
            dur_str = "-"
        # raid_id: "YY-MM-DD-XXXXX" → "DD-MM-YY"
        date_str = "-"
        if raid_id:
            parts = raid_id.split("-")
            if len(parts) >= 3:
                date_str = f"{parts[2]}-{parts[1]}-{parts[0]}"
        rows.append({
            "boss": boss_short,
            "rank": str(rank) if rank is not None else "-",
            "points": pts_str,
            "best_dps": dps_str,
            "duration": dur_str,
            "kills": str(kills) if kills is not None else "-",
            "date": date_str,
        })

    overall_pts = data.get("overall_points")
    overall_rank = data.get("overall_rank")
    return {
        "rows": rows,
        "overall_points": f"{overall_pts / 100:.2f}" if overall_pts is not None else "0.00",
        "overall_rank": str(overall_rank) if overall_rank is not None else "-",
        "name": str(data.get("name") or nombre),
    }


def _fetch_uwu_overview_for_dps(
    nombre: str, server: str, spec_filter: str | None = None
) -> dict | None:
    """
    Obtiene de forma rápida el resumen de personaje (rank/points/dps por boss)
    desde UwU Logs. Usa la mejor spec disponible salvo que spec_filter lo indique.
    """
    if spec_filter:
        class_i = None
        first = _fetch_uwu_character(nombre, server, 1)
        if isinstance(first, dict) and not first.get("__error__"):
            class_i = first.get("class_i")
        spec_i_candidates = _uwu_spec_ids_for_filter(spec_filter, class_i)
        if spec_i_candidates:
            for si in spec_i_candidates:
                data = _fetch_uwu_character(nombre, server, si)
                result = _extract_character_overview(data, nombre)
                if result is not None:
                    return result
            return None

    _, data = _pick_uwu_spec(nombre, server)
    if data is None:
        return None
    return _extract_character_overview(data, nombre)


def _uwu_icc_bugfix_kills(
    nombre: str,
    server: str,
    char_class: str | None = None,
):
    cache_key = ("v3", nombre.lower(), server, char_class)
    cached = _cache_get(UWU_ICC_KILLS_CACHE, cache_key, UWU_ICC_KILLS_TTL)
    if cached is not None:
        return cached

    target = {
        "Marrowgar": "Lord Marrowgar",
        "Deathwhisper": "Lady Deathwhisper",
    }
    modes = ("10H", "25N", "25H")
    result: dict[str, dict[str, str | None]] = {
        short_name: {mode: None for mode in modes} for short_name in target
    }

    profiles = _uwu_dps_profiles(nombre, server)
    lower_name = nombre.lower()

    # uwu-logs no respondió: sin dato (None) y sin cachear, no ❌.
    if profiles is None:
        return result

    # Sin perfil en /character ("Unknown-...") uwu-logs no da la clase, pero el
    # personaje puede figurar igual en los rankings (Ganji): se usa la del
    # armory. Sin ninguna de las dos no hay dónde buscar: ❌ en todos los modos.
    fallback_class_i = UWU_CLASS_INDEX.get(char_class or "")
    if not profiles and fallback_class_i is None:
        for short_name in target:
            for mode in modes:
                result[short_name][mode] = "❌"
        _cache_set(UWU_ICC_KILLS_CACHE, cache_key, result)
        return result

    character_mode_presence = {
        short_name: {mode: False for mode in modes} for short_name in target
    }
    for _, _, data in profiles:
        bosses = data.get("bosses")
        if not isinstance(bosses, dict):
            continue
        for short_name, full_boss_name in target.items():
            boss_info = bosses.get(full_boss_name)
            if not isinstance(boss_info, dict) or not boss_info:
                continue
            has_report = any(
                boss_info.get(key)
                for key in ("report_id", "raid_id", "raids", "dps_max")
            )
            if not has_report:
                continue
            default_mode = UWU_BOSS_MODE.get(full_boss_name)
            if default_mode in character_mode_presence[short_name]:
                character_mode_presence[short_name][default_mode] = True

    probe_pairs = [(spec_i, class_i) for spec_i, class_i, _ in profiles]
    if not probe_pairs:
        probe_pairs = [(spec_i, fallback_class_i) for spec_i in (1, 2, 3)]
    complete = True
    for short_name, full_boss_name in target.items():
        for mode in modes:
            found = character_mode_presence.get(short_name, {}).get(mode, False)
            checked = found
            for spec_i, class_i in probe_pairs:
                if found:
                    break
                players = _fetch_uwu_spec_players(
                    server, full_boss_name, mode, class_i, spec_i
                )
                if players is None:
                    complete = False
                    continue
                checked = True
                found = lower_name in players
            result[short_name][mode] = "✅" if found else ("❌" if checked else None)

    if complete:
        _cache_set(UWU_ICC_KILLS_CACHE, cache_key, result)
    return result


def _fetch_uwu_spec_ranking(server: str, class_i: int, spec_i: int):
    """
    Ranking de puntos de una spec: nombres (en minúscula) en orden, de POST
    /top_points (que devuelve [nombre, %, puntos]). Se cachea la lista de
    nombres (~30 KB), compartida entre personajes. None si uwu-logs falló.
    """
    cache_key = (server, class_i, spec_i)
    cached = _cache_get(UWU_TOP_POINTS_CACHE, cache_key, UWU_TOP_POINTS_TTL)
    if cached is not None:
        return cached

    persistent_cache_key = f"uwu:top_points_names:{server}:{class_i}:{spec_i}"
    cached = get_external_cache("uwu_top_points", persistent_cache_key, UWU_TOP_POINTS_TTL)
    if isinstance(cached, list):
        _cache_set(UWU_TOP_POINTS_CACHE, cache_key, cached)
        return cached

    payload = {"server": server, "class_i": class_i, "spec_i": spec_i}
    started = time.monotonic()
    try:
        status, size, rows = _post_json_with_deadline(
            f"{UWU_BASE}/top_points", payload, UWU_TOP_PLAYER_TIMEOUT
        )
    except Exception as e:
        logger.info(
            "uwu_top_points class=%s spec=%s error=%r elapsed=%.2fs",
            class_i, spec_i, e, time.monotonic() - started,
        )
        return None
    logger.info(
        "uwu_top_points class=%s spec=%s status=%s bytes=%s elapsed=%.2fs",
        class_i, spec_i, status, size, time.monotonic() - started,
    )
    if status != 200 or not isinstance(rows, list):
        return None

    names = [
        str(row[0]).lower() for row in rows if isinstance(row, list) and row
    ]
    _cache_set(UWU_TOP_POINTS_CACHE, cache_key, names)
    set_external_cache(
        "uwu_top_points",
        f"{UWU_BASE}/top_points",
        persistent_cache_key,
        names,
        {"server": server, "class_i": class_i, "spec_i": spec_i},
    )
    return names


def _fetch_uwu_performance(nombre: str, server: str, char_class: str | None = None):
    """
    Puesto de uwu-logs para /p: el de la spec principal (la misma que usa
    /dps). None si uwu-logs no respondió, {} si el personaje no está rankeado.
    Si /character no tiene perfil ("Unknown-...", como Ganji, que igual figura
    en los rankings) se lo busca en el ranking de cada spec de la clase del
    armory.
    """
    profiles = _uwu_dps_profiles(nombre, server)
    if profiles is None:
        return None
    valid = [
        (s, c, d)
        for s, c, d in profiles
        if c in UWU_SPEC_NAMES and float(d.get("overall_points") or 0) > 0
    ]
    if valid:
        spec_i, class_i, data = max(
            valid, key=lambda item: _uwu_spec_sort_key(item[0], item[2])
        )
        ranking = _fetch_uwu_spec_ranking(server, class_i, spec_i)
        rank = data.get("overall_rank")
        return {
            "spec": UWU_SPEC_NAMES[class_i][spec_i - 1],
            "points": round(float(data["overall_points"]) / 100, 2),
            "rank": int(rank) if rank else None,
            "total": len(ranking) if ranking is not None else None,
        }

    class_i = UWU_CLASS_INDEX.get(char_class or "")
    if profiles or class_i is None:
        return {}
    lower_name = nombre.lower()
    found = []
    failed = False
    for spec_i in (1, 2, 3):
        ranking = _fetch_uwu_spec_ranking(server, class_i, spec_i)
        if ranking is None:
            failed = True
            continue
        if lower_name in ranking:
            found.append((spec_i, ranking.index(lower_name) + 1, len(ranking)))
    if not found:
        return None if failed else {}
    # DPS antes que healer/tank; después el mejor percentil.
    spec_i, rank, total = min(
        found,
        key=lambda f: ((class_i, f[0]) in UWU_NON_DPS_SPECS, f[1] / f[2]),
    )
    return {
        "spec": UWU_SPEC_NAMES[class_i][spec_i - 1],
        "points": None,
        "rank": rank,
        "total": total,
    }


def _fetch_uwu_report_ids(server: str, nombre: str, fight: str | None = None):
    """
    Ids de los reportes de uwu-logs donde aparece el jugador (POST /logs_list
    filtra por nombre exacto), opcionalmente solo los que tienen esa pelea.
    None si uwu-logs no respondió.
    """
    payload = {"server": server, "player": nombre}
    if fight:
        payload["fight"] = fight
    started = time.monotonic()
    try:
        status, size, ids = _post_top_with_retry(
            payload, UWU_TOP_PLAYER_TIMEOUT, path="/logs_list"
        )
    except Exception as e:
        logger.info(
            "uwu_logs_list name=%s fight=%s error=%r elapsed=%.2fs",
            nombre, fight, e, time.monotonic() - started,
        )
        return None
    logger.info(
        "uwu_logs_list name=%s fight=%s status=%s bytes=%s elapsed=%.2fs",
        nombre, fight, status, size, time.monotonic() - started,
    )
    if status != 200 or not isinstance(ids, list):
        return None
    return [str(report_id) for report_id in ids]


def _uwu_report_label(fights: set[str]) -> str:
    """"ICC 11/12", "Halion", "ICC 12/12 + Halion" u "otro raid"."""
    parts = []
    icc = sum(1 for fight in UWU_LOGS_ICC_FIGHTS if fight in fights)
    if icc:
        parts.append(f"ICC {icc}/{len(UWU_LOGS_ICC_FIGHTS)}")
    parts.extend(
        label for fight, label in UWU_LOGS_OTHER_FIGHTS.items() if fight in fights
    )
    return " + ".join(parts) or "otro raid"


def _fetch_uwu_recent_logs(nombre: str, server: str):
    """
    Últimos UWU_LOGS_LIMIT reportes de uwu-logs del personaje para /logs, del
    más nuevo al más viejo, con la etiqueta de raid de cada uno. /logs_list no
    trae los bosses: se pide una vez por pelea (14 consultas, 2 a la vez) y se
    cruza. None si uwu-logs no respondió.
    """
    cache_key = (nombre.lower(), server)
    cached = _cache_get(UWU_LOGS_CACHE, cache_key, UWU_LOGS_TTL)
    if cached is not None:
        return cached
    persistent_cache_key = f"uwu:logs:{server}:{nombre.lower()}"
    cached = get_external_cache("uwu_logs", persistent_cache_key, UWU_LOGS_TTL)
    if isinstance(cached, dict):
        _cache_set(UWU_LOGS_CACHE, cache_key, cached)
        return cached

    ids = _fetch_uwu_report_ids(server, nombre)
    if ids is None:
        return None
    # El id empieza con "AA-MM-DD--HH-MM": ordenarlo como texto es por fecha.
    recent = sorted(set(ids), reverse=True)[:UWU_LOGS_LIMIT]
    result = {"total": len(set(ids)), "reports": []}
    if not recent:
        return result

    fights = list(UWU_LOGS_ICC_FIGHTS) + list(UWU_LOGS_OTHER_FIGHTS)
    with ThreadPoolExecutor(max_workers=UWU_TOP_WORKERS) as pool:
        fight_ids = dict(
            zip(
                fights,
                pool.map(lambda fight: _fetch_uwu_report_ids(server, nombre, fight), fights),
            )
        )
    complete = all(v is not None for v in fight_ids.values())
    fight_sets = {fight: set(v or []) for fight, v in fight_ids.items()}

    for report_id in recent:
        parts = report_id.split("--")
        date = "-".join(reversed(parts[0].split("-"))) if parts else report_id
        author = parts[2] if len(parts) >= 4 else "?"
        present = {fight for fight, s in fight_sets.items() if report_id in s}
        result["reports"].append({
            "id": report_id,
            "date": date,
            "author": author,
            "label": _uwu_report_label(present) if complete else "?",
        })

    if complete:
        _cache_set(UWU_LOGS_CACHE, cache_key, result)
        set_external_cache(
            "uwu_logs",
            f"{UWU_BASE}/logs_list",
            persistent_cache_key,
            result,
            {"server": server, "name": nombre},
        )
    return result


UWU_DOWN_MESSAGE = (
    "⚠️ UwU Logs no responde en este momento. Probá de nuevo en unos minutos."
)


def _uwu_dps_row(boss_name: str, mode: str, player_rows, truncated: bool):
    boss_short = UWU_BOSS_SHORT.get(boss_name, boss_name[:10])
    dps_values = [x for x in (_uwu_row_dps(r) for r in player_rows) if x is not None]
    # Con la lista truncada pueden faltar las raids de menor DPS del jugador:
    # el máximo es exacto, pero la cantidad es un mínimo ("+").
    raids_suffix = "+" if truncated else ""
    if not dps_values:
        return {
            "Boss": boss_short,
            "Mode": mode,
            "Raids": "0" + raids_suffix,
            "Max DPS": "-",
            "Avg DPS": "-",
            "_boss": boss_name,
        }
    dps_avg = round(sum(dps_values) / len(dps_values), 2)
    dps_max = round(max(dps_values), 2)
    return {
        "Boss": boss_short,
        "Mode": mode,
        "Raids": f"{len(dps_values)}{raids_suffix}",
        "Max DPS": f"{dps_max:.2f}",
        "Avg DPS": f"{dps_avg:.2f}",
        "_boss": boss_name,
    }


def _build_uwu_dps_summary(
    nombre: str,
    server: str,
    selected_bosses=None,
    spec_filter: str | None = None,
    time_budget_s: float = 30.0,
    char_class: str | None = None,
):
    selected_bosses_key = tuple(selected_bosses) if selected_bosses else None
    cache_key = (nombre.lower(), server, selected_bosses_key, spec_filter, char_class)
    cached = _cache_get(UWU_PDPS_SUMMARY_CACHE, cache_key, UWU_PDPS_SUMMARY_TTL)
    if cached is not None:
        return cached

    deadline_ts = time.monotonic() + max(time_budget_s, 1.0)
    profiles = _uwu_dps_profiles(nombre, server)
    failed_by_mode = {mode: 0 for mode in UWU_MODES_ALL}
    if profiles is None:
        # No se cachea: es una falla de uwu-logs, no "sin datos".
        return {
            "rows": [],
            "__error__": UWU_DOWN_MESSAGE,
            "uwu_down": True,
            "failed_by_mode": failed_by_mode,
            "timed_out": False,
        }
    spec_class_pairs = _uwu_dps_spec_pairs(profiles, spec_filter, char_class)

    if not spec_class_pairs:
        payload = {
            "rows": [],
            "__error__": "No hay datos de uwu-logs para el personaje.",
            "failed_by_mode": failed_by_mode,
            "timed_out": False,
        }
        _cache_set(UWU_PDPS_SUMMARY_CACHE, cache_key, payload)
        return payload

    if selected_bosses:
        boss_names = [
            boss for boss in selected_bosses if isinstance(boss, str) and boss
        ]
    else:
        bosses = {}
        for _, _, data in profiles:
            _bosses = data.get("bosses", {})
            if isinstance(_bosses, dict):
                bosses.update(_bosses)
        if not bosses:
            bosses = {boss_name: {} for boss_name in UWU_BOSS_SHORT}
        boss_names = sorted(bosses.keys(), key=lambda x: UWU_BOSS_SHORT.get(x, x))

    def fetch(boss_name, mode, spec_i, class_i):
        remaining = deadline_ts - time.monotonic()
        if remaining <= 0:
            return {"__error__": "timeout"}
        return _fetch_uwu_player_rows(
            server,
            boss_name,
            mode,
            class_i,
            spec_i,
            nombre,
            timeout_override=min(UWU_TOP_PLAYER_TIMEOUT, max(1.0, remaining)),
        )

    tasks = [
        (boss_name, mode, spec_i, class_i)
        for boss_name in boss_names
        for mode in UWU_MODES_ALL
        for spec_i, class_i in spec_class_pairs
    ]
    # Cada consulta de 10000 filas tarda ~0,3-2 s: van en paralelo, pocas a la
    # vez para no castigar a uwu-logs.
    pool = ThreadPoolExecutor(max_workers=UWU_TOP_WORKERS)
    futures = {pool.submit(fetch, *task): task for task in tasks}
    _, pending = wait(futures, timeout=max(deadline_ts - time.monotonic(), 0.0))
    pool.shutdown(wait=False, cancel_futures=True)
    timed_out = bool(pending)

    results = {}
    for future, task in futures.items():
        if future in pending:
            continue
        try:
            results[task] = future.result()
        except Exception as e:
            results[task] = {"__error__": f"uwu top error: {e}"}

    rows = []
    for boss_name in boss_names:
        for mode in UWU_MODES_ALL:
            player_rows = []
            truncated = False
            any_fetch_ok = False
            answered = False
            for spec_i, class_i in spec_class_pairs:
                data = results.get((boss_name, mode, spec_i, class_i))
                if data is None:
                    continue
                answered = True
                if not isinstance(data, dict) or data.get("__error__"):
                    failed_by_mode[mode] += 1
                    continue
                any_fetch_ok = True
                player_rows.extend(data.get("rows") or [])
                truncated = truncated or bool(data.get("truncated"))
            if not answered:
                # Quedó afuera por el timeout: la fila no se muestra.
                continue
            if not any_fetch_ok:
                player_rows = []
            rows.append(_uwu_dps_row(boss_name, mode, player_rows, truncated))

    if not rows:
        # Ninguna consulta terminó bien: uwu-logs está lento o caído.
        return {
            "rows": [],
            "__error__": UWU_DOWN_MESSAGE,
            "uwu_down": True,
            "failed_by_mode": failed_by_mode,
            "timed_out": timed_out,
        }

    payload = {
        "rows": rows,
        "spec_i": spec_class_pairs[0][0] if len(spec_class_pairs) == 1 else "all",
        "failed_by_mode": failed_by_mode,
        "timed_out": timed_out,
    }
    _cache_set(UWU_PDPS_SUMMARY_CACHE, cache_key, payload)
    return payload

