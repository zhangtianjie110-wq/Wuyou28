from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
import os

from .constants import BACKUP_DIR


def backup_database(database_path: str | Path, backup_dir: str | Path = BACKUP_DIR) -> Path:
    source = Path(database_path)
    if not source.exists():
        raise FileNotFoundError("数据库文件不存在")
    destination_dir = Path(backup_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = destination_dir / f"wuyou28_backup_{timestamp}.db"
    # SQLite 在线备份 API 能在 WAL 模式下得到一致快照，避免只复制主文件时遗漏事务。
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()
    return destination


def daily_backup(database_path: str | Path, backup_dir: str | Path = BACKUP_DIR) -> Path | None:
    destination_dir = Path(backup_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    today_prefix = f"wuyou28_backup_{date.today().strftime('%Y%m%d')}_"
    if any(path.name.startswith(today_prefix) for path in destination_dir.glob("*.db")):
        return None
    return backup_database(database_path, destination_dir)


def restore_database(
    backup_path: str | Path,
    database_path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Restore a consistent SQLite snapshot without touching the source.

    The default refuses to replace an existing database.  When replacement is
    explicitly enabled, the restored file is written beside the target first
    and atomically moved into place after the SQLite backup completes.
    """

    source = Path(backup_path)
    target = Path(database_path)
    if not source.exists():
        raise FileNotFoundError("备份文件不存在")
    if target.exists() and not overwrite:
        raise FileExistsError("目标数据库已存在；恢复覆盖必须显式设置 overwrite=True")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.restore-{datetime.now().strftime('%Y%m%d%H%M%S%f')}.tmp")
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()
    try:
        os.replace(temporary, target)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return target
