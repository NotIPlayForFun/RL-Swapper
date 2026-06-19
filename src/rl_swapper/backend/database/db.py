import sqlite3
from pathlib import Path

def get_connection(db_path: Path) -> sqlite3.Connection:
    """Get a connection to the swaps database and ensure the schema exists."""
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    # allow concurrent reads/writes and reduces locking issues
    conn.execute("PRAGMA journal_mode=WAL;")
    # enable foreign key constraints
    conn.execute("PRAGMA foreign_keys=ON;")
    # allow accessing columns by name
    conn.row_factory = sqlite3.Row
    
    # create tables if they don't exist
    _ensure_schema(conn)
    
    return conn

def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the swaps table if it doesn't exist."""
    conn.execute(
        # run_dir: mostly for backwards compatibility
        # run_name: unique, best practice to ensure rows are unique data-instances
        # with_thumbnails: boolean stored as integer
        # status: prepared, pushed, reverted, deleted
        # created_at, pushed_at: iso string
        """
        CREATE TABLE IF NOT EXISTS swaps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_name TEXT NOT NULL UNIQUE,
            run_dir TEXT NOT NULL,
            target_name TEXT NOT NULL,
            donor_name TEXT NOT NULL,
            target_id TEXT NOT NULL,
            donor_id TEXT NOT NULL,
            target_product TEXT,
            donor_product TEXT,
            target_quality TEXT,
            donor_quality TEXT,
            target_slot TEXT,
            donor_slot TEXT,
            target_unlock_method TEXT,
            donor_unlock_method TEXT,
            target_asset_package TEXT,
            donor_asset_package TEXT,
            target_asset_path TEXT,
            donor_asset_path TEXT,
            with_thumbnails INTEGER NOT NULL DEFAULT 0,
            target_thumb_name TEXT,
            donor_thumb_name TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            pushed_at TEXT
        );
    """)
    conn.commit()