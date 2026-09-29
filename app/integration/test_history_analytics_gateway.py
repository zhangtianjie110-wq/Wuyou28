from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.integration.gateway import IntegrationGateway
from app.integration.models import IntegrationPaths


class HistoryAnalyticsGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="history-analytics-gateway-")
        self.root = Path(self.temporary.name)
        self.database = self.root / "draws.sqlite3"
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                """CREATE TABLE yu28_draws(
                    nbr TEXT PRIMARY KEY,
                    draw_time TEXT NOT NULL,
                    number TEXT NOT NULL,
                    combination TEXT NOT NULL,
                    countdown TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )"""
            )
            for index in range(40):
                value = index % 28
                size = "大" if value >= 14 else "小"
                parity = "双" if value % 2 == 0 else "单"
                connection.execute(
                    "INSERT INTO yu28_draws VALUES(?,?,?,?,?,?)",
                    (
                        str(1000 + index),
                        f"2026-09-27 00:{index:02d}:00",
                        f"0+0+{value}={value}",
                        size + parity,
                        "",
                        "2026-09-27T00:00:00+00:00",
                    ),
                )
            connection.commit()
        finally:
            connection.close()
        paths = IntegrationPaths(
            draw_db=self.database,
            draw_raw_inputs=self.root / "raw",
            vip100_production=self.root / "production",
            vip100_hash_status=self.root / "hash.json",
            strategy_db=self.root / "strategy.sqlite3",
            strategy_runtime_status=self.root / "strategy-status.json",
        )
        self.gateway = IntegrationGateway(paths)

    def tearDown(self):
        self.temporary.cleanup()

    def test_gateway_history_queries_are_read_only_and_backend_methods_remain(self):
        before = self.database.read_bytes()
        omission = self.gateway.history_omission("NUMBER", 30)
        hot_cold = self.gateway.history_hot_cold("NUMBER", 1000)
        detail = self.gateway.history_object_detail("NUMBER", "0")
        quality = self.gateway.history_quality("ALL")
        after = self.database.read_bytes()

        self.assertEqual(28, len(omission["records"]))
        self.assertEqual(40, hot_cold["actual_samples"])
        self.assertEqual(10, len(detail["hot_cold"]))
        self.assertEqual(40, quality["valid_records"])
        self.assertEqual(before, after)
        self.assertTrue(callable(self.gateway.draw_by_issue))
        self.assertTrue(callable(self.gateway.keno_20))


if __name__ == "__main__":
    unittest.main()
