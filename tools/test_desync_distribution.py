# SPDX-License-Identifier: Apache-2.0
from collections import Counter
from copy import deepcopy
import unittest
from desync_distribution import prepare, validate_trees
from desync_assemble import assemble
from audit_desync_protection import audit
from repair_gf180_design import graph_proof
from gf180_physical import SC, SRAM
from test_desync_network import fixture


class DistributionTests(unittest.TestCase):
    def fixture(self):
        part=fixture();top=dict(ports={},netnames={},cells={})
        for i,n in enumerate(('serviceClock','serviceClockEnable','resetHold/unsafe_supply','watchdogClock','sda',
                             'desync_cpu_capture','desync_fabric_m','desync_fabric_s','desync_power_m','desync_power_s')):
            top['netnames'][n]=dict(bits=[i+2],attributes={})
            if '/' not in n:top['ports'][n]=dict(direction='input',bits=[i+2])
        for i in range(257):
            top['cells']['storage'+str(i)]=dict(type=SC+'dffq_1',parameters={},attributes={},
                port_directions=dict(D='input',CLK='input',Q='output'),
                connections=dict(D=['0'],CLK=top['ports']['desync_cpu_capture']['bits'],Q=[100+i]))
            top['netnames']['q'+str(i)]=dict(bits=[100+i],attributes={})
        net,report=assemble(dict(modules={'RiscayMcuDigital':top}),dict(status='storage-scaffold-only',partition=part),timing_preparation=True)
        lib={c['type']:'' for c in net['modules']['RiscayMcuDigital']['cells'].values()}
        lib[SC+'dffq_1']='pin(CLK) {direction : input; clock : true;} pin(D) {direction : input;} pin(Q) {direction : output;}'
        for kind in ('buf_2','clkbuf_8'):
            lib[SC+kind]='pin(I) {direction : input;} pin(Z) {direction : output; function : "I";}'
        return net,report['bindings'],lib

    def test_parent_isolation_preserves_graph_and_every_storage_sink(self):
        net,bindings,lib=self.fixture();original=deepcopy(net)
        result,report=prepare(net,bindings,lib)
        protected={b['instance']+'/'+c['name']:b['instance'] for b in bindings for c in b['cells']}
        proof=graph_proof(net,result,'RiscayMcuDigital',protected,[lib])
        self.assertEqual(len(proof['added_buffers']),report['buffer_count'])
        self.assertEqual(audit(result,bindings,experimental=True)['status'],'pass')
        self.assertEqual(net,original)
        self.assertEqual(validate_trees(result,result,report)['sinks'],257)
        seen=Counter(p for t in report['enable_trees'] for p in t['sinks'])
        expected={n+'/CLK' for n,c in net['modules']['RiscayMcuDigital']['cells'].items() if c['type']==SC+'dffq_1'}
        self.assertEqual(set(seen),expected);self.assertTrue(all(n==1 for n in seen.values()))
        body=result['modules']['RiscayMcuDigital'];cells=body['cells']
        for tree in report['enable_trees']:
            drivers={cells[n]['connections']['Z'][0]:cells[n]['connections']['I'][0] for n in tree['buffers']}
            for pin in tree['sinks']:
                n,p=pin.rsplit('/',1);bit=cells[n]['connections'][p][0];depth=0
                while bit in drivers:bit=drivers[bit];depth+=1
                self.assertEqual((bit,depth),(tree['root'],tree['depth']))
            fanout=Counter(b for c in cells.values() for p,bs in c['connections'].items()
                          if c['port_directions'][p]=='input' for b in bs)
            self.assertTrue(all(fanout[b]<=16 for b in drivers))
        # A buffer accidentally inserted into a local keeper must fail even
        # though contracting it would preserve ordinary Boolean connectivity.
        bad=deepcopy(result);b=bindings[0];native=bad['modules']['RiscayMcuDigital']['cells']
        n=b['instance']+'/'+b['cells'][0]['name']
        p=next(p for p in native[n]['connections'] if native[n]['port_directions'][p]=='input')
        native[n]['connections'][p]=[999999]
        with self.assertRaisesRegex(ValueError,'NATIVE_CONNECTIVITY'):
            graph_proof(net,bad,'RiscayMcuDigital',protected,[lib])
        bad=deepcopy(result);cell=bad['modules']['RiscayMcuDigital']['cells']['storage0']
        cell['connections']['CLK']=[report['enable_trees'][0]['root']]
        with self.assertRaisesRegex(ValueError,'TREE_DEPTH'):validate_trees(result,bad,report)
        for whole_tree in (False,True):
            bad_report=deepcopy(report)
            if whole_tree:bad_report['enable_trees'].pop()
            else:bad_report['enable_trees'][0]['sinks'].pop()
            with self.assertRaisesRegex(ValueError,'TREE_SINK_COVERAGE'):
                validate_trees(result,result,bad_report)

    def test_blackbox_pins_are_not_discarded_by_graph_proof(self):
        cell=dict(type='fixed',parameters={},attributes={},port_directions=dict(I='input',Z='output'),connections=dict(I=[2],Z=[3]))
        module=dict(attributes={'blackbox':'1'},ports=dict(I=dict(direction='input',bits=[2]),Z=dict(direction='output',bits=[3])))
        net=dict(modules={'RiscayMcuDigital':dict(ports={},netnames={},cells={'fixed':cell}), 'fixed':module})
        self.assertEqual(graph_proof(net,net,'RiscayMcuDigital',{},[])['original_cells'],1)
        bad=deepcopy(net);bad['modules']['RiscayMcuDigital']['cells']['fixed']['connections']['I']=['0']
        with self.assertRaisesRegex(ValueError,'GRAPH_CHANGED'):graph_proof(net,bad,'RiscayMcuDigital',{},[])


if __name__=='__main__':unittest.main()
