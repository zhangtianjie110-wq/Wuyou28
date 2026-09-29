from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.database import Database
from app.ui.widgets import PageHeader, polish_table, secondary_button

from . import __version__
from .conditions import StrategyConditionGenerator
from .engine import StrategyLabEngine
from .filter import FilterDecision, StrategyFilterEngine
from .freeze import FrozenStrategy, StrategyFreezeService
from .models import CandidateResult, ExperimentResult
from .ranking import RankingEntry, StrategyRanking
from .search import SearchConfig, SearchResult, StrategySearchEngine
from .storage import StrategyLabStorage
from .tracker import StrategyTracker, TrackingResult
from .compare import ComparisonResult, StrategyComparator
from .v2 import V2ExperimentRunner, ValidationConfig
from .v2.snapshot import SnapshotBuilder
from .v2.experiment_audit import ExperimentAuditStore


class _ScanWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, records: list[dict[str, Any]], source: str):
        super().__init__()
        self.records = records
        self.source = source

    @Slot()
    def run(self) -> None:
        try:
            conditions = StrategyConditionGenerator().generate()
            result = StrategyLabEngine().scan(
                self.records,
                conditions,
                data_source=self.source,
                progress=self.progress.emit,
            )
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class _SearchWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        records: list[dict[str, Any]],
        storage: StrategyLabStorage,
        config: SearchConfig,
    ):
        super().__init__()
        self.records = records
        self.storage = storage
        self.config = config

    @Slot()
    def run(self) -> None:
        try:
            result = StrategySearchEngine(self.storage).search(
                self.records, config=self.config
            )
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class StrategyExperimentPage(QWidget):
    """Strategy Lab v2.1 page backed by the isolated lab package."""

    data_changed = Signal()

    def __init__(
        self,
        database: Database,
        parent=None,
        *,
        storage: StrategyLabStorage | None = None,
    ):
        super().__init__(parent)
        self.database = database
        self.storage = storage or StrategyLabStorage()
        self.experiment: ExperimentResult | None = None
        self.filter_engine = StrategyFilterEngine()
        self.ranking_engine = StrategyRanking(filter_config=self.filter_engine.config)
        self.filter_decisions: tuple[FilterDecision, ...] = ()
        self.ranking_entries: tuple[RankingEntry, ...] = ()
        self.search_result: SearchResult | None = None
        self.freeze_service = StrategyFreezeService(self.storage)
        self.tracker = StrategyTracker(self.storage)
        self.comparator = StrategyComparator(self.storage)
        self.frozen_strategies: tuple[FrozenStrategy, ...] = ()
        self.tracking_results: tuple[TrackingResult, ...] = ()
        self.comparison_result: ComparisonResult | None = None
        self.v21_result = None
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 12)
        root.setSpacing(10)
        root.addWidget(PageHeader("策略实验室", "自动发现条件，训练集筛选，验证集独立检验"))

        controls = QFrame()
        controls.setObjectName("Card")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(12, 10, 12, 10)
        controls_layout.setSpacing(6)
        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_row.addWidget(QLabel("数据源"))
        self.source = QComboBox()
        self.source.addItem("VIP100", "VIP")
        self.source.addItem("智能选法数据", "VIP")
        source_row.addWidget(self.source)
        self.sample_label = QLabel("可用样本 0")
        self.sample_label.setObjectName("Muted")
        source_row.addWidget(self.sample_label)
        source_row.addWidget(QLabel("搜索数量"))
        self.search_limit = QComboBox()
        for value in (50, 100, 200):
            self.search_limit.addItem(str(value), value)
        self.search_limit.setCurrentText("100")
        source_row.addWidget(self.search_limit)
        source_row.addWidget(QLabel("实验类型"))
        self.experiment_mode = QComboBox()
        self.experiment_mode.addItem("基础回测 v1", "v1")
        self.experiment_mode.addItem("可复现实验 v2", "v2")
        self.experiment_mode.addItem("稳定性实验 v2.1", "v21")
        self.experiment_mode.setCurrentIndex(2)
        source_row.addWidget(self.experiment_mode)
        source_row.addWidget(QLabel("数据范围"))
        self.data_range = QComboBox()
        self.data_range.addItem("全部", None)
        self.data_range.addItem("最近1000", 1000)
        self.data_range.addItem("最近5000", 5000)
        self.data_range.addItem("自定义期号", "custom")
        source_row.addWidget(self.data_range)
        self.custom_start = QLineEdit()
        self.custom_start.setPlaceholderText("起始期号")
        self.custom_start.setMaximumWidth(110)
        self.custom_end = QLineEdit()
        self.custom_end.setPlaceholderText("结束期号")
        self.custom_end.setMaximumWidth(110)
        self.custom_start.setVisible(False)
        self.custom_end.setVisible(False)
        source_row.addWidget(self.custom_start)
        source_row.addWidget(self.custom_end)
        source_row.addStretch()
        controls_layout.addLayout(source_row)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.start_button = QPushButton("开始扫描")
        self.start_button.setObjectName("PrimaryAction")
        self.start_button.clicked.connect(self.start_scan)
        action_row.addWidget(self.start_button)
        self.search_button = QPushButton("开始搜索")
        self.search_button.setObjectName("PrimaryAction")
        self.search_button.clicked.connect(self.start_search)
        action_row.addWidget(self.search_button)
        self.v21_button = QPushButton("开始实验")
        self.v21_button.setObjectName("PrimaryAction")
        self.v21_button.clicked.connect(self.run_v21)
        action_row.addWidget(self.v21_button)
        self.filter_button = QPushButton("自动筛选")
        secondary_button(self.filter_button)
        self.filter_button.clicked.connect(self.apply_filter)
        action_row.addWidget(self.filter_button)
        self.detail_button = QPushButton("查看详情")
        secondary_button(self.detail_button)
        self.detail_button.clicked.connect(self.show_details)
        action_row.addWidget(self.detail_button)
        self.save_button = QPushButton("保存策略")
        secondary_button(self.save_button)
        self.save_button.clicked.connect(self.save_strategy)
        action_row.addWidget(self.save_button)
        self.freeze_button = QPushButton("冻结策略")
        secondary_button(self.freeze_button)
        self.freeze_button.clicked.connect(self.freeze_strategy)
        action_row.addWidget(self.freeze_button)
        self.track_button = QPushButton("查看变化")
        secondary_button(self.track_button)
        self.track_button.clicked.connect(self.track_strategies)
        action_row.addWidget(self.track_button)
        self.compare_button = QPushButton("比较策略")
        secondary_button(self.compare_button)
        self.compare_button.clicked.connect(self.compare_strategies)
        action_row.addWidget(self.compare_button)
        self.export_button = QPushButton("导出报告")
        secondary_button(self.export_button)
        self.export_button.clicked.connect(self.export_report)
        action_row.addWidget(self.export_button)
        action_row.addStretch()
        controls_layout.addLayout(action_row)
        self.validation_plan = QLabel("v2.1 固定验证：训练 70% / 验证 20% / 最终测试 10%")
        self.validation_plan.setObjectName("Muted")
        controls_layout.addWidget(self.validation_plan)
        self.v21_snapshot_label = QLabel("Snapshot: — | 数据 SHA256: — | 算法版本: — | 引擎版本: —")
        self.v21_snapshot_label.setObjectName("Muted")
        self.v21_snapshot_label.setWordWrap(True)
        controls_layout.addWidget(self.v21_snapshot_label)
        root.addWidget(controls)

        self.notice = QLabel("等待扫描或搜索，自动搜索支持 50 / 100 / 200 个候选条件")
        self.notice.setObjectName("Muted")
        root.addWidget(self.notice)

        self.result_tabs = QTabWidget()
        self.results = QTableWidget(0, 6)
        self.results.setHorizontalHeaderLabels(
            ("策略", "触发次数", "训练命中率", "验证命中率", "最近表现", "状态")
        )
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results.setSelectionBehavior(QTableWidget.SelectRows)
        self.results.setSelectionMode(QTableWidget.SingleSelection)
        self.results.verticalHeader().setVisible(False)
        self.results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        polish_table(self.results, 440)

        self.filter_table = QTableWidget(0, 4)
        self.filter_table.setHorizontalHeaderLabels(
            ("策略", "筛选结果", "淘汰原因", "Walk Forward通过率")
        )
        self._prepare_table(self.filter_table)

        self.ranking_table = QTableWidget(0, 8)
        self.ranking_table.setHorizontalHeaderLabels(
            (
                "策略",
                "条件参数",
                "触发次数",
                "训练/验证",
                "最近30/50/100",
                "最大连中/连错",
                "平均间隔",
                "状态",
            )
        )
        self._prepare_table(self.ranking_table)

        self.search_table = QTableWidget(0, 5)
        self.search_table.setHorizontalHeaderLabels(
            ("搜索编号", "参数组合", "缓存命中", "实际计算", "运行时间")
        )
        self._prepare_table(self.search_table)

        self.freeze_table = QTableWidget(0, 4)
        self.freeze_table.setHorizontalHeaderLabels(
            ("策略名称", "版本", "状态", "创建时间")
        )
        self._prepare_table(self.freeze_table)
        self.freeze_table.setSelectionMode(QTableWidget.ExtendedSelection)

        self.tracking_table = QTableWidget(0, 5)
        self.tracking_table.setHorizontalHeaderLabels(
            ("策略", "新增样本", "最近表现", "当前状态", "异常")
        )
        self._prepare_table(self.tracking_table)

        self.compare_table = QTableWidget(0, 7)
        self.compare_table.setHorizontalHeaderLabels(
            (
                "策略/版本",
                "条件参数",
                "样本数",
                "训练/验证",
                "最近30/50/100",
                "最大连中/连错",
                "平均间隔",
            )
        )
        self._prepare_table(self.compare_table)

        self.v21_table = QTableWidget(0, 6)
        self.v21_table.setHorizontalHeaderLabels(
            ("策略", "训练集", "验证集", "最终测试", "最差窗口", "状态")
        )
        self._prepare_table(self.v21_table)

        self.result_tabs.addTab(self.results, "扫描结果")
        self.result_tabs.addTab(self.filter_table, "筛选结果")
        self.result_tabs.addTab(self.ranking_table, "排行榜")
        self.result_tabs.addTab(self.search_table, "自动搜索")
        self.result_tabs.addTab(self.freeze_table, "冻结策略")
        self.result_tabs.addTab(self.tracking_table, "策略跟踪")
        self.result_tabs.addTab(self.compare_table, "策略对比")
        self.result_tabs.addTab(self.v21_table, "稳定性 v2.1")
        root.addWidget(self.result_tabs, 1)
        self.results.itemSelectionChanged.connect(self._update_actions)
        self.filter_table.itemSelectionChanged.connect(self._update_actions)
        self.ranking_table.itemSelectionChanged.connect(self._update_actions)
        self.freeze_table.itemSelectionChanged.connect(self._update_actions)
        self.result_tabs.currentChanged.connect(self._update_actions)
        self.data_range.currentIndexChanged.connect(self._update_range_inputs)
        self._update_range_inputs()
        self._update_actions()

    @staticmethod
    def _prepare_table(table: QTableWidget) -> None:
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.horizontalHeader().setStretchLastSection(True)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        polish_table(table, 440)

    def refresh(self) -> None:
        count = len(self._records())
        self.sample_label.setText(f"可用样本 {count}")
        self._refresh_frozen_table()

    def _records(self) -> list[dict[str, Any]]:
        records = list(self.database.valid_backtest_records("VIP"))
        selected = self.data_range.currentData()
        if isinstance(selected, int):
            return records[-selected:]
        if selected == "custom":
            start, end = self.custom_start.text().strip(), self.custom_end.text().strip()
            if start or end:
                return [
                    row for row in records
                    if (not start or str(row.get("issue_no") or "") >= start)
                    and (not end or str(row.get("issue_no") or "") <= end)
                ]
        return records

    def _update_range_inputs(self) -> None:
        visible = self.data_range.currentData() == "custom"
        self.custom_start.setVisible(visible)
        self.custom_end.setVisible(visible)

    def start_scan(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        if self.experiment_mode.currentData() == "v21":
            self.run_v21()
            return
        if self.experiment_mode.currentData() == "v2":
            try:
                result = self.run_v2_sync()
                self.notice.setText(f"v2 可复现实验完成：Snapshot {result.snapshot.snapshot_id}")
            except Exception as exc:
                self.notice.setText(f"v2 实验失败：{type(exc).__name__}: {exc}")
            return
        records = self._records()
        if not records:
            self.notice.setText("没有可用于回测的历史样本")
            return
        self.start_button.setEnabled(False)
        self.search_button.setEnabled(False)
        self.notice.setText("正在生成并扫描候选条件…")
        self._thread = QThread(self)
        self._worker = _ScanWorker(records, str(self.source.currentData()))
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._scan_progress)
        self._worker.completed.connect(self._scan_completed)
        self._worker.failed.connect(self._scan_failed)
        self._worker.completed.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._scan_finished)
        self._thread.start()

    def start_search(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        records = self._records()
        if not records:
            self.notice.setText("没有可用于搜索的历史样本")
            return
        config = SearchConfig(
            max_candidates=int(self.search_limit.currentData()),
            data_source=str(self.source.currentData()),
        )
        self.start_button.setEnabled(False)
        self.search_button.setEnabled(False)
        self.notice.setText(f"正在搜索 {config.max_candidates} 个参数组合…")
        self._thread = QThread(self)
        self._worker = _SearchWorker(records, self.storage, config)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.completed.connect(self._search_completed)
        self._worker.failed.connect(self._scan_failed)
        self._worker.completed.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._scan_finished)
        self._thread.start()

    def run_v21(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        try:
            result = self.run_v21_sync()
            self.notice.setText(
                f"v2.1 完成：{len(result.validation)} 个候选，训练/验证/测试按 70/20/10 分离"
            )
        except Exception as exc:
            self.notice.setText(f"v2.1 实验失败：{type(exc).__name__}: {exc}")

    def run_v2_sync(self):
        records = self._records()
        if not records:
            raise ValueError("没有可用于实验的历史样本")
        runner = V2ExperimentRunner(
            storage=self.storage,
            audit_store=ExperimentAuditStore(self.storage.path),
            snapshot_builder=SnapshotBuilder(),
        )
        result = runner.run(
            records,
            config=SearchConfig(
                max_candidates=int(self.search_limit.currentData()),
                data_source="VIP",
                min_sample_size=1,
            ),
        )
        self._accept_search_result(result.search)
        return result

    def run_v21_sync(self):
        """Run the fixed-standard v2.1 experiment and render its report."""
        records = self._records()
        if len(records) < 3:
            raise ValueError("v2.1 至少需要 3 条完整历史样本")
        limit = int(self.search_limit.currentData())
        gui_run_id = f"GUI-V21-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex[:8]}"
        self.storage.save_gui_run({
            "gui_run_id": gui_run_id,
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "experiment_type": "v2.1",
            "parameters": {"range": self.data_range.currentText(), "validation": ValidationConfig().to_dict()},
            "status": "RUNNING",
        })
        runner = V2ExperimentRunner(
            storage=self.storage,
            audit_store=ExperimentAuditStore(self.storage.path),
            snapshot_builder=SnapshotBuilder(),
        )
        try:
            result = runner.run_v21(
                records,
                config=SearchConfig(max_candidates=limit, data_source="VIP", min_sample_size=1),
                validation_config=ValidationConfig(),
                snapshot_metadata={
                    "data_range": self.data_range.currentText(),
                    "custom_start": self.custom_start.text().strip(),
                    "custom_end": self.custom_end.text().strip(),
                },
            )
        except Exception as exc:
            self.storage.save_gui_run({
                "gui_run_id": gui_run_id,
                "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "experiment_type": "v2.1",
                "parameters": {"range": self.data_range.currentText(), "validation": ValidationConfig().to_dict()},
                "status": "FAIL",
                "error_message": f"{type(exc).__name__}: {exc}",
            })
            raise
        self.storage.save_gui_run({
            "gui_run_id": gui_run_id,
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "experiment_type": "v2.1",
            "parameters": {"range": self.data_range.currentText(), "validation": ValidationConfig().to_dict()},
            "snapshot_id": result.snapshot.snapshot_id,
            "status": "PASS",
            "result_summary": {"candidate_count": len(result.validation)},
        })
        self.v21_result = result
        self._render_v21_result(result)
        self.result_tabs.setCurrentWidget(self.v21_table)
        self.data_changed.emit()
        return result

    def _render_v21_result(self, result) -> None:
        self.v21_table.setRowCount(len(result.validation))
        for row, item in enumerate(result.validation):
            robustness = result.robustness[row] if row < len(result.robustness) else None
            if not item.train.valid_samples or not item.validation.valid_samples or not item.test.valid_samples:
                state = "INSUFFICIENT_DATA"
            elif item.test.hit_rate is None:
                state = "FAIL"
            elif robustness is not None and robustness.worst_hit_rate is not None and item.train.hit_rate is not None and robustness.worst_hit_rate < item.train.hit_rate - 20:
                state = "WATCH"
            else:
                state = "PASS"
            values = (
                item.condition_id,
                f"{item.train.valid_samples} / {self._rate(item.train.hit_rate)}",
                f"{item.validation.valid_samples} / {self._rate(item.validation.hit_rate)}",
                f"{item.test.valid_samples} / {self._rate(item.test.hit_rate)}",
                "—" if robustness is None else self._rate(robustness.worst_hit_rate),
                state,
            )
            for column, value in enumerate(values):
                self.v21_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.v21_table.setToolTip(
            f"Snapshot ID: {result.snapshot.snapshot_id}\n"
            f"数据 SHA256: {result.snapshot.source_sha256}\n"
            f"算法版本: {result.snapshot.algorithm_version}\n"
            f"引擎版本: {result.snapshot.engine_version}"
        )
        self.v21_snapshot_label.setText(
            f"实验ID: {result.run_id} | Snapshot: {result.snapshot.snapshot_id} | "
            f"数据 SHA256: {result.snapshot.source_sha256} | "
            f"算法版本: {result.snapshot.algorithm_version} | 引擎版本: {result.snapshot.engine_version}"
        )

    def run_scan_sync(self, *, limit: int = 100) -> ExperimentResult:
        """Synchronous entry point used by smoke tests and non-GUI callers."""

        conditions = StrategyConditionGenerator().generate(limit)
        result = StrategyLabEngine().scan(
            self._records(), conditions, data_source=str(self.source.currentData())
        )
        self._accept_result(result)
        return result

    def run_search_sync(self, *, limit: int = 100) -> SearchResult:
        result = StrategySearchEngine(self.storage).search(
            self._records(),
            config=SearchConfig(
                max_candidates=limit,
                data_source=str(self.source.currentData()),
            ),
        )
        self._accept_search_result(result)
        return result

    @Slot(int, int)
    def _scan_progress(self, current: int, total: int) -> None:
        self.notice.setText(f"正在扫描 {current}/{total}")

    @Slot(object)
    def _scan_completed(self, result: ExperimentResult) -> None:
        self._accept_result(result)

    @Slot(object)
    def _search_completed(self, result: SearchResult) -> None:
        self._accept_search_result(result)

    @Slot(str)
    def _scan_failed(self, message: str) -> None:
        self.notice.setText(f"扫描失败：{message}")

    @Slot()
    def _scan_finished(self) -> None:
        self.start_button.setEnabled(True)
        self.search_button.setEnabled(True)
        if self._worker:
            self._worker.deleteLater()
        if self._thread:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None

    def _accept_search_result(self, result: SearchResult) -> None:
        self.search_result = result
        self._accept_result(result.experiment)
        self.search_table.setRowCount(1)
        values = (
            result.search_id,
            result.parameter_count,
            result.cache_hits,
            result.evaluated_count,
            f"{result.runtime_seconds:.3f}s",
        )
        self._set_result_row(
            self.search_table,
            0,
            values,
            "",
            json.dumps(dict(result.result_summary), ensure_ascii=False),
        )
        self.result_tabs.setCurrentWidget(self.search_table)
        self.notice.setText(
            f"搜索完成：参数 {result.parameter_count}，缓存 {result.cache_hits}，"
            f"实际计算 {result.evaluated_count}"
        )

    def _accept_result(self, result: ExperimentResult) -> None:
        self.experiment = result
        self.filter_decisions = ()
        self.ranking_entries = ()
        self.storage.save_experiment(result)
        self.filter_table.setRowCount(0)
        self.ranking_table.setRowCount(0)
        self.results.setRowCount(len(result.candidates))
        for row, candidate in enumerate(result.candidates):
            recent = candidate.overall.recent_30
            values = (
                candidate.condition.name,
                candidate.overall.trigger_count,
                self._rate(candidate.train.hit_rate),
                self._rate(candidate.validation.hit_rate),
                self._rate(recent),
                candidate.status,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setData(Qt.UserRole, candidate.condition.condition_id)
                item.setToolTip(candidate.condition.name)
                self.results.setItem(row, column, item)
        if result.candidates:
            self.results.selectRow(0)
        self.result_tabs.setCurrentIndex(0)
        self.notice.setText(
            f"扫描完成：{len(result.candidates)} 个候选；排序依据仅使用训练集"
        )
        self.data_changed.emit()
        self._update_actions()

    def apply_filter(self) -> tuple[FilterDecision, ...]:
        if not self.experiment:
            self.notice.setText("请先完成扫描")
            return ()
        self.filter_decisions = self.filter_engine.filter(self.experiment.candidates)
        self.ranking_entries = self.ranking_engine.rank(
            self.experiment.candidates, self.filter_decisions
        )
        self.storage.save_filter_results(
            self.experiment.experiment_id,
            self.filter_decisions,
            self.filter_engine.config,
        )
        self.storage.save_rankings(
            self.experiment.experiment_id,
            self.ranking_entries,
            self.ranking_engine.weights,
        )
        self._show_filter_results()
        self._show_rankings()
        passed = sum(1 for item in self.filter_decisions if item.passed)
        self.notice.setText(
            f"自动筛选完成：{passed} 个进入候选池，"
            f"{len(self.filter_decisions) - passed} 个未通过"
        )
        self.result_tabs.setCurrentIndex(1)
        self._update_actions()
        return self.filter_decisions

    def _show_filter_results(self) -> None:
        self.filter_table.setRowCount(len(self.filter_decisions))
        for row, decision in enumerate(self.filter_decisions):
            reasons = "；".join(decision.reasons) if decision.reasons else "进入候选池"
            values = (
                decision.candidate.condition.name,
                decision.result,
                reasons,
                f"{decision.walk_forward_pass_ratio * 100:.2f}%",
            )
            self._set_result_row(
                self.filter_table,
                row,
                values,
                decision.candidate.condition.condition_id,
                reasons,
            )

    def _show_rankings(self) -> None:
        self.ranking_table.setRowCount(len(self.ranking_entries))
        for row, entry in enumerate(self.ranking_entries):
            candidate = entry.candidate
            overall = candidate.overall
            values = (
                f"{entry.rank}. {candidate.condition.name}",
                json.dumps(dict(candidate.condition.params), ensure_ascii=False, separators=(",", ":")),
                overall.trigger_count,
                f"{self._rate(candidate.train.hit_rate)} / {self._rate(candidate.validation.hit_rate)}",
                f"{self._rate(overall.recent_30)} / {self._rate(overall.recent_50)} / {self._rate(overall.recent_100)}",
                f"{overall.max_consecutive_hits} / {overall.max_consecutive_misses}",
                "—" if overall.average_trigger_interval is None else f"{overall.average_trigger_interval:.2f}",
                entry.status,
            )
            self._set_result_row(
                self.ranking_table,
                row,
                values,
                candidate.condition.condition_id,
                "仅展示历史统计，不代表未来结果",
            )

    @staticmethod
    def _set_result_row(
        table: QTableWidget,
        row: int,
        values: tuple[Any, ...],
        condition_id: str,
        tooltip: str,
    ) -> None:
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignCenter)
            item.setData(Qt.UserRole, condition_id)
            item.setToolTip(tooltip)
            table.setItem(row, column, item)

    def _selected_candidate(self) -> CandidateResult | None:
        if not self.experiment:
            return None
        if self.result_tabs.currentIndex() not in (0, 1, 2):
            return None
        table = (self.results, self.filter_table, self.ranking_table)[
            self.result_tabs.currentIndex()
        ]
        row = table.currentRow()
        item = table.item(row, 0) if row >= 0 else None
        if item is None:
            return None
        condition_id = item.data(Qt.UserRole)
        return next(
            (
                candidate
                for candidate in self.experiment.candidates
                if candidate.condition.condition_id == condition_id
            ),
            None,
        )

    def _update_actions(self) -> None:
        enabled = self._selected_candidate() is not None
        self.filter_button.setEnabled(self.experiment is not None)
        self.detail_button.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        self.freeze_button.setEnabled(enabled)
        selected_frozen = self._selected_frozen_strategies()
        self.track_button.setEnabled(bool(selected_frozen or self.frozen_strategies))
        self.compare_button.setEnabled(len(selected_frozen) >= 2)
        self.export_button.setEnabled(self.experiment is not None)

    def show_details(self) -> None:
        candidate = self._selected_candidate()
        if not candidate:
            return
        payload = {
            "条件参数": dict(candidate.condition.params),
            "训练结果": candidate.train.to_dict(),
            "验证结果": candidate.validation.to_dict(),
            "Walk Forward窗口数": len(candidate.walk_forward),
        }
        decision = next(
            (
                item.to_dict()
                for item in self.filter_decisions
                if item.candidate.condition.condition_id == candidate.condition.condition_id
            ),
            None,
        )
        ranking = next(
            (
                item.to_dict()
                for item in self.ranking_entries
                if item.candidate.condition.condition_id == candidate.condition.condition_id
            ),
            None,
        )
        payload["筛选结果"] = decision
        payload["排行榜"] = ranking
        QMessageBox.information(
            self,
            "策略详情",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

    def save_strategy(self) -> None:
        candidate = self._selected_candidate()
        if not candidate or not self.experiment:
            return
        strategy_id = self.storage.save_strategy(self.experiment.experiment_id, candidate)
        self.notice.setText(f"策略已保存到独立实验库，编号 {strategy_id}")

    def freeze_strategy(self) -> FrozenStrategy | None:
        candidate = self._selected_candidate()
        if candidate is None:
            self.notice.setText("请先在扫描、筛选或排行榜中选择策略")
            return None
        decision = next(
            (
                item
                for item in self.filter_decisions
                if item.candidate.condition.condition_id == candidate.condition.condition_id
            ),
            None,
        )
        if decision is None:
            self.apply_filter()
            decision = next(
                (
                    item
                    for item in self.filter_decisions
                    if item.candidate.condition.condition_id == candidate.condition.condition_id
                ),
                None,
            )
        if decision is None or not decision.passed:
            self.notice.setText("该策略未通过自动筛选，不能冻结")
            return None
        existing = [
            item
            for item in self.freeze_service.list()
            if item.strategy_name == candidate.condition.name
        ]
        version = f"1.0.{len(existing)}"
        try:
            frozen = self.freeze_service.freeze(
                candidate,
                decision,
                strategy_version=version,
            )
        except Exception as exc:
            self.notice.setText(f"冻结失败：{exc}")
            return None
        self._refresh_frozen_table()
        self.result_tabs.setCurrentWidget(self.freeze_table)
        self.notice.setText(
            f"策略已冻结：{frozen.strategy_name} v{frozen.strategy_version}"
        )
        return frozen

    def _refresh_frozen_table(self) -> None:
        self.frozen_strategies = self.freeze_service.list()
        self.freeze_table.setRowCount(len(self.frozen_strategies))
        for row, frozen in enumerate(self.frozen_strategies):
            values = (
                frozen.strategy_name,
                frozen.strategy_version,
                frozen.status,
                frozen.created_at,
            )
            self._set_result_row(
                self.freeze_table,
                row,
                values,
                frozen.freeze_id,
                json.dumps(frozen.to_dict()["condition_params"], ensure_ascii=False),
            )

    def _selected_frozen_strategies(self) -> tuple[FrozenStrategy, ...]:
        if not hasattr(self, "freeze_table"):
            return ()
        rows = sorted({index.row() for index in self.freeze_table.selectedIndexes()})
        freeze_ids = {
            self.freeze_table.item(row, 0).data(Qt.UserRole)
            for row in rows
            if self.freeze_table.item(row, 0) is not None
        }
        return tuple(
            item for item in self.frozen_strategies if item.freeze_id in freeze_ids
        )

    def track_strategies(self) -> tuple[TrackingResult, ...]:
        selected = self._selected_frozen_strategies()
        if not selected and len(self.frozen_strategies) == 1:
            selected = self.frozen_strategies
        if not selected:
            self.notice.setText("请先选择至少一个冻结策略")
            return ()
        self.tracking_results = tuple(
            self.tracker.track(frozen, self._records()) for frozen in selected
        )
        self.tracking_table.setRowCount(len(self.tracking_results))
        frozen_by_id = {item.freeze_id: item for item in self.frozen_strategies}
        for row, result in enumerate(self.tracking_results):
            frozen = frozen_by_id[result.freeze_id]
            values = (
                frozen.strategy_name,
                result.new_samples,
                self._rate(result.recent_performance.recent_30),
                result.current_status,
                "是" if result.anomaly else "否",
            )
            self._set_result_row(
                self.tracking_table,
                row,
                values,
                result.freeze_id,
                "；".join(result.reasons) or "未发现异常变化",
            )
        self._refresh_frozen_table()
        self.result_tabs.setCurrentWidget(self.tracking_table)
        self.notice.setText(f"跟踪完成：{len(self.tracking_results)} 个冻结策略")
        return self.tracking_results

    def compare_strategies(self) -> ComparisonResult | None:
        selected = self._selected_frozen_strategies()
        if len(selected) < 2:
            self.notice.setText("请在冻结策略中选择两个或多个策略")
            return None
        self.comparison_result = self.comparator.compare(selected)
        self.compare_table.setRowCount(len(self.comparison_result.rows))
        for row, item in enumerate(self.comparison_result.rows):
            values = (
                f"{item.strategy_name} / {item.strategy_version}",
                json.dumps(dict(item.condition_params), ensure_ascii=False, separators=(",", ":")),
                item.sample_count,
                f"{self._rate(item.train_hit_rate)} / {self._rate(item.validation_hit_rate)}",
                f"{self._rate(item.recent_30)} / {self._rate(item.recent_50)} / {self._rate(item.recent_100)}",
                f"{item.max_consecutive_hits} / {item.max_consecutive_misses}",
                "—" if item.average_trigger_interval is None else f"{item.average_trigger_interval:.2f}",
            )
            self._set_result_row(
                self.compare_table,
                row,
                values,
                item.freeze_id,
                "冻结版本历史指标对比",
            )
        self.result_tabs.setCurrentWidget(self.compare_table)
        self.notice.setText(f"已比较 {len(self.comparison_result.rows)} 个冻结策略")
        return self.comparison_result

    def export_report(self) -> None:
        if not self.experiment:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出实验报告", "strategy_lab_report.json", "JSON (*.json)"
        )
        if not path:
            return
        self.write_report(path)
        self.notice.setText(f"报告已导出：{path}")

    def write_report(self, path: str | Path) -> Path:
        if not self.experiment:
            raise ValueError("尚无可导出的实验结果")
        target = Path(path)
        payload = self.experiment.to_dict()
        payload["strategy_lab_version"] = __version__
        payload["filter_config"] = self.filter_engine.config.to_dict()
        payload["filter_results"] = [item.to_dict() for item in self.filter_decisions]
        payload["ranking_weights"] = self.ranking_engine.weights.to_dict()
        payload["rankings"] = [item.to_dict() for item in self.ranking_entries]
        payload["search"] = self.search_result.to_dict() if self.search_result else None
        payload["frozen_strategies"] = [item.to_dict() for item in self.frozen_strategies]
        payload["tracking_results"] = [item.to_dict() for item in self.tracking_results]
        payload["comparison"] = (
            self.comparison_result.to_dict() if self.comparison_result else None
        )
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    def closeEvent(self, event) -> None:
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()
        super().closeEvent(event)

    @staticmethod
    def _rate(value: float | None) -> str:
        return "—" if value is None else f"{value:.2f}%"


__all__ = ["StrategyExperimentPage"]
