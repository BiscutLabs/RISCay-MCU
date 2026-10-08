# SPDX-License-Identifier: Apache-2.0
"""Independent dimensional/arithmetic and fail-closed controls for cost estimates."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.gf180_estimate import (cell_metrics, direct_groups, equivalent_primitives,
    interpolate, library, mapping_inventory, pin_cycle, read_activity, table_value, verify_hash)


class Gf180EstimateTest(unittest.TestCase):
    def test_input_hash_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"input"; path.write_bytes(b'abc')
            expected='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
            verify_hash(path,expected)
            path.write_bytes(b'abd')
            with self.assertRaisesRegex(ValueError,"INPUT_HASH_MISMATCH"): verify_hash(path,expected)

    def test_linear_and_bilinear_tables(self):
        self.assertEqual(interpolate([0,2],[2,6],1),4)
        # Independent plane z=2*x+3*y: at (1,2) result is 8.
        body='index_1("0,2"); index_2("0,4"); values("0,12", "4,16");'
        self.assertEqual(table_value(body,1,2),8)
        self.assertEqual(table_value('values("0.75");'),0.75)
        with self.assertRaisesRegex(ValueError,"INVALID_2D_TABLE"):
            table_value('index_1("0,2"); index_2("0,4"); values("0,12");')

    def test_cycle_energy_adds_rise_and_fall_once(self):
        body='internal_power() { rise_power(scalar) { values("2"); } fall_power(scalar) { values("3"); } }'
        self.assertEqual(pin_cycle(body),5)
        # Mutually exclusive conditions are averaged, never summed.
        self.assertEqual(pin_cycle(body+body.replace('"2"','"6"')),7)

    def test_nested_test_pins_do_not_overwrite_real_pins(self):
        body='pin(CLK) { capacitance : 0.25; } test_cell() { pin(CLK) { direction : input; } }'
        self.assertEqual(dict(direct_groups(body,"pin")),{"CLK":" capacitance : 0.25; "})

    def test_cell_units_and_condition_envelope(self):
        body='''area : 10;
        leakage_power() { when : "D"; value : "0.0002"; }
        leakage_power() { when : "!D"; value : "0.0004"; }
        leakage_power() { value : "99"; }
        pin(CLK) { clock : true; direction : input; capacitance : 0.003;
          internal_power() { rise_power(scalar) { values("0.1"); } fall_power(scalar) { values("0.2"); } } }
        pin(D) { direction : input; capacitance : 0.002; }
        '''
        m=cell_metrics(body)
        self.assertAlmostEqual(m["leak_mean_uw"],0.0003)
        self.assertAlmostEqual(m["clock_internal_pj"]+m["clock_cap_pf"]*3.3**2,0.33267)
        self.assertEqual(m["data_cap_pf"],0.002)

    def test_header_only_and_wrong_unit_libraries_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"lib.lib"
            header='leakage_power_unit : 1uW; time_unit : 1ns; capacitive_load_unit(1, pf); current_unit : 1mA; voltage_unit : 1V;'
            path.write_text(header)
            with self.assertRaisesRegex(ValueError,"EMPTY_LIBRARY"): library(path)
            path.write_text(header.replace("1uW","1nW")+'cell(x) { area : 1; }')
            with self.assertRaisesRegex(ValueError,"UNSUPPORTED_LEAKAGE_UNIT"): library(path)

    def test_primitive_unknown_and_budget_sensitivity(self):
        items=[dict(model="ChiselAsyncControlGate_v1",parameters=dict(WIDTH="1",OP="0",RESET_VALUE="0")),
               dict(model="ChiselAsyncAsymmetricC_v1",parameters=dict(COMMON_INVERT="0",RISING_INVERT="0",FALLING_INVERT="0"))]
        a,_,guards,cs=equivalent_primitives(items)
        b,_,_,_=equivalent_primitives(items,64,12)
        self.assertEqual((guards,cs),(1,1))
        self.assertEqual(sum(b.values())-sum(a.values()),70)
        with self.assertRaisesRegex(ValueError,"UNKNOWN_ASYNC_PRIMITIVE"):
            equivalent_primitives([dict(model="UnqualifiedCell",parameters={})])

    def test_mixed_reset_values_preserve_all_storage(self):
        cells,*_=equivalent_primitives([dict(model="ChiselAsyncEventRegister_v1",parameters=dict(WIDTH="4",RESET_VALUE="5"))])
        self.assertEqual(cells["gf180mcu_fd_sc_mcu7t5v0__dffrnq_1"],2)
        self.assertEqual(cells["gf180mcu_fd_sc_mcu7t5v0__dffsnq_1"],2)

    def test_activity_requires_nonzero_completed_equal_work(self):
        # Alternate log order deliberately: monitors run at the same event.
        blocks=['ASYNC,0,0,0\nWAKE,1,20,8,0,0,1647\n',
                'WAKE,1,183,181,0,1,15272\nASYNC,0,0,0\n',
                'WAKE,2,470,468,43,0,39189\nASYNC,1184,37944,0\n']
        text=''.join(blocks*2)+'ESTIMATE_ACTIVITY_COMPLETE\nRISCAY_SOC_PASS\n'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"activity.log"; path.write_text(text)
            self.assertEqual(read_activity(path)["firmware"]["latch_bits"],37944)
            for bad,error in ((text.replace('RISCAY_SOC_PASS',''),'MISSING_ACTIVITY_COMPLETION'),
                              (text.replace('20,8','0,0'),'EMPTY_WAKE'),
                              (text.replace('468,43','468,42'),'WORKLOAD_RETIREMENT_CHANGED'),
                              (text.replace('ASYNC,1184,37944,0',''),'MISSING_ASYNC_ACTIVITY')):
                path.write_text(bad)
                with self.assertRaisesRegex(ValueError,error): read_activity(path)

    def test_unmapped_and_missing_clock_cells_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"mapped.json"
            module=dict(ports={"clk":{"bits":[2]}},cells={"u":{"type":"unknown","connections":{}}})
            path.write_text(json.dumps({"modules":{"riscay_reset_hold":module}}))
            with self.assertRaisesRegex(ValueError,"UNMAPPED_DIGITAL_CELL"):
                mapping_inventory(path,"riscay_reset_hold",{})
            module['cells']['u']=dict(type='ff',connections={'CLK':[9]})
            path.write_text(json.dumps({"modules":{"riscay_reset_hold":module}}))
            with self.assertRaisesRegex(ValueError,"UNKNOWN_CLOCK_DOMAIN"):
                mapping_inventory(path,"riscay_reset_hold",{'ff':{'clock_pin':'CLK'}})


if __name__=="__main__": unittest.main()
