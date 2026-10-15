# SPDX-License-Identifier: Apache-2.0
"""Independent minimal-source tests; these do not simulate hardware."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

import bind_saved_address_controls as binder
import check_saved_address_controls as runner
import saved_address_fixture_contract as contract


# Deliberately explicit expected constants; not imported from the implementation.
WIDTHS={4:2,12:4,1024:10,1028:11,2048:11,3072:12}
RANGES={4:'|(probeAddress[31:2])',12:"probeAddress > 32'hB",1024:'|(probeAddress[31:10])',
        1028:"probeAddress > 32'h403",2048:'|(probeAddress[31:11])',3072:"probeAddress > 32'hBFF"}
NEGATIVE_COUNTS={4:264,12:256,1024:200,1028:200,2048:192,3072:192}


def source_sample(capacity,bank_annotation='designs/sample/SramBank.scala',fixture_annotation='fixture.scala'):
    source=f'''module SramSavedAddressFixture; // {fixture_annotation}:1:1
input [31:0] probeAddress;
reg [{WIDTHS[capacity]-1}:0] probe_saved_address; // {bank_annotation}:27:18
wire _GEN_7 = {RANGES[capacity]};
'''
    for lane in range(4):
        source+=f'''if (probe_io_request_{lane}_ready & probe_io_request_{lane}_valid & ~reset & _GEN_7) begin
  if (`ASSERT_VERBOSE_COND_)
    $error("Assertion failed: SRAM_BYTE_ADDRESS_OUT_OF_RANGE_LANE_{lane}\\n");
  if (`STOP_COND_)
    $fatal;
end
'''
    for bank in range((capacity+1023)//1024):
        source+=f'gf180mcu_ocd_ip_sram__sram1024x8m8wm1 probe_macros_{bank} ( );\n'
    return source+'endmodule\n'


def fixture_sample(root,variant,capacity,identity):
    root.mkdir()
    # A synthetic, independently constructed metadata/port cohort. No compiler
    # or simulator ever consumes this helper fixture.
    groups = {
        ('input',1): 'reset serviceClock watchdogClock scl sda adcMiso request_valid response_ready probeValid probeWrite probeEnable answerReady',
        ('input',2): 'request_bits_operation probeLane', ('input',4): 'request_bits_mask',
        ('input',8): 'probeData', ('input',32): 'gpioIn request_bits_data request_bits_address probeAddress',
        ('output',1): 'sdaLow adcCsN adcSclk programmed locked systemReset resetReason sleeping serviceClockEnable trace_trap trace_writeRegister trace_valid traceEvent commit_valid request_ready response_bits_error response_valid probeReady answerValid',
        ('output',2): 'commit_bits_operation capturedTag stateView', ('output',3): 'mode',
        ('output',4): 'trace_cause trace_rd commit_bits_mask', ('output',8): 'answerData',
        ('output',32): 'gpioOut gpioOe sleepEntries trace_data trace_instruction trace_pc commit_bits_data commit_bits_address response_bits_data timeNow',
        ('output',42): 'captured',
    }
    specs = {name:(direction,width) for (direction,width),names in groups.items() for name in names.split()}
    for bank in range((capacity+1023)//1024):
        for name,width in (('macroAddress',10),('macroData',8),('macroCen',1),('macroGwen',1)):
            specs[f'{name}_{bank}']=('output',width)
    ports=[]
    for name,(direction,width) in specs.items():
        if name.startswith(('trace_','request_','response_','commit_')): field=name.replace('_','.')
        elif name.startswith('macro'): field=name.rsplit('_',1)[0]+'['+name.rsplit('_',1)[1]+']'
        else:field=name
        ports.append(dict(source='~|SramSavedAddressFixture>'+field,width=width,signed=False,direction=direction,
                          clock=name in ('serviceClock','watchdogClock')))
    source=source_sample(capacity,identity[variant]['annotation'],identity['fixture']['annotation'])
    source=source.replace('module SramSavedAddressFixture;','module SramSavedAddressFixture(\n'+
        ',\n'.join(f'{direction} [{width-1}:0] {name}' for name,(direction,width) in specs.items())+'\n);')
    source=source.replace('input [31:0] probeAddress;\n','')
    (root/'SramSavedAddressFixture.sv').write_text(source)
    catalog=json.loads((contract.ASSETS/'root-contract.json').read_text());children=catalog.pop('child_ids')
    abi_nodes=[dict(rtl_path='SramSavedAddressFixture',module='SramSavedAddressFixture',ports=ports,
                    channels=[dict(source='~|SramSavedAddressFixture>'+name,protocol='decoupled-v1') for name in ('request','response')])]
    catalog['children']=[]
    for name in children:
        path='SramSavedAddressFixture.ca_child_'+name
        node=dict(rtl_path=path,module='HelperUnit',reset_domain='root',capacity=1,endpoints=[],channels=[],
                  primitives=[],timing=[],children=[])
        catalog['children'].append(dict(id=name,contract=node))
        abi_nodes.append(dict(rtl_path=path,module='HelperUnit',ports=[],channels=[]))
    catalog['children'][0]['contract']['primitives']=[dict(id='cell',resource='helper/HelperUnit.sv')]
    (root/'HelperUnit.sv').write_text('module HelperUnit(); endmodule\n')
    (root/'ports.json').write_text(json.dumps(dict(schema='chisel-async-port-abi-v2',top='SramSavedAddressFixture',nodes=abi_nodes)))
    (root/'ref_SramSavedAddressFixture.sv').write_text('// synthetic probe metadata, never compiled\n')
    (root/'filelist.f').write_text('SramSavedAddressFixture.sv\nHelperUnit.sv\n')
    manifest=dict(schema='chisel-async-contract-v3',time_unit='fs',time_range='0..9223372036854775807',
        top='SramSavedAddressFixture',toolchain=dict(chisel='7.16.0',scala='2.13.18',firtool='1.160.0',options=[
        '-O=release','--strip-fir-debug-info','--lowering-options=disallowPortDeclSharing,disallowLocalVariables']),
        resources={'helper/HelperUnit.sv':hashlib.sha256((root/'HelperUnit.sv').read_text().encode()).hexdigest()},rtl_semantic_sha256={},
        probe_abi=dict(file='ref_SramSavedAddressFixture.sv',sha256=runner.sha(root/'ref_SramSavedAddressFixture.sv')),
        port_abi=dict(file='ports.json',sha256=runner.sha(root/'ports.json')),design=catalog)
    for filename in ('SramSavedAddressFixture.sv','HelperUnit.sv'):
        text=(root/filename).read_text()
        if filename=='HelperUnit.sv':text='// Generated by CIRCT firtool-1.160.0\n'+text
        manifest['rtl_semantic_sha256'][filename]=hashlib.sha256(text.encode()).hexdigest()
    semantic=hashlib.sha256(json.dumps(manifest,separators=(',',':')).encode()).hexdigest()
    (root/'contract.json').write_text(json.dumps(dict(semantic_sha256=semantic,manifest=manifest)))
    (root/'sim.vvp').write_text('synthetic unit-test placeholder, never executed')
    (root/'compile.log').write_text('')
    (root/'simulation.log').write_text('RISCAY_SOC_PASS\n')
    (root/'testbench.sv').write_text(contract.testbench(capacity))
    return dict(variant=variant,bytes=capacity,path=str(root.resolve()))


class PredicateBindings(unittest.TestCase):
    def test_all_six_capacities_bind_all_four_actual_fire_forms(self):
        for capacity in WIDTHS:
            source=source_sample(capacity)
            sites,bindings,_=binder.bind_emitted_predicates(source,'fixture.sv',capacity)
            self.assertEqual(set(sites),{'0','1','2','3'})
            for lane in range(4):
                site=sites[str(lane)]
                runner.validate_probe_predicate(source.splitlines(),dict(bytes=capacity,probe_predicates=bindings),
                                                lane,site['error_line'],site['fatal_line'])

    def test_range_width_lane_assertion_and_guard_mutations_reject(self):
        for capacity in WIDTHS:
            source=source_sample(capacity)
            faults=[source.replace('input [31:0]','input [30:0]'),
                    source.replace(f'reg [{WIDTHS[capacity]-1}:0]',f'reg [{WIDTHS[capacity]}:0]'),
                    source.replace(RANGES[capacity],'1\'b0'),
                    source.replace('wire _GEN_7 =','wire _GEN_8 ='),
                    source.replace('input [31:0] probeAddress;','input [31:0] probeAddress;\ninput [31:0] probeAddress;'),
                    source+'assign _GEN_7 = 1\'b0;\n',
                    source.replace('if (`STOP_COND_)','if (0)'),
                    source.replace('if (`ASSERT_VERBOSE_COND_)','if (0)'),
                    source.replace('SRAM_BYTE_ADDRESS_OUT_OF_RANGE_LANE_0','WRONG_ASSERTION'),
                    source.replace('$fatal;','$display("fatal");'),
                    source.replace('probe_io_request_0_ready','fabric_ram_io_request_0_ready'),
                    source.replace('probe_io_request_0_valid','1\'b1'),
                    source.replace('~reset & _GEN_7','1\'b1 & _GEN_7'),
                    source.replace('~reset & _GEN_7','~reset & _GEN_7 & probeEnable')]
            for altered in faults:
                with self.assertRaises(ValueError,msg=(capacity,altered)):
                    binder.bind_emitted_predicates(altered,'fixture.sv',capacity)

    def test_retargeted_metadata_cannot_authorize_wrong_predicates(self):
        source=source_sample(1028);sites,bindings,_=binder.bind_emitted_predicates(source,'fixture.sv',1028)
        for fault in ('definition','condition','line','guard'):
            lines=source.splitlines();group=dict(bytes=1028,probe_predicates=copy.deepcopy(bindings));binding=group['probe_predicates']['2']
            if fault=='definition':
                lines[binding['definition_line']-1]=lines[binding['definition_line']-1].replace("32'h403","32'h407")
                binding['definition']=lines[binding['definition_line']-1]
            elif fault=='condition':
                lines[binding['condition_line']-1]=lines[binding['condition_line']-1].replace('~reset',"1'b1")
                binding['condition']=lines[binding['condition_line']-1]
            elif fault=='line':binding['condition_line']+=1
            else:lines[binding['condition_line']]='if (0)'
            with self.assertRaises(ValueError):
                runner.validate_probe_predicate(lines,group,2,sites['2']['error_line'],sites['2']['fatal_line'])


class ExactDiagnostics(unittest.TestCase):
    def test_blank_lines_are_allowed_but_full_fatal_identity_is_mandatory(self):
        path=str(Path('fixture.sv').resolve());site=dict(file=path,error_line=10,fatal_line=12,scope='Testbench.dut')
        error=f'ERROR: {path}:10: Assertion failed: SRAM_BYTE_ADDRESS_OUT_OF_RANGE_LANE_2\n\n       Time: 123  Scope: Testbench.dut\n'
        fatal=f'FATAL: {path}:12: \n       Time: 123  Scope: Testbench.dut\n';log=error+fatal
        self.assertEqual([r['kind'] for r in runner.classify(log,1,site,2)],['ERROR','FATAL'])
        faults=[log.replace('\n\n','\nnonblank\n'),log.replace(':10:',':11:'),log.replace(':12:',':13:'),
                log.replace('LANE_2','LANE_1'),log.replace('Testbench.dut','Testbench.other'),
                log.replace('Time: 123','Time: 124',1),error,fatal,log+fatal,
                log+'SOC_DEADLINE\n',log+'RISCAY_SOC_PASS\n',log+'SAVED_ADDRESS_INVALID_WAS_ACCEPTED\n']
        for altered in faults:
            with self.assertRaises(ValueError):runner.classify(altered,1,site,2)
        with self.assertRaises(ValueError):runner.classify(log,0,site,2)


class InventoryAndSources(unittest.TestCase):
    def test_exact_1304_cases_with_boundary_read_disabled_and_all_high_bits(self):
        total=0
        for capacity in WIDTHS:
            cases=runner.case_inventory(capacity);self.assertEqual(cases[0],('positive',None,None,None,None))
            actual={tuple(c[1:]) for c in cases[1:]};expected=set()
            for lane in range(4):
                addresses={capacity+lane,0xffffffff}
                addresses.update((1<<bit)|lane for bit in range(WIDTHS[capacity],32))
                expected.update((lane,address,1,1) for address in addresses)
                expected.update(((lane,capacity+lane,0,1),(lane,capacity+lane,1,0)))
            self.assertEqual(actual,expected);self.assertEqual(len(actual),len(cases)-1)
            self.assertEqual(2*len(actual),NEGATIVE_COUNTS[capacity]);total+=2*len(actual)
        self.assertEqual(total,1304)
        for capacity in (0,True,4.0,16):
            with self.assertRaises(ValueError):runner.case_inventory(capacity)

    def test_explicit_complete_cohort_rejects_aliases_missing_and_relative_paths(self):
        groups=[dict(variant=v,bytes=c,path=str(Path(f'fixture-{v}-{c}').resolve())) for v in ('bd','click') for c in WIDTHS]
        runner.validate_cohort(groups)
        faults=[groups[:-1],copy.deepcopy(groups),copy.deepcopy(groups),copy.deepcopy(groups),copy.deepcopy(groups)]
        faults[1][-1]=faults[1][0];faults[2][-1]['path']=faults[2][0]['path']
        faults[3][0]['path']='relative';faults[4][0]['bytes']=4.0
        for altered in faults:
            with self.assertRaises(ValueError):runner.validate_cohort(altered)

    def test_source_hashes_annotations_and_explicit_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source_root=root/'candidate';source_root.mkdir()
            for relative in runner.SOURCE_PATHS.values():
                path=source_root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('source identity only')
            identity=binder.source_identity(root,source_root)
            record=fixture_sample(root/'fixture','click',3072,identity)
            bound=binder.bind_fixture(record,identity)
            self.assertEqual(len(bound['assertions']),4)
            self.assertEqual(bound['inputs'],runner.source_inventory(Path(record['path'])))
            changed=copy.deepcopy(identity);changed['click']['annotation']='wrong/'+runner.SOURCE_PATHS['click']
            with self.assertRaises(ValueError):runner.validate_source_identity(changed)
            changed=copy.deepcopy(identity);changed['bd']['sha256']='0'*64
            with self.assertRaises(ValueError):runner.validate_source_identity(changed)
            (source_root/runner.SOURCE_PATHS['fixture']).write_text('changed after binding')
            with self.assertRaises(ValueError):runner.validate_source_identity(identity)

    def test_fixture_wrong_source_capacity_oracle_positive_and_nonlocal_input_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source_root=root/'source';source_root.mkdir()
            for relative in runner.SOURCE_PATHS.values():
                path=source_root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('source identity only')
            identity=binder.source_identity(root,source_root)
            for fault in ('source','capacity','oracle','positive','nonlocal','macro'):
                record=fixture_sample(root/('fixture-'+fault),'bd',12,identity);folder=Path(record['path'])
                binder.bind_fixture(record,identity)
                if fault=='source':
                    path=folder/'SramSavedAddressFixture.sv';path.write_text(path.read_text().replace(identity['bd']['annotation'],'wrong.scala'))
                elif fault=='capacity':record['bytes']=1024
                elif fault=='oracle':
                    path=folder/'testbench.sv';path.write_text(path.read_text().replace('SAVED_ADDRESS_STOP_PHASE','REMOVED'))
                elif fault=='positive':(folder/'simulation.log').write_text('SOC_DEADLINE\n')
                elif fault=='macro':
                    path=folder/'SramSavedAddressFixture.sv';path.write_text(path.read_text().replace('probe_macros_0 (','probe_macros_1 ('))
                else:
                    outside=root/'outside.sv';outside.write_text('not local')
                    path=folder/'filelist.f';path.write_text(path.read_text()+'../outside.sv\n')
                with self.assertRaises(ValueError):binder.bind_fixture(record,identity)


class FullFixtureContract(unittest.TestCase):
    def identity(self,root):
        for relative in runner.SOURCE_PATHS.values():
            path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('independent helper source identity')
        return binder.source_identity(root,root)

    def test_full_oracle_guards_tasks_stimulus_and_clock_mutations_reject(self):
        for capacity in (4,12,1024,1028,2048,3072):
            original=contract.testbench(capacity);contract.validate_testbench(original,capacity)
            pairs=[
                ('$fatal(1,"SAVED_ADDRESS_FULL_CAPTURE")','$display("SAVED_ADDRESS_FULL_CAPTURE")'),
                ('if(captured!==sampledRequest || capturedTag!==sampledLane)',"if(1'b0 && (captured!==sampledRequest || capturedTag!==sampledLane))"),
                ('!reset && !negativeCampaign && probeValid && probeReady',"1'b0 && !reset && !negativeCampaign && probeValid && probeReady"),
                ('sampledRequest={probeAddress,probeWrite,probeData,probeEnable}','sampledRequest=captured'),
                ('@(posedge serviceClock); while(!probeReady) @(posedge serviceClock);','@(posedge serviceClock);'),
                ('#1; probeValid=0; probeAddress=~offset; probeData=~data;','#1; probeValid=0;'),
                ('repeat(4) begin @(negedge serviceClock);','repeat(0) begin @(negedge serviceClock);'),
                ('#25.0; if(clockEnabled)','#24.0; if(clockEnabled)'),
                ('for(phase=0;phase<4;phase=phase+1)','for(phase=1;phase<4;phase=phase+1)'),
                ('#1000;\n          if(captured!==heldCapture','#1;\n          if(captured!==heldCapture'),
                ('beforeWrites=writes; reset=1; #2000; reset=0; #3000;','beforeWrites=writes; #2000; #3000;'),
                ('issue(negativeLane,negativeAddress,negativeWrite',"issue(negativeLane,32'b0,negativeWrite"),
                ('if(macroCen_0 !==','if(0 && macroCen_0 !=='),
                ('if(expectedEnable && $realtime-accessAt<50)','if(0)'),
                ('if(accessAt>0 && $realtime-accessAt<5)','if(0)'),
                ('if(!expectedEnable || expectedAddress/1024!=0','if(0 && !expectedEnable || expectedAddress/1024!=0'),
            ]
            for before,after in pairs:
                self.assertIn(before,original)
                with self.assertRaisesRegex(ValueError,'COMPLETE_TESTBENCH_ORACLE'):
                    contract.validate_testbench(original.replace(before,after),capacity)

    def test_only_clean_compile_output_and_exact_known_macro_notices_are_allowed(self):
        good='\n'.join(f'P:/fixture/{contract.MACRO}:{line}: warning: Choosing typ expression.'
                       for line in (263,264,265,267,268,269,270,271,273,274))+'\n'
        contract.validate_compile_log('');contract.validate_compile_log(good)
        for bad in (good+'error: a failed compiler\n',good+'WARNING: unknown\n',good+good,
                    good.replace(':263:',':262:'),good.replace('typ expression','min expression'),
                    good.replace('P:/fixture/','P:/other/',1), '\n'.join(good.splitlines()[1:])):
            with self.assertRaisesRegex(ValueError,'BASELINE_COMPILE_DIAGNOSTIC'):
                contract.validate_compile_log(bad)

    def test_metadata_rejects_rehashed_malformed_shapes_ports_and_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);identity=self.identity(root)
            record=fixture_sample(root/'fixture','bd',12,identity);folder=Path(record['path'])
            binder.bind_fixture(record,identity)
            originals={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}
            def reseal():
                document=json.loads((folder/'contract.json').read_text());manifest=document['manifest']
                manifest['port_abi']['sha256']=runner.sha(folder/'ports.json')
                document['semantic_sha256']=hashlib.sha256(json.dumps(manifest,separators=(',',':')).encode()).hexdigest()
                (folder/'contract.json').write_text(json.dumps(document))
            for fault in ('empty-design','empty-children','wrong-schema','wrong-top','width','width-type',
                          'direction','clock','source','duplicate-port','duplicate-node','node-module',
                          'port-schema','port-top','missing-port-node','rtl','resource','manifest-hash','extra-field'):
                for name,contents in originals.items():(folder/name).write_bytes(contents)
                document=json.loads((folder/'contract.json').read_text());abi=json.loads((folder/'ports.json').read_text())
                manifest=document['manifest'];port=next(p for p in abi['nodes'][0]['ports'] if p['source'].endswith('>probeAddress'))
                if fault=='empty-design':manifest['design']={}
                elif fault=='empty-children':manifest['design']['children']=[]
                elif fault=='wrong-schema':manifest['schema']='wrong'
                elif fault=='wrong-top':manifest['top']='Other'
                elif fault=='width':port['width']=31
                elif fault=='width-type':port['width']=32.0
                elif fault=='direction':port['direction']='output'
                elif fault=='clock':port['clock']=True
                elif fault=='source':port['source']='~|Other>probeAddress'
                elif fault=='duplicate-port':abi['nodes'][0]['ports'].append(copy.deepcopy(port))
                elif fault=='duplicate-node':abi['nodes'].append(copy.deepcopy(abi['nodes'][0]))
                elif fault=='node-module':abi['nodes'][0]['module']='Other'
                elif fault=='port-schema':abi['schema']='wrong'
                elif fault=='port-top':abi['top']='Other'
                elif fault=='missing-port-node':abi['nodes'].pop()
                elif fault=='rtl':
                    p=folder/'SramSavedAddressFixture.sv';p.write_text(p.read_text().replace('probe_saved_address','other_saved_address'))
                elif fault=='resource':manifest['resources']['helper/HelperUnit.sv']='0'*64
                elif fault=='extra-field':manifest['unexpected']=True
                (folder/'contract.json').write_text(json.dumps(document));(folder/'ports.json').write_text(json.dumps(abi));reseal()
                if fault=='manifest-hash':
                    document=json.loads((folder/'contract.json').read_text());document['semantic_sha256']='0'*64
                    (folder/'contract.json').write_text(json.dumps(document))
                with self.subTest(fault=fault),self.assertRaises((ValueError,KeyError)):
                    binder.bind_fixture(record,identity)

    def test_runner_rebinds_every_fixture_and_actual_binder_before_process_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);identity=self.identity(root)
            records=[fixture_sample(root/f'{variant}-{capacity}',variant,capacity,identity)
                     for variant in ('bd','click') for capacity in (4,12,1024,1028,2048,3072)]
            plan=binder.make_plan(dict(schema='riscay-sram-saved-cohort-v1',fixtures=records),root,root)
            runner.validate_plan(plan)
            for fault in ('binder','tool','swap-first','swap-last','scope','last-input','last-oracle'):
                altered=copy.deepcopy(plan)
                if fault=='binder':altered['binder_sha256']='0'*64
                elif fault=='tool':altered['tool_inputs'][next(iter(altered['tool_inputs']))]='0'*64
                elif fault.startswith('swap'):
                    index=0 if fault=='swap-first' else 5
                    altered['fixtures'][index]['variant']='click';altered['fixtures'][index+6]['variant']='bd'
                elif fault=='scope':altered['fixtures'][-1]['assertions']['3']['scope']='Testbench.other'
                elif fault=='last-input':altered['fixtures'][-1]['inputs']['missing']='0'*64
                elif fault=='last-oracle':
                    altered['fixtures'][-1]['metadata']['top_ports']=1
                plan_path=root/(fault+'.json');plan_path.write_text(json.dumps(altered))
                with patch.object(sys,'argv',['runner','--plan',str(plan_path),'--out',str(root/(fault+'-output'))]), \
                     patch.object(runner.subprocess,'run',side_effect=AssertionError('hardware must not launch')) as process:
                    with self.assertRaises(ValueError):runner.main()
                    process.assert_not_called()
            baseline=root/'baseline.json';baseline.write_text(json.dumps(plan))
            with patch.object(sys,'argv',['runner','--plan',str(baseline),'--out',str(root/'baseline-output')]), \
                 patch.object(runner.subprocess,'run',side_effect=RuntimeError('execution sentinel')) as process:
                with self.assertRaisesRegex(RuntimeError,'execution sentinel'):runner.main()
                process.assert_called_once()


if __name__=='__main__':unittest.main()
