# SPDX-License-Identifier: Apache-2.0
"""Leaf provenance and evidence controls, independent of generated exports."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
import tkinter

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
        for kind in ('buf_2','clkbuf_3','clkbuf_4','clkbuf_8'):
            with self.subTest(kind=kind):
                before,after=fixture()
                after['modules']['RiscayMcuDigital']['cells']['branch']['type']=SC+kind
                index=leaf.LeafIndex(before,after,['branch'])
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
    def test_standalone_routed_script_uses_fresh_export_and_own_annotation(self):
        p,c,s,i=ack_fixture();c['state']=dict(cases=[],keeper_cuts=['keeper'])
        tool=SimpleNamespace(path=lambda p:str(p))
        script=leaf.script('original.v','tt_025C_3v30',.2,p,c,sta=tool,
                           routed_netlist='fresh-actual.v',spef='actual-min.spef')
        self.assertIn('read_verilog {fresh-actual.v}',script)
        self.assertNotIn('read_db',script)
        self.assertIn('report_parasitic_annotation -report_unannotated',script)
        self.assertIn('set_disable_timing -from A1 -to ZN [get_cells {keeper}]',script)
        self.assertIn('leaf_check_loop_cuts $roots $audit_targets',script)
        with self.assertRaisesRegex(ValueError,'LEAF_ROUTED_INPUT_PAIR'):
            leaf.script('original.v','tt_025C_3v30',.2,p,c,sta=tool,routed_netlist='fresh-actual.v')

    def test_routed_script_uses_actual_database_and_matching_sram_corner(self):
        p,c,s,i=ack_fixture();c['state']=dict(cases=[],keeper_cuts=[])
        tool=SimpleNamespace(path=lambda p:str(p))
        script=leaf.script('unused.v','ss_125C_3v00',.2,p,c,sta=tool,odb='actual.odb',spef='actual-min.spef')
        self.assertIn('read_db {actual.odb}',script)
        self.assertIn('read_spef {actual-min.spef}',script)
        self.assertNotIn('read_verilog',script)
        self.assertIn(leaf.SRAM+'__ss_125C_3v00.lib',script)
        with self.assertRaisesRegex(ValueError,'LEAF_ROUTED_INPUT_PAIR'):
            leaf.script('unused.v','ss_125C_3v00',.2,p,c,sta=tool,odb='actual.odb')

    def test_incomplete_spef_annotation_cannot_be_a_timing_pass(self):
        p,c,s,i=ack_fixture()
        for code in range(1640,1658):
            with self.subTest(code=code),self.assertRaisesRegex(ValueError,'LEAF_SPEF_ANNOTATION_INCOMPLETE'):
                leaf.parse(f'[WARNING STA-{code}] unmatched annotation\n'+s,p,c,.2,i)

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


class LoopCorridorTests(unittest.TestCase):
    def check(self, edges, *, targets=('target',), phase=('', ''), vertices=None):
        """Exercise the production Tcl on a graph with competing alternatives."""
        interp=tkinter.Tcl();interp.eval(leaf.SLEW_TCL);rows=[];iterator_count=0
        interp.createcommand('row',lambda *args: rows.append(args) or '')
        interp.createcommand('get_full_name',lambda pin: pin[2:])
        interp.createcommand('sta::pin_sim_logic_value',lambda pin:'X')
        nodes={'root',*targets,*[n for a,b,flags in edges for n in (a,b)]}
        def iterator(items):
            nonlocal iterator_count
            iterator_count+=1;name='iterator'+str(iterator_count);remaining=list(items)
            interp.createcommand(name,lambda method: bool(remaining) if method=='has_next' else
                                 remaining.pop(0) if method=='next' else '')
            return name
        def vertex(name,method):
            if method=='pin':return 'p_'+name
            return iterator('e'+str(i) for i,(a,b,_) in enumerate(edges) if b==name)
        for name in nodes:
            interp.createcommand('p_'+name,lambda method,n=name: (vertices or {}).get(n,('v_'+n,)))
            interp.createcommand('v_'+name,lambda method,n=name: vertex(n,method))
        for i,(a,b,flags) in enumerate(edges):
            values={'from':'v_'+a,'to':'v_'+b,'from_pin':'p_'+a,'to_pin':'p_'+b,
                    'role':'combinational','is_disabled_loop':False,'is_disabled_constant':False,
                    'is_disabled_constraint':False,'is_disabled_cond_default':False,
                    'sim_timing_sense':'positive_unate',
                    'to_string':a+' -> '+b,**flags}
            interp.createcommand('e'+str(i),lambda method,v=values:v[method])
        interp.call('leaf_check_loop_cuts',('p_root',),tuple('p_'+n for n in targets),*phase)
        return rows

    def test_automatic_cut_on_competing_path_is_rejected(self):
        graph=[('root','good',{}),('good','target',{}),('root','alternative',{}),
               ('alternative','target',{'is_disabled_loop':True})]
        with self.assertRaisesRegex(tkinter.TclError,'LEAF_ACTIVE_LOOP_CUT alternative -> target'):
            self.check(graph)
        for disable in ('is_disabled_constraint','is_disabled_cond_default'):
            enabled=deepcopy(graph);enabled[-1][2][disable]=True
            self.assertEqual(self.check(enabled)[0][0],'LEAF_LOOP_CUT_COVERAGE')
        graph[-1][2]['is_disabled_constant']=True
        with self.assertRaisesRegex(tkinter.TclError,'LEAF_ACTIVE_LOOP_CUT'):
            self.check(graph)
        graph[-1][2]['sim_timing_sense']='none'
        self.check(graph)

    def test_unrelated_cut_is_irrelevant_but_missing_target_fails(self):
        graph=[('root','target',{}),('elsewhere','other',{'is_disabled_loop':True})]
        self.check(graph)
        with self.assertRaisesRegex(tkinter.TclError,'LEAF_LOOP_TARGET_UNREACHABLE absent'):
            self.check(graph,targets=('target','absent'))

    def test_sequential_ack_includes_only_its_actual_clock_to_q(self):
        graph=[('root','clock',{}),('clock','q',{'role':'rising_edge'}),('q','target',{})]
        self.check(graph,phase=('clock','q'))
        with self.assertRaisesRegex(tkinter.TclError,'LEAF_LOOP_TARGET_UNREACHABLE'):
            self.check(graph)

    def test_missing_or_bidirectional_vertices_fail_closed(self):
        graph=[('root','middle',{}),('middle','target',{})]
        for pin,vs in (('root',()),('target',()),('middle',('v_middle','v_other'))):
            with self.subTest(pin=pin), self.assertRaisesRegex(tkinter.TclError,'LEAF_LOOP_PIN_VERTICES'):
                self.check(graph,vertices={pin:vs})


if __name__=='__main__':unittest.main()
