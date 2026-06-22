#!/usr/bin/env python3

# This file should call orchestrate swap operations 
# such as prepare, push, revert, delete
# by calling fs and db layers. For this, it contains relevant context objects
# (like RunPaths), but delegates actual fs or db operations to the respective layers.



from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from rl_swapper.backend.database import db
import rl_swapper.backend.database.swap_repository as swap_repo
from rl_swapper.backend.models import SwapRecord
from rl_swapper.backend.models import SwapWorkspacePaths
from rl_swapper.backend.engine import rl_asset_swapper
from rl_swapper.backend.item_catalog import (
    CatalogItem,
)
from rl_swapper.backend.utils import (
    current_timestamp_iso,
)

from rl_swapper.config import load_settings
import rl_swapper.backend.filesystem.filesystem as fs

logger = logging.getLogger(__name__)

# TODO the backend should ensure that initiate_backend has been called within the context, 
# f.e. through a context manager or global state variable
def initiate_backend(items_path: Path, swapper_path: Path) -> None:
    """Validate that required UPK tools dependencies exist and create the workspaces folder.

    Exits the process with an error message if the item catalog or the swapper
    script from UPK tools are missing.
    """
    if not items_path.exists():
        raise SystemExit(f"Missing items.json at {items_path}")
    if not swapper_path.exists():
        raise SystemExit(f"Missing rl_asset_swapper.py at {swapper_path}")
    # workspaces_dir.mkdir(parents=True, exist_ok=True)
    
    # legacy database migration to new db/fs structure
    # DEPRECTATED, DOESNT WORK WHEN USED MULTIPLE TIMES!!
    # legacy_runs_dir: Path = load_settings().legacy_runs_path
    # migrated_info_dict = migrate_all_legacy_swaps(legacy_runs_dir=legacy_runs_dir)
    # logger.info(f"Completed legacy migration with info: {migrated_info_dict}")
    # print(f"Completed legacy migration with info: {migrated_info_dict}")
    # import time
    # time.sleep(25)
    
# TODO #10 files should be backed up separately from individual swaps workspaces. This will
# make handling multiple swaps interacting with the same files easier.

def revert_swap(swap: SwapRecord) -> SwapRecord:
    """Revert a pushed swap on filesystem and update database.
    
    Uses the backup stored in the swap's workspace."""
    with closing(db.get_connection()) as conn: # context manager: close connection after block
        # TODO figure out whether it would be best practice to implement a 
        # double rollback mechanism where both db and fs can be rolled back in case of failure
        with conn: # context manager, transaction management: rollback on exception
            # ensure db entry exists
            if not swap_repo.get_swap(conn=conn, uuid=swap.id):
                raise SystemExit(f"Swap with id {swap.id} not found in database.")
            fs.restore_target_from_backup(swap=swap)
            new_swap: SwapRecord = swap_repo.mark_swap_reverted(conn=conn, uuid=swap.id)

    return new_swap

def list_swaps(include_deleted: bool = False) -> list[SwapRecord]:
    """List all swaps, optionally including those marked as deleted."""
    with closing(db.get_connection()) as conn:
        return swap_repo.list_swaps(conn=conn, include_deleted=include_deleted)


# new delete_swap, implemented similarly to revert_swap
def delete_swap(swap: SwapRecord) -> SwapRecord:
    """Delete a swap's workspace and mark it as deleted in the database.
    
    Raises exception if swap currently marked as pushed."""
    with closing(db.get_connection()) as conn:
        with conn:
            # ensure db entry exists and is not pushed
            existing = swap_repo.get_swap(conn=conn, uuid=swap.id)
            if not existing:
                logger.error(f"Swap with id {swap.id} not found in database.")
                raise SystemExit(f"Swap with id {swap.id} not found in database.")
            if existing.is_pushed():
                logger.error(f"Cannot delete swap with id {swap.id} because it is currently pushed.")
                raise SystemExit(f"Cannot delete swap with id {swap.id} because it is currently pushed.")
            
            # delete workspace    
            fs.delete_swap_workspace(swap=swap)

            # mark swap as deleted in db
            new_swap: SwapRecord = swap_repo.mark_swap_deleted(conn=conn, uuid=swap.id)

    return new_swap

# TODO legacy, left here for now
def _normalize_name(value: str) -> str:
    name = Path(value).name
    if not name.lower().endswith(".upk"):
        name += ".upk"
    return name

def _infer_thumbnail_name(main_name: str) -> str:
    name = _normalize_name(main_name)
    lower = name.lower()
    if lower.endswith("_sf.upk"):
        return name[:-7] + "_T_SF.upk"
    if lower.endswith(".upk"):
        return name[:-4] + "_T_SF.upk"
    return name + "_T_SF.upk"


