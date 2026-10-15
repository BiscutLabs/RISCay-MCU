# SPDX-License-Identifier: Apache-2.0
"""Pure canonical topology controls; actual owner graphs run separately."""
import copy
import unittest
from quiescing_request_hold_proof import owner_signature, prove_request_hold


class NativeHoldTopologyTest(unittest.TestCase):
    def fixture(self):
        m=dict(netnames={'owner.reset':dict(bits=[2]),'owner.input':dict(bits=[3]),
                         'owner.output':dict(bits=[5])},cells={
            'owner.payload':dict(type='ChiselAsyncEventRegister_v1',parameters=dict(WIDTH='1',DELAY_FS='101'),
                port_directions=dict(reset='input',trigger='input',d='input',q='output'),
                connections=dict(reset=[2],trigger=[4],d=[3],q=[5])),
            '$generated/path:999':dict(type='$not',parameters=dict(A_WIDTH='1',Y_WIDTH='1'),
                port_directions=dict(A='input',Y='output'),connections=dict(A=[5],Y=[4]))})
        return dict(modules=dict(Top=m))

    def signature(self,d):return owner_signature(d,'Top','owner',['reset','input'],['output'])

    def test_native_feedback_is_finite_but_complete_inputs_are_bound(self):
        d=self.fixture();before=self.signature(d)
        for pin in ('reset','trigger','d'):
            changed=copy.deepcopy(d);changed['modules']['Top']['cells']['owner.payload']['connections'][pin]=['0']
            self.assertNotEqual(self.signature(changed)['sha256'],before['sha256'],pin)

    def test_parameters_and_native_identity_are_bound(self):
        d=self.fixture();before=self.signature(d)
        for change in ('parameter','identity','model','direction'):
            changed=copy.deepcopy(d);cells=changed['modules']['Top']['cells'];p=cells['owner.payload']
            if change=='parameter':p['parameters']['DELAY_FS']='110'
            elif change=='identity':cells['owner.other']=cells.pop('owner.payload')
            elif change=='model':p['type']='ChiselAsyncClosingLatch_v1'
            else:p['port_directions']['d']='output'
            try:after=self.signature(changed)['sha256']
            except ValueError:continue
            self.assertNotEqual(after,before['sha256'],change)

    def test_generated_names_paths_and_bit_numbers_do_not_change_signature(self):
        d=self.fixture();before=self.signature(d)
        m=d['modules']['Top'];m['cells']['$other/export/path:12345']=m['cells'].pop('$generated/path:999')
        for net in m['netnames'].values():net['bits']=[b+100 if isinstance(b,int) else b for b in net['bits']]
        for cell in m['cells'].values():
            cell['connections']={p:[b+100 if isinstance(b,int) else b for b in bits] for p,bits in cell['connections'].items()}
        self.assertEqual(self.signature(d),before)

    def test_additional_native_state_cannot_disappear_from_binding(self):
        d=self.fixture();before=self.signature(d)
        d['modules']['Top']['cells']['owner.extra']=dict(type='ChiselAsyncPhaseRegister_v1',parameters={},
            port_directions=dict(reset='input',trigger='input',q='output'),connections=dict(reset=[2],trigger=[3],q=[8]))
        self.assertNotEqual(self.signature(d)['sha256'],before['sha256'])

    def test_unbound_or_periodic_owner_is_not_a_native_lifetime_proof(self):
        for change in ('input','periodic','cycle'):
            d=self.fixture();m=d['modules']['Top']
            if change=='input':m['cells']['owner.payload']['connections']['d']=[99]
            elif change=='periodic':m['cells']['$generated/path:999']['type']='$adff'
            else:m['cells']['$generated/path:999']['connections']['A']=[4]
            with self.assertRaisesRegex(ValueError,'RDC_QUIESCING_HOLD_(UNBOUND_OR_CYCLIC|FOREIGN_OR_CLOCKED)_OWNER'):
                self.signature(d)

    def test_boundary_alias_and_lane_changes_are_not_ignored(self):
        d=self.fixture();m=d['modules']['Top'];m['netnames']['owner.input']['bits']=[2]
        with self.assertRaisesRegex(ValueError,'RDC_QUIESCING_HOLD_ALIASED_OWNER_INPUT'):
            self.signature(d)

    def test_capacity_identity_is_explicit_not_inferred_from_owner(self):
        for top,caps in [('FourPhaseSoc',{'program':64,'ram':32}),
                         ('BdResetBoundarySocFixture',{'program':2048,'ram':1024}),
                         ('ClickSoc',None),('ClickSoc',{'program':True,'ram':1024})]:
            with self.assertRaisesRegex(ValueError,'RDC_QUIESCING_HOLD_REVIEWED_CAPACITIES'):
                prove_request_hold({},top,caps)


if __name__=='__main__':unittest.main()
