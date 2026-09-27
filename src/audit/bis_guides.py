"""BiS por reino, armado con lo que equipan los mejores jugadores de Warmane.

Warmane Lordaeron tiene los jefes reforzados y Icecrown es blizzlike, así que
las guías genéricas de WotLK no sirven: `tools/build_bis_from_armory.py` lee del
armory el equipo de los jugadores con más GS de cada spec (candidatos sacados
de los rankings ICC 25H de uwu-logs) y genera `static/bis/<reino>.json`. Este
módulo convierte esos datos en `BisGuide` para el auditor de /ia.

La clasificación de roles y tipos de spec vive acá para que el generador y el
bot usen exactamente la misma regla.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .models import BisGuide, BisItemOption, BisSlot, StatCap

BIS_DIR = Path(__file__).resolve().parents[2] / "static" / "bis"
GUIDE_REALMS = ("Lordaeron", "Icecrown")

# Tanques: DKs de cualquier spec con mucho esquivar (muestra del armory
# 2026-09-27: tanques 23-29 %, DPS 6-13 %), Feral oso por aguante, y
# Protection siempre.
DK_TANK_DODGE_PCT = 18.0
FERAL_BEAR_STAMINA = 3300

CASTER_SPECS = {
    ("Druid", "Balance"), ("Mage", "Arcane"), ("Mage", "Fire"), ("Mage", "Frost"),
    ("Priest", "Shadow"), ("Shaman", "Elemental"), ("Warlock", "Affliction"),
    ("Warlock", "Demonology"), ("Warlock", "Destruction"),
}
HEALER_SPECS = {
    ("Druid", "Restoration"), ("Paladin", "Holy"), ("Priest", "Discipline"),
    ("Priest", "Holy"), ("Shaman", "Restoration"),
}
# Clases/specs donde el mismo árbol se juega de tanque o de DPS: la guía se
# separa por rol.
SPLIT_ROLE_CLASSES = {"Death Knight"}
SPLIT_ROLE_SPECS = {("Druid", "Feral Combat")}


def is_caster(char_class: str, spec: str) -> bool:
    return (char_class, spec) in CASTER_SPECS


def detect_role(char_class: str, spec: str, stats: dict) -> str:
    """"Tank", "DPS" o "" (specs con un solo rol posible)."""
    if spec == "Protection":
        return "Tank"
    if char_class in SPLIT_ROLE_CLASSES:
        dodge = stats.get("dodge_pct")
        return "Tank" if isinstance(dodge, (int, float)) and dodge >= DK_TANK_DODGE_PCT else "DPS"
    if (char_class, spec) in SPLIT_ROLE_SPECS:
        stamina = stats.get("stamina")
        return "Tank" if isinstance(stamina, (int, float)) and stamina >= FERAL_BEAR_STAMINA else "DPS"
    return ""


def normalize_realm(realm: str | None) -> str | None:
    clean = str(realm or "").strip().lower()
    return next((r for r in GUIDE_REALMS if r.lower() == clean), None)


@lru_cache(maxsize=None)
def _load_realm(realm: str) -> dict:
    path = BIS_DIR / f"{realm.lower()}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def available_guides(realm: str) -> list[str]:
    """Etiquetas legibles de las guías de un reino, ej. 'Death Knight Blood (Tank)'."""
    guides = _load_realm(realm).get("guides", {})
    labels = []
    for key in sorted(guides):
        char_class, spec, role = key.split("|")
        labels.append(f"{char_class} {spec}" + (f" ({role})" if role else ""))
    return labels


_POOLED = {"Finger": ("Finger 1", "Finger 2"), "Trinket": ("Trinket 1", "Trinket 2")}


def get_bis_guide(
    char_class: str, spec: str, realm: str = "Lordaeron", role: str = ""
) -> BisGuide | None:
    """BiS del reino para clase + spec (+ rol en DK / Feral), o None si no hay
    datos suficientes."""
    realm_name = normalize_realm(realm)
    if realm_name is None:
        return None
    data = _load_realm(realm_name)
    raw = data.get("guides", {}).get(f"{char_class.strip()}|{spec.strip()}|{role}")
    if raw is None:
        return None

    n = raw["sample_size"]
    slots: dict[str, BisSlot] = {}
    for pooled, slot in raw["slots"].items():
        options = [
            BisItemOption(
                item_id=opt["item_id"],
                item_name=opt["item_name"],
                tier_note=f"lo usan {opt['used_by']}/{n} top de {realm_name}",
            )
            for opt in slot["options"]
        ]
        for slot_name in _POOLED.get(pooled, (pooled,)):
            slots[slot_name] = BisSlot(
                slot=slot_name,
                options=options,
                required_enchant_ids=slot.get("enchant_ids", []),
                enchant_display_name=slot.get("enchant_label", ""),
            )

    meta = raw.get("meta_gem") or {}
    role_label = f" ({role})" if role else ""
    lo, hi = raw["gs_range"]
    return BisGuide(
        spec_name=f"{char_class} {spec}{role_label} · {realm_name}",
        char_class=char_class,
        spec=spec,
        slots=slots,
        stat_caps=[StatCap(**cap) for cap in raw.get("stat_caps", [])],
        meta_gem_id=meta.get("item_id"),
        meta_gem_name=meta.get("name", ""),
        nightmare_tear_required=raw.get("nightmare_tear_share", 0) >= 0.5,
        item_names=data.get("item_names", {}),
        priority_note=(
            f"BiS armado con lo que equipan los {n} jugadores de {spec}{role_label} "
            f"con más GS de Warmane {realm_name} (GS {lo}-{hi}), datos del "
            f"{data.get('generated', '?')}."
        ),
    )
