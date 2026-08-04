#!/usr/bin/env python3
"""Recolecta nombres de personajes de Warmane y los guarda en tracked_characters.txt.

Estrategia principal (guilds):
  1. Scrapea /leaderboard/Guild/Lordaeron → ~49 guilds (~20k miembros)
  2. Para cada guild, llama /api/guild/{name}/Lordaeron/summary → roster completo
  3. Mergea con nombres existentes en tracked_characters.txt

Estrategia secundaria (UwU):
  --source uwu  → rankings de DPS por boss/class/spec (más lento, ~540 queries)

Uso:
    python3 tools/seed_names.py                        # Guilds (recomendado, ~4 min)
    python3 tools/seed_names.py --source uwu           # UwU Logs (más lento)
    python3 tools/seed_names.py --dry-run              # Solo imprime, no escribe
    python3 tools/seed_names.py --delay 8              # Delay mayor entre requests
"""

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup
from src.schemas.constants import SESSION, HTTP_TIMEOUT
from tools.preload_character_gs import _normalize_name

TRACKED_FILE = Path(__file__).resolve().parent.parent / "data" / "tracked_characters.txt"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://armory.warmane.com/",
}


def _read_existing_names(file_path: Path) -> set[str]:
    """Read existing names from tracked_characters.txt."""
    if not file_path.exists():
        return set()
    names = set()
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        name = parts[0].strip()
        if name:
            names.add(_normalize_name(name))
    return names


