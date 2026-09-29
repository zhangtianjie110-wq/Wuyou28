"""Compatibility exports for v2 additive persistence."""

from .experiment_audit import DEFAULT_PATH, ExperimentAuditStore

ExperimentAudit = ExperimentAuditStore


class ExperimentV21Storage(ExperimentAuditStore):
    """Named facade for v2.1 result tables, retaining one DB owner."""

    pass

__all__ = ["DEFAULT_PATH", "ExperimentAudit", "ExperimentAuditStore", "ExperimentV21Storage"]
