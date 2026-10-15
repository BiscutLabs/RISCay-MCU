# SPDX-License-Identifier: Apache-2.0
"""Reuse each fresh positive compiled fixture for exact full-width bound faults.

The plan's four assertion locations must be bound to the freshly emitted probe
bank (not the idle program/RAM banks). No source or testbench is changed here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

CAPACITIES = (4, 12, 1024, 1028, 2048, 3072)
SOURCE_PATHS = {
    'fixture': 'verification/src/test/scala/riscay/SramSavedAddressSpec.scala',
    'bd': 'designs/four-phase-bd/src/main/scala/riscay/bd/SramBank.scala',
    'click': 'designs/two-phase-click/src/main/scala/riscay/click/SramBank.scala',
}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def need(ok,why):
    if not ok:raise ValueError('SAVED_ADDRESS_CONTROL_'+why)


def validate_cohort(groups):
    need(len(groups)==12,'FIXTURE_COUNT')
    need(all(type(g['bytes']) is int and g['variant'] in ('bd','click') and
             Path(g['path']).is_absolute() for g in groups),'FIXTURE_IDENTITY')
    need({(g['variant'],g['bytes']) for g in groups}==
         {(v,b) for v in ('bd','click') for b in CAPACITIES},'FIXTURE_COHORT')
    paths=[str(Path(g['path']).resolve()) for g in groups]
    need(len(set(paths))==12,'DUPLICATE_FIXTURE_PATH')


def validate_source_identity(identity):
    need(set(identity)==set(SOURCE_PATHS),'SOURCE_IDENTITY_INVENTORY')
    for kind,relative in SOURCE_PATHS.items():
        record=identity[kind];path=Path(record['path']).resolve()
        need(path.is_file() and path.as_posix().endswith('/'+relative),'SOURCE_IDENTITY_PATH')
        annotation=record['annotation']
        need(isinstance(annotation,str) and not Path(annotation).is_absolute() and
             '..' not in Path(annotation).parts and annotation.endswith(relative) and
             path.as_posix().endswith('/'+annotation),
             'SOURCE_IDENTITY_ANNOTATION')
        need(sha(path)==record['sha256'],'SOURCE_IDENTITY_CHANGED')


def case_inventory(capacity):
    need(type(capacity) is int and capacity in CAPACITIES,'CASE_CAPACITY')
    cases=[('positive',None,None,None,None)]
    width=(capacity-1).bit_length()
    for lane in range(4):
        addresses=[capacity+lane,0xffffffff]+[(1<<bit)|lane for bit in range(width,32)]
        cases += [(f'lane-{lane}-address-{address:08x}',lane,address,1,1) for address in dict.fromkeys(addresses)]
        cases += [(f'lane-{lane}-disabled-boundary',lane,capacity+lane,0,1),
                  (f'lane-{lane}-read-boundary',lane,capacity+lane,1,0)]
    return cases


def classify(log,code,site,lane):
    need(code==1,'NOT_FATAL_EXIT')
    need(not re.search(r'DEADLINE|TIMEOUT|RISCAY_SOC_PASS|SAVED_ADDRESS_INVALID_WAS_ACCEPTED',log),'UNRELATED_FAILURE')
    lines=[line for line in log.splitlines() if line.strip()];records=[]
    for i,line in enumerate(lines):
        if not re.search(r'ERROR:|FATAL:',line):continue
        m=re.fullmatch(r'(ERROR|FATAL): (.+):(\d+):\s*(.*)',line)
        need(m is not None and i+1<len(lines),'BAD_RECORD')
        context=re.fullmatch(r'\s+Time: (\d+)\s+Scope: ([\w.]+)\s*',lines[i+1])
        need(context is not None,'BAD_CONTEXT')
        expected_line=site['error_line'] if m[1]=='ERROR' else site['fatal_line']
        need((Path(m[2]).resolve(),int(m[3]),context[2])==
             (Path(site['file']).resolve(),expected_line,site['scope']),'WRONG_ASSERTION_SITE')
        expected=f'Assertion failed: SRAM_BYTE_ADDRESS_OUT_OF_RANGE_LANE_{lane}' if m[1]=='ERROR' else ''
        need(m[4].strip()==expected,'WRONG_ASSERTION_MESSAGE')
        records.append(dict(kind=m[1],file=m[2],line=int(m[3]),message=m[4],time=int(context[1]),scope=context[2]))
    need([x['kind'] for x in records]==['ERROR','FATAL'] and records[0]['time']==records[1]['time'],
         'MISSING_SINGLE_ERROR_FATAL_PAIR')
    return records


def source_inventory(root):
    sources=[(root/p.strip()).resolve() for p in (root/'filelist.f').read_text().splitlines() if p.strip()]
    manifest=json.loads((root/'contract.json').read_text())['manifest']
    def visit(n):
        yield n
        for c in n.get('children',[]):yield from visit(c['contract'])
    sources += [(root/Path(p['resource']).name).resolve() for n in visit(manifest['design']) for p in n.get('primitives',[])]
    sources += [root/'testbench.sv',root/'contract.json',root/'ports.json',root/'filelist.f',root/'sim.vvp',
                root/'ref_SramSavedAddressFixture.sv']
    need(all(p.is_file() and p.is_relative_to(root) for p in sources),'NONLOCAL_OR_MISSING_INPUT')
    return {str(p):sha(p) for p in sorted(set(sources))}


def tool_inventory():
    import saved_address_fixture_contract as contract
    directory=Path(__file__).resolve().parent
    paths=[directory/name for name in ('check_saved_address_controls.py',
        'bind_saved_address_controls.py','saved_address_fixture_contract.py')]
    paths += [contract.ASSETS/name for name in contract.ASSET_NAMES]
    return {str(path.resolve()):sha(path) for path in paths}


def validate_plan(plan):
    # Validate the whole cohort before the first simulator launch, including
    # source attribution, oracle, metadata, original logs and tool identities.
    import bind_saved_address_controls as binder
    need(plan.get('status')=='BOUND_TO_FRESH_EMITTED_RTL','UNBOUND_PLAN')
    need(plan.get('schema')=='riscay-sram-saved-plan-v1','PLAN_SCHEMA')
    need(plan.get('runner_sha256')==sha(Path(__file__)),'RUNNER_CHANGED_SINCE_BINDING')
    need(plan.get('binder_sha256')==sha(Path(binder.__file__)),'BINDER_CHANGED_SINCE_BINDING')
    need(plan.get('tool_inputs')==tool_inventory(),'TOOL_CONTRACT_CHANGED_SINCE_BINDING')
    validate_source_identity(plan['source_identity'])
    validate_cohort(plan['fixtures'])
    for group in plan['fixtures']:
        need(group==binder.bind_fixture(group,plan['source_identity']),'FIXTURE_REBINDING')



def validate_probe_predicate(lines, group, lane, error_line, fatal_line):
    binding=group['probe_predicates'][str(lane)];width=(group['bytes']-1).bit_length()
    wire=binding['wire'];need(re.fullmatch(r'_GEN_\d+',wire) is not None,'PREDICATE_WIRE')
    expected=(f'|(probeAddress[31:{width}])' if group['bytes'] & (group['bytes']-1)==0
              else f"probeAddress > 32'h{group['bytes']-1:X}")
    clean=lambda line:line.split('//',1)[0].strip()
    definition=f'wire {wire} = {expected};'
    matches=[i+1 for i,line in enumerate(lines) if clean(line)==definition]
    need(matches==[binding['definition_line']] and
         lines[binding['definition_line']-1]==binding['definition'],'FULL_WIDTH_PREDICATE')
    # No alternative driver or declaration can be hidden behind the bound name.
    code='\n'.join(line.split('//',1)[0] for line in lines)
    need(len(re.findall(r'\b'+re.escape(wire)+r'\s*(?:=|<=)',code))==1,'PREDICATE_DRIVER')
    need(re.search(r'input\s+\[31:0\]\s+probeAddress\b',code) is not None,'PROBE_ADDRESS_WIDTH')
    condition=f'if (probe_io_request_{lane}_ready & probe_io_request_{lane}_valid & ~reset & {wire}) begin'
    condition_line=binding['condition_line']
    need([i+1 for i,line in enumerate(lines) if clean(line)==condition]==[condition_line] and
         lines[condition_line-1]==binding['condition'] and
         error_line==condition_line+2 and fatal_line==condition_line+4 and
         clean(lines[condition_line])=='if (`ASSERT_VERBOSE_COND_)' and
         clean(lines[condition_line+2])=='if (`STOP_COND_)','PROBE_LANE_FIRE')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();plan=json.loads(args.plan.read_text())
    validate_plan(plan)
    groups=plan['fixtures'];validate_cohort(groups)
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False);receipts=[]
    for group in groups:
        import bind_saved_address_controls as binder
        need(plan['tool_inputs']==tool_inventory(),'TOOLS_CHANGED_BEFORE_FIXTURE')
        need(group==binder.bind_fixture(group,plan['source_identity']),'FIXTURE_CHANGED_BEFORE_EXECUTION')
        validate_source_identity(plan['source_identity'])
        root=Path(group['path']).resolve();before=source_inventory(root)
        need(not out.is_relative_to(root) and not root.is_relative_to(out),'OVERLAP')
        need(group['inputs']==before,'STALE_PLAN')
        need(sha(root/'simulation.log')==group['positive_simulation_sha256'] and
             sha(root/'compile.log')==group['compile_log_sha256'],'ORIGINAL_RUN_CHANGED')
        need(set(group['assertions'])==set(map(str,range(4))),'ASSERTION_INVENTORY')
        for lane in range(4):
            site=group['assertions'][str(lane)];source=Path(site['file']).resolve()
            need(str(source) in before and source.suffix=='.sv' and source.name!='testbench.sv','ASSERTION_SOURCE')
            lines=source.read_text().splitlines();error_line=site['error_line'];fatal_line=site['fatal_line']
            need(1<=error_line<fatal_line<=error_line+3 and fatal_line<=len(lines),'ASSERTION_LINES')
            need('$error(' in lines[error_line-1] and f'SRAM_BYTE_ADDRESS_OUT_OF_RANGE_LANE_{lane}' in lines[error_line-1]
                 and '$fatal' in lines[fatal_line-1],'ASSERTION_BINDING')
            # FIRRTL hoists the exact full-width compare. Bind its definition
            # and each target lane's complete ready/valid/POR firing condition.
            validate_probe_predicate(lines, group, lane, error_line, fatal_line)
        folder=out/f"{group['variant']}-{group['bytes']}";folder.mkdir()
        cases=case_inventory(group['bytes'])
        records=[]
        for label,lane,address,enabled,write in cases:
            need(source_inventory(root)==before,'INPUT_CHANGED_BEFORE_EXECUTION')
            command=['vvp','sim.vvp'] + ([] if lane is None else [f'+invalidLane={lane}',f'+invalidAddress={address:08x}',
                f'+invalidEnable={enabled}',f'+invalidWrite={write}'])
            try:
                result=subprocess.run(command,cwd=root,text=True,capture_output=True,timeout=300)
            except subprocess.TimeoutExpired as error:
                def text(value):return value.decode(errors='replace') if isinstance(value,bytes) else (value or '')
                (folder/(label+'.log')).write_text(text(error.stdout)+text(error.stderr)+'\nCONTROL_TIMEOUT\n')
                raise ValueError('SAVED_ADDRESS_CONTROL_TIMEOUT:'+label) from error
            log=result.stdout+result.stderr;(folder/(label+'.log')).write_text(log)
            need(source_inventory(root)==before,'SOURCE_OR_BINARY_CHANGED_DURING_EXECUTION')
            fatal=None
            if lane is None:
                need(result.returncode==0 and log.count('RISCAY_SOC_PASS')==1 and
                     not re.search(r'ERROR|FATAL|TIMEOUT|DEADLINE',log),'POSITIVE')
            else:fatal=classify(log,result.returncode,group['assertions'][str(lane)],lane)
            records.append(dict(label=label,command=command,exit_code=result.returncode,fatal=fatal,
                                log_sha256=sha(folder/(label+'.log'))))
            (folder/'partial.json').write_text(json.dumps(records,indent=2)+'\n')
        receipts.append(dict(variant=group['variant'],bytes=group['bytes'],inputs=before,
                             source_oracle_binary_unchanged=True,records=records))
        (out/'receipt.json').write_text(json.dumps(dict(status='PARTIAL',fixtures=receipts),indent=2)+'\n')
    validate_source_identity(plan['source_identity'])
    need(plan['tool_inputs']==tool_inventory(),'TOOLS_CHANGED_DURING_EXECUTION')
    need(sum(len(g['records'])-1 for g in receipts)==1304,'EXECUTED_CASE_COUNT')
    (out/'receipt.json').write_text(json.dumps(dict(status='PASS',plan_sha256=sha(args.plan),
        runner_sha256=sha(Path(__file__)),binder_sha256=plan['binder_sha256'],
        source_identity=plan['source_identity'],tool_inputs=plan['tool_inputs'],positive_replays=12,negative_replays=1304,
        scope='Exact full-width admission assertions; no physical qualification.',fixtures=receipts),indent=2)+'\n')
    print('ALL_SAVED_ADDRESS_EXACT_BOUND_CONTROLS_PASS')


if __name__=='__main__':main()