def _write_names(file_path: Path, names: set[str], header: str = "") -> None:
    """Write names to file, one per line, sorted."""
    lines = []
    if header:
        lines.append(f"# {header}")
        lines.append(f"# Generado: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
    for name in sorted(names):
        lines.append(name)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _scrape_guild_leaderboard(server: str) -> list[str]:
    """Scrape /leaderboard/Guild/{server} to get top guild names."""
    url = f"https://armory.warmane.com/leaderboard/Guild/{server}"
    print(f"[GUILDS] Fetching leaderboard: {url}")
    try:
        resp = SESSION.get(url, headers=_HEADERS, timeout=HTTP_TIMEOUT)
        if resp.status_code == 429:
            print(f"[GUILDS] Rate limited (429). Waiting 10s...")
            time.sleep(10)
            resp = SESSION.get(url, headers=_HEADERS, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"[GUILDS] Error fetching leaderboard: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    guild_names = []
    for row in soup.select("#data-table-list tr"):
        link = row.select_one("td a[href*='/guild/']")
        if link:
            name = link.get_text(strip=True)
            if name:
                guild_names.append(name)

    print(f"[GUILDS] Found {len(guild_names)} guilds on leaderboard")
    return guild_names


def _fetch_guild_roster(guild_name: str, server: str) -> list[str]:
    """Fetch guild roster via API, returns list of character names."""
    # Replace spaces with + for URL encoding
    encoded_name = guild_name.replace(" ", "+")
    url = f"https://armory.warmane.com/api/guild/{encoded_name}/{server}/summary"

    try:
        resp = SESSION.get(url, headers=_HEADERS, timeout=HTTP_TIMEOUT)
        if resp.status_code == 429:
            print(f"  [429] Rate limited on '{guild_name}'. Waiting 10s...")
            time.sleep(10)
            resp = SESSION.get(url, headers=_HEADERS, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            print(f"  [{resp.status_code}] Failed for '{guild_name}'")
            return []

        data = resp.json()
        roster = data.get("roster", [])
        names = []
        for member in roster:
            name = str(member.get("name", "")).strip()
            if name:
                names.append(_normalize_name(name))
        return names

    except Exception as e:
        print(f"  [ERROR] '{guild_name}': {e}")
        return []


def collect_from_guilds(server: str, delay: float) -> set[str]:
    """Collect names from guild leaderboards + rosters."""
    guild_names = _scrape_guild_leaderboard(server)
    if not guild_names:
        print("[GUILDS] No guilds found. Check connectivity / rate limits.")
        return set()

    all_names = set()
    start = time.time()

    for idx, guild in enumerate(guild_names, 1):
        elapsed = time.time() - start
        speed = (idx - 1) / elapsed if idx > 1 else 0
        remaining = max(len(guild_names) - (idx - 1), 0)
        eta = int(remaining / speed) if speed > 0 else 0
        pct = (idx / len(guild_names)) * 100

        names = _fetch_guild_roster(guild, server)
        new_before = len(all_names)
        all_names.update(names)
        new_count = len(all_names) - new_before

        print(
            f"[{idx}/{len(guild_names)}] ({pct:.0f}%) {guild}: "
            f"{len(names)} members, {new_count} new | "
            f"total={len(all_names)} | eta={eta}s"
        )

        if idx < len(guild_names) and delay > 0:
            # Jitter: ±20% around the base delay
            jittered = delay * random.uniform(0.8, 1.2)
            time.sleep(jittered)

    elapsed = time.time() - start
    print(f"[GUILDS] Done in {int(elapsed)}s — {len(all_names)} unique names")
    return all_names


def collect_from_uwu(server: str, limit: int, best_only: bool) -> set[str]:
    """Collect names from UwU Logs (slower, ~540 queries)."""
    from src.schemas.constants import UWU_MODES_ALL, UWU_PDPS_BOSS_ORDER
    from tools.preload_character_gs import _collect_names_from_uwu

    print(f"[UWU] Recolectando desde UwU Logs ({server})...")
    names = set(_collect_names_from_uwu(server, limit=limit, best_only=best_only))
    print(f"[UWU] {len(names)} unique names collected")
    return names


def main():
    parser = argparse.ArgumentParser(
        description="Recolecta nombres de personajes de Warmane."
    )
    parser.add_argument(
        "--server",
        default="Lordaeron",
        help="Realm (default: Lordaeron)",
    )
    parser.add_argument(
        "--source",
        choices=["guilds", "uwu", "both"],
        default="guilds",
        help="Fuente de nombres (default: guilds)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Delay entre requests a guild API en segundos (default: 5)",
    )
    parser.add_argument(
        "--uwu-limit",
        type=int,
        default=200,
        help="Máximo de filas por query UwU (default: 200)",
    )
    parser.add_argument(
        "--uwu-best-only",
        action="store_true",
        help="Usa best_only=True al sembrar desde UwU",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(TRACKED_FILE),
        help=f"Archivo de salida (default: {TRACKED_FILE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo imprime los nombres, no escribe el archivo",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Reemplaza completamente el archivo (no merge)",
    )
    args = parser.parse_args()

    output_path = Path(args.output)

    # Read existing names
    existing_names = set()
    if not args.replace:
        existing_names = _read_existing_names(output_path)
        print(f"[INFO] Nombres existentes: {len(existing_names)}")

    # Collect from chosen source(s)
    new_names = set()
    if args.source in ("guilds", "both"):
        new_names |= collect_from_guilds(args.server, args.delay)
    if args.source in ("uwu", "both"):
        new_names |= collect_from_uwu(args.server, args.uwu_limit, args.uwu_best_only)

    # Merge
    all_names = existing_names | new_names
    all_names = {n for n in all_names if n}
    added = new_names - existing_names
    print(f"\n[RESUMEN] Total: {len(all_names)} | Existentes: {len(existing_names)} | Nuevos: {len(added)}")

    if args.dry_run:
        print("\n--- DRY RUN ---")
        for name in sorted(all_names)[:50]:
            marker = " (nuevo)" if name in added else ""
            print(f"  {name}{marker}")
        if len(all_names) > 50:
            print(f"  ... y {len(all_names) - 50} más")
        print(f"\n[DRY RUN] Total: {len(all_names)} nombres")
        return

    # Write
    _write_names(output_path, all_names, header="Lista de personajes semilla para GsChecker")
    print(f"[OK] {len(all_names)} nombres guardados en {output_path}")


if __name__ == "__main__":
    main()
