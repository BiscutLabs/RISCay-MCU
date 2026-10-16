# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest
from unittest.mock import patch

import control_retention_timing as r


def fixture(variant='bd'):
    u=dict(prefix='update/',event='event/Z',lane_map=[dict(lane=i,capture=f'p{i}/E',Q=f'p{i}/Q') for i in range(2)],
           phase=dict(CLK=dict(pin='phase/CLK'),Q=dict(pin='phase/Q')),
           native=dict(signals=dict(acknowledge='ack',acknowledge_guard='ack'),
                       cells=[dict(path='ack',pins=dict(Z='ack'))]))
    plan=dict(variant=variant,stages=dict(update=u),retention_contexts=[]);results={}
    for side in ('left','right'):
        for phase in ([0] if variant=='bd' else [0,1]):
            c=dict(id=f'{side}-permission-{phase}',kind='permission',phase=phase,side=side,
                   sources=['update/event/Z'],queries=[])
            for i in range(2):
                for m in ('min','max'):c['queries'].append(dict(id=f'capture:{i}:{m}',role='capture',lane=i,mode=m,
                    source_edge='rise',sink_edge='fall' if variant=='bd' else 'rise',sink=f'update/p{i}/E'))
            for m in ('min','max'):c['queries'].append(dict(id='ack:'+m,role='ack',mode=m,source_edge='rise' if variant=='bd' else 'any',
                sink_edge='rise' if phase==0 else 'fall',sink='probe_update_ack'))
            plan['retention_contexts'].append(c)
            slew=dict(event=[.1,.2],ack=[.3,.4])
            results[c['id']]=dict(rows={q['id']:dict(delay_ns=10 if q['role']=='ack' else 4+q['lane']) for q in c['queries']},slews=deepcopy(slew))
            results[c['id'].replace('permission','arrival')]=dict(slews=deepcopy(slew))
        results[side+'-fork']=dict(rows={'a:min':dict(delay_ns=2),'ack:max':dict(delay_ns=.1)},slews=dict(ack=[.3,.4]))
    return plan,results


class ArithmeticTests(unittest.TestCase):
    def test_zero_contamination_uses_last_lane_and_no_source_or_transform_credit(self):
        p,v=fixture();s=r.margins(v,p,dict(hold_ns=.5))
        self.assertEqual([a['zero_contamination_hold_margin_ns'] for a in s['permission']],[4.5,4.5])
        self.assertEqual(s['forks'][0]['margin_ns'],1.9)
        self.assertFalse(s['physical_qualification'])

    def test_late_noncritical_capture_must_become_a_failure(self):
        p,v=fixture();v['left-permission-0']['rows']['capture:0:max']['delay_ns']=20
        self.assertEqual(r.margins(v,p,dict(hold_ns=.5))['permission'][0]['zero_contamination_hold_margin_ns'],-10.5)

    def test_early_ack_must_become_a_failure(self):
        p,v=fixture();v['left-permission-0']['rows']['ack:min']['delay_ns']=0
        self.assertEqual(r.margins(v,p,dict(hold_ns=.5))['permission'][0]['zero_contamination_hold_margin_ns'],-5.5)

    def test_fork_equality_is_not_strict_order(self):
        p,v=fixture();v['left-fork']['rows']['a:min']['delay_ns']=.1
        self.assertFalse(r.margins(v,p,dict(hold_ns=.5))['forks'][0]['strict_order'])

    def test_click_covers_both_phases_without_a_bd_fork_claim(self):
        p,v=fixture('click');s=r.margins(v,p,dict(hold_ns=.5))
        self.assertEqual([(a['side'],a['phase']) for a in s['permission']],[(s,p) for s in ('left','right') for p in (0,1)])
        self.assertEqual(s['forks'],[])

    def test_every_upstream_slew_bound_must_match(self):
        for variant in ('bd','click'):
            for side in ('left','right'):
                for phase in ([0] if variant=='bd' else [0,1]):
                    for signal in ('event','ack'):
                        for i in (0,1):
                            p,v=fixture(variant);v[f'{side}-arrival-{phase}']['slews'][signal][i]+=.01
                            with self.assertRaisesRegex(ValueError,'^RETENTION_COMMON_SLEW_CHANGED$'):r.margins(v,p,dict(hold_ns=.5))

    def test_fork_uses_measured_ack_slew(self):
        p,v=fixture();v['right-fork']['slews']['ack'][0]=0
        with self.assertRaisesRegex(ValueError,'^RETENTION_FORK_SLEW_CHANGED$'):r.margins(v,p,dict(hold_ns=.5))


