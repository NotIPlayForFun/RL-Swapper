from contextlib import closing
import json
import logging
from logging import config
import sqlite3
from pathlib import Path
from typing import Iterator, Optional

from rl_swapper.backend.swap_store import SwapRecord, SwapRecord
import rl_swapper.backend.database.db as db
import rl_swapper.backend.database.swap_repository as db_repo

logger = logging.getLogger(__name__)


def iter_legacy_manifests(runs_dir: Path) -> Iterator[Path]:
    """
    Yield swap.json files under immediate run folders.
    
    Args:
        runs_dir: Path to the runs directory
        
    Yields:
        Path objects pointing to swap.json files found in run subdirectories
    """
    for run_folder in runs_dir.iterdir():
        if not run_folder.is_dir():
            continue
        
        swap_file = run_folder / "swap.json"
        if swap_file.exists() and swap_file.is_file():
            yield swap_file

def migrate_legacy_swap_to_new_db(swap: SwapRecord, legacy_folder_path: Path) -> bool:
    """
    Insert a swap folder with a .json-manifest into the SQLite database if it doesn't already exist there.
    Doesn't delete the .json, but is idempotent and can be re-run without creating duplications or issues.
    
    Args:
        swap: SwapRecord instance to insert into the database"""
    with closing(db.get_connection()) as conn:
        # everything that the database entry relies on should lie within "with conn:" in case of fs failure,
        # to avoid completed database entries without corresponding filesystem changes
        with conn:
            
            # check for existing record with id = folder name
            legacy_folder_name = legacy_folder_path.name
            existing = db_repo.get_swap(conn=conn, uuid=legacy_folder_name)
            if existing:
                # folder already in new db
                logger.info(f"Found folder on fs that has a legacy .json-manifest but \
                    already corresponds to existing db entry. Skipping migration.")
                return False
            
            # migrate to new db
            swap_db: SwapRecord = db_repo.insert_swap(conn=conn, swap=swap)
            
            # rename folder to match db entry
            new_folder_name = str(swap_db.id)
            new_folder_path = legacy_folder_path.parent / new_folder_name
            if legacy_folder_path != new_folder_path:
                legacy_folder_path.rename(new_folder_path)
                logger.info(f"Migrated legacy swap manifest from {legacy_folder_path} to new db with id {swap_db.id}, \
                    renamed folder to {new_folder_name}")
    return True

def load_legacy_swap(manifest_path: Path) -> Optional[SwapRecord]:
    """
    Load and normalize a legacy swap.json manifest to SwapRecord.
    
    Normalizes the old shape:
    - Map 'pushed' boolean to 'status' string
    - If 'pushed_at'=='', normalize to None
    
    Args:
        manifest_path: Path to the swap.json file
        
    Returns:
        SwapRecord if successfully loaded and normalized, None on parse/shape failure
    """
    try:
        with open(manifest_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to parse swap.json at {manifest_path}: {e}")
        raise e
    
    if not isinstance(data, dict):
        logger.warning(f"Invalid swap.json shape at {manifest_path}: expected dict, got {type(data).__name__}")
        raise ValueError(f"Invalid swap.json shape at {manifest_path}: expected dict, got {type(data).__name__}")
    
    try:
        # Normalize status based on legacy 'pushed' field
        if "status" not in data and "pushed" in data:
            data["status"] = "pushed" if data.pop("pushed") else "prepared"
        elif "pushed" in data:
            data.pop("pushed")
        
        # Normalize empty string pushed_at to None
        if data.get("pushed_at") == "":
            data["pushed_at"] = None
        
        return SwapRecord(**data)
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"Failed to create SwapRecord from {manifest_path}: {e}")
        raise e


def migrate_all_legacy_swaps(runs_dir: Path) -> dict[str, int]:
    """
    Migrate all legacy swap.json manifests found in runs_dir into the new database.
    
    Args:
        runs_dir: Path to the runs directory containing legacy swap folders with swap.json manifests
    Returns:
        A summary dict with counts of total found, successfully migrated, and skipped due to existing db entries.
    """
    summary = {
        "total_found": 0,
        "migrated": 0,
        "already_migrated": 0,
        "failed": 0
    }
    
    for manifest_path in iter_legacy_manifests(runs_dir):
        summary["total_found"] += 1
        try:
            swap = load_legacy_swap(manifest_path)
            if swap is None:
                logger.warning(f"Skipping {manifest_path} due to load failure.")
                summary["failed"] += 1
                continue
            
            migrated = migrate_legacy_swap_to_new_db(swap, manifest_path.parent)
            summary["migrated"] += 1 if migrated else 0
            summary["already_migrated"] += 0 if migrated else 1
        except Exception as e:
            logger.error(f"Error migrating {manifest_path}: {e}")
            summary["failed"] += 1
    
    return summary


