#!/usr/bin/env python3
r"""Stage and run a Rocket League UPK swap from filenames.

Usage examples:
  py prepare_rl_swap.py skin_grain_lightning_SF.upk skin_grain_KarmineCorp_SF.upk
  py prepare_rl_swap.py skin_grain_lightning_SF.upk skin_grain_KarmineCorp_SF.upk \
      --with-thumbnails
    py prepare_rl_swap.py skin_grain_lightning_SF.upk skin_grain_KarmineCorp_SF.upk \
            --target-comment "swap to lightning" --donor-comment "from karmine" --comment "test run"

By default this:
    - looks for the files in C:\Program Files\Epic Games\rocketleague\TAGame\CookedPCConsole
  - stages them into a local folder under ./swap_runs/
  - creates a backup copy of the target
  - runs python/rl_asset_swapper.py without thumbnails
    - leaves the live RL folder untouched unless --write-back is given

If you move this script outside the repo, set VELOCITYRL_ROOT to the folder
that still contains python/items.json and python/rl_asset_swapper.py.

With --with-thumbnails, provide --target-thumb/--donor-thumb if you want to
override the inferred thumbnail names.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from rl_swapper.backend.item_catalog import (
    ItemRecord,
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


def ensure_workspace(items_path: Path, swapper_path: Path, runs_dir: Path) -> None:
    """Validate that required VelocityRL dependencies exist and create the runs folder.

    Exits the process with an error message if the item catalog or the swapper
    script from VelocityRL are missing.
    """
    if not items_path.exists():
        raise SystemExit(f"Missing items.json at {items_path}")
    if not swapper_path.exists():
        raise SystemExit(f"Missing rl_asset_swapper.py at {swapper_path}")
    runs_dir.mkdir(parents=True, exist_ok=True)


def revert_swap(swap: SwapRecord, rl_source_dir: Path) -> SwapRecord:
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


def delete_swap(swap: SwapRecord) -> None:
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


def prepare_swap(
    donor: ItemRecord,
    target: ItemRecord,
    swapper_path: Path,
    source_dir: Path,
    runs_dir: Path,
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
    run_index = next_run_index(runs_dir)
    run_name = f"swap{run_index}__TARGET_{Path(target_name).stem}__from__DONOR_{Path(donor_name).stem}__{stamp}"
    run_dir = runs_dir / run_name
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

    command = [
        sys.executable,
        str(swapper_path),
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
    if with_thumbnails:
        command.append("--include-thumbnails")
    else:
        command.append("--no-thumbnails")

    result = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parent,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or f"rl_asset_swapper.py failed with exit code {result.returncode}"
        print(details, file=sys.stderr)
        raise SystemExit(details)

    swap = SwapRecord(
        run_name=run_name,
        run_dir=str(run_dir),
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
        pushed=False,
        created_at=stamp,
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
    print(f"Push complete for {swap.run_name}; RL folder updated.")
    return updated