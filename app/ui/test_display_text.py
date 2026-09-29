from __future__ import annotations

import unittest

from app.ui.display_text import STATUS_TEXT, display_message, display_name, display_status


class DisplayTextTests(unittest.TestCase):
    def test_required_statuses_have_chinese_display_text(self):
        required = {
            "RUNNING",
            "STOPPED",
            "ONLINE",
            "OFFLINE",
            "PASS",
            "FAIL",
            "WARNING",
            "PENDING",
            "HASH_OK",
            "HASH_FAIL",
            "FRESH",
            "STALE",
            "UNAVAILABLE",
            "NOT_FOUND",
            "COMPLETE",
            "PARTIAL",
            "MISSING",
            "INVALID_SAMPLE",
            "RESEARCH_ONLY",
            "CANDIDATE",
            "FORWARD_TEST",
            "VERIFIED",
            "REJECTED",
            "LOCAL_V2",
            "FROZEN_VERIFIED",
            "MATCH",
            "MISMATCH",
            "YES",
            "NO",
            "READY",
            "NOT_TRIGGERED",
            "WAITING_DATA",
            "INVALID_INPUT",
            "MISSED_FORWARD",
            "FORWARD",
            "RECONSTRUCTED",
        }
        self.assertTrue(required.issubset(STATUS_TEXT))
        self.assertTrue(all(display_status(value) != value for value in required))

    def test_unknown_values_and_internal_names_are_not_mutated(self):
        self.assertEqual(display_status("VIP100"), "VIP100")
        self.assertEqual(display_status("custom_internal_value"), "custom_internal_value")
        self.assertEqual(display_name("StrategyResearchEngine"), "策略研究引擎")
        self.assertEqual(
            display_message("Strategy DB status OFFLINE"),
            "策略数据库 status 离线",
        )


if __name__ == "__main__":
    unittest.main()
