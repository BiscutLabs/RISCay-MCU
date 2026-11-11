# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from measure_desync_gates import inventory, prepare, deck, check, setup_table, setup_value, opening_check, opening_verdict, qualifier_chains
from primitives import resolve_candidate
from test_desync_handoff import cell


class GateTests(unittest.TestCase):
    def fixture(self, cpu=False, previous=False, opening=False):
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
            active=opening and name=='target'
            target_params=dict(params,initial_open=cpu or previous if active else previous,
                               closed_count=int(active and not cpu),rise_qualified=active and cpu)
            connections=(dict(acknowledgeIn='other/acknowledgeOut',riseAllowed='source/acknowledgeOut') if cpu else
                         dict(acknowledgeIn='opening_join/out',closed0='source/acknowledgeOut')) if active else {}
            add(name,'RiscayDesyncQualifiedController',target_params,connections)
        add('join','RiscayDesyncJoin',dict(initial_open=False),
            dict(input0='other/acknowledgeOut' if cpu else 'target/acknowledgeOut',input1='other/acknowledgeOut'))
        if opening and not cpu:add('opening_join','RiscayDesyncJoin',dict(initial_open=False),
            dict(input0='source/acknowledgeOut',input1='other/acknowledgeOut'))
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

    def test_opening_preserves_target_keeper_and_common_source_closure(self):
        for cpu,previous in ((False,False),(True,False),(False,True)):
            body,bindings=self.fixture(cpu=cpu,previous=previous,opening=True)
            rows,*metadata=inventory(body,bindings);f=prepare(body,bindings,rows[0],*metadata,opening=True)
            self.assertIn('target/ack_keeper__cell',f['cells'])
            self.assertNotIn('source/ack_keeper__cell',f['cells'])
            self.assertEqual(f['root'],body['cells']['source/enable_invert__cell']['connections']['I'][0])
            self.assertTrue(f['root_rise'])
            for n,c in f['cells'].items():
                if n!='qualifier':self.assertEqual(c,body['cells'][n])
            self.assertIn('target/qualified_set__cell' if cpu else 'opening_join/reset_state__cell',f['cells'])

    def test_qualifier_chain_uses_real_direct_links_not_domain_maxima(self):
        body,bindings=self.fixture();cells=body['cells'];cells['qualifier']['connections']['D']=[8888]
        cells['prior']=cell('latq_1',dict(D=9999,E=cells['qualifier']['connections']['E'][0]),dict(Q=8888))
        rows,ports,owners,native,drivers=inventory(body,bindings)
        chains=qualifier_chains(body,rows,native,drivers)
        self.assertEqual([x['cell'] for x in chains['qualifier']['links']],['qualifier','prior'])
        self.assertEqual(chains['qualifier']['data_pin'],'prior/D')
        cells['prior']['connections']['D']=cells['qualifier']['connections']['Q']
        with self.assertRaisesRegex(ValueError,'DATA_LOOP'):qualifier_chains(body,rows,native,drivers)

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

    def library(self):
        return '''library(test) { slew_derate_from_library : 0.5;
          lu_table_template(cnst) { variable_1 : constrained_pin_transition; variable_2 : related_pin_transition; }
          cell(latch) { pin(D) { timing() { related_pin : "E"; timing_type : setup_falling;
            rise_constraint(cnst) { index_1("0.02, 2"); index_2("0.02, 2"); values("0.22,20.02", "2.2,22"); }
            fall_constraint(cnst) { index_1("0.02, 2"); index_2("0.02, 2"); values("0.22,20.02", "2.2,22"); }
          } } } }'''

    def test_setup_axes_physical_slew_and_range_admission(self):
        for rise in (True,False):
            table=setup_table(self.library(),'latch',rise)
            self.assertAlmostEqual(setup_value(table,.1,.2),4.2)
            for data,clock in ((.001,.2),(.1,2),(float('nan'),.2)):
                with self.assertRaisesRegex(ValueError,'OUTSIDE_TABLE'):setup_value(table,data,clock)
        with self.assertRaisesRegex(ValueError,'SETUP_AXES'):
            setup_table(self.library().replace('constrained_pin_transition','related_pin_transition'),'latch',True)

    def test_opening_data_and_root_slews_are_independent(self):
        body,bindings=self.fixture(opening=True);gates,*metadata=inventory(body,bindings)
        f=prepare(body,bindings,gates[0],*metadata,True);library={};headers={}
        for c in body['cells'].values():
            headers[c['type']]=list(c['connections'])+['VDD','VNW','VPW','VSS']
            library[c['type']]=''.join('pin('+p+') { capacitance : 0.001; }' for p in c['connections'])
        def stimulus(root,data):
            text,*_=deck(f,library,headers,Path('pdk'),SimpleNamespace(path=str),
                         ('test','typical',25,3.3),root,0,.1,0,Path('wave'),200,data)
            return {line.split()[0]:line for line in text.splitlines() if line.startswith('V')}
        fast=stimulus(.02,.02);slow_data=stimulus(.02,2);slow_root=stimulus(2,.02)
        self.assertEqual(fast['Vroot'],slow_data['Vroot'])
        self.assertEqual(fast['Vdata'],slow_root['Vdata'])
        self.assertNotEqual(fast['Vdata'],slow_data['Vdata'])
        self.assertNotEqual(fast['Vroot'],slow_root['Vroot'])

    def opening_wave(self,old,cpu):
        names=['root','a','b','n','e','clock','data','q','condition','out','request','ack'];observed=dict(zip(names,range(len(names))))
        rows=[]
        def ramp(t,center,width=1):return max(0,min(1,(t-center)/width+.5))
        for i in range(2501):
            t=i/10;event=ramp(t,203);root=ramp(t,200.5);q=(1-ramp(t,199)) if old else ramp(t,199)
            data=(1-ramp(t,198.5)) if old else ramp(t,198.5)
            clock=event if t>=180 else int(cpu)
            rows.append([t*1e-9,root,event if cpu else 1-event,0 if cpu else 1-event,
                         1-event if cpu else event,1-ramp(t,201),clock,data,q,q,clock*q,int(cpu),1])
        table=('index_1("0.02,2");index_2("0.02,2");values("0.1,0.1","0.1,0.1");',.5)
        return rows,observed,list(observed.values()),1,old,.1,cpu,table

    def test_opening_premise_and_order_are_distinct_failure_kinds(self):
        for old in (0,1):
            for cpu in (False,True):
                args=self.opening_wave(old,cpu);r=opening_check(*args);opening_verdict(r)
                bad=dict(r,setup_headroom_ns=-.1)
                with self.assertRaisesRegex(ValueError,'INVALID_APERTURE_PREMISE'):opening_verdict(bad)
                # A late qualifier with valid D/setup must trip the ordering check.
                rows,obs,*_=args
                for row in rows:
                    t=row[0]*1e9;q=max(0,min(1,t-204+.5));q=1-q if old else q
                    row[obs['q']+1]=q;row[obs['condition']+1]=q
                    row[obs['out']+1]=0 if old else max(0,min(1,t-205+.5))
                    if cpu and t<180:row[obs['out']+1]=old
                r=opening_check(*args);self.assertGreater(r['setup_headroom_ns'],.1)
                with self.assertRaisesRegex(ValueError,'QUALIFIER_ORDER'):opening_verdict(r)

    def test_opening_cannot_time_request_instead_or_hide_feedback_pulses(self):
        for old in (0,1):
            for fault in ('request','ack','b','clock','previous_pulse','missing'):
                args=deepcopy(self.opening_wave(old,True));rows,observed,*_=args
                if fault=='missing':del rows[2000]
                elif fault=='previous_pulse':rows[1750][observed['out']+1]=1-old
                else:rows[1980 if fault in ('request','ack') else 2100][observed[fault]+1]=0 if fault in ('request','ack','clock') else 1
                with self.assertRaises(ValueError):opening_check(*args)


if __name__=='__main__':unittest.main()
