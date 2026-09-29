from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest

from app.database import Database
from app.integration.data_center_repository import DataCenterRepository
from app.yu28 import YU28Draw
from app.yu28_controller import sync_latest_draws


class _Client:
    def __init__(self):
        self.draws = {
            str(issue): YU28Draw(
                str(issue),
                f"2026-09-27 03:{(issue - 100) * 3:02d}:00",
                "1+2+3=6",
                "小双",
                "03:00",
            )
            for issue in range(100, 103)
        }

    def fetch_latest(self):
        return self.draws["102"]

    def fetch_draw_by_issue(self, issue):
        return self.draws[str(issue)]


class YU28ProducerTests(unittest.TestCase):
    def test_sync_catches_up_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "draws.db")
            client = _Client()
            database.save_yu28_draw(client.draws["100"].payload())
            result = sync_latest_draws(database, client)
            self.assertEqual({"latest_issue": "102", "inserted": 2}, result)
            self.assertEqual(3, database.count_yu28_draws())
            self.assertEqual(0, sync_latest_draws(database, client)["inserted"])

    def test_dead_pid_cannot_remain_running(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            path.write_text(
                json.dumps(
                    {
                        "status": "RUNNING",
                        "pid": 2147483647,
                        "updated_at": datetime.now().astimezone().isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            value = DataCenterRepository._service_from_file(
                None, "test", path, stale_after=120
            )
            self.assertEqual("OFFLINE", value["status"])

    def test_live_pid_is_running(self):
        self.assertTrue(DataCenterRepository._pid_running(os.getpid()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            path.write_text(
                json.dumps(
                    {
                        "status": "RUNNING",
                        "pid": os.getpid(),
                        "updated_at": datetime.now().astimezone().isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            running = DataCenterRepository._service_from_file(
                None, "test", path, stale_after=120
            )
            self.assertEqual("RUNNING", running["status"])
            stale_time = datetime.now().astimezone() - timedelta(minutes=5)
            path.write_text(
                json.dumps(
                    {
                        "status": "RUNNING",
                        "pid": os.getpid(),
                        "updated_at": stale_time.isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            stale = DataCenterRepository._service_from_file(
                None, "test", path, stale_after=120
            )
            self.assertEqual("STALE", stale["status"])


if __name__ == "__main__":
    unittest.main()
