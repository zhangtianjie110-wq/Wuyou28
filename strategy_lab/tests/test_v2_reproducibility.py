import hashlib
import sqlite3

import pytest

from strategy_lab.search import SearchConfig
from strategy_lab.storage import StrategyLabStorage
from strategy_lab.v2 import (
    ExperimentAuditStore,
    SnapshotBuilder,
    V2ExperimentRunner,
    canonical_config_hash,
    inspect_history_metadata,
    sha256_file,
)

from .helpers import make_records


def make_history(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE vip100_reconstructed_runs (
                target_issue TEXT PRIMARY KEY,
                engine_version TEXT,
                replay_version TEXT,
                prediction_count INTEGER,
                actual_result TEXT,
                actual_combination TEXT
            );
            CREATE TABLE vip100_reconstructed_predictions (
                target_issue TEXT,
                algorithm_id TEXT,
                prediction TEXT,
                hit INTEGER
            );
            """
        )
        connection.execute(
            "INSERT INTO vip100_reconstructed_runs VALUES (?, ?, ?, ?, ?, ?)",
            ("202609280001", "engine-1", "algo-1", 100, "", "大单"),
        )
        connection.executemany(
            "INSERT INTO vip100_reconstructed_predictions VALUES (?, ?, ?, ?)",
            [("202609280001", f"A{i}", "大单", i % 2) for i in range(100)],
        )


def test_snapshot_is_deterministic_and_reads_source_read_only(tmp_path):
    history = tmp_path / "vip100_history.sqlite3"
    make_history(history)
    before = sha256_file(history)
    config = {"max_candidates": 50, "train_ratio": 0.7}
    first = SnapshotBuilder(history).build(config)
    second = SnapshotBuilder(history).build(config)
    assert first.snapshot_id == second.snapshot_id
    assert first.source_sha256 == before
    assert first.source_size == history.stat().st_size
    assert first.algorithm_version == "algo-1"
    assert first.engine_version == "engine-1"
    assert inspect_history_metadata(history)["issue_count"] == 1
    assert sha256_file(history) == before


def test_config_hash_is_order_independent():
    assert canonical_config_hash({"b": 2, "a": 1}) == canonical_config_hash({"a": 1, "b": 2})


def test_additive_audit_schema_and_success_run(tmp_path):
    history = tmp_path / "vip100_history.sqlite3"
    make_history(history)
    lab_db = tmp_path / "strategy_lab.db"
    audit = ExperimentAuditStore(lab_db)
    runner = V2ExperimentRunner(
        storage=StrategyLabStorage(lab_db),
        audit_store=audit,
        snapshot_builder=SnapshotBuilder(history),
    )
    result = runner.run(make_records(20), config=SearchConfig(max_candidates=50, min_sample_size=1))
    assert result.snapshot.snapshot_id.startswith("SNAP-")
    assert result.experiment.data_source == result.snapshot.snapshot_id
    with sqlite3.connect(lab_db) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"experiment_snapshots", "experiment_audit_log", "experiment_run_v2"} <= tables
    run = audit.get_run(result.run_id)
    assert run["status"] == "PASS"
    assert [row["stage"] for row in audit.list_audit(result.run_id)] == ["SNAPSHOT", "DATA_CHECK", "SEARCH"]


def test_failed_run_is_audited(tmp_path):
    history = tmp_path / "vip100_history.sqlite3"
    make_history(history)
    lab_db = tmp_path / "strategy_lab.db"
    audit = ExperimentAuditStore(lab_db)
    runner = V2ExperimentRunner(
        storage=StrategyLabStorage(lab_db),
        audit_store=audit,
        snapshot_builder=SnapshotBuilder(history),
    )
    with pytest.raises(ValueError, match="no complete"):
        runner.run([], config=SearchConfig(max_candidates=50, min_sample_size=1))
    with sqlite3.connect(lab_db) as connection:
        row = connection.execute("SELECT status, failure_reason FROM experiment_run_v2").fetchone()
    assert row[0] == "FAIL"
    assert "no complete" in row[1]

