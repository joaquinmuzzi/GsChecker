import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import gearscore
import profile_scraper
from dotenv import load_dotenv

from src.db.postgres import init_database, set_external_cache
from src.functions.uwu import _fetch_uwu_top
from src.functions.warmane import _fetch_gear_data, _fetch_specs, _fetch_summary
from src.schemas.constants import UWU_MODES_ALL, UWU_PDPS_BOSS_ORDER


def _build_character_spec_gs_key(nombre: str, server: str, spec_name: str) -> str:
    return (
        f"character:spec-gs:{server.strip().lower()}:"
        f"{nombre.strip().lower()}:{spec_name.strip().lower()}"
    )


def _normalize_name(name: str) -> str:
    return str(name or "").strip().capitalize()


def _collect_names_from_file(file_path: str) -> list[str]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo: {file_path}")

    names = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        names.append(_normalize_name(line))
    return names


def _collect_names_from_uwu(server: str, limit: int, best_only: bool) -> list[str]:
    names = set()
    total_queries = len(UWU_PDPS_BOSS_ORDER) * len(UWU_MODES_ALL) * 10 * 3
    query_idx = 0
    seed_start = time.time()
    print(
        "[INFO] Seed UwU iniciado "
        f"(consultas={total_queries}, best_only={best_only}, limit={limit})"
    )

    for boss in UWU_PDPS_BOSS_ORDER:
        boss_start = time.time()
        print(f"[UWU] Boss: {boss}")
        for mode in UWU_MODES_ALL:
            for class_i in range(10):
                for spec_i in (1, 2, 3):
                    query_idx += 1
                    rows = _fetch_uwu_top(
                        server,
                        boss,
                        mode,
                        class_i,
                        spec_i,
                        best_only=best_only,
                    )
                    if not isinstance(rows, list):
                        continue
                    for row in rows[:limit]:
                        if not isinstance(row, list) or len(row) < 4:
                            continue
                        row_name = str(row[3] or "").strip()
                        if row_name:
                            names.add(_normalize_name(row_name))

                    if query_idx % 40 == 0 or query_idx == total_queries:
                        elapsed = max(time.time() - seed_start, 0.001)
                        qps = query_idx / elapsed
                        remaining = max(total_queries - query_idx, 0)
                        eta_sec = int(remaining / qps) if qps > 0 else 0
                        pct = (query_idx / total_queries) * 100 if total_queries else 100
                        print(
                            "[UWU] "
                            f"{query_idx}/{total_queries} ({pct:.1f}%) | "
                            f"nombres={len(names)} | eta={eta_sec}s"
                        )

            print(
                f"[UWU] Boss {boss} mode {mode} listo | "
                f"nombres={len(names)}"
            )

        print(
            f"[UWU] Boss {boss} finalizado en "
            f"{int(time.time() - boss_start)}s | nombres={len(names)}"
        )

    print(
        f"[INFO] Seed UwU finalizado en {int(time.time() - seed_start)}s "
        f"| nombres_unicos={len(names)}"
    )
    return sorted(names)


def _calculate_character_gs(nombre: str, server: str) -> dict | None:
    summary = _fetch_summary(nombre, server)
    if not isinstance(summary, dict) or summary.get("__error__"):
        return None

    nombre_char = str(summary.get("name") or nombre)
    talents = _fetch_specs(nombre_char, server)
    active_specs = [
        str(t.get("name") or "").strip()
        for t in talents
        if isinstance(t, dict) and t.get("active")
    ]
    active_specs = [spec for spec in active_specs if spec and spec != "N/A"]

    gear_data = _fetch_gear_data(nombre_char, server)
    try:
        gear_ids = profile_scraper.get_gear_ids_from_gear_data(gear_data)
        gear_ids = [gid for gid in gear_ids if gid]
        gs = sum(gearscore.main(gear_ids)) if gear_ids else summary.get("gearScore", "N/A")
    except Exception:
        gs = summary.get("gearScore", "N/A")

    return {
        "name": nombre_char,
        "server": server,
        "active_specs": active_specs,
        "gs": gs,
        "gear_items": len(gear_data) if isinstance(gear_data, list) else 0,
    }


