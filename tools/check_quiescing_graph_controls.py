# SPDX-License-Identifier: Apache-2.0
"""Exact C1e mutations on four fresh strict proc/flatten graphs.

Read-only proof replay; never elaborates, converts, simulates or maps hardware.
Full audit_graph runs unchanged, including real coordinator and POR proofs.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import time

import check_quiescing_receipt_controls as regression
from check_frame_store_controls import helper_closure
from check_reset_crossings import audit_graph, SRAM
from reset_bridge_proof import Cone, sram_capacities
from reset_coordinator_proof import work_clock
from quiescing_receipt_proof import FIELDS

KEYS = tuple(s+'/'+v for s in ('portable-r1','physical-r1') for v in ('bd','click'))
GENERATED = ('mapping-probe-attestation.json','contract_probe.sv','contract_probe.vvp',
             'contract_simulation.log','resolved.json','reset-crossings/report.json','reset-crossings/netlist.json',
             'reset-crossings/sv2v.log','reset-crossings/yosys.log')
LIMITS = ('Structural graph controls only. The historical 152 synthetic negatives remain separate. '
          'Fresh functional/strict execution, real production-gate stimulus, source retention, '
          'cost and physical setup/hold/mask-release/reset qualification remain separate gates.')


def need(value, reason):
    if not value:
        raise ValueError('QUIESCING_GRAPH_CONTROL_'+reason)


sha = regression.sha
read_json = regression.read_json
write_json = regression.write_json


def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def local(base, name):
    path=(base/name).resolve()
    need(not Path(name).is_absolute() and path.is_relative_to(base.resolve()),'NONLOCAL_INPUT')
    return path


def bind(inputs, path, digest=None):
    path=Path(path).resolve();actual=sha(path)
    need(digest is None or actual==digest,'INPUT_CHANGED:'+str(path))
    need(str(path) not in inputs or inputs[str(path)]==actual,'INPUT_CHANGED_DURING_BINDING')
    inputs[str(path)]=actual
    return path


def rehash(inputs):
    for name,digest in inputs.items():
        need(sha(name)==digest,'STALE_INPUT:'+name)


def and_tree(cone, vector, stop=()):
    """Scalar AND ancestors only; other expressions remain opaque leaves."""
    need(len(vector)==1,'SCALAR_AND_ROOT')
    found={};leaves=[];active=set()
    def visit(bit):
        if bit in stop or bit not in cone.drivers:
            leaves.append(bit);return
        name,cell,port,index=cone.drivers[bit];pins=cell['connections']
        if cell['type'] not in ('$and','$logic_and'):
            leaves.append(bit);return
        need(name not in active,'CYCLIC_AND_CONE')
        need(port=='Y' and index==0 and set(pins)=={'A','B','Y'} and
             all(len(pins[p])==1 for p in pins),'SCALAR_AND_CELL')
        active.add(name);found[name]=cell
        visit(pins['A'][0]);visit(pins['B'][0]);active.remove(name)
    visit(vector[0])
    return found,leaves


def saved_data_sink(cone,clock):
    vector=cone.bits('fabric_ram_saved_data')
    need(len(vector)==8 and all(bit in cone.drivers for bit in vector),'ACTUAL_PERIODIC_DATA_SINK')
    names={cone.drivers[bit][0] for bit in vector}
    need(len(names)==1,'UNIQUE_PERIODIC_DATA_SINK')
    name=names.pop();cell=cone.module['cells'][name];pins=cell['connections']
    need(cell['type'] in ('$dff','$adff') and pins['Q']==vector and len(pins['D'])==8 and
         pins['CLK']==clock and cell['parameters']['CLK_POLARITY']=='1' and
         all(cone.drivers[bit][2:]==('Q',i) for i,bit in enumerate(vector)),'ACTUAL_PERIODIC_DATA_SINK')
    return name,cell


def targets(database,top):
    """Resolve fixed logical roles from actual connections, never cell numbering."""
    need(top in ('FourPhaseSoc','ClickSoc'),'SOC_TOP')
    module=database['modules'][top];cone=Cone(module);prefix='ca_child_request_bridge'
    source_name='ca_child_core.ca_child_address.ca_primitive_payload'
    source=module['cells'][source_name]
    model=database['modules'].get(source['type'],{}).get('attributes',{}).get('hdlname',source['type']).split()[0]
    need(model==('ChiselAsyncEventRegister_v1' if top=='ClickSoc' else 'ChiselAsyncClosingLatch_v1') and
         len(source['connections']['q'])==70,'NATIVE_SOURCE')
    q=source['connections']['q'];valid=cone.bits(prefix+'.out_valid');masks={}
    for field,(offset,width) in FIELDS.items():
        incoming=cone.bits(prefix+'.in_bits_'+field);out=cone.bits(prefix+'.out_bits_'+field)
        need(incoming==cone.bits('ca_child_transactions.serviceRequest_bits_'+field)==q[offset:offset+width],
             'SOURCE_PACKING_'+field)
        need(len(out)==width and all(bit in cone.drivers for bit in out),'MASK_OUTPUT_'+field)
        names={cone.drivers[b][0] for b in out};need(len(names)==1,'UNIQUE_MASK_'+field)
        name=names.pop();cell=module['cells'][name]
        need(cell['type']=='$mux' and cell['connections']==dict(A=['0']*width,B=incoming,S=valid,Y=out),
             'MASK_CONNECTIONS_'+field)
        need(all(cone.drivers[b][2:]==('Y',i) for i,b in enumerate(out)),'MASK_LANE_ORDER_'+field)
        masks[field]=name
    need(len(set(masks.values()))==4,'FOUR_MASK_CELLS')
    clock=work_clock(cone)
    ready=cone.bits(prefix+'.out_ready');available=cone.bits('fabric_cpuAvailable');gate=cone.bits('gate_enabled')
    need(ready==cone.bits('fabric_io_request_ready') and len(available)==len(gate)==1,'READY_ALIASES')
    _,leaves=and_tree(cone,ready,available)
    need(leaves.count(available[0])==1,'CPU_AVAILABLE_ACTUAL_READY_FACTOR')
    cpu_cells,_=and_tree(cone,available,gate)
    factors=[(name,pin) for name,cell in cpu_cells.items() for pin in ('A','B') if cell['connections'][pin]==gate]
    need(len(factors)==1,'UNIQUE_CPU_CLOCK_FACTOR')
    sink_name,sink=saved_data_sink(cone,clock)
    need(sink['connections']['D'][0]!=q[FIELDS['data'][0]],'ACTUAL_PERIODIC_DATA_SINK')
    return dict(masks=masks,ready_cell=factors[0][0],ready_pin=factors[0][1],gate=gate,
                sink=sink_name,source_data_bit=q[FIELDS['data'][0]],source=source_name)


def obligations(database,top):
    bound=targets(database,top);jobs=[]
    cells=database['modules'][top]['cells']
    def add(label,cell,pin,index,after,expected):
        before=cells[cell]['connections'][pin][index]
        need(before!=after,'VACUOUS_MUTATION')
        jobs.append(dict(label=label,cell=cell,pin=pin,index=index,before=before,after=after,expected=expected))
    for field,(_,width) in FIELDS.items():
        name=bound['masks'][field];expected='RDC_QUIESCING_RECEIPT_EXACT_MASK_'+field
        for lane in range(width):add('source-'+field+'-'+str(lane),name,'B',lane,'0',expected)
        add('mask-'+field,name,'S',0,'1',expected)
    add('ready-clock-factor',bound['ready_cell'],bound['ready_pin'],0,'1','RDC_QUIESCING_RECEIPT_READY_WITHOUT_WORK_CLOCK')
    add('unmasked-periodic-sink',bound['sink'],'D',0,bound['source_data_bit'],
        'RDC_QUIESCING_RECEIPT_UNMASKED_PERIODIC_SINK_'+bound['sink']+'_D')
    need(len(jobs)==76 and len({j['label'] for j in jobs})==76,'EXACT_76_OBLIGATIONS')
    return jobs


def mutated(database,top,job):
    result=copy.deepcopy(database);pins=result['modules'][top]['cells'][job['cell']]['connections']
    need(pins[job['pin']][job['index']]==job['before'] and job['after']!=job['before'],'MUTATION_REBIND')
    pins[job['pin']][job['index']]=job['after']
    # Reversibility proves there is exactly one changed actual connection.
    restored=copy.deepcopy(result)
    restored['modules'][top]['cells'][job['cell']]['connections'][job['pin']][job['index']]=job['before']
    need(restored==database,'EXTRA_GRAPH_MUTATION')
    return result


def baseline(database,top,capacities,saved):
    before=canonical(database)
    result=audit_graph(database,top,capacities)
    need(canonical(database)==before,'AUDIT_CHANGED_GRAPH')
    need(canonical(result)==canonical({k:v for k,v in saved.items() if k!='inputs'}) and result['status']=='pass' and
         result['violations']==[],'FULL_BASELINE_MISMATCH')
    proofs=result['receiver_proofs']
    need(sum(p['prefix']=='applicationResetCoordinator' for p in proofs)==1,'REAL_COORDINATOR_REQUIRED')
    masks=[p for p in proofs if p['prefix']=='ca_child_request_bridge' and p.get('source_width')==70]
    need(len(masks)==1 and masks[0]['masked_bits']==70 and len(masks[0]['mask_cells'])==4,'REAL_MASK_PROOF_REQUIRED')
    return result


def negative(database,top,capacities,job):
    changed=mutated(database,top,job);before=canonical(changed)
    try:
        audit_graph(changed,top,capacities)
    except ValueError as error:
        need(str(error)==job['expected'],'WRONG_DIAGNOSTIC:'+str(error))
    else:
        raise ValueError('QUIESCING_GRAPH_CONTROL_SURVIVED:'+job['label'])
    need(canonical(changed)==before,'AUDIT_CHANGED_MUTANT')
    return dict(status='EXACT_REJECTION',diagnostic=job['expected'],mutant_canonical_sha256=before)


def graph_inputs(export,report,root,tool_inputs,inputs):
    """Check the exact unoptimized producer script and all saved transformations."""
    record=report['inputs'];folder=export/'reset-crossings';top=record['top']
    need(record['contract_sha256']==sha(export/'contract.json') and record['filelist_sha256']==sha(export/'filelist.f'),
         'GRAPH_EXPORT_BINDING')
    listed=[n.strip() for n in (export/'filelist.f').read_text().splitlines() if n.strip()]
    need(set(record['sources'])==set(listed) and len(listed)==len(set(listed)),'GRAPH_SOURCE_INVENTORY')
    lock=read_json(root/'tools/gf180-estimate-inputs.json');bind(inputs,root/'tools/gf180-estimate-inputs.json')
    sram=root/'soc/src/main/resources/riscay/sram'/(SRAM+'.blackbox.v')
    bind(inputs,sram,record['sram_blackbox_sha256'])
    sram_lock=read_json(bind(inputs,root/'soc/sram-lock.json'))
    need(sha(sram)==sram_lock['assets'][sram.name]['sha256'],'PINNED_SRAM_BLACKBOX')
    names=[]
    for name in listed:
        original=bind(inputs,local(export,name),record['sources'][name]);names.append(original.name)
        text=original.read_text()
        if original.name.startswith('ChiselAsync'):
            a=text.index('module ');b=text.index(');',a)+2
            text='(* blackbox *)\n'+text[a:b]+'\nendmodule\n'
            text=text.replace('parameter time','parameter [63:0]').replace('parameter longint unsigned','parameter [63:0]').replace('parameter bit','parameter')
        elif original.name==SRAM+'.sv':text=sram.read_text()
        target=bind(inputs,folder/original.name)
        need(target.read_text()==text,'GRAPH_TRANSFORM_CHANGED:'+original.name)
    need(len(names)==len(set(names)),'GRAPH_DUPLICATE_BASENAME')
    def linux(p):
        text=str(Path(p).resolve()).replace('\\','/')
        need(re.match(r'^[A-Za-z]:/',text) is not None,'GRAPH_WINDOWS_ROOT')
        return '/mnt/'+text[0].lower()+text[2:]
    tools={name:Path(record['tools'][name]['path']) for name in ('sv2v','yosys')}
    need(set(record['tools'])==set(tools),'GRAPH_TOOL_INVENTORY')
    for name,path in tools.items():
        need(str(path.resolve()) in tool_inputs and record['tools'][name]['sha256']==tool_inputs[str(path.resolve())]==lock['tools'][name]['sha256'],
             'GRAPH_TOOL_BINDING:'+name)
        bind(inputs,path,record['tools'][name]['sha256'])
    script=(f'read_verilog -sv {linux(folder/"converted.v")}\n'
            f'hierarchy -check -top {top}\nproc\nflatten\nopt_clean\n'
            f'write_json {linux(folder/"netlist.json")}\n')
    need((folder/'graph.ys').read_text()==script,'ACTUAL_PROC_FLATTEN_SCRIPT')
    commands=[['wsl','-e',linux(tools['sv2v']),'-DSYNTHESIS',*[linux(folder/n) for n in names]],
              ['wsl','-e',linux(tools['yosys']),'-s',linux(folder/'graph.ys')]]
    need(record['commands']==commands,'GRAPH_EXECUTED_COMMANDS')
    for name,key in [('graph.ys','script_sha256'),('converted.v','converted_sha256'),('netlist.json','netlist_sha256')]:bind(inputs,folder/name,record[key])
    for name in ('sv2v.log','yosys.log'):bind(inputs,folder/name)
    log=(folder/'yosys.log').read_text()
    need('Executing JSON backend.' in log and 'End of script.' in log and not re.search(r'ERROR:|TIMEOUT',log),'GRAPH_PRODUCER_COMPLETION')
    need(record['sram_inventory_sha256']==sha(export/'sram.json'),'GRAPH_SRAM_INVENTORY')
    return read_json(folder/'netlist.json')


def strict_case(key,case,before,execution,base,strict_dir,root,inputs):
    export=(base/key).resolve();top='FourPhaseSoc' if key.endswith('/bd') else 'ClickSoc'
    need(case['status']=='PASS' and case['exit_code']==0 and not case.get('exception') and not case.get('timed_out'), 'STRICT_CASE_NOT_PASS')
    need(execution['ended_unix']*1e9<=case['started_unix_ns']<=case['ended_unix_ns'],'STRICT_TIME_ORDER')
    initial={n[len(key)+1:]:h for n,h in execution['exports_sha256'].items() if n.startswith(key+'/')}
    need(initial and before['exports_sha256']==execution['exports_sha256'] and
         before['preexisting_generated'][key]==[] and not any(n in GENERATED or n.startswith('reset-crossings/') for n in initial),
         'FRESH_STRICT_EXPORT_REQUIRED')
    need(execution['ended_unix']*1e9<=before['captured_unix_ns']<=case['started_unix_ns'],'STRICT_BEFORE_TIME_ORDER')
    for name,digest in initial.items():bind(inputs,local(export,name),digest)
    command=case['command'];library=Path(before['library']).resolve()
    expected=[execution['command'][0],'tools/check_export.py',str(export),'--library',str(library),'--soc','--sleep-clock','--vector-coverage',
              '--probe-timeout','3600','--probe-compile-timeout','3600']
    need(command==expected,'STRICT_COMMAND')
    label=key.replace('/','-');logpath=bind(inputs,strict_dir/(label+'.log'),case['log_sha256'])
    need(read_json(bind(inputs,strict_dir/(label+'-command.json')))==command,'STRICT_COMMAND_RECORD')
    result=read_json(logpath)
    need(result==case['result'] and result['status']=='PASS' and result['sleep_clock_background'] is True and
         result['reset_contract']=='generated-system-reset' and result['coverage']=='packed-equivalent' and
         result['probe_timeout_seconds']==result['probe_compile_timeout_seconds']==3600,'STRICT_RESULT')
    for name,digest in case['executed_inputs_sha256'].items():bind(inputs,local(export,name),digest)
    need((set(GENERATED)|{'contract.json','ports.json','filelist.f'})<=set(case['executed_inputs_sha256']),'STRICT_EXECUTED_INPUTS')
    need(case['coverage']['complete_sweep_campaigns']==4 and case['coverage']['total_mapping_checks']==result['mapping_checks'] and
         case['coverage']['endpoint_count']==result['endpoints'] and result['mapping_checks']>0,'STRICT_MANDATORY_CAMPAIGNS')
    doc=read_json(export/'contract.json');manifest=doc['manifest'];att=read_json(export/'mapping-probe-attestation.json');resolved=read_json(export/'resolved.json')
    need(manifest['top']==top and manifest['schema']=='chisel-async-contract-v3' and
         hashlib.sha256(json.dumps(manifest,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()==doc['semantic_sha256'],'EXPORT_MANIFEST')
    need(doc['semantic_sha256']==result['semantic_sha256']==att['semantic_sha256']==resolved['semantic_sha256'] and
         att['status']==resolved['status']=='PASS' and att['mapping_checks']==resolved['mapping_checks']==result['mapping_checks'],'STRICT_SEMANTIC_BINDING')
    need(set(result['sram_instances'])=={top+'.fabric_program_macros_0',top+'.fabric_program_macros_1',top+'.fabric_ram_macros_0'},'THREE_SRAMS')
    files=[local(export,n.strip()) for n in (export/'filelist.f').read_text().splitlines() if n.strip()]
    need(len(files)==len(set(files))==len({p.name for p in files}),'STRICT_FILELIST')
    need({p.name:sha(p) for p in files}==att['source_sha256']==resolved['source_sha256'],'STRICT_SOURCE_ATTESTATION')
    auxiliary={p.relative_to(export).as_posix():sha(p) for p in sorted((export/'verification').rglob('*')) if p.is_file()}
    need(auxiliary==att['validation_auxiliary_sha256'],'STRICT_AUXILIARY')
    for name,digest in auxiliary.items():bind(inputs,export/name,digest)
    for name,keyname in [('contract_probe.sv','probe_sha256'),('contract_probe.vvp','compiled_vvp_sha256'),('contract_simulation.log','simulation_log_sha256')]:bind(inputs,export/name,att[keyname])
    need(sha(export/'mapping-probe-attestation.json')==case['attestation_sha256'],'STRICT_ATTESTATION_HASH')
    compile_cmd=att['compile_command']
    need(compile_cmd[:9]==['iverilog','-s','ContractProbe','-g2012','-DCHISEL_ASYNC_MAPPING','-s',top,'-o','contract_probe.vvp'] and
         compile_cmd[-1]=='contract_probe.sv' and len(compile_cmd[9:-1])==len(files) and
         {Path(p).resolve() for p in compile_cmd[9:-1]}==set(files) and att['simulation_command']==['vvp','contract_probe.vvp'],'STRICT_EXECUTED_PROBE_COMMAND')
    log=(export/'contract_simulation.log').read_text()
    need(re.findall(r'CONTRACT_PROBES_PASS:(\d+)',log)==[str(result['mapping_checks'])] and not re.search(r'FATAL|ERROR|TIMEOUT|DEADLINE',log),'STRICT_PROBE_ACTIVITY')
    report=read_json(export/'reset-crossings/report.json')
    need(report['status']=='pass' and not report['violations'] and report['inputs']['top']==top,'SAVED_FULL_AUDIT')
    need(report['inputs']['sources']==case['rdc_sources_sha256'],'STRICT_GRAPH_SOURCE_BINDING')
    database=graph_inputs(export,report,root,before['tool_inputs_sha256'],inputs)
    capacities=sram_capacities(read_json(bind(inputs,export/'sram.json')),top)
    need(capacities==report['inputs']['sram_capacities'],'ACTUAL_SRAM_CAPACITIES')
    return dict(key=key,export=str(export),top=top,graph=str(export/'reset-crossings/netlist.json'),report=str(export/'reset-crossings/report.json'),
                capacities=capacities,graph_sha256=sha(export/'reset-crossings/netlist.json'),jobs=obligations(database,top))


def bind_plan(regression_path,strict_path,root,checker_successor=None):
    root=root.resolve();regression_path=regression_path.resolve();strict_path=strict_path.resolve();inputs={}
    execution,records,_,coverage=regression.bind_execution(regression_path,root,checker_successor)
    source=regression.source_binding(execution,root,checker_successor)
    export_root=regression_path.parent if checker_successor is None else Path(source['exports_root'])
    for p,h in records.items():bind(inputs,p,h)
    receipt=read_json(bind(inputs,strict_path));strict_dir=strict_path.parent
    need(receipt['status']=='PASS' and set(receipt['cases'])==set(KEYS) and
         receipt['regression_receipt_sha256']==sha(regression_path),'FOUR_FRESH_STRICT_EXPORTS')
    before=read_json(bind(inputs,strict_dir/'strict-before.json',receipt['before_sha256']))
    need(before['regression_receipt_sha256']==sha(regression_path) and before['sources_sha256']==execution['sources_sha256'] and
         before['compiled_class_sha256']==execution['compiled_class_sha256'] and set(before['preexisting_generated'])==set(KEYS),'STRICT_BEFORE_REGRESSION')
    need(before['helpers_sha256']==receipt['helpers_sha256'] and before['tool_inputs_sha256']==receipt['tool_inputs_sha256'],'STRICT_TOOLS_UNCHANGED')
    if checker_successor is not None:
        identity=source['checker_successor']
        for record in (before,receipt):
            need(record['checker_successor']==identity['path'] and record['checker_successor_sha256']==identity['sha256'] and
                 record['current_sources_sha256']==source['current_sources_sha256'],'STRICT_CHECKER_SUCCESSOR')
        need(receipt['exports_root']==str(export_root) and
             receipt['copy_receipt_sha256']==before['copied_exports_receipt_sha256']==source['copied_exports_receipt']['sha256'],
             'STRICT_COPIED_EXPORT_ROOT')
    driver=Path(before['driver']).resolve()
    need(str(driver) in before['helpers_sha256'] and before['helpers_sha256'][str(driver)]==receipt['script_sha256'],'STRICT_DRIVER_BINDING')
    library=Path(before['library']).resolve()
    need((library/'tools/check_export.py').is_file(),'STRICT_LIBRARY_MISSING')
    required=set(helper_closure([root/'tools/check_export.py',root/'tools/check_reset_crossings.py',root/'tools/check_quiescing_graph_controls.py']))
    required|={p.resolve() for p in (library/'tools').rglob('*.py') if '__pycache__' not in p.parts}
    need(required<={Path(p).resolve() for p in before['helpers_sha256']},'COMPLETE_STRICT_HELPERS')
    for p,h in before['helpers_sha256'].items():bind(inputs,p,h)
    for p,h in before['tool_inputs_sha256'].items():bind(inputs,p,h)
    need(all(before['tool_inputs_sha256'].get(p)==h for p,h in execution['tool_inputs_sha256'].items()),'COMPLETE_REGRESSION_RUNTIME')
    for inventory in (source['current_sources_sha256'],execution['compiled_class_sha256']):
        for p,h in inventory.items():bind(inputs,root/p,h)
    exports=[strict_case(key,receipt['cases'][key],before,execution,export_root,strict_dir,root,inputs) for key in KEYS]
    rehash(inputs)
    plan=dict(schema='riscay-quiescing-actual-graph-plan-v1',status='BOUND_FRESH_STRICT_GRAPHS_NOT_EXECUTED',repository=str(root),
                regression=str(regression_path),strict=str(strict_path),required_regression=coverage,inputs_sha256=inputs,
                exports=exports,baselines=4,exact_negatives=304,historical_synthetic_negatives=152,limits=LIMITS)
    if checker_successor is not None:plan['checker_successor']=str(Path(checker_successor).resolve())
    return plan


def validate_plan(plan):
    need(plan['schema']=='riscay-quiescing-actual-graph-plan-v1' and plan['status']=='BOUND_FRESH_STRICT_GRAPHS_NOT_EXECUTED','PLAN_STATUS')
    need(plan==bind_plan(Path(plan['regression']),Path(plan['strict']),Path(plan['repository']),plan.get('checker_successor')),'STALE_OR_EDITED_PLAN')


def run(plan,out):
    validate_plan(plan);out=out.resolve()
    need(all(not out.is_relative_to(Path(e['export'])) and not Path(e['export']).is_relative_to(out) for e in plan['exports']),'OUTPUT_EXPORT_OVERLAP')
    out.mkdir(parents=True,exist_ok=False);write_json(out/'plan.json',plan);records=[];failure=None
    try:
        for entry in plan['exports']:
            rehash(plan['inputs_sha256']);database=read_json(entry['graph']);original=canonical(database)
            label=entry['key'].replace('/','-');folder=out/label;folder.mkdir()
            saved=read_json(entry['report']);record=dict(label=label+'-baseline',status='RUNNING')
            try:record.update(status='PASS',result=baseline(database,entry['top'],entry['capacities'],saved))
            except BaseException as error:record.update(status='FAIL_OR_INCOMPLETE',error=repr(error));raise
            finally:write_json(folder/'baseline.json',record);records.append(record)
            need(obligations(database,entry['top'])==entry['jobs'],'OBLIGATION_CHANGED')
            for job in entry['jobs']:
                record=dict(label=label+'-'+job['label'],status='RUNNING',mutation=job)
                try:
                    record.update(negative(database,entry['top'],entry['capacities'],job))
                    need(canonical(database)==original and sha(entry['graph'])==entry['graph_sha256'],'BASELINE_CHANGED')
                except BaseException as error:record.update(status='FAIL_OR_INCOMPLETE',error=repr(error));raise
                finally:write_json(folder/(job['label']+'.json'),record);records.append(record)
            rehash(plan['inputs_sha256'])
        validate_plan(plan)
        need(len(records)==308 and sum(r['status']=='EXACT_REJECTION' for r in records)==304,'FULL_CAMPAIGN_COUNT')
    except BaseException as error:failure=repr(error)
    write_json(out/'receipt.json',dict(status='PASS_EXACT_ACTUAL_GRAPH_CONTROLS' if failure is None else 'FAIL_OR_INCOMPLETE',
        failure=failure,plan_sha256=sha(out/'plan.json'),records=records,completed_unix=time.time(),limits=LIMITS))
    need(failure is None,'CAMPAIGN_FAILED:'+str(failure))


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    binder=sub.add_parser('bind');binder.add_argument('--regression',type=Path,required=True);binder.add_argument('--strict',type=Path,required=True)
    binder.add_argument('--repository',type=Path,required=True);binder.add_argument('--out',type=Path,required=True)
    binder.add_argument('--checker-successor',type=Path)
    replay=sub.add_parser('run');replay.add_argument('--plan',type=Path,required=True);replay.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.action=='bind':write_json(args.out,bind_plan(args.regression,args.strict,args.repository,args.checker_successor))
    else:run(read_json(args.plan),args.out)


if __name__=='__main__':main()
