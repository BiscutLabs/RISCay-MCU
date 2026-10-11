# SPDX-License-Identifier: Apache-2.0
"""Strict-probe controls for both sides of final-return admission and quiet."""
import argparse,hashlib,json,re,shutil,subprocess,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from check_admission_controls import replace_pin
from check_i2c_wiring_controls import hashes


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bd',type=Path,required=True)
    parser.add_argument('--click',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=1)
    parser.add_argument('--probe-timeout',type=int,default=7200)
    args=parser.parse_args();out=args.out.resolve()
    if args.jobs<1:parser.error('--jobs must be positive')
    if args.probe_timeout<1:parser.error('--probe-timeout must be positive')
    inputs=[('bd',args.bd.resolve()),('click',args.click.resolve())]
    if any(out.is_relative_to(source) for _,source in inputs):parser.error('output must be separate from input exports')
    out.mkdir(parents=True,exist_ok=False)
    results={};commands=[]
    def run(command,folder,log,case_commands):
        timeout=args.probe_timeout if command[0]=='vvp' else 600
        case_commands.append(dict(cwd=str(folder),argv=list(map(str,command)),log=log,timeout_seconds=timeout))
        started=time.monotonic()
        try:
            result=subprocess.run(command,cwd=folder,text=True,capture_output=True,timeout=timeout)
        except subprocess.TimeoutExpired as error:
            def decoded(value):return value.decode(errors='replace') if isinstance(value,bytes) else value or ''
            (folder/log).write_text(decoded(error.stdout)+decoded(error.stderr)+'\nWALL_TIMEOUT_NOT_A_PASS\n',encoding='utf-8')
            raise
        text=result.stdout+result.stderr;(folder/log).write_text(text,encoding='utf-8')
        return dict(exit_code=result.returncode,seconds=round(time.monotonic()-started,3),log=str(folder/log)),text
    def record():
        for name,value in (('results',results),('commands',commands)):
            (out/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    for variant,source in inputs:
        before=hashes(source);receipt=json.loads((source/'resolved.json').read_text())
        assert receipt['status']=='PASS','RETURN_MAPPING_STRICT_BASELINE_REQUIRED'
        manifest=json.loads((source/'contract.json').read_text())['manifest'];top=manifest['top']
        probe=(source/'contract_probe.sv').read_bytes();probe_hash=hashlib.sha256(probe).hexdigest()
        assert f"CONTRACT_PROBES_PASS:{receipt['mapping_checks']}" in (source/'contract_simulation.log').read_text()
        def one_case(owner,kind):
            case_commands=[]
            label=variant+'-'+owner+'-'+kind;case=out/label;shutil.copytree(source,case)
            rtl=case/(top+'.sv');text=rtl.read_text(encoding='utf-8')
            if kind=='ready':
                pattern=r'(wire\s+fabric_io_'+owner+r'Source_reserve_ready\s*=)(.*?);'
                match=re.search(pattern,text,re.S);assert match,'RETURN_MAPPING_READY_SHAPE'
                text=text[:match.start(2)]+' _ca_child_'+owner+'_reserve_bridge_in_ready'+text[match.end(2):]
            elif kind=='valid':
                text=replace_pin(text,'ca_child_'+owner+'_reserve_bridge','in_valid','fabric_io_'+owner+'Source_reserve_valid')
            elif kind=='quiet':
                text=replace_pin(text,'ca_child_'+owner+'_final_return','quiet','fabric_io_'+owner+'Source_quiet')
            else:
                pattern=r'(assign\s+'+owner+r'ReturnFence\s*=)(.*?);'
                match=re.search(pattern,text,re.S);assert match,'RETURN_MAPPING_FENCE_SHAPE'
                term='| _ca_child_'+owner+'_source_recoveryReturning';assert match[2].count(term)==1
                text=text[:match.start(2)]+match[2].replace(term,'')+text[match.end(2):]
            rtl.write_text(text,encoding='utf-8')
            assert (case/'contract_probe.sv').read_bytes()==probe,'RETURN_MAPPING_ORACLE_CHANGED'
            files=[str((case/p.strip()).resolve()) for p in (case/'filelist.f').read_text().splitlines() if p.strip()]
            compiled,log=run(['iverilog','-g2012','-DCHISEL_ASYNC_MAPPING','-s','ContractProbe','-s',top,
                '-o','control.vvp',*files,'contract_probe.sv'],case,'compile.log',case_commands)
            assert compiled['exit_code']==0,log[-4000:]
            simulated,log=run(['vvp','control.vvp'],case,'simulation.log',case_commands)
            result=dict(strict_semantic_sha256=receipt['semantic_sha256'],probe_sha256=probe_hash,
                compile=compiled,simulation=simulated,mutated_rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest())
            passed=simulated['exit_code']!=0 and 'PUBLICATION_SOURCE_BINDING:' in log and 'TIMEOUT' not in log and 'DEADLINE' not in log
            return label,result,case_commands,passed,log[-4000:]
        failures=[]
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            cases=[pool.submit(one_case,owner,kind) for owner in ('telemetry','housekeeping') for kind in ('ready','valid','quiet','fence')]
            for future in as_completed(cases):
                label,result,case_commands,passed,tail=future.result()
                results[label]=result;commands.extend(case_commands);record()
                if not passed:failures.append((label,tail))
                print(label,'PASS' if passed else 'FAIL',flush=True)
        assert hashes(source)==before,'RETURN_MAPPING_ORIGINAL_CHANGED'
        for label,result in results.items():
            if label.startswith(variant+'-'):result['original_preserved']=True
        record()
        assert not failures,failures
    results['summary']=dict(actual_rtl_mutations=16,originals_preserved=True);record()
    print('ALL_RETURN_MAPPING_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()
