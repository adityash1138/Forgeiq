"""Idempotent database initializer — safe to run on every app startup.

A freshly-provisioned managed Postgres (Railway / Render / Supabase) starts
empty. Rather than make you run SQL by hand against a remote database, the API
calls init_db() on startup so the schema and config seed apply themselves on
first boot. Every statement is idempotent:

  - schema.sql uses CREATE TABLE/INDEX IF NOT EXISTS
  - seed_config.sql uses ON CONFLICT DO NOTHING

so running it again on an already-initialised database is a no-op.

Controlled by env vars (read at call time):
  FORGEIQ_AUTO_INIT=1   (default) run schema + seed_config on startup
  FORGEIQ_SEED_DEMO=1   also load demo data (db.seed_demo) — handy for a
                        first deploy so the dashboard isn't empty
"""
from __future__ import annotations

import os
from pathlib import Path

from db.connection import fetch_one, get_db_connection

HERE = Path(__file__).parent
SCHEMA_FILE = HERE / "schema.sql"
SEED_FILE = HERE / "seed_config.sql"


def _env_true(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def _run_sql_file(path: Path) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(path.read_text())


def _schema_present() -> bool:
    return fetch_one(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'industries'"
    ) is not None


def init_db(force: bool = False) -> dict:
    """Apply schema + config seed if needed. Returns a small status dict.

    Safe to call repeatedly. `force` re-applies even if tables already exist
    (still idempotent thanks to IF NOT EXISTS / ON CONFLICT).
    """
    status = {"schema": "skipped", "seed_config": "skipped", "demo": "skipped"}

    already = _schema_present()
    if force or not already:
        _run_sql_file(SCHEMA_FILE)
        status["schema"] = "applied"

    # seed_config is always safe (ON CONFLICT DO NOTHING) — guarantees the 13
    # signal types / negatives exist even if an older deploy missed them.
    _run_sql_file(SEED_FILE)
    status["seed_config"] = "applied"

    if _env_true("FORGEIQ_SEED_DEMO"):
        try:
            from db.seed_demo import seed as seed_demo
            seed_demo()
            status["demo"] = "applied"
        except Exception as exc:  # demo data is non-critical
            status["demo"] = f"failed: {exc}"

    return status


def maybe_init_on_startup() -> dict | None:
    """Called from the API startup hook. No-op unless FORGEIQ_AUTO_INIT is on."""
    if not _env_true("FORGEIQ_AUTO_INIT", default="1"):
        return None
    try:
        result = init_db()
        print(f"[init_db] {result}")
        return result
    except Exception as exc:
        # Never let DB init crash the web process — /health will report degraded.
        print(f"[init_db] startup initialization failed: {exc}")
        return {"error": str(exc)}


if __name__ == "__main__":
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL not set.")
    print(init_db(force=True))
