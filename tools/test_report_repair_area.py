# SPDX-License-Identifier: Apache-2.0
import copy
from pathlib import Path
import tempfile
import unittest

from gf180_physical import SC, SRAM
from repair_gf180_design import flat
from report_repair_area import adapter_costs, lef_areas, summarize


class RepairAreaTest(unittest.TestCase):
    def test_adapter_categories_and_dlyd_are_not_added_twice(self):
        cells={n:dict(type=SC+k) for n,k in (
            ('guard/delay','dlyd_1'),('logic/gate','and2_1'),('data/buf','buf_1'))}
        areas={SC+'dlyd_1':75,SC+'and2_1':18,SC+'buf_1':13}
        def binding(name,role,kind,delay):
            return dict(model='Gate',requirements=dict(role=role),parameters=dict(DELAY_FS=delay),
                        instances=[name],cells=[dict(name=kind,cell=cells[name+'/'+kind]['type'])])
        mapping=dict(bindings=[binding('guard','matched-control-delay','delay',32000000),
            binding('logic','matched-control-delay','gate',1000000),
            binding('data','whole-transform-allowance','buf',10000000)])
        audit=dict(adapter_instances={n:n for n in ('guard','logic','data')},preserved_async_cells=3)
        result=adapter_costs(cells,mapping,audit,areas)
        self.assertAlmostEqual(result['matched_control_mm2'],93/1e6)
        self.assertAlmostEqual(result['guards_mm2'],75/1e6)
        self.assertAlmostEqual(result['functional_control_mm2'],18/1e6)
        self.assertAlmostEqual(result['allowances_mm2'],13/1e6)
        self.assertAlmostEqual(result['dlyd_mm2'],75/1e6)
        self.assertEqual(result['dlyd_cells'],1)
        purposes=adapter_costs(cells,mapping,audit,areas,{'guard':'ordering-publication'})
        self.assertEqual(purposes['dlyd_by_purpose'],
                         {'ordering-publication':dict(cells=1,area_mm2=75/1e6)})
        with self.assertRaisesRegex(ValueError,'AREA_LEDGER_DLYD_UNCLASSIFIED'):
            adapter_costs(cells,mapping,audit,areas,{})
        for changed in (dict(audit,preserved_async_cells=4),
                        dict(audit,adapter_instances=dict(guard='logic',logic='logic',data='data'))):
            with self.assertRaisesRegex(ValueError,'AREA_LEDGER_'):
                adapter_costs(cells,mapping,changed,areas)
        with self.assertRaisesRegex(ValueError,'AREA_LEDGER_ADAPTER_LEAF'):
            adapter_costs(cells,dict(bindings=mapping['bindings']+[mapping['bindings'][0]]),audit,areas)

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
            dict(native_reset=1,sram_clock=0,native_output=0,native_input=0,writer_feedback=1,openroad_other=1))
        self.prep['native_input_buffers']=[dict(buffer='island/other')]
        isolated=self.result()
        self.assertEqual(isolated['buffers']['native_input'],dict(count=1,area_mm2=10/1e6))
        self.assertEqual(isolated['buffers']['openroad_other'],dict(count=0,area_mm2=0))
        self.assertEqual(isolated['logic_after_mm2'],result['logic_after_mm2'])

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