def _store_character_gs(payload: dict) -> int:
    nombre_char = payload["name"]
    server = payload["server"]
    gs = payload["gs"]
    active_specs = payload.get("active_specs") or []

    stored = 0
    for spec_name in active_specs:
        set_external_cache(
            "character_spec_gs",
            "/tools/preload_character_gs",
            _build_character_spec_gs_key(nombre_char, server, spec_name),
            {
                "character": nombre_char,
                "server": server,
                "spec": spec_name,
                "gs": gs,
                "gear_items": payload.get("gear_items", 0),
            },
            {
                "character": nombre_char,
                "server": server,
                "spec": spec_name,
                "source": "preload_character_gs",
            },
        )
        stored += 1
    return stored


def main():
    parser = argparse.ArgumentParser(
        description="Precarga GearScore por spec activa en Postgres para muchos personajes."
    )
    parser.add_argument("--server", default="Lordaeron", help="Realm a consultar")
    parser.add_argument(
        "--name",
        action="append",
        default=[],
        help="Nombre de personaje. Se puede repetir varias veces.",
    )
    parser.add_argument(
        "--names-file",
        help="Archivo de texto con un personaje por línea.",
    )
    parser.add_argument(
        "--seed-uwu",
        action="store_true",
        help="Toma nombres desde UwU Logs recorriendo los 6 bosses del comando /dps.",
    )
    parser.add_argument(
        "--uwu-limit",
        type=int,
        default=200,
        help="Máximo de filas por consulta de UwU a considerar al sembrar nombres.",
    )
    parser.add_argument(
        "--uwu-best-only",
        action="store_true",
        help="Usa best_only=True al sembrar desde UwU para acelerar y reducir volumen.",
    )
    parser.add_argument(
        "--max-characters",
        type=int,
        default=0,
        help="Si es > 0, procesa solo esa cantidad de personajes del conjunto total.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="Pausa entre personajes para no pegarle demasiado fuerte a Warmane.",
    )
    args = parser.parse_args()

    load_dotenv()
    init_database()

    names = {_normalize_name(name) for name in args.name if str(name).strip()}

    if args.names_file:
        names.update(_collect_names_from_file(args.names_file))

    if args.seed_uwu:
        print("[INFO] Recolectando nombres desde UwU Logs...")
        names.update(
            _collect_names_from_uwu(
                args.server,
                limit=args.uwu_limit,
                best_only=args.uwu_best_only,
            )
        )

    names = sorted(name for name in names if name)
    if args.max_characters and args.max_characters > 0:
        names = names[: args.max_characters]

    if not names:
        print("[ERROR] No hay personajes para procesar. Usa --name, --names-file o --seed-uwu.")
        return

    print(f"[INFO] Procesando {len(names)} personajes en {args.server}...")

    ok = 0
    skipped = 0
    stored_specs = 0
    run_start = time.time()

    for idx, nombre in enumerate(names, start=1):
        elapsed = max(time.time() - run_start, 0.001)
        speed = (idx - 1) / elapsed if idx > 1 else 0
        remaining = max(len(names) - (idx - 1), 0)
        eta_sec = int(remaining / speed) if speed > 0 else 0
        pct = (idx / len(names)) * 100 if names else 100
        print(
            f"[{idx}/{len(names)}] ({pct:.1f}%) {nombre} "
            f"| ok={ok} skip={skipped} specs={stored_specs} | eta={eta_sec}s"
        )
        payload = _calculate_character_gs(nombre, args.server)
        if not payload:
            skipped += 1
            print(f"  [SKIP] No se pudo calcular {nombre}")
            if args.delay > 0:
                time.sleep(args.delay)
            continue

        stored = _store_character_gs(payload)
        stored_specs += stored
        ok += 1
        active_specs = ", ".join(payload.get("active_specs") or []) or "sin spec activa"
        print(f"  [OK] GS={payload['gs']} | specs={active_specs} | stored={stored}")

        if args.delay > 0:
            time.sleep(args.delay)

    print("\n[INFO] Finalizado")
    print(f"  Personajes OK: {ok}")
    print(f"  Personajes omitidos: {skipped}")
    print(f"  Specs guardadas: {stored_specs}")
    print(f"  Duración total: {int(time.time() - run_start)}s")


if __name__ == "__main__":
    main()
