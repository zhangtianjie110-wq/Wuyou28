import json
import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from strategy_lab.page import StrategyExperimentPage
from strategy_lab.models import ExperimentResult
from strategy_lab.storage import StrategyLabStorage

from .helpers import make_candidate, make_records


class _Database:
    def valid_backtest_records(self, source_type):
        assert source_type == "VIP"
        return make_records(80)


def test_page_opens_scans_and_uses_isolated_storage(tmp_path):
    app = QApplication.instance() or QApplication([])
    page = StrategyExperimentPage(
        _Database(), storage=StrategyLabStorage(tmp_path / "strategy_lab.sqlite3")
    )
    result = page.run_scan_sync(limit=2)
    assert page.results.rowCount() == 2
    assert len(result.candidates) == 2
    assert page.start_button.text() == "开始扫描"
    assert page.search_button.text() == "开始搜索"
    assert page.filter_button.text() == "自动筛选"
    assert page.detail_button.text() == "查看详情"
    assert page.save_button.text() == "保存策略"
    assert page.freeze_button.text() == "冻结策略"
    assert page.track_button.text() == "查看变化"
    assert page.compare_button.text() == "比较策略"
    assert page.export_button.text() == "导出报告"
    decisions = page.apply_filter()
    assert len(decisions) == 2
    assert page.filter_table.rowCount() == 2
    assert page.ranking_table.rowCount() == 2
    assert page.result_tabs.tabText(0) == "扫描结果"
    assert page.result_tabs.tabText(1) == "筛选结果"
    assert page.result_tabs.tabText(2) == "排行榜"
    assert page.result_tabs.tabText(3) == "自动搜索"
    assert page.result_tabs.tabText(4) == "冻结策略"
    assert page.result_tabs.tabText(5) == "策略跟踪"
    assert page.result_tabs.tabText(6) == "策略对比"
    page.result_tabs.setCurrentIndex(0)
    page.results.selectRow(0)
    page.save_strategy()
    report = page.write_report(tmp_path / "report.json")
    assert json.loads(report.read_text(encoding="utf-8"))["selection_basis"] == "training_only"
    assert json.loads(report.read_text(encoding="utf-8"))["strategy_lab_version"] == "1.2.0"
    with sqlite3.connect(tmp_path / "strategy_lab.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM saved_strategies").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM strategy_filters").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM strategy_rankings").fetchone()[0] == 2
    search = page.run_search_sync(limit=50)
    assert search.parameter_count == 50
    assert page.search_table.rowCount() == 1
    assert page.result_tabs.currentWidget() is page.search_table

    candidates = (make_candidate("GUI-A"), make_candidate("GUI-B"))
    page._accept_result(
        ExperimentResult(
            experiment_id="GUI-EXPERIMENT",
            data_source="VIP",
            candidates=candidates,
            created_at="2026-09-28T00:00:00+08:00",
        )
    )
    page.apply_filter()
    page.result_tabs.setCurrentIndex(0)
    page.results.selectRow(0)
    assert page.freeze_strategy() is not None
    page.result_tabs.setCurrentIndex(0)
    page.results.selectRow(1)
    assert page.freeze_strategy() is not None
    assert page.freeze_table.rowCount() == 2
    page.freeze_table.selectAll()
    comparison = page.compare_strategies()
    assert comparison is not None
    assert page.compare_table.rowCount() == 2
    page.freeze_table.selectAll()
    tracking = page.track_strategies()
    assert len(tracking) == 2
    assert page.tracking_table.rowCount() == 2
    page.close()
    app.processEvents()