def log_fixture(variant='bd',phase=0):
    p,_=fixture(variant);c=next(c for c in p['retention_contexts'] if c['side']=='left' and c['phase']==phase)
    lines=['RETENTION_BEGIN']
    for q in c['queries']:
        seq=variant=='click' and q['role']=='ack';sa=2 if seq else 0
        start='update/phase/Q' if seq else c['sources'][0];se=q['sink_edge'] if seq else q['source_edge']
        arrival=10 if q['role']=='ack' else 4
        lines.append(f'CONTROL_PATH\t{q["id"]}\t{sa}\t{arrival}\t{arrival}\t{arrival-sa}\t.2\t{start}\t{q["sink"]}\t{se}\t{q["sink_edge"]}')
        points=[c['sources'][0]]
        if q['role']=='ack':
            if seq:points+=['update/phase/CLK','update/phase/Q']
            points+=['update/ack/Z']
        points.append(q['sink']);lines.append('CONTROL_POINTS\t'+q['id']+'\t'+'\t'.join(points))
    lines+=['RETENTION_EVENT_SLEW\t.1\t.2','RETENTION_ACK_SLEW\t.3\t.4','RETENTION_ELECTRICAL_BEGIN','RETENTION_ELECTRICAL_END','RETENTION_COMPLETE']
    return p,c,'\n'.join(lines)+'\n'


class ParserTests(unittest.TestCase):
    def reject(self,fn,diagnostic,variant='bd',phase=0):
        p,c,s=log_fixture(variant,phase)
        with self.assertRaisesRegex(ValueError,'^'+diagnostic+'$'):r.parse(fn(s),p,c)

    def test_phase_clk_q_is_included_once(self):
        for phase in (0,1):
            p,c,s=log_fixture('click',phase);self.assertEqual(r.parse(s,p,c)['rows']['ack:min']['delay_ns'],10)

    def test_missing_phase_clock_rejects(self):
        self.reject(lambda s:s.replace('update/phase/CLK\t',''),'RETENTION_CLK_Q_PROVENANCE','click',1)

    def test_wrong_phase_edge_rejects(self):
        self.reject(lambda s:s.replace('\tfall\tfall\n','\trise\tfall\n'),'RETENTION_PATH_BINDING','click',1)

    def test_no_missing_path_becomes_zero(self):
        self.reject(lambda s:'\n'.join(l for l in s.splitlines() if '\tack:min\t' not in l)+'\n','RETENTION_QUERY_COVERAGE')

    def test_wrong_ack_driver_rejects(self):
        self.reject(lambda s:s.replace('update/ack/Z','sibling/ack/Z'),'RETENTION_ACK_PROVENANCE')

    def test_nonfinite_slew_rejects(self):
        self.reject(lambda s:s.replace('RETENTION_ACK_SLEW\t.3\t.4','RETENTION_ACK_SLEW\tNaN\t.4'),'RETENTION_SLEW_NUMERIC')

    def test_reversed_slew_bounds_reject(self):
        self.reject(lambda s:s.replace('RETENTION_EVENT_SLEW\t.1\t.2','RETENTION_EVENT_SLEW\t.3\t.2'),'RETENTION_SLEW_NUMERIC')

    def test_unfinished_log_rejects(self):
        self.reject(lambda s:s.replace('RETENTION_COMPLETE\n',''),'RETENTION_INCOMPLETE')

    def test_tool_warning_is_not_a_pass(self):
        self.reject(lambda s:'Warning: loop\n'+s,'RETENTION_TOOL_DIAGNOSTIC')

    def test_arrival_forwards_period(self):
        p,_=fixture();c=dict(kind='arrival',phase=0,request={})
        with patch.object(r.j,'script',return_value='row JOIN_COMPLETE\n') as script:
            r.script(None,'tt',.2,p,c,None,period=2000)
        self.assertEqual(script.call_args.kwargs['period'],2000)


def cofactor_fixture():
    n=dict(signals=dict(b='b',request_delay='req',a='q'),ports=dict(reset='reset',out_ack='ack'),cells=[])
    for name,kind,pins in [('nb','inv_1',dict(I='b',ZN='nb')),('na','inv_1',dict(I='ack',ZN='na')),
                          ('rise','and2_1',dict(A1='nb',A2='req',Z='rise')),('hold','or2_1',dict(A1='nb',A2='na',Z='hold')),
                          ('keeper','aoi21_1',dict(A1='feedback',A2='hold',B='rise',ZN='qn')),
                          ('reset','nor2_1',dict(A1='qn',A2='reset',ZN='feedback')),('out','buf_1',dict(I='feedback',Z='q'))]:
        n['cells'].append(dict(path='ca_primitive_a/'+name,cell=r.j.SC+kind,pins=pins))
    return dict(prefix='left/',native=n)


