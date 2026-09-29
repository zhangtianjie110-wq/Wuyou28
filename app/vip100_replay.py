from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Callable, Iterable


REPLAY_VERSION = "VIP100_REPLAY_V1"
SOURCE_TYPE = "RECONSTRUCTED"


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def eligible_issues(draws: Iterable[dict], limit: int = 5000) -> list[str]:
    by_issue = {int(row["issue"]): row for row in draws}
    values = [
        issue
        for issue in sorted(by_issue)
        if all(issue - offset in by_issue for offset in range(1, 8))
    ]
    return [str(issue) for issue in values[-max(0, int(limit)) :]]


def build_replay_payload(
    target_issue: str | int,
    draws_by_issue: dict[int, dict],
    catalog: list[dict],
    algorithm_hash: str,
    calculate_all: Callable,
    *,
    generated_at: str | None = None,
) -> dict:
    issue = int(target_issue)
    required = [issue - offset for offset in range(1, 8)]
    if any(value >= issue for value in required):
        raise ValueError("historical input boundary is invalid")
    try:
        history = [dict(draws_by_issue[value]) for value in required]
    except KeyError as exc:
        raise ValueError(f"missing historical input: {exc.args[0]}") from exc
    if [int(row["issue"]) for row in history] != required:
        raise ValueError("historical input order is invalid")
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    batch = calculate_all(history, catalog, issue, calculated_at=timestamp, as_of=None)
    if batch.get("record_count") != 100 or len(batch.get("records", ())) != 100:
        raise ValueError("replay must contain exactly 100 predictions")
    if batch.get("catalog_sha256") != algorithm_hash:
        raise ValueError("replay algorithm hash mismatch")
    records = []
    for order, row in enumerate(batch["records"], 1):
        records.append(
            {
                "target_issue": str(issue),
                "algorithm_id": str(row["algorithm_id"]),
                "algorithm_order": order,
                "prediction": int(row["local_prediction"]),
                "combination": str(row["combination"]),
                "formula": str(row["formulaText"]),
                "formula_hash": hashlib.sha256(
                    str(row["formulaText"]).encode("utf-8")
                ).hexdigest(),
                "source_type": SOURCE_TYPE,
            }
        )
    input_snapshot = [
        {
            "issue": str(row["issue"]),
            "draw_time": str(row["draw_time"]),
            "number": str(row["number"]),
        }
        for row in history
    ]
    return {
        "target_issue": str(issue),
        "source_type": SOURCE_TYPE,
        "engine_version": str(batch["engine_version"]),
        "algorithm_hash": algorithm_hash,
        "generated_at": timestamp,
        "as_of_issue": str(issue - 1),
        "input_start_issue": str(issue - 7),
        "input_end_issue": str(issue - 1),
        "input_count": 7,
        "prediction_count": 100,
        "replay_version": REPLAY_VERSION,
        "input_snapshot_hash": sha256(input_snapshot),
        "records": records,
    }


@dataclass(frozen=True)
class ReplayValidation:
    issues: int
    predictions: int
    missing_predictions: int
    duplicate_predictions: int
    rejected_issues: int
    input_boundary_errors: int
    hash_errors: int
    forward_contamination: int


