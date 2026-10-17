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
    def test_leaf_sdf_rejects_wire_delays(self):
        j.validate_leaf_sdf('(DELAYFILE (CELL (DELAY (ABSOLUTE (IOPATH I Z (1:1:1))))))')
        for kind in ('INTERCONNECT','PORT','NETDELAY','TIMINGCHECK'):
            with self.assertRaisesRegex(ValueError,'JOIN_LEAF_SDF_WIRE_OR_UNSUPPORTED'):
                j.validate_leaf_sdf('(DELAYFILE ('+kind+' a b (1:1:1)))')

    def test_leaf_paths_allow_only_selected_click_storage(self):
        p,_=fixture('click');ctx=dict(side='left',kind='launch')
        cells={k:dict(type=j.SC+kind,connections={x:[] for x in pins}) for k,kind,pins in
               [('fire','buf_1',['Z']),('left/store','dffrnq_1',['CLK','Q']),
                ('other','dffrnq_1',['CLK','Q']),('update/store','dffrnq_1',['D'])]}
        points=['fire/Z','left/store/CLK','left/store/Q','update/store/D']
        j.validate_leaf_paths({'q':points},p,ctx,cells)
        with self.assertRaisesRegex(ValueError,'JOIN_LEAF_INTERMEDIATE_STORAGE'):
            j.validate_leaf_paths({'q':points[:3]+['other/CLK','other/Q']+points[3:]},p,ctx,cells)
        with self.assertRaisesRegex(ValueError,'JOIN_LEAF_PATH_PIN'):
            j.validate_leaf_paths({'q':points+['missing/D']},p,ctx,cells)

    def test_parent_ack_guard_is_an_explicit_channel_route(self):
        join=dict(connections=dict(reset=[1],out_ack=[2],out_req=[3],out_bits_left=[4],out_bits_right=[5]))
        sink=dict(connections=dict(reset=[1],in_ack=[6],in_req=[3],in_bits_left=[4],in_bits_right=[5],out_ack=[7]),
                  port_directions=dict(reset='input',in_ack='output',in_req='input',in_bits_left='input',in_bits_right='input',out_ack='input'))
        guard=dict(a=[6],q=[2],b=['0'],reset=[1])
        args=(dict(cells={}),join,sink,dict(left='left',right='right'),{})
        self.assertEqual(len(j.bind_inputs(*args,guard)),4)
        with self.assertRaisesRegex(ValueError,'JOIN_UPDATE_WIRING'):j.bind_inputs(*args)
        for pin in ('a','q','b','reset'):
            bad=deepcopy(guard);bad[pin]=[99]
            with self.assertRaisesRegex(ValueError,'JOIN_ACK_GUARD_WIRING'):j.bind_inputs(*args,bad)

    def test_identity_storage_checks_each_lane_not_just_width(self):
        b=dict(ports=dict(in_bits=dict(bits=[2,3]),out_bits=dict(bits=[4,5])),
            cells=dict(ca_primitive_payload=dict(connections=dict(d=[6,7],q=[4,5])),
                       ca_primitive_data_delay=dict(connections=dict(a=[2,3],q=[6,7]))))
        j.identity_storage(b)
        b['cells']['ca_primitive_data_delay']['connections']['a']=[3,2]
        with self.assertRaisesRegex(ValueError,'^JOIN_IDENTITY_DATA$'):j.identity_storage(b)

    def test_bd_q_before_close_and_conservative_latest_close(self):
        p,r=fixture();s=j.margins(r,p,dict(setup_ns=1))[0]
        self.assertEqual(s['maximum_input_data_lag_ns'],5) # min(10-2-1,10-2-3)
        self.assertEqual(s['minimum_conditional_setup_margin_ns'],12) # 30-12-5-1

    def test_click_uses_clock_q_arrival_without_added_latch_close(self):
        p,r=fixture('click');s=j.margins(r,p,dict(setup_ns=1))
        self.assertEqual(len(s),4)
        self.assertTrue(all(v['maximum_input_data_lag_ns']==7 and v['minimum_conditional_setup_margin_ns']==24 for v in s))

    def test_delayed_capture_exposes_bd_failure(self):
        p,r=fixture();r['left-request-0']['rows']['source_capture:0:max:fall']['delay_ns']=100
        self.assertEqual(j.margins(r,p,dict(setup_ns=1))[0]['minimum_conditional_setup_margin_ns'],-76)

    def test_bd_annotation_must_match_arc_slew(self):
        p,r=fixture();r['left-launch-0']['source_slews']['0'][1]=0
        with self.assertRaisesRegex(ValueError,'^JOIN_DQ_SLEW_CHANGED$'):j.margins(r,p,dict(setup_ns=1))

    def test_click_launch_slew_must_match_each_request_phase(self):
        for phase in (0,1):
            for mode in (0,1):
                p,r=fixture('click');r[f'left-request-{phase}']['event_slews'][mode]+=.1
                with self.assertRaisesRegex(ValueError,'^JOIN_EVENT_SLEW_CHANGED$'):j.margins(r,p,dict(setup_ns=1))

    def test_unmodeled_dynamic_lane_is_rejected(self):
        p,_=fixture()
        with patch.object(j,'reachable_lanes',return_value=[]):
            with self.assertRaisesRegex(ValueError,'^JOIN_DYNAMIC_LANE_COVERAGE$'):j.contexts(p,[])

    def test_only_independently_literal_lanes_can_be_absent(self):
        p,_=fixture();p['stages']['update']['constant_lanes']={'0':0}
        with patch.object(j,'reachable_lanes',return_value=[]),patch.object(j,'state',return_value={}):
            cs=j.contexts(p,[])
        self.assertTrue(all(c['absent_lanes']==[0] for c in cs if c['kind']=='launch'))

    def test_sequential_cell_does_not_fake_combinational_reachability(self):
        cells=[dict(path='left/store',cell=j.SC+'latrnq_1',pins=dict(D='in',Q='q',E='e'),directions=dict(D='input',Q='output',E='input')),
               dict(path='hidden',cell=j.SC+'dffrnq_1',pins=dict(D='q',Q='x',CLK='clk'),directions=dict(D='input',Q='output',CLK='input')),
               dict(path='update/store',cell=j.SC+'latrnq_1',pins=dict(D='x',Q='out',E='e'),directions=dict(D='input',Q='output',E='input'))]
        p,_=fixture();self.assertEqual(j.reachable_lanes(cells,p['stages']['left'],p['stages']['update']),[])
        cells[1]=dict(path='wire',cell=j.SC+'buf_1',pins=dict(I='q',Z='x'),directions=dict(I='input',Z='output'))
        self.assertEqual(j.reachable_lanes(cells,p['stages']['left'],p['stages']['update']),[0])


