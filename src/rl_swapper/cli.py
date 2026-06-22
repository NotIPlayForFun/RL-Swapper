#!/usr/bin/env python3
"""Command-line entry point for the UPK swap backend."""

from __future__ import annotations

import argparse
from pathlib import Path

from rl_swapper.backend.swap_orchestration.swap_orchestration import (
    initiate_backend,
    _infer_thumbnail_name,
    _normalize_name,
    prepare_swap,
)
from rl_swapper.backend.item_catalog import find_item_by_filename, load_items
from rl_swapper import config

def main() -> int:
    settings = config.load_settings()
    swap_workspaces_dir = Path(settings.workspaces_dir)
    config.setup_logging(swap_workspaces_dir)
    
    parser = argparse.ArgumentParser(description="Stage a Rocket League UPK swap from filenames")
    parser.add_argument("donor", help="Donor UPK filename to copy the visual data from")
    parser.add_argument("target", help="Target UPK filename to be replaced")
    parser.add_argument("--source-dir", type=Path, default=Path(settings.rl_source_dir), help="Folder containing the donor and target UPKs to stage from")
    parser.add_argument("--with-thumbnails", action="store_true", help="Also swap the thumbnail packages")
    parser.add_argument("--write-back", action="store_true", help="Copy the swapped target back into the live RL folder")
    parser.add_argument("--target-comment", default="", help="Short comment for the target decal")
    parser.add_argument("--donor-comment", default="", help="Short comment for the donor decal")
    parser.add_argument("--comment", default="", help="Short overall comment for the whole swap")
    parser.add_argument("--target-thumb", default="", help="Override target thumbnail filename")
    parser.add_argument("--donor-thumb", default="", help="Override donor thumbnail filename")
    args = parser.parse_args()

    initiate_backend(settings.items_path, settings.swapper_path, swap_workspaces_dir) # TODO remove ensure_workspace everywhere since files are always there

    items = load_items(settings.items_path)
    target_name = _normalize_name(args.target)
    donor_name = _normalize_name(args.donor)
    target_thumb_name = _normalize_name(args.target_thumb) if args.target_thumb else _infer_thumbnail_name(target_name)
    donor_thumb_name = _normalize_name(args.donor_thumb) if args.donor_thumb else _infer_thumbnail_name(donor_name)

    target_item = find_item_by_filename(target_name, items)
    donor_item = find_item_by_filename(donor_name, items)

    swap = prepare_swap(
        donor=donor_item,
        target=target_item,
        swapper_path=settings.swapper_path,
        items_path=settings.items_path,
        keys_path=settings.keys_path,
        keys_map_path=settings.keys_map_path,
        source_dir=args.source_dir,
        workspaces_dir=swap_workspaces_dir,
        work_dir=settings.decryption_work_path,
        with_thumbnails=args.with_thumbnails,
        target_comment=args.target_comment,
        donor_comment=args.donor_comment,
        overall_comment=args.comment,
        write_back=args.write_back,
    )

    if args.write_back:
        print("Live RL folder updated.")
    else:
        print("Live RL folder left untouched. Re-run with --write-back to apply the output.")

    print(f"Done. Run folder: {swap.run_dir}")
    print(f"Backup folder: {Path(swap.run_dir) / 'source_backup'}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
