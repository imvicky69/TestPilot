"""
test_solver.py - Unit tests for Option Mapping and Solver Payload validation
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from test_automation import OPTION_MAP
from dashboard import OPTION_MAP as DASH_OPTION_MAP


class TestSolverMappings(unittest.TestCase):
    """Validate DOM option selectors and mapping dictionaries."""

    def test_option_mappings(self):
        for letter, opt_id in [("A", "question-option-0"), ("B", "question-option-1"), ("C", "question-option-2"), ("D", "question-option-3")]:
            self.assertEqual(OPTION_MAP.get(letter), opt_id)
            self.assertEqual(DASH_OPTION_MAP.get(letter), opt_id)

    def test_numeric_aliases(self):
        self.assertEqual(OPTION_MAP.get("1"), "question-option-0")
        self.assertEqual(OPTION_MAP.get("2"), "question-option-1")
        self.assertEqual(OPTION_MAP.get("3"), "question-option-2")
        self.assertEqual(OPTION_MAP.get("4"), "question-option-3")


if __name__ == "__main__":
    unittest.main()

