import sys
import os
import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict

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

# ---- Read/write data (workspaces for swaps, logs, user config lives in user profile) ----
# TODO #9 move APPDATA path to /PlayForFun/RL_Swapper to avoid namespace clashes
USER_DATA_DIR = Path(os.getenv('LOCALAPPDATA') or Path.home() / "AppData" / "Local") / "RL_UPK_Swapper"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
SWAPS_DB_FILE = USER_DATA_DIR / "swaps.db"
USER_SETTINGS_FILE = USER_DATA_DIR / "app_settings.json"

# -- Default paths (can be overridden by user config) --
DEFAULT_RL_SOURCE_DIR = r"C:\Program Files\Epic Games\rocketleague\TAGame\CookedPCConsole"
DEFAULT_DECRYPTION_WORK_DIR = str(USER_DATA_DIR / "work")

@dataclass
class AppSettings:
    # TODO standardize names (dir vs. file strings/paths) 
    # and only expose Path objects through properties, make strings private
    rl_source_dir: str = DEFAULT_RL_SOURCE_DIR
    shipped_data_dir: str = str(SHIPPED_DATA_DIR)
    decryption_work_dir: str = DEFAULT_DECRYPTION_WORK_DIR # for decrypted files, used by rl_asset_swapper.py
    workspaces_dir: str = str(USER_DATA_DIR / "workspaces")
    legacy_runs_dir: str = str(USER_DATA_DIR / "swap_runs") # TODO remove
    db_file: str = str(SWAPS_DB_FILE)
    
    @property
    def rl_source_dir_path(self) -> Path:
        return Path(self.rl_source_dir)
    
    @property
    def legacy_runs_path(self) -> Path:
        return Path(self.legacy_runs_dir)
    
    @property
    def db_file_path(self) -> Path:
        return Path(self.db_file)
    
    @property
    def workspaces_path(self) -> Path:
        return Path(self.workspaces_dir)

    @property
    def items_path(self) -> Path:
        return Path(self.shipped_data_dir) / "items.json"

    @property
    def keys_path(self) -> Path:
        return Path(self.shipped_data_dir) / "keys.txt"

    @property
    def keys_map_path(self) -> Path:
        return Path(self.shipped_data_dir) / "keys_map.json"

    # Doesn't work anymore since the .py file is no longer included 
    # in the data/ folder which is given to pyinstaller to include as datas
    # @property
    # def swapper_path(self) -> Path:
    #     return APP_DIR / "backend" / "engine" / "rl_asset_swapper.py"

    @property
    def decryption_work_path(self) -> Path:
        return Path(self.decryption_work_dir)


def load_settings() -> AppSettings:
    # TODO maybe not best practice to read and parse it everytime a setting is accessed
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
        format="[%(asctime)s] [%(levelname)s] [%(name)s:%(funcName)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    
    # TODO implement something more like this, with a rotating file handler and console logging handler
    # # Create the root logger
    # logger = logging.getLogger()
    # logger.setLevel(logging.INFO)
    
    # formatter = logging.Formatter(
    #     "[%(asctime)s] [%(levelname)s] [%(name)s:%(funcName)s] %(message)s",
    #     datefmt="%Y-%m-%dT%H:%M:%S"
    # )

    # # 1. The File Handler (Max 5MB per file, keep 3 backups)
    # file_handler = RotatingFileHandler(
    #     log_file, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
    # )
    # file_handler.setFormatter(formatter)
    # logger.addHandler(file_handler)

    # # 2. The Console Handler (For CLI visibility)
    # console_handler = logging.StreamHandler(sys.stdout)
    # console_handler.setFormatter(formatter)
    # logger.addHandler(console_handler) 
