from pathlib import Path

from rl_swapper.backend.item_catalog import CatalogItem
from rl_swapper.backend.utils import current_timestamp_iso


import uuid
from dataclasses import dataclass, field
from typing import Literal

from rl_swapper.config import load_settings

# TODO #12 implement some checks (at app start, not here) to make sure any swaps in the db
# as well as items in the shipped data catalog
# are still valid with current rocket league update, f.e.:
# - Check for rocket league version
# - Check that paths/ids/any information in the db and catalog
#   still matches current data from CookedPCConsole, 
#   and if not, mark them as invalid and let user/dev know

# SwapRecord is NOT normalized to only contain ids to be robust against
# and avoid the program getting confused when the catalog changes 
# and ids get reused for different items
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
    ) -> "SwapRecord":
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


@dataclass(frozen=True)
class SwapWorkspacePaths:
    """Data class representing the relevant paths to and within swap workspace.
    
    Can be constructed from a SwapRecord using `SwapWorkspacePaths.from_swap_record(...)`."""
    workspace_dir: Path
    source_dir: Path
    output_dir: Path
    backup_dir: Path

    @classmethod
    def from_swap_record(cls, swap_record: SwapRecord) -> "SwapWorkspacePaths":
        """Construct SwapWorkspacePaths from a SwapRecord."""
        settings = load_settings()
        workspace_dir = Path(settings.workspaces_dir) / f"{swap_record.id}"
        return cls(
            workspace_dir=workspace_dir,
            # TODO consider changing "source" to "input" to separet it from the original source dir.
            # But not necessarily a good idea
            source_dir=workspace_dir / "source",
            output_dir=workspace_dir / "output",
            backup_dir=workspace_dir / "backup",
        )