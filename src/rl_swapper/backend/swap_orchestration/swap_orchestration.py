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
from rl_swapper.backend.swap_orchestration.models import SwapWorkspacePaths
from rl_swapper.backend.engine import rl_asset_swapper
from rl_swapper.backend.item_catalog import (
    CatalogItem,
    find_item_by_filename,
    find_item_by_product,
    find_item_id,
    load_items,
    search_items,
)
from rl_swapper.backend.swap_store import (
    SwapRecord,
    list_swaps,
    load_swap_manifest,
    mark_swap_pushed,
    mark_swap_unpushed,
    save_swap_manifest,
)
from rl_swapper.backend.database.migration import (
    migrate_all_legacy_swaps,
)
from rl_swapper.config import load_settings
import rl_swapper.backend.filesystem.filesystem as fs

logger = logging.getLogger(__name__)

# TODO the backend should ensure that initiate_backend has been called within the context, 
# f.e. through a context manager or global state variable
def initiate_backend(items_path: Path, swapper_path: Path, workspaces_dir: Path) -> None:
    """Validate that required UPK tools dependencies exist and create the workspaces folder.
    
    Handle database migration from legacy .json manifests if needed.

    Exits the process with an error message if the item catalog or the swapper
    script from UPK tools are missing.
    """
    if not items_path.exists():
        raise SystemExit(f"Missing items.json at {items_path}")
    if not swapper_path.exists():
        raise SystemExit(f"Missing rl_asset_swapper.py at {swapper_path}")
    workspaces_dir.mkdir(parents=True, exist_ok=True)
    
    # legacy database migration to new db/fs structure
    legacy_runs_dir: Path = load_settings().legacy_runs_path
    migrate_all_legacy_swaps(legacy_runs_dir=legacy_runs_dir)
    
# TODO #10 files should be backed up separately from individual swaps workspaces. This will
# make handling multiple swaps interacting with the same files easier.

def revert_swap(swap: SwapRecord) -> SwapRecord:
    """Revert a pushed swap on filesystem and update database.
    
    Uses the backup stored in the swap's workspace."""
    with closing(db.get_connection()) as conn:
        # TODO figure out whether it would be best practice to implement a 
        # double rollback mechanism where both db and fs can be rolled back in case of failure
        with conn:
            # ensure db entry exists
            if not swap_repo.get_swap(conn=conn, uuid=swap.id):
                raise SystemExit(f"Swap with id {swap.id} not found in database.")
            fs.restore_target_from_backup(swap=swap)
            new_swap: SwapRecord = swap_repo.mark_swap_reverted(conn=conn, uuid=swap.id)

    return new_swap


def revert_swap_legacy(swap: SwapRecord, rl_source_dir: Path) -> SwapRecord:
    """Restore the live Rocket League folder to the pre-swap target state.

    Copies the un-swapped UPKs from the backup folder within the swap's run
    directory back into CookedPCConsole.

    Args:
        swap: A SwapRecord containing metadata about the pushed files.
        rl_source_dir: The path to the live Rocket League CookedPCConsole folder.

    Returns:
        The updated SwapRecord with 'pushed' set to False.
    """
    run_dir = Path(swap.run_dir)
    backup_target_dir = run_dir / "source_backup" / "target"

    source = backup_target_dir / swap.target_name
    target_rl = rl_source_dir / swap.target_name
    message = f"Reverting push: copying {source} to {target_rl}"
    print(message)
    logging.info(f"revert_swap start {swap.run_name}: {source} -> {target_rl}")
    copy_required(source, target_rl)

    if swap.with_thumbnails and swap.target_thumb_name:
        source_thumb = backup_target_dir / swap.target_thumb_name
        target_thumb_rl = rl_source_dir / swap.target_thumb_name
        print(f"Reverting push: copying {source_thumb} to {target_thumb_rl}")
        if copy_if_exists(source_thumb, target_thumb_rl):
            logging.info(f"revert_swap thumb {swap.run_name}: {source_thumb} -> {target_thumb_rl}")
    logging.info(f"revert_swap complete {swap.run_name}")
    
    updated = mark_swap_unpushed(swap)
    return updated

# new delete_swap, implemented similarly to revert_swap
def delete_swap(swap: SwapRecord) -> SwapRecord:
    """Delete a swap's workspace and mark it as deleted in the database."""
    with closing(db.get_connection()) as conn:
        with conn:
            fs.delete_swap_workspace(swap=swap)
            new_swap: SwapRecord = swap_repo.mark_swap_deleted(conn=conn, uuid=swap.id)

    return new_swap
    

