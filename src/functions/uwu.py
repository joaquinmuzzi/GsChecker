import time

from src.schemas.constants import (
    SESSION,
    HTTP_TIMEOUT,
    UWU_BASE,
    UWU_BOSS_MODE,
    UWU_BOSS_SHORT,
    UWU_MODES_ALL,
    UWU_SPEC_KEYWORDS,
    UWU_CHARACTER_CACHE,
    UWU_CHARACTER_TTL,
    UWU_TOP_CACHE,
    UWU_TOP_TTL,
    UWU_PDPS_SUMMARY_CACHE,
    UWU_PDPS_SUMMARY_TTL,
    UWU_ICC_KILLS_CACHE,
    UWU_ICC_KILLS_TTL,
)
from src.db.postgres import get_external_cache, set_external_cache
from src.functions.cache import _cache_get, _cache_set


def _fetch_uwu_character(nombre: str, server: str, spec_i: int):
    cache_key = (nombre, server, spec_i)
    cached = _cache_get(UWU_CHARACTER_CACHE, cache_key, UWU_CHARACTER_TTL)
    if cached is not None:
        return cached

    persistent_cache_key = f"uwu:character:{server}:{nombre.lower()}:{spec_i}"
    cached = get_external_cache("uwu_character", persistent_cache_key, UWU_CHARACTER_TTL)
    if cached is not None:
        _cache_set(UWU_CHARACTER_CACHE, cache_key, cached)
        return cached

    url = f"{UWU_BASE}/character/{server}/{nombre}/{spec_i}"
    try:
        resp = SESSION.get(url, timeout=HTTP_TIMEOUT)
    except Exception as e:
        return {"__error__": f"uwu character error: {e}"}

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
        try:
            resp = SESSION.post(f"{UWU_BASE}/top", json=payload, timeout=timeout_value)
        except Exception as e:
            last_error = f"uwu top error: {e}"
            continue

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


def _discover_uwu_spec_class_pairs(
    nombre: str,
    server: str,
    boss_names,
    modes,
    deadline_ts: float | None = None,
):
    lower_name = nombre.lower()
    discovered_pairs = []
    seen = set()

    for boss_name in boss_names:
        for mode in modes:
            for class_i in range(10):
                for spec_i in (1, 2, 3):
                    if deadline_ts is not None and time.monotonic() >= deadline_ts:
                        return discovered_pairs
                    remaining = None
                    if deadline_ts is not None:
                        remaining = max(deadline_ts - time.monotonic(), 0.5)
                    top_rows = _fetch_uwu_top(
                        server,
                        boss_name,
                        mode,
                        class_i,
                        spec_i,
                        timeout_override=(
                            min(HTTP_TIMEOUT, remaining)
                            if remaining is not None
                            else None
                        ),
                        max_attempts=1,
                    )
                    if not isinstance(top_rows, list):
                        continue
                    has_player = any(
                        isinstance(row, list)
                        and len(row) > 3
                        and str(row[3]).lower() == lower_name
                        and _uwu_row_dps(row) is not None
                        for row in top_rows
                    )
                    if not has_player:
                        continue
                    pair = (spec_i, class_i)
                    if pair not in seen:
                        seen.add(pair)
                        discovered_pairs.append(pair)

    return discovered_pairs


def _pick_uwu_spec(nombre: str, server: str):
    payloads = []
    for spec_i in (1, 2, 3):
        data = _fetch_uwu_character(nombre, server, spec_i)
        if isinstance(data, dict) and not data.get("__error__"):
            payloads.append((spec_i, data))

    if not payloads:
        return None, None

    def sort_key(item):
        spec_i, data = item
        bosses = data.get("bosses", {}) if isinstance(data, dict) else {}
        bosses_with_data = sum(1 for v in bosses.values() if isinstance(v, dict) and v)
        points = float(data.get("overall_points") or 0)
        return (bosses_with_data, points, -spec_i)

    best_spec_i, best_payload = max(payloads, key=sort_key)
    return best_spec_i, best_payload


def _uwu_icc_bugfix_kills(
    nombre: str,
    server: str,
):
    cache_key = ("v2", nombre.lower(), server)
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

    profiles = _uwu_profiles(nombre, server)
    lower_name = nombre.lower()

    character_mode_presence = {
        short_name: {mode: False for mode in modes} for short_name in target
    }
    for spec_i in (1, 2, 3):
        data = _fetch_uwu_character(nombre, server, spec_i)
        if not isinstance(data, dict) or data.get("__error__"):
            continue
        profile_name = str(data.get("name") or "")
        if profile_name.startswith("Unknown-"):
            continue
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

    # Si el personaje no tiene perfil válido en UwU no tiene sentido escanear
    # miles de listas de ranking: salimos de inmediato con ❌ en todos los modos.
    if not probe_pairs:
        for short_name in target:
            for mode in modes:
                result[short_name][mode] = "❌"
        _cache_set(UWU_ICC_KILLS_CACHE, cache_key, result)
        return result

    for short_name, full_boss_name in target.items():
        for mode in modes:
            found = character_mode_presence.get(short_name, {}).get(mode, False)
            checked = found
            for spec_i, class_i in probe_pairs:
                top_rows = _fetch_uwu_top(
                    server,
                    full_boss_name,
                    mode,
                    class_i,
                    spec_i,
                )
                if not isinstance(top_rows, list):
                    continue
                checked = True
                for row in top_rows:
                    if not isinstance(row, list) or len(row) < 6:
                        continue
                    row_name = str(row[3]).lower() if len(row) > 3 else ""
                    if row_name != lower_name:
                        continue
                    if _uwu_row_dps(row) is not None:
                        found = True
                        break
                if found:
                    break
            result[short_name][mode] = "✅" if found else ("❌" if checked else None)

    _cache_set(UWU_ICC_KILLS_CACHE, cache_key, result)
    return result