def request_log():
    p,_=fixture('bd');c=next(c for c in p['contexts'] if c['id']=='left-request-0')
    c['queries']=[q for q in c['queries'] if q['role']=='source_capture']
    text='JOIN_BEGIN\n'
    for q in c['queries']:
        delay=10 if q['mode']=='min' else 12
        text+=f"CONTROL_PATH\t{q['id']}\t0\t{delay}\t{delay}\t{delay}\t.5\tjoin_left_req\tleft/store/E\trise\tfall\n"
        text+=f"CONTROL_POINTS\t{q['id']}\tjoin_left_req\tleft/request_delay/Z\tleft/a/Z\tleft/long_hold/Z\tleft/store/E\n"
    return p,c,text+'JOIN_ELECTRICAL_BEGIN\nJOIN_ELECTRICAL_END\nJOIN_COMPLETE\n'


class ParserTests(unittest.TestCase):
    def test_period_control_checks_noncritical_lanes_and_slews(self):
        from check_control_join_controls import check_period
        baseline=dict(rows={'critical':10,'noncritical':2},source_slew=.5,paths=['source','sink'])
        check_period(baseline,baseline,{'minimum':10},{'minimum':10})
        for key,value in [('rows',dict(critical=10,noncritical=3)),('source_slew',.6),('paths',['sibling','sink'])]:
            changed=deepcopy(baseline);changed[key]=value
            with self.assertRaisesRegex(ValueError,'^JOIN_CONTROL_PERIOD_DEPENDENCE$'):
                check_period(changed,baseline,{'minimum':10},{'minimum':10})

    def reject(self,change,diagnostic):
        p,c,log=request_log()
        with self.assertRaisesRegex(ValueError,'^'+diagnostic+'$'):j.parse(change(log),p,c)

    def test_request_pair(self):
        p,c,log=request_log();self.assertEqual(len(j.parse(log,p,c)['rows']),2)

    def test_reversed_bounds(self):
        self.reject(lambda s:s.replace('\t0\t10\t10\t10\t','\t0\t20\t20\t20\t'),'JOIN_REVERSED_BOUNDS')

    def test_nonfinite_slew(self):
        self.reject(lambda s:s.replace('\t.5\t','\tINF\t'),'JOIN_NUMERIC')

    def test_wrong_side(self):
        self.reject(lambda s:s.replace('\tjoin_left_req\t','\tjoin_right_req\t'),'JOIN_COMBINATIONAL_SOURCE')

    def test_wrong_capture_pin(self):
        self.reject(lambda s:s.replace('left/store/E','right/store/E'),'JOIN_PATH_BINDING')

    def test_wrong_transition(self):
        self.reject(lambda s:s.replace('\trise\tfall\n','\tfall\tfall\n'),'JOIN_PATH_BINDING')

    def test_missing_path(self):
        self.reject(lambda s:'\n'.join(l for l in s.split('\n') if 'source_capture:0:max' not in l),'JOIN_QUERY_COVERAGE')

    def test_incomplete(self):
        self.reject(lambda s:s.replace('JOIN_COMPLETE\n',''),'JOIN_INCOMPLETE')

    def test_tool_error_is_not_missing_coverage(self):
        self.reject(lambda s:'Warning: invalid\n'+s,'JOIN_TOOL_DIAGNOSTIC')

    def test_no_fake_clock_phase_arrival_at_request_port(self):
        self.reject(lambda s:s.replace('\t0\t10\t10\t10\t','\t500\t510\t10\t10\t'),'JOIN_INPUT_ARRIVAL')

    def test_direct_source_control_path_required(self):
        self.reject(lambda s:s.replace('left/a/Z','left/return/Z'),'JOIN_SOURCE_CONTROL_PROVENANCE')