def delete_swap_legacy(swap: SwapRecord) -> None:
    """Permanently delete a swap run's folder and all its contents.

    This destroys the prepared files and backups for this run.
    """
    run_dir = Path(swap.run_dir)
    if not run_dir.exists():
        print(f"Swap run folder already missing: {run_dir}")
        logging.info(f"delete_swap missing {swap.run_name}: {run_dir}")
        return
    logging.info(f"delete_swap start {swap.run_name}: {run_dir}")
    shutil.rmtree(run_dir)
    print(f"Deleted prepared swap run folder: {run_dir}")
    logging.info(f"delete_swap complete {swap.run_name}: {run_dir}")

# legacy
def normalize_name(value: str) -> str:
    name = Path(value).name
    if not name.lower().endswith(".upk"):
        name += ".upk"
    return name


def stem_matches(asset_package: str, file_name: str) -> bool:
    left = Path(asset_package).name
    right = Path(file_name).name
    return left == right


def next_run_index(runs_dir: Path) -> int:
    run_index = 0
    if runs_dir.exists():
        for child in runs_dir.iterdir():
            if child.is_dir() and child.name.startswith("swap"):
                try:
                    index = int(child.name.split("swap")[1].split("__")[0])
                    run_index = max(run_index, index)
                except (ValueError, IndexError):
                    pass
    return run_index + 1


def infer_thumbnail_name(main_name: str) -> str:
    name = normalize_name(main_name)
    lower = name.lower()
    if lower.endswith("_sf.upk"):
        return name[:-7] + "_T_SF.upk"
    if lower.endswith(".upk"):
        return name[:-4] + "_T_SF.upk"
    return name + "_T_SF.upk"


