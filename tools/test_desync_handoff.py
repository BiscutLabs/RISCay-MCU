# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest
from gf180_physical import SC
from measure_desync_handoff import pair_inventory, parse, audit_view, clock_cone, run
from primitives import resolve_candidate


def cell(kind,inputs,outputs):
    return dict(type=SC+kind,connections={k:[v] for k,v in (inputs|outputs).items()},
                port_directions={k:'input' for k in inputs}|{k:'output' for k in outputs})


class HandoffTests(unittest.TestCase):
    def fixture(self):
        source=dict(instance='desync_control/x.m'); target=dict(instance='desync_control/x.s')
        body=dict(ports={'close':dict(direction='input',bits=[20])},cells={
            source['instance']+'/enable_invert__cell':cell('inv_1',{'I':10},{'ZN':1}),
            target['instance']+'/enable_invert__cell':cell('inv_1',{'I':20},{'ZN':2}),
            'm':cell('latq_1',{'E':1,'D':100},{'Q':3}),
            's':cell('latq_1',{'E':2,'D':3},{'Q':4})})
        roots={source['instance']+'/enable':'m_root',target['instance']+'/enable':'s_root'}
        routes={'m/E':dict(root='m_root',arcs=[]),'s/E':dict(root='s_root',arcs=[])}
        return body,routes,roots,source,target

    def test_pair_inventory_is_independent_of_route_inventory(self):
        args=self.fixture()
        self.assertEqual(pair_inventory(*args),[('m/Q','s/D')])
        args[1].clear() # Both missing endpoints used to pass one-to-one checks.
        with self.assertRaisesRegex(ValueError,'TREE_INVENTORY'):pair_inventory(*args)

    def test_hidden_gated_or_non_latch_sink_is_rejected(self):
        for macro in (False,True):
            body,routes,roots,source,target=self.fixture()
            if macro:
                body['cells']['bad']=cell('dffq_1',{'CLK':2,'D':100},{'Q':7})
            else:
                body['cells']['gate']=cell('and2_1',{'A1':2,'A2':100},{'Z':6})
                body['cells']['bad']=cell('latq_1',{'E':6,'D':100},{'Q':7})
            with self.assertRaisesRegex(ValueError,'NOT_LATCH|GATED'):
                pair_inventory(body,routes,roots,source,target)

    def test_every_data_bit_must_be_a_direct_pair(self):
        args=self.fixture();args[0]['cells']['s']['connections']['D']=[100]
        with self.assertRaisesRegex(ValueError,'DIRECT_DATA'):pair_inventory(*args)

    def test_clock_cone_rejects_unknown_qualifier(self):
        body,*_=self.fixture()
        with self.assertRaisesRegex(ValueError,'UNKNOWN_CLOCK_FRONTIER'):
            clock_cone(body,'close',[('m/Q','s/D')])
        body['cells']['desync_control/x.m/enable_invert__cell']['connections']['I']=[20]
        self.assertIn('s/E',clock_cone(body,'close',[('m/Q','s/D')]))

    def test_both_polarities_and_every_slew_are_required(self):
        text='CASE 0.02 rise\nHOLD m/Q s/D 0.2\nPATH_SLEW 1\nCASE 0.02 fall\nHOLD m/Q s/D 0.3\nPATH_SLEW 1\nHOLD_DONE\n'
        self.assertEqual({r['edge'] for r in parse(text,[('m/Q','s/D')],[.02])},{'rise','fall'})
        for broken in (text.replace('HOLD m/Q s/D 0.3\n',''),text.replace('0.3','nan'),text+'Error: bad\n',
                       text.replace('0.3\n','0.3\nHOLD m/Q s/D 0.3\n'),text.replace('PATH_SLEW 1\n',''),
                       text.replace('PATH_SLEW 1','PATH_SLEW 2.1'),text+'Warning: SDF target missing\n'):
            with self.assertRaises(ValueError):parse(broken,[('m/Q','s/D')],[.02])

    def test_timing_policy_cannot_be_weakened_or_nonfinite(self):
        for period,derate,late in ((0,1.2,0),(1000,1.19,0),(1000,1.2,-1),(float('nan'),1.2,0),(1000,float('inf'),0)):
            with self.assertRaisesRegex(ValueError,'INVALID_TIMING_POLICY'):
                run(None,None,None,None,None,'i2c',period,derate,late)

    def test_graph_and_removed_pin_loads_are_independent_inventories(self):
        binding=dict(instance='desync_control/j',primitive='RiscayDesyncJoin',parameters={'initial_open':False})
        recipe=resolve_candidate(binding['primitive'],binding['parameters']);nets={}
        def bit(n):return nets.setdefault(n,len(nets)+2)
        cells={}
        for c in recipe['cells']:
            inputs={p:bit(n) for p,n in c['pins'].items() if p not in ('Z','ZN')}
            outputs={p:bit(n) for p,n in c['pins'].items() if p in ('Z','ZN')}
            cells[binding['instance']+'/'+c['name']]=cell(c['cell'].removeprefix(SC),inputs,outputs)
        ports={n:dict(direction='input',bits=[bit(n)]) for n in recipe['ports']}
        before=dict(modules={'RiscayMcuDigital':dict(cells=cells,ports=ports)})
        after=deepcopy(before);after['modules']['RiscayMcuDigital']['cells']={};loads=[]
        for i,(net,b) in enumerate(nets.items()):
            if net not in ports:continue
            pins=[[c['type'],p] for c in cells.values() for p,bs in c['connections'].items()
                  if c['port_directions'][p]=='input' and bs==[b]]
            helper=cell('buf_1',{'I':b},{})
            helper['type']='DesyncAnalysisLoad'+str(i)
            after['modules']['RiscayMcuDigital']['cells']['load'+str(i)]=helper
            loads.append(dict(cell=helper['type'],pins=pins))
        audit_view(before,after,loads,[binding],[])
        next(r for r in loads if r['pins'])['pins'].pop()
        with self.assertRaisesRegex(ValueError,'PIN_LOAD_CHANGED'):audit_view(before,after,loads,[binding],[])


if __name__=='__main__':unittest.main()
