# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import math
import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from area_ratio import storage_width, compare, check_budget, check_budget_history, context, CEILING, mutex_allowance
from audit_desync_protection import audit
from primitives import require_recipe, classified_cells, REGISTRY, Primitive
from size_desync_delays import select_count, load_recipe, publish_policy
from gf180_estimate import sha
from characterize_gf180_liberty import CORNERS
from test_global_repair import cell
from clocked_physical import check_clock_coverage, electrical_gate


class DesyncToolsTest(unittest.TestCase):
    def test_mutex_estimate_is_explicit_and_does_not_enable_mapping(self):
        self.assertGreater(mutex_allowance()['area_bound_mm2'], 0)
        self.assertLessEqual(mutex_allowance()['area_bound_mm2'], .001)
        self.assertIn('estimate', mutex_allowance()['status'])
        with self.assertRaisesRegex(ValueError,'PHYSICAL_RECIPE_UNAVAILABLE'):
            require_recipe('RiscayDesyncMutex')
    def test_ideal_region_cannot_satisfy_whole_chip_area_gate(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);netlist=root/'netlist.json';metadata=root/'desync.json'
            netlist.write_text('{}')
            metadata.write_text(json.dumps(dict(clocking='ideal-clock-region')))
            (root/'receipt.json').write_text(json.dumps(dict(status='pass',
                inputs=[str(metadata.resolve())],
                sha256={str(p.resolve()):sha(p) for p in (netlist,metadata)})))
            with self.assertRaisesRegex(ValueError,'DESYNC_INCOMPLETE_GENERATOR'):
                context(netlist)
            metadata.write_text(json.dumps(dict(clocking='multi-bank-bundled-data')))
            (root/'receipt.json').write_text(json.dumps(dict(status='pass',
                inputs=[str(metadata.resolve())],
                sha256={str(p.resolve()):sha(p) for p in (netlist,metadata)})))
            with self.assertRaisesRegex(ValueError,'DESYNC_BANK_IMPLEMENTATION_REQUIRED'):
                context(netlist)

    def test_real_report_violation_prevents_accepting_physical_reference(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            for c in CORNERS:(root/('cts-'+c+'-electrical.rpt')).write_text('')
            self.assertFalse(any(electrical_gate(root).values()))
            (root/('cts-'+CORNERS[0]+'-electrical.rpt')).write_text(
                'max slew\nPin Limit Slew Slack\nq/Q 2.0 3.0 -1.0 (VIOLATED)\n')
            with self.assertRaisesRegex(ValueError,'ELECTRICAL_VIOLATIONS'):electrical_gate(root)

    def test_committed_budget_loosening_is_not_compared_only_to_itself(self):
        with TemporaryDirectory() as temporary:
            path=Path(temporary)/'budget.json'
            parent=dict(mapped_ratio=1.10,repaired_tree_ratio=1.2,storage_ratio=1.05,control_area_fraction=.05)
            current=dict(CEILING,schema=2,mapped_ratio=1.12);path.write_text(json.dumps(current))
            with patch('area_ratio.subprocess.run',side_effect=[SimpleNamespace(returncode=0,stdout=json.dumps(current)),SimpleNamespace(returncode=0,stdout=json.dumps(parent))]):
                with self.assertRaisesRegex(ValueError,'BUDGET_LOOSENED'):check_budget_history(path)

    def test_loaded_chain_policy_requires_current_netlist_and_all_final_corners(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);netlist=root/'netlist.v';evidence=root/'measured.json'
            netlist.write_text('fixture netlist')
            measured=dict(netlist_sha256=sha(netlist),
                cell_mix=[dict(cell='and2_1',count=1),dict(cell='buf_1',count=1)],
                corners=[dict(corner=c,requirement_ns=10,unit_period_min_ns=1,
                    critical_path=['q/Q','d/D'],electrical_pass=True) for c in CORNERS],
                final_chain=[dict(corner=c,period_min_ns=12,electrical_pass=True,
                    count=12,netlist_sha256=sha(netlist),
                    cell_mix=[dict(cell='and2_1',count=1),dict(cell='buf_1',count=1)]) for c in CORNERS])
            evidence.write_text(json.dumps(measured))
            policy=publish_policy(netlist,evidence,'region',root/'policy.json')
            self.assertEqual(load_recipe(policy,'region',netlist,evidence)['count'],12)
            for mutate,diagnostic in ((lambda m:m.update(netlist_sha256='stale'),'STALE'),
                    (lambda m:m['final_chain'][0].update(period_min_ns=11),'TOO_SHORT'),
                    (lambda m:m['final_chain'][0].update(count=13),'IDENTITY'),
                    (lambda m:m['final_chain'][0].update(cell_mix=[]),'IDENTITY'),
                    (lambda m:m['final_chain'][0].update(netlist_sha256='stale'),'IDENTITY')):
                bad=deepcopy(measured);mutate(bad);evidence.write_text(json.dumps(bad))
                with self.assertRaisesRegex(ValueError,diagnostic):publish_policy(netlist,evidence,'region',root/'bad.json')
            policy['lines']['region']['kind']='absolute'
            with self.assertRaisesRegex(ValueError,'NOT_PHYSICAL'):load_recipe(policy,'region',netlist,evidence)

    def test_clock_coverage_requires_every_sink_and_its_actual_domain(self):
        expected=[dict(path='q',clock_pin='CLK',domain='work')]
        check_clock_coverage(expected,'work\trise\tq/CLK\nservice\trise\tq/CLK\n')
        for report in ('','service\trise\tq/CLK\n','work\trise\tother/CLK\n'):
            with self.assertRaises(ValueError):check_clock_coverage(expected,report)

    def test_delay_count_uses_same_corner_ratios_and_has_no_default(self):
        rows=[dict(corner=c,requirement_ns=10*(i+1),unit_period_min_ns=i+1,
                   critical_path=['q/Q','d/D'],electrical_pass=True) for i,c in enumerate(CORNERS)]
        self.assertEqual(select_count(rows)[0],12)
        # Mixing the slow requirement with the fast unit would instead give 60.
        with self.assertRaisesRegex(ValueError,'ENTRY_MISSING'):
            load_recipe({'schema':1,'lines':{}},'region',None,None)
        with self.assertRaisesRegex(ValueError,'CORNER_COVERAGE'): select_count(rows[:-1])
        rows[0]['electrical_pass']=False
        with self.assertRaisesRegex(ValueError,'UNQUALIFIED_PATH'):select_count(rows)

    def test_storage_is_liberty_state_not_cell_name(self):
        self.assertEqual(storage_width('ff(IQ,IQN){clocked_on:"CLK";}'),1)
        self.assertEqual(storage_width('latch(IQ,IQN){enable:"E";}'),1)
        self.assertEqual(storage_width('ff_bank(IQ,IQN,8){clocked_on:"CLK";}'),8)
        self.assertEqual(storage_width('pin(Q){function:"D";}'),0)

    def test_unqualified_generator_cannot_be_replaced_with_logic(self):
        for name in REGISTRY:
            with self.subTest(primitive=name):
                with self.assertRaisesRegex(ValueError,'PHYSICAL_RECIPE_UNAVAILABLE'):
                    require_recipe(name)
                with self.assertRaisesRegex(ValueError,'PHYSICAL_RECIPE_UNAVAILABLE'):
                    classified_cells([dict(primitive=name,ports=[],cells=[])])

    def test_ordinary_cell_net_and_module_protection_rejected(self):
        fixture=dict(modules={'RiscayMcuDigital':dict(ports={},netnames={},cells={'q':cell('dffq_1',D=1,CLK=2,Q=3)})})
        self.assertEqual(audit(fixture)['registered_cells'],0)
        for target in ('module','cell','net'):
            a=deepcopy(fixture);m=a['modules']['RiscayMcuDigital']
            if target=='module': m['attributes']={'keep':'1'}
            if target=='cell': m['cells']['q']['attributes']={'dont_touch':'1'}
            if target=='net': m['netnames']['D']={'bits':[1],'attributes':{'keep':'1'}}
            with self.assertRaisesRegex(ValueError,'DESYNC_PROTECTED'):audit(a)

    def test_registry_can_forbid_primitive_protection(self):
        gate=cell('and2_1',A1=1,A2=2,Z=3)
        child=dict(ports={p:dict(bits=[i],direction='output' if p=='z' else 'input') for p,i in [('a',1),('b',2),('z',3)]},
                   netnames={p:dict(bits=[i]) for p,i in [('a',1),('b',2),('z',3)]},cells={'gate':gate})
        top=dict(ports={},netnames={},cells={'native':dict(type='Fixture',connections=dict(a=[1],b=[2],z=[3]))})
        fixture=dict(modules={'RiscayMcuDigital':top,'Fixture':child})
        binding=dict(instance='native',primitive='Fixture',ports=dict(a='a',b='b',z='z'),
                     cells=[dict(name='gate',cell=gate['type'],pins=dict(A1='a',A2='b',Z='z'))])
        entry=Primitive('controller',('a','b','z'),('relative',),'none','unit fixture',protect=())
        with patch.dict(REGISTRY,{'Fixture':entry}):
            self.assertEqual(audit(fixture,[binding])['protected_cells'],0)
            for target in ('cell','net','module'):
                bad=deepcopy(fixture);m=bad['modules']['Fixture']
                obj=m['cells']['gate'] if target=='cell' else m['netnames']['a'] if target=='net' else m
                obj['attributes']={'keep':'1'}
                with self.subTest(target=target), self.assertRaisesRegex(ValueError,'DESYNC_PROTECTED'):
                    audit(bad,[binding])

    def test_budget_may_only_tighten_and_must_be_finite(self):
        original=dict(CEILING)
        check_budget(original,original)
        for value in (1.16,math.inf,math.nan,0):
            candidate=dict(original,mapped_ratio=value)
            with self.assertRaisesRegex(ValueError,'BUDGET_LOOSENED'):check_budget(candidate,original)
        check_budget(dict(original,mapped_ratio=1.05),original)
        check_budget(original,dict(mapped_ratio=1.15,repaired_tree_ratio=1.2,storage_ratio=1.05,control_area_fraction=.05))
        for value in (.99,1.01):
            with self.assertRaisesRegex(ValueError,'BITS_MUST_MATCH'):
                check_budget(dict(original,architectural_bits_ratio=value),original)

    def test_ratio_is_same_library_and_macro_count_and_no_nan(self):
        reference=dict(logic_mm2=.5,storage_bits=100,architectural_bits=100,storage_area_mm2=.2,
                       liberty_sha256={'lib':'x'},sram_macros=3,special_area_mm2={})
        budget=dict(CEILING)
        self.assertEqual(compare(reference,reference,budget)['status'],'pass')
        self.assertEqual(compare(dict(reference,logic_mm2=.6),reference,budget)['exceeded'],['area'])
        self.assertEqual(compare(dict(reference,storage_area_mm2=.251),reference,budget)['exceeded'],['storage_area'])
        for count in (99,101):
            self.assertEqual(compare(dict(reference,architectural_bits=count),reference,budget)['exceeded'],['architectural_bits'])
        for candidate in (dict(reference,liberty_sha256={'lib':'y'}),dict(reference,sram_macros=2),dict(reference,logic_mm2=math.nan)):
            with self.assertRaises(ValueError):compare(candidate,reference,budget)


if __name__=='__main__':unittest.main()
