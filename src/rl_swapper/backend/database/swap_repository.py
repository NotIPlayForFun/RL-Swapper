import sqlite3
from pathlib import Path

from rl_swapper.backend.swap_store import SwapRecord
from rl_swapper.backend.database.query_helpers import (
    SWAP_TABLE_COLUMNS,
    columns_to_stringlist,
    columns_to_params_stringlist,
    params_to_values_dir,
)

def row_to_swap_record(row: sqlite3.Row) -> SwapRecord:
    """Convert a sqlite3.Row from the swaps table into a SwapRecord instance"""
    
    return SwapRecord(
        id=row["id"],
        run_name=row["run_name"],
        run_dir=row["run_dir"],
        target_name=row["target_name"],
        donor_name=row["donor_name"],
        target_id=row["target_id"],
        donor_id=row["donor_id"],
        target_product=row["target_product"],
        donor_product=row["donor_product"],
        target_quality=row["target_quality"],
        donor_quality=row["donor_quality"],
        target_slot=row["target_slot"],
        donor_slot=row["donor_slot"],
        target_unlock_method=row["target_unlock_method"],
        donor_unlock_method=row["donor_unlock_method"],
        target_asset_package=row["target_asset_package"],
        donor_asset_package=row["donor_asset_package"],
        target_asset_path=row["target_asset_path"],
        donor_asset_path=row["donor_asset_path"],
        with_thumbnails=bool(row["with_thumbnails"]),
        target_thumb_name=row["target_thumb_name"],
        donor_thumb_name=row["donor_thumb_name"],
        status=row["status"],
        created_at=row["created_at"],
        pushed_at=row["pushed_at"]
    )

def insert_swap_record(conn: sqlite3.Connection, swap: SwapRecord) -> int:
    """Insert a new swap record into the database and return its ID."""
    
    try:
        with conn:
            cursor = conn.execute(
                f"""INSERT INTO swaps (
                    {columns_to_stringlist(SWAP_TABLE_COLUMNS)}
                ) VALUES (
                    {columns_to_params_stringlist(SWAP_TABLE_COLUMNS)}
                )""",
                {
                    **params_to_values_dir(swap)
                }
            )
        if cursor.lastrowid is None:
            raise ValueError("Insert failed to return an ID.")
        return cursor.lastrowid
    except sqlite3.IntegrityError as e:
        # This can happen if run_name is not unique
        raise ValueError(f"Swap with run_name '{swap.run_name}' already exists. " +
                            "Skipping insertion.")

def get_swap_by_run_dir(conn: sqlite3.Connection, run_dir: Path) -> SwapRecord | None:
    """Fetch a swap record by its run_dir, or return None if not found."""
    row = conn.execute("SELECT * FROM swaps WHERE run_dir = ?", (str(run_dir),)).fetchone()
    if row:
        return row_to_swap_record(row)
    return None

def get_swap_by_run_name(conn: sqlite3.Connection, run_name: str) -> SwapRecord | None:
    """Fetch a swap record by its run_name, or return None if not found."""
    row = conn.execute("SELECT * FROM swaps WHERE run_name = ?", (run_name,)).fetchone()
    if row:
        return row_to_swap_record(row)
    return None

def get_swap(conn: sqlite3.Connection, id: int) -> SwapRecord | None:
    """Fetch a swap record by its id, or return None if not found."""
    row = conn.execute("SELECT * FROM swaps WHERE id = ?", (id,)).fetchone()
    if row:
        return row_to_swap_record(row)
    return None

def list_swaps(conn: sqlite3.Connection, include_deleted: bool = False) -> list[SwapRecord]:
    """List all swap records, optionally including those marked as deleted."""
    query = "SELECT * FROM swaps"
    if not include_deleted:
        query += " WHERE status != 'deleted'"
    rows = conn.execute(query).fetchall()
    return [row_to_swap_record(row) for row in rows]

def mark_swap_pushed(conn: sqlite3.Connection, id: int, pushed_at_iso: str) -> None:
    """Update a swap record to mark it as pushed."""
    with conn:
        conn.execute(
            "UPDATE swaps SET status = 'pushed', pushed_at = ? WHERE id = ?",
            (pushed_at_iso, id)
        )

def mark_swap_reverted(conn: sqlite3.Connection, id: int) -> None:
    """Update a swap record to mark it as reverted."""
    with conn:
        conn.execute(
            "UPDATE swaps SET status = 'reverted' WHERE id = ?",
            (id,)
        )

def mark_swap_deleted(conn: sqlite3.Connection, id: int) -> None:
    """Update a swap record to mark it as deleted."""
    with conn:
        conn.execute(
            "UPDATE swaps SET status = 'deleted' WHERE id = ?",
            (id,)
        )

def upsert_swap(conn: sqlite3.Connection, swap: SwapRecord) -> int:
    """Insert a new swap record or update an existing one based on run_name."""
    existing = get_swap_by_run_name(conn, swap.run_name)
    if existing:
        # Update existing record
        with conn:
            cursor = conn.execute(
                f"""INSERT INTO swaps (
                    {columns_to_stringlist(SWAP_TABLE_COLUMNS)}
                ) VALUES (
                    {columns_to_params_stringlist(SWAP_TABLE_COLUMNS)}
                ) ON CONFLICT(run_name) DO UPDATE SET
                    {", ".join(f"{col}=EXCLUDED.{col}" for col in SWAP_TABLE_COLUMNS)}
                    RETURNING id
                """,
                {
                    **params_to_values_dir(swap)
                }
            )
        row = cursor.fetchone()
        if row is not None:
            if row["id"] is None:
                raise ValueError("Upsert failed to return an id.")
            return row["id"]
        else:
            raise ValueError("Upsert failed to return a row.")
    else:
        # Insert new record
        return insert_swap_record(conn, swap)
