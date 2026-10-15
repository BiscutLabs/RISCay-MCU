# SPDX-License-Identifier: Apache-2.0
"""Bind explicit saved-address fixtures to their current sources and exact fatals.

Supply a JSON object with schema ``riscay-sram-saved-cohort-v1`` and twelve
fixtures containing variant, bytes and absolute path. No directory discovery or
recency selection is performed. This prepares a plan; it does not run hardware.
"""
import argparse
import json
from pathlib import Path
import re

import check_saved_address_controls as controls
import saved_address_fixture_contract as contract


def need(ok,why):
    if not ok:raise ValueError('SAVED_ADDRESS_BINDING_'+why)


def source_identity(repository,source_root):
    repository=Path(repository).resolve();source_root=Path(source_root).resolve()
    need(source_root.is_relative_to(repository),'NONLOCAL_SOURCE_ROOT')
    result={}
    for kind,relative in controls.SOURCE_PATHS.items():
        path=source_root/relative
        need(path.is_file(),'MISSING_SOURCE_'+kind)
        result[kind]=dict(path=str(path),sha256=controls.sha(path),
                          annotation=path.relative_to(repository).as_posix())
    controls.validate_source_identity(result)
    return result


def bind_emitted_predicates(source,source_path,capacity):
    """Closed emitted form: full-width input, one exact compare, four real fires."""
    lines=source.splitlines();width=(capacity-1).bit_length()
    code='\n'.join(line.split('//',1)[0] for line in lines)
    need(len(re.findall(r'input\s+\[31:0\]\s+probeAddress\b',code))==1,'FULL_ADDRESS_PORT')
    declarations=list(re.finditer(r'reg\s+\[(\d+):0\]\s+probe_saved_address;[^\n]*',source))
    need(len(declarations)==1 and int(declarations[0][1])+1==width,'SAVED_WIDTH')
    declaration=declarations[0]
    expected=(f'|(probeAddress[31:{width}])' if capacity & (capacity-1)==0
              else f"probeAddress > 32'h{capacity-1:X}")
    definitions=[(i+1,m[1]) for i,line in enumerate(lines)
                 if (m:=re.fullmatch(r'\s*wire\s+(_GEN_\d+)\s*=\s*'+re.escape(expected)+
                                     r';\s*(?://.*)?',line))]
    need(len(definitions)==1,'EXACT_RANGE_DEFINITION')
    definition_line,wire=definitions[0];bindings={};assertions={}
    for lane in range(4):
        condition=f'if (probe_io_request_{lane}_ready & probe_io_request_{lane}_valid & ~reset & {wire}) begin'
        matches=[i+1 for i,line in enumerate(lines) if line.split('//',1)[0].strip()==condition]
        need(len(matches)==1,'EXACT_LANE_FIRE')
        line=matches[0];error=line+2;fatal=line+4
        need(fatal<=len(lines),'ASSERTION_EXTENT')
        need(lines[error-1].split('//',1)[0].strip()==
             f'$error("Assertion failed: SRAM_BYTE_ADDRESS_OUT_OF_RANGE_LANE_{lane}\\n");' and
             lines[fatal-1].split('//',1)[0].strip()=='$fatal;','EXACT_ASSERTION')
        bindings[str(lane)]=dict(wire=wire,definition_line=definition_line,
                                 definition=lines[definition_line-1],condition_line=line,condition=lines[line-1])
        assertions[str(lane)]=dict(file=str(Path(source_path).resolve()),error_line=error,
                                   fatal_line=fatal,scope='Testbench.dut')
    group=dict(bytes=capacity,probe_predicates=bindings)
    for lane in range(4):
        site=assertions[str(lane)]
        controls.validate_probe_predicate(lines,group,lane,site['error_line'],site['fatal_line'])
    return assertions,bindings,declaration[0]


def bind_fixture(record,identity):
    variant=record['variant'];capacity=record['bytes'];root=Path(record['path']).resolve()
    need(root.is_dir(),'MISSING_FIXTURE')
    path=root/'SramSavedAddressFixture.sv';source=path.read_text()
    metadata=contract.validate_metadata(root,capacity,source)
    assertions,bindings,declaration=bind_emitted_predicates(source,path,capacity)
    normalized=lambda text:re.sub(r'[\\/]+','/',text)
    need(identity['fixture']['annotation'] in normalized(source),'FIXTURE_SOURCE_IDENTITY')
    need(identity[variant]['annotation']+':' in normalized(declaration),'BANK_SOURCE_IDENTITY')
    macros=[int(index) for index in re.findall(r'gf180mcu_ocd_ip_sram__sram1024x8m8wm1 probe_macros_(\d+) \(',source)]
    need(macros==list(range((capacity+1023)//1024)),'MACRO_INVENTORY')
    tb=(root/'testbench.sv').read_text()
    contract.validate_testbench(tb,capacity)
    contract.validate_compile_log((root/'compile.log').read_text())
    log=(root/'simulation.log').read_text()
    need(log.count('RISCAY_SOC_PASS')==1 and not re.search(r'ERROR|FATAL|TIMEOUT|DEADLINE',log),'ORIGINAL_POSITIVE')
    inputs=controls.source_inventory(root)
    need(str(path) in inputs,'TOP_NOT_COMPILED')
    # Record the original pass separately; the runner reruns it in the same binary.
    return dict(variant=variant,bytes=capacity,path=str(root),inputs=inputs,metadata=metadata,
                assertions=assertions,probe_predicates=bindings,
                positive_simulation_sha256=controls.sha(root/'simulation.log'),
                compile_log_sha256=controls.sha(root/'compile.log'))


def make_plan(cohort,repository,source_root):
    need(cohort.get('schema')=='riscay-sram-saved-cohort-v1','COHORT_SCHEMA')
    groups=cohort['fixtures'];controls.validate_cohort(groups)
    identity=source_identity(repository,source_root)
    fixtures=[bind_fixture(record,identity) for record in groups]
    controls.validate_source_identity(identity)
    return dict(status='BOUND_TO_FRESH_EMITTED_RTL',schema='riscay-sram-saved-plan-v1',
                source_identity=identity,fixtures=fixtures,
                binder_sha256=controls.sha(Path(__file__)),tool_inputs=controls.tool_inventory(),
                runner_sha256=controls.sha(Path(controls.__file__)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True)
    parser.add_argument('--repository',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source-root',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();cohort=json.loads(args.cohort.read_text())
    plan=make_plan(cohort,args.repository,args.source_root or args.repository)
    plan['cohort_sha256']=controls.sha(args.cohort)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x') as output:output.write(json.dumps(plan,indent=2)+'\n')
    print(json.dumps(dict(status=plan['status'],fixtures=len(plan['fixtures']),sites=48,
                         plan_sha256=controls.sha(args.out))))


if __name__=='__main__':main()
