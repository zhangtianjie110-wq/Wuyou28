"""Preserve both original assertion suites, now loading the formal DIY module."""
import contextlib
import io
import unittest

from . import ui_diy_phase1_original, ui_diy_phase2_original

class OriginalPhaseTests(unittest.TestCase):
    def test_original_phase1_assertions(self):
        with contextlib.redirect_stdout(io.StringIO()):
            ui_diy_phase1_original.main()

    def test_original_phase2_assertions(self):
        with contextlib.redirect_stdout(io.StringIO()):
            ui_diy_phase2_original.main()
