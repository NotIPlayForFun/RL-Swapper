





# DO NOT USE WITHOUT READING!!!
# --------------------------------- IMPORTANT NOTE ---------------------------------
# --------------------------------- IMPORTANT NOTE ---------------------------------
# --------------------------------- IMPORTANT NOTE ---------------------------------
# DO NOT USE WITHOUT READING!!!
# 
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# 
# DO NOT USE WITHOUT READING!!!
#
# This is not functional. It ran once correctly, but has AT LEAST the following problems:
#
# - It ports the legacy swap.json manifest and comments.txt
# - Doesn't utilize the filesystem.py, which means any changes to filesystem handling are not reflected here
#
# - Doesn't check for whether a swap was already migrated correctly. It checks whether it exists in db,
# but of course the newly created SwapRecord has its own new uuid, meaning it
# 
# >!>>>!>>>> WILL KEEP MIGRATING ALL LEGACY SWAPS TO NEW DB AND FS UUID ENTITIES EVERYTIME IT IS RUN<<<<<<<<<<
#
# - The above could be solved by adding a legacy_id to the new workspace folder of a swap, but
# I don't care since I'm the only person that needed to run it, I ran it only once, manually cleaned up the
# legacy swap.json and comments.txt, and will never run it again.





















from contextlib import closing
import json
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Iterator, Optional

from rl_swapper import config
from rl_swapper.backend.swap_store import SwapRecord, SwapRecord
import rl_swapper.backend.database.db as db
import rl_swapper.backend.database.swap_repository as db_repo

logger = logging.getLogger(__name__)


def iter_legacy_manifests(legacy_runs_dir: Path) -> Iterator[Path]:
    """
    Yield swap.json files under immediate run folders.
    
    Args:
        legacy_runs_dir: Path to the legacy runs directory
        
    Yields:
        Path objects pointing to swap.json files found in run subdirectories
    """
    for run_folder in legacy_runs_dir.iterdir():
        if not run_folder.is_dir():
            continue
        
        swap_file = run_folder / "swap.json"
        if swap_file.exists() and swap_file.is_file():
            yield swap_file

def migrate_legacy_swap_to_new_db(swap: SwapRecord, legacy_folder_path: Path) -> bool:
    """
    Insert a swap folder with a .json-manifest into the SQLite database if it doesn't already exist there.
    Additionally, create the necessary workspace folder in new workspace structure if not already present.
    Doesn't delete the .json, but is idempotent and can be re-run without creating duplications or issues.
    
    Args:
        swap: SwapRecord instance to insert into the database"""
    with closing(db.get_connection()) as conn:
        # everything that the database entry relies on should lie within "with conn:" in case of fs failure,
        # to avoid completed database entries without corresponding filesystem changes
        with conn:
            
            # check for existing record with id = folder name
            legacy_folder_name = legacy_folder_path.name
            in_db = db_repo.get_swap(conn=conn, uuid=legacy_folder_name)
            if in_db:
                # folder already in new db
                logger.info(f"Found folder on fs that has a legacy .json-manifest but \
                    already corresponds to existing db entry. Skipping migration.")
                return False
            
            # migrate to new db
            swap_db: SwapRecord = db_repo.insert_swap(conn=conn, swap=swap)
            
            # copy folder to new workspace structure with new name = db id
            workspaces_dir = config.load_settings().workspaces_path
            new_folder_name = str(swap_db.id)
            new_folder_path = workspaces_dir / new_folder_name
            if new_folder_path.exists():
                logger.warning(f"{new_folder_path} already exists but didn't have a corresponding db entry. Aborting.")
                raise FileExistsError(f"{new_folder_path} already exists but didn't have a corresponding db entry. Aborting.")
            # copy legacy folder to new location with new name
            # recursively copy entire folder and subfolders and files to new location with new name
            # note: also copies the legacy swap.json, but this is ignored by the new system
            shutil.copytree(legacy_folder_path, new_folder_path)
            logger.info(f"Migrated legacy swap manifest from {legacy_folder_path} to new db with id {swap_db.id}, \
                associated fs-folder is named {new_folder_name} and located at {new_folder_path}")
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
        
        if data["status"] == "pushed" and not data.get("pushed_at"):
            logger.warning(f"Legacy swap manifest at {manifest_path} has status 'pushed' but missing 'pushed_at' timestamp. Setting 'pushed_at' to None.")
            raise ValueError(f"Legacy swap manifest at {manifest_path} has status 'pushed' but missing 'pushed_at' timestamp. Setting 'pushed_at' to None.")
        
        if not data["created_at"] or not isinstance(data["created_at"], str):
            logger.warning(f"Legacy swap manifest at {manifest_path} has null 'created_at' timestamp. This field is required in the new system. Cannot migrate this swap.")
            raise ValueError(f"Legacy swap manifest at {manifest_path} has null 'created_at' timestamp. This field is required in the new system. Cannot migrate this swap.")
        
        # Normalize empty string pushed_at to None
        if data.get("pushed_at") == "":
            data["pushed_at"] = None
        
        return SwapRecord(
            target_name=data["target_name"],
            donor_name=data["donor_name"],
            target_id=data["target_id"],
            donor_id=data["donor_id"],
            target_product=data["target_product"],
            donor_product=data["donor_product"],
            target_quality=data["target_quality"],
            donor_quality=data["donor_quality"],
            target_slot=data["target_slot"],
            donor_slot=data["donor_slot"],
            target_unlock_method=data["target_unlock_method"],
            donor_unlock_method=data["donor_unlock_method"],
            target_asset_package=data["target_asset_package"],
            donor_asset_package=data["donor_asset_package"],
            target_asset_path=data["target_asset_path"],
            donor_asset_path=data["donor_asset_path"],
            with_thumbnails=data["with_thumbnails"],
            target_thumb_name=data.get("target_thumb_name"),
            donor_thumb_name=data.get("donor_thumb_name"),
            status=data["status"],
            pushed_at=data.get("pushed_at"),
            created_at=data.get("created_at")
        )
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"Failed to create SwapRecord from {manifest_path}: {e}")
        raise e


def migrate_all_legacy_swaps(legacy_runs_dir: Path) -> dict[str, int]:
    """
    Migrate all legacy swap.json manifests found in legacy_runs_dir into the new database.
    
    Args:
        legacy_runs_dir: Path to the runs directory containing legacy swap folders with swap.json manifests
    Returns:
        A summary dict with counts of total found, successfully migrated, and skipped due to existing db entries.
    """
    summary = {
        "total_found": 0,
        "migrated": 0,
        "already_migrated": 0,
        "failed": 0
    }
    
    for manifest_path in iter_legacy_manifests(legacy_runs_dir):
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
            raise e
    
    return summary


