from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import time

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from .secure_store import load_yu28_api_key, save_yu28_api_key
from .yu28 import YU28Client


class _Signals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, function: Callable[[], object]):
        super().__init__()
        self.function = function
        self.signals = _Signals()

    def run(self) -> None:
        try:
            self.signals.finished.emit(self.function())
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class YU28Controller(QObject):
    status_changed = Signal(str, str)
    latest_changed = Signal(object)
    new_draw = Signal(object)

    def __init__(self, database, parent=None, poll_seconds: int = 30):
        super().__init__(parent)
        self.database = database
        self.thread_pool = QThreadPool.globalInstance()
        self.timer = QTimer(self)
        self.timer.setInterval(max(10, int(poll_seconds)) * 1000)
        self.timer.timeout.connect(self.refresh)
        self.busy = False
        self.last_status = "未配置"
        self.last_state = "muted"
        self.latest = self.database.latest_yu28_draw()

    def has_api_key(self) -> bool:
        try:
            return bool(load_yu28_api_key())
        except Exception:
            return False

    def save_api_key(self, value: str) -> None:
        save_yu28_api_key(value)

    def start(self) -> None:
        if self.latest:
            self.latest_changed.emit(self.latest)
        if not self.has_api_key():
            self._set_status("YU28 未配置", "muted")
            return
        self.timer.start()
        self.refresh()

    def stop(self) -> None:
        self.timer.stop()

    def test_connection(self) -> bool:
        if not self.has_api_key():
            self._set_status("YU28 未配置 API Key", "error")
            return False
        if not self.timer.isActive():
            self.timer.start()
        return self.refresh()

    def refresh(self) -> bool:
        if self.busy:
            return False
        try:
            api_key = load_yu28_api_key()
        except Exception as exc:
            self._set_status(f"YU28 连接失败：{exc}", "error")
            return False
        if not api_key:
            self._set_status("YU28 未配置", "muted")
            return False
        self.busy = True
        self._set_status("正在连接 YU28……", "working")

        def fetch_and_store():
            draw = YU28Client(api_key, timeout=15).fetch_latest()
            payload = draw.payload()
            inserted = self.database.save_yu28_draw(payload)
            updated = self.database.update_result_by_issue(draw.nbr, draw.result)
            return {"draw": payload, "inserted": inserted, "updated": updated}

        task = _Task(fetch_and_store)
        task.signals.finished.connect(self._done)
        task.signals.failed.connect(self._failed)
        self.thread_pool.start(task)
        return True

    def _done(self, result: dict) -> None:
        self.busy = False
        self.latest = result["draw"]
        self._set_status("YU28 已连接", "success")
        self.latest_changed.emit(self.latest)
        if result["inserted"]:
            self.new_draw.emit({**result["draw"], "updated_predictions": result["updated"]})

    def _failed(self, message: str) -> None:
        self.busy = False
        # Keep polling after transient failures. Existing data is untouched.
        self._set_status(f"YU28 连接失败：{message}", "error")

    def _set_status(self, message: str, state: str) -> None:
        self.last_status = message
        self.last_state = state
        self.status_changed.emit(message, state)


def _write_service_status(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sync_latest_draws(database, client: YU28Client) -> dict:
    """Catch the official database up to the latest completed YU28 issue."""
    latest = client.fetch_latest()
    latest_issue = int(latest.nbr)
    local = database.latest_yu28_draw()
    first_issue = latest_issue if local is None else int(local["nbr"]) + 1
    if first_issue > latest_issue:
        return {"latest_issue": str(latest_issue), "inserted": 0}
    if latest_issue - first_issue > 5000:
        raise RuntimeError("YU28 producer refuses an automatic gap larger than 5000 issues")

    inserted = 0
    for issue in range(first_issue, latest_issue + 1):
        draw = latest if issue == latest_issue else client.fetch_draw_by_issue(issue)
        payload = draw.payload()
        existing = database.find_yu28_draw(str(issue))
        if existing is not None:
            fields = ("nbr", "time", "number", "combination")
            if any(str(existing[field]) != str(payload[field]) for field in fields):
                raise RuntimeError(f"YU28 draw conflict at issue {issue}")
            continue
        if database.save_yu28_draw(payload):
            inserted += 1
        database.update_result_by_issue(draw.nbr, draw.result)
    return {"latest_issue": str(latest_issue), "inserted": inserted}


def run_headless_producer(database_path: Path, poll_seconds: int = 10) -> None:
    import msvcrt

    from .database import Database

    database_path = Path(database_path).resolve()
    status_path = database_path.with_name("yu28_producer_status.json")
    lock_path = database_path.with_name("yu28_producer.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open("a+b")
    if lock.tell() == 0:
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        lock.close()
        raise RuntimeError("YU28 producer is already running") from exc

    database = Database(database_path)
    client = YU28Client(load_yu28_api_key(), timeout=15)
    try:
        while True:
            try:
                result = sync_latest_draws(database, client)
                _write_service_status(
                    status_path,
                    {
                        "status": "RUNNING",
                        "pid": os.getpid(),
                        "updated_at": datetime.now().astimezone().isoformat(),
                        "latest_issue": result["latest_issue"],
                        "last_inserted": result["inserted"],
                        "database": str(database_path),
                    },
                )
            except Exception as exc:
                _write_service_status(
                    status_path,
                    {
                        "status": "ERROR",
                        "pid": os.getpid(),
                        "updated_at": datetime.now().astimezone().isoformat(),
                        "error": f"{type(exc).__name__}: {exc}",
                        "database": str(database_path),
                    },
                )
            time.sleep(max(5, int(poll_seconds)))
    finally:
        _write_service_status(
            status_path,
            {
                "status": "STOPPED",
                "pid": os.getpid(),
                "updated_at": datetime.now().astimezone().isoformat(),
                "database": str(database_path),
            },
        )
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


def main() -> int:
    from .database import Database
    from .integration.models import IntegrationPaths

    parser = argparse.ArgumentParser(prog="YU28Producer")
    parser.add_argument("command", choices=("run-once", "run-loop", "status"))
    parser.add_argument("--database", type=Path)
    parser.add_argument("--poll-seconds", type=int, default=10)
    args = parser.parse_args()
    database_path = (args.database or IntegrationPaths.from_environment().draw_db).resolve()
    status_path = database_path.with_name("yu28_producer_status.json")
    if args.command == "run-loop":
        run_headless_producer(database_path, args.poll_seconds)
    elif args.command == "status":
        print(status_path.read_text(encoding="utf-8") if status_path.exists() else "{}")
    else:
        result = sync_latest_draws(
            Database(database_path), YU28Client(load_yu28_api_key(), timeout=15)
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
