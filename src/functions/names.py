import re

# Nombres de personaje de WoW: solo letras (con acentos), entre 2 y 12.
# Filtra basura como los placeholders "C_7119121" de uwu-logs o "Veletriel\".
_VALID_CHARACTER_NAME = re.compile(r"^[^\W\d_]{2,12}$")


def is_valid_character_name(name) -> bool:
    return bool(_VALID_CHARACTER_NAME.match(str(name or "").strip()))
