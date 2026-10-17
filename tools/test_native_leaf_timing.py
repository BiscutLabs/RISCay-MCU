# SPDX-License-Identifier: Apache-2.0
"""Leaf provenance and evidence controls, independent of generated exports."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

import native_leaf_timing as leaf
import control_relative_timing as relative
from gf180_physical import SC


def fixture():
    def cell(kind, **pins):
        return dict(type=SC+kind, connections={p:[b] for p,b in pins.items()},
                    port_directions={p:'output' if p in ('Q','Z','ZN') else 'input' for p in pins})
    stage=dict(ports={p:dict(direction='input',bits=[b]) for p,b in
                      (('data',1),('unused',3),('constant',4))},
               cells=dict(payload=cell('latrnq_1',D=1,E=4,Q=2)))
    top=dict(ports={},cells=dict(source=cell('dffrnq_1',Q=10,CLK=11,D=12),
        sibling=cell('buf_1',I=10,Z=20),
        stage=dict(type='Stage',connections=dict(data=[10],unused=[13],constant=['0']),
                   port_directions={p:'input' for p in stage['ports']})))
    before=dict(modules=dict(RiscayMcuDigital=top,Stage=stage))
    after=deepcopy(before)
    after['modules']['RiscayMcuDigital']['cells']['branch']=cell('buf_2',I=10,Z=14)
    after['modules']['RiscayMcuDigital']['cells']['stage']['connections']['data']=[14]
    return before,after


class LeafGraphTests(unittest.TestCase):
    def test_parent_branch_keeps_original_root_and_all_fanout(self):
        before,after=fixture();index=leaf.LeafIndex(before,after,['branch'])
        row=index.boundary('stage','data')[0]
        self.assertEqual(row['source'],'source/Q')
        self.assertEqual(set(row['complete_fanout']),{'sibling/I','stage/payload/D'})
        self.assertIn('branch',index.after['cells'])
        self.assertEqual(index.boundary('stage','unused')[0]['kind'],'unused')
        self.assertEqual(index.boundary('stage','constant')[0]['value'],0)

    def test_unbuffered_sibling_must_remain_connected(self):
        before,after=fixture()
        after['modules']['RiscayMcuDigital']['cells']['sibling']['connections']['I']=[19]
        with self.assertRaisesRegex(ValueError,'LEAF_FANOUT_CHANGED'):
            leaf.LeafIndex(before,after,['branch']).boundary('stage','data')

    def test_removed_used_pin_is_never_unused(self):
        before,after=fixture()
        after['modules']['Stage']['cells']['payload']['connections']['D']=[5]
        with self.assertRaisesRegex(ValueError,'LEAF_FANOUT_CHANGED'):
            leaf.LeafIndex(before,after,['branch']).boundary('stage','data')

    def test_output_alias_is_not_unused(self):
        before,after=fixture()
        for design in (before,after):
            design['modules']['Stage']['ports']['alias']=dict(direction='output',bits=[3])
            design['modules']['RiscayMcuDigital']['cells']['stage']['connections']['alias']=[13]
        with self.assertRaisesRegex(ValueError,'LEAF_REFERENCE_DRIVER'):
            leaf.LeafIndex(before,after,['branch']).boundary('stage','unused')

    def test_constant_cannot_turn_into_dynamic_signal(self):
        before,after=fixture()
        after['modules']['RiscayMcuDigital']['cells']['stage']['connections']['constant']=[18]
        with self.assertRaisesRegex(ValueError,'LEAF_CONSTANT_CHANGED'):
            leaf.LeafIndex(before,after,['branch']).boundary('stage','constant')

    def test_inverting_branch_rejected(self):
        before,after=fixture()
        after['modules']['RiscayMcuDigital']['cells']['branch']['type']=SC+'inv_1'
        with self.assertRaisesRegex(ValueError,'LEAF_BUFFER_SHAPE'):
            leaf.LeafIndex(before,after,['branch'])


def ack_fixture():
    plan=dict(leaf_anchored=True,event='event/Z')
    ctx=dict(kind='common',sources=['event/Z'],root_slew_ns=dict(min=.2,max=.2),queries=[
        dict(id='ack:'+m,sink='receiver/I',role='ack',receiver_role='external-receiver',
             source_edge='rise',sink_edge='rise',mode=m) for m in ('min','max')])
    log='RELATIVE_BEGIN\n'
    for m in ('min','max'):
        log+=f'LEAF_ACK_PATH\tack:{m}\t0\t3\t3\t3\t.2\tevent/Z\treceiver/I\trise\trise\n'
        log+=f'LEAF_ACK_POINTS\tack:{m}\tevent/Z\treceiver/I\n'
    for m in ('min','max'):
        for e in ('rise','fall'):log+=f'LEAF_SOURCE_SLEW\t0\t{m}\t{e}\t.2\n'
    log+='RELATIVE_EVENT_SLEW\t.2\t.2\nRELATIVE_ELECTRICAL_BEGIN\nRELATIVE_ELECTRICAL_END\nRELATIVE_COMPLETE\n'
    index=SimpleNamespace(after=dict(cells={'receiver':dict(type=SC+'buf_1')}))
    return plan,ctx,log,index


class LeafEvidenceTests(unittest.TestCase):
    def test_local_hold_grants_no_source_or_transform_delay_credit(self):
        from test_control_relative_timing import arithmetic
        results,plan,aperture=arithmetic();plan['leaf_anchored']=True
        results['common']['rows']['ack:min:rise'].update(end='feedback/I',receiver_role='internal-feedback')
        before=relative.margins(results,plan,aperture)
        for row in results['data']['rows'].values():row['delay_ns']+=100
        after=relative.margins(results,plan,aperture)
        self.assertEqual(before['minimum_zero_reuse_hold_ns'],2.5)
        self.assertEqual(after['minimum_zero_reuse_hold_ns'],2.5)
        self.assertEqual(before['lanes'][0]['ack_receiver_role'],'internal-feedback')

    def test_graph_arrival_has_distinct_measurement_kind(self):
        p,c,s,i=ack_fixture();result=leaf.parse(s,p,c,.2,i)
        self.assertEqual(result['rows']['ack:min']['measurement'],'propagated-graph-arrival')
        self.assertEqual(result['rows']['ack:min']['receiver_role'],'external-receiver')

    def test_ack_must_not_claim_constrained_path_end(self):
        p,c,s,i=ack_fixture()
        with self.assertRaisesRegex(ValueError,'RELATIVE_LEAF_ACK_KIND'):
            leaf.parse(s.replace('LEAF_ACK_PATH','CONTROL_PATH'),p,c,.2,i)

    def test_missing_slew_polarity_and_changed_slew_rejected(self):
        p,c,s,i=ack_fixture()
        with self.assertRaisesRegex(ValueError,'LEAF_SLEW_COVERAGE'):
            leaf.parse(s.replace('LEAF_SOURCE_SLEW\t0\tmin\tfall\t.2\n',''),p,c,.2,i)
        with self.assertRaisesRegex(ValueError,'LEAF_SLEW_CHANGED'):
            leaf.parse(s.replace('LEAF_SOURCE_SLEW\t0\tmin\tfall\t.2','LEAF_SOURCE_SLEW\t0\tmin\tfall\t.3'),p,c,.2,i)

    def test_duplicate_ack_evidence_rejected(self):
        p,c,s,i=ack_fixture()
        with self.assertRaisesRegex(ValueError,'RELATIVE_QUERY_ID'):
            leaf.parse(s+next(l for l in s.splitlines() if l.startswith('LEAF_ACK_PATH'))+'\n',p,c,.2,i)

    def test_common_source_slew_must_come_from_prior_context(self):
        p,c,s,i=ack_fixture();del c['root_slew_ns']
        with self.assertRaisesRegex(ValueError,'LEAF_COMMON_SLEW_REQUIRED'):
            leaf.script(None,None,.2,p,c,sta=None)


if __name__=='__main__':unittest.main()