def arc_log():
    ctx=dict(sources=['ack/Z'],chain=[['inv/I','inv/ZN','^','v']],fork_pins=dict(a='or/A1',ack='or/A2'))
    lines=['RETENTION_BEGIN']
    for m in ('min','max'):
        lines += [f'FORK_WIRE\t{m}\tack/Z\tinv/I\t^\t0\t0',
                  f'FORK_CELL\t{m}\tinv/I\tinv/ZN\t^\tv\t0.3\t0.01\t0.4\t0.5\t0.4\t0',
                  f'FORK_DCALC_BEGIN\t{m}\tinv/I\tinv/ZN',
                  '------- input_net_transition = 0.3','|       total_output_net_capacitance = 0.01','Delay = 0.4',
                  '------- input_net_transition = 0.3','|       total_output_net_capacitance = 0.01','Slew = 0.5','FORK_DCALC_END',
                  f'FORK_WIRE\t{m}\tinv/ZN\tor/A1\tv\t0\t0',f'FORK_PATH\t{m}\t0.4\t0.5\tv',
                  f'FORK_WIRE\t{m}\tack/Z\tor/A2\t^\t0\t0']
    lines += ['RETENTION_EVENT_SLEW\t0.1\t0.1','RETENTION_ACK_SLEW\t0.3\t0.3','RETENTION_COMPLETE']
    return ctx,'\n'.join(lines)+'\n'


class ForkTests(unittest.TestCase):
    def test_b_high_disables_request_minterm_in_both_request_states(self):
        chain=r.fork_chain(cofactor_fixture());self.assertEqual(len(chain),5)
        self.assertTrue(chain[0][0].endswith('na/I'));self.assertEqual(chain[-1][-1],'v')

    def test_active_request_minterm_rejects(self):
        s=cofactor_fixture();s['native']['cells'][2]['pins']['A1']='req'
        with self.assertRaisesRegex(ValueError,'^RETENTION_COFACTOR_FUNCTION$'):r.fork_chain(s)

    def test_unknown_cell_is_not_assumed_to_be_a_buffer(self):
        s=cofactor_fixture();s['native']['cells'][-1]['cell']=r.j.SC+'unknown'
        with self.assertRaisesRegex(ValueError,'^RETENTION_COFACTOR_CELL$'):r.fork_chain(s)

    def test_actual_arc_reports_are_summed(self):
        c,s=arc_log();v=r.parse_fork(s,c)
        self.assertEqual(v['rows']['a:min']['delay_ns'],.4);self.assertEqual(v['rows']['ack:max']['delay_ns'],0)

    def reject(self,fn,message):
        c,s=arc_log()
        with self.assertRaisesRegex(ValueError,'^'+message+'$'):r.parse_fork(fn(s),c)

    def test_raw_report_load_mismatch_rejects(self):
        self.reject(lambda s:s.replace('capacitance = 0.01','capacitance = 0.02',1),'RETENTION_ARC_REPORT_MISMATCH')

    def test_slew_handoff_mismatch_rejects(self):
        self.reject(lambda s:s.replace('RETENTION_ACK_SLEW\t0.3\t0.3','RETENTION_ACK_SLEW\t0.2\t0.3'),'RETENTION_ARC_SLEW_CHAIN')

    def test_unmodeled_wire_rc_rejects(self):
        self.reject(lambda s:s.replace('ack/Z\tor/A2\t^\t0\t0','ack/Z\tor/A2\t^\t0.1\t0'),'RETENTION_UNMODELED_WIRE')

    def test_fault_annotation_not_allowed_in_baseline(self):
        self.reject(lambda s:s.replace('ack/Z\tor/A2\t^\t0\t0','ack/Z\tor/A2\t^\t10\t1'),'RETENTION_UNMODELED_WIRE')

    def test_pure_transport_fault_changes_only_ack_branch(self):
        c,s=arc_log();s=s.replace('ack/Z\tor/A2\t^\t0\t0','ack/Z\tor/A2\t^\t10\t1')
        v=r.parse_fork(s,c,True);self.assertEqual(v['rows']['a:min']['delay_ns']-v['rows']['ack:max']['delay_ns'],-9.6)

    def test_missing_cell_row_is_not_a_zero_delay(self):
        self.reject(lambda s:'\n'.join(l for l in s.splitlines() if not l.startswith('FORK_CELL\tmin'))+'\n','RETENTION_ARC_COVERAGE')

    def test_wrong_polarity_rejects(self):
        self.reject(lambda s:s.replace('inv/I\tinv/ZN\t^\tv\t','inv/I\tinv/ZN\t^\t^\t'),'RETENTION_ARC_POLARITY')


if __name__=='__main__':unittest.main()
