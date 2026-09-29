"""Syntax-only parser for Le28 saved formulaText values.

This module deliberately does not assign business meaning to any symbol.  It
only records the bracketed numeric terms and the separators observed in the
formula text.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


class FormulaSyntaxError(ValueError):
    """Raised when formulaText contains syntax outside the observed grammar."""


_TOKEN_RE = re.compile(r"\[(?P<number>\d+)\]|(?P<operator>[+|=#])")


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    for match in _TOKEN_RE.finditer(text):
        if text[pos : match.start()].strip():
            raise FormulaSyntaxError(
                f"unexpected text at offset {pos}: {text[pos:match.start()]!r}"
            )
        if match.group("number") is not None:
            tokens.append(("number", match.group("number")))
        else:
            tokens.append(("operator", match.group("operator")))
        pos = match.end()
    if text[pos:].strip():
        raise FormulaSyntaxError(f"unexpected text at offset {pos}: {text[pos:]!r}")
    if not tokens:
        raise FormulaSyntaxError("formulaText is empty")
    return tokens


def parse_formula(text: str) -> dict[str, Any]:
    """Return a deterministic syntax AST for one formulaText string.

    ``+`` and ``|`` are retained as structural operators. ``=`` and ``#``
    are retained as opaque markers because their semantics are intentionally
    outside this first research phase.
    """

    if not isinstance(text, str):
        raise TypeError("formulaText must be a string")
    tokens = _tokenize(text)
    groups: list[list[dict[str, Any]]] = [[]]
    operators: list[str] = []
    values: list[int] = []
    for kind, value in tokens:
        if kind == "number":
            number = int(value)
            groups[-1].append({"kind": "number", "value": number, "raw": value})
            values.append(number)
            continue
        operators.append(value)
        if value == "|":
            groups.append([])
        elif value in "=#":
            groups[-1].append({"kind": "marker", "value": value})
        elif value == "+":
            # The plus sign is represented in the operator stream; terms stay
            # as an ordered list so no arithmetic interpretation is implied.
            continue
    if any(not group for group in groups):
        raise FormulaSyntaxError("empty group in formulaText")

    group_signatures = [tuple(item.get("value") for item in group if item["kind"] == "number") for group in groups]
    return {
        "type": "formula",
        "raw": text,
        "normalized": text.replace(" ", ""),
        "groups": [{"terms": group, "term_count": len(group)} for group in groups],
        "group_count": len(groups),
        "term_counts": [len(group) for group in groups],
        "operators": operators,
        "operator_counts": dict(sorted(Counter(operators).items())),
        "numbers": values,
        "number_range": {"min": min(values), "max": max(values)},
        "duplicate_group_count": len(group_signatures) - len(set(group_signatures)),
        "duplicate_number_count": len(values) - len(set(values)),
    }


def parse_many(formulas: list[str]) -> list[dict[str, Any]]:
    return [parse_formula(formula) for formula in formulas]