class ReplayStore:
    """Writer for the isolated replay database; never opens production databases."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS vip100_reconstructed_runs (
                    target_issue INTEGER PRIMARY KEY,
                    source_type TEXT NOT NULL CHECK(source_type='RECONSTRUCTED'),
                    engine_version TEXT NOT NULL,
                    algorithm_hash TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    as_of_issue INTEGER NOT NULL,
                    input_start_issue INTEGER NOT NULL,
                    input_end_issue INTEGER NOT NULL,
                    input_count INTEGER NOT NULL CHECK(input_count=7),
                    prediction_count INTEGER NOT NULL CHECK(prediction_count=100),
                    replay_version TEXT NOT NULL,
                    input_snapshot_hash TEXT NOT NULL,
                    actual_result TEXT,
                    actual_combination TEXT,
                    CHECK(as_of_issue < target_issue),
                    CHECK(input_end_issue < target_issue)
                );
                CREATE TABLE IF NOT EXISTS vip100_reconstructed_predictions (
                    target_issue INTEGER NOT NULL,
                    algorithm_id TEXT NOT NULL,
                    algorithm_order INTEGER NOT NULL,
                    prediction INTEGER NOT NULL CHECK(prediction BETWEEN 0 AND 27),
                    combination TEXT NOT NULL,
                    formula TEXT NOT NULL,
                    formula_hash TEXT NOT NULL,
                    source_type TEXT NOT NULL CHECK(source_type='RECONSTRUCTED'),
                    hit INTEGER CHECK(hit IN (0,1) OR hit IS NULL),
                    PRIMARY KEY(target_issue, algorithm_id),
                    UNIQUE(target_issue, algorithm_order),
                    FOREIGN KEY(target_issue) REFERENCES vip100_reconstructed_runs(target_issue)
                );
                CREATE INDEX IF NOT EXISTS idx_reconstructed_source
                    ON vip100_reconstructed_runs(source_type, target_issue);
                """
            )
            connection.commit()

    def write_batch(
        self,
        payload: dict,
        *,
        actual_result: str | None,
        actual_combination: str | None,
    ) -> bool:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            inserted = self._write_batch(
                connection,
                payload,
                actual_result=actual_result,
                actual_combination=actual_combination,
            )
            connection.commit()
        return inserted

    def write_batches(
        self,
        batches: Iterable[tuple[dict, str | None, str | None]],
        *,
        transaction_size: int = 100,
    ) -> int:
        inserted = 0
        pending = 0
        size = max(1, int(transaction_size))
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            for payload, actual_result, actual_combination in batches:
                inserted += int(
                    self._write_batch(
                        connection,
                        payload,
                        actual_result=actual_result,
                        actual_combination=actual_combination,
                    )
                )
                pending += 1
                if pending >= size:
                    connection.commit()
                    pending = 0
            connection.commit()
        return inserted

    @staticmethod
    def _write_batch(
        connection: sqlite3.Connection,
        payload: dict,
        *,
        actual_result: str | None,
        actual_combination: str | None,
    ) -> bool:
        if payload.get("source_type") != SOURCE_TYPE:
            raise ValueError("replay source must be RECONSTRUCTED")
        if payload.get("prediction_count") != 100 or len(payload.get("records", ())) != 100:
            raise ValueError("replay batch must contain exactly 100 rows")
        issue = int(payload["target_issue"])
        existing = connection.execute(
            "SELECT algorithm_hash, input_snapshot_hash, prediction_count "
            "FROM vip100_reconstructed_runs WHERE target_issue=?",
            (issue,),
        ).fetchone()
        if existing is not None:
            expected = (
                payload["algorithm_hash"],
                payload["input_snapshot_hash"],
                payload["prediction_count"],
            )
            if tuple(existing) != expected:
                raise FileExistsError(f"replay conflict at issue {issue}")
            count = connection.execute(
                "SELECT COUNT(*) FROM vip100_reconstructed_predictions "
                "WHERE target_issue=?",
                (issue,),
            ).fetchone()[0]
            if int(count) != 100:
                raise ValueError(f"incomplete existing replay at issue {issue}")
            return False
        connection.execute(
            """INSERT INTO vip100_reconstructed_runs VALUES(
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )""",
            (
                issue,
                SOURCE_TYPE,
                payload["engine_version"],
                payload["algorithm_hash"],
                payload["generated_at"],
                int(payload["as_of_issue"]),
                int(payload["input_start_issue"]),
                int(payload["input_end_issue"]),
                int(payload["input_count"]),
                int(payload["prediction_count"]),
                payload["replay_version"],
                payload["input_snapshot_hash"],
                actual_result,
                actual_combination,
            ),
        )
        connection.executemany(
            """INSERT INTO vip100_reconstructed_predictions VALUES(
                ?,?,?,?,?,?,?,?,?
            )""",
            [
                (
                    issue,
                    row["algorithm_id"],
                    int(row["algorithm_order"]),
                    int(row["prediction"]),
                    row["combination"],
                    row["formula"],
                    row["formula_hash"],
                    SOURCE_TYPE,
                    None
                    if actual_combination is None
                    else int(row["combination"] == actual_combination),
                )
                for row in payload["records"]
            ],
        )
        return True

    def validate(self, expected_hash: str) -> ReplayValidation:
        with closing(sqlite3.connect(self.path)) as connection:
            issues = int(
                connection.execute(
                    "SELECT COUNT(*) FROM vip100_reconstructed_runs"
                ).fetchone()[0]
            )
            predictions = int(
                connection.execute(
                    "SELECT COUNT(*) FROM vip100_reconstructed_predictions"
                ).fetchone()[0]
            )
            missing = int(
                connection.execute(
                    """SELECT COALESCE(SUM(100-total),0) FROM (
                        SELECT r.target_issue, COUNT(p.algorithm_id) AS total
                        FROM vip100_reconstructed_runs r
                        LEFT JOIN vip100_reconstructed_predictions p
                          ON p.target_issue=r.target_issue
                        GROUP BY r.target_issue HAVING total<100
                    )"""
                ).fetchone()[0]
            )
            duplicates = int(
                connection.execute(
                    """SELECT COUNT(*) FROM (
                        SELECT target_issue, algorithm_id, COUNT(*) AS total
                        FROM vip100_reconstructed_predictions
                        GROUP BY target_issue, algorithm_id HAVING total>1
                    )"""
                ).fetchone()[0]
            )
            boundary = int(
                connection.execute(
                    """SELECT COUNT(*) FROM vip100_reconstructed_runs
                       WHERE as_of_issue>=target_issue OR input_end_issue>=target_issue
                          OR input_start_issue<>target_issue-7
                          OR input_end_issue<>target_issue-1 OR input_count<>7"""
                ).fetchone()[0]
            )
            hash_errors = int(
                connection.execute(
                    "SELECT COUNT(*) FROM vip100_reconstructed_runs WHERE algorithm_hash<>?",
                    (expected_hash,),
                ).fetchone()[0]
            )
            contamination = int(
                connection.execute(
                    """SELECT
                        (SELECT COUNT(*) FROM vip100_reconstructed_runs WHERE source_type<>'RECONSTRUCTED')
                        + (SELECT COUNT(*) FROM vip100_reconstructed_predictions WHERE source_type<>'RECONSTRUCTED')"""
                ).fetchone()[0]
            )
        return ReplayValidation(
            issues,
            predictions,
            missing,
            duplicates,
            0,
            boundary,
            hash_errors,
            contamination,
        )
