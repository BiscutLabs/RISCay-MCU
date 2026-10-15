# SPDX-License-Identifier: Apache-2.0
"""Pure provenance tests. All producer bytes/receipts are synthetic fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_quiescing_receipt_controls as controls
import quiescing_gate_control as gate
from check_frame_store_controls import helper_closure

SRAM='gf180mcu_ocd_ip_sram__sram1024x8m8wm1'


def put(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value,(dict,list)) else value)
    return path


def producer(root, variant='bd', prefix=0):
    top=('Bd' if variant=='bd' else 'Click')+'ResetBoundarySocFixture'
    export=root/'build/soc-tests'/f'{variant}-soc-receipt-real-gate-{prefix}123'
    folder=root/'build/graphs'/f'{variant}-{prefix}';folder.mkdir(parents=True)
    name=top+'.sv';put(export/name,'module '+top+'; endmodule\n')
    put(export/'contract.json',dict(manifest=dict(top=top)));put(export/'filelist.f',name+'\n')
    inventory=dict(schema='riscay-gf180-sram-v1',macro=SRAM,program_bytes=64,working_ram_bytes=32,
        instances=[dict(path=top+'.fabric_'+bank+'_macros_0',bank=bank,index=0) for bank in ('program','ram')])
    put(export/'sram.json',inventory);put(folder/name,(export/name).read_text())
    sram=put(root/'soc/src/main/resources/riscay/sram'/(SRAM+'.blackbox.v'),'module SRAM; endmodule\n')
    put(root/'soc/sram-lock.json',dict(assets={sram.name:dict(sha256=controls.sha(sram))}))
    tools={n:put(root/n,'synthetic tool bytes; never executed') for n in ('sv2v','yosys')}
    put(root/'tools/gf180-estimate-inputs.json',dict(tools={n:dict(sha256=controls.sha(p)) for n,p in tools.items()}))
    linux=lambda p:'/mnt/'+str(p.resolve())[0].lower()+str(p.resolve())[2:].replace('\\','/')
    script=f'read_verilog -sv {linux(folder/"converted.v")}\nhierarchy -check -top {top}\nproc\nflatten\nopt_clean\nwrite_json {linux(folder/"netlist.json")}\n'
    put(folder/'graph.ys',script);put(folder/'converted.v','synthetic unexecuted converter output')
    put(folder/'netlist.json',dict(synthetic_only=True));put(folder/'sv2v.log','')
    put(folder/'yosys.log','Executing JSON backend.\nEnd of script.\n')
    record=dict(top=top,sources={name:controls.sha(export/name)},contract_sha256=controls.sha(export/'contract.json'),
        filelist_sha256=controls.sha(export/'filelist.f'),sram_blackbox_sha256=controls.sha(sram),
        sram_inventory_sha256=controls.sha(export/'sram.json'),sram_capacities=dict(program=64,ram=32),
        tools={n:dict(path=str(p),sha256=controls.sha(p)) for n,p in tools.items()},
        commands=[['wsl','-e',linux(tools['sv2v']),'-DSYNTHESIS',linux(folder/name)],
                  ['wsl','-e',linux(tools['yosys']),'-s',linux(folder/'graph.ys')]])
    for name,key in [('graph.ys','script_sha256'),('converted.v','converted_sha256'),('netlist.json','netlist_sha256')]:record[key]=controls.sha(folder/name)
    return export,folder,record,{str(p.resolve()):controls.sha(p) for p in tools.values()}


def receipt_package(root):
    groups=[];cases={};outputs={};fresh={}
    full=dict(status='pass',violations=[],receiver_proofs=[dict(prefix='applicationResetCoordinator'),
        dict(prefix='ca_child_request_bridge',masked_bits=70)])
    for variant,prefix in [('bd',0),('click',0),('click',1)]:
        export,folder,record,tools=producer(root,variant,prefix)
        put(folder/'report.json',dict(**full,inputs=record))
        groups.append(dict(variant=variant,prefix=prefix,kind='real-gate',path=str(export)))
        outputs[str(export)]=str(folder);fresh[str(export)]=controls.file_hashes(export)
        cases[str(export)]=dict(output=str(folder),status='PASS',exit_code=0,started_unix_ns=3_000_000_000,
            ended_unix_ns=4_000_000_000,producer=record,output_sha256=controls.file_hashes(folder))
    regression=put(root/'regression.json',dict(synthetic_only=True))
    put(root/'tools/check_reset_crossings.py','# synthetic import root; not executed\n')
    driver=put(root/'driver.py','# synthetic root driver; not executed\n')
    helpers=set(helper_closure([Path(gate.__file__),root/'tools/check_reset_crossings.py']))|{driver}
    helpers={str(p.resolve()):controls.sha(p) for p in helpers}
    execution=dict(ended_unix=1,sources_sha256={'source':'synthetic'},compiled_class_sha256={'class':'synthetic'},
                   tool_inputs_sha256=tools,fresh_fixtures_sha256=fresh)
    before=dict(regression_receipt_sha256=controls.sha(regression),sources_sha256=execution['sources_sha256'],
        compiled_class_sha256=execution['compiled_class_sha256'],captured_unix_ns=2_000_000_000,
        helpers_sha256=helpers,tool_inputs_sha256=tools,driver=str(driver),fixtures_sha256=copy.deepcopy(fresh),
        outputs=outputs,preexisting_outputs={p:[] for p in outputs.values()})
    beforepath=put(root/'gate-graphs-before.json',before)
    receipt=dict(schema='riscay-quiescing-gate-graphs-v1',status='PASS_GATE_GRAPH_PREPARATION',
        regression_receipt_sha256=controls.sha(regression),before_sha256=controls.sha(beforepath),
        sources_unchanged=True,tools_unchanged=True,helpers_unchanged=True,started_unix_ns=3_000_000_000,
        ended_unix_ns=4_000_000_000,helpers_sha256=helpers,tool_inputs_sha256=tools,driver_sha256=controls.sha(driver),cases=cases)
    path=put(root/'graphs.json',receipt)
    return path,regression,execution,groups,before,receipt,full


class BindingTests(unittest.TestCase):
    def setUp(self):
        guard=patch('subprocess.Popen',side_effect=AssertionError('NO_HARDWARE_IN_BINDING_TESTS'))
        guard.start();self.addCleanup(guard.stop)

    def test_exact_producer_and_every_changed_transformation_rejects(self):
        for change in ('none','script','converted','graph','source','command','blackbox','tool','missing_completion'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);export,folder,record,tools=producer(root)
                if change=='script':
                    put(folder/'graph.ys',(folder/'graph.ys').read_text().replace('flatten\n','flatten\nsetattr -set invented 1\n'))
                    record['script_sha256']=controls.sha(folder/'graph.ys')
                if change=='converted':put(folder/'converted.v','replaced')
                if change=='graph':put(folder/'netlist.json',dict(replaced=True))
                if change=='source':put(folder/(record['top']+'.sv'),'invented replacement')
                if change=='command':record['commands'][1].append('unreviewed')
                if change=='blackbox':
                    p=root/'soc/src/main/resources/riscay/sram'/(SRAM+'.blackbox.v');put(p,'changed')
                    record['sram_blackbox_sha256']=controls.sha(p)
                if change=='tool':tools[str(root/'yosys')]='unbound'
                if change=='missing_completion':put(folder/'yosys.log','no completed producer')
                if change=='none':gate._graph_inputs(export,folder,record,root,tools,{})
                else:
                    with self.assertRaises(ValueError):gate._graph_inputs(export,folder,record,root,tools,{})

    def test_three_fresh_graph_receipts_bind_without_any_producer_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,reg,execution,groups,before,receipt,full=receipt_package(root)
            # This isolates provenance parsing; real full proof rejection is
            # separately exercised in GateTests, never replaced in production.
            with patch.object(gate,'_full_graph_proof',return_value=json.dumps(dict(full=full,gate=dict(synthetic=True)))) as proof:
                result=gate.bind_gate_graphs(path,reg,execution,groups,root)
            self.assertEqual(len(result['fixtures']),3);self.assertEqual(proof.call_count,3)
            self.assertEqual({p['fixture'] for p in result['fixtures']},set(execution['fresh_fixtures_sha256']))

    def assert_output_alias_rejected_before_proof(self, alias):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,reg,execution,groups,before,receipt,full=receipt_package(root)
            first,second=groups[1]['path'],groups[2]['path']
            before['outputs'][second]=alias(before['outputs'][first])
            before['preexisting_outputs']={value:[] for value in before['outputs'].values()}
            receipt['cases'][second]=copy.deepcopy(receipt['cases'][first])
            self.assertEqual(len(set(before['outputs'].values())),3)
            self.assertEqual(len({str(Path(p).resolve()).casefold() for p in before['outputs'].values()}),2)
            self.assertEqual(before['fixtures_sha256'],execution['fresh_fixtures_sha256'])
            put(root/'gate-graphs-before.json',before)
            receipt['before_sha256']=controls.sha(root/'gate-graphs-before.json');put(path,receipt)
            with patch.object(gate,'_full_graph_proof',return_value=json.dumps(dict(full=full,gate={}))) as proof:
                with self.assertRaisesRegex(ValueError,'^QUIESCING_CONTROL_GATE_GRAPH_FRESH_OUTPUTS$'):
                    gate.bind_gate_graphs(path,reg,execution,groups,root)
                proof.assert_not_called()

    def test_resolved_output_alias_rejected_before_full_graph_proof(self):
        self.assert_output_alias_rejected_before_proof(lambda path:path+'/.')

    def test_casefold_output_alias_rejected_before_full_graph_proof(self):
        self.assert_output_alias_rejected_before_proof(lambda path:path.swapcase())

    def test_stale_filtered_partial_or_retrospective_graph_cohorts_reject(self):
        for change in ('status','old_regression','source_changed','class_changed','before_time','preexisting',
                       'duplicate_output','relative_output','missing_case','missing_fixture','wrong_driver','omitted_helper','omitted_runtime',
                       'fixture_changed','output_changed','case_failed','case_timeout','wrong_top','source_not_unchanged'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);path,reg,execution,groups,before,receipt,full=receipt_package(root)
                key=groups[0]['path'];folder=Path(before['outputs'][key])
                if change=='status':receipt['status']='RUNNING'
                if change=='old_regression':receipt['regression_receipt_sha256']='old'
                if change=='source_changed':before['sources_sha256']={'source':'changed'}
                if change=='class_changed':before['compiled_class_sha256']={'class':'changed'}
                if change=='before_time':before['captured_unix_ns']=0
                if change=='preexisting':before['preexisting_outputs'][str(folder)]=['netlist.json']
                if change=='duplicate_output':before['outputs'][groups[1]['path']]=str(folder)
                if change=='relative_output':before['outputs'][key]='build/relative-output'
                if change=='missing_case':receipt['cases'].pop(key)
                if change=='missing_fixture':before['fixtures_sha256'].pop(key)
                if change=='wrong_driver':receipt['driver_sha256']='wrong'
                if change=='omitted_helper':
                    name=str(Path(gate.__file__).resolve());before['helpers_sha256'].pop(name);receipt['helpers_sha256'].pop(name,None)
                if change=='omitted_runtime':
                    name=next(iter(execution['tool_inputs_sha256']));before['tool_inputs_sha256'].pop(name);receipt['tool_inputs_sha256'].pop(name,None)
                    execution['tool_inputs_sha256'][name]='expected-runtime'
                if change=='fixture_changed':put(Path(key)/'extra.sv','unbound source')
                if change=='output_changed':put(folder/'extra.json',dict(unbound=True))
                if change=='case_failed':receipt['cases'][key]['exit_code']=1
                if change=='case_timeout':receipt['cases'][key]['timed_out']=True
                if change=='wrong_top':
                    put(Path(key)/'contract.json',dict(manifest=dict(top='FourPhaseSoc')))
                    before['fixtures_sha256'][key]=controls.file_hashes(Path(key));execution['fresh_fixtures_sha256'][key]=controls.file_hashes(Path(key))
                if change=='source_not_unchanged':receipt['sources_unchanged']=False
                put(root/'gate-graphs-before.json',before);receipt['before_sha256']=controls.sha(root/'gate-graphs-before.json');put(path,receipt)
                with patch.object(gate,'_full_graph_proof',return_value=json.dumps(dict(full=full,gate={}))),self.assertRaises(ValueError):
                    gate.bind_gate_graphs(path,reg,execution,groups,root)


if __name__=='__main__':unittest.main()
