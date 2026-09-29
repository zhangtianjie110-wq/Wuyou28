from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.constants import DATA_DIR

from .snapshot import ExperimentSnapshot, canonical_json


DEFAULT_PATH = DATA_DIR / "strategy_lab.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ExperimentAuditStore:
    """Additive v2 persistence in the isolated strategy_lab database."""

    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        return connection

    def ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiment_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    source_size INTEGER NOT NULL,
                    schema_version TEXT NOT NULL,
                    algorithm_version TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    condition_generator_version TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_audit_log (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS experiment_run_v2 (
                    run_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_reason TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS experiment_validation (
                    run_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    condition_id TEXT NOT NULL,
                    train_result TEXT NOT NULL,
                    validation_result TEXT NOT NULL,
                    test_result TEXT NOT NULL,
                    selected INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, condition_id)
                );
                CREATE TABLE IF NOT EXISTS experiment_robustness (
                    run_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    condition_id TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, condition_id)
                );
                CREATE TABLE IF NOT EXISTS experiment_baselines (
                    run_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    condition_id TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, condition_id)
                );
                CREATE INDEX IF NOT EXISTS idx_experiment_audit_run
                    ON experiment_audit_log(run_id, audit_id);
                """
            )

    def save_validation(self, run_id: str, snapshot_id: str, condition_id: str,
                        train_result: Any, validation_result: Any, test_result: Any,
                        *, selected: bool = False) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO experiment_validation
                (run_id, snapshot_id, condition_id, train_result, validation_result,
                 test_result, selected, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, snapshot_id, condition_id, canonical_json(train_result),
                 canonical_json(validation_result), canonical_json(test_result),
                 int(selected), _now()),
            )

    def save_robustness(self, run_id: str, snapshot_id: str, condition_id: str, result: Any) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO experiment_robustness
                (run_id, snapshot_id, condition_id, result_json, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (run_id, snapshot_id, condition_id, canonical_json(result), _now()),
            )

    def save_baselines(self, run_id: str, snapshot_id: str, condition_id: str, result: Any) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO experiment_baselines
                (run_id, snapshot_id, condition_id, result_json, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (run_id, snapshot_id, condition_id, canonical_json(result), _now()),
            )

    def list_validation(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM experiment_validation WHERE run_id = ? ORDER BY condition_id", (run_id,)).fetchall()
        return [dict(row) for row in rows]

    # Descriptive aliases for storage integrations.
    save_validation_result = save_validation
    save_robustness_result = save_robustness
    save_baseline_result = save_baselines

    def save_snapshot(self, snapshot: ExperimentSnapshot) -> str:
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO experiment_snapshots
                (snapshot_id, source_path, source_sha256, source_size,
                 schema_version, algorithm_version, engine_version,
                 condition_generator_version, config_hash, snapshot_json,
                 created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot.snapshot_id,
                    snapshot.source_path,
                    snapshot.source_sha256,
                    snapshot.source_size,
                    snapshot.schema_version,
                    snapshot.algorithm_version,
                    snapshot.engine_version,
                    snapshot.condition_generator_version,
                    snapshot.config_hash,
                    json.dumps(snapshot.to_dict(), ensure_ascii=False, sort_keys=True),
                    snapshot.created_at,
                ),
            )
        return snapshot.snapshot_id

    def start_run(self, snapshot: ExperimentSnapshot, config: Any) -> str:
        run_id = f"RUN2-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex[:8]}"
        started = _now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO experiment_run_v2
                (run_id, snapshot_id, config_json, started_at, status)
                VALUES (?, ?, ?, ?, ?)""",
                (run_id, snapshot.snapshot_id, canonical_json(config), started, "RUNNING"),
            )
        return run_id

    def record_stage(
        self,
        run_id: str,
        snapshot_id: str,
        stage: str,
        status: str,
        *,
        candidate_count: int = 0,
        reason: str = "",
        started_at: str | None = None,
        ended_at: str | None = None,
    ) -> int:
        begin = started_at or _now()
        end = ended_at or _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO experiment_audit_log
                (run_id, snapshot_id, stage, status, candidate_count, reason,
                 started_at, ended_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, snapshot_id, stage, status, int(candidate_count), reason, begin, end),
            )
            return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        candidate_count: int = 0,
        success_count: int = 0,
        failure_reason: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE experiment_run_v2
                SET ended_at = ?, status = ?, candidate_count = ?,
                    success_count = ?, failure_reason = ?
                WHERE run_id = ?""",
                (_now(), status, int(candidate_count), int(success_count), failure_reason, run_id),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM experiment_run_v2 WHERE run_id = ?", (run_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def list_audit(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM experiment_audit_log WHERE run_id = ? ORDER BY audit_id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]


ExperimentAudit = ExperimentAuditStore

__all__ = ["DEFAULT_PATH", "ExperimentAudit", "ExperimentAuditStore"]
