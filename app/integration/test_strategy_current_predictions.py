from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

from app.integration.gateway import IntegrationGateway
from app.integration.models import IntegrationPaths


ENGINE_ROOT = (
    Path.home()
    / "Documents"
    / "Codex"
    / "2026-09-25"
    / "vip"
    / "research"
    / "vip_formula_engine"
)
STRATEGY_ROOT = ENGINE_ROOT / "StrategyResearchEngine"
if str(STRATEGY_ROOT) not in sys.path:
    sys.path.insert(0, str(STRATEGY_ROOT))

from strategy_research_engine.conditions import strategy_identity
from strategy_research_engine.current_predictions import (
    EXPECTED_ALGORITHM_HASH,
    record_current_predictions,
    settle_strategy_predictions,
)
from strategy_research_engine.storage import connect


class StrategyCurrentRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gateway-strategy-current-")
        self.root = Path(self.temporary.name)
        self.database = self.root / "strategy.sqlite3"
        self.runtime = self.root / "status.json"
        self.runtime.write_text(
            json.dumps(
                {
                    "status": "RUNNING",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        self.rows = []
        connection = connect(self.database)
        try:
            connection.execute(
                """INSERT INTO research_runs VALUES(
                    'run-current','2026-09-26T00:00:00+00:00','2026-09-26T00:01:00+00:00',
                    1,999,100,2,2,0,'dataset','config','COMPLETE')"""
            )
            for condition, predictor in (
                ({"field": "minimum_count", "op": "between", "value": [0, 100]}, "lowest_1"),
                ({"field": "minimum_count", "op": "between", "value": [101, 200]}, "highest_1"),
            ):
                strategy_id, rule_hash = strategy_identity(condition, predictor)
                condition_json = json.dumps(
                    condition,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                connection.execute(
                    """INSERT INTO strategy_results VALUES(
                        ?,?,?,?,?,1,'RESEARCH_ONLY',60,20,20,30,18,12,
                        0.6,0.6,0.6,0.6,4,3,0.6,0.6,0.6,0.0)""",
                    ("run-current", strategy_id, rule_hash, predictor, condition_json),
                )
                connection.execute(
                    "INSERT INTO forward_strategies VALUES(?,?,?,?,?,?,?)",
                    (
                        strategy_id,
                        rule_hash,
                        predictor,
                        condition_json,
                        "2026-09-26T00:01:00+00:00",
                        999,
                        "RESEARCH_ONLY",
                    ),
                )
                self.rows.append((strategy_id, rule_hash))
            connection.commit()
        finally:
            connection.close()

        batch = {
            "issue": "1000",
            "generated_at": "2026-09-27T00:00:00+00:00",
            "source": "VIP100_LOCAL_V2",
            "algorithm_hash": EXPECTED_ALGORITHM_HASH,
            "prediction_count": 100,
            "history_issues": [str(1000 - offset) for offset in range(1, 8)],
            "records": [
                {
                    "algorithm_id": f"A{index:03d}",
                    "local_prediction": index % 28,
                    "source": "VIP100_LOCAL_V2",
                }
                for index in range(100)
            ],
        }
        record_current_predictions(batch, self.database)
        connection = connect(self.database)
        try:
            settle_strategy_predictions(
                connection,
                1000,
                "大单",
                "2026-09-27T00:03:00+00:00",
            )
            connection.commit()
        finally:
            connection.close()

        paths = IntegrationPaths(
            draw_db=self.root / "draw.sqlite3",
            draw_raw_inputs=self.root / "raw",
            vip100_production=self.root / "production",
            vip100_hash_status=self.root / "hash.json",
            strategy_db=self.database,
            strategy_runtime_status=self.runtime,
        )
        self.gateway = IntegrationGateway(paths)

    def tearDown(self):
        self.temporary.cleanup()

    def test_gateway_reads_current_status_and_history_without_writing(self):
        before = self.database.read_bytes()
        strategies = self.gateway.strategies.list_strategies()
        status = self.gateway.strategy_current_status()
        history = self.gateway.strategy_prediction_history(strategies[0].strategy_id)
        after = self.database.read_bytes()

        self.assertEqual(2, len(strategies))
        self.assertEqual({"READY", "NOT_TRIGGERED"}, {row.prediction_status for row in strategies})
        self.assertTrue(all(row.target_issue == "1000" for row in strategies))
        self.assertTrue(all(row.strategy_version.startswith("v1-") for row in strategies))
        self.assertTrue(all(row.rule_hash for row in strategies))
        self.assertEqual(2, status["strategy_total"])
        self.assertEqual(1, status["status_counts"]["READY"])
        self.assertEqual(1, status["status_counts"]["NOT_TRIGGERED"])
        self.assertEqual(1, len(history))
        self.assertEqual("FORWARD", history[0]["source"])
        self.assertIn(history[0]["validation_status"], {"PASS", "FAIL", "NOT_TRIGGERED"})
        self.assertEqual(before, after)

    def test_detail_statistics_filters_and_identity_are_read_only(self):
        strategy_id, rule_hash = self.rows[0]
        connection = connect(self.database)
        try:
            for issue, split, hit in (
                (990, "train", 1),
                (991, "validation", 0),
                (992, "validation", 1),
                (993, "test", 1),
            ):
                connection.execute(
                    "INSERT INTO strategy_triggers VALUES(?,?,?,?,?,?,?)",
                    (
                        "run-current",
                        strategy_id,
                        issue,
                        split,
                        '["大单"]',
                        "大单" if hit else "小双",
                        hit,
                    ),
                )
            version = connection.execute(
                """SELECT strategy_version FROM strategy_rule_versions
                   WHERE strategy_id=?""",
                (strategy_id,),
            ).fetchone()[0]
            connection.execute(
                """INSERT INTO strategy_prediction_history VALUES(
                    999,?,?,?,?,0,NULL,'INVALID_INPUT',?,'RECONSTRUCTED',?,?
                )""",
                (
                    strategy_id,
                    strategy_id,
                    version,
                    rule_hash,
                    "2026-09-26T23:50:00+00:00",
                    "VIP100_LOCAL_V2",
                    "prediction-sha",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        before = self.database.read_bytes()
        detail = self.gateway.strategy_detail(strategy_id, "ALL", 100)
        validation = self.gateway.strategy_detail(strategy_id, "VALIDATION", 100)
        forward = self.gateway.strategy_detail(strategy_id, "FORWARD", 100)
        after = self.database.read_bytes()

        self.assertIsNotNone(detail)
        self.assertEqual(strategy_id, detail.summary.strategy_id)
        self.assertEqual(version, detail.summary.strategy_version)
        self.assertEqual(rule_hash, detail.summary.rule_hash)
        self.assertEqual(30, detail.statistics["valid_samples"])
        self.assertEqual(1, detail.statistics["invalid_samples"])
        self.assertEqual(31, detail.statistics["matched_issues"])
        self.assertEqual(0.75, detail.statistics["recent_30_accuracy"])
        self.assertEqual(0.6, detail.statistics["accuracy"])
        self.assertEqual(1000, detail.latest_trigger["issue"])
        self.assertTrue(json.loads(detail.latest_trigger["prediction"]))
        self.assertEqual("大单", detail.latest_trigger["actual_result"])
        self.assertEqual("PASS", detail.latest_trigger["result_status"])
        self.assertEqual("FORWARD", detail.latest_trigger["sample_type"])
        self.assertEqual(
            {"VALIDATION"},
            {row["sample_type"] for row in validation.history_records},
        )
        self.assertTrue(forward.history_records)
        self.assertEqual(
            {"FORWARD"},
            {row["sample_type"] for row in forward.history_records},
        )
        self.assertNotIn(
            "RECONSTRUCTED",
            {row["sample_type"] for row in forward.history_records},
        )
        self.assertLessEqual(len(detail.history_records), 100)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