def _asset_swapper_cli_helper(
    items_path: Path,
    source_donor_dir: Path,
    output_target_dir: Path,
    source_target_dir: Path,
    work_dir: Path,
    target: CatalogItem,
    donor: CatalogItem,
    with_thumbnails: bool,
    target_thumb_name: str | None,
    donor_thumb_name: str | None,
    keys_path: Path,
    keys_map_path: Path,
):
    """Run rl_asset_swapper using it's cli functionality."""
    swapper_args = [
        "--items",
        str(items_path),
        "--donor-dir",
        str(source_donor_dir),
        "--output-dir",
        str(output_target_dir),
        "--key-source-dir",
        str(source_target_dir),
        "--work-dir",
        str(work_dir),
        "--target",
        str(target.item_id),
        "--donor",
        str(donor.item_id),
    ]
    
    # keys, keys map from config and thumbnail handling
    swapper_args.append("--include-thumbnails" if with_thumbnails else "--no-thumbnails")
    swapper_args.extend(["--keys", str(keys_path)])
    swapper_args.extend(["--keys-map", str(keys_map_path)])
    
    if getattr(sys, "frozen", False):
        # In PyInstaller builds, sys.executable points to the bundled app,
        # so spawning "-m rl_swapper..." is unreliable. Run swapper in-process.
        from rl_swapper.backend.engine import rl_asset_swapper as swapper_module

        parser = swapper_module.build_arg_parser()
        parsed_args = parser.parse_args(swapper_args)
        return_code = swapper_module.cli_run(parsed_args)
        if return_code != 0:
            raise SystemExit(f"rl_asset_swapper failed with exit code {return_code}")
    else:
        # TODO low priority: after db, fs and orchestration migration and overall redesign and 
        # cleanup, refactor this to call the relevant swapper module function directly.
        command = [
            sys.executable,
            "-m",
            "rl_swapper.backend.engine.rl_asset_swapper",
            *swapper_args,
        ]
        result = subprocess.run(
            command,
            cwd=work_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip() or f"rl_asset_swapper.py failed with exit code {result.returncode}"
            print(details, file=sys.stderr)
            raise SystemExit(details)
    

# prepare_swap implemented using the new fs and db layers and config
def prepare_swap(
    donor: CatalogItem,
    target: CatalogItem,
    with_thumbnails: bool = False,
) -> SwapRecord | None:
    """"""
    # Thumbnail handling
    if with_thumbnails:
        target_thumb_name: str | None = _infer_thumbnail_name(target.asset_package)
        donor_thumb_name: str | None = _infer_thumbnail_name(donor.asset_package)
        if target_thumb_name is not None and not Path(target_thumb_name).exists():
            logging.info(f"Thumbnail for target not found, continuing without it: {target_thumb_name}")
            target_thumb_name = None
        if donor_thumb_name is not None and not Path(donor_thumb_name).exists():
            logging.info(f"Thumbnail for donor not found, continuing without it: {donor_thumb_name}")
            donor_thumb_name = None
    else:
        target_thumb_name = None
        donor_thumb_name = None
    
    with closing(db.get_connection()) as conn:
        with conn:
            # create swap record
            swap = SwapRecord.from_items(
                donor=donor, 
                target=target, 
                with_thumbnails=with_thumbnails,
                target_thumb_name=target_thumb_name,
                donor_thumb_name=donor_thumb_name,
                status="prepared",
                )
            # insert swap record into db
            swap = swap_repo.insert_swap(conn=conn, swap=swap)
            
            # create workspace
            fs.create_swap_workspace(swap=swap)
            swap_paths = SwapWorkspacePaths.from_swap_record(swap)
            
            # stage workspace from source
            fs.stage_workspace_from_source(swap=swap)
            
            # run swapper
            _asset_swapper_cli_helper(
                items_path=load_settings().items_path,
                source_donor_dir=swap_paths.source_dir / "donor",
                output_target_dir=swap_paths.output_dir / "target",
                source_target_dir=swap_paths.source_dir / "target",
                work_dir=load_settings().decryption_work_path,
                target=target,
                donor=donor,
                with_thumbnails=with_thumbnails,
                target_thumb_name=target_thumb_name,
                donor_thumb_name=donor_thumb_name,
                keys_path=load_settings().keys_path,
                keys_map_path=load_settings().keys_map_path,
            )
            
            # verify output
            output_target_file = swap_paths.output_dir / "target" / swap.target_name
            if not output_target_file.exists():
                # TODO need to find a way for backend to communicate with frontend.
                # f.e. whether a swap worked, and maybe some info about that if it failed.
                logger.error(f"Expected output file not found after running swapper: {output_target_file}")
                fs.delete_swap_workspace(swap=swap)
                swap_repo.mark_swap_deleted(conn=conn, uuid=swap.id)
                return None
    return swap

def push_swap(swap: SwapRecord) -> SwapRecord:
    """Push a prepared swap to the live Rocket League folder and update database."""
    # implements a push_swap using new fs and db layers, similar to prepare_swap
    
    with closing(db.get_connection()) as conn:
        with conn:
            # ensure db entry exists
            if not swap_repo.get_swap(conn=conn, uuid=swap.id):
                logger.error(f"Swap with id {swap.id} not found in database.")
                # TODO figure out whether SystemExit is best practice here.
                # But regardless, backend should communicate to frontend here,
                # be that through an error (maybe custom exception) or other option
                raise SystemExit(f"Swap with id {swap.id} not found in database.")
            # TODO allow swapping pushed thumbnails separately from pushed skin.
            # Currently just pushes whatever the output of the swap was, which
            # either includes or doesnt include also the thumbnail upk

            # push swap output to rl source dir
            fs.push_swap_output_to_rl_source(swap=swap)

            # update db record to mark as pushed at current timestamp
            new_swap: SwapRecord = swap_repo.mark_swap_pushed(conn=conn, uuid=swap.id, pushed_at_iso=current_timestamp_iso())

    return new_swap