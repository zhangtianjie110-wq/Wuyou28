"""Strategy laboratory v2 reproducibility primitives.

The v2 package is additive.  Existing strategy_lab v1 imports and database
tables are intentionally left untouched.
"""

from .snapshot import (
    ExperimentSnapshot,
    SnapshotBuilder,
    canonical_config_hash,
    inspect_history_metadata,
    sha256_file,
)
from .experiment_audit import ExperimentAudit, ExperimentAuditStore
from .experiment import V2ExperimentResult, V2ExperimentRunner
from .validation import ValidationConfig, ValidationSplit, ValidationResult, split_time_series, evaluate_three_way
from .robustness import WindowResult, SensitivityResult, RobustnessResult, analyze_time_windows, analyze_parameter_sensitivity, analyze_robustness
from .baselines import BaselineResult, evaluate_baselines, compare_to_baselines

__version__ = "2.1.0"

__all__ = [
    "ExperimentAuditStore",
    "ExperimentAudit",
    "ExperimentSnapshot",
    "SnapshotBuilder",
    "V2ExperimentResult",
    "V2ExperimentRunner",
    "ValidationConfig",
    "ValidationSplit",
    "ValidationResult",
    "split_time_series",
    "evaluate_three_way",
    "WindowResult",
    "SensitivityResult",
    "RobustnessResult",
    "analyze_time_windows",
    "analyze_parameter_sensitivity",
    "analyze_robustness",
    "BaselineResult",
    "evaluate_baselines",
    "compare_to_baselines",
    "canonical_config_hash",
    "inspect_history_metadata",
    "sha256_file",
    "__version__",
]
