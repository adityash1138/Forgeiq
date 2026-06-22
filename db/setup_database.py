"""One-shot database setup: runs schema.sql then seed_config.sql.

Usage (after setting DATABASE_URL in your environment / .env):
    python -m db.setup_database

The schema is applied as a single block so foreign-key ordering holds. After
running, this prints a SELECT COUNT(*) for each table to confirm all 16 tables
were created and the config rows are present.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional in production (Railway injects env vars)

from db.connection import get_db_connection, fetch_all  # noqa: E402

HERE = Path(__file__).parent
SCHEMA_FILE = HERE / "schema.sql"
SEED_FILE = HERE / "seed_config.sql"

CORE_TABLES = [
    "industries", "vendor_categories", "applications",
    "signal_type_config", "cascade_wave_config", "negative_signals_config",
    "companies", "entity_resolution_queue", "raw_signals", "scores",
    "cascade_state", "contacts", "competitor_intelligence", "vendors",
    "lead_delivery", "outcomes",
]


def run_sql_file(path: Path) -> None:
    sql = path.read_text()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    print(f"  applied {path.name}")


def main() -> None:
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL not set. Add it to .env first.")

    print("Applying schema...")
    run_sql_file(SCHEMA_FILE)
    print("Seeding config...")
    run_sql_file(SEED_FILE)

    print("\nRow counts:")
    for table in CORE_TABLES:
        rows = fetch_all(f"SELECT COUNT(*) AS n FROM {table}")
        print(f"  {table:28s} {rows[0]['n']:>5}")

    sig = fetch_all("SELECT COUNT(*) AS n FROM signal_type_config")[0]["n"]
    print(f"\nsignal_type_config has {sig} rows (expected 13).")
    print("Done." if sig == 13 else "WARNING: expected 13 signal types.")


if __name__ == "__main__":
    main()
