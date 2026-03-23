import json
import os
from contextlib import contextmanager

import psycopg


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if database_url:
        return database_url.strip()

    host = os.getenv("PGHOST")
    port = os.getenv("PGPORT", "5432")
    dbname = os.getenv("PGDATABASE")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")

    if host and dbname and user and password:
        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
    return ""


def db_enabled() -> bool:
    return bool(get_database_url())


@contextmanager
def _get_connection():
    conn = psycopg.connect(get_database_url(), connect_timeout=10)
    try:
        yield conn
    finally:
        conn.close()


def init_database() -> bool:
    if not db_enabled():
        print("[INFO] Postgres no configurado. Se usará solo caché en memoria.")
        return False

    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS external_api_cache (
                    cache_key TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    metadata_json TEXT,
                    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_external_api_cache_source_fetched_at
                ON external_api_cache (source, fetched_at DESC)
                """
            )
        conn.commit()

    print("[INFO] Postgres inicializado correctamente.")
    return True


def get_external_cache(source: str, cache_key: str, ttl_seconds: int):
    if not db_enabled():
        return None

    try:
        with _get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload_json
                    FROM external_api_cache
                    WHERE source = %s
                      AND cache_key = %s
                      AND fetched_at >= NOW() - (%s * INTERVAL '1 second')
                    LIMIT 1
                    """,
                    (source, cache_key, ttl_seconds),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return json.loads(row[0])
    except Exception as exc:
        print(f"[WARN] Error leyendo caché Postgres ({source}): {exc}")
        return None


def set_external_cache(
    source: str,
    endpoint: str,
    cache_key: str,
    payload,
    metadata: dict | None = None,
) -> None:
    if not db_enabled():
        return

    try:
        payload_json = json.dumps(payload, ensure_ascii=False)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        with _get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO external_api_cache (
                        cache_key,
                        source,
                        endpoint,
                        payload_json,
                        metadata_json,
                        fetched_at
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (cache_key)
                    DO UPDATE SET
                        source = EXCLUDED.source,
                        endpoint = EXCLUDED.endpoint,
                        payload_json = EXCLUDED.payload_json,
                        metadata_json = EXCLUDED.metadata_json,
                        fetched_at = NOW()
                    """,
                    (cache_key, source, endpoint, payload_json, metadata_json),
                )
            conn.commit()
    except Exception as exc:
        print(f"[WARN] Error guardando caché Postgres ({source}): {exc}")


def find_character_spec_gs_by_metadata(
    character_name: str,
    server: str,
    spec_candidates: list[str],
    ttl_seconds: int,
):
    if not db_enabled():
        return None

    clean_character = str(character_name or "").strip().lower()
    clean_server = str(server or "").strip().lower()
    clean_specs = [str(spec or "").strip().lower() for spec in spec_candidates if str(spec or "").strip()]
    if not clean_character or not clean_specs:
        return None

    try:
        with _get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload_json
                    FROM external_api_cache
                    WHERE source = 'character_spec_gs'
                      AND fetched_at >= NOW() - (%s * INTERVAL '1 second')
                      AND LOWER(
                            COALESCE(
                                metadata_json::jsonb->>'character',
                                payload_json::jsonb->>'character',
                                ''
                            )
                          ) = %s
                      AND LOWER(
                            COALESCE(
                                metadata_json::jsonb->>'spec',
                                payload_json::jsonb->>'spec',
                                ''
                            )
                          ) = ANY(%s)
                      AND (
                            LOWER(
                                COALESCE(
                                    metadata_json::jsonb->>'server',
                                    payload_json::jsonb->>'server',
                                    ''
                                )
                            ) = %s
                          )
                    ORDER BY fetched_at DESC
                    LIMIT 1
                    """,
                    (ttl_seconds, clean_character, clean_specs, clean_server),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return json.loads(row[0])
    except Exception as exc:
        print(f"[WARN] Error buscando spec GS por metadata ({character_name}/{server}): {exc}")
        return None
