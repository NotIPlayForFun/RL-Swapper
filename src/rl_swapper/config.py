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
# # Point to bundled data folder (same directory as config.py)
# UPK_TOOLS = str(Path(__file__).resolve().parent / "data")
# # Work directory for temporary files (user can override in app_settings.json)
# DEFAULT_WORK_DIR = str(Path.home() / "AppData" / "Local" / "RL_UPK_Swapper" / "work")


# ---- Read-only data (assets/shipped data lives in app dir) ----
if getattr(sys, 'frozen', False):
    # to make mypy happy
    if hasattr(sys, '_MEIPASS'):
        APP_DIR = Path(sys._MEIPASS)
    else:
        # error
        raise RuntimeError("Frozen app missing _MEIPASS attribute")
else:
    APP_DIR = Path(__file__).resolve().parent

# TODO add resoures/python json/txt file paths here

# asset paths
# ICON_PATH = APP_DIR / "icon.png"
SHIPPED_DATA_DIR = APP_DIR / "data"

# ---- Read/write data (runs, logs, user config lives in user profile) ----
USER_DATA_DIR = Path(os.getenv('LOCALAPPDATA') or Path.home() / "AppData" / "Local") / "RL_UPK_Swapper"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
SWAPS_DB_FILE = USER_DATA_DIR / "swaps.db"
USER_SETTINGS_FILE = USER_DATA_DIR / "app_settings.json"

# -- Default paths (can be overridden by user config) --
DEFAULT_RL_SOURCE_DIR = r"C:\Program Files\Epic Games\rocketleague\TAGame\CookedPCConsole"
DEFAULT_WORK_DIR = str(USER_DATA_DIR / "work")

@dataclass
class AppSettings:
    rl_source_dir: str = DEFAULT_RL_SOURCE_DIR
    shipped_data_dir: str = str(SHIPPED_DATA_DIR)
    work_dir: str = DEFAULT_WORK_DIR # for decrypted files, used by rl_asset_swapper.py
    runs_dir: str = str(USER_DATA_DIR / "swap_runs")
    db_file: str = str(SWAPS_DB_FILE)
    
    @property
    def db_file_path(self) -> Path:
        return Path(self.db_file)
    
    @property
    def runs_dir_path(self) -> Path:
        return Path(self.runs_dir)

    @property
    def items_path(self) -> Path:
        return Path(self.shipped_data_dir) / "items.json"

    @property
    def keys_path(self) -> Path:
        return Path(self.shipped_data_dir) / "keys.txt"

    @property
    def keys_map_path(self) -> Path:
        return Path(self.shipped_data_dir) / "keys_map.json"

    @property
    def swapper_path(self) -> Path:
        return APP_DIR / "backend" / "engine" / "rl_asset_swapper.py"

    @property
    def work_path(self) -> Path:
        return Path(self.work_dir)


def load_settings() -> AppSettings:
    if USER_SETTINGS_FILE.exists():
        try:
            data = json.loads(USER_SETTINGS_FILE.read_text(encoding="utf-8"))
            return AppSettings(**data)
        except Exception:
            pass
    return AppSettings()


def save_settings(settings: AppSettings) -> None:
    USER_SETTINGS_FILE.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")


def setup_logging() -> None:
    log_file = USER_DATA_DIR / "activity.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_file),
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
