# SPDX-License-Identifier: Apache-2.0
"""Independent numerical/failure controls; these do not substitute for SPICE."""
from dataclasses import replace
from pathlib import Path
import json
import math
import unittest

from characterize import Case, analyze, check_window, integrate, prepare_resistor_model
from design import Design, netlist


def square_wave(end=.6051, start=.006, period=.01):
    points = {0.: 0., .001: 0., .003: 0., .005: 0., end: 0.}
    # Explicit finite 100 ns edges avoid float-modulo glitches in the oracle.
    edge = start
    while edge < end:
        for t, v in ((edge-1e-7, 0.), (edge, 3.3),
                     (edge+period/2-1e-7, 3.3), (edge+period/2, 0.)):
            if 0 <= t <= end:
                points[t] = v
        edge += period
    return [(t, v, -5e-9, -16.5e-9) for t, v in sorted(points.items())]


class Measurements(unittest.TestCase):
    def test_integral_interpolates_window_boundaries(self):
        # y=2t, integral from .25 to .75 is .5, with nonuniform spacing.
        self.assertAlmostEqual(integrate([(0, 0), (.1, .2), (.9, 1.8), (1, 2)], 1, .25, .75), .5)

    def test_full_cycle_power_and_frequency(self):
        result = check_window(square_wave(), .1, .6, 3.3)
        self.assertAlmostEqual(result["hz"], 100, places=4)
        self.assertAlmostEqual(result["current_na"], 5)
        self.assertAlmostEqual(result["power_nw"], 16.5)
        self.assertLess(result["max_rise_ns"], 100)

    def test_startup_and_complete_trace(self):
        result = analyze(square_wave(), Case(duration=.6, settle=.1))
        self.assertLess(result["startup_ms"], 1)

    def test_stuck_and_small_ripple_are_rejected(self):
        for scale in (0, .1):
            rows = [(t, v*scale, i, p) for t, v, i, p in square_wave()]
            with self.assertRaisesRegex(ValueError, "Startup"):
                analyze(rows, Case(duration=.6, settle=.1))

    def test_startup_only_then_stopped_is_rejected(self):
        rows = [(t, v if t < .25 else 0, i, p) for t, v, i, p in square_wave()]
        with self.assertRaisesRegex(ValueError, "late cycles"):
            analyze(rows, Case(duration=.6, settle=.1))

    def test_truncated_nonfinite_and_reversed_time_fail(self):
        rows = square_wave()
        for invalid in (rows[:-10], [(0, math.nan, 0, 0)]+rows[1:], list(reversed(rows))):
            with self.assertRaises(ValueError):
                analyze(invalid, Case(duration=.6, settle=.1))

    def test_inverted_supply_current_is_rejected(self):
        rows = [(t, v, -i, -p) for t, v, i, p in square_wave()]
        with self.assertRaisesRegex(ValueError, "current"):
            analyze(rows, Case(duration=.6, settle=.1))

    def test_reset_clock_activity_is_rejected(self):
        rows = [(t, 3.3 if .003 <= t < .004 else v, i, p) for t, v, i, p in square_wave()]
        with self.assertRaisesRegex(ValueError, "reset"):
            analyze(rows, Case(duration=.6, settle=.1))

    def test_unknown_model_patch_is_rejected(self):
        with self.assertRaises(ValueError):
            prepare_resistor_model("unrecognized model revision")

    def test_checked_in_candidate_matches_generator(self):
        base = Path(__file__).resolve().parent
        self.assertEqual((base/"riscay_lf_osc_gf180.spice").read_text(), netlist())
        self.assertEqual(Design(**json.loads((base/"candidate.json").read_text())), Design())
        for bad in (replace(Design(), stages=4), replace(Design(), resistor_megohm=0),
                    replace(Design(), buffer_stack=0)):
            with self.assertRaises(ValueError):
                netlist(bad)


if __name__ == "__main__":
    unittest.main()
