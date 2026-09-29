from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .constants import DEFAULT_DB_PATH
from .stats import validate_and_enrich


PREDICTION_COLUMNS = (
    "issue_no",
    "source_type",
    "plan_text",
    "plan_count",
    "big_single",
    "big_double",
    "small_single",
    "small_double",
    "actual_result",
    "actual_combo",
    "correct_count",
    "wrong_count",
    "status",
    "invalid_reason",
    "is_invalid",
    "stat_min",
    "stat_max",
    "lowest_two",
    "lowest_two_diff",
    "tied_min",
    "average",
)


class DuplicateRecordError(ValueError):
    pass


class Database:
    def __init__(
        self,
        path: str | Path = DEFAULT_DB_PATH,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            # WAL is persistent for the database file. Setting it once during
            # initialization avoids taking a schema-level lock on every read.
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_no TEXT NOT NULL,
                    source_type TEXT NOT NULL CHECK(source_type = 'VIP'),
                    plan_text TEXT NOT NULL DEFAULT '',
                    plan_count INTEGER NOT NULL DEFAULT 0,
                    big_single INTEGER NOT NULL DEFAULT 0,
                    big_double INTEGER NOT NULL DEFAULT 0,
                    small_single INTEGER NOT NULL DEFAULT 0,
                    small_double INTEGER NOT NULL DEFAULT 0,
                    actual_result TEXT NOT NULL DEFAULT '',
                    actual_combo TEXT,
                    correct_count INTEGER,
                    wrong_count INTEGER,
                    status TEXT NOT NULL DEFAULT '待检查',
                    invalid_reason TEXT NOT NULL DEFAULT '',
                    is_invalid INTEGER NOT NULL DEFAULT 0,
                    stat_min INTEGER NOT NULL DEFAULT 0,
                    stat_max INTEGER NOT NULL DEFAULT 0,
                    lowest_two TEXT NOT NULL DEFAULT '',
                    lowest_two_diff INTEGER NOT NULL DEFAULT 0,
                    tied_min INTEGER NOT NULL DEFAULT 0,
                    average REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_type, issue_no)
                );

                CREATE INDEX IF NOT EXISTS idx_predictions_issue ON predictions(issue_no);
                CREATE INDEX IF NOT EXISTS idx_predictions_source ON predictions(source_type);
                CREATE INDEX IF NOT EXISTS idx_predictions_status ON predictions(status);

                CREATE TABLE IF NOT EXISTS strategies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    source_type TEXT NOT NULL CHECK(source_type = 'VIP'),
                    method TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id INTEGER NOT NULL,
                    strategy_name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(strategy_id) REFERENCES strategies(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS yu28_draws (
                    nbr TEXT PRIMARY KEY,
                    draw_time TEXT NOT NULL,
                    number TEXT NOT NULL,
                    combination TEXT NOT NULL,
                    countdown TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS data_integrity_issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_no TEXT NOT NULL,
                    issue_type TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT '',
                    trigger_issue TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'missing'
                        CHECK(status IN ('missing', 'queued', 'resolved')),
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(issue_no, issue_type, source_type, trigger_issue)
                );

                CREATE INDEX IF NOT EXISTS idx_integrity_issues_status
                    ON data_integrity_issues(status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_integrity_issues_issue
                    ON data_integrity_issues(issue_no, source_type);
                """
            )
            now = self._now()
            db.execute(
                "INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES('train_ratio', '0.7', ?)",
                (now,),
            )
        self._migrate_validation_rules()

    def _migrate_validation_rules(self) -> None:
        if self.get_setting("validation_rules_version", "1") == "3":
            return
        assignment = ", ".join(f"{name}=?" for name in PREDICTION_COLUMNS)
        with self.connect() as db:
            rows = db.execute("SELECT * FROM predictions").fetchall()
            for row in rows:
                values = self._record_values(dict(row))
                db.execute(
                    f"UPDATE predictions SET {assignment} WHERE id=?",
                    tuple(values[name] for name in PREDICTION_COLUMNS) + (row["id"],),
                )
            db.execute(
                """
                INSERT INTO settings(key, value, updated_at) VALUES('validation_rules_version', '3', ?)
                ON CONFLICT(key) DO UPDATE SET value='3', updated_at=excluded.updated_at
                """,
                (self._now(),),
            )

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _record_values(payload: dict[str, Any]) -> dict[str, Any]:
        enriched = validate_and_enrich(payload).values
        enriched["is_invalid"] = int(bool(enriched.get("is_invalid")))
        enriched["tied_min"] = int(bool(enriched.get("tied_min")))
        return enriched

    def add_prediction(self, payload: dict[str, Any]) -> int:
        values = self._record_values(payload)
        now = self._now()
        column_sql = ", ".join(PREDICTION_COLUMNS)
        placeholder_sql = ", ".join(f":{name}" for name in PREDICTION_COLUMNS)
        values.update(created_at=now, updated_at=now)
        try:
            with self.connect() as db:
                cursor = db.execute(
                    f"INSERT INTO predictions ({column_sql}, created_at, updated_at) "
                    f"VALUES ({placeholder_sql}, :created_at, :updated_at)",
                    values,
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper():
                raise DuplicateRecordError(
                    f"{values['source_type']} 的期号 {values['issue_no']} 已存在"
                ) from exc
            raise

    def update_prediction(self, record_id: int, payload: dict[str, Any]) -> None:
        current = self.get_prediction(record_id)
        if not current:
            raise ValueError("记录不存在")
        merged = dict(current)
        merged.update(payload)
        values = self._record_values(merged)
        values["id"] = int(record_id)
        values["updated_at"] = self._now()
        assignment = ", ".join(f"{name}=:{name}" for name in PREDICTION_COLUMNS)
        try:
            with self.connect() as db:
                db.execute(
                    f"UPDATE predictions SET {assignment}, updated_at=:updated_at WHERE id=:id",
                    values,
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper():
                raise DuplicateRecordError(
                    f"{values['source_type']} 的期号 {values['issue_no']} 已存在"
                ) from exc
            raise

    def update_result_by_issue(self, issue_no: str, actual_result: str) -> int:
        updated = 0
        result = str(actual_result).strip()
        for record in self.find_by_issue(str(issue_no).strip()):
            if str(record.get("actual_result") or "").strip() == result:
                continue
            self.update_prediction(record["id"], {"actual_result": result})
            updated += 1
        return updated

    def set_invalid(self, record_id: int, invalid: bool) -> None:
        record = self.get_prediction(record_id)
        if not record:
            raise ValueError("记录不存在")
        record["is_invalid"] = int(invalid)
        self.update_prediction(record_id, record)

    def delete_prediction(self, record_id: int) -> dict[str, Any]:
        """Delete one record and discard stale backtests for its source."""
        record = self.get_prediction(record_id)
        if not record:
            raise ValueError("记录不存在")
        with self.connect() as db:
            db.execute("DELETE FROM predictions WHERE id=?", (int(record_id),))
            db.execute("DELETE FROM backtest_runs WHERE source_type=?", (record["source_type"],))
        return record

    def count_non_normal_predictions(self) -> int:
        with self.connect() as db:
            return int(db.execute(
                "SELECT COUNT(*) FROM predictions WHERE status<>'正常'"
            ).fetchone()[0])

    def delete_non_normal_predictions(self) -> int:
        """Delete records excluded from the user's retained '正常' dataset."""
        with self.connect() as db:
            cursor = db.execute("DELETE FROM predictions WHERE status<>'正常'")
            return int(cursor.rowcount)

    def get_prediction(self, record_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM predictions WHERE id=?", (record_id,)).fetchone()
            return dict(row) if row else None

    def find_prediction(self, source_type: str, issue_no: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM predictions WHERE source_type=? AND issue_no=?",
                (source_type, issue_no),
            ).fetchone()
            return dict(row) if row else None

    def find_by_issue(self, issue_no: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM predictions WHERE issue_no=? ORDER BY source_type", (issue_no,)
            ).fetchall()
            return [dict(row) for row in rows]

    def list_predictions(
        self,
        search: str = "",
        source_type: str = "全部",
        status: str = "全部",
        ascending: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            clauses.append("(issue_no LIKE ? OR plan_text LIKE ? OR actual_result LIKE ?)")
            pattern = f"%{search.strip()}%"
            params.extend([pattern, pattern, pattern])
        if source_type == "VIP":
            clauses.append("source_type=?")
            params.append(source_type)
        if status != "全部":
            clauses.append("status=?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        order = "ASC" if ascending else "DESC"
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM predictions{where} ORDER BY id {order}", params
            ).fetchall()
            return [dict(row) for row in rows]

    def valid_backtest_records(self, source_type: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM predictions
                WHERE source_type=? AND status='正常' AND is_invalid=0 AND actual_combo IS NOT NULL
                ORDER BY id ASC
                """,
                (source_type,),
            ).fetchall()
            return [dict(row) for row in rows]

    def dashboard(self) -> dict[str, Any]:
        today = datetime.now().strftime("%Y-%m-%d")
        with self.connect() as db:
            total = db.execute("SELECT COUNT(DISTINCT issue_no) FROM predictions").fetchone()[0]
            total_rows = db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
            latest = db.execute("SELECT * FROM predictions ORDER BY id DESC LIMIT 1").fetchone()
            latest_rows = db.execute(
                "SELECT * FROM predictions ORDER BY id DESC LIMIT 10"
            ).fetchall()
            source_rows = db.execute(
                """
                SELECT source_type, COUNT(*) AS records,
                       COUNT(DISTINCT issue_no) AS issues,
                       SUM(CASE WHEN substr(created_at, 1, 10)=? THEN 1 ELSE 0 END) AS today_records
                FROM predictions GROUP BY source_type
                """,
                (today,),
            ).fetchall()
            latest_strategy = db.execute(
                """
                SELECT s.name, b.result_json
                FROM backtest_runs b JOIN strategies s ON s.id=b.strategy_id
                ORDER BY b.id DESC LIMIT 1
                """
            ).fetchone()
        strategy_data: dict[str, Any] = {}
        strategy_name = "未运行"
        if latest_strategy:
            strategy_name = latest_strategy["name"]
            strategy_data = json.loads(latest_strategy["result_json"])
        source_counts = {
            "VIP": {"records": 0, "issues": 0, "today_records": 0},
        }
        for row in source_rows:
            source_counts[row["source_type"]] = {
                "records": int(row["records"] or 0),
                "issues": int(row["issues"] or 0),
                "today_records": int(row["today_records"] or 0),
            }
        trend: list[float] = []
        hits = 0
        for index, detail in enumerate(strategy_data.get("details", []), start=1):
            hits += int(bool(detail.get("hit")))
            trend.append(round(hits / index * 100, 2))
        return {
            "total": total,
            "total_rows": total_rows,
            "current_issue": latest["issue_no"] if latest else "—",
            "last_time": latest["updated_at"] if latest else "—",
            "recent": [dict(row) for row in latest_rows],
            "source_counts": source_counts,
            "today_total": sum(item["today_records"] for item in source_counts.values()),
            "strategy_name": strategy_name,
            "strategy_samples": strategy_data.get("matched", 0),
            "strategy_hits": strategy_data.get("hits", 0),
            "strategy_misses": strategy_data.get("misses", 0),
            "strategy_hit_rate": strategy_data.get("hit_rate", 0.0),
            "strategy_trend": trend,
        }

    def statistics(self) -> dict[str, Any]:
        """Return the VIP real-data summary."""
        with self.connect() as db:
            source_rows = db.execute(
                """
                SELECT source_type,
                       COUNT(*) AS records,
                       COUNT(DISTINCT issue_no) AS issues,
                       SUM(CASE WHEN status='正常' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status='待开奖' THEN 1 ELSE 0 END) AS pending,
                       SUM(CASE WHEN status='待检查' THEN 1 ELSE 0 END) AS review,
                       SUM(CASE WHEN status='无效' THEN 1 ELSE 0 END) AS invalid,
                       COALESCE(SUM(correct_count), 0) AS correct_plans,
                       COALESCE(SUM(wrong_count), 0) AS wrong_plans
                FROM predictions GROUP BY source_type
                """
            ).fetchall()
            backtests = db.execute(
                """
                SELECT b.source_type, b.strategy_name, b.result_json, b.created_at
                FROM backtest_runs b
                JOIN (
                    SELECT source_type, MAX(id) AS max_id FROM backtest_runs GROUP BY source_type
                ) latest ON latest.max_id=b.id
                """
            ).fetchall()
        result = {
            "VIP": {"records": 0, "issues": 0, "completed": 0, "pending": 0,
                    "review": 0, "invalid": 0, "correct_plans": 0, "wrong_plans": 0},
        }
        for row in source_rows:
            item = result[row["source_type"]]
            for key in item:
                item[key] = int(row[key] or 0)
            denominator = item["correct_plans"] + item["wrong_plans"]
            item["plan_hit_rate"] = round(item["correct_plans"] / denominator * 100, 2) if denominator else 0.0
        for source in result:
            result[source].setdefault("plan_hit_rate", 0.0)
            result[source]["backtest"] = None
        for row in backtests:
            data = json.loads(row["result_json"])
            result[row["source_type"]]["backtest"] = {
                "strategy_name": row["strategy_name"],
                "created_at": row["created_at"],
                "matched": int(data.get("matched", 0)),
                "hits": int(data.get("hits", 0)),
                "misses": int(data.get("misses", 0)),
                "hit_rate": float(data.get("hit_rate", 0.0)),
            }
        return result

    def save_strategy(
        self, name: str, source_type: str, method: str, parameters: dict[str, Any]
    ) -> int:
        name = name.strip()
        if not name:
            raise ValueError("策略名称不能为空")
        now = self._now()
        content = json.dumps(parameters, ensure_ascii=False, sort_keys=True)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO strategies(name, source_type, method, parameters_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    source_type=excluded.source_type,
                    method=excluded.method,
                    parameters_json=excluded.parameters_json,
                    updated_at=excluded.updated_at
                """,
                (name, source_type, method, content, now, now),
            )
            row = db.execute("SELECT id FROM strategies WHERE name=?", (name,)).fetchone()
            return int(row[0])

    def list_strategies(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM strategies ORDER BY updated_at DESC, id DESC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["parameters"] = json.loads(item.pop("parameters_json"))
            item["enabled"] = bool(item["parameters"].get("enabled", True))
            result.append(item)
        return result

    def get_strategy(self, strategy_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM strategies WHERE id=?", (strategy_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["parameters"] = json.loads(item.pop("parameters_json"))
        item["enabled"] = bool(item["parameters"].get("enabled", True))
        return item

    def set_strategy_enabled(self, strategy_id: int, enabled: bool) -> None:
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("策略不存在")
        parameters = dict(strategy["parameters"])
        parameters["enabled"] = bool(enabled)
        self.save_strategy(
            strategy["name"], strategy["source_type"], strategy["method"], parameters
        )

    def delete_strategy(self, strategy_id: int) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM strategies WHERE id=?", (strategy_id,))

    def save_backtest_result(self, strategy: dict[str, Any], result: dict[str, Any]) -> int:
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO backtest_runs(strategy_id, strategy_name, source_type, result_json, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    strategy["id"],
                    strategy["name"],
                    strategy["source_type"],
                    json.dumps(result, ensure_ascii=False),
                    self._now(),
                ),
            )
            return int(cursor.lastrowid)

    def latest_backtest(self, strategy_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM backtest_runs WHERE strategy_id=? ORDER BY id DESC LIMIT 1",
                (strategy_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json"))
        return item

    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return str(row[0]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        now = self._now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO settings(key, value, updated_at) VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, str(value), now),
            )

    def save_yu28_draw(self, payload: dict[str, Any]) -> bool:
        """Insert one official draw once; return True only for a new issue."""
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO yu28_draws(
                    nbr, draw_time, number, combination, countdown, created_at
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    str(payload["nbr"]),
                    str(payload["time"]),
                    str(payload["number"]),
                    str(payload["combination"]),
                    str(payload.get("countdown", "")),
                    self._now(),
                ),
            )
            return cursor.rowcount == 1

    def find_yu28_draw(self, issue_no: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                """SELECT nbr, draw_time AS time, number, combination,
                          countdown, created_at
                   FROM yu28_draws WHERE nbr=?""",
                (str(issue_no),),
            ).fetchone()
            return dict(row) if row else None

    def latest_yu28_draw(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                """SELECT nbr, draw_time AS time, number, combination,
                          countdown, created_at
                   FROM yu28_draws
                   ORDER BY CAST(nbr AS INTEGER) DESC LIMIT 1"""
            ).fetchone()
            return dict(row) if row else None

    def count_yu28_draws(self) -> int:
        with self.connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM yu28_draws").fetchone()[0])

    def list_yu28_draws(self, limit: int = 10000) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100000))
        with self.connect() as db:
            rows = db.execute(
                """SELECT nbr, draw_time AS time, number, combination,
                          countdown, created_at
                   FROM yu28_draws
                   ORDER BY CAST(nbr AS INTEGER) ASC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_predictions_for_integrity(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT id, issue_no, source_type, actual_result, status,
                          created_at, updated_at
                   FROM predictions ORDER BY CAST(issue_no AS INTEGER), source_type"""
            ).fetchall()
            return [dict(row) for row in rows]

    def upsert_integrity_issue(
        self,
        issue_no: str,
        issue_type: str,
        *,
        source_type: str = "",
        trigger_issue: str = "",
        status: str = "missing",
        detail: str = "",
    ) -> int:
        if status not in ("missing", "queued", "resolved"):
            raise ValueError(f"不支持的数据完整性状态：{status}")
        now = self._now()
        resolved_at = now if status == "resolved" else ""
        with self.connect() as db:
            db.execute(
                """INSERT INTO data_integrity_issues(
                       issue_no, issue_type, source_type, trigger_issue,
                       status, detail, created_at, updated_at, resolved_at
                   ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(issue_no, issue_type, source_type, trigger_issue)
                   DO UPDATE SET status=excluded.status,
                                 detail=excluded.detail,
                                 updated_at=excluded.updated_at,
                                 resolved_at=excluded.resolved_at""",
                (
                    str(issue_no), str(issue_type), str(source_type),
                    str(trigger_issue), status, str(detail), now, now, resolved_at,
                ),
            )
            row = db.execute(
                """SELECT id FROM data_integrity_issues
                   WHERE issue_no=? AND issue_type=? AND source_type=? AND trigger_issue=?""",
                (str(issue_no), str(issue_type), str(source_type), str(trigger_issue)),
            ).fetchone()
            return int(row[0])

    def list_integrity_issues(
        self, limit: int = 200, status: str | None = None
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 5000))
        with self.connect() as db:
            if status:
                rows = db.execute(
                    """SELECT * FROM data_integrity_issues
                       WHERE status=? ORDER BY CAST(issue_no AS INTEGER), id LIMIT ?""",
                    (status, safe_limit),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT * FROM data_integrity_issues
                       ORDER BY CAST(issue_no AS INTEGER), id LIMIT ?""",
                    (safe_limit,),
                ).fetchall()
            return [dict(row) for row in rows]

    def integrity_summary(self) -> dict[str, int]:
        with self.connect() as db:
            issue_counts = db.execute(
                """SELECT status, COUNT(*) AS count FROM data_integrity_issues
                   GROUP BY status"""
            ).fetchall()
            wrong_count = db.execute(
                """SELECT COUNT(*) FROM data_integrity_issues
                   WHERE issue_type IN ('错期', '期号绑定失败') AND status<>'resolved'"""
            ).fetchone()[0]
        issue_map = {str(row[0]): int(row[1]) for row in issue_counts}
        with self.connect() as db:
            total_periods = int(db.execute("SELECT COUNT(*) FROM yu28_draws").fetchone()[0])
            complete = int(db.execute(
                """SELECT COUNT(*) FROM predictions
                   WHERE status='正常' AND actual_result<>'' AND is_invalid=0"""
            ).fetchone()[0])
        return {
            "total_periods": total_periods,
            "complete": complete,
            "partial": max(0, total_periods - complete - issue_map.get("missing", 0)),
            "missing": issue_map.get("missing", 0),
            "duplicate_count": 0,
            "wrong_issue_count": int(wrong_count),
            "pending_count": 0,
        }

    def backfill_result_if_empty(self, issue_no: str, actual_result: str) -> int:
        """Fill only blank results; never replace an existing result."""
        result = str(actual_result).strip()
        updated = 0
        for record in self.find_by_issue(str(issue_no).strip()):
            if str(record.get("actual_result") or "").strip():
                continue
            self.update_prediction(record["id"], {"actual_result": result})
            updated += 1
        return updated

