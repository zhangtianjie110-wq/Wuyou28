from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from app.integration.models import IntegrationPaths
from app.integration.gateway import IntegrationGateway
from app.integration.vip100_reconstructed_repository import (
    Vip100ReconstructedRepository,
)
from app.ui.display_text import display_status
from app.ui.vip100_page import Vip100Page
from app.vip100_replay import ReplayStore, build_replay_payload, eligible_issues


HASH = "test-catalog-hash"


def draws(start: int, count: int) -> list[dict]:
    return [
        {
            "issue": str(issue),
            "draw_time": f"2026-09-01 00:{(issue - start) % 60:02d}:00",
            "number": f"{issue % 10}+{(issue + 1) % 10}+{(issue + 2) % 10}="
            f"{issue % 10 + (issue + 1) % 10 + (issue + 2) % 10}",
        }
        for issue in range(start, start + count)
    ]


def catalog() -> list[dict]:
    return [
        {
            "algorithm_id": f"A{index:03d}",
            "algorithm_name": f"算法 {index:03d}",
            "formulaText": f"公式 {index:03d}",
        }
        for index in range(1, 101)
    ]


def calculate(history, algorithms, target_issue, **_kwargs):
    records = []
    for index, row in enumerate(algorithms, 1):
        value = (target_issue + index) % 28
        size = "大" if value >= 14 else "小"
        parity = "双" if value % 2 == 0 else "单"
        records.append(
            {
                "target_issue": str(target_issue),
                "algorithm_id": row["algorithm_id"],
                "algorithm_name": row["algorithm_name"],
                "formulaText": row["formulaText"],
                "local_prediction": value,
                "combination": size + parity,
            }
        )
    return {
        "record_count": 100,
        "catalog_sha256": HASH,
        "engine_version": "测试引擎V2",
        "records": records,
    }


class GatewayStub:
    def __init__(self, repository):
        self.vip100_reconstructed = repository
        self.vip100 = repository

    def health(self):
        return {
            "DRAW_LATEST_ISSUE": "1106",
            "VIP100_STATUS": "RUNNING",
            "VIP100_PREDICTION_COUNT": 100,
            "VIP100_HASH_STATUS": "HASH_OK",
            "STRATEGY_ENGINE_STATUS": "RUNNING",
            "DATA_FRESHNESS": "FRESH",
        }

    def vip100_issues(self, source_type, limit=200):
        return self.vip100_reconstructed.list_issues(limit)

    def vip100_batch(self, source_type, issue):
        return self.vip100_reconstructed.get(issue)


