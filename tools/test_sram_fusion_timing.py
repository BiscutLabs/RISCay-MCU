# SPDX-License-Identifier: Apache-2.0
"""Adversarial projection and arithmetic controls; no PDK required."""
from copy import deepcopy
import unittest
import sram_fusion_timing as s
from test_control_join_timing import fixture as join_fixture


def fixture(variant='bd'):
    owner=dict(reset=[1],out_req=[2],out_ack=[3],out_bits_left=[])
    fork=dict(reset=[1],in_req=[2],in_ack=[3],in_bits_result=['0']*32)
    start=10
    for field,width in dict(address=32,data=32,mask=4,write=1).items():
        bits=list(range(start,start+width));start+=width
        owner['out_bits_right_'+field]=bits;fork['in_bits_request_'+field]=bits
    issue=dict(reset=[1]);dest=dict(reset=[1])
    for branch,receiver,prefix in zip(('out_0','out_1') if variant=='bd' else ('left','right'),(issue,dest),('in','left')):
        for pin,bits in list(fork.items()):
            if not pin.startswith('in_'):continue
            port=branch+pin[2:];fork[port]=list(range(start,start+len(bits)));start+=len(bits)
            receiver[prefix+pin[2:]]=fork[port]
    return dict(cells={name:dict(connections=conn) for name,conn in zip(
        ('ca_child_owner','ca_child_lane_0_fork','ca_child_lane_0_issue','ca_child_lane_0_join'),(owner,fork,issue,dest))})


class FusionTests(unittest.TestCase):
    def test_both_native_fork_projections(self):
        for v in ('bd','click'):
            p=fixture(v);self.assertEqual(len(s.projection(p,v)),2)
            p['cells']['ca_child_owner']['connections']['out_bits_left']=[999]
            s.projection(p,v)

    def test_lane_exchange_and_zero_change_fail(self):
        for field in ('address','data','mask'):
            p=fixture();a=p['cells']['ca_child_lane_0_fork']['connections']['in_bits_request_'+field]
            p=deepcopy(p);p['cells']['ca_child_lane_0_fork']['connections']['in_bits_request_'+field]=list(reversed(a))
            with self.assertRaisesRegex(ValueError,'SRAM_FUSION_PROJECTION_LANES'):s.projection(p,'bd')
        p=fixture();p['cells']['ca_child_lane_0_fork']['connections']['in_bits_result'][31]='1'
        with self.assertRaisesRegex(ValueError,'SRAM_FUSION_RESULT_ZERO'):s.projection(p,'bd')

    def test_either_branch_request_ack_and_payload_must_match(self):
        for v in ('bd','click'):
            for name,prefix in (('ca_child_lane_0_issue','in'),('ca_child_lane_0_join','left')):
                for suffix in ('_req','_ack','_bits_request_data','_bits_result'):
                    with self.subTest(variant=v,branch=name,signal=suffix):
                        p=fixture(v);p['cells'][name]['connections'][prefix+suffix]=[999]
                        with self.assertRaisesRegex(ValueError,'SRAM_FUSION_BRANCH_WIRING'):s.projection(p,v)

    def test_extra_fields_prepare_or_changed_handshake_fail(self):
        p=fixture();p['cells']['ca_child_prepare']={}
        with self.assertRaisesRegex(ValueError,'SRAM_FUSION_CHILDREN'):s.projection(p,'bd')
        p=fixture();p['cells']['ca_child_lane_0_fork']['connections']['in_bits_extra']=[999]
        with self.assertRaisesRegex(ValueError,'SRAM_FUSION_PROJECTION_FIELDS'):s.projection(p,'bd')
        for pin in ('out_req','out_ack'):
            p=fixture();p['cells']['ca_child_owner']['connections'][pin]=[999]
            with self.assertRaisesRegex(ValueError,'SRAM_FUSION_OWNER_HANDSHAKE'):s.projection(p,'bd')

    def test_right_operand_uses_real_launch_bounds(self):
        for v in ('bd','click'):
            p,r=join_fixture(v)
            expected=[x for x in s.join.margins(r,p,dict(setup_ns=1,hold_ns=0)) if x['side']=='right']
            for row in expected:row['return_after_latest_capture_hold_ns']=1 if v=='bd' else None
            self.assertEqual(s.source_margins(r,p,dict(setup_ns=1,hold_ns=0)),expected)
            # Credit data is architecturally unused; its data rows cannot
            # contribute fictitious setup credit to the retained request.
            r['left-input']['rows']={}
            self.assertEqual(s.source_margins(r,p,dict(setup_ns=1,hold_ns=0)),expected)

    def test_slew_provenance_cannot_be_substituted(self):
        p,r=join_fixture();r['right-launch-0']['source_slews']['0']=[.01,.01]
        with self.assertRaisesRegex(ValueError,'SRAM_FUSION_DQ_SLEW'):s.source_margins(r,p,dict(setup_ns=1,hold_ns=0))
        p,r=join_fixture('click');r['right-launch-0']['event_slews']=[.01,.01]
        with self.assertRaisesRegex(ValueError,'SRAM_FUSION_EVENT_SLEW'):s.source_margins(r,p,dict(setup_ns=1,hold_ns=0))

    def test_both_return_orders_use_latest_capture_and_real_hold(self):
        p,r=join_fixture();r['left-request-0']['rows']['capture:0:max:fall']['delay_ns']=34
        rows=s.return_ordering(r,p,dict(hold_ns=.25))
        self.assertEqual([x['zero_contamination_hold_margin_ns'] for x in rows],[-1.25,.75])
        p,r=join_fixture('click');self.assertEqual(s.return_ordering(r,p,dict(hold_ns=.25)),[])


if __name__=='__main__':unittest.main()
