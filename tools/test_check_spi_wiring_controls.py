# SPDX-License-Identifier: Apache-2.0
"""Fail-closed binding controls; hardware mutations use the unchanged wire oracle."""
import tempfile
from pathlib import Path
import unittest

from check_spi_wiring_controls import NATIVE_FIELDS, group, strict_cases, wire_cases


PLAYER = """
  wire [31:0] _GEN = {27'h0, slot};
  wire        _GEN_1 = playing & divider;
  wire        _GEN_2 = recipe_occupied >> _GEN == 32'h1;
  wire [31:0] _cs_T = recipe_csN >> _GEN;
  wire [31:0] _clockLevel_T = recipe_sclk >> _GEN;
  if (reset) slot <= 5'h0;
  if (_GEN_0) // actual offer
    slot <= 5'h0;
  slot <= slot + 5'h1;
  playing <= ~_GEN_3 & (_GEN_0 ? (|recipe_occupied) : playing);
  cs <= _cs_T[0];
  clockLevel <= _clockLevel_T[0];
  cs <= recipe_initialCsN;
  clockLevel <= recipe_initialSclk;
  samples <= {miso, samples[31:1]};
""" + ''.join(f'.program_{field}(recipe_{field})\n' for field, _, _, _ in NATIVE_FIELDS)


class WiringBindings(unittest.TestCase):
    def test_each_wire_fault_changes_one_actual_site_and_preserves_reset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'SpiAdc.sv').write_text(PLAYER)
            cases = wire_cases(root)
            self.assertEqual(len(cases), 10)
            self.assertEqual(len({c['family'] for c in cases}), 10)
            messages = sorted({c['fatal_sites'][0]['format'] for c in cases})
            (root / 'testbench.sv').write_text('\n'.join(f'$fatal(1,"{m}");' for m in messages))
            self.assertEqual(group(root, 'bd', 'wire')['timeout_seconds'], 900)
            for fault in cases:
                self.assertEqual(PLAYER.count(fault['old']), 1)
                self.assertNotEqual(fault['old'], fault['new'])
                self.assertNotIn('reset', fault['old'])
            slot = next(c for c in cases if c['family'] == 'slot-load')
            changed = PLAYER.replace(slot['old'], slot['new'])
            self.assertIn("if (reset) slot <= 5'h0;", changed)
            self.assertIn("slot <= 5'h1;", changed)

    def test_missing_or_duplicate_binding_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for old in ('cs <= _cs_T[0];', '.program_occupied(recipe_occupied)',
                        "slot <= slot + 5'h1;", 'samples <= {miso, samples[31:1]};'):
                for changed in (PLAYER.replace(old, ''), PLAYER + old):
                    (root / 'SpiAdc.sv').write_text(changed)
                    with self.assertRaises(ValueError):
                        wire_cases(root)

    def test_native_constant_controls_preserve_all_five_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = '\n'.join(f"assign program_{f} = {w}'h{v:X};" for f, w, v, _ in NATIVE_FIELDS)
            for variant, module in (('bd', 'FourPhaseSpiAdc'), ('click', 'ClickSpiAdc')):
                (root / (module + '.sv')).write_text(source)
                cases = strict_cases(root, variant)
                self.assertEqual(len(cases), 5)
                (root / 'contract_probe.sv').write_text('\n'.join(
                    f'$fatal(1,"MCU_SPI_PROGRAM_VALUE:{field}");' for field, _, _, _ in NATIVE_FIELDS))
                self.assertEqual(group(root, variant, 'strict')['timeout_seconds'], 3600)
                for case, (field, _, _, _) in zip(cases, NATIVE_FIELDS):
                    self.assertEqual(case['fatal_sites'][0]['format'], 'MCU_SPI_PROGRAM_VALUE:' + field)
                    self.assertEqual(source.count(case['old']), 1)
                    self.assertEqual(source.count(case['new']), 0)
                (root / (module + '.sv')).write_text(source.replace("32'hFFFFFFFF", "32'h7FFFFFFF"))
                with self.assertRaises(ValueError):
                    strict_cases(root, variant)


if __name__ == '__main__':
    unittest.main()
