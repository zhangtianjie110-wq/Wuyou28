"""Build a read-only, chronological research snapshot from production SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from extract_algorithms import read_current_algorithms


DB = Path(r"C:\Users\Administrator\AppData\Local\Le28Predictor\data\le28.db")
OUTPUT = Path(__file__).resolve().parent / "data"
FIRST_ID = "1790079879506-sfbf2m"


def _history_rows(table_rows_json: str) -> list[dict[str, Any]]:
    try:
        rows = json.loads(table_rows_json or "[]")
    except json.JSONDecodeError:
        return []
    result = []
    for row in rows:
        if not isinstance(row, list) or not row:
            continue
        issue = str(row[0])
        if not re.fullmatch(r"\d{6,}", issue):
            continue
        result.append({"issue": issue, "columns": row})
    return result


def build() -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    captures = conn.execute(
        "select issue_no, source_type, capture_source, current_formula, table_rows_json, created_at "
        "from le28_capture_details where source_type='VIP' order by cast(issue_no as integer)"
    ).fetchall()
    predictions = {
        row["issue_no"]: dict(row)
        for row in conn.execute(
            "select issue_no, source_type, actual_result, actual_combo, status, is_invalid "
            "from predictions where source_type='VIP'"
        )
    }
    draws = {
        row["nbr"]: dict(row)
        for row in conn.execute("select nbr, number, combination, draw_time from yu28_draws")
    }
    conn.close()

    algorithms = read_current_algorithms()
    first = next(item for item in algorithms if item["id"] == FIRST_ID)
    records = []
    matching = []
    for capture in captures:
        issue = str(capture["issue_no"])
        record = {
            "issue": issue,
            "source_type": capture["source_type"],
            "read_method": capture["capture_source"],
            "current_formula": capture["current_formula"],
            "le28_output": _history_rows(capture["table_rows_json"]),
            "actual": predictions.get(issue, {}),
            "draw": draws.get(issue),
            "created_at": capture["created_at"],
        }
        records.append(record)
        if capture["current_formula"].strip() == first["formulaText"]:
            matching.append(record)
    records.sort(key=lambda item: int(item["issue"]))
    matching.sort(key=lambda item: int(item["issue"]))
    return {
        "algorithm": first,
        "records": records,
        "matching_algorithm_records": matching,
        "record_count": len(records),
        "matching_count": len(matching),
        "database": str(DB),
        "future_data_policy": "target issue N may only use rows with issue < N",
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "validation_dataset.json").write_text(
        json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
