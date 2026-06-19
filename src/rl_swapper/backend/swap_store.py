#!/usr/bin/env python3
"""Swap manifest persistence helpers for Rocket League UPK swapping."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
# import typing so we can make strings be literal "prepared" or "pushed"
from typing import Literal


@dataclass(frozen=True)
class SwapRecord:
    run_name: str
    run_dir: str
    target_name: str
    donor_name: str
    target_id: int
    donor_id: int
    target_product: str
    donor_product: str
    target_quality: str
    donor_quality: str
    target_slot: str
    donor_slot: str
    target_unlock_method: str
    donor_unlock_method: str
    target_asset_package: str
    donor_asset_package: str
    target_asset_path: str
    donor_asset_path: str
    with_thumbnails: bool
    target_thumb_name: str
    donor_thumb_name: str
    # pushed: bool
    status: Literal["prepared", "pushed", "reverted", "deleted"]
    created_at: str
    pushed_at: str | None = None
    id: int | None = None
    
    def is_pushed(self) -> bool:
        return self.status == "pushed"


def swap_manifest_path(run_dir: Path) -> Path:
    return run_dir / "swap.json"


def save_swap_manifest(swap: SwapRecord) -> None:
    run_dir = Path(swap.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    swap_manifest_path(run_dir).write_text(json.dumps(asdict(swap), indent=2), encoding="utf-8")


def load_swap_manifest(run_dir: Path) -> SwapRecord | None:
    manifest_path = swap_manifest_path(run_dir)
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return SwapRecord(**data)
    except Exception:
        return None


def list_swaps(runs_dir: Path) -> list[SwapRecord]:
    swaps: list[SwapRecord] = []
    if not runs_dir.exists():
        return swaps
    for child in sorted(runs_dir.iterdir(), key=lambda path: path.name.lower(), reverse=True):
        if child.is_dir():
            swap = load_swap_manifest(child)
            if swap is not None:
                swaps.append(swap)
    # sort by creation time desc
    swaps.sort(key=lambda s: s.created_at, reverse=True)
    return swaps


def mark_swap_pushed(swap: SwapRecord) -> SwapRecord:
    updated = SwapRecord(**{**asdict(swap), "status": "pushed", "pushed_at": datetime.now().isoformat(timespec="seconds")})
    save_swap_manifest(updated)
    return updated


def mark_swap_unpushed(swap: SwapRecord) -> SwapRecord:
    updated = SwapRecord(**{**asdict(swap), "status": "prepared", "pushed_at": None})
    save_swap_manifest(updated)
    return updated
