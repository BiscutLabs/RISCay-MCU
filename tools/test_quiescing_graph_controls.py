# SPDX-License-Identifier: Apache-2.0
"""Pure synthetic-shape tests only; no synthetic graph earns production credit."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_quiescing_graph_controls as controls


def graph(click=False):
    top='ClickSoc' if click else 'FourPhaseSoc';source='ca_child_core.ca_child_address.ca_primitive_payload'
    cells={source:dict(type='Native',port_directions={'q':'output'},connections={'q':list(range(10,80))})}
    nets={}
    def net(name,bits):nets[name]={'bits':bits}
    def and_cell(name,a,b,y):cells[name]=dict(type='$and',port_directions={'A':'input','B':'input','Y':'output'},connections={'A':[a],'B':[b],'Y':[y]})
    for name,bits in {'serviceClock':[81],'gate_enabled':[82],'workClock':[83],'fabric_clock':[83],
                     'fabric_cpuAvailable':[86],'fabric_io_request_ready':[88],
                     'ca_child_request_bridge.out_ready':[88],'ca_child_request_bridge.out_valid':[80]}.items():net(name,bits)
    and_cell('work_clock',81,82,83);and_cell('cpu_gate',84,82,85);and_cell('cpu_tail',85,87,86);and_cell('ready_tail',86,89,88)
    for field,(offset,width) in controls.FIELDS.items():
        incoming=list(range(10+offset,10+offset+width));out=list(range(100+offset,100+offset+width))
        net('ca_child_transactions.serviceRequest_bits_'+field,incoming)
        net('ca_child_request_bridge.in_bits_'+field,incoming);net('ca_child_request_bridge.out_bits_'+field,out)
        cells['mask_'+field]=dict(type='$mux',port_directions={'A':'input','B':'input','S':'input','Y':'output'},
                                connections={'A':['0']*width,'B':incoming,'S':[80],'Y':out})
    net('fabric_ram_saved_data',list(range(200,208)))
    cells['actual_saved_data']=dict(type='$dff',parameters={'CLK_POLARITY':'1'},
        port_directions={'D':'input','Q':'output','CLK':'input'},
        connections={'D':list(range(210,218)),'Q':list(range(200,208)),'CLK':[83]})
    return dict(modules={top:dict(cells=cells,netnames=nets),
        'Native':dict(attributes={'hdlname':'ChiselAsyncEventRegister_v1' if click else 'ChiselAsyncClosingLatch_v1'})}),top


def baseline_result():
    return dict(status='pass',violations=[],receiver_proofs=[dict(prefix='applicationResetCoordinator'),
        dict(prefix='ca_child_request_bridge',source_width=70,masked_bits=70,mask_cells=['a','b','c','d'])])


def producer_package(root):
    export=root/'export';folder=export/'reset-crossings';folder.mkdir(parents=True)
    name='FourPhaseSoc.sv';(export/name).write_text('module FourPhaseSoc; endmodule\n')
    (export/'contract.json').write_text('{}');(export/'filelist.f').write_text(name+'\n')
    (export/'sram.json').write_text('{}');(folder/name).write_bytes((export/name).read_bytes())
    sram=root/'soc/src/main/resources/riscay/sram'/(controls.SRAM+'.blackbox.v');sram.parent.mkdir(parents=True);sram.write_text('module SRAM; endmodule\n')
    (root/'soc/sram-lock.json').write_text(json.dumps({'assets':{sram.name:{'sha256':controls.sha(sram)}}}))
    tools={n:root/n for n in ('sv2v','yosys')}
    for p in tools.values():p.write_text('fake helper tool bytes; never executed')
    lock=root/'tools/gf180-estimate-inputs.json';lock.parent.mkdir();lock.write_text(json.dumps({'tools':{n:{'sha256':controls.sha(p)} for n,p in tools.items()}}))
    linux=lambda p:'/mnt/'+str(p.resolve())[0].lower()+str(p.resolve())[2:].replace('\\','/')
    script=f'read_verilog -sv {linux(folder/"converted.v")}\nhierarchy -check -top FourPhaseSoc\nproc\nflatten\nopt_clean\nwrite_json {linux(folder/"netlist.json")}\n'
    (folder/'graph.ys').write_text(script);(folder/'converted.v').write_text('synthetic helper text only')
    (folder/'netlist.json').write_text('{"synthetic_helper_only":true}')
    (folder/'sv2v.log').write_text('');(folder/'yosys.log').write_text('Executing JSON backend.\nEnd of script.\n')
    record=dict(top='FourPhaseSoc',sources={name:controls.sha(export/name)},contract_sha256=controls.sha(export/'contract.json'),
        filelist_sha256=controls.sha(export/'filelist.f'),sram_blackbox_sha256=controls.sha(sram),sram_inventory_sha256=controls.sha(export/'sram.json'),
        tools={n:dict(path=str(p),sha256=controls.sha(p)) for n,p in tools.items()},
        commands=[['wsl','-e',linux(tools['sv2v']),'-DSYNTHESIS',linux(folder/name)],['wsl','-e',linux(tools['yosys']),'-s',linux(folder/'graph.ys')]])
    for name,key in [('graph.ys','script_sha256'),('converted.v','converted_sha256'),('netlist.json','netlist_sha256')]:record[key]=controls.sha(folder/name)
    return export,dict(inputs=record),{str(p.resolve()):controls.sha(p) for p in tools.values()}


def strict_log_package(root):
    """Synthetic strict-case envelope, never an executed production receipt."""
    key='portable-r1/bd';base=root/'fresh';export=base/key;export.mkdir(parents=True)
    folder=export/'reset-crossings';folder.mkdir();strict_dir=base/'strict-r1';strict_dir.mkdir()
    db,top=graph();caps={'program':2048,'ram':1024}
    manifest=dict(top=top,schema='chisel-async-contract-v3')
    # strict_case hashes manifest insertion order, rather than canonical order.
    semantic=controls.hashlib.sha256(json.dumps(manifest,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    def put(name,text):
        path=export/name;path.write_text(text);return path
    put('contract.json',json.dumps(dict(manifest=manifest,semantic_sha256=semantic)))
    put('ports.json','{}');put('filelist.f','FourPhaseSoc.sv\n');source=put('FourPhaseSoc.sv','synthetic unit source only\n')
    put('sram.json','{}')
    initial={key+'/'+name:controls.sha(export/name) for name in ('contract.json','ports.json','filelist.f','FourPhaseSoc.sv','sram.json')}
    put('contract_probe.sv','synthetic unit probe only\n');put('contract_probe.vvp','synthetic unit binary only\n')
    put('contract_simulation.log','CONTRACT_PROBES_PASS:1\n')
    sources={'FourPhaseSoc.sv':controls.sha(source)}
    att=dict(status='PASS',semantic_sha256=semantic,mapping_checks=1,source_sha256=sources,validation_auxiliary_sha256={},
        compile_command=['iverilog','-s','ContractProbe','-g2012','-DCHISEL_ASYNC_MAPPING','-s',top,'-o','contract_probe.vvp',str(source.resolve()),'contract_probe.sv'],
        simulation_command=['vvp','contract_probe.vvp'],probe_sha256=controls.sha(export/'contract_probe.sv'),
        compiled_vvp_sha256=controls.sha(export/'contract_probe.vvp'),simulation_log_sha256=controls.sha(export/'contract_simulation.log'))
    put('mapping-probe-attestation.json',json.dumps(att))
    put('resolved.json',json.dumps({k:att[k] for k in ('status','semantic_sha256','mapping_checks','source_sha256')}))
    put('reset-crossings/report.json',json.dumps(dict(status='pass',violations=[],inputs=dict(top=top,sources=sources,sram_capacities=caps))))
    put('reset-crossings/netlist.json',json.dumps(db))
    put('reset-crossings/sv2v.log','original converter diagnostic\n')
    put('reset-crossings/yosys.log','original producer diagnostic\nExecuting JSON backend.\nEnd of script.\n')
    result=dict(status='PASS',sleep_clock_background=True,reset_contract='generated-system-reset',coverage='packed-equivalent',
        probe_timeout_seconds=3600,probe_compile_timeout_seconds=3600,mapping_checks=1,endpoints=1,semantic_sha256=semantic,
        sram_instances=[top+'.fabric_'+name+'_macros_'+str(index) for name,index in [('program',0),('program',1),('ram',0)]])
    command=['python','tools/check_export.py',str(export.resolve()),'--library',str((root/'library').resolve()),'--soc','--sleep-clock',
        '--vector-coverage','--probe-timeout','3600','--probe-compile-timeout','3600']
    (strict_dir/'portable-r1-bd.log').write_text(json.dumps(result));(strict_dir/'portable-r1-bd-command.json').write_text(json.dumps(command))
    case=dict(status='PASS',exit_code=0,started_unix_ns=2_000_000_000,ended_unix_ns=3_000_000_000,command=command,
        log_sha256=controls.sha(strict_dir/'portable-r1-bd.log'),result=result,
        executed_inputs_sha256={name:controls.sha(export/name) for name in set(controls.GENERATED)|{'contract.json','ports.json','filelist.f'}},
        coverage=dict(complete_sweep_campaigns=4,total_mapping_checks=1,endpoint_count=1),
        attestation_sha256=controls.sha(export/'mapping-probe-attestation.json'),rdc_sources_sha256=sources)
    before=dict(exports_sha256=initial,preexisting_generated={key:[]},captured_unix_ns=1_500_000_000,
        library=str(root/'library'),tool_inputs_sha256={})
    return dict(key=key,case=case,before=before,execution=dict(ended_unix=1,exports_sha256=initial,command=['python']),
        base=base,strict_dir=strict_dir,root=root,inputs={}),db,caps


class PureGraphControls(unittest.TestCase):
    def setUp(self):
        guard=patch('subprocess.Popen',side_effect=AssertionError('NO_HARDWARE_IN_HELPER_TESTS'));guard.start();self.addCleanup(guard.stop)

    def test_four_export_inventory_and_304_distinct_controls(self):
        self.assertEqual(set(controls.KEYS),{'portable-r1/bd','portable-r1/click','physical-r1/bd','physical-r1/click'})
        for click in (False,True):
            db,top=graph(click);jobs=controls.obligations(db,top)
            self.assertEqual(len(jobs),76);self.assertEqual(sum(j['label'].startswith('source-') for j in jobs),70)
            self.assertEqual(sum(j['label'].startswith('mask-') for j in jobs),4)
            for field,(_,width) in controls.FIELDS.items():self.assertEqual([j['index'] for j in jobs if j['label'].startswith('source-'+field+'-')],list(range(width)))

    def test_every_mutation_changes_one_actual_pin_and_preserves_baseline(self):
        db,top=graph();before=copy.deepcopy(db)
        for job in controls.obligations(db,top):
            changed=controls.mutated(db,top,job);self.assertEqual(db,before)
            self.assertEqual(set(changed['modules'][top]['cells']),set(db['modules'][top]['cells']))
            changed['modules'][top]['cells'][job['cell']]['connections'][job['pin']][job['index']]=job['before']
            self.assertEqual(changed,db)

    def test_ready_factor_preserves_other_inputs_and_work_clock(self):
        db,top=graph();job=next(j for j in controls.obligations(db,top) if j['label']=='ready-clock-factor')
        self.assertEqual((job['cell'],job['pin'],job['before'],job['after']),('cpu_gate','B',82,'1'))
        changed=controls.mutated(db,top,job)
        self.assertEqual(changed['modules'][top]['cells']['work_clock'],db['modules'][top]['cells']['work_clock'])
        self.assertEqual(changed['modules'][top]['cells']['cpu_gate']['connections']['A'],[84])

    def test_unmasked_sink_is_existing_periodic_register(self):
        db,top=graph();job=controls.obligations(db,top)[-1]
        self.assertEqual((job['cell'],job['pin'],job['index'],job['after']),('actual_saved_data','D',0,14))
        self.assertEqual(job['expected'],'RDC_QUIESCING_RECEIPT_UNMASKED_PERIODIC_SINK_actual_saved_data_D')

    def test_existing_sink_must_have_unique_complete_ordered_register_driver(self):
        db,top=graph();m=db['modules'][top]
        m['netnames']['fabric_ram_saved_data']['bits'][0]=86
        with self.assertRaisesRegex(ValueError,'UNIQUE_PERIODIC_DATA_SINK'):controls.targets(db,top)
        db,top=graph();db['modules'][top]['netnames']['fabric_ram_saved_data']['bits'].reverse()
        with self.assertRaisesRegex(ValueError,'ACTUAL_PERIODIC_DATA_SINK'):controls.targets(db,top)

    def test_detached_cpu_available_or_duplicate_clock_factor_rejects(self):
        db,top=graph();db['modules'][top]['cells']['ready_tail']['connections']['A']=[900]
        with self.assertRaisesRegex(ValueError,'CPU_AVAILABLE_ACTUAL_READY_FACTOR'):controls.targets(db,top)
        db,top=graph();db['modules'][top]['cells']['cpu_tail']['connections']['B']=[82]
        with self.assertRaisesRegex(ValueError,'UNIQUE_CPU_CLOCK_FACTOR'):controls.targets(db,top)

    def test_wrong_source_lane_mask_model_and_consumer_clock_reject(self):
        for change in ('source','mask','model','clock'):
            db,top=graph();m=db['modules'][top]
            if change=='source':m['netnames']['ca_child_request_bridge.in_bits_data']['bits']=[999]*32
            elif change=='mask':m['cells']['mask_data']['connections']['S']=['1']
            elif change=='model':db['modules']['Native']['attributes']['hdlname']='SyntheticPayload'
            else:m['cells']['actual_saved_data']['connections']['CLK']=[81]
            with self.subTest(change=change),self.assertRaises(ValueError):controls.targets(db,top)

    def test_baseline_invokes_full_audit_and_requires_identical_saved_proof(self):
        db,top=graph();saved=baseline_result();caps={'program':2048,'ram':1024}
        with patch.object(controls,'audit_graph',return_value=copy.deepcopy(saved)) as full:
            self.assertEqual(controls.baseline(db,top,caps,{**saved,'inputs':{}}),saved)
            full.assert_called_once_with(db,top,caps)
        bad=copy.deepcopy(saved);bad['receiver_proofs'].pop(0)
        with patch.object(controls,'audit_graph',return_value=bad),self.assertRaisesRegex(ValueError,'REAL_COORDINATOR_REQUIRED'):
            controls.baseline(db,top,caps,bad)
        bad=copy.deepcopy(saved);bad['violations']=[{'sink':'unrelated'}];bad['status']='fail'
        with patch.object(controls,'audit_graph',return_value=bad),self.assertRaisesRegex(ValueError,'FULL_BASELINE_MISMATCH'):
            controls.baseline(db,top,caps,bad)

    def test_baseline_accepts_json_roundtrip_of_native_alias_pairs(self):
        db,top=graph();actual=baseline_result()
        actual['receiver_proofs'].append(dict(prefix='native_hold',phase_aliases=[('req_a','req_b'),('ack_a','ack_b')]))
        saved=json.loads(json.dumps(actual))
        with patch.object(controls,'audit_graph',return_value=actual):
            self.assertEqual(controls.baseline(db,top,{},saved),actual)
        for change in ('alias','missing','order'):
            bad=copy.deepcopy(saved);proof=bad['receiver_proofs'][-1]
            if change=='alias':proof['phase_aliases'][0][1]='wrong'
            elif change=='missing':del proof['phase_aliases']
            else:proof['phase_aliases'].reverse()
            with self.subTest(change=change),patch.object(controls,'audit_graph',return_value=actual),self.assertRaisesRegex(ValueError,'FULL_BASELINE_MISMATCH'):
                controls.baseline(db,top,{},bad)

    def test_baseline_preserves_json_boolean_integer_types(self):
        db,top=graph();actual=baseline_result();actual['extra_count']=1
        saved=copy.deepcopy(actual);saved['extra_count']=True
        with patch.object(controls,'audit_graph',return_value=actual),self.assertRaisesRegex(ValueError,'FULL_BASELINE_MISMATCH'):
            controls.baseline(db,top,{},saved)

    def test_negative_requires_exact_diagnostic_not_error_family_or_report_failure(self):
        db,top=graph();job=controls.obligations(db,top)[-2]
        for text in ('RDC_BRIDGE_OTHER',job['expected']+'_OTHER','unrelated'):
            with patch.object(controls,'audit_graph',side_effect=ValueError(text)),self.assertRaisesRegex(ValueError,'WRONG_DIAGNOSTIC'):
                controls.negative(db,top,{},job)
        with patch.object(controls,'audit_graph',return_value={'status':'fail'}),self.assertRaisesRegex(ValueError,'SURVIVED'):
            controls.negative(db,top,{},job)
        with patch.object(controls,'audit_graph',side_effect=ValueError(job['expected'])) as full:
            self.assertEqual(controls.negative(db,top,{},job)['status'],'EXACT_REJECTION');self.assertEqual(full.call_count,1)

    def test_helper_audit_mutation_or_wrong_exception_never_qualifies(self):
        db,top=graph();job=controls.obligations(db,top)[0]
        def modifies(graph,*args):
            graph['unexpected']=True;raise ValueError(job['expected'])
        with patch.object(controls,'audit_graph',side_effect=modifies),self.assertRaisesRegex(ValueError,'AUDIT_CHANGED_MUTANT'):
            controls.negative(db,top,{},job)
        with patch.object(controls,'audit_graph',side_effect=KeyError(job['expected'])),self.assertRaises(KeyError):controls.negative(db,top,{},job)

    def test_stale_graph_binary_or_source_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);inputs={}
            for name in ('netlist.json','contract_probe.vvp','source.scala'):
                p=root/name;p.write_text('before');controls.bind(inputs,p)
            controls.rehash(inputs)
            for name in ('netlist.json','contract_probe.vvp','source.scala'):
                p=root/name;p.write_text('after')
                with self.assertRaisesRegex(ValueError,'STALE_INPUT'):controls.rehash(inputs)
                p.write_text('before')

    def test_actual_graph_producer_script_and_hashes_are_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);export,report,tools=producer_package(root)
            self.assertEqual(controls.graph_inputs(export,report,root,tools,{}),{'synthetic_helper_only':True})
            folder=export/'reset-crossings';saved=(folder/'graph.ys').read_text()
            (folder/'graph.ys').write_text(saved.replace('flatten\n','flatten\nsetattr -set synthetic 1\n'))
            report['inputs']['script_sha256']=controls.sha(folder/'graph.ys')
            with self.assertRaisesRegex(ValueError,'ACTUAL_PROC_FLATTEN_SCRIPT'):controls.graph_inputs(export,report,root,tools,{})
            (folder/'graph.ys').write_text(saved);report['inputs']['script_sha256']=controls.sha(folder/'graph.ys')
            (folder/'netlist.json').write_text('{"replaced":true}')
            with self.assertRaisesRegex(ValueError,'INPUT_CHANGED'):controls.graph_inputs(export,report,root,tools,{})

    def test_synthetic_blackbox_or_compiler_command_replacement_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);export,report,tools=producer_package(root)
            path=export/'reset-crossings/FourPhaseSoc.sv';path.write_text('reconstructed synthetic owner')
            with self.assertRaisesRegex(ValueError,'GRAPH_TRANSFORM_CHANGED'):controls.graph_inputs(export,report,root,tools,{})
            path.write_bytes((export/'FourPhaseSoc.sv').read_bytes())
            report['inputs']['commands'][1].append('extra')
            with self.assertRaisesRegex(ValueError,'GRAPH_EXECUTED_COMMANDS'):controls.graph_inputs(export,report,root,tools,{})

    def test_graph_blackbox_must_match_pinned_asset_not_just_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);export,report,tools=producer_package(root)
            path=root/'soc/src/main/resources/riscay/sram'/(controls.SRAM+'.blackbox.v')
            path.write_text('changed blackbox')
            report['inputs']['sram_blackbox_sha256']=controls.sha(path)
            with self.assertRaisesRegex(ValueError,'PINNED_SRAM_BLACKBOX'):controls.graph_inputs(export,report,root,tools,{})

    def test_original_strict_producer_logs_are_bound_before_graph_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,db,caps=strict_log_package(Path(tmp))
            with patch.object(controls,'graph_inputs',return_value=db) as reader,patch.object(controls,'sram_capacities',return_value=caps):
                result=controls.strict_case(**args)
            reader.assert_called_once();self.assertEqual(len(result['jobs']),76)
            for name in ('reset-crossings/sv2v.log','reset-crossings/yosys.log'):
                path=(args['base']/args['key']/name).resolve()
                self.assertEqual(args['inputs'][str(path)],args['case']['executed_inputs_sha256'][name])

    def test_missing_original_strict_producer_log_hash_rejects_before_graph_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,db,caps=strict_log_package(Path(tmp))
            original=copy.deepcopy(args['case'])
            for name in ('reset-crossings/sv2v.log','reset-crossings/yosys.log'):
                args['case']=copy.deepcopy(original);args['inputs']={}
                del args['case']['executed_inputs_sha256'][name]
                with self.subTest(name=name),patch.object(controls,'graph_inputs') as reader:
                    with self.assertRaisesRegex(ValueError,'STRICT_EXECUTED_INPUTS'):controls.strict_case(**args)
                    reader.assert_not_called()

    def test_changed_producer_log_with_original_strict_receipt_rejects_before_graph_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,db,caps=strict_log_package(Path(tmp));original=copy.deepcopy(args['case'])
            for name in ('reset-crossings/sv2v.log','reset-crossings/yosys.log'):
                path=args['base']/args['key']/name;saved=path.read_bytes();args['inputs']={}
                path.write_text('replacement still looks complete\nExecuting JSON backend.\nEnd of script.\n')
                with self.subTest(name=name),patch.object(controls,'graph_inputs') as reader:
                    with self.assertRaisesRegex(ValueError,'INPUT_CHANGED:'):controls.strict_case(**args)
                    reader.assert_not_called()
                self.assertEqual(args['case'],original);path.write_bytes(saved)

    def test_strict_reader_rejects_historical_or_preexisting_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);key='portable-r1/bd';case=dict(status='PASS',exit_code=0,started_unix_ns=2e9,ended_unix_ns=3e9)
            execution=dict(ended_unix=1,exports_sha256={key+'/reset-crossings/netlist.json':'hash'})
            before=dict(exports_sha256=execution['exports_sha256'],preexisting_generated={key:[]})
            with self.assertRaisesRegex(ValueError,'FRESH_STRICT_EXPORT_REQUIRED'):
                controls.strict_case(key,case,before,execution,root,root,root,{})
            execution['exports_sha256']={key+'/top.sv':'hash'};before['exports_sha256']=execution['exports_sha256'];before['preexisting_generated'][key]=['resolved.json']
            with self.assertRaisesRegex(ValueError,'FRESH_STRICT_EXPORT_REQUIRED'):
                controls.strict_case(key,case,before,execution,root,root,root,{})
            case['started_unix_ns']=0
            with self.assertRaisesRegex(ValueError,'STRICT_TIME_ORDER'):
                controls.strict_case(key,case,before,execution,root,root,root,{})

    def test_retrospective_or_preregression_strict_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);key='portable-r1/bd';case=dict(status='PASS',exit_code=0,started_unix_ns=2e9,ended_unix_ns=3e9)
            execution=dict(ended_unix=1,exports_sha256={key+'/top.sv':'hash'})
            before=dict(exports_sha256=execution['exports_sha256'],preexisting_generated={key:[]})
            for timestamp in (0,2e9+1,3e9):
                before['captured_unix_ns']=timestamp
                with self.subTest(timestamp=timestamp),self.assertRaisesRegex(ValueError,'STRICT_BEFORE_TIME_ORDER'):
                    controls.strict_case(key,case,before,execution,root,root,root,{})

    def test_plan_exact_rebind_rejects_edited_jobs_or_inputs(self):
        plan=dict(schema='riscay-quiescing-actual-graph-plan-v1',status='BOUND_FRESH_STRICT_GRAPHS_NOT_EXECUTED',
            regression='regression.json',strict='strict.json',repository='repo',exports=[{'job':'original'}])
        with patch.object(controls,'bind_plan',return_value=copy.deepcopy(plan)):
            controls.validate_plan(plan);plan['exports'][0]['job']='edited'
            with self.assertRaisesRegex(ValueError,'STALE_OR_EDITED_PLAN'):controls.validate_plan(plan)

    def test_run_stops_after_first_wrong_diagnostic_and_retains_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);export=root/'export';export.mkdir();db,top=graph();graphpath=export/'netlist.json';graphpath.write_text(json.dumps(db))
            saved=baseline_result();reportpath=export/'report.json';reportpath.write_text(json.dumps(saved));jobs=controls.obligations(db,top)
            entry=dict(key='portable-r1/bd',export=str(export),top=top,graph=str(graphpath),report=str(reportpath),capacities={},jobs=jobs,graph_sha256=controls.sha(graphpath))
            plan=dict(exports=[entry],inputs_sha256={str(graphpath):controls.sha(graphpath)})
            with patch.object(controls,'validate_plan'),patch.object(controls,'audit_graph',side_effect=[saved,ValueError('WRONG')]) as full:
                with self.assertRaisesRegex(ValueError,'CAMPAIGN_FAILED'):controls.run(plan,root/'out')
                self.assertEqual(full.call_count,2)
            receipt=controls.read_json(root/'out/receipt.json')
            self.assertEqual(receipt['status'],'FAIL_OR_INCOMPLETE');self.assertEqual(len(receipt['records']),2)
            self.assertEqual(controls.sha(graphpath),entry['graph_sha256'])
            with self.assertRaises(FileExistsError),patch.object(controls,'validate_plan'):controls.run(plan,root/'out')


if __name__=='__main__':unittest.main()
