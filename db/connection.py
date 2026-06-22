"""Database connection management for ForgeIQ.

Provides a single get_db_connection() entry point used by every module
(scrapers, processing pipeline, engine, API). Uses psycopg2 with a simple
connection pool. Reads DATABASE_URL from the environment — never hardcode it.
"""
import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool

# psycopg2 returns UUID columns as strings when we register the UUID adapter,
# which keeps the rest of the codebase free of psycopg2-specific types.
psycopg2.extras.register_uuid()

_pool: SimpleConnectionPool | None = None


def _get_pool() -> SimpleConnectionPool:
    """Lazily build the connection pool from DATABASE_URL."""
    global _pool
    if _pool is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. Add it to your .env (local) or "
                "Railway environment variables (production)."
            )
        _pool = SimpleConnectionPool(minconn=1, maxconn=10, dsn=database_url)
    return _pool


@contextmanager
def get_db_connection():
    """Yield a pooled connection, committing on success and rolling back on error.

    Usage:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(dict_rows: bool = True):
    """Yield a cursor directly. Defaults to dict-like rows (RealDictCursor).

    Usage:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM industries")
            rows = cur.fetchall()  # list of dicts
    """
    cursor_factory = psycopg2.extras.RealDictCursor if dict_rows else None
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            yield cur


def fetch_one(query: str, params: tuple = ()) -> dict | None:
    with get_cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def execute(query: str, params: tuple = ()) -> None:
    with get_cursor() as cur:
        cur.execute(query, params)


if __name__ == "__main__":
    # Smoke test: confirm the connection works and all 16 tables exist.
    expected_tables = {
        "industries", "vendor_categories", "applications",
        "signal_type_config", "cascade_wave_config", "negative_signals_config",
        "companies", "entity_resolution_queue", "raw_signals", "scores",
        "cascade_state", "contacts", "competitor_intelligence", "vendors",
        "lead_delivery", "outcomes",
    }
    rows = fetch_all(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public'"
    )
    present = {r["table_name"] for r in rows}
    missing = expected_tables - present
    print(f"Connected. {len(expected_tables & present)}/16 core tables present.")
    if missing:
        print(f"MISSING: {sorted(missing)}")
    else:
        print("All 16 core tables exist.")
