"""Summarize VIP formula research v2 without declaring unverified semantics."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> None:
    observation = json.loads((ROOT / "data" / "v2_single_algorithm_observations.json").read_text(encoding="utf-8"))
    mapping = json.loads((ROOT / "data" / "v2_mapping_experiments.json").read_text(encoding="utf-8"))
    wrapper = json.loads((ROOT / "data" / "v2_export_wrapper_analysis.json").read_text(encoding="utf-8"))
    tested = [item for item in mapping["hypotheses"] if item.get("tested_samples", 0)]
    best = max(tested, key=lambda item: (item["support_samples"], -item["counterexamples"])) if tested else None
    report = {
        "single_algorithm_standard_answers": {
            "success": True,
            "algorithm": observation["algorithm"],
            "sample_count": observation["sample_count"],
            "first_issue": observation["samples"][0]["issue"],
            "last_issue": observation["samples"][-1]["issue"],
            "read_method": observation["read_method"],
        },
        "numeric_token_conclusion": "no candidate has been promoted to semantics",
        "best_exploratory_candidate": best,
        "evidence_and_counterexamples": mapping["hypotheses"],
        "plus": mapping["operator_observations"]["+"],
        "pipe": mapping["operator_observations"]["|"],
        "export_wrapper": wrapper,
        "control_experiments": {
            "count": 0,
            "reason": "no safe edit interaction was used",
        },
        "highest_validation": {
            "sample_count": observation["sample_count"],
            "candidate_support": best["support_samples"] if best else 0,
            "candidate_total": best["tested_samples"] if best else 0,
        },
        "evaluator_ready": False,
        "evaluator_requirement": "one deterministic rule must reach 10/10, then 30/30, then an independent 50/50",
        "production_integration": False,
    }
    (ROOT / "data" / "v2_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
