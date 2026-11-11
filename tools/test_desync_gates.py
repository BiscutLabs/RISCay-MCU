# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest
from measure_desync_gates import inventory, prepare, check
from primitives import resolve_candidate
from test_desync_handoff import cell


class GateTests(unittest.TestCase):
    def fixture(self, cpu=False, previous=False):
        nets={};cells={};bindings=[]
        def bit(n):return nets.setdefault(n,len(nets)+10)
        def add(name,primitive,parameters,connections):
            b=dict(instance=name,primitive=primitive,parameters=parameters);bindings.append(b)
            for c in resolve_candidate(primitive,parameters)['cells']:
                pins={p:bit(connections.get(n,name+'/'+n)) for p,n in c['pins'].items()}
                cells[name+'/'+c['name']]=cell(c['cell'].split('__')[1],
                    {p:v for p,v in pins.items() if p not in ('Z','ZN')},
                    {p:v for p,v in pins.items() if p in ('Z','ZN')})
        params=dict(initial_open=not previous,same_count=0,closed_count=2,rise_qualified=False)
        add('source','RiscayDesyncQualifiedController',params,
            dict(acknowledgeIn='join/out',closed0='target/enable' if cpu else 'target/acknowledgeOut',closed1='other/acknowledgeOut'))
        for name in ('target','other'):
            add(name,'RiscayDesyncQualifiedController',dict(params,initial_open=previous,closed_count=0),{})
        add('join','RiscayDesyncJoin',dict(initial_open=False),
            dict(input0='other/acknowledgeOut' if cpu else 'target/acknowledgeOut',input1='other/acknowledgeOut'))
        cells['clock_buffer']=cell('buf_2',{'I':bit('target/acknowledgeOut' if cpu else 'target/enable')},{'Z':bit('clock')})
        cells['qualifier']=cell('latq_1',{'D':bit('sink/Q'),'E':bit('source/enable')},{'Q':bit('qualifier/Q')})
        cells['gate']=cell('and2_1',{'A1':bit('clock'),'A2':bit('qualifier/Q')},{'Z':bit('gated')})
        cells['sink']=cell('dffq_1' if cpu else 'latq_1',{'CLK' if cpu else 'E':bit('gated'),'D':bit('data')},{'Q':bit('sink/Q')})
        cells['extra']=cell('buf_1',{'I':bit('qualifier/Q')},{'Z':bit('extra')})
        cells['lf']=cell('dffq_1',{'CLK':bit('watchdogClock'),'D':bit('data')},{'Q':bit('lf/Q')})
        return dict(cells=cells,ports={'watchdogClock':dict(direction='input',bits=[bit('watchdogClock')])}),bindings

    def prepared(self,**kw):
        body,bindings=self.fixture(**kw);rows,*metadata=inventory(body,bindings)
        self.assertEqual({r['gate'] for r in rows},{'gate'})
        return body,prepare(body,bindings,rows[0],*metadata)

    def test_actual_paths_feedback_and_omitted_loads_are_preserved(self):
        for cpu,previous in ((False,False),(True,False),(False,True)):
            body,f=self.prepared(cpu=cpu,previous=previous)
            for n,c in f['cells'].items():
                if n!='qualifier':self.assertEqual(c,body['cells'][n])
            self.assertTrue(any(n.startswith('join/') for n in f['cells']))
            self.assertIn('target/enable_invert__cell',f['cells'])
            self.assertEqual(f['root_rise'],not cpu)
            self.assertEqual(f['initial'][f['root']],int(not previous))
            q=body['cells']['qualifier']['connections']['Q'][0]
            self.assertIn(dict(cell='extra',type=body['cells']['extra']['type'],pin='I'),f['loads'][q])

    def test_unknown_gate_or_storage_clock_cannot_hide_sinks(self):
        for kind in ('and3','unknown','unlisted_port'):
            body,bindings=self.fixture()
            if kind=='and3':body['cells']['gate']=cell('and3_1',dict(A1=body['cells']['gate']['connections']['A1'][0],A2=body['cells']['gate']['connections']['A2'][0],A3='1'),dict(Z=body['cells']['gate']['connections']['Z'][0]))
            elif kind=='unknown':body['cells']['sink']['connections']['E']=[9999]
            else:body['ports'].clear()
            with self.assertRaisesRegex(ValueError,'UNKNOWN_STORAGE_CLOCK'):inventory(body,bindings)

    def test_clocked_qualifier_and_broken_primitive_fail(self):
        body,bindings=self.fixture();c=body['cells']['qualifier']
        body['cells']['qualifier']=cell('dffq_1',dict(D=c['connections']['D'][0],CLK=c['connections']['E'][0]),dict(Q=c['connections']['Q'][0]))
        with self.assertRaisesRegex(ValueError,'QUALIFIER_NOT_LATCH'):inventory(body,bindings)
        body,bindings=self.fixture();body['cells']['source/ack_keeper__cell']['connections']['A1']=[9999]
        with self.assertRaisesRegex(ValueError,'NATIVE_WIRING'):inventory(body,bindings)

    def test_two_gates_from_one_target_cannot_overwrite_a_fixture(self):
        body,bindings=self.fixture()
        body['cells']['gate2']=deepcopy(body['cells']['gate'])
        body['cells']['gate2']['connections']['Z']=[9998]
        body['cells']['sink2']=cell('latq_1',dict(E=9998,D=9997),dict(Q=9996))
        with self.assertRaisesRegex(ValueError,'DUPLICATE_TARGET'):inventory(body,bindings)

    def test_cyclic_join_is_not_treated_as_a_shared_subtree(self):
        body,bindings=self.fixture();recipe=resolve_candidate('RiscayDesyncJoin',dict(initial_open=False))
        out=next(body['cells']['join/'+c['name']]['connections'][p][0] for c in recipe['cells'] for p,n in c['pins'].items() if n=='out')
        for c in recipe['cells']:
            for p,n in c['pins'].items():
                if n=='input0':body['cells']['join/'+c['name']]['connections'][p]=[out]
        rows,*metadata=inventory(body,bindings)
        with self.assertRaisesRegex(ValueError,'RETURN_LOOP'):prepare(body,bindings,rows[0],*metadata)

    def wave(self,old):
        names=['a','b','n','e','clock','condition','q','out'];observed=dict(zip(names,range(len(names))))
        rows=[]
        for i in range(2501):
            t=i/10;a=int(60<=t<201);b=int(110<=t<202);n=int(t<60 or t>=203)
            q=old if t<204 else 1-old
            rows.append([t*1e-9,a,b,n,n,int(110<=t<200.5),q,q,int(old and 110<=t<200.6)])
        return rows,observed,list(observed.values()),1,old,.1

    def test_complete_return_and_clean_gate_output(self):
        for old in (0,1):
            args=self.wave(old);self.assertGreater(check(*args)['input_order_separation_ns'],1)
            for mutation in ('missing','reopen','newpulse','no_reuse','early','history','slowclock'):
                args=deepcopy(self.wave(old));rows,observed,*_=args
                if mutation=='missing':del rows[2100]
                elif mutation=='reopen':rows[2100][observed['clock']+1]=1
                elif mutation=='newpulse':rows[2200][observed['out']+1]=1
                elif mutation=='early':rows[1700][observed['condition']+1]=1-old
                elif mutation=='history':rows[1900][observed['b']+1]=0
                elif mutation=='no_reuse':
                    for row in rows[2000:]:row[observed['q']+1]=old
                else:
                    for row in rows[2000:2060]:row[observed['clock']+1]=1
                with self.assertRaises(ValueError):check(*args)


if __name__=='__main__':unittest.main()
