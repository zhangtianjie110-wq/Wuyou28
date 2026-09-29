from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..conditions import __file__ as CONDITIONS_FILE
from ..vip100_history import resolve_history_database


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_config_hash(config: Any) -> str:
    """Return a stable SHA256 for a run configuration."""

    return hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _schema_version(connection: sqlite3.Connection) -> str:
    rows: list[dict[str, Any]] = []
    tables = connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    for name, sql in tables:
        columns = [
            {"name": row[1], "type": row[2], "notnull": row[3], "default": row[4], "pk": row[5]}
            for row in connection.execute(f'PRAGMA table_info("{name}")').fetchall()
        ]
        rows.append({"name": name, "sql": sql or "", "columns": columns})
    return hashlib.sha256(canonical_json(rows).encode("utf-8")).hexdigest()[:16]


def _distinct_text(connection: sqlite3.Connection, table: str, column: str) -> tuple[str, ...]:
    try:
        values = connection.execute(
            f'SELECT DISTINCT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL AND "{column}" <> "" ORDER BY "{column}"'
        ).fetchall()
    except sqlite3.OperationalError:
        return ()
    return tuple(str(row[0]) for row in values)


def _first_distinct_text(connection: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> tuple[str, ...]:
    for column in columns:
        values = _distinct_text(connection, table, column)
        if values:
            return values
    return ()


def _condition_generator_version() -> str:
    try:
        return sha256_file(CONDITIONS_FILE)[:16]
    except OSError:
        # Frozen builds may ship bytecode without the source .py file.  Keep a
        # stable marker rather than making an otherwise valid audit impossible.
        return hashlib.sha256(b"strategy_lab.conditions:v1").hexdigest()[:16]


def inspect_history_metadata(path: str | Path | None = None) -> dict[str, Any]:
    """Inspect VIP100_HISTORY without opening it for writes."""

    source = resolve_history_database(path) if path is not None else resolve_history_database()
    if not source.is_file():
        raise FileNotFoundError(f"VIP100_HISTORY database not found: {source}")
    uri = f"{source.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        runs_table = "vip100_reconstructed_runs" in tables
        predictions_table = "vip100_reconstructed_predictions" in tables
        issue_count = 0
        prediction_count = 0
        algorithm_count = 0
        if runs_table:
            issue_count = int(connection.execute("SELECT COUNT(DISTINCT target_issue) FROM vip100_reconstructed_runs").fetchone()[0])
        if predictions_table:
            prediction_count = int(connection.execute("SELECT COUNT(*) FROM vip100_reconstructed_predictions").fetchone()[0])
            algorithm_count = int(connection.execute("SELECT COUNT(DISTINCT algorithm_id) FROM vip100_reconstructed_predictions").fetchone()[0])
        return {
            "schema_version": _schema_version(connection),
            "tables": tables,
            "issue_count": issue_count,
            "prediction_count": prediction_count,
            "algorithm_count": algorithm_count,
            "engine_versions": _first_distinct_text(connection, "vip100_reconstructed_runs", ("engine_version", "engine_version_hash")) if runs_table else (),
            "algorithm_versions": _first_distinct_text(connection, "vip100_reconstructed_runs", ("replay_version", "algorithm_version", "algorithm_hash")) if runs_table else (),
        }


@dataclass(frozen=True)
class ExperimentSnapshot:
    snapshot_id: str
    source_path: str
    source_sha256: str
    source_size: int
    schema_version: str
    algorithm_version: str
    engine_version: str
    condition_generator_version: str
    config_hash: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SnapshotBuilder:
    """Build deterministic metadata for a reproducible experiment run."""

    def __init__(self, history_path: str | Path | None = None):
        self.history_path = resolve_history_database(history_path) if history_path is not None else resolve_history_database()

    def build(self, config: Any) -> ExperimentSnapshot:
        source = self.history_path
        metadata = inspect_history_metadata(source)
        source_hash = sha256_file(source)
        config_hash = canonical_config_hash(config)
        algorithm_version = ",".join(metadata["algorithm_versions"]) or "unknown"
        engine_version = ",".join(metadata["engine_versions"]) or "unknown"
        identity = {
            "source_sha256": source_hash,
            "schema_version": metadata["schema_version"],
            "algorithm_version": algorithm_version,
            "engine_version": engine_version,
            "condition_generator_version": _condition_generator_version(),
            "config_hash": config_hash,
        }
        snapshot_id = "SNAP-" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:24]
        return ExperimentSnapshot(
            snapshot_id=snapshot_id,
            source_path=str(source),
            source_sha256=source_hash,
            source_size=source.stat().st_size,
            schema_version=metadata["schema_version"],
            algorithm_version=algorithm_version,
            engine_version=engine_version,
            condition_generator_version=identity["condition_generator_version"],
            config_hash=config_hash,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )


__all__ = [
    "ExperimentSnapshot",
    "SnapshotBuilder",
    "canonical_config_hash",
    "canonical_json",
    "inspect_history_metadata",
    "sha256_file",
]
