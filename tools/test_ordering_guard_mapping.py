# SPDX-License-Identifier: Apache-2.0
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from ordering_guard_mapping import specialize, rewrite_owner
from gf180_physical import adapter, CONTROL


class OrderingMappingSpec(unittest.TestCase):
    def fixture(self, directory):
        params=dict(WIDTH='1',OP='0',RESET_VALUE='0',DELAY_FS='31000000')
        primitive=dict(model='ChiselAsyncControlGate_v1',parameters=params,id='output_delay',
                       rtl_path='Top.one.guard',ports=[])
        one=dict(rtl_path='Top.one',module='FourPhaseStage',primitives=[primitive],children=[])
        two=deepcopy(one);two['rtl_path']='Top.two';two['primitives'][0]['rtl_path']='Top.two.guard'
        top=dict(rtl_path='Top',module='Top',primitives=[],children=[dict(contract=one),dict(contract=two)])
        (directory/'Top.sv').write_text('module Top(); Shared one(); Shared two(); endmodule')
        (directory/'Shared.sv').write_text('module Shared(); ChiselAsyncControlGate_v1 #(.WIDTH(1), .OP(0)) guard(); endmodule')
        row=dict(instance='Top.one.guard',owner='Top.one',owner_module='FourPhaseStage',primitive_id='output_delay',
                 original_parameters={k:int(v) for k,v in params.items()},stages=8,previous_stages=38,purpose='ordering-publication')
        policy=dict(schema='riscay-gf180-ordering-guards-v1',status='locally-measured',engineering_derate=.2,
                    residual_ns=2,statistical_qualification=False,variants={'bd':[row]})
        return dict(top='Top',design=top),{('unused',()):[primitive,two['primitives'][0]]},policy

    def test_shared_owner_preserves_unselected_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);manifest,groups,policy=self.fixture(path)
            _,_,_,applied=specialize(path,manifest,groups,policy,'bd',1.)
            self.assertEqual({r['stages'] for r in applied.values()},{38})
            second=deepcopy(policy['variants']['bd'][0]);second.update(instance='Top.two.guard',owner='Top.two',stages=12)
            policy['variants']['bd'].append(second)
            _,wrappers,rewrites,applied=specialize(path,manifest,groups,policy,'bd',1.)
            self.assertEqual({r['stages'] for r in applied.values()},{12})
            self.assertEqual(wrappers['ChiselAsyncControlGate_v1_RiscayStages_12']['stages'],12)
            rewritten=rewrite_owner((path/'Shared.sv').read_text(),rewrites['Shared.sv'])
            self.assertIn('RiscayStages_12 #(.WIDTH(1), .OP(0)) guard()',rewritten)

    def test_unaccepted_or_changed_obligation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);manifest,groups,policy=self.fixture(path)
            policy['status']='candidate-not-yet-accepted'
            with self.assertRaisesRegex(ValueError,'NOT_ACCEPTED'):
                specialize(path,manifest,groups,policy,'bd',1.)
            specialize(path,manifest,groups,policy,'bd',1.,candidate=True)
            policy['status']='locally-measured';policy['variants']['bd'][0]['purpose']='minimum-pulse-width'
            with self.assertRaisesRegex(ValueError,'FIXED_TIME_OR_UNREVIEWED_PURPOSE'):
                specialize(path,manifest,groups,policy,'bd',1.)

    def test_rewrite_cannot_consume_another_primitive(self):
        source='ChiselAsyncControlGate_v1 #(.WIDTH(1)) first(); ChiselAsyncControlGate_v1 #(.WIDTH(1)) second();'
        result=rewrite_owner(source,{'second':'Special'})
        self.assertTrue(result.startswith('ChiselAsyncControlGate_v1 #(.WIDTH(1)) first(); Special'))
        with self.assertRaisesRegex(ValueError,'PRIMITIVE_REWRITE'):
            rewrite_owner(source,{'absent':'Special'})

    def test_mislabeled_custom_cross_variant_or_wrong_id_rejected(self):
        for family,ident in [('ClickRecoveryReturn','output_delay'),
                             ('ClickStage','acknowledge_guard'),('FourPhaseStage','reset_guard')]:
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp);manifest,groups,policy=self.fixture(path)
                owner=manifest['design']['children'][0]['contract']
                owner['module']=family;owner['primitives'][0]['id']=ident
                policy['variants']['bd'][0].update(owner_module=family,primitive_id=ident)
                with self.assertRaisesRegex(ValueError,'FIXED_TIME_OR_UNREVIEWED_PURPOSE'):
                    specialize(path,manifest,groups,policy,'bd',1.)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);manifest,groups,policy=self.fixture(path)
            policy['residual_ns']=float('inf')
            with self.assertRaisesRegex(ValueError,'MISMATCH_POLICY'):
                specialize(path,manifest,groups,policy,'bd',1.)

    def test_physical_override_keeps_reset_and_exact_delay_count(self):
        p=dict(model='ChiselAsyncControlGate_v1',parameters=dict(WIDTH='1',OP='0',RESET_VALUE='0',DELAY_FS='31000000'))
        circuit,requirement=adapter(p,1.,role=CONTROL,guard_stages=8)
        self.assertEqual(sum(c['cell'].endswith('__dlyd_1') for c in circuit.cells),8)
        self.assertTrue(any('reset' in c['pins'].values() for c in circuit.cells))
        self.assertNotIn('control_min_ns',requirement)
        self.assertEqual(requirement['model_delay_fs'],31000000)
        p['parameters']['WIDTH']='2'
        with self.assertRaisesRegex(ValueError,'INVALID_ORDERING_GUARD_OVERRIDE'):
            adapter(p,1.,role=CONTROL,guard_stages=8)


if __name__=='__main__':unittest.main()
