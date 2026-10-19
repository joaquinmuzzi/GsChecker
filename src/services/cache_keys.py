"""Claves de la caché externa (Postgres `external_cache`).

Cambiar el formato de una clave invalida todo lo que ya está guardado con la
anterior: subir la versión (`v7`, `v2`) es la forma de hacerlo a propósito.
"""


def _build_personaje_cache_key(nombre: str) -> str:
    return f"command:personaje:v7:{nombre.strip().lower()}"


def _build_dps_cache_key(nombre: str, spec: str | None) -> str:
    return f"command:dps:v2:{nombre.strip().lower()}:{(spec or '').strip().lower()}"


def _build_character_spec_gs_key(nombre: str, server: str, spec_name: str) -> str:
    return f"character:spec-gs:{server.strip().lower()}:{nombre.strip().lower()}:{spec_name.strip().lower()}"


def _build_character_spec_gs_legacy_key(nombre: str, spec_name: str) -> str:
    return f"character:spec-gs:{nombre.strip().lower()}:{spec_name.strip().lower()}"


def _build_confirmed_icc_kills_key(nombre: str, server: str) -> str:
    return f"character:icc-confirmed-kills:{server.strip().lower()}:{nombre.strip().lower()}"
