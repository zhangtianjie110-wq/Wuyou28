import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formula_evaluator import FormulaSemanticsUnknown, evaluate_formula
from formula_parser import parse_formula
from formula_validator import assert_strictly_prior


class FormulaParserTests(unittest.TestCase):
    def test_first_formula_is_syntax_only(self):
        ast = parse_formula("[17]+[18]+[3]|[15]+[16]+[4]|[15]+[15]+[4]")
        self.assertEqual(ast["group_count"], 3)
        self.assertEqual(ast["term_counts"], [3, 3, 3])
        self.assertEqual(ast["number_range"], {"min": 3, "max": 18})
        self.assertEqual(ast["duplicate_group_count"], 0)

    def test_opaque_markers_are_retained(self):
        ast = parse_formula("=[1]#[2]|[3]")
        self.assertEqual(ast["operator_counts"], {"#": 1, "=": 1, "|": 1})

    def test_unknown_semantics_cannot_emit_prediction(self):
        with self.assertRaises(FormulaSemanticsUnknown):
            evaluate_formula("[1]|[2]", [])

    def test_future_rows_are_rejected(self):
        with self.assertRaises(AssertionError):
            assert_strictly_prior([{"issue": "10"}], 10)
        assert_strictly_prior([{"issue": "9"}], 10)


if __name__ == "__main__":
    unittest.main()