class StorageDescriptorTests(unittest.TestCase):
    def values(self,variant):
        from test_native_stage_timing import fixture as stage_fixture
        m,n,r,path,v=stage_fixture(variant)
        family='LongHoldBuffer' if variant=='bd' else 'ClickBuffer';old=m['design']['module'];module=family+'_99'
        m['design']['module']=module
        for e in m['design']['endpoints']:
            e['source']=e['source'].replace(old,module)
            if e['id']=='in_data':e['width']=2
        mapped='FourPhaseStage' if variant=='bd' else 'ClickStage'
        n['modules'][family]=n['modules'].pop(mapped);n['modules']['Soc']['cells']['ca_child_stage']['type']=family
        return m,n,r,path,v

    def test_buffers_require_explicit_storage_mode(self):
        for variant in ('bd','click'):
            values=self.values(variant)
            with self.assertRaisesRegex(ValueError,'^STAGE_UNSUPPORTED_CONTROLLER$'):j.stages.descriptor(*values)
            self.assertEqual(j.stages.descriptor(*values,storage=True)['payload_width'],2)

    def test_nonidentity_width_rejected(self):
        values=self.values('bd');next(e for e in values[0]['design']['endpoints'] if e['id']=='in_data')['width']=3
        with self.assertRaisesRegex(ValueError,'^STAGE_STORAGE_WIDTH$'):j.stages.descriptor(*values,storage=True)


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

    def test_register_permutation_tieoff_and_wrong_width_reject(self):
        for value in ([21,20],['0','0'],[20]):
            args=self.fixture();args[2]['connections']['in_bits_registers_0']=value
            with self.assertRaisesRegex(ValueError,'^JOIN_SIDE_INPUT_BINDING$'):j.bind_inputs(*args)

    def test_duplicated_declared_source_cannot_fake_coverage(self):
        args=self.fixture();args[0]['cells']['rf']['connections']['values_1']=[20,21]
        args[2]['connections']['in_bits_registers_1']=[20,21]
        with self.assertRaisesRegex(ValueError,'^JOIN_SIDE_INPUT_ALIAS$'):j.bind_inputs(*args)

    def test_constant_side_source_is_not_an_independent_launch(self):
        args=self.fixture();args[0]['cells']['rf']['connections']['values_0']=['0','1']
        args[2]['connections']['in_bits_registers_0']=['0','1']
        with self.assertRaisesRegex(ValueError,'^JOIN_SIDE_INPUT_ALIAS$'):j.bind_inputs(*args)

    def test_extra_input_and_omitted_rf_are_not_covered_by_destination_union(self):
        for extra in (False,True):
            args=self.fixture()
            if extra:
                args[2]['connections']['in_bits_hidden']=[24];args[2]['port_directions']['in_bits_hidden']='input'
            else:del args[4]['in_bits_registers_0']
            with self.assertRaisesRegex(ValueError,'^JOIN_INPUT_COVERAGE$'):j.bind_inputs(*args)

    def test_operand_field_permutation_rejects(self):
        args=self.fixture();args[3].update(left='response',right='state')
        with self.assertRaisesRegex(ValueError,'^JOIN_UPDATE_WIRING$'):j.bind_inputs(*args)

    def test_overlapping_rf_path_remains_a_separate_obligation(self):
        cells=[dict(path='mux',cell=j.SC+'mux2_1',pins=dict(I0='join',I1='rf',S='select',Z='d'),
                    directions=dict(I0='input',I1='input',S='input',Z='output')),
               dict(path='sink/store',cell=j.SC+'latrnq_1',pins=dict(D='d',Q='q',E='e'),
                    directions=dict(D='input',Q='output',E='input'))]
        dest=dict(prefix='sink/',lane_map=[dict(lane=0,D='store/D')])
        self.assertEqual(j.reachable_from(cells,{'join'},dest),[0])
        self.assertEqual(j.reachable_from(cells,{'rf'},dest),[0])

    def test_execute_selection_enumerates_all_fifteen_banks(self):
        for variant in ('bd','click'):
            config=j.selection(variant,'execute')
            self.assertEqual(sum(s['width'] for s in config['side_inputs'].values()),480)
            self.assertEqual(len(config['side_inputs']),15)
        with self.assertRaisesRegex(ValueError,'^JOIN_TARGET$'):j.selection('bd','elapsed')


if __name__=='__main__':unittest.main()
