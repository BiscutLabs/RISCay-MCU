# SPDX-License-Identifier: Apache-2.0
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('guard_variation',
    Path(__file__).resolve().parents[1]/'analog/gf180-guard-variation/characterize.py')
variation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(variation)


class VariationTest(unittest.TestCase):
    def test_both_ratio_tails_must_fit_the_derate(self):
        self.assertLess(variation.envelope([0.99, 1.01])['required_symmetric_derate'], 0.20)
        for ratios in ([1.6, 1.01], [0.6, 1.01]):
            self.assertGreater(variation.envelope(ratios)['required_symmetric_derate'], 0.20)
        for ratios in ([], [0], [float('nan')], [float('inf')]):
            with self.assertRaisesRegex(ValueError, 'INVALID_RATIO'):variation.envelope(ratios)

    def test_missing_nonfinite_and_negative_measurements_fail(self):
        names = ['delay_rise', 'delay_fall', 'logic_rise', 'logic_fall']
        good = ''.join(f'{name} = 2.5e-9 targ=1\n' for name in names)
        self.assertEqual(set(variation.measurements(good)), set(names))
        for bad in ('', good+good, good.replace('2.5e-9', 'nan'), good.replace('2.5e-9', '-1')):
            with self.assertRaises(ValueError):variation.measurements(bad)


if __name__ == '__main__':unittest.main()
