"""Genera static/item_levels.json: ilvl, calidad y tipo de slot de cada ítem equipable de 3.3.5a.

gearscore.py calcula el GS de cada ítem con la fórmula del addon GearScore a partir
de esos tres datos. La fuente es el `item_template` de AzerothCore (la misma DB de
ítems de 3.3.5a que usa Warmane). Wowhead /wotlk no sirve para esto: es Wrath Classic
y varios ítems de Ulduar tienen otro ilvl (Constellus 252 en vez de 239).

Uso (el .sql pesa ~16 MB y no se guarda en el repo):

    git clone --depth 1 --filter=blob:none --sparse https://github.com/azerothcore/azerothcore-wotlk ac
    git -C ac sparse-checkout set --no-cone /data/sql/base/db_world/item_template.sql
    python tools/build_item_levels.py ac/data/sql/base/db_world/item_template.sql --commit $(git -C ac rev-parse HEAD)
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = BASE_DIR / "static" / "item_levels.json"

# Columnas de `item_template` (orden del CREATE TABLE de AzerothCore)
COL_ENTRY = 0
COL_QUALITY = 6
COL_INVENTORY_TYPE = 12
COL_ITEM_LEVEL = 15

# Tipos de slot que suman GS en el addon (camisa, tabardo, bolsas y munición no)
GS_INVENTORY_TYPES = {1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 20, 21, 22, 23, 25, 26, 28}
# Verde, azul, épico, legendario y reliquia (heirloom). Blancos y grises suman 0-2
# puntos en el addon y no vale la pena cargarlos.
GS_QUALITIES = {2, 3, 4, 5, 7}

_SQL_VALUE = re.compile(r"'(?:[^'\\]|\\.|'')*'|[^,]+")


def parse_item_template(sql_path: Path) -> dict[int, tuple[int, int, int]]:
    """item_id -> (ilvl, calidad, inventory_type) de las filas del dump."""
    items: dict[int, tuple[int, int, int]] = {}
    with sql_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.startswith("("):
                continue
            row = line.rstrip("\n").rstrip(";").rstrip(",")
            values = _SQL_VALUE.findall(row[1:-1])
            items[int(values[COL_ENTRY])] = (
                int(values[COL_ITEM_LEVEL]),
                int(values[COL_QUALITY]),
                int(values[COL_INVENTORY_TYPE]),
            )
    return items


def build_groups(items: dict[int, tuple[int, int, int]]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for item_id, (ilvl, quality, inventory_type) in items.items():
        if quality in GS_QUALITIES and inventory_type in GS_INVENTORY_TYPES:
            groups[f"{quality}:{inventory_type}:{ilvl}"].append(item_id)

    def sort_key(key: str) -> tuple[int, ...]:
        return tuple(int(part) for part in key.split(":"))

    return {key: sorted(groups[key]) for key in sorted(groups, key=sort_key)}


def write_output(groups: dict[str, list[int]], source: str, path: Path = OUTPUT_PATH) -> None:
    # Un grupo por línea: el archivo queda chico y un cambio se ve en el diff
    lines = [
        "{",
        f'  "_source": {json.dumps(source)},',
        '  "_format": "calidad:inventory_type:ilvl -> item IDs",',
        '  "groups": {',
    ]
    entries = [f"    {json.dumps(key)}: {json.dumps(ids)}" for key, ids in groups.items()]
    lines.append(",\n".join(entries))
    lines += ["  }", "}", ""]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("sql_path", type=Path, help="item_template.sql de AzerothCore")
    parser.add_argument("--commit", default="", help="commit de azerothcore-wotlk del que sale el .sql")
    args = parser.parse_args()

    items = parse_item_template(args.sql_path)
    groups = build_groups(items)
    source = "azerothcore-wotlk data/sql/base/db_world/item_template.sql"
    if args.commit:
        source += f" @ {args.commit}"
    write_output(groups, source)
    total = sum(len(ids) for ids in groups.values())
    print(f"{total} ítems equipables de {len(items)} filas -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
