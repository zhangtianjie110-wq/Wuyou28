"""Create a machine-readable first-phase stopping report."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    algorithms = json.loads((ROOT / "data" / "algorithms.json").read_text(encoding="utf-8"))
    syntax = json.loads((ROOT / "data" / "syntax_summary.json").read_text(encoding="utf-8"))
    dataset = json.loads((ROOT / "data" / "validation_dataset.json").read_text(encoding="utf-8"))
    report = {
        "algorithms_read": len(algorithms),
        "all_formulaText_read": len(algorithms) == 100,
        "syntax": syntax,
        "first_algorithm": dataset["algorithm"],
        "hypotheses": [],
        "comparison": {
            "compared": 0,
            "一致": 0,
            "不一致": 0,
            "一致率": None,
            "reason": "the first saved algorithm does not occur in the read-only Le28 capture history",
        },
        "available_vip_capture_records": dataset["record_count"],
        "matching_first_algorithm_records": dataset["matching_count"],
        "continuation_eligible": False,
        "continuation_requirement": "at least 50 chronological matching samples, then an independent 100% validation",
        "production_integration": False,
    }
    (ROOT / "data" / "phase1_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