def _build_uwu_dps_summary(
    nombre: str,
    server: str,
    selected_bosses=None,
    spec_filter: str | None = None,
    time_budget_s: float = 30.0,
):
    selected_bosses_key = tuple(selected_bosses) if selected_bosses else None
    cache_key = (nombre.lower(), server, selected_bosses_key, spec_filter)
    cached = _cache_get(UWU_PDPS_SUMMARY_CACHE, cache_key, UWU_PDPS_SUMMARY_TTL)
    if cached is not None:
        return cached

    profiles = _uwu_profiles(nombre, server)
    spec_class_pairs = [(spec_i, class_i) for spec_i, class_i, _ in profiles]
    deadline_ts = time.monotonic() + max(time_budget_s, 1.0)
    timed_out = False

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

    if not spec_class_pairs:
        discovered_pairs = _discover_uwu_spec_class_pairs(
            nombre,
            server,
            boss_names,
            ("10H", "25N", "10N", "25H"),
            deadline_ts=deadline_ts,
        )
        if discovered_pairs:
            spec_class_pairs = discovered_pairs
        else:
            spec_class_pairs = [(-1, -1)]

    if spec_filter:
        kw = spec_filter.strip().lower()
        allowed_spec_ids = UWU_SPEC_KEYWORDS.get(kw)
        if allowed_spec_ids:
            filtered = [(s, c) for s, c in spec_class_pairs if s in allowed_spec_ids]
            if filtered:
                spec_class_pairs = filtered
            elif profiles:
                class_i_fallback = profiles[0][1]
                spec_class_pairs = [(s, class_i_fallback) for s in allowed_spec_ids]
            else:
                spec_class_pairs = [(s, -1) for s in allowed_spec_ids]

    rows = []
    lower_name = nombre.lower()
    failed_by_mode = {mode: 0 for mode in UWU_MODES_ALL}

    for boss_name in boss_names:
        if time.monotonic() >= deadline_ts:
            timed_out = True
            break
        boss_short = UWU_BOSS_SHORT.get(boss_name, boss_name[:10])
        for mode in UWU_MODES_ALL:
            if time.monotonic() >= deadline_ts:
                timed_out = True
                break
            player_rows = []
            any_fetch_ok = False
            for spec_i, class_i in spec_class_pairs:
                remaining = deadline_ts - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                top_rows = _fetch_uwu_top(
                    server,
                    boss_name,
                    mode,
                    class_i,
                    spec_i,
                    best_only=False,
                    timeout_override=min(HTTP_TIMEOUT, max(1.0, remaining)),
                    max_attempts=1,
                )
                if not isinstance(top_rows, list):
                    failed_by_mode[mode] += 1
                    continue
                any_fetch_ok = True
                for row in top_rows:
                    if not isinstance(row, list) or len(row) < 6:
                        continue
                    row_name = str(row[3]).lower() if len(row) > 3 else ""
                    if row_name == lower_name:
                        player_rows.append(row)

            if timed_out:
                break

            if not any_fetch_ok:
                rows.append(
                    {
                        "Boss": boss_short,
                        "Mode": mode,
                        "Raids": "0",
                        "Max DPS": "-",
                        "Avg DPS": "-",
                        "_boss": boss_name,
                    }
                )
                continue

            dps_values = [
                x for x in (_uwu_row_dps(x) for x in player_rows) if x is not None
            ]
            if not dps_values:
                rows.append(
                    {
                        "Boss": boss_short,
                        "Mode": mode,
                        "Raids": "0",
                        "Max DPS": "-",
                        "Avg DPS": "-",
                        "_boss": boss_name,
                    }
                )
                continue

            dps_avg = round(sum(dps_values) / len(dps_values), 2)
            dps_max = round(max(dps_values), 2)
            rows.append(
                {
                    "Boss": boss_short,
                    "Mode": mode,
                    "Raids": str(len(dps_values)),
                    "Max DPS": f"{dps_max:.2f}",
                    "Avg DPS": f"{dps_avg:.2f}",
                    "_boss": boss_name,
                }
            )

        if timed_out:
            break

    if not rows:
        payload = {
            "rows": [],
            "__error__": "No hay datos de uwu-logs para el personaje.",
            "failed_by_mode": failed_by_mode,
            "timed_out": timed_out,
        }
        _cache_set(UWU_PDPS_SUMMARY_CACHE, cache_key, payload)
        return payload

    payload = {
        "rows": rows,
        "spec_i": "all",
        "failed_by_mode": failed_by_mode,
        "timed_out": timed_out,
    }
    _cache_set(UWU_PDPS_SUMMARY_CACHE, cache_key, payload)
    return payload
