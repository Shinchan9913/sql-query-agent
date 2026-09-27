"""Build the sample SQLite database from schema.sql and seed.sql."""

import sqlite3
import sys
from pathlib import Path

DB_DIR = Path(__file__).parent
DEFAULT_DB_PATH = DB_DIR / "sample.db"


def init_db(db_path: Path = DEFAULT_DB_PATH) -> Path:
    db_path.unlink(missing_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript((DB_DIR / "schema.sql").read_text())
        conn.executescript((DB_DIR / "seed.sql").read_text())
    return db_path


if __name__ == "__main__":
    path = init_db(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH)
    print(f"Created {path}")
