# SPDX-License-Identifier: Apache-2.0
import copy
from pathlib import Path
import tempfile
import unittest

from gf180_physical import SC, SRAM
from repair_gf180_design import flat
from report_repair_area import lef_areas, summarize


class RepairAreaTest(unittest.TestCase):
    def setUp(self):
        def netlist(kinds):
            return dict(modules=dict(RiscayMcuDigital=dict(ports={},cells=dict(island=dict(
                type='Block',connections={},port_directions={}))),Block=dict(ports={},cells={
                n:dict(type=k,connections={},port_directions={}) for n,k in kinds.items()})))
        self.a=flat(netlist(dict(gate=SC+'buf_1',ram=SRAM)),'RiscayMcuDigital')['cells']
        self.b=flat(netlist(dict(gate=SC+'buf_2',ram=SRAM,reset=SC+'buf_1',
            riscay_output_feedback_0=SC+'buf_1',other=SC+'buf_1',tie=SC+'tiel')),'RiscayMcuDigital')['cells']
        self.proof=dict(added_buffers=['island/reset','island/riscay_output_feedback_0','island/other'],added_ties=['island/tie'])
        self.prep=dict(reset_buffers=[dict(buffer='island/reset')])
        self.lef={SC+'buf_1':10,SC+'buf_2':20,SC+'tiel':2,SRAM:100}
        self.lib=dict(self.lef);self.lib[SRAM]=150

    def result(self):return summarize(self.a,self.b,self.proof,self.prep,self.lib,self.lef)

    def test_separate_sram_views_and_every_hierarchical_leaf(self):
        result=self.result()
        self.assertAlmostEqual(result['lef_total_before_mm2'],110/1e6)
        self.assertAlmostEqual(result['lef_total_after_mm2'],152/1e6)
        self.assertAlmostEqual(result['liberty_total_before_mm2'],160/1e6)
        self.assertAlmostEqual(result['liberty_total_after_mm2'],202/1e6)
        self.assertAlmostEqual(result['logic_delta_mm2'],42/1e6)
        self.assertAlmostEqual(result['new_cell_area_mm2'],32/1e6)
        self.assertAlmostEqual(result['resize_delta_mm2'],10/1e6)
        self.assertEqual((result['original_cells'],result['repaired_cells']),(2,6))
        self.assertEqual({k:v['count'] for k,v in result['buffers'].items()},
            dict(native_reset=1,sram_clock=0,writer_feedback=1,openroad_other=1))

    def test_sram_driver_category_and_area(self):
        self.prep['sram_clock_buffers']=[dict(buffer='island/other')]
        result=self.result()
        self.assertEqual(result['buffers']['sram_clock'],dict(count=1,area_mm2=10/1e6))
        self.assertEqual(result['buffers']['openroad_other'],dict(count=0,area_mm2=0))
        self.assertAlmostEqual(result['logic_delta_mm2'],42/1e6)

    def test_preparation_categories_cannot_overlap_or_name_absent_cells(self):
        for name in ('island/reset','island/riscay_output_feedback_0','island/absent'):
            with self.subTest(name=name):
                self.prep['sram_clock_buffers']=[dict(buffer=name)]
                with self.assertRaisesRegex(ValueError,'REPAIR_AREA_PREPARATION_INVENTORY'):self.result()

    def test_missing_area_fails(self):
        del self.lef[SRAM]
        with self.assertRaisesRegex(ValueError,'REPAIR_AREA_MISSING_CELL'):self.result()

    def test_unaccounted_addition_fails(self):
        self.proof['added_buffers'].pop()
        with self.assertRaisesRegex(ValueError,'REPAIR_AREA_ADDITION_INVENTORY'):self.result()

    def test_changed_macro_inventory_fails(self):
        self.b['island/another_ram']=copy.deepcopy(self.b['island/ram'])
        self.proof['added_ties'].append('island/another_ram')
        with self.assertRaisesRegex(ValueError,'REPAIR_AREA_MACRO_CHANGED'):self.result()

    def test_lef_footprint_uses_size_and_rejects_ambiguity(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'macro.lef'
            path.write_text('MACRO memory\n  SIZE 3 BY 5 ;\nEND memory\n')
            self.assertEqual(lef_areas([path]),dict(memory=15))
            path.write_text('MACRO memory\n  SIZE 3 BY 5 ;\n  SIZE 4 BY 5 ;\nEND memory\n')
            with self.assertRaisesRegex(ValueError,'REPAIR_AREA_LEF_MACRO'):lef_areas([path])


if __name__=='__main__':unittest.main()
