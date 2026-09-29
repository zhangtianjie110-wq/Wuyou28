"""Runtime preparation and diagnostics for packaged desktop deployments.

This module owns only deployment concerns: creating per-user directories,
configuring file logging, and resolving read-only bundled resources.  It does
not import database, collection, or strategy code.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

from .constants import (
    APP_HOME,
    CONFIG_DIR,
    DATA_DIR,
    LOG_DIR,
    RESOURCES_DIR,
    STRATEGIES_DIR,
    BACKUP_DIR,
)

RUNTIME_DIRS = (
    DATA_DIR,
    CONFIG_DIR,
    LOG_DIR,
    BACKUP_DIR,
    STRATEGIES_DIR,
    RESOURCES_DIR,
)


def prepare_runtime() -> dict[str, Path]:
    """Create mutable runtime directories and return their paths.

    The function is intentionally idempotent and never writes to the folder
    containing the executable in frozen mode.
    """
    for path in RUNTIME_DIRS:
        path.mkdir(parents=True, exist_ok=True)
    return {
        "app_home": APP_HOME,
        "data": DATA_DIR,
        "config": CONFIG_DIR,
        "logs": LOG_DIR,
        "backup": BACKUP_DIR,
        "strategies": STRATEGIES_DIR,
        "resources": RESOURCES_DIR,
    }


def configure_logging() -> Path:
    """Configure a rotating application log in the user runtime directory."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "wuyou28.log"
    root = logging.getLogger()
    if not any(getattr(handler, "_wuyou28", False) for handler in root.handlers):
        handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler._wuyou28 = True  # type: ignore[attr-defined]
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    if not getattr(sys, "_wuyou28_excepthook", False):
        previous_hook = sys.excepthook

        def _log_uncaught(exc_type, exc_value, exc_traceback):
            logging.getLogger("wuyou28").error(
                "运行异常",
                exc_info=(exc_type, exc_value, exc_traceback),
            )
            previous_hook(exc_type, exc_value, exc_traceback)

        sys.excepthook = _log_uncaught
        sys._wuyou28_excepthook = True
    return log_path


def resource_path(name: str) -> Path:
    """Resolve a bundled read-only resource for source and frozen runs."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "resources" / name
    return Path(__file__).resolve().parent.parent / "resources" / name


def log_startup_failure(exc: BaseException) -> None:
    """Record a startup failure even when the Qt application cannot start."""
    try:
        configure_logging()
        logging.getLogger(__name__).error(
            "启动失败: %s\n%s",
            exc,
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )
    except Exception:
        # Last-resort diagnostics must never mask the original startup error.
        pass
