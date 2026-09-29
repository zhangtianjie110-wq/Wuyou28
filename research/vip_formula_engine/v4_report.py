"""Assemble the read-only v4 cross-observation report."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    observation = json.loads((ROOT / "data" / "v4_ui_observation.json").read_text(encoding="utf-8"))
    structure = json.loads((ROOT / "data" / "v4_structure_analysis.json").read_text(encoding="utf-8"))
    audit = json.loads((ROOT / "data" / "v3_hash_audit.json").read_text(encoding="utf-8"))
    report = {
        "page_classification": observation["page_classification"],
        "classification_reason": "algorithm summary rows and a separate current forecast/history table are both visible",
        "algorithm_count": observation["algorithm_count"],
        "visible_summary_row_count": observation["visible_summary_row_count"],
        "reliable_algorithm_mapping_count": observation["reliable_algorithm_mapping_count"],
        "same_issue_independent_output_count": observation["independent_output_count_for_current_issue"],
        "active_algorithm": observation["active_algorithm_matches"],
        "formula_pair_has_one_numeric_difference": structure["one_number_difference_pair_count"] > 0,
        "formula_pair_has_one_position_difference": structure["one_position_difference_pair_count"] > 0,
        "formula_pair_has_one_segment_difference": structure["one_segment_difference_pair_count"] > 0,
        "closest_10": structure["closest_10"],
        "numeric_1_to_21_new_evidence": "none: no additional algorithm-specific output mapping was available",
        "multi_period_cross_observation_recommended": False,
        "multi_period_reason": "first obtain a reliable per-algorithm UI mapping; current summary rows omit algorithm_id and formulaText",
        "evaluator_missing": ["per-algorithm output mapping", "validated meaning of numeric tokens", "validated + and | semantics", "independent 100% comparison"],
        "canonical_sha256": audit["historical_hash_reproduced"],
        "canonical_sha256_matches_required": audit["historical_hash_reproduced"] == "18c1390bdbf3d5db6e48939fc5c124f217ab04e2195db2cc60b3bff4e0e838bd",
        "leveldb_write": False,
        "production_integration": False,
    }
    (ROOT / "data" / "v4_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
