# SPDX-License-Identifier: Apache-2.0
"""Adversarial controls for the graph that global electrical repair may change."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
import json
from gf180_physical import SC, SRAM
from repair_gf180_design import (graph_proof, validate_receipt, split_output_feedback, correct_scalar_port_escaping,
    buffer_native_resets, buffer_sram_clocks, validate_sram_clock_drivers, prune_added_orphan_ties, EVIDENCE, sha)


def cell(kind, **pins):
    return dict(type=SC+kind,connections={p:[b] for p,b in pins.items()},
        port_directions={p:'output' if p in ('Z','ZN','Q') else 'input' for p in pins})


BUF='pin(I){direction:input;} pin(Z){direction:output; function:"I";}'
INV='pin(I){direction:input;} pin(Z){direction:output; function:"!I";}'
LIB={SC+'buf_1':BUF,SC+'buf_2':BUF,SC+'buf_16':BUF,SC+'inv_1':INV,
     SC+'tieh':'pin(Z){direction:output; function:"1";}',
     SC+'tiel':'pin(ZN){direction:output; function:"0";}',
     SC+'dff_1':'ff(IQ,IQN){clocked_on:"I";} '+BUF,
     SC+'dff_2':'ff(IQ,IQN){clocked_on:"I";} '+BUF}


def fixture():
    return dict(modules={'top':dict(ports={'in':dict(direction='input',bits=[1]),
        'out':dict(direction='output',bits=[3])},cells={
        'driver':cell('buf_1',I=1,Z=2),'sink':cell('inv_1',I=2,Z=3)})})


def buffered():
    b=fixture();c=b['modules']['top']['cells'];c['distribution']=cell('buf_2',I=2,Z=4);c['sink']['connections']['I']=[4]
    return b


class GlobalRepairTest(unittest.TestCase):
    def proof(self,before,after,protected=None):
        return graph_proof(before,after,'top',protected or {},[LIB]*5)

    def test_three_sram_clocks_keep_exact_macros_and_get_exclusive_drivers(self):
        a=dict(modules=dict(top=dict(ports={'clk':dict(direction='input',bits=[1])},cells={
            'ram'+str(i):dict(type=SRAM,connections=dict(CLK=[1],Q=[i+2]),
                            port_directions=dict(CLK='input',Q='output')) for i in range(3)})))
        b=deepcopy(a);report=buffer_sram_clocks(b,'top')
        self.assertEqual(len(report),3)
        self.assertEqual(len(self.proof(a,b)['added_buffers']),3)
        self.assertEqual({b['modules']['top']['cells'][r['owner']]['type'] for r in report},{SRAM})
        self.assertEqual(len({tuple(b['modules']['top']['cells'][r['buffer']]['connections']['Z']) for r in report}),3)
        self.assertEqual(validate_sram_clock_drivers(b,'top'),report)
        # Whole-graph contraction alone deliberately permits a shared buffer.
        # The final physical clock check must reject that electrically bad case.
        bad=deepcopy(b);cells=bad['modules']['top']['cells'];first=report[0]['buffer']
        for r in report[1:]:
            cells[r['owner']]['connections']['CLK']=cells[first]['connections']['Z']
            del cells[r['buffer']]
        self.proof(a,bad)
        with self.assertRaisesRegex(ValueError,'REPAIR_SRAM_CLOCK_EXCLUSIVE'):
            validate_sram_clock_drivers(bad,'top')
        cells=b['modules']['top']['cells'];cells[first]['type']=SC+'inv_1'
        cells[first]['connections']['ZN']=cells[first]['connections'].pop('Z')
        cells[first]['port_directions']['ZN']=cells[first]['port_directions'].pop('Z')
        with self.assertRaisesRegex(ValueError,'REPAIR_SRAM_CLOCK_NONINVERTING'):
            validate_sram_clock_drivers(b,'top')

    def test_shared_sram_parent_is_edited_once_and_counted_three_times(self):
        wrapper=dict(ports={'clk':dict(direction='input',bits=[1]),'q':dict(direction='output',bits=[2])},cells=dict(
            ram=dict(type=SRAM,connections=dict(CLK=[1],Q=[2]),port_directions=dict(CLK='input',Q='output'))))
        top=dict(ports={'clk':dict(direction='input',bits=[1])},cells={
            'bank'+str(i):dict(type='wrapper',connections=dict(clk=[1],q=[i+2]),port_directions=dict(clk='input',q='output')) for i in range(3)})
        a=dict(modules=dict(top=top,wrapper=wrapper));b=deepcopy(a)
        report=buffer_sram_clocks(b,'top')
        self.assertEqual(len(report),3)
        self.assertEqual(len(b['modules']['wrapper']['cells']),2)
        self.assertEqual(len(self.proof(a,b)['added_buffers']),3)
        del a['modules']['top']['cells']['bank2']
        with self.assertRaisesRegex(ValueError,'REPAIR_SRAM_COUNT'):buffer_sram_clocks(a,'top')

    def reject(self,after,diagnostic,before=None,protected=None):
        with self.assertRaisesRegex(ValueError,diagnostic):self.proof(before or fixture(),after,protected)

    def test_buffer_and_equivalent_drive_resize(self):
        b=buffered();b['modules']['top']['cells']['driver']['type']=SC+'buf_2'
        p=self.proof(fixture(),b)
        self.assertEqual(len(p['added_buffers']),1);self.assertEqual(len(p['resized']),1)

    def test_pin_and_net_number_changes_are_independent(self):
        b=buffered()
        for p in b['modules']['top']['ports'].values():p['bits']=[x+10 for x in p['bits']]
        for c in b['modules']['top']['cells'].values():
            c['connections']={p:[x+10 for x in bs] for p,bs in c['connections'].items()}
        self.proof(fixture(),b)




    def test_rewired_sink_rejected(self):
        b=fixture();b['modules']['top']['cells']['sink']['connections']['I']=[1]
        self.reject(b,'REPAIR_GRAPH_CHANGED')



    def test_hidden_duplicate_driver_rejected_before_contraction(self):
        b=buffered();b['modules']['top']['cells']['driver']['connections']['Z']=[4]
        self.reject(b,'REPAIR_MULTIPLE_DRIVERS')

    def test_unused_buffer_rejected(self):
        b=buffered();b['modules']['top']['cells']['sink']['connections']['I']=[2]
        self.reject(b,'REPAIR_UNUSED_BUFFER')


    def native(self):
        a=fixture();a['modules']['owner']=dict(ports={'I':dict(direction='input',bits=[1]),
            'Q':dict(direction='output',bits=[2])},cells={'keeper':cell('keeper',I=1,FB=2,Q=2)})
        a['modules']['top']['cells']['driver']=dict(type='owner',port_directions={'I':'input','Q':'output'},connections={'I':[1],'Q':[2]})
        return a

    def test_native_boundary_buffer_allowed(self):
        a=self.native();b=deepcopy(a);c=b['modules']['top']['cells'];c['distribution']=cell('buf_2',I=2,Z=4)
        c['sink']['connections']['I']=[4];self.proof(a,b,{'driver/keeper':'driver'})

    def test_buffer_inside_native_feedback_rejected(self):
        a=self.native();b=deepcopy(a);c=b['modules']['owner']['cells'];c['distribution']=cell('buf_2',I=2,Z=4)
        c['keeper']['connections']['FB']=[4]
        self.reject(b,'REPAIR_NATIVE_INTERNAL_BUFFER',a,{'driver/keeper':'driver'})


    def test_tie_driver_must_match_original_constant(self):
        a=fixture();a['modules']['top']['cells']['driver']['connections']['I']=['1']
        b=deepcopy(a);c=b['modules']['top']['cells'];c['supply']=cell('tieh',Z=4);c['driver']['connections']['I']=[4]
        self.assertEqual(self.proof(a,b)['added_ties'],['supply'])
        c['supply']=cell('tiel',ZN=4)
        self.reject(b,'REPAIR_GRAPH_CHANGED',a)

    def test_unused_tie_requires_original_native_constant_port(self):
        a=self.native();a['modules']['owner']['ports']['unused']=dict(direction='output',bits=['1'])
        b=deepcopy(a);b['modules']['top']['cells']['supply']=cell('tieh',Z=4)
        b['modules']['top']['cells']['driver']['connections']['unused']=[4]
        b['modules']['owner']['ports']['unused']['bits']=[5]
        # The driver sits outside the protected native implementation. The
        # otherwise unused port still has to retain its original constant.
        self.proof(a,b,{'driver/keeper':'driver'})
        self.reject(b,'REPAIR_UNUSED_BUFFER',a)
        b['modules']['top']['cells']['supply']=cell('tiel',ZN=4)
        self.reject(b,'REPAIR_NATIVE_CONNECTIVITY',a,{'driver/keeper':'driver'})

    def test_stage_and_join_require_repair_before_any_output(self):
        import native_stage_timing,control_join_timing
        with TemporaryDirectory() as t:
            p=Path(t);mapping=p/'mapping';mapping.mkdir()
            for runner in (lambda out:native_stage_timing.run(mapping,out,'bd',['stage']),
                           lambda out:control_join_timing.run(mapping,out,'bd')):
                out=p/'out'
                with self.assertRaisesRegex(ValueError,'REPAIR_RECEIPT_REQUIRED'):runner(out)
                self.assertFalse(out.exists())

    def test_only_unused_constant_native_inputs_may_be_omitted(self):
        a=self.native();a['modules']['owner']['ports']['unused']=dict(direction='input',bits=[8])
        a['modules']['top']['cells']['driver']['connections']['unused']=['0']
        b=deepcopy(a);del b['modules']['owner']['ports']['unused']
        del b['modules']['top']['cells']['driver']['connections']['unused']
        protected={'driver/keeper':'driver'}
        self.assertEqual(self.proof(a,b,protected)['omitted_dead_native_inputs'],[
            dict(port='driver/unused',direction='input',width=1,constants=['0'])])
        for mode in ('dynamic','output','used'):
            bad=deepcopy(a)
            if mode=='dynamic':bad['modules']['top']['cells']['driver']['connections']['unused']=[1]
            if mode=='output':bad['modules']['owner']['ports']['unused']['direction']='output'
            if mode=='used':bad['modules']['owner']['cells']['keeper']['connections']['I']=[8]
            self.reject(b,'REPAIR_NATIVE_PORT_REMOVED',bad,protected)

    def test_feedback_split_preserves_native_driver_and_every_consumer(self):
        a=fixture();m=a['modules']['top']
        a['modules']['source']=dict(ports={'I':dict(direction='input',bits=[1]),
            'Q':dict(direction='output',bits=[2])},cells={'leaf':cell('buf_1',I=1,Z=2)})
        m['cells']['driver']=dict(type='source',port_directions={'I':'input','Q':'output'},connections={'I':[1],'Q':[2]})
        m['ports']['observe']=dict(direction='output',bits=[2,'0'])
        b=deepcopy(a);changes=split_output_feedback(b,'top')
        self.assertEqual(len(changes),1)
        p=self.proof(a,b,{'driver/leaf':'driver'})
        self.assertEqual(len(p['added_buffers']),1)
        self.assertEqual(b['modules']['top']['ports'],m['ports'])
        self.assertEqual(b['modules']['source'],a['modules']['source'])
        # An output fed directly by a primitive leaf is not an alias adapter;
        # neither is the leaf's own keeper feedback a permissible split.
        direct=fixture();direct['modules']['top']['ports']['observe']=dict(direction='output',bits=[2,'0'])
        self.assertEqual(split_output_feedback(direct,'top'),[])
        recursive=deepcopy(a);recursive['modules']['top']['cells']['driver']['connections']['I']=[2]
        self.assertEqual(split_output_feedback(recursive,'top'),[])

    def feedback_passthrough(self):
        a=fixture();m=a['modules']['top']
        a['modules']['source']=dict(ports={'I':dict(direction='input',bits=[1]),
            'Q':dict(direction='output',bits=[2])},cells={'leaf':cell('buf_1',I=1,Z=2)})
        a['modules']['pass']=dict(ports={'I':dict(direction='input',bits=[1]),
            'Q':dict(direction='output',bits=[1])},cells={})
        m['cells']['driver']=dict(type='source',port_directions={'I':'input','Q':'output'},connections={'I':[1],'Q':[2]})
        m['cells']['sink']=dict(type='pass',port_directions={'I':'input','Q':'output'},connections={'I':[2],'Q':[3]})
        m['ports']['observe']=dict(direction='output',bits=[2,'0'])
        return a

    def test_feedback_passthrough_to_top_output_is_a_live_consumer(self):
        a=self.feedback_passthrough();b=deepcopy(a);skipped=[]
        self.assertEqual(len(split_output_feedback(b,'top',skipped=skipped)),1)
        self.assertEqual(skipped,[])
        self.assertEqual(len(self.proof(a,b,{'driver/leaf':'driver'})['added_buffers']),1)

    def test_feedback_declared_but_unused_child_lane_gets_no_buffer(self):
        a=self.feedback_passthrough();del a['modules']['top']['ports']['out']
        b=deepcopy(a);skipped=[]
        self.assertEqual(split_output_feedback(b,'top',skipped=skipped),[])
        self.assertEqual(b,a)
        self.assertEqual(len(skipped),1)
        self.assertEqual(skipped[0]['instances'],['riscay_output_feedback_2'])
        self.proof(a,b,{'driver/leaf':'driver'})

    def test_feedback_shared_module_liveness_must_agree_for_every_instance(self):
        a=self.feedback_passthrough();wrapper=a['modules'].pop('top');a['modules']['wrapper']=wrapper
        a['modules']['top']=dict(ports={'in':dict(direction='input',bits=[1]),
            'out':dict(direction='output',bits=[3])},cells={
            n:dict(type='wrapper',port_directions={'in':'input','out':'output','observe':'output'},
                connections={'in':[1],'out':[3] if n=='a' else [],'observe':[]}) for n in ('a','b')})
        with self.assertRaisesRegex(ValueError,'REPAIR_FEEDBACK_SHARED_LIVENESS'):
            split_output_feedback(a,'top')

    def test_existing_repair_rejected_before_synthesis_writes(self):
        from gf180_implement import synth
        with TemporaryDirectory() as t:
            p=Path(t);(p/'electrical-repair').mkdir();(p/'netlist.v').write_text('retained')
            with self.assertRaisesRegex(ValueError,'REPAIR_FRESH_MAPPING_REQUIRED'):synth(p,p)
            self.assertEqual((p/'netlist.v').read_text(),'retained')

    def reset_native(self):
        a=self.native();m=a['modules']['top'];owner=a['modules']['owner']
        m['ports']['reset']=dict(direction='input',bits=[8])
        m['cells']['driver']['connections']['reset']=[8]
        m['cells']['driver']['port_directions']['reset']='input'
        owner['ports']['reset']=dict(direction='input',bits=[5])
        owner['cells']['keeper']['connections']['RESET']=[5]
        owner['cells']['keeper']['port_directions']['RESET']='input'
        return a

    def test_reset_buffer_is_outside_native_owner_and_counted(self):
        a=self.reset_native();b=deepcopy(a)
        report=buffer_native_resets(b,'top',{'native':'driver'})
        self.assertEqual(b['modules']['owner'],a['modules']['owner'])
        self.assertEqual(report,[dict(owner='driver',port='reset',buffer='riscay_native_reset_0',master=SC+'buf_1')])
        proof=self.proof(a,b,{'driver/keeper':'driver'})
        self.assertEqual(proof['added_buffers'],['riscay_native_reset_0'])
        self.assertEqual(b['modules']['top']['cells']['riscay_native_reset_0']['connections']['I'],[8])

    def test_reset_boundary_shape_and_exact_path_are_required(self):
        a=self.reset_native()
        with self.assertRaisesRegex(ValueError,'REPAIR_RESET_ADAPTER_MISSING'):
            buffer_native_resets(a,'top',{'native':'not_the_owner'})
        a['modules']['owner']['ports']['reset']['bits'].append(6)
        with self.assertRaisesRegex(ValueError,'REPAIR_RESET_BOUNDARY_SHAPE'):
            buffer_native_resets(a,'top',{'native':'driver'})

    def test_shared_reset_wrapper_counts_each_physical_buffer(self):
        a=self.reset_native();top=a['modules'].pop('top');a['modules']['wrapper']=top
        a['modules']['top']=dict(ports={'in':dict(direction='input',bits=[1]),
            'reset':dict(direction='input',bits=[2]),'out0':dict(direction='output',bits=[3]),
            'out1':dict(direction='output',bits=[4])},cells={
            n:dict(type='wrapper',port_directions={'in':'input','reset':'input','out':'output'},
                connections={'in':[1],'reset':[2],'out':[i+3]}) for i,n in enumerate(('a','b'))})
        b=deepcopy(a);report=buffer_native_resets(b,'top',{'one':'a/driver','two':'b/driver'})
        self.assertEqual(len(report),2)
        self.assertEqual(len(b['modules']['wrapper']['cells'])-len(top['cells']),1)
        self.assertEqual(len(self.proof(a,b,{'a/driver/keeper':'a/driver','b/driver/keeper':'b/driver'})['added_buffers']),2)

    def passive_native(self):
        a=self.reset_native()
        a['modules']['allowance']=dict(ports={'a':dict(direction='input',bits=[1,2]),
            'q':dict(direction='output',bits=[1,2])},cells={})
        a['modules']['top']['cells']['data']=dict(type='allowance',
            port_directions={'a':'input','q':'output'},connections={'a':[1,8],'q':[1,8]})
        binding=dict(model='ChiselAsyncPassiveDataAllowance_v1',module='allowance',
            parameters=dict(WIDTH=2,DELAY_FS=10000),instances=['data_native'],cells=[],
            aliases=[['q[0]','a[0]'],['q[1]','a[1]']])
        return a,[dict(model='ChiselAsyncBuffer_v1',instances=['native']),binding]

    def test_only_proved_passive_alias_skips_reset_distribution(self):
        a,bindings=self.passive_native();b=deepcopy(a);aliases=[]
        report=buffer_native_resets(b,'top',{'native':'driver','data_native':'data'},
            bindings=bindings,reset_free_aliases=aliases)
        self.assertEqual(len(report),1)
        self.assertEqual(b['modules']['allowance'],a['modules']['allowance'])
        self.assertEqual(b['modules']['top']['cells']['data'],a['modules']['top']['cells']['data'])
        self.assertEqual(aliases,[dict(instance='data_native',owner='data',
            model='ChiselAsyncPassiveDataAllowance_v1',width=2,
            reason='proved-cell-free-data-alias-with-no-reset-load')])
        self.assertEqual(len(self.proof(a,b,{'driver/keeper':'driver'})['added_buffers']),1)

    def test_resetless_alias_requires_exact_model_and_instance_binding(self):
        for mutation,error in (
            (lambda bs:bs[1].update(model='ChiselAsyncBuffer_v1'),'REPAIR_RESET_BOUNDARY_SHAPE'),
            (lambda bs:bs[1].update(module='other'),'REPAIR_RESET_ALIAS_IDENTITY'),
            (lambda bs:bs[1].update(instances=['other']),'REPAIR_RESET_BINDING_MISSING'),
            (lambda bs:bs.append(deepcopy(bs[1])),'REPAIR_RESET_BINDING_DUPLICATE')):
            with self.subTest(error=error):
                a,bindings=self.passive_native();mutation(bindings)
                with self.assertRaisesRegex(ValueError,error):
                    buffer_native_resets(a,'top',{'native':'driver','data_native':'data'},bindings=bindings)
        a,_=self.passive_native()
        with self.assertRaisesRegex(ValueError,'REPAIR_RESET_BOUNDARY_SHAPE'):
            buffer_native_resets(a,'top',{'data_native':'data'})

    def test_resetless_alias_complete_module_and_instance_shape_are_checked(self):
        mutations=(
            (lambda a,b:a['modules']['allowance']['cells'].update(hidden=cell('buf_1',I=1,Z=2)),
                'PASSIVE_ALIAS_HAS_CELLS'),
            (lambda a,b:a['modules']['allowance']['ports']['q'].update(bits=[2,1]),
                'PASSIVE_ALIAS_CONNECTION'),
            (lambda a,b:b[1].update(aliases=[['q[0]','a[1]'],['q[1]','a[0]']]),
                'PASSIVE_ALIAS_LAYOUT'),
            (lambda a,b:a['modules']['allowance']['ports'].update(reset=dict(direction='input',bits=[3])),
                'PASSIVE_ALIAS_PORTS'),
            (lambda a,b:a['modules']['top']['cells']['data']['connections'].update(q=[1]),
                'REPAIR_RESET_ALIAS_INSTANCE_PORTS'),
            (lambda a,b:a['modules']['top']['cells']['data']['port_directions'].update(q='input'),
                'REPAIR_RESET_ALIAS_INSTANCE_PORTS'))
        for mutation,error in mutations:
            with self.subTest(error=error):
                a,bindings=self.passive_native();mutation(a,bindings)
                with self.assertRaisesRegex(ValueError,error):
                    buffer_native_resets(a,'top',{'native':'driver','data_native':'data'},bindings=bindings)

    def test_orphan_cleanup_removes_only_added_ties(self):
        a=fixture();a['modules']['top']['cells']['original_tie']=cell('tiel',ZN=7)
        b=deepcopy(a);b['modules']['top']['cells']['added_tie']=cell('tieh',Z=8)
        removed=prune_added_orphan_ties(a,b,'top',{},[LIB]*5)
        self.assertEqual([r['cell'] for r in removed],['added_tie'])
        self.assertIn('original_tie',b['modules']['top']['cells'])
        self.assertEqual(self.proof(a,b)['added_ties'],[])



    def test_cleanup_preserves_unconsumed_native_constant_output(self):
        a=self.native();a['modules']['owner']['ports']['unused']=dict(direction='output',bits=['1'])
        b=deepcopy(a);b['modules']['top']['cells']['supply']=cell('tieh',Z=4)
        b['modules']['top']['cells']['driver']['connections']['unused']=[4]
        b['modules']['owner']['ports']['unused']['bits']=[5]
        protected={'driver/keeper':'driver'}
        self.assertEqual(prune_added_orphan_ties(a,b,'top',protected,[LIB]*5),[])
        self.proof(a,b,protected)

    def test_cleanup_rejects_partially_live_shared_tie(self):
        a=fixture();a['modules']['source']=dict(ports={'out':dict(direction='output',bits=['0'])},cells={})
        a['modules']['top']['cells']['a']=dict(type='source',port_directions={'out':'output'},connections={'out':[4]})
        a['modules']['top']['cells']['b']=dict(type='source',port_directions={'out':'output'},connections={'out':[]})
        a['modules']['top']['cells']['sink']['connections']['I']=[4]
        b=deepcopy(a);b['modules']['source']['ports']['out']['bits']=[5]
        b['modules']['source']['cells']['tie']=cell('tiel',ZN=5)
        with self.assertRaisesRegex(ValueError,'REPAIR_ORPHAN_TIE_SHARED_MODULE'):
            prune_added_orphan_ties(a,b,'top',{},[LIB]*5)

    def test_cleanup_does_not_hide_multiple_drivers(self):
        a=fixture();a['modules']['top']['cells']['original_tie']=cell('tieh',Z=7)
        b=deepcopy(a);b['modules']['top']['cells']['added_tie']=cell('tiel',ZN=7)
        with self.assertRaisesRegex(ValueError,'REPAIR_ORPHAN_TIE_MULTIPLE_DRIVERS'):
            prune_added_orphan_ties(a,b,'top',{},[LIB]*5)

    def test_exact_declared_scalar_reference_is_escaped(self):
        raw='module m(a);\n input \\owner_bus[3] ;\n buf u(.I(owner_bus[3]), .Z(a));\nendmodule\n'
        fixed,edits=correct_scalar_port_escaping(raw)
        self.assertEqual(fixed,raw.replace('.I(owner_bus[3])','.I(\\owner_bus[3] )'))
        self.assertEqual(edits,[dict(module='m',identifier='owner_bus[3]',offsets=[raw.index('owner_bus[3]),')])])
        self.assertEqual(correct_scalar_port_escaping(fixed),(fixed,[]))

    def test_valid_bus_and_other_module_are_unchanged(self):
        raw='module m(a);\n input [3:0] owner_bus;\n buf u(.I(owner_bus[3]), .Z(a));\nendmodule\n'
        raw+='module n(a);\n input \\owner_bus[3] ;\n buf u(.I(\\owner_bus[3] ), .Z(a));\nendmodule\n'
        self.assertEqual(correct_scalar_port_escaping(raw),(raw,[]))

    def test_scalar_and_real_base_declaration_are_ambiguous(self):
        for declaration in ('wire [7:0] owner_bus;', 'wire [7:0] other, owner_bus;',
                            'input owner_bus;', 'wire [7:0] \\owner_bus ;'):
            with self.subTest(declaration=declaration):
                raw='module m(a);\n input \\owner_bus[3] ;\n '+declaration+'\nendmodule\n'
                with self.assertRaisesRegex(ValueError,'REPAIR_SERIALIZER_AMBIGUOUS_BASE'):
                    correct_scalar_port_escaping(raw)

    def test_malformed_escape_is_rejected_instead_of_guessed(self):
        for raw in ('module m(a);\n input \\owner_bus[3];\nendmodule\n',
                    'module m(a);\n input \\owner_bus[3] ;\n buf u(.I(\\owner_bus[3]),.Z(a));\nendmodule\n'):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError,'REPAIR_SERIALIZER_MALFORMED_ESCAPE'):
                    correct_scalar_port_escaping(raw)

    def test_comments_strings_and_other_escaped_names_are_unchanged(self):
        raw='module m(a);\n input \\owner_bus[3] ;\n // owner_bus[3]\n'
        raw+=' /* owner_bus[3] */\n initial $display("owner_bus[3]");\n'
        raw+=' buf u(.I(\\other.owner_bus[3] ),.Z(a));\nendmodule\n'
        self.assertEqual(correct_scalar_port_escaping(raw),(raw,[]))

    def test_receipt_requires_complete_evidence_and_current_audit(self):
        with TemporaryDirectory() as t:
            p=Path(t).resolve();out=p/'electrical-repair';out.mkdir()
            for name in EVIDENCE:
                f=out/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(name)
            for name in ('netlist.v','netlist.json','source.py'): (p/name).write_text(name)
            (p/'netlist-audit.json').write_text('candidate/netlist-audit.json')
            receipt=dict(schema='riscay-electrical-repair-v1',status='structurally-accepted-electrically-unqualified',
                physical_qualification=False,repaired_verilog_sha256=sha(p/'netlist.v'),repaired_json_sha256=sha(p/'netlist.json'),
                inputs_sha256={str(p/'source.py'):sha(p/'source.py')},
                evidence_sha256={n:sha(out/n) for n in EVIDENCE})
            def check(r):
                (out/'receipt.json').write_text(json.dumps(r));return validate_receipt(p)
            with patch('repair_gf180_design.input_files',return_value=[p/'source.py']):
                check(receipt)
                for key,error in (('evidence_sha256','REPAIR_EVIDENCE_INVENTORY'),('inputs_sha256','REPAIR_INPUT_INVENTORY')):
                    bad=deepcopy(receipt);bad[key]={}
                    with self.assertRaisesRegex(ValueError,error):check(bad)
                (p/'netlist-audit.json').write_text('stale')
                with self.assertRaisesRegex(ValueError,'REPAIR_AUDIT_CHANGED'):check(receipt)


if __name__=='__main__':unittest.main()
