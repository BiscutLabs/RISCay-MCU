# SPDX-License-Identifier: Apache-2.0
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from decimal import Decimal
from gf180_slew_policy import limit_view, verify_view, native_recipe_pins, classify, compose_reports, report_rows
from gf180_physical import SC, adapter
from gf180_control_roles import DATA, CONTROL


def binding(model, parameters, role=None):
    p = dict(model='ChiselAsync'+model+'_v1', parameters=parameters)
    cells, requirements = adapter(p, 1.404, role=role)
    return dict(model=p['model'], cells=cells.cells, requirements=requirements)


class SlewPolicy(unittest.TestCase):
    def test_database_buses_use_exact_schema_without_changing_bit_order(self):
        import copy
        from experiment_gf180_slew_policy import pack_database_graph
        ref=dict(modules=dict(RiscayMcuDigital=dict(ports={'data':dict(direction='input',bits=[1,2])},
            cells={'macro':dict(type=SC+'fixture',connections={'A':[1,2]},port_directions={'A':'input'})})))
        db=dict(modules=dict(RiscayMcuDigital=dict(ports={
            'data[1]':dict(direction='input',bits=[22]),'data[0]':dict(direction='input',bits=[11])},
            cells={'macro':dict(type=SC+'fixture',connections={'A[1]':[22],'A[0]':[11]},
                                port_directions={'A[1]':'input','A[0]':'input'})})))
        packed=pack_database_graph(db,ref)['modules']['RiscayMcuDigital']
        self.assertEqual(packed['ports']['data']['bits'],[11,22])
        self.assertEqual(packed['cells']['macro']['connections']['A'],[11,22])
        bad=copy.deepcopy(db);del bad['modules']['RiscayMcuDigital']['ports']['data[1]']
        with self.assertRaisesRegex(ValueError,'PIN_SCHEMA'):pack_database_graph(bad,ref)
        bad=copy.deepcopy(db);bad['modules']['RiscayMcuDigital']['cells']['macro']['port_directions']['A[1]']='output'
        with self.assertRaisesRegex(ValueError,'PIN_DIRECTION'):pack_database_graph(bad,ref)

    def test_fresh_reporting_runs_both_contexts_twice_and_rejects_changed_repeat(self):
        import experiment_gf180_slew_policy as experiment
        for fault in (False,True):
            with self.subTest(fault=fault),TemporaryDirectory() as directory:
                out=Path(directory);calls=[]
                row='max slew\nparent/Z 2 3 -1 (VIOLATED)\n'
                for c in experiment.CORNERS:
                    for label in ('ordinary','native'):(out/f'after-{label}-{c}.rpt').write_text(row)
                runtime=SimpleNamespace(path=str,command=lambda args,**kw:args)
                def run(args,stdout,**kwargs):
                    script=Path(args[-1]);label=script.stem.removeprefix('report-');calls.append(label)
                    self.assertIn('COMMON_CORNER_VIEWS',script.read_text())
                    text=row if not fault or calls.count(label)==1 else row.replace('2 3 -1','2 4 -2')
                    for c in experiment.CORNERS:(out/f'fresh-{label}-{c}.rpt').write_text(text)
                    stdout.write('SLEW_REPORT_COMPLETE\n')
                with patch.object(experiment.subprocess,'run',side_effect=run):
                    if fault:
                        with self.assertRaisesRegex(ValueError,'NOT_REPRODUCIBLE'):
                            experiment.fresh_reports(out,runtime,['COMMON_CORNER_VIEWS'],out/'helper.tcl')
                    else:
                        result=experiment.fresh_reports(out,runtime,['COMMON_CORNER_VIEWS'],out/'helper.tcl')
                        self.assertEqual(calls,['ordinary','ordinary','native','native'])
                        self.assertEqual(len(result),2)

    def test_only_numeric_electrical_limits_change(self):
        source = b'time_unit : 1ns; max_transition : 15.6 ; default_max_transition: 1e1;\nvalues("15.6, 10");'
        candidate, edits = limit_view(source)
        self.assertEqual(candidate, b'time_unit : 1ns; max_transition : 12.48 ; default_max_transition: 8;\nvalues("15.6, 10");')
        self.assertEqual(len(edits), 2)
        verify_view(source, candidate)
        with self.assertRaisesRegex(ValueError, 'CHANGED_CHARACTERIZATION'):
            verify_view(source, candidate.replace(b'15.6, 10', b'12.48, 10'))
        with self.assertRaisesRegex(ValueError, 'CHANGED_CHARACTERIZATION'):
            verify_view(source, candidate.replace(b'12.48', b'13'))

    def test_all_five_corner_limits_keep_a_fraction(self):
        for limit in ('5.2','7.4','8.6','11','15.6'):
            text = f'time_unit: 1ns; max_transition: {limit};'.encode()
            _, edits = limit_view(text)
            self.assertEqual(Decimal(edits[0]['after']), Decimal(limit)*Decimal('.8'))

    def test_invalid_limit_policy_rejected(self):
        for fraction in (Decimal(0), Decimal(1), Decimal(2)):
            with self.assertRaisesRegex(ValueError,'SLEW_FRACTION'):
                limit_view(b'time_unit: 1ns; max_transition: 2;', fraction)
        for source in (b'time_unit: 1ns;', b'time_unit: 1ns; max_transition: 0;'):
            with self.assertRaises(ValueError): limit_view(source)

    def test_comments_strings_and_time_units_are_not_limit_attributes(self):
        source=b'time_unit: 1ns; /* max_transition: 99; */ value("max_transition: 77;");\nmax_transition: 10;'
        changed,_=limit_view(source)
        self.assertIn(b'/* max_transition: 99; */ value("max_transition: 77;");',changed)
        self.assertTrue(changed.endswith(b'max_transition: 8.0;'))
        continued=source+b' values("1, \\\n 2, max_transition: 77;");'
        self.assertEqual(limit_view(continued)[0],changed+b' values("1, \\\n 2, max_transition: 77;");')
        for text in (source.replace(b'1ns',b'1ps'),source+b' /* unclosed',source.replace(b'10;',b'bad;')):
            with self.assertRaises(ValueError):limit_view(text)

    def test_reports_select_exact_classes_and_keep_capacitance_separate(self):
        a='max slew\nordinary/D 6 7 -1 (VIOLATED)\nnative/Z 6 7 -1 (VIOLATED)\nmax capacitance\nordinary/Z 1 2 -1 (VIOLATED)\n'
        b='max slew\nordinary/D 2 7 -5 (VIOLATED)\nnative/Z 2 7 -5 (VIOLATED)\nmax capacitance\nordinary/Z 1 2 -1 (VIOLATED)\n'
        inventory=dict(native_pins=['native/Z'],ordinary_pins=['ordinary/D','ordinary/Z'])
        rows=compose_reports(a,b,inventory)
        self.assertEqual([(r['pin'],r['limit'],r['unit']) for r in rows],
                         [('ordinary/Z',1.,'pF'),('ordinary/D',6.,'ns'),('native/Z',2.,'ns')])
        for bad in (b.replace('native/Z','unknown/Z'),b.replace('native/Z 2 7 -5','native/Z 3 7 -4'),
                    b.replace('ordinary/Z 1 2 -1','ordinary/Z 1 3 -2'),
                    b.replace('native/Z 2 7 -5 (VIOLATED)\n',''),
                    b.replace('ordinary/D 2 7 -5','ordinary/D 2 8 -6')):
            with self.assertRaises(ValueError):compose_reports(a,bad,inventory)
        for bad in ('unexpected output',a+'ordinary/Z changed (VIOLATED)\n',a+a):
            with self.assertRaises(ValueError):report_rows(bad)

    def test_storage_payload_is_ordinary_but_capture_reset_are_native(self):
        for model in ('EventRegister','ClosingLatch'):
            b = binding(model, {'WIDTH':33,'RESET_VALUE':0})
            selected = set(native_recipe_pins(b))
            for c in b['cells']:
                for pin in c['pins']:
                    name = c['name']+'/'+pin
                    if pin in ('D','Q'): self.assertNotIn(name,selected)
                    if pin in ('E','CLK','RN','SETN'): self.assertIn(name,selected)

    def test_data_allowance_reset_stays_native(self):
        params = dict(WIDTH=33, OP=0, RESET_VALUE=0, DELAY_FS=10000000)
        b = binding('ControlGate',params,DATA)
        selected = set(native_recipe_pins(b))
        for c in b['cells']:
            for pin,net in c['pins'].items():
                if net.startswith(('a[','q[')): self.assertNotIn(c['name']+'/'+pin, selected)
            if c['cell']==SC+'and2_1': self.assertIn(c['name']+'/A2',selected)
        control = binding('ControlGate',params,CONTROL)
        self.assertEqual(len(native_recipe_pins(control)),sum(len(c['pins']) for c in control['cells']))
        b['requirements']['role'] = 'guessed'
        with self.assertRaisesRegex(ValueError,'UNKNOWN_NATIVE_RECIPE'):native_recipe_pins(b)

    def test_new_buffers_and_shared_receipt_promote_the_entire_control_net(self):
        def cell(kind, connections):return dict(type=SC+kind,connections={p:[n] for p,n in connections.items()})
        graph=dict(cells={
            'source':cell('buf_4',dict(I=1,Z=2)),
            'inserted':cell('buf_8',dict(I=2,Z=3)),
            'native':cell('and2_1',dict(A1=3,A2=4,Z=5)),
            'receipt':cell('dffrnq_1',dict(D=3,CLK=6,RN=7,Q=8)),
            'ordinary':cell('buf_1',dict(I=8,Z=9))})
        got=classify(graph,['native/A1'])
        self.assertIn('source/I',got['native_pins'])
        self.assertIn('inserted/Z',got['native_pins'])
        self.assertIn('receipt/D',got['native_pins'])
        self.assertIn('receipt/Q',got['ordinary_pins'])
        self.assertIn('ordinary/Z',got['ordinary_pins'])
        self.assertEqual(got['native_nets'],{1,2,3})
        with self.assertRaisesRegex(ValueError,'NATIVE_PIN_MISSING'): classify(graph,['native/missing'])

    def test_top_level_payload_driver_keeps_boundary_limit(self):
        graph=dict(cells={'observation':dict(type=SC+'dffrnq_1',connections={'Q':[1],'CLK':[2]})},
                   ports={'sdaLow':dict(bits=[1])})
        self.assertIn('observation/Q',classify(graph,['observation/CLK'])['native_pins'])

    def test_macro_buses_remain_in_the_complete_pin_inventory(self):
        from gf180_physical import SRAM
        graph=dict(cells={'macro':dict(type=SRAM,connections={'CLK':[1],'A':[2,3], 'D':[4,5], 'Q':[6,7]})})
        result=classify(graph,['macro/CLK'])
        self.assertEqual(result['native_pins'],['macro/CLK'])
        self.assertEqual(result['ordinary_pins'],['macro/A[0]','macro/A[1]','macro/D[0]',
                                                  'macro/D[1]','macro/Q[0]','macro/Q[1]'])


if __name__=='__main__':unittest.main()
