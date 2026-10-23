"""tools/build_item_levels.py: lectura del item_template.sql de AzerothCore."""

from __future__ import annotations

import json

from tools.build_item_levels import build_groups, parse_item_template, write_output

# Primeras columnas de filas reales del dump (el parser solo usa entry, Quality,
# InventoryType e ItemLevel). Val'anyr trae una comilla escapada y una coma en el nombre.
SQL_SAMPLE = """INSERT INTO `item_template` VALUES
(53,4,0,-1,'Neophyte\\'s Shirt',9944,1,0,0,1,1,1,4,-1,-1,1,0,0,0),
(37086,4,0,-1,'Tome of Salramm',51600,3,0,0,1,200603,50150,23,-1,-1,187,78,0,0),
(46017,2,4,-1,'Val\\'anyr, Hammer of Ancient Kings',61655,5,0,0,1,1818255,363651,21,32767,-1,245,80,0,0);
"""


def test_parse_reads_item_level_quality_and_slot(tmp_path):
    sql_path = tmp_path / "item_template.sql"
    sql_path.write_text(SQL_SAMPLE, encoding="utf-8")

    items = parse_item_template(sql_path)

    assert items == {53: (1, 1, 4), 37086: (187, 3, 23), 46017: (245, 5, 21)}


def test_groups_skip_items_that_never_add_gearscore(tmp_path):
    sql_path = tmp_path / "item_template.sql"
    sql_path.write_text(SQL_SAMPLE, encoding="utf-8")

    groups = build_groups(parse_item_template(sql_path))

    # La camisa blanca no suma GS en el addon
    assert groups == {"3:23:187": [37086], "5:21:245": [46017]}


def test_output_is_valid_json(tmp_path):
    out = tmp_path / "item_levels.json"

    write_output({"3:23:187": [37086], "5:21:245": [46017]}, "test", out)

    assert json.loads(out.read_text(encoding="utf-8"))["groups"]["5:21:245"] == [46017]
