"""Evaluation boundary for VIP formula research.

No symbol has been assigned business semantics yet.  Raising explicitly is
safer than producing a plausible but unverified prediction.
"""


class FormulaSemanticsUnknown(NotImplementedError):
    pass


def evaluate_formula(formula_text: str, prior_history: list[dict]) -> list:
    """Refuse evaluation until a rule is independently validated."""

    raise FormulaSemanticsUnknown(
        "formula semantics are not established; no local prediction is emitted"
    )
