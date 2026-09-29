from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from PySide6.QtWidgets import QApplication, QLabel, QTabWidget

from app.integration import IntegrationGateway, IntegrationPaths
from app.integration.strategy_state_similarity_repository import StrategyStateSimilarityRepository
from app.ui.display_text import display_status
from app.ui.strategy_research_page import StrategyResearchPage
from strategy_research_engine.state_similarity_v3 import SCHEMA


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fixture(database: Path) -> None:
    metrics = {
        "targets": 4500, "triggers": 4200, "hits": 2268, "misses": 1932,
        "accuracy": 0.54, "ci_low": 0.525, "ci_high": 0.555,
        "max_consecutive_hits": 9, "max_consecutive_misses": 10,
        "average_trigger_interval": 1.07,
    }
    recent = {str(value): {**metrics, "targets": value, "triggers": value} for value in (30, 50, 100, 200, 500)}
    definition = {
        "representation": "RAW_DISTRIBUTION", "distance_method": "EUCLIDEAN",
        "k_value": 50, "time_decay": "EQUAL", "min_similar_samples": 30,
        "distance_percentile": 0.95, "recency_scale": 500.0,
    }
    best = {
        "method_id": "SSV3_fixture", "method_version": "v3-rulehash", "rule_hash": "rulehash",
        "definition": definition, "distance_threshold": 0.1,
        "train": metrics, "validation": metrics, "test": metrics, "strict": metrics,
        "recent": recent, "recent_state": "BASICALLY_STABLE",
        "segments": {"count": 18, "minimum_accuracy": 0.5, "maximum_accuracy": 0.58, "median_accuracy": 0.54},
        "gains": {"fixed": 0.01, "v1": 0.0, "v2": 0.0}, "clear_improvement": False,
    }
    features = {
        "counts": {"大单": 20, "大双": 24, "小单": 26, "小双": 30},
        "r1": "大单", "r2": "大双", "r3": "小单", "r4": "小双",
        "r1_count": 20, "r2_count": 24, "r3_count": 26, "r4_count": 30,
        "spread": 10, "concentration": 0.2552,
    }
    pair_stats = {
        pair: {"samples": 50, "hits": 27, "misses": 23, "accuracy": 0.54, "ci_low": 0.403, "ci_high": 0.671}
        for pair in ("大单+大双", "大单+小单", "大单+小双", "大双+小单", "大双+小双", "小单+小双")
    }
    connection = sqlite3.connect(database)
    try:
        connection.executescript(SCHEMA)
        connection.execute("CREATE TABLE large_sample_runs(marker TEXT)")
        connection.execute("CREATE TABLE dynamic_v2_runs(marker TEXT)")
        connection.execute("INSERT INTO large_sample_runs VALUES('V1_UNCHANGED')")
        connection.execute("INSERT INTO dynamic_v2_runs VALUES('V2_UNCHANGED')")
        connection.execute(
            "INSERT INTO state_v3_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "SSV3_TEST", "strategy-state-similarity-v3", "RECONSTRUCTED", "dataset",
                5000, 500, 4500, 3481908, 3485407, 3485408, 3486157, 3486158, 3486907,
                40, 32, 5, 5, 0, "SSV3_fixture", "WEAK", _json(best), _json({}), _json({}),
                "2026-09-27T00:00:00+00:00", "2026-09-27T00:01:00+00:00", "COMPLETE",
            ),
        )
        connection.execute(
            "INSERT INTO state_v3_methods VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "SSV3_TEST", "SSV3_fixture", "v3-rulehash", "rulehash",
                "RAW_DISTRIBUTION", "EUCLIDEAN", 50, "EQUAL", 30, 0.1,
                _json(metrics), _json(metrics), _json(metrics), _json(metrics), _json(recent),
                "TESTED", "OBSERVATION", "2026-09-27T00:01:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO state_v3_replay VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "SSV3_TEST", "SSV3_fixture", 3486907, "TEST", "RECONSTRUCTED", 4999,
                3486906, 50, 0.03, 0.08, _json(["大单", "大双"]), "大单", 1, 1,
            ),
        )
        connection.execute(
            "INSERT INTO state_v3_segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("SSV3_TEST", "SSV3_fixture", 1, 3482408, 3482657, 240, 130, 110, 0.5417, 0.478, 0.604, 8),
        )
        connection.execute(
            "INSERT INTO state_v3_current_state VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "SSV3_TEST", 3487000, "hash", 100, "2026-09-27T00:00:00+08:00",
                _json(features), "HISTORICALLY_SIMILAR", 50, 0.03, 0.08,
                _json(["大单", "大双"]), _json(pair_stats), "BASICALLY_STABLE",
            ),
        )
        connection.execute(
            "INSERT INTO state_v3_current_neighbors VALUES(?,?,?,?,?,?,?,?)",
            (
                "SSV3_TEST", 1, 3486800, 0.01, 0.9901,
                _json({"大单": 20, "大双": 24, "小单": 26, "小双": 30}),
                "大单", _json(["大单+大双", "大单+小单", "大单+小双"]),
            ),
        )
        connection.commit()
    finally:
        connection.close()


