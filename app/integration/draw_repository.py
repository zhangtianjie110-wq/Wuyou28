from __future__ import annotations

import logging
from pathlib import Path

from .health import freshness, read_json_object, readonly_sqlite
from .models import DrawRecord


logger = logging.getLogger(__name__)


def _combination(number: str) -> str:
    total = int(str(number).rsplit("=", 1)[1])
    return ("大" if total >= 14 else "小") + ("双" if total % 2 == 0 else "单")


class DrawRepository:
    """Read official YU28 draws without initializing or migrating any database."""

    def __init__(self, database_path: Path, raw_inputs_dir: Path):
        self.database_path = Path(database_path)
        self.raw_inputs_dir = Path(raw_inputs_dir)

    def _database_draws(self) -> dict[str, DrawRecord]:
        if not self.database_path.is_file():
            logger.warning("draw database missing: path=%s", self.database_path)
            return {}
        try:
            with readonly_sqlite(self.database_path) as connection:
                rows = connection.execute(
                    """SELECT nbr, draw_time, number, combination, countdown
                       FROM yu28_draws ORDER BY CAST(nbr AS INTEGER)"""
                ).fetchall()
        except Exception:
            logger.exception("draw database read failed: path=%s", self.database_path)
            raise
        logger.info("draw database loaded: path=%s rows=%s", self.database_path, len(rows))
        return {
            str(row["nbr"]): DrawRecord(
                issue=str(row["nbr"]),
                draw_time=str(row["draw_time"]),
                number=str(row["number"]),
                combination=str(row["combination"]),
                countdown=str(row["countdown"] or ""),
                source="YU28_DATABASE",
            )
            for row in rows
        }

    def _database_history(
        self, limit: int, after_issue: str | int | None = None
    ) -> list[DrawRecord]:
        if not self.database_path.is_file():
            logger.warning("draw history database missing: path=%s", self.database_path)
            return []
        parameters: list[object] = []
        where = ""
        if after_issue is not None:
            where = "WHERE nbr > ?"
            parameters.append(str(after_issue))
        parameters.append(limit)
        try:
            with readonly_sqlite(self.database_path) as connection:
                rows = connection.execute(
                    f"""SELECT nbr, draw_time, number, combination, countdown
                        FROM yu28_draws {where}
                        ORDER BY nbr DESC LIMIT ?""",
                    tuple(parameters),
                ).fetchall()
        except Exception:
            logger.exception(
                "draw history read failed: path=%s limit=%s after_issue=%s",
                self.database_path,
                limit,
                after_issue,
            )
            raise
        return [
            DrawRecord(
                issue=str(row["nbr"]),
                draw_time=str(row["draw_time"]),
                number=str(row["number"]),
                combination=str(row["combination"]),
                countdown=str(row["countdown"] or ""),
                source="YU28_DATABASE",
            )
            for row in reversed(rows)
        ]

    def _latest_database_draw(self) -> DrawRecord | None:
        rows = self._database_history(1)
        return rows[-1] if rows else None

    def _latest_raw_draw(self) -> DrawRecord | None:
        if not self.raw_inputs_dir.is_dir():
            return None
        paths = sorted(
            (item for item in self.raw_inputs_dir.glob("*.json") if item.stem.isdigit()),
            key=lambda item: int(item.stem),
            reverse=True,
        )
        for path in paths:
            try:
                document = read_json_object(path)
            except (OSError, ValueError):
                continue
            candidates = []
            for row in document.get("history", []):
                issue = str(row.get("issue", ""))
                number = str(row.get("number", ""))
                draw_time = str(row.get("draw_time", ""))
                if issue.isdigit() and "=" in number and draw_time:
                    candidates.append(
                        DrawRecord(
                            issue=issue,
                            draw_time=draw_time,
                            number=number,
                            combination=_combination(number),
                            source="YU28_RAW_SNAPSHOT",
                        )
                    )
            if candidates:
                return max(candidates, key=lambda row: int(row.issue))
        return None

    def _raw_draws(self) -> dict[str, DrawRecord]:
        values: dict[str, DrawRecord] = {}
        if not self.raw_inputs_dir.is_dir():
            return values
        paths = sorted(
            (item for item in self.raw_inputs_dir.glob("*.json") if item.stem.isdigit()),
            key=lambda item: int(item.stem),
            reverse=True,
        )
        for path in paths:
            try:
                document = read_json_object(path)
            except (OSError, ValueError):
                continue
            for row in document.get("history", []):
                issue = str(row.get("issue", ""))
                number = str(row.get("number", ""))
                draw_time = str(row.get("draw_time", ""))
                if not issue.isdigit() or issue in values or "=" not in number or not draw_time:
                    continue
                values[issue] = DrawRecord(
                    issue=issue,
                    draw_time=draw_time,
                    number=number,
                    combination=_combination(number),
                    source="YU28_RAW_SNAPSHOT",
                )
        return values

    def _all(self) -> dict[str, DrawRecord]:
        try:
            values = self._database_draws()
        except Exception:
            logger.exception("draw database source unavailable: path=%s", self.database_path)
            values = {}
        try:
            values.update(self._raw_draws())
        except Exception:
            logger.exception("draw raw snapshot source unavailable: path=%s", self.raw_inputs_dir)
            pass
        return values

    def latest(self) -> DrawRecord | None:
        database = self._latest_database_draw()
        raw = self._latest_raw_draw()
        values = [row for row in (database, raw) if row is not None]
        return (
            max(
                values,
                key=lambda row: (
                    int(row.issue),
                    row.source == "YU28_RAW_SNAPSHOT",
                ),
            )
            if values
            else None
        )

    def recent(self, limit: int = 20) -> list[DrawRecord]:
        safe_limit = max(1, min(int(limit), 500000))
        values = self._all()
        issues = sorted(values, key=int, reverse=True)[:safe_limit]
        return [values[issue] for issue in issues]

    def history(self, limit: int = 500000) -> list[DrawRecord]:
        """Return oldest-to-newest official draws using the indexed issue key."""
        safe_limit = max(1, min(int(limit), 500000))
        values = {row.issue: row for row in self._database_history(safe_limit)}
        try:
            values.update(self._raw_draws())
        except Exception:
            pass
        issues = sorted(values, key=int)[-safe_limit:]
        return [values[issue] for issue in issues]

    def since(self, issue: str | int, limit: int = 500000) -> list[DrawRecord]:
        """Return new draws after an issue without rescanning the full database."""
        safe_limit = max(1, min(int(limit), 500000))
        marker = str(issue)
        values = {
            row.issue: row
            for row in self._database_history(safe_limit, after_issue=marker)
        }
        try:
            values.update(
                {
                    key: row
                    for key, row in self._raw_draws().items()
                    if int(key) > int(marker)
                }
            )
        except Exception:
            pass
        issues = sorted(values, key=int)[:safe_limit]
        return [values[value] for value in issues]

    def get(self, issue: str | int) -> DrawRecord | None:
        return self._all().get(str(issue))

    def status(self) -> dict:
        try:
            source_errors = []
            try:
                database_values = self._database_draws()
                database_status = "ONLINE" if database_values else "OFFLINE"
            except Exception as exc:
                database_values = {}
                database_status = "ERROR"
                source_errors.append(f"database: {type(exc).__name__}: {exc}")
            try:
                raw_values = self._raw_draws()
                raw_status = "ONLINE" if raw_values else "OFFLINE"
            except Exception as exc:
                raw_values = {}
                raw_status = "ERROR"
                source_errors.append(f"raw snapshots: {type(exc).__name__}: {exc}")
            values = {**database_values, **raw_values}
            latest = values[max(values, key=int)] if values else None
            if latest is None:
                status = "ERROR" if source_errors else "OFFLINE"
                return {
                    "status": status,
                    "latest_issue": None,
                    "database_status": database_status,
                    "raw_snapshots_status": raw_status,
                    "errors": source_errors,
                    "freshness": {"status": status},
                }
            current = freshness(latest.draw_time, 600)
            return {
                "status": "ONLINE" if current["status"] == "FRESH" else "STALE",
                "latest_issue": latest.issue,
                "source": latest.source,
                "freshness": current,
                "database_status": database_status,
                "raw_snapshots_status": raw_status,
                "errors": source_errors,
            }
        except Exception as exc:
            return {
                "status": "ERROR",
                "latest_issue": None,
                "error": f"{type(exc).__name__}: {exc}",
                "freshness": {"status": "ERROR"},
            }
