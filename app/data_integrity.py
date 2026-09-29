from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .database import Database


SOURCE_MISSING = {"VIP": "VIP缺失"}


@dataclass(frozen=True)
class IntegrityIssue:
    issue_no: str
    issue_type: str
    source_type: str = ""
    trigger_issue: str = ""
    detail: str = ""
    status: str = "missing"


class DataIntegrityAuditor:
    """Check YU28 and prediction health without starting legacy services."""

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _next_issue(issue_no: str) -> str:
        value = str(issue_no).strip()
        return str(int(value) + 1).zfill(len(value))

    @staticmethod
    def _previous_issue(issue_no: str) -> str:
        value = str(issue_no).strip()
        return str(int(value) - 1).zfill(len(value))

    @staticmethod
    def _issue_key(issue: IntegrityIssue) -> tuple[str, str, str, str]:
        return (issue.issue_no, issue.issue_type, issue.source_type, issue.trigger_issue)

    def audit(self, *, auto_queue: bool = False) -> dict[str, Any]:
        """Return health details; ``auto_queue`` is retained but ignored.

        Older callers may still pass ``auto_queue``. The strategy-first
        runtime never creates or requeues legacy tasks, regardless of its
        value.
        """
        del auto_queue
        draws = self.database.list_yu28_draws()
        draw_by_issue = {str(row["nbr"]): row for row in draws}
        draw_numbers = sorted(
            (issue for issue in draw_by_issue if issue.isdigit()), key=int
        )
        predictions = self.database.list_predictions_for_integrity()
        predictions_by_key = {
            (str(row["source_type"]), str(row["issue_no"])): row
            for row in predictions
        }
        issues: dict[tuple[str, str, str, str], IntegrityIssue] = {}

        def add(issue: IntegrityIssue) -> None:
            issues[self._issue_key(issue)] = issue

        for previous, current in zip(draw_numbers, draw_numbers[1:]):
            gap = int(current) - int(previous)
            if gap <= 1:
                continue
            for value in range(int(previous) + 1, int(current)):
                missing = str(value).zfill(len(current))
                add(
                    IntegrityIssue(
                        missing,
                        "YU28开奖缺失",
                        trigger_issue=missing,
                        detail=f"已知开奖期号 {previous} 与 {current} 之间缺少 YU28 记录",
                    )
                )

        complete = partial = missing_predictions = 0
        for trigger in draw_numbers:
            target = self._next_issue(trigger)
            prediction = predictions_by_key.get(("VIP", target))
            if prediction is None:
                missing_predictions += 1
                add(
                    IntegrityIssue(
                        target,
                        SOURCE_MISSING["VIP"],
                        source_type="VIP",
                        trigger_issue=trigger,
                        detail=f"VIP 尚无 {target} 期预测记录",
                    )
                )
                continue
            if str(prediction.get("actual_result") or "").strip():
                complete += 1
            else:
                partial += 1
                add(
                    IntegrityIssue(
                        target,
                        "开奖结果未回填",
                        source_type="VIP",
                        trigger_issue=trigger,
                        detail=f"VIP 已有 {target} 期预测，但尚无开奖结果",
                    )
                )

        for prediction in predictions:
            issue_no = str(prediction["issue_no"])
            trigger = self._previous_issue(issue_no) if issue_no.isdigit() else ""
            if trigger and trigger not in draw_by_issue:
                add(
                    IntegrityIssue(
                        issue_no,
                        "YU28开奖缺失",
                        source_type=str(prediction["source_type"]),
                        trigger_issue=trigger,
                        detail=f"预测 {issue_no} 缺少可靠的 {trigger} 期开奖基准",
                    )
                )

            draw = draw_by_issue.get(issue_no)
            if draw and not str(prediction.get("actual_result") or "").strip():
                self.database.backfill_result_if_empty(
                    issue_no, str(draw["number"]).rsplit("=", 1)[-1]
                )

        active_keys = set(issues)
        for row in self.database.list_integrity_issues(100000):
            key = (
                str(row["issue_no"]),
                str(row["issue_type"]),
                str(row["source_type"]),
                str(row["trigger_issue"]),
            )
            if key not in active_keys and row["status"] != "resolved":
                self.database.upsert_integrity_issue(
                    row["issue_no"],
                    row["issue_type"],
                    source_type=row["source_type"],
                    trigger_issue=row["trigger_issue"],
                    status="resolved",
                    detail="完整性审计确认已恢复",
                )
        for issue in issues.values():
            self.database.upsert_integrity_issue(
                issue.issue_no,
                issue.issue_type,
                source_type=issue.source_type,
                trigger_issue=issue.trigger_issue,
                status=issue.status,
                detail=issue.detail,
            )

        missing_yu28 = sum(
            issue.issue_type == "YU28开奖缺失" for issue in issues.values()
        )
        summary = {
            "total_periods": len(draw_numbers),
            "complete": complete,
            "partial": partial,
            "missing": missing_predictions + missing_yu28,
            "duplicate_count": 0,
            "wrong_issue_count": sum(
                issue.issue_type in ("错期", "期号绑定失败") for issue in issues.values()
            ),
            "pending_count": 0,
        }
        return {
            "summary": summary,
            "issues": [issue.__dict__ for issue in issues.values()],
            "auto_queued": 0,
        }


__all__ = ["DataIntegrityAuditor", "IntegrityIssue", "SOURCE_MISSING"]
