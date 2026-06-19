#!/usr/bin/env python3
"""Swap manifest persistence helpers for Rocket League UPK swapping."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
# import typing so we can make strings be literal "prepared" or "pushed"
from typing import Literal
import uuid

from rl_swapper import config

# base class containing swap data
@dataclass
class SwapRecord:
    """Data class representing a swap record tied to the sqlite3 db, 
    containing all relevant swap information and metadata."""
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
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pushed_at: str | None = None
    
    def is_pushed(self) -> bool:
        return self.status == "pushed"

# DB class containing swap data + DB ID
# @dataclass
# class SwapRecord(SwapRecord):
#     id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
#     @property
#     def run_dir(self) -> Path:
#         """Derive swap directory from ID to connect with filesystem"""
#         return config.load_settings().runs_dir_path / str(self.id)

# def swap_manifest_path(run_dir: Path) -> Path:
#     return run_dir / "swap.json"


# def save_swap_manifest(swap: SwapBase) -> None:
#     run_dir = Path(swap.run_dir)
#     run_dir.mkdir(parents=True, exist_ok=True)
#     swap_manifest_path(run_dir).write_text(json.dumps(asdict(swap), indent=2), encoding="utf-8")


# def load_swap_manifest(run_dir: Path) -> SwapBase | None:
#     manifest_path = swap_manifest_path(run_dir)
#     if not manifest_path.exists():
#         return None
#     try:
#         data = json.loads(manifest_path.read_text(encoding="utf-8"))
#         # TODO this is because db migration is in the works
#         # if it has "pushed" remove it
#         if "pushed" in data:
#             data["status"] = "pushed" if data.pop("pushed") else "prepared"
#         return SwapBase(**data)
#     except Exception as e:
#         print(f"Error loading swap manifest from {manifest_path}: {e}")
#         return None


# def list_swaps(runs_dir: Path) -> list[SwapBase]:
#     swaps: list[SwapBase] = []
#     if not runs_dir.exists():
#         return swaps
#     for child in sorted(runs_dir.iterdir(), key=lambda path: path.name.lower(), reverse=True):
#         if child.is_dir():
#             swap = load_swap_manifest(child)
#             if swap is not None:
#                 swaps.append(swap)
#     # sort by creation time desc
#     swaps.sort(key=lambda s: s.created_at, reverse=True)
#     return swaps


# def mark_swap_pushed(swap: SwapBase) -> SwapBase:
#     updated = SwapBase(**{**asdict(swap), "status": "pushed", "pushed_at": datetime.now().isoformat(timespec="seconds")})
#     save_swap_manifest(updated)
#     return updated


# def mark_swap_unpushed(swap: SwapBase) -> SwapBase:
#     updated = SwapBase(**{**asdict(swap), "status": "prepared", "pushed_at": None})
#     save_swap_manifest(updated)
#     return updated
