
from dataclasses import dataclass
from pathlib import Path
from rl_swapper.backend.swap_store import SwapRecord
from rl_swapper.config import load_settings

# dataclass for paths in a swap workspace. Can be constructed from a SwapRecord
@dataclass(frozen=True)
class SwapWorkspacePaths:
    workspace_dir: Path
    source_dir: Path
    output_dir: Path
    backup_dir: Path

    @classmethod
    def from_swap_record(cls, swap_record: SwapRecord) -> "SwapWorkspacePaths":
        """Construct SwapWorkspacePaths from a SwapRecord."""
        settings = load_settings()
        workspace_dir = Path(settings.workspaces_dir) / f"swap_{swap_record.id}"
        return cls(
            workspace_dir=workspace_dir,
            source_dir=workspace_dir / "source",
            output_dir=workspace_dir / "output",
            backup_dir=workspace_dir / "backup",
        )