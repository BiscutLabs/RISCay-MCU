# SPDX-License-Identifier: Apache-2.0
"""Actual solver negative control, not a mocked success/log parser."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from equiv_desync import run


class EquivalenceControlTest(unittest.TestCase):
    def test_identical_fixed_macro_and_changed_input(self):
        with TemporaryDirectory() as temporary:
            folder=Path(temporary)
            gold=folder/'gold.v'; bad=folder/'bad.v'
            source=('module Mem(input clk,d,output q); endmodule\n'
                    'module T(input clk,d,output q); Mem m(.clk(clk),.d(d),.q(q)); endmodule\n')
            gold.write_text(source); bad.write_text(source.replace('.d(d)','.d(!d)'))
            run(gold,gold,folder/'pass','T')
            with self.assertRaises(ValueError):run(gold,bad,folder/'fail','T')
            self.assertIn('unproven $equiv',(folder/'fail/equiv.log').read_text())

    def test_edge_and_async_reset_model_rejects_wrong_next_state(self):
        with TemporaryDirectory() as temporary:
            folder=Path(temporary)
            gold=folder/'gold.v'; bad=folder/'bad.v'
            source='module T(input clk,reset,d,output reg q); always @(posedge clk or posedge reset) if(reset) q<=0; else q<=d; endmodule\n'
            gold.write_text(source); bad.write_text(source.replace('q<=d','q<=!d'))
            run(gold,gold,folder/'pass','T')
            with self.assertRaises(ValueError):run(gold,bad,folder/'fail','T')
            log=(folder/'fail/equiv.log').read_text()
            self.assertIn('unproven $equiv',log)
            self.assertNotIn('No SAT model available',log)
            reset=folder/'reset.v';reset.write_text(source.replace('q<=0','q<=1'))
            with self.assertRaises(ValueError):run(gold,reset,folder/'reset-fail','T')
            self.assertIn('unproven $equiv',(folder/'reset-fail/equiv.log').read_text())


if __name__=='__main__':unittest.main()
