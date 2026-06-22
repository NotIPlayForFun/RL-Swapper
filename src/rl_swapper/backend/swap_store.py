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
from rl_swapper.backend.item_catalog import CatalogItem

# TODO consider if this is the best place for this helper
# helper to get a current iso timestamp string, since it's used in multiple places
def current_timestamp_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

# base class containing swap data
# TODO move to models.py
@dataclass(frozen=True)
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
    """filename.upk of the target"""
    donor_asset_package: str
    """filename.upk of the donor"""
    target_asset_path: str
    """internal asset path of the target, e.g. `"Package.Asset"` """
    donor_asset_path: str
    """internal asset path of the donor, e.g. `"Package.Asset"` """
    with_thumbnails: bool
    target_thumb_name: str | None
    """filename.upk of the target thumbnail, if applicable"""
    donor_thumb_name: str | None
    """filename.upk of the donor thumbnail, if applicable"""
    # pushed: bool
    status: Literal["prepared", "pushed", "reverted", "deleted"]
    created_at: str = field(default_factory=current_timestamp_iso)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pushed_at: str | None = None
    
    @classmethod
    def from_items(
        cls, 
        donor: CatalogItem, 
        target: CatalogItem, 
        with_thumbnails: bool, 
        target_thumb_name: str | None, 
        donor_thumb_name: str | None, 
        status: Literal["prepared", "pushed", "reverted", "deleted"],
        **kwargs
    ) -> SwapRecord:
        """Factory method to create a SwapRecord from donor and target CatalogItems.
        
        Other swap details are required to be passed to force the caller to be explicit about them."""
        return cls(
            target_name=target.asset_package,
            donor_name=donor.asset_package,
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
            status=status,
            pushed_at=None,
            **kwargs
        )
    
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
