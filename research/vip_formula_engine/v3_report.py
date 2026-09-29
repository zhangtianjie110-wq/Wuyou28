"""Produce the v3 stop report without claiming control-experiment results."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    preflight = json.loads((ROOT / "data" / "v3_preflight.json").read_text(encoding="utf-8"))
    v2 = json.loads((ROOT / "data" / "v2_single_algorithm_observations.json").read_text(encoding="utf-8"))
    baseline = preflight["baseline"]
    (ROOT / "data" / "v3_report.json").write_text(
        json.dumps(
            {
                "baseline": baseline,
                "baseline_matches_v1_hash": baseline["sha256_id_order"] == "8ab6c0e4b07809b636bf4f7b5d3561d65ac0c3ce7469b6cad6167328558fa460",
                "official_editor_visible": preflight["official_editor_visible"],
                "control_experiments": 0,
                "temporary_algorithms_created": 0,
                "mutation_performed": False,
                "single_variable_fingerprints": [],
                "position_experiments": [],
                "operator_experiments": [],
                "existing_v2_samples_preserved": v2["sample_count"],
                "status": preflight["status"],
                "stop_reason": preflight["stop_reason"],
                "evaluator_revalidation": "not started; no candidate semantics were produced",
                "production_integration": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