def copy_required(src: Path, dst: Path) -> None:
    if not src.exists():
        raise SystemExit(f"Missing required file: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def write_comments(run_dir: Path, target_name: str, donor_name: str, target_comment: str, donor_comment: str, overall_comment: str) -> None:
    lines = [
        f"Target: {target_name}",
        f"Donor: {donor_name}",
        "",
        f"Target comment: {target_comment or '(none)'}",
        f"Donor comment: {donor_comment or '(none)'}",
        f"Overall comment: {overall_comment or '(none)'}",
        "",
    ]
    (run_dir / "comments.txt").write_text("\n".join(lines), encoding="utf-8")

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
        target_thumb_name: str | None = infer_thumbnail_name(target.asset_package)
        donor_thumb_name: str | None = infer_thumbnail_name(donor.asset_package)
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

def prepare_swap_legacy(
    donor: CatalogItem,
    target: CatalogItem,
    swapper_path: Path,
    items_path: Path,
    keys_path: Path | None,
    keys_map_path: Path | None,
    source_dir: Path,
    workspaces_dir: Path,
    work_dir: Path,
    with_thumbnails: bool = False,
    target_comment: str = "",
    donor_comment: str = "",
    overall_comment: str = "",
    write_back: bool = False,
) -> SwapRecord:
    """Stage files, create backups, and run rl_asset_swapper.py to generate a swapped UPK.
    
    This function sets up an isolated environment for the swap run:
      1. Generates a new `swap_runs/swapX` folder based on timestamps and donor/target.
      2. Creates a backup of the original `target` file.
      3. Copies the source UPKs into an internal source folder.
      4. Executes `rl_asset_swapper.py` to rewrite the properties.
      5. Leaves the finished swap file in the run's `output` folder.

    If `write_back` is True, it will immediately copy the output into `source_dir`.
    
    Args:
        donor: ItemRecord representing the donor item in the database.
        target: ItemRecord representing the target item in the database.
        swapper_path: Path to the `rl_asset_swapper.py` utility.
        source_dir: The directory from which upk files are read (usually the live CookedPCConsole).
        with_thumbnails: Extract and swap thumbnail packages alongside the main upks.
        target_comment: Informational comment representing target selection.
        donor_comment: Informational comment representing donor selection.
        overall_comment: General note.
        write_back: Immediately push the swap instead of stopping at staging.
        
    Returns:
        SwapRecord: Stored metadata about the resulting swap.
    """
    source_root = Path(source_dir)
    target_name = normalize_name(target.asset_package)
    donor_name = normalize_name(donor.asset_package)
    target_thumb_name = infer_thumbnail_name(target_name)
    donor_thumb_name = infer_thumbnail_name(donor_name)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_index = next_run_index(workspaces_dir)
    run_name = f"swap{run_index}__TARGET_{Path(target_name).stem}__from__DONOR_{Path(donor_name).stem}__{stamp}"
    run_dir = workspaces_dir / run_name
    source_donor_dir = run_dir / "source" / "donor"
    source_target_dir = run_dir / "source" / "target"
    output_target_dir = run_dir / "output" / "target"
    backup_donor_dir = run_dir / "source_backup" / "donor"
    backup_target_dir = run_dir / "source_backup" / "target"

    for directory in (
        source_target_dir,
        source_donor_dir,
        backup_target_dir,
        backup_donor_dir,
        output_target_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    target_src = source_root / target_name
    donor_src = source_root / donor_name
    target_thumb_src = source_root / target_thumb_name
    donor_thumb_src = source_root / donor_thumb_name

    copy_required(target_src, source_target_dir / target_name)
    copy_required(donor_src, source_donor_dir / donor_name)
    copy_required(target_src, backup_target_dir / target_name)
    copy_required(donor_src, backup_donor_dir / donor_name)

    copy_if_exists(target_thumb_src, source_target_dir / target_thumb_name)
    copy_if_exists(donor_thumb_src, source_donor_dir / donor_thumb_name)
    copy_if_exists(target_thumb_src, backup_target_dir / target_thumb_name)
    copy_if_exists(donor_thumb_src, backup_donor_dir / donor_thumb_name)

    write_comments(run_dir, target_name, donor_name, target_comment, donor_comment, overall_comment)

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
    if keys_path and keys_path.exists():
        swapper_args.extend(["--keys", str(keys_path)])
    if keys_map_path and keys_map_path.exists():
        swapper_args.extend(["--keys-map", str(keys_map_path)])
    if with_thumbnails:
        swapper_args.append("--include-thumbnails")
    else:
        swapper_args.append("--no-thumbnails")

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
            cwd=run_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip() or f"rl_asset_swapper.py failed with exit code {result.returncode}"
            print(details, file=sys.stderr)
            raise SystemExit(details)

    swap = SwapRecord(
        target_name=target_name,
        donor_name=donor_name,
        target_id=target.item_id,
        donor_id=donor.item_id,
        target_product=target.product,
        donor_product=donor.product,
        target_quality=target.quality,
        donor_quality=donor.quality,
        target_slot=target.slot,
        donor_slot=donor.slot,
        target_unlock_method=target.unlock_method,
        donor_unlock_method=donor.unlock_method,
        target_asset_package=target.asset_package,
        donor_asset_package=donor.asset_package,
        target_asset_path=target.asset_path,
        donor_asset_path=donor.asset_path,
        with_thumbnails=with_thumbnails,
        target_thumb_name=target_thumb_name,
        donor_thumb_name=donor_thumb_name,
        status="prepared",
        created_at=stamp,
        pushed_at=None,
    )

    if write_back:
        push_swap_output_to_rl(run_dir, target_name, target_thumb_name if with_thumbnails else "", with_thumbnails, source_dir)

    save_swap_manifest(swap)
    return swap


def push_swap_output_to_rl(run_dir: Path, target_name: str, target_thumb_name: str, with_thumbnails: bool, rl_source_dir: Path) -> None:
    output_target_dir = run_dir / "output" / "target"
    message = f"Pushing swap: copying {output_target_dir / target_name} to {rl_source_dir / target_name}"
    print(message)
    logging.info(f"push_swap start {run_dir.name}: {output_target_dir / target_name} -> {rl_source_dir / target_name}")
    copy_required(output_target_dir / target_name, rl_source_dir / target_name)
    if with_thumbnails and target_thumb_name:
        print(f"Pushing swap: copying {output_target_dir / target_thumb_name} to {rl_source_dir / target_thumb_name}")
        if copy_if_exists(output_target_dir / target_thumb_name, rl_source_dir / target_thumb_name):
            logging.info(f"push_swap thumb {run_dir.name}: {output_target_dir / target_thumb_name} -> {rl_source_dir / target_thumb_name}")
    logging.info(f"push_swap complete {run_dir.name}")


def push_swap(swap: SwapRecord, rl_source_dir: Path) -> SwapRecord:
    """Copy the fully prepared swap file from the output directory to the live RL folder.

    Updates the swap's state to reflect that the live game has been modified.
    
    Args:
        swap: A SwapRecord containing metadata about the swap run pointing to output.
        rl_source_dir: The path to the live Rocket League CookedPCConsole folder.

    Returns:
        The updated SwapRecord with 'pushed' set to True.
    """
    run_dir = Path(swap.run_dir)
    push_swap_output_to_rl(run_dir, swap.target_name, swap.target_thumb_name, swap.with_thumbnails, rl_source_dir)
    updated = mark_swap_pushed(swap)
    print(f"Push complete for {swap.id}; RL folder updated.")
    return updated