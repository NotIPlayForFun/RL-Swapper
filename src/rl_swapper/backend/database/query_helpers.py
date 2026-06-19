from rl_swapper.backend.swap_store import SwapRecord


SWAP_TABLE_COLUMNS = [
    "run_name", "run_dir", "target_name", "donor_name", 
    "target_id", "donor_id", "target_product", "donor_product", 
    "target_quality", "donor_quality", "target_slot", "donor_slot", 
    "target_unlock_method", "donor_unlock_method", "target_asset_package", 
    "donor_asset_package", "target_asset_path", "donor_asset_path", 
    "with_thumbnails", "target_thumb_name", "donor_thumb_name", 
    "status", "created_at", "pushed_at"
]

def columns_to_stringlist(columns: list[str]) -> str:
    """Convert a list of column names into a comma-separated string."""
    return ", ".join(columns)

def columns_to_params_stringlist(columns: list[str]) -> str:
    """Convert a list of column names into a string of SQL parameters for binding."""
    return ", ".join(f":{col}" for col in columns)

def params_to_values_dir(swap: SwapRecord) -> dict[str, str | int | bool | None]:
    """Convert a SwapRecord into a dict suitable for SQL parameter binding."""
    return {
        "run_name": swap.run_name,
        "run_dir": swap.run_dir,
        "target_name": swap.target_name,
        "donor_name": swap.donor_name,
        "target_id": swap.target_id,
        "donor_id": swap.donor_id,
        "target_product": swap.target_product,
        "donor_product": swap.donor_product,
        "target_quality": swap.target_quality,
        "donor_quality": swap.donor_quality,
        "target_slot": swap.target_slot,
        "donor_slot": swap.donor_slot,
        "target_unlock_method": swap.target_unlock_method,
        "donor_unlock_method": swap.donor_unlock_method,
        "target_asset_package": swap.target_asset_package,
        "donor_asset_package": swap.donor_asset_package,
        "target_asset_path": swap.target_asset_path,
        "donor_asset_path": swap.donor_asset_path,
        "with_thumbnails": int(swap.with_thumbnails),
        "target_thumb_name": swap.target_thumb_name,
        "donor_thumb_name": swap.donor_thumb_name,
        "status": swap.status,
        "created_at": swap.created_at,
        "pushed_at": swap.pushed_at
    }