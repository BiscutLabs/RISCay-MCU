# SPDX-License-Identifier: Apache-2.0
"""Pure helper controls. Synthetic strings/files never execute as HDL."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_quiescing_receipt_controls as controls


def fixture(variant='bd', composed=False):
    prefix = 'FourPhase' if variant == 'bd' else 'Click'
    top = ('Bd' if variant == 'bd' else 'Click') + 'ResetBoundarySocFixture' if composed else 'QuiescingReceiptFixture'
    identity = 'request_bridge' if composed else 'rx'; instance = 'ca_child_' + identity
    module = prefix + 'QuiescingReceipt'; field = '_address' if composed else ''; width = 32 if composed else 70
    body = f'''module {top};
wire workClock = serviceClock & enabled;
wire ready = allow & enabled;
always @(posedge workClock or posedge reset) begin end
{module} {instance} (.clock(serviceClock),.in_bits(data),.out_ready(ready),.out_bits(result),.out_bits_address(address));
assign bits = result;
assign captured_address = address;
'''
    children = [dict(id=identity, contract=dict(module=module, rtl_path=top+'.'+instance))]
    if composed:
        body += prefix+'Core ca_child_core (.reset(nativeCoreReset));\n'
        children.append(dict(id='core', contract=dict(module=prefix+'Core', rtl_path=top+'.ca_child_core')))
    body += 'endmodule\n'
    owner = f'''module {module};
wire [{width-1}:0] held = offered ? in_bits{field} : {width}'h0;
assign out_valid = offered;
assign out_bits{field} = held;
endmodule
'''
    tb = '''module Testbench;
task offer(input [69:0] nextValue); begin
  if(bits !== nextValue || acknowledge === phase) $fatal(1,"RECEIPT_OFFER");
end endtask
initial begin
 if(bits !== 0) $fatal(1,"RECEIPT_IDLE_ASYNC_LEAK");
 if(acknowledge !== heldAck) $fatal(1,"RECEIPT_ACK_WITHOUT_CONSUMER_CLOCK");
 if(rawPayload_address !== savedAddress) $fatal(1,"SOC_BOUNDARY_WORK_SOURCE_CHANGED_BEFORE_CLOSURE");
 if(captured_address !== 0) $fatal(1,"SOC_BOUNDARY_CLOSED_INGRESS_OUTPUT_NOT_MASKED");
 $display("RISCAY_SOC_PASS"); $finish;
end
endmodule
'''
    return {top+'.sv':body, module+'.sv':owner, 'testbench.sv':tb}, dict(top=top, design=dict(children=children))


def cohort(folder):
    legacy=[dict(variant=v, kind=k, path=str(folder/(v+('-soc-reset-work-stopped' if k=='composed' else '-retained-quiescing-'+k)+'123')))
            for v in ('bd','click') for k in ('walk','invalid','work-stop','composed')]
    gates=[dict(variant=v,kind='real-gate',prefix=p,path=str(folder/(v+'-soc-receipt-real-gate-'+str(p)+'123')))
           for v,p in [('bd',0),('click',0),('click',1)]]
    return dict(schema='riscay-quiescing-controls-cohort-v2',fixtures=legacy+gates)


def regression():
    inventory=controls.required_inventory()
    command = ['python','tools/sbt.py','clean',inventory['primary_command'],'physical/test',
               'fourPhaseBd/runMain riscay.bd.EmitFourPhaseSoc build/fresh/portable/bd',
               'twoPhaseClick/runMain riscay.click.EmitClickSoc build/fresh/portable/click',
               'physical/runMain riscay.physical.EmitPhysical build/fresh/physical']
    before = dict(sources_sha256={'source':'hash'}, tool_inputs_sha256={'tool':'hash'}, fixtures=['old'])
    execution = dict(status='PASS_DIGITAL_REGRESSION_AND_FRESH_EXPORTS',exit_code=0,error=None,
        sources_unchanged=True,tools_unchanged=True,command=command,
        sources_sha256=before['sources_sha256'].copy(), tool_inputs_sha256=before['tool_inputs_sha256'].copy(),
        test_summaries=[['144','0','0','0','0'],['1','0','0','0','0']],started_unix=1,ended_unix=2,fresh_fixtures_sha256={'fresh':{'rtl':'hash'}})
    lines=['compiling 4 Scala sources to /repo/verification']
    for suite,names in inventory['suites'].items():
        lines+=['[info] '+suite+':']+['[info] - '+name for name in names]
    lines+=['[info] Run completed in 1 second.','[info] Total number of tests run: 144',
            '[info] Suites: completed 4, aborted 0',
            '[info] Tests: succeeded 144, failed 0, canceled 0, ignored 0, pending 0','[info] All tests passed.',
            '[info] PhysicalHelperSpec:','[info] - synthetic independent physical result',
            '[info] Run completed in 1 second.','[info] Total number of tests run: 1',
            '[info] Suites: completed 1, aborted 0',
            '[info] Tests: succeeded 1, failed 0, canceled 0, ignored 0, pending 0','[info] All tests passed.']
    log='\n'.join(lines)+'\n'
    return execution,before,log,command


class PureControls(unittest.TestCase):
    def setUp(self):
        # Every test below must remain pure even if an implementation regresses.
        self.block = patch('subprocess.Popen', side_effect=AssertionError('NO_CHILD_PROCESS_IN_HELPER_TEST'))
        self.block.start(); self.addCleanup(self.block.stop)

    def test_exact_inventory_148_faults_preserves_five_types_per_variant(self):
        jobs = [(v,f,l) for v in ('bd','click') for k in ('walk','invalid','work-stop','composed') for f,l in controls.cases(k)]
        self.assertEqual(len(jobs),148)
        for v in ('bd','click'):
            self.assertEqual([l for variant,f,l in jobs if variant==v and f=='payload'],list(range(70)))
            self.assertEqual({f for variant,f,l in jobs if variant==v},
                             {'payload','invalid-mask','work-enable','raw-source-reset','closed-mask'})

    def test_added_gate_cohort_is_exact_three_and_total151(self):
        with tempfile.TemporaryDirectory() as tmp:
            good=cohort(Path(tmp)); groups=controls.validate_cohort(good)
            self.assertEqual(sum(len(controls.cases(g['kind'])) for g in groups),151)
            self.assertEqual(len(groups),11)
            legacy=[g for g in groups if g['kind']!='real-gate']
            self.assertEqual(len(controls.validate_original_cohort(dict(schema='riscay-quiescing-controls-cohort-v1',fixtures=legacy))),8)
            for change in ('prefix','duplicate','missing','bool','extra','historical_schema'):
                bad=copy.deepcopy(good)
                if change=='prefix':bad['fixtures'][8]['prefix']=1
                if change=='duplicate':bad['fixtures'][10]=copy.deepcopy(bad['fixtures'][9])
                if change=='missing':bad['fixtures'].pop()
                if change=='bool':bad['fixtures'][8]['prefix']=False
                if change=='extra':bad['fixtures'][8]['graph']='unbound'
                if change=='historical_schema':bad['schema']='riscay-quiescing-controls-cohort-v1'
                with self.subTest(change=change),self.assertRaises(ValueError):controls.validate_cohort(bad)

    def test_gate_activity_requires_exact_counts_and_phase_before_fault(self):
        baseline='SOC_GATE_REQUEST_PHASE:1\nSOC_GATE_CAPTURE_COUNTS:1:1:1:4\nRISCAY_SOC_PASS\n'
        self.assertEqual(controls.gate_activity(baseline,'bd'),1)
        self.assertEqual(controls.gate_activity('SOC_GATE_REQUEST_PHASE:0\n','click',0,fault=True),0)
        for bad in ('',baseline+baseline,baseline.replace('1:1:1:4','1:1:1:3'),baseline.replace('PHASE:1','PHASE:0')):
            with self.assertRaises(ValueError):controls.gate_activity(bad,'bd')
        for bad in (baseline,'', 'SOC_GATE_REQUEST_PHASE:1\nSOC_GATE_REQUEST_PHASE:0\n'):
            with self.assertRaises(ValueError):controls.gate_activity(bad,'click',1,fault=True)
        with self.assertRaises(ValueError):controls.gate_activity('SOC_GATE_REQUEST_PHASE:0\n','click',1,fault=True)

    def test_gate_mutation_dispatch_and_exact_fatal_are_preserved(self):
        import test_quiescing_gate_control as fixtures
        for variant in ('bd','click'):
            texts,manifest=fixtures.fixture(variant)
            name,changed,site=controls.mutate(texts,manifest,variant,'actual-gate')
            self.assertEqual(changed,texts[name].replace('& gate_enabled;',"& 1'h1;"))
            self.assertEqual(site['message'],'SOC_GATE_ACK_WITHOUT_REAL_CAPTURE')
            good=dict(exit_code=0,timed_out=False);bad=dict(exit_code=1,timed_out=False)
            log=f"FATAL: {site['source']}:{site['line']}: {site['message']}\n       Time: 12000  Scope: {site['scope']}\n"
            controls.classify(good,bad,log,site)
            with self.assertRaises(ValueError):controls.classify(good,bad,log.replace('Time: 12000','Time: 0'),site)
            with self.assertRaises(ValueError):controls.mutate(texts,manifest,variant,'actual-gate',0)

    def test_full_324_process_schedule_and_first_gate_failure_are_bounded(self):
        import test_quiescing_gate_control as gates
        for wrong_gate_fatal in (False, True):
            with self.subTest(wrong_gate_fatal=wrong_gate_fatal),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);groups=[];jobs={}
                definitions=[(v,k,None) for v in ('bd','click') for k in controls.KINDS]
                definitions += [('bd','real-gate',0),('click','real-gate',0),('click','real-gate',1)]
                for variant,kind,prefix in definitions:
                    texts,manifest=(gates.fixture(variant) if kind=='real-gate' else fixture(variant,kind=='composed'))
                    label=variant+'-'+kind+('-prefix-'+str(prefix) if kind=='real-gate' else '')
                    source=root/'sources'/label;source.mkdir(parents=True)
                    for name,text in texts.items():(source/name).write_text(text)
                    (source/'contract.json').write_text(json.dumps(dict(manifest=manifest)))
                    (source/'ports.json').write_text('{}');(source/'filelist.f').write_text('synthetic fixture only\n')
                    mutations=[]
                    for fault,lane in controls.cases(kind):
                        name,changed,site=controls.mutate(texts,manifest,variant,fault,lane)
                        job=dict(fault=fault,lane=lane,file=name,before_sha256=controls.sha(source/name),
                                 after_sha256=hashlib.sha256(changed.encode()).hexdigest(),site=site)
                        mutations.append(job)
                        jobs[label+'-'+fault+('' if lane is None else '-'+str(lane))]=(kind,1 if variant=='bd' else prefix,job)
                    group=dict(path=str(source),variant=variant,kind=kind,files=[n for n in texts if n!='testbench.sv'],
                        inputs=controls.file_hashes(source),mutations=mutations,oracle_sha256=controls.sha(source/'testbench.sv'))
                    if kind=='real-gate':group.update(prefix=prefix,gate_phase=1 if variant=='bd' else prefix)
                    groups.append(group);jobs[label+'-baseline']=(kind,1 if variant=='bd' else prefix,None)
                calls=[]
                def fake_run(command,folder,log_name,timeout):
                    calls.append((folder.name,timeout));kind,phase,job=jobs[folder.name]
                    if log_name=='compile.log':
                        (folder/'sim.vvp').write_text('synthetic binary; never executed');log='';code=0
                    elif job is None:
                        log=('SOC_GATE_REQUEST_PHASE:'+str(phase)+'\nSOC_GATE_CAPTURE_COUNTS:1:1:1:4\n' if kind=='real-gate' else '')+'RISCAY_SOC_PASS\n';code=0
                    else:
                        site=job['site'];message=site['message']
                        if wrong_gate_fatal and kind=='real-gate':message='UNRELATED_ASSERTION'
                        log=('SOC_GATE_REQUEST_PHASE:'+str(phase)+'\n' if kind=='real-gate' else '')
                        log+=f"FATAL: {site['source']}:{site['line']}: {message}\n       Time: 1000  Scope: {site['scope']}\n";code=1
                    (folder/log_name).write_text(log)
                    return dict(exit_code=code,timed_out=False),log
                plan=dict(fixtures=groups,binaries=dict(iverilog='mock-compiler',vvp='mock-simulator'))
                with patch.object(controls,'validate_plan'),patch.object(controls,'run_process',side_effect=fake_run):
                    if wrong_gate_fatal:
                        with self.assertRaisesRegex(ValueError,'CAMPAIGN_FAILED'):controls.execute(plan,root/'out')
                    else:controls.execute(plan,root/'out')
                receipt=controls.read_json(root/'out/receipt.json')
                self.assertEqual(len(calls),316 if wrong_gate_fatal else 324)
                self.assertEqual([t for _,t in calls],[60,90]*(len(calls)//2))
                self.assertEqual(len(receipt['records']),158 if wrong_gate_fatal else 162)
                self.assertEqual(receipt['status'],'FAIL_OR_INCOMPLETE' if wrong_gate_fatal else 'PASS_EXACT_DIGITAL_CONTROLS')
                if wrong_gate_fatal:self.assertTrue(calls[-1][0].endswith('actual-gate'))

    def test_all_payload_lane_faults_are_valid_only_and_keep_oracle(self):
        for variant in ('bd','click'):
            texts,manifest=fixture(variant); original=copy.deepcopy(texts)
            observed=set()
            for lane in range(70):
                name,body,site=controls.mutate(texts,manifest,variant,'payload',lane)
                self.assertIn(f"assign out_bits = held ^ (offered ? 70'h{1<<lane:x} : 70'h0);",body)
                self.assertEqual(site,dict(source='testbench.sv',line=3,message='RECEIPT_OFFER',scope='Testbench.offer'))
                observed.add(body)
            self.assertEqual(len(observed),70); self.assertEqual(texts,original)

    def test_other_eight_faults_keep_original_testbench(self):
        for variant in ('bd','click'):
            for fault in ('invalid-mask','work-enable','raw-source-reset','closed-mask'):
                texts,manifest=fixture(variant,fault in ('raw-source-reset','closed-mask'))
                original=copy.deepcopy(texts); name,body,site=controls.mutate(texts,manifest,variant,fault)
                self.assertNotEqual(body,texts[name]); self.assertEqual(texts,original)
                self.assertEqual(site['scope'],'Testbench')
                expected={'invalid-mask':'RECEIPT_IDLE_ASYNC_LEAK','work-enable':'RECEIPT_ACK_WITHOUT_CONSUMER_CLOCK',
                          'raw-source-reset':'SOC_BOUNDARY_WORK_SOURCE_CHANGED_BEFORE_CLOSURE',
                          'closed-mask':'SOC_BOUNDARY_CLOSED_INGRESS_OUTPUT_NOT_MASKED'}
                self.assertEqual(site['message'],expected[fault])

    def test_detached_wrong_width_gate_and_duplicate_anchors_reject(self):
        changes=[('QuiescingReceiptFixture.sv','ca_child_rx','detached'),
                 ('QuiescingReceiptFixture.sv','.out_bits(result)','.out_bits(detached)'),
                 ('FourPhaseQuiescingReceipt.sv','[69:0]','[68:0]'),
                 ('FourPhaseQuiescingReceipt.sv','out_valid = offered','out_valid = other'),
                 ('FourPhaseQuiescingReceipt.sv','assign out_bits = held;','assign out_bits = held;\nassign out_bits = held;')]
        for file,before,after in changes:
            texts,manifest=fixture(); texts[file]=texts[file].replace(before,after)
            with self.subTest(after=after),self.assertRaises(ValueError):controls.mutate(texts,manifest,'bd','payload',0)
        texts,manifest=fixture(); texts['QuiescingReceiptFixture.sv']=texts['QuiescingReceiptFixture.sv'].replace('ready = allow & enabled','ready = allow')
        with self.assertRaises(ValueError):controls.mutate(texts,manifest,'bd','work-enable')
        for lane in (-1,70,True,None):
            texts,manifest=fixture()
            with self.assertRaises(ValueError):controls.mutate(texts,manifest,'bd','payload',lane)

    def test_exact_fatal_file_line_scope_message_and_activity(self):
        texts,_=fixture(); site=controls.literal_site(texts['testbench.sv'],'RECEIPT_OFFER')
        log='FATAL: testbench.sv:3: RECEIPT_OFFER\n       Time: 12  Scope: Testbench.offer\n'
        good=dict(exit_code=0,timed_out=False); fault=dict(exit_code=1,timed_out=False)
        self.assertEqual(len(controls.classify(good,fault,log,site)),1)
        bad_logs=[log.replace('testbench.sv','other.sv'),log.replace(':3:',':4:'),log.replace('Testbench.offer','Testbench'),
                  log.replace('RECEIPT_OFFER','RECEIPT_IDLE_ASYNC_LEAK'),log.replace('Time: 12','Time: 0'),
                  log+log,log+'RISCAY_SOC_PASS\n',log+'SOC_DEADLINE\n','RECEIPT_OFFER\n','']
        for bad in bad_logs:
            with self.subTest(log=bad),self.assertRaises(ValueError):controls.classify(good,fault,bad,site)
        for compiled,simulated in [(dict(exit_code=1),fault),(good,dict(exit_code=0)),
                                   (good,dict(exit_code=1,timed_out=True)),(dict(exit_code=0,timed_out=True),fault)]:
            with self.assertRaises(ValueError):controls.classify(compiled,simulated,log,site)

    def test_baseline_rejects_no_activity_duplicates_and_unrelated_errors(self):
        good=dict(exit_code=0,timed_out=False)
        controls.classify(good,good,'RISCAY_SOC_PASS\n')
        for text in ('','RISCAY_SOC_PASS\nRISCAY_SOC_PASS\n','RISCAY_SOC_PASS\nERROR: x','SOC_DEADLINE'):
            with self.assertRaises(ValueError):controls.classify(good,good,text)

    def test_unique_site_ignores_display_and_comments_and_tracks_named_task_block(self):
        source='''module Testbench;
// $fatal(1,"EXACT");
task offer; begin : check
  $display("EXACT");
  if(bad) $fatal(1,"EXACT");
end endtask
endmodule
'''
        site=controls.literal_site(source,'EXACT')
        self.assertEqual((site['line'],site['scope']),(5,'Testbench.offer.check'))
        with self.assertRaises(ValueError):controls.literal_site(source.replace('if(bad)', '$fatal(1,"EXACT"); if(bad)'),'EXACT')

    def test_complete_explicit_cohort_rejects_missing_duplicate_and_wrong_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            good=cohort(Path(tmp)); self.assertEqual(len(controls.validate_cohort(good)),11)
            mutants=[]
            x=copy.deepcopy(good);x['fixtures'].pop();mutants.append(x)
            x=copy.deepcopy(good);x['fixtures'][0]=x['fixtures'][1];mutants.append(x)
            x=copy.deepcopy(good);x['fixtures'][0]['path']=x['fixtures'][0]['path'].replace('bd-retained','click-retained');mutants.append(x)
            x=copy.deepcopy(good);x['fixtures'][0]['path']='relative';mutants.append(x)
            x=copy.deepcopy(good);x['schema']='other';mutants.append(x)
            for x in mutants:
                with self.assertRaises(ValueError):controls.validate_cohort(x)

    def test_successful_fresh_regression_and_failed_stale_incomplete_variants(self):
        execution,before,log,command=regression(); controls.execution_header(execution,before,log,command)
        for key,value in [('status','RUNNING'),('exit_code',1),('sources_unchanged',False),('tools_unchanged',False),
                          ('error','failure'),('snapshot_errors',{'x':'failed'}),('ended_unix',0),
                          ('fresh_fixtures_sha256',{'old':{'rtl':'hash'}}),('test_summaries',[['19','0','0','0','0']])]:
            x=copy.deepcopy(execution);x[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):controls.execution_header(x,before,log,command)
        for bad in (log.replace('compiling 4 Scala sources','loaded cached classes'),log.replace('failed 0','failed 1'),
                    log.replace('QuiescingReceiptSpec:','OtherSpec:'),log+'[error] bad'):
            with self.assertRaises(ValueError):controls.execution_header(execution,before,bad,command)
        bad=command.copy();bad.remove('clean')
        x=copy.deepcopy(execution);x['command']=bad
        with self.assertRaises(ValueError):controls.execution_header(x,before,log,bad)

    def test_reviewed_inventory_is_exact_144_and_source_bound(self):
        inventory=controls.required_inventory()
        self.assertEqual({s:len(n) for s,n in inventory['suites'].items()},
                         {'QuiescingReceiptSpec':20,'QuiescingBridgeSpec':46,'ResetBoundarySpec':36,'ResetBoundarySocSpec':42})
        self.assertEqual(sum(map(len,inventory['suites'].values())),144)
        self.assertEqual(set(inventory['source_lf_sha256']),{
            'verification/src/test/scala/riscay/QuiescingReceiptSpec.scala',
            'verification/src/test/scala/riscay/QuiescingBridgeSpec.scala',
            'verification/src/test/scala/riscay/ResetBoundarySocSpec.scala'})
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'inventory.json'; altered=copy.deepcopy(inventory)
            path.write_bytes(controls.REQUIRED_INVENTORY.read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n'))
            with patch.object(controls,'REQUIRED_INVENTORY',path):self.assertEqual(controls.required_inventory(),inventory)
            altered['suites']['QuiescingReceiptSpec'].pop();path.write_text(json.dumps(altered))
            with patch.object(controls,'REQUIRED_INVENTORY',path),self.assertRaisesRegex(ValueError,'REVIEWED_INVENTORY_CHANGED'):
                controls.required_inventory()

    def test_selectors_filters_globs_split_duplicates_and_extra_commands_reject(self):
        execution,before,log,command=regression()
        for suffix in (' -- -z selected-fixture-only',' -- -t "one case"',' -- -n only-tag',' -- -l excluded-tag'):
            x=copy.deepcopy(execution);changed=command.copy();changed[3]+=suffix;x['command']=changed
            with self.subTest(suffix=suffix),self.assertRaises(ValueError):controls.execution_header(x,before,log,changed)
        commands=[]
        changed=command.copy();changed[3]=changed[3].replace('riscay.QuiescingReceiptSpec','riscay.*');commands.append(changed)
        changed=command.copy();changed.append('verification/testOnly riscay.QuiescingReceiptSpec');commands.append(changed)
        changed=command.copy();changed.append('set verification / Test / testOptions := Seq()');commands.append(changed)
        changed=command.copy();changed[3]+='; verification/testOnly riscay.QuiescingReceiptSpec';commands.append(changed)
        for changed in commands:
            x=copy.deepcopy(execution);x['command']=changed
            with self.assertRaises(ValueError):controls.execution_header(x,before,log,changed)

    def test_review_adversarial_one_or_eight_tests_with_all_headers_reject(self):
        for count in (1,8):
            execution,before,log,command=regression()
            prefix='compiling 4 Scala sources to /repo/verification\n'
            prefix+='\n'.join('[info] '+s+':' for s in ('QuiescingReceiptSpec','QuiescingBridgeSpec','ResetBoundarySpec','ResetBoundarySocSpec'))+'\n'
            prefix+='\n'.join('[info] - selected '+str(n) for n in range(count))+'\n'
            prefix+='[info] Run completed in 1 second.\n'+f'[info] Total number of tests run: {count}\n'
            prefix+='[info] Suites: completed 4, aborted 0\n'+f'[info] Tests: succeeded {count}, failed 0, canceled 0, ignored 0, pending 0\n[info] All tests passed.\n'
            bad=prefix+log[log.index('[info] PhysicalHelperSpec:'):]
            execution['test_summaries'][0][0]=str(count)
            with self.assertRaises(ValueError):controls.execution_header(execution,before,bad,command)

    def test_missing_renamed_duplicated_and_cross_suite_named_cases_reject(self):
        execution,before,log,command=regression()
        first='[info] - bd retained quiescing receipt preserves all 70 bits and stored-receiver cadence\n'
        mutants=[log.replace(first,first+first),log.replace(first,first.replace('all 70 bits','only one bit')),
                 log.replace('[info] QuiescingReceiptSpec:','[info] OtherReceiptSpec:')]
        for bad in mutants:
            with self.assertRaises(ValueError):controls.execution_header(execution,before,bad,command)
        # Even internally consistent reduced aggregate totals cannot hide one missing case.
        bad=log.replace(first,'').replace('tests run: 144','tests run: 143').replace('succeeded 144','succeeded 143')
        x=copy.deepcopy(execution);x['test_summaries'][0][0]='143'
        with self.assertRaises(ValueError):controls.execution_header(x,before,bad,command)

    def test_missing_duplicate_and_inconsistent_completion_records_reject(self):
        execution,before,log,command=regression()
        mutants=[log.replace('[info] Run completed in 1 second.\n','',1),
                 log.replace('[info] Suites: completed 4, aborted 0\n','',1),
                 log.replace('Suites: completed 4','Suites: completed 3',1),
                 log.replace('Suites: completed 4, aborted 0','Suites: completed 4, aborted 1',1),
                 log.replace('[info] All tests passed.\n','',1),
                 log.replace('[info] Suites: completed 4, aborted 0\n','[info] Suites: completed 4, aborted 0\n'*2),
                 log+'[info] QuiescingReceiptSpec:\n',
                 log+log[log.index('[info] PhysicalHelperSpec:'):]]
        for bad in mutants:
            with self.subTest(log=bad[-100:]),self.assertRaises(ValueError):controls.execution_header(execution,before,bad,command)

    def test_stale_source_class_binary_and_duplicate_json_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('source.scala','Owner.class','sim.vvp'):(root/name).write_text(name)
            identities={name:controls.sha(root/name) for name in ('source.scala','Owner.class','sim.vvp')}
            controls.check_hashes(root,identities)
            for name in identities:
                original=(root/name).read_bytes();(root/name).write_text('changed')
                with self.assertRaises(ValueError):controls.check_hashes(root,identities)
                (root/name).write_bytes(original)
            (root/'bad.json').write_text('{"schema":1,"schema":2}')
            with self.assertRaises(ValueError):controls.read_json(root/'bad.json')

    def test_plan_rebinding_is_exact_not_selected_field_checks(self):
        baseline=dict(schema='riscay-quiescing-controls-plan-v2',status='BOUND_TO_FRESH_REGRESSION',
                      execution='receipt.json',cohort='cohort.json',repository='repo',gate_graphs='graphs.json',fixtures=[dict(site='original')])
        with patch.object(controls,'bind_plan',return_value=copy.deepcopy(baseline)):
            controls.validate_plan(baseline)
            x=copy.deepcopy(baseline);x['fixtures'][0]['site']='edited'
            with self.assertRaises(ValueError):controls.validate_plan(x)

    def test_execution_stops_at_wrong_fatal_and_preserves_both_oracles_and_failed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();texts,manifest=fixture()
            for name,text in texts.items():(source/name).write_text(text)
            (source/'contract.json').write_text(json.dumps(dict(manifest=manifest)))
            (source/'ports.json').write_text('{}');(source/'filelist.f').write_text('unused helper fixture\n')
            files=[n for n in texts if n!='testbench.sv']
            name,changed,site=controls.mutate(texts,manifest,'bd','invalid-mask')
            job=dict(fault='invalid-mask',lane=None,file=name,before_sha256=controls.sha(source/name),
                     after_sha256=hashlib.sha256(changed.encode()).hexdigest(),site=site)
            group=dict(path=str(source),variant='bd',kind='invalid',files=files,inputs=controls.file_hashes(source),
                       mutations=[job],oracle_sha256=controls.sha(source/'testbench.sv'))
            plan=dict(fixtures=[group],binaries=dict(iverilog='mock-compiler',vvp='mock-simulator'))
            calls=[]
            def fake_run(command,folder,log_name,timeout):
                calls.append((command,timeout))
                if log_name=='compile.log':
                    (folder/'sim.vvp').write_text('mock binary; never executed');log='';code=0
                elif folder.name.endswith('baseline'):
                    log='RISCAY_SOC_PASS\n';code=0
                else:
                    log='FATAL: testbench.sv:1: WRONG_ASSERTION\n       Time: 1  Scope: Testbench\n';code=1
                (folder/log_name).write_text(log)
                return dict(exit_code=code,timed_out=False),log
            with patch.object(controls,'validate_plan'),patch.object(controls,'run_process',side_effect=fake_run):
                with self.assertRaisesRegex(ValueError,'CAMPAIGN_FAILED'):controls.execute(plan,root/'output')
            receipt=controls.read_json(root/'output/receipt.json')
            self.assertEqual(receipt['status'],'FAIL_OR_INCOMPLETE')
            self.assertEqual([r['status'] for r in receipt['records']],['PASS','FAIL_OR_INCOMPLETE'])
            self.assertEqual([t for _,t in calls],[60,90,60,90])
            self.assertEqual(controls.sha(source/'testbench.sv'),group['oracle_sha256'])
            for folder in (root/'output').iterdir():
                if folder.is_dir():self.assertEqual(controls.sha(folder/'testbench.sv'),group['oracle_sha256'])


if __name__ == '__main__':
    unittest.main()
