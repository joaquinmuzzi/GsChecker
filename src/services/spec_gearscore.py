"""GearScore por spec: qué specs tiene el personaje y el último GS conocido de cada una.

El GS del gear equipado solo vale para la spec activa; el de las otras specs sale
de lo que se guardó la última vez que el personaje las tuvo activas.
"""

from src.db.postgres import find_character_spec_gs_by_metadata, get_external_cache
from src.schemas.constants import CHARACTER_SPEC_GS_TTL
from src.services.cache_keys import (
    _build_character_spec_gs_key,
    _build_character_spec_gs_legacy_key,
)

CLASS_SPEC_FALLBACK = {
    "Death Knight": ["Blood", "Frost", "Unholy"],
    "Druid": ["Balance", "Feral Combat", "Restoration"],
    "Hunter": ["Beast Mastery", "Marksmanship", "Survival"],
    "Mage": ["Arcane", "Fire", "Frost"],
    "Paladin": ["Holy", "Protection", "Retribution"],
    "Priest": ["Discipline", "Holy", "Shadow"],
    "Rogue": ["Assassination", "Combat", "Subtlety"],
    "Shaman": ["Elemental", "Enhancement", "Restoration"],
    "Warlock": ["Affliction", "Demonology", "Destruction"],
    "Warrior": ["Arms", "Fury", "Protection"],
}

SPEC_SYNONYM_GROUPS = [
    ("Retribution", "Retri", "Ret"),
    ("Feral Combat", "Feral"),
    ("Beast Mastery", "BM"),
    ("Marksmanship", "MM"),
    ("Survival", "SV"),
    ("Death Knight", "DK"),
    ("Blood", "BDK"),
    ("Frost", "FDK"),
    ("Unholy", "UDK"),
]


def _fallback_spec_names_for_class(class_name: str) -> list[str]:
    clean_class_name = str(class_name or "").strip()
    return list(CLASS_SPEC_FALLBACK.get(clean_class_name, []))


def _spec_lookup_candidates(spec_name: str) -> list[str]:
    clean_name = str(spec_name or "").strip()
    if not clean_name:
        return []

    lowered = clean_name.lower()
    candidates = [clean_name]
    for group in SPEC_SYNONYM_GROUPS:
        group_lower = [entry.lower() for entry in group]
        if lowered in group_lower:
            for entry in group:
                if entry.lower() not in {value.lower() for value in candidates}:
                    candidates.append(entry)
            break
    return candidates


def _split_active_inactive_specs(talents, clase):
    if isinstance(talents, list) and len(talents) > 0:
        sorted_talents = sorted(talents, key=lambda t: not t.get("active", False))
        active_specs = [
            t.get("name", "N/A") for t in sorted_talents if t.get("active", False)
        ]
        inactive_specs = [
            t.get("name", "N/A")
            for t in sorted_talents
            if not t.get("active", False)
        ]
        # Warmane sometimes returns talents without an explicit active marker.
        # If no active spec is flagged, promote the first valid talent as active.
        if not active_specs:
            for talent in sorted_talents:
                candidate = str(talent.get("name") or "").strip()
                if not candidate or candidate == "N/A":
                    continue
                active_specs = [candidate]
                inactive_specs = [
                    name
                    for name in inactive_specs
                    if str(name or "").strip() != candidate
                ]
                break
        return active_specs, inactive_specs
    return [], _fallback_spec_names_for_class(clase)


def _get_known_gs_by_spec(
    nombre: str,
    server: str,
    spec_names: list[str],
    current_gs=None,
    active_specs=None,
):
    active_specs = set(active_specs or [])
    result = {}
    seen = set()
    for spec_name in spec_names:
        clean_name = str(spec_name or "").strip()
        if not clean_name or clean_name == "N/A" or clean_name in seen:
            continue
        seen.add(clean_name)

        cache_payload = None
        for lookup_spec_name in _spec_lookup_candidates(clean_name):
            cached = get_external_cache(
                "character_spec_gs",
                _build_character_spec_gs_key(nombre, server, lookup_spec_name),
                CHARACTER_SPEC_GS_TTL,
            )
            if isinstance(cached, dict) and cached.get("gs") not in {None, "N/A"}:
                cache_payload = cached
                break

            legacy_cached = get_external_cache(
                "character_spec_gs",
                _build_character_spec_gs_legacy_key(nombre, lookup_spec_name),
                CHARACTER_SPEC_GS_TTL,
            )
            if isinstance(legacy_cached, dict) and legacy_cached.get("gs") not in {
                None,
                "N/A",
            }:
                legacy_server = str(legacy_cached.get("server") or "").strip().lower()
                if legacy_server == str(server or "").strip().lower():
                    cache_payload = legacy_cached
                    break

        if cache_payload is None:
            metadata_cached = find_character_spec_gs_by_metadata(
                nombre,
                server,
                _spec_lookup_candidates(clean_name),
                CHARACTER_SPEC_GS_TTL,
            )
            if isinstance(metadata_cached, dict) and metadata_cached.get("gs") not in {
                None,
                "N/A",
            }:
                cache_payload = metadata_cached

        if isinstance(cache_payload, dict):
            result[clean_name] = cache_payload.get("gs")
        elif clean_name in active_specs and current_gs not in {None, "N/A"}:
            # current_gs reflects the gear currently equipped, which only
            # represents the spec that is actually active right now — never
            # an offspec, which may have been worn with different gear.
            result[clean_name] = current_gs
    return result


def _build_spec_gs_entries(
    spec_names: list[str],
    gs_by_spec: dict,
    active_specs: list[str] | None = None,
):
    active_spec_names = set(active_specs or [])
    entries = []
    seen = set()
    for spec_name in spec_names:
        clean_name = str(spec_name or "").strip()
        if not clean_name or clean_name == "N/A" or clean_name in seen:
            continue
        seen.add(clean_name)
        entries.append(
            {
                "name": clean_name,
                "main": clean_name in active_spec_names,
                "gearscore": gs_by_spec.get(clean_name, "?"),
            }
        )
    return sorted(
        entries, key=lambda entry: (not entry.get("main", False), entry.get("name", ""))
    )


def _format_spec_gs_value(spec_gs_entries: list[dict]) -> str:
    lines = []
    for entry in spec_gs_entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        label = f"**{name}**" if entry.get("main") else name
        lines.append(f"{label}: {entry.get('gearscore', '?')}")
    return "\n".join(lines) if lines else "?"
