import os
import sys
from pathlib import Path

APP_NAME = "无忧28"

SOURCE_TYPES = ("VIP",)
SOURCE_TOTALS = {"VIP": 100}
COMBINATIONS = ("大单", "大双", "小单", "小双")
COMBINATION_FIELDS = {
    "大单": "big_single",
    "大双": "big_double",
    "小单": "small_single",
    "小双": "small_double",
}
OPPOSITE_COMBINATIONS = {
    "大单": "小双",
    "大双": "小单",
    "小单": "大双",
    "小双": "大单",
}

STRATEGY_METHODS = {
    "买最低一个": "lowest_one",
    "买最低两个": "lowest_two",
    "买最高一个": "highest_one",
    "买最高两个": "highest_two",
    "买最高 + 最低": "highest_lowest",
    "买中间两个": "middle_two",
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _version_manifest_candidates() -> tuple[Path, ...]:
    """Return version manifest locations in packaged-runtime priority order.

    PyInstaller onedir builds place collected data below ``_MEIPASS`` (which
    is the ``_internal`` directory in current builds), while older builds and
    development runs may keep resources beside the executable or project.
    Keeping all supported locations here makes every consumer use the same
    manifest without embedding a release version in Python code.
    """
    if not getattr(sys, "frozen", False):
        return (PROJECT_ROOT / "resources" / "version.json",)

    executable_root = Path(sys.executable).resolve().parent
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = []
    if meipass:
        candidates.append(Path(meipass) / "resources" / "version.json")
    candidates.extend(
        (
            executable_root / "_internal" / "resources" / "version.json",
            executable_root / "resources" / "version.json",
        )
    )
    return tuple(dict.fromkeys(candidates))


def _load_app_version() -> str:
    """Read the shipped UTF-8 version manifest, with a safe fallback."""
    try:
        import json

        for candidate in _version_manifest_candidates():
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError, TypeError):
                continue
            value = str(payload.get("version", "")).strip()
            if value:
                return value
    except (OSError, ValueError, TypeError):
        pass
    return "0.0.0"


APP_VERSION = _load_app_version()

if getattr(sys, "frozen", False):
    # Keep mutable application state outside the installation directory.  The
    # product name is used for the public runtime folder; legacy module names
    # remain untouched for backwards-compatible imports and data migration.
    APP_HOME = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
    DATA_DIR = APP_HOME / "data"
    BACKUP_DIR = APP_HOME / "backup"
    EXPORT_DIR = APP_HOME / "exports"
    CONFIG_DIR = APP_HOME / "config"
    LOG_DIR = APP_HOME / "logs"
    STRATEGIES_DIR = APP_HOME / "strategies"
    RESOURCES_DIR = APP_HOME / "resources"
else:
    APP_HOME = PROJECT_ROOT
    DATA_DIR = PROJECT_ROOT / "data"
    BACKUP_DIR = PROJECT_ROOT / "backups"
    EXPORT_DIR = PROJECT_ROOT / "exports"
    CONFIG_DIR = PROJECT_ROOT / "app" / "ui" / "config"
    LOG_DIR = PROJECT_ROOT / "logs"
    STRATEGIES_DIR = PROJECT_ROOT / "strategies"
    RESOURCES_DIR = PROJECT_ROOT / "resources"
DEFAULT_DB_PATH = DATA_DIR / "le28.db"

DEFAULT_TRAIN_RATIO = 0.7