class FakeStateGateway:
    def __init__(self, repository):
        self.repository = repository
        self.state_reads = 0

    def strategy_status(self):
        return {
            "status": "RUNNING", "database_status": "ONLINE", "latest_research_at": None,
            "production_periods": 0, "candidate_strategies": 0,
            "forward_test_strategies": 0, "verified_strategies": 0,
            "freshness": {"status": "FRESH"},
        }

    def strategy_state_similarity_status(self):
        return self.repository.status()

    def strategy_state_similarity_list(self, limit=20):
        self.state_reads += 1
        return self.repository.list_methods(limit)

    def strategy_state_similarity_current(self):
        return self.repository.current()

    def strategy_state_similarity_replay(self, method_id=None, limit=100):
        return self.repository.replay(method_id, limit)

    def strategy_state_similarity_segments(self, method_id=None):
        return self.repository.segments(method_id)

    def strategy_dynamic_pair_status(self):
        return {"available": False}

    def strategy_large_sample_status(self):
        return {"available": False}


class StateSimilarityFormalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.temporary = tempfile.TemporaryDirectory(prefix="state-v3-ui-")
        cls.database = Path(cls.temporary.name) / "strategy.sqlite3"
        _fixture(cls.database)
        cls.repository = StrategyStateSimilarityRepository(cls.database)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_gateway_reads_state_v3_without_writing(self):
        missing = Path(self.temporary.name) / "missing"
        gateway = IntegrationGateway(IntegrationPaths(missing, missing, missing, missing, self.database, missing, missing))
        before = self.database.read_bytes()
        self.assertTrue(gateway.strategy_state_similarity_status()["available"])
        self.assertEqual(1, len(gateway.strategy_state_similarity_list()))
        self.assertEqual(3487000, gateway.strategy_state_similarity_current()["target_issue"])
        self.assertEqual(1, len(gateway.strategy_state_similarity_replay()))
        self.assertEqual(before, self.database.read_bytes())

    def test_replay_is_reconstructed_and_strictly_historical(self):
        replay = self.repository.replay()
        self.assertEqual({"RECONSTRUCTED"}, {row["source_type"] for row in replay})
        self.assertTrue(all(row["historical_max_issue"] < row["target_issue"] for row in replay))
        self.assertEqual({"TEST"}, {row["dataset_split"] for row in replay})

    def test_v1_v2_markers_remain_unchanged(self):
        connection = sqlite3.connect(self.database)
        try:
            before = (
                connection.execute("SELECT marker FROM large_sample_runs").fetchall(),
                connection.execute("SELECT marker FROM dynamic_v2_runs").fetchall(),
            )
        finally:
            connection.close()
        self.repository.status(); self.repository.current(); self.repository.replay()
        connection = sqlite3.connect(self.database)
        try:
            after = (
                connection.execute("SELECT marker FROM large_sample_runs").fetchall(),
                connection.execute("SELECT marker FROM dynamic_v2_runs").fetchall(),
            )
        finally:
            connection.close()
        self.assertEqual(before, after)

    def test_state_v3_ui_is_chinese_and_complete(self):
        gateway = FakeStateGateway(self.repository)
        page = StrategyResearchPage(gateway)
        try:
            self.assertTrue(page.state_similarity_mode)
            self.assertEqual("当前状态与相似状态 v3", page.research_type.currentText())
            self.assertEqual(["相似状态", "近期状态", "历史回放"], [page.state_v3_tabs.tabText(i) for i in range(page.state_v3_tabs.count())])
            self.assertEqual(6, page.current_pair_table.rowCount())
            self.assertEqual(1, page.neighbor_table.rowCount())
            self.assertEqual(1, page.replay_table.rowCount())
            self.assertEqual("观察中", page.table.item(0, 10).text())
            visible = " ".join(widget.text() for widget in page.findChildren(QLabel) if not widget.isHidden())
            visible += " " + " ".join(page.state_v3_tabs.tabText(i) for i in range(page.state_v3_tabs.count()))
            for token in ("SIMILAR", "REPLAY", "TRAIN", "VALIDATION", "TEST", "OBSERVATION", "WEAK"):
                self.assertNotIn(token, visible)
            self.assertGreater(gateway.state_reads, 0)
        finally:
            page.close()

    def test_chinese_mapping_covers_v3_enums(self):
        self.assertEqual("欧氏距离", display_status("EUCLIDEAN"))
        self.assertEqual("近期增强", display_status("RECENT_STRENGTHENING"))
        self.assertEqual("较弱", display_status("WEAK"))
        self.assertEqual("观察中", display_status("OBSERVATION"))

    def test_ui_has_no_direct_database_or_engine_write_path(self):
        source = (Path(__file__).resolve().parents[1] / "app" / "ui" / "strategy_research_page.py").read_text(encoding="utf-8")
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("strategy_research_engine", source)
        self.assertNotIn("INSERT INTO", source)
        self.assertIn("strategy_state_similarity_current", source)
        self.assertNotIn("下注", source)


if __name__ == "__main__":
    unittest.main()
