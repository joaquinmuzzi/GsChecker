"""Cron job entrypoint: precarga GearScore por spec para todos los personajes
rastreados (semilla en `data/tracked_characters.txt` + tabla `tracked_characters`
en Postgres), agrupando por reino y respetando delays para no gatillar 429.

Uso:
    python -m tools.run_scheduled_preload

Configurable por env vars:
    PRELOAD_TXT_PATH        Ruta al txt semilla (default: data/tracked_characters.txt)
    PRELOAD_DEFAULT_REALM   Reino asumido cuando el txt no lo especifica (default: Lordaeron)
    PRELOAD_DELAY_SECONDS   Pausa entre personajes (default: 5.0)
    PRELOAD_MAX_CHARACTERS  Corte duro para tandas grandes (default: 0 = sin límite)
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from src.db.postgres import init_database, list_tracked_characters
from src.schemas.constants import ARMORY_CIRCUIT
from tools.preload_character_gs import (
    _calculate_character_gs,
    _normalize_name,
    _store_character_gs,
)


logger = logging.getLogger("gschecker.preload_cron")


DEFAULT_TXT_PATH = "data/tracked_high_gs.txt"
DEFAULT_REALM = "Lordaeron"
DEFAULT_DELAY = 2.0


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _parse_txt_line(raw_line: str, default_realm: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None

    if "," in line:
        name_part, realm_part = line.split(",", 1)
    else:
        name_part, realm_part = line, default_realm

    name = _normalize_name(name_part)
    realm = str(realm_part or default_realm).strip() or default_realm
    if not name:
        return None
    return (name, realm)


def _load_from_txt(path: Path, default_realm: str) -> list[tuple[str, str]]:
    if not path.exists():
        logger.info("Archivo semilla no existe: %s (se omite)", path)
        return []

    pairs: list[tuple[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_txt_line(raw_line, default_realm)
        if parsed:
            pairs.append(parsed)
    logger.info("Leídos %s personajes de %s", len(pairs), path)
    return pairs


def _load_from_db() -> list[tuple[str, str]]:
    rows = list_tracked_characters()
    pairs = [(_normalize_name(name), realm.strip()) for name, realm in rows]
    pairs = [(n, r) for n, r in pairs if n and r]
    logger.info("Leídos %s personajes de la tabla tracked_characters", len(pairs))
    return pairs


def _dedupe_preserving_order(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for name, realm in pairs:
        key = (name.lower(), realm.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append((name, realm))
    return result


def _process_one(nombre: str, realm: str) -> tuple[bool, int]:
    payload = _calculate_character_gs(nombre, realm)
    if not payload:
        return (False, 0)
    stored = _store_character_gs(payload)
    return (True, stored)


def main() -> int:
    _configure_logging()
    load_dotenv()

    txt_path = Path(os.getenv("PRELOAD_TXT_PATH", DEFAULT_TXT_PATH))
    if not txt_path.is_absolute():
        txt_path = PROJECT_ROOT / txt_path

    default_realm = os.getenv("PRELOAD_DEFAULT_REALM", DEFAULT_REALM).strip() or DEFAULT_REALM
    delay = float(os.getenv("PRELOAD_DELAY_SECONDS", str(DEFAULT_DELAY)))
    max_characters = int(os.getenv("PRELOAD_MAX_CHARACTERS", "0"))

    from datetime import datetime
    today = datetime.now()
    if today.day == 1:
        logger.info("Día 1 del mes — ejecutando filter_high_gs primero...")
        try:
            from tools.filter_high_gs import main as filter_main
            import sys
            old_argv = sys.argv
            sys.argv = ["filter_high_gs", "--delay", "2"]
            try:
                filter_main()
            finally:
                sys.argv = old_argv
            logger.info("Filter completado, continuando con preload...")
        except Exception as exc:
            logger.warning("Filter falló (continuando con preload): %s", exc)

    init_database()

    txt_pairs = _load_from_txt(txt_path, default_realm)
    db_pairs = _load_from_db()

    all_pairs = _dedupe_preserving_order(txt_pairs + db_pairs)
    if max_characters and max_characters > 0:
        all_pairs = all_pairs[:max_characters]

    if not all_pairs:
        logger.warning(
            "No hay personajes para procesar. Agregá nombres a %s o usá el bot al menos una vez.",
            txt_path,
        )
        return 0

    logger.info(
        "Iniciando preload de %s personajes (delay=%.1fs, max=%s, txt=%s)",
        len(all_pairs),
        delay,
        max_characters or "sin límite",
        txt_path,
    )

    ok = 0
    skipped = 0
    stored_specs = 0
    run_start = time.time()

    for idx, (nombre, realm) in enumerate(all_pairs, start=1):
        while ARMORY_CIRCUIT.is_open():
            wait_s = int(ARMORY_CIRCUIT.seconds_until_close()) + 1
            logger.warning(
                "Circuit abierto, esperando %ss antes de continuar...", wait_s
            )
            time.sleep(min(wait_s, 30))

        elapsed = max(time.time() - run_start, 0.001)
        speed = (idx - 1) / elapsed if idx > 1 else 0
        remaining = max(len(all_pairs) - (idx - 1), 0)
        eta_sec = int(remaining / speed) if speed > 0 else 0
        pct = (idx / len(all_pairs)) * 100
        logger.info(
            "[%s/%s] (%.1f%%) %s/%s | ok=%s skip=%s specs=%s eta=%ss",
            idx,
            len(all_pairs),
            pct,
            nombre,
            realm,
            ok,
            skipped,
            stored_specs,
            eta_sec,
        )

        try:
            success, stored = _process_one(nombre, realm)
        except Exception as exc:
            logger.warning("Error procesando %s/%s: %s", nombre, realm, exc)
            skipped += 1
            if delay > 0:
                time.sleep(delay)
            continue

        if not success:
            skipped += 1
            logger.info("  [SKIP] No se pudo calcular %s/%s", nombre, realm)
        else:
            ok += 1
            stored_specs += stored
            logger.info("  [OK] %s/%s | stored=%s specs", nombre, realm, stored)

        if delay > 0:
            time.sleep(delay)

    duration = int(time.time() - run_start)
    logger.info(
        "Finalizado: ok=%s skip=%s specs_guardadas=%s duración=%ss",
        ok,
        skipped,
        stored_specs,
        duration,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
