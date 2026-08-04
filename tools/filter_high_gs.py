#!/usr/bin/env python3
"""Filtra personajes de tracked_characters.txt por GS > 5000.

Recorre todos los personajes del txt semilla, fetch solo el summary del armory
para obtener gearScore, y guarda los >5000 GS en tracked_high_gs.txt.

El cron job principal puede entonces leer solo de tracked_high_gs.txt en vez
del listado completo, reduciendo el trabajo a ~1-3k personajes.

Uso:
    python3 tools/filter_high_gs.py                    # Filtra todos
    python3 tools/filter_high_gs.py --min-gs 6000      # Solo >6k
    python3 tools/filter_high_gs.py --dry-run           # Solo imprime
    python3 tools/filter_high_gs.py --max 500           # Test: solo primeros 500
"""

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gearscore
from src.schemas.constants import (
    SESSION,
    HTTP_TIMEOUT,
    ARMORY_LIMITER,
    ARMORY_CIRCUIT,
)
from tools.preload_character_gs import _normalize_name

TRACKED_FILE = Path(__file__).resolve().parent.parent / "data" / "tracked_characters.txt"
HIGH_GS_FILE = Path(__file__).resolve().parent.parent / "data" / "tracked_high_gs.txt"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://armory.warmane.com/",
}


def _load_names(file_path: Path, default_realm: str = "Lordaeron") -> list[tuple[str, str]]:
    """Load (name, realm) pairs from tracked_characters.txt."""
    if not file_path.exists():
        return []
    pairs = []
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line:
            name_part, realm_part = line.split(",", 1)
        else:
            name_part, realm_part = line, default_realm
        name = _normalize_name(name_part)
        realm = str(realm_part or default_realm).strip()
        if name:
            pairs.append((name, realm))
    return pairs


def _fetch_summary_gs(nombre: str, server: str) -> int | None:
    """Fetch character summary from armory, calculate GS from equipment IDs."""
    url = f"https://armory.warmane.com/api/character/{nombre}/{server}/summary"
    try:
        ARMORY_LIMITER.acquire()
        resp = SESSION.get(url, headers=_HEADERS, timeout=HTTP_TIMEOUT)
        if resp.status_code == 429:
            time.sleep(10)
            ARMORY_LIMITER.acquire()
            resp = SESSION.get(url, headers=_HEADERS, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, dict) or data.get("error"):
            return None
        equipment = data.get("equipment", [])
        if not equipment:
            return None
        gear_ids = [str(item.get("item", "")) for item in equipment]
        gear_ids = [gid for gid in gear_ids if gid and gid.isdigit()]
        if not gear_ids:
            return None
        gs_values = gearscore.main(gear_ids)
        return sum(gs_values)
    except Exception:
        return None


def _write_high_gs(file_path: Path, entries: list[tuple[str, str]]) -> None:
    """Write filtered (name, realm) pairs to file."""
    lines = [
        f"# Personajes con GS alto (generado {time.strftime('%Y-%m-%d %H:%M:%S')})",
        "",
    ]
    for name, realm in sorted(entries):
        lines.append(f"{name}, {realm}")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Filtra personajes por GS > min_gs desde el armory."
    )
    parser.add_argument(
        "--min-gs",
        type=int,
        default=5000,
        help="GearScore mínimo (default: 5000)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=0,
        help="Máximo de personajes a procesar (0 = todos)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay entre requests (default: 2.0)",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(TRACKED_FILE),
        help=f"Archivo de entrada (default: {TRACKED_FILE})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(HIGH_GS_FILE),
        help=f"Archivo de salida (default: {HIGH_GS_FILE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo imprime, no escribe",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    pairs = _load_names(input_path)
    if args.max and args.max > 0:
        pairs = pairs[:args.max]

    print(f"[INFO] Procesando {len(pairs)} personajes (min_gs={args.min_gs}, delay={args.delay}s)")

    high_gs = []
    ok = 0
    skipped = 0
    start = time.time()

    for idx, (nombre, realm) in enumerate(pairs, 1):
        # Wait for circuit breaker
        while ARMORY_CIRCUIT.is_open():
            wait_s = int(ARMORY_CIRCUIT.seconds_until_close()) + 1
            print(f"  [CIRCUIT] Esperando {wait_s}s...")
            time.sleep(min(wait_s, 30))

        elapsed = time.time() - start
        speed = (idx - 1) / elapsed if idx > 1 else 0
        remaining = max(len(pairs) - (idx - 1), 0)
        eta = int(remaining / speed) if speed > 0 else 0
        pct = (idx / len(pairs)) * 100

        gs = _fetch_summary_gs(nombre, realm)

        if gs is not None and gs >= args.min_gs:
            high_gs.append((nombre, realm))
            ok += 1
            if ok % 50 == 0 or ok <= 10:
                print(f"  [{idx}/{len(pairs)}] ({pct:.0f}%) {nombre}/{realm} GS={gs} ✓ | high_gs={ok} | eta={eta}s")
        else:
            skipped += 1
            if skipped % 200 == 0:
                print(f"  [{idx}/{len(pairs)}] ({pct:.0f}%) skip={skipped} high_gs={ok} | eta={eta}s")

        if args.delay > 0 and idx < len(pairs):
            jittered = args.delay * random.uniform(0.8, 1.2)
            time.sleep(jittered)

    duration = int(time.time() - start)
    print(f"\n[RESUMEN] Procesados: {len(pairs)} | GS>={args.min_gs}: {ok} | Skip: {skipped} | Duración: {duration}s")

    if args.dry_run:
        print(f"\n--- DRY RUN: {len(high_gs)} personajes con GS>={args.min_gs} ---")
        for name, realm in sorted(high_gs)[:30]:
            print(f"  {name}, {realm}")
        if len(high_gs) > 30:
            print(f"  ... y {len(high_gs) - 30} más")
        return

    _write_high_gs(output_path, high_gs)
    print(f"[OK] {len(high_gs)} personajes guardados en {output_path}")


if __name__ == "__main__":
    main()
