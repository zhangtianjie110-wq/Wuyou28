from __future__ import annotations

from pathlib import Path
import re
import unittest

from app.integration import IntegrationGateway, IntegrationPaths
from app.integration.health import readonly_sqlite


HASH = "ceac161e70735b8319be5f1b5748db520a3c86a86842f54b1550bf82f921b067"


class IntegrationGatewayContractTests(unittest.TestCase):
    def setUp(self):
        self.gateway = IntegrationGateway()

    def test_reads_latest_official_draw(self):
        draw = self.gateway.draws.latest()
        self.assertIsNotNone(draw)
        self.assertTrue(draw.issue.isdigit())
        self.assertRegex(draw.number, r"^\d+\+\d+\+\d+=\d+$")
        self.assertIn(draw.source, {"YU28_DATABASE", "YU28_RAW_SNAPSHOT"})
        self.assertEqual(draw, self.gateway.draws.get(draw.issue))
        self.assertGreaterEqual(len(self.gateway.draws.recent(7)), 7)

    def test_reads_exactly_100_local_predictions_and_hash(self):
        batch = self.gateway.vip100.latest()
        self.assertIsNotNone(batch)
        self.assertEqual(100, batch.prediction_count)
        self.assertEqual(100, len({row.algorithm_id for row in batch.predictions}))
        self.assertTrue(all(row.formula for row in batch.predictions))
        self.assertTrue(
            all(
                row.combination in {"大单", "大双", "小单", "小双"}
                for row in batch.predictions
            )
        )
        self.assertEqual(HASH, batch.algorithm_hash)
        self.assertTrue(batch.history_hash)
        self.assertTrue(batch.input_hash)
        self.assertEqual("HASH_OK", self.gateway.vip100.hash_status()["status"])

    def test_reads_strategy_database_metrics_and_details(self):
        status = self.gateway.strategies.status()
        self.assertEqual("ONLINE", status["database_status"])
        candidates = self.gateway.strategies.list_candidates(10)
        self.assertTrue(candidates)
        self.assertIn(
            candidates[0].status,
            {"RESEARCH_ONLY", "CANDIDATE", "FORWARD_TEST", "VERIFIED"},
        )
        detail = self.gateway.strategies.get(candidates[0].strategy_id)
        self.assertIsNotNone(detail)
        self.assertEqual(candidates[0].strategy_id, detail.summary.strategy_id)
        self.assertGreaterEqual(detail.summary.trigger_count, 0)
        self.assertGreaterEqual(detail.summary.max_consecutive_misses, 0)
        self.gateway.strategies.list_rejected(3)

    def test_gateway_health_contract(self):
        health = self.gateway.health()
        required = {
            "DRAW_SOURCE_STATUS",
            "DRAW_LATEST_ISSUE",
            "VIP100_STATUS",
            "VIP100_LATEST_ISSUE",
            "VIP100_PREDICTION_COUNT",
            "VIP100_HASH_STATUS",
            "STRATEGY_ENGINE_STATUS",
            "STRATEGY_DB_STATUS",
            "DATA_FRESHNESS",
        }
        self.assertTrue(required.issubset(health))
        self.assertEqual(100, health["VIP100_PREDICTION_COUNT"])
        self.assertEqual("HASH_OK", health["VIP100_HASH_STATUS"])
        self.assertEqual("ONLINE", health["STRATEGY_DB_STATUS"])

    def test_sqlite_connections_are_query_only_and_make_no_changes(self):
        with readonly_sqlite(self.gateway.paths.strategy_db) as connection:
            self.assertEqual(1, connection.execute("PRAGMA query_only").fetchone()[0])
            before = connection.total_changes
            connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            self.assertEqual(before, connection.total_changes)

    def test_repository_sources_contain_no_write_sql(self):
        integration_dir = Path(__file__).resolve().parents[1] / "app" / "integration"
        mutation = re.compile(r"\b(?:INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b")
        for path in integration_dir.glob("*.py"):
            if path.name.startswith("test_"):
                continue
            with self.subTest(path=path.name):
                self.assertIsNone(mutation.search(path.read_text(encoding="utf-8")))

    def test_missing_backends_return_offline_without_crashing(self):
        missing = Path(__file__).resolve().parent / "does-not-exist"
        paths = IntegrationPaths(missing, missing, missing, missing, missing, missing)
        gateway = IntegrationGateway(paths)
        health = gateway.health()
        self.assertEqual("OFFLINE", health["DRAW_SOURCE_STATUS"])
        self.assertEqual("OFFLINE", health["VIP100_STATUS"])
        self.assertEqual("OFFLINE", health["STRATEGY_ENGINE_STATUS"])
        data_center = gateway.data_center.snapshot()
        self.assertEqual("OFFLINE", data_center["top"]["draw_status"])
        self.assertEqual("OFFLINE", data_center["top"]["vip100_status"])
        self.assertEqual("OFFLINE", data_center["top"]["strategy_status"])

    def test_gateway_has_no_service_control_surface(self):
        forbidden = {"start", "stop", "restart", "run", "run_loop", "spawn"}
        self.assertTrue(forbidden.isdisjoint(dir(self.gateway)))
        self.assertTrue(forbidden.isdisjoint(dir(self.gateway.draws)))
        self.assertTrue(forbidden.isdisjoint(dir(self.gateway.vip100)))
        self.assertTrue(forbidden.isdisjoint(dir(self.gateway.strategies)))
        self.assertTrue(forbidden.isdisjoint(dir(self.gateway.data_center)))

    def test_vip100_status_is_independent(self):
        status = self.gateway.vip100.status()
        self.assertEqual(100, self.gateway.vip100.latest().prediction_count)

    def test_data_center_matches_official_sources(self):
        snapshot = self.gateway.data_center.snapshot()
        self.assertEqual(
            snapshot["counts"]["vip100_periods"] * 100,
            snapshot["counts"]["vip100_prediction_rows"],
        )
        self.assertEqual(
            snapshot["counts"]["strategy_total"],
            sum(
                snapshot["counts"][status]
                for status in (
                    "RESEARCH_ONLY",
                    "CANDIDATE",
                    "FORWARD_TEST",
                    "VERIFIED",
                    "REJECTED",
                )
            ),
        )
        self.assertTrue(snapshot["recent"])
        self.assertEqual(5, len(snapshot["services"]))


if __name__ == "__main__":
    unittest.main()
