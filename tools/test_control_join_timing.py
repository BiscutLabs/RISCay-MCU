# SPDX-License-Identifier: Apache-2.0
"""Independent arithmetic, coverage and evidence-integrity controls (no PDK)."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import control_join_timing as j


def fixture(variant='bd'):
    stages={}
    owners=('request_delay','a','long_hold','acknowledge','input_compare','fire')
    for name in ('left','right','update'):
        stages[name]=dict(prefix=name+'/',lane_map=[dict(lane=0,D='store/D',Q='store/Q',capture='store/E' if variant=='bd' else 'store/CLK')],
            payload_width=1,constant_lanes={},event='event',phase=dict(Q=dict(pin='phase/Q'),CLK=dict(pin='phase/CLK')),
            native=dict(signals={k:k for k in owners},cells=[dict(path=k,pins=dict(Z=k)) for k in owners]),contexts=[dict(id='data',sources=['in_bits'])])
    p=dict(variant=variant,stages=stages,rendezvous='join/')
    with patch.object(j,'state',return_value={}):
        with patch.object(j,'reachable_lanes',return_value=[0]):p['contexts']=j.contexts(p,[])
    r={}
    for side in ('left','right'):
        r[side+'-input']=dict(rows={f'input:0:max:{e}':dict(delay_ns=2) for e in ('rise','fall')},
            dq={'0':{e:dict(delay_ns=3,slew_ns=.5) for e in ('rise','fall')}})
        for phase in ([0] if variant=='bd' else [0,1]):
            edge='fall' if variant=='bd' else 'rise'
            r[f'{side}-request-{phase}']=dict(rows={f'source_capture:0:{m}:{edge}':dict(delay_ns=v) for m,v in [('min',10),('max',12)]},source_slews={'0':[.5,.5]},event_slews=[.3,.5])
            if variant=='bd':r[f'{side}-request-{phase}']['rows'].update({'return:min':dict(delay_ns=33),'return:max':dict(delay_ns=35)})
            captures={f'capture:0:{m}:{edge}':dict(delay_ns=v) for m,v in [('min',30),('max',32)]}
            r[f'{side}-launch-{phase}']=dict(rows={f'data:0:max:{e}':dict(delay_ns=5) for e in ('rise','fall')},source_slews={'0':[.5,.5]},event_slews=[.3,.5])
            r[f'{side}-'+('request-' if variant=='bd' else 'launch-')+str(phase)]['rows'].update(captures)
    return p,r


class CompositionTests(unittest.TestCase):


    def test_identity_storage_checks_each_lane_not_just_width(self):
        b=dict(ports=dict(in_bits=dict(bits=[2,3]),out_bits=dict(bits=[4,5])),
            cells=dict(ca_primitive_payload=dict(connections=dict(d=[6,7],q=[4,5])),
                       ca_primitive_data_delay=dict(connections=dict(a=[2,3],q=[6,7]))))
        j.identity_storage(b)
        b['cells']['ca_primitive_data_delay']['connections']['a']=[3,2]
        with self.assertRaisesRegex(ValueError,'^JOIN_IDENTITY_DATA$'):j.identity_storage(b)


def request_log():
    p,_=fixture('bd');c=next(c for c in p['contexts'] if c['id']=='left-request-0')
    c['queries']=[q for q in c['queries'] if q['role']=='source_capture']
    text='JOIN_BEGIN\n'
    for q in c['queries']:
        delay=10 if q['mode']=='min' else 12
        text+=f"CONTROL_PATH\t{q['id']}\t0\t{delay}\t{delay}\t{delay}\t.5\tjoin_left_req\tleft/store/E\trise\tfall\n"
        text+=f"CONTROL_POINTS\t{q['id']}\tjoin_left_req\tleft/request_delay/Z\tleft/a/Z\tleft/long_hold/Z\tleft/store/E\n"
    return p,c,text+'JOIN_ELECTRICAL_BEGIN\nJOIN_ELECTRICAL_END\nJOIN_COMPLETE\n'


class InputCoverageTests(unittest.TestCase):
    def fixture(self):
        parent=dict(cells={'rf':dict(connections={'values_0':[20,21],'values_1':[22,23]},
                                    port_directions={'values_0':'output','values_1':'output'})})
        join=dict(connections={'out_req':[2],'out_ack':[3],'out_bits_left':[4,5],'out_bits_right':[6,7]})
        conn={'reset':[1],'in_req':[2],'in_ack':[3],'in_bits_state':[4,5],
              'in_bits_response':[6,7],'in_bits_registers_0':[20,21],'in_bits_registers_1':[22,23],'out_ack':[8]}
        sink=dict(connections=conn,port_directions={p:'output' if p=='in_ack' else 'input' for p in conn})
        side={f'in_bits_registers_{i}':dict(cell='rf',port=f'values_{i}',width=2) for i in range(2)}
        return parent,join,sink,{'left':'state','right':'response'},side

    def test_every_side_bit_keeps_actual_parent_provenance(self):
        rows=j.bind_inputs(*self.fixture());side=[r for r in rows if r['kind']=='uncomposed-side-source']
        self.assertEqual(sum(r['width'] for r in side),4)
        self.assertEqual(side[0]['lanes'],[dict(source_bit=i,destination_bit=i,parent_net=20+i) for i in range(2)])


if __name__=='__main__':unittest.main()
