"""Validación del nombre y el reino que escribe el usuario."""

from src.functions.names import is_valid_character_name

DEFAULT_CHARACTER_REALM = "Lordaeron"
SUPPORTED_CHARACTER_REALMS = {
    "lordaeron": "Lordaeron",
    "icecrown": "Icecrown",
    "blackrock": "Blackrock",
    "onyxia": "Onyxia",
    "frostmourne": "Frostmourne",
}


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
    raise ValueError(
        f"⚠️ Reino inválido: '{clean_realm}'. Reinos válidos: {valid_realms}."
    )