class Vip100ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vip100-replay-")
        self.root = Path(self.temporary.name)
        self.database = self.root / "replay.sqlite3"
        self.store = ReplayStore(self.database)
        self.store.initialize()
        self.draws = draws(1000, 107)
        self.by_issue = {int(row["issue"]): row for row in self.draws}

    def tearDown(self):
        self.temporary.cleanup()

    def payload(self, issue=1007):
        return build_replay_payload(
            issue, self.by_issue, catalog(), HASH, calculate,
            generated_at="2026-09-27T00:00:00+00:00",
        )

    def test_eligible_issues_require_all_seven_prior_draws(self):
        self.assertEqual("1007", eligible_issues(self.draws, 5000)[0])
        self.assertEqual(100, len(eligible_issues(self.draws, 5000)))

    def test_missing_input_is_rejected_before_calculation(self):
        del self.by_issue[1003]
        with self.assertRaisesRegex(ValueError, "missing historical input"):
            self.payload()

    def test_isolated_store_contains_only_reconstructed_rows(self):
        self.assertTrue(
            self.store.write_batch(
                self.payload(), actual_result="1+2+3=6", actual_combination="小双"
            )
        )
        status = self.store.validate(HASH)
        self.assertEqual(1, status.issues)
        self.assertEqual(100, status.predictions)
        self.assertEqual(0, status.missing_predictions)
        self.assertEqual(0, status.duplicate_predictions)
        self.assertEqual(0, status.input_boundary_errors)
        self.assertEqual(0, status.hash_errors)
        self.assertEqual(0, status.forward_contamination)

    def test_idempotency_and_duplicate_protection(self):
        payload = self.payload()
        self.assertTrue(self.store.write_batch(payload, actual_result=None, actual_combination=None))
        self.assertFalse(self.store.write_batch(payload, actual_result=None, actual_combination=None))
        self.assertEqual(100, self.store.validate(HASH).predictions)

    def test_forward_artifact_is_not_opened_or_changed(self):
        forward = self.root / "formal-forward.json"
        forward.write_bytes(b"formal-forward")
        before = forward.read_bytes()
        self.store.write_batch(self.payload(), actual_result=None, actual_combination=None)
        self.assertEqual(before, forward.read_bytes())

    def test_read_repository_preserves_source_and_metadata(self):
        self.store.write_batch(
            self.payload(), actual_result="1+2+3=6", actual_combination="小双"
        )
        repository = Vip100ReconstructedRepository(self.database)
        batch = repository.get("1007")
        self.assertEqual("RECONSTRUCTED", batch.source)
        self.assertEqual("1000", batch.input_start_issue)
        self.assertEqual("1006", batch.input_end_issue)
        self.assertEqual(100, batch.prediction_count)
        self.assertEqual(1, repository.count())

    def test_gateway_keeps_forward_and_reconstructed_sources_separate(self):
        self.store.write_batch(
            self.payload(), actual_result="1+2+3=6", actual_combination="小双"
        )
        missing = self.root / "missing"
        gateway = IntegrationGateway(
            IntegrationPaths(
                draw_db=missing,
                draw_raw_inputs=missing,
                vip100_production=missing,
                vip100_hash_status=missing,
                strategy_db=missing,
                strategy_runtime_status=missing,
                vip100_replay_db=self.database,
            )
        )
        before = self.database.read_bytes()
        self.assertEqual(["1007"], gateway.vip100_issues("RECONSTRUCTED"))
        self.assertEqual("RECONSTRUCTED", gateway.vip100_batch("RECONSTRUCTED", "1007").source)
        self.assertEqual([], gateway.vip100_issues("FORWARD"))
        with self.assertRaises(ValueError):
            gateway.vip100_issues("UNKNOWN")
        self.assertEqual(before, self.database.read_bytes())

    def test_pilot_100_has_exactly_10000_rows(self):
        for issue in eligible_issues(self.draws, 100):
            self.store.write_batch(
                build_replay_payload(issue, self.by_issue, catalog(), HASH, calculate),
                actual_result=None,
                actual_combination=None,
            )
        status = self.store.validate(HASH)
        self.assertEqual(100, status.issues)
        self.assertEqual(10000, status.predictions)
        self.assertEqual(0, status.missing_predictions)

    def test_ui_uses_chinese_source_and_hit_status(self):
        self.store.write_batch(
            self.payload(), actual_result="1+2+3=6", actual_combination="小双"
        )
        page = Vip100Page(GatewayStub(Vip100ReconstructedRepository(self.database)))
        try:
            page.source_selector.setCurrentIndex(1)
            self.application.processEvents()
            texts = " ".join(label.text() for label in page.findChildren(QLabel))
            self.assertIn("历史重建", texts)
            for forbidden in ("RECONSTRUCTED", "FORWARD", "RUNNING", "HASH_OK"):
                self.assertNotIn(forbidden, texts)
        finally:
            page.close()

    def test_display_mapping_keeps_internal_enum_chinese_only_in_ui(self):
        self.assertEqual("历史重建", display_status("RECONSTRUCTED"))
        self.assertEqual("正式前向", display_status("FORWARD"))
        self.assertEqual("正式前向", display_status("VIP100_LOCAL_V2"))


if __name__ == "__main__":
    unittest.main()
