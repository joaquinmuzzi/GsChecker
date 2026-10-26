"""Validación del nombre y el reino que escribe el usuario."""

import re

from src.functions.names import is_valid_character_name

DEFAULT_CHARACTER_REALM = "Lordaeron"
SUPPORTED_CHARACTER_REALMS = {
    "lordaeron": "Lordaeron",
    "icecrown": "Icecrown",
    "blackrock": "Blackrock",
    "onyxia": "Onyxia",
    "frostmourne": "Frostmourne",
}


_NAME_WITH_REALM = re.compile(r"^\s*(?P<name>[^()]+?)\s*\(\s*(?P<realm>[^()]+?)\s*\)\s*$")


def split_name_and_realm(nombre: str | None, reino: str | None = None) -> tuple[str, str | None]:
    """Separa el valor "Nombre (Reino)" que devuelve el autocompletado.

    Si el usuario ya eligió un reino, manda ese; si no, el del paréntesis (solo
    cuando es un reino soportado). Un texto sin paréntesis queda igual.
    """
    match = _NAME_WITH_REALM.match(str(nombre or ""))
    if not match:
        return str(nombre or ""), reino
    realm_from_name = SUPPORTED_CHARACTER_REALMS.get(match.group("realm").lower())
    if realm_from_name is None:
        return str(nombre or ""), reino
    return match.group("name"), (reino or realm_from_name)


def _normalize_character_name(nombre: str | None) -> str:
    """Capitaliza y valida el nombre antes de tocar el armory: un nombre imposible
    (ej. "C_123") no existe en Warmane y consultarlo gasta ~15 requests del
    rate limit compartido por todos los usuarios."""
    clean_name = str(nombre or "").strip().capitalize()
    if not is_valid_character_name(clean_name):
        raise ValueError(
            f"⚠️ '{str(nombre or '').strip()}' no es un nombre de personaje válido "
            "(solo letras, entre 2 y 12)."
        )
    return clean_name


def _normalize_character_realm(reino: str | None) -> str:
    clean_realm = str(reino or "").strip()
    if not clean_realm:
        return DEFAULT_CHARACTER_REALM

    normalized = SUPPORTED_CHARACTER_REALMS.get(clean_realm.lower())
    if normalized:
        return normalized

    title_realm = clean_realm.title()
    normalized = SUPPORTED_CHARACTER_REALMS.get(title_realm.lower())
    if normalized:
        return normalized

    valid_realms = ", ".join(SUPPORTED_CHARACTER_REALMS.values())
    raise ValueError(f"⚠️ Reino inválido: '{clean_realm}'. Reinos válidos: {valid_realms}.")
