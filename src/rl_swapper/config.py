import sys
import os
import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict

# old:
# SETTINGS_FILE = Path(__file__).resolve().parent / "app_settings.json"

# # Default paths based on original backend/upk_swap.py
# DEFAULT_RL_SOURCE_DIR = r"C:\Program Files\Epic Games\rocketleague\TAGame\CookedPCConsole"
# # Point to bundled resources folder (same directory as config.py)
# DEFAULT_VELOCITYRL_ROOT = str(Path(__file__).resolve().parent / "resources")
# # Work directory for temporary files (user can override in app_settings.json)
# DEFAULT_WORK_DIR = str(Path.home() / "AppData" / "Local" / "RL_UPK_Swapper" / "work")


# ---- Read-only data (assets/shipped data lives in app dir) ----
if getattr(sys, 'frozen', False):
    APP_DIR = Path(sys._MEIPASS)
else:
    APP_DIR = Path(__file__).resolve().parent

# TODO add resoures/python json/txt file paths here

# asset paths
# ICON_PATH = APP_DIR / "icon.png"

# ---- Read/write data (runs, logs, user config lives in user profile) ----
USER_DATA_DIR = Path(os.getenv('LOCALAPPDATA') or Path.home() / "AppData" / "Local") / "RL_UPK_Swapper"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = USER_DATA_DIR / "app_settings.json"

# -- Default paths (can be overridden by user config) --
DEFAULT_RL_SOURCE_DIR = r"C:\Program Files\Epic Games\rocketleague\TAGame\CookedPCConsole"
DEFAULT_VELOCITYRL_ROOT = str(APP_DIR / "resources")
DEFAULT_WORK_DIR = str(USER_DATA_DIR / "work")

@dataclass
class AppSettings:
    rl_source_dir: str = DEFAULT_RL_SOURCE_DIR
    velocityrl_root: str = DEFAULT_VELOCITYRL_ROOT
    work_dir: str = DEFAULT_WORK_DIR # for decrypted files, used by rl_asset_swapper.py
    runs_dir: str = str(USER_DATA_DIR / "swap_runs")

    @property
    def items_path(self) -> Path:
        return Path(self.velocityrl_root) / "python" / "items.json"

    @property
    def keys_path(self) -> Path:
        return Path(self.velocityrl_root) / "python" / "keys.txt"

    @property
    def keys_map_path(self) -> Path:
        return Path(self.velocityrl_root) / "python" / "keys_map.json"

    @property
    def swapper_path(self) -> Path:
        return Path(self.velocityrl_root) / "python" / "rl_asset_swapper.py"

    @property
    def work_path(self) -> Path:
        return Path(self.work_dir)


def load_settings() -> AppSettings:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return AppSettings(**data)
        except Exception:
            pass
    return AppSettings()


def save_settings(settings: AppSettings) -> None:
    SETTINGS_FILE.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")


def setup_logging() -> None:
    log_file = USER_DATA_DIR / "activity.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_file),
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
