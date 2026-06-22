import logging
from pathlib import Path
import shutil

from rl_swapper.backend.models import SwapWorkspacePaths
from rl_swapper.config import AppSettings, load_settings
from rl_swapper.backend.models import SwapRecord

logger = logging.getLogger(__name__)

def create_swap_workspace(swap: SwapRecord) -> SwapWorkspacePaths:
    paths = SwapWorkspacePaths.from_swap_record(swap)
    # create workspace directories
    # TODO figure out if its best practice to create folder paths immediately or only when needed for files.
    # probably indeed best to create them immediately
    paths.workspace_dir.mkdir(parents=True, exist_ok=True)
    paths.source_dir.mkdir(parents=True, exist_ok=True)
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    return paths

def delete_swap_workspace(swap: SwapRecord) -> None:
    paths = SwapWorkspacePaths.from_swap_record(swap)
    
    # Check if workspace exists
    if not paths.workspace_dir.exists():
        logger.warning(f"Workspace directory for swap.id={swap.id} already does not exist at expected path {paths.workspace_dir}.")
        return
    
    # Delete workspace tree
    try:
        shutil.rmtree(paths.workspace_dir)
        logger.info(f"Successfully deleted workspace directory for swap.id={swap.id} at path {paths.workspace_dir}.")
        return
    except Exception as e:
        logger.error(f"Failed to delete workspace directory for swap.id={swap.id} at path {paths.workspace_dir}: {e}")
        raise e

def restore_target_from_backup(swap: SwapRecord) -> None:
    backup_path = SwapWorkspacePaths.from_swap_record(swap).backup_dir / swap.target_asset_package
    to_restore_path = load_settings().rl_source_dir_path / swap.target_asset_package

    if not backup_path.exists():
        logger.warning(f"Backup file for target does not exist at expected path {backup_path}. Cannot restore target from backup.")
        # TODO this is another place of many that the backend needs to communicate with the frontend
        # about results (in this case failure) of an action. For this we need to implement a route
        # of communication from backend to frontend, be that through directly passing messages
        # through called functions, or some event system. Event system would be more flexible for
        # asynchronous actions, but those will probably never be needed 
        raise FileNotFoundError(f"Backup file for target does not exist at expected path {backup_path}. Cannot restore target from backup.")
    if not to_restore_path.exists():
        logger.warning(f"Target file to restore does not exist at expected path {to_restore_path}. Cannot restore target from backup.")
        raise FileNotFoundError(f"Target file to restore does not exist at expected path {to_restore_path}. Cannot restore target from backup.")
        
    try:
        shutil.copy2(backup_path, to_restore_path)
        logger.info(f"Successfully restored target from backup for swap.id={swap.id} at path {to_restore_path}.")
    except Exception as e:
        logger.error(f"Failed to restore target from backup for swap.id={swap.id} at path {to_restore_path}: {e}")
        raise e

def stage_workspace_from_source(swap: SwapRecord) -> None:
    """Copy target and donor source files into workspace source directory.
    
    Also creates backup of source files in workspace backup directory."""
    paths = SwapWorkspacePaths.from_swap_record(swap)
    
    if not paths.source_dir.exists():
        logger.warning(f"Source directory for swap.id={swap.id} does not exist at expected path {paths.source_dir}. Cannot stage workspace from source.")
        raise FileNotFoundError(f"Source directory for swap.id={swap.id} does not exist at expected path {paths.source_dir}. Cannot stage workspace from source.")
    if not paths.backup_dir.exists():
        logger.warning(f"Backup directory for swap.id={swap.id} does not exist at expected path {paths.backup_dir}. Cannot stage workspace from source.")
        raise FileNotFoundError(f"Backup directory for swap.id={swap.id} does not exist at expected path {paths.backup_dir}. Cannot stage workspace from source.")
    
    # copy target and donor source files into workspace source dir
    try:
        shutil.copy2(load_settings().rl_source_dir_path / swap.target_asset_package, paths.source_dir / swap.target_asset_package)
        shutil.copy2(load_settings().rl_source_dir_path / swap.donor_asset_package, paths.source_dir / swap.donor_asset_package)
        logger.info(f"Successfully copied target and donor source files into workspace source directory for swap.id={swap.id}.")
    except Exception as e:
        logger.error(f"Failed to copy target and donor source files into workspace source directory for swap.id={swap.id}: {e}")
        raise e
    
    # create backup of target and donor source files in workspace backup dir
    try:
        shutil.copy2(load_settings().rl_source_dir_path / swap.target_asset_package, paths.backup_dir / swap.target_asset_package)
        shutil.copy2(load_settings().rl_source_dir_path / swap.donor_asset_package, paths.backup_dir / swap.donor_asset_package)
        logger.info(f"Successfully created backup of target and donor source files in workspace backup directory for swap.id={swap.id}.")
    except Exception as e:
        logger.error(f"Failed to create backup of target and donor source files in workspace backup directory for swap.id={swap.id}: {e}")
        raise e
    
    return

def push_swap_output_to_rl_source(swap: SwapRecord) -> None:
    """Copy swapped target and target-thumbnail (if present) 
    files from workspace output directory into rl source directory, 
    overwriting existing source files."""
    paths = SwapWorkspacePaths.from_swap_record(swap)
    
    output_target_path = paths.output_dir / swap.target_asset_package
    rl_source_target_path = load_settings().rl_source_dir_path / swap.target_asset_package
    if swap.with_thumbnails and swap.target_thumb_name:
        output_thumb_path = paths.output_dir / swap.target_thumb_name
        rl_source_thumb_path = load_settings().rl_source_dir_path / swap.target_thumb_name
    else    :
        output_thumb_path = None
        rl_source_thumb_path = None

    if not output_target_path.exists():
        logger.warning(f"Output target file does not exist at expected path {output_target_path}. Cannot push swap output to rl source.")
        raise FileNotFoundError(f"Output target file does not exist at expected path {output_target_path}. Cannot push swap output to rl source.")
    
    try:
        shutil.copy2(output_target_path, rl_source_target_path)
        logger.info(f"Successfully pushed swap output to rl source for swap.id={swap.id} at path {rl_source_target_path}.")
        if output_thumb_path and rl_source_thumb_path:
            shutil.copy2(output_thumb_path, rl_source_thumb_path)
            logger.info(f"Successfully pushed swap output thumbnail to rl source for swap.id={swap.id} at path {rl_source_thumb_path}.")
    except Exception as e:
        logger.error(f"Failed to push swap output for swap.id={swap.id} to rl source folder at {rl_source_target_path}: {e}")
        raise e

################################################################################
# TODO
# - first, move orchestration functions from legacy to new structure, using fs functions (that we will implement next) to handle the filesystem changes that need to happen in each step, and db functions to handle the db changes. This way we can keep all the logic for what needs to happen in each step in the orchestration layer, while keeping the actual implementation of how it happens in the fs and db layers.
# - then, implement those fs functions that are needed
# - then, the entire backend should be fully migrated to new structure.
# - Last, test migration of existing .json-based db
# - remove any legay code and run-based naming conventions