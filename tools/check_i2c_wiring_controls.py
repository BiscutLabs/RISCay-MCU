# SPDX-License-Identifier: Apache-2.0
"""Replay real strict probes, then mutate only isolated exported RTL copies."""
from pathlib import Path
import argparse, hashlib, json, re, shutil, subprocess, sys, time


def hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


def run(command, folder, log, commands):
    commands.append(dict(cwd=str(folder), argv=[str(x) for x in command], log=log))
    started=time.monotonic()
    result=subprocess.run(command,cwd=folder,text=True,capture_output=True,timeout=600)
    (folder/log).write_text(result.stdout+result.stderr,encoding='utf-8')
    return dict(exit_code=result.returncode,seconds=round(time.monotonic()-started,3),log=str(folder/log)),result.stdout+result.stderr


def mutate_pin(source,instance,pin):
    block=re.compile(r'(\b'+re.escape(instance)+r'\s*\()(.*?)(\n\s*\);)',re.S)
    matches=list(block.finditer(source))
    if len(matches)!=1:raise AssertionError(('instance count',instance,len(matches)))
    match=matches[0]
    changed,count=re.subn(r'(\.'+re.escape(pin)+r'\s*\()([^)]*)(\))',lambda m:m[1]+"1'b0"+m[3],match[2])
    if count!=1:raise AssertionError(('port count',instance,pin,count))
    return source[:match.start(2)]+changed+source[match.end(2):]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bd',type=Path,required=True);parser.add_argument('--click',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args();args.repo=args.repo.resolve();args.library=args.library.resolve()
    out=args.out.resolve()
    inputs=[('bd',args.bd.resolve()),('click',args.click.resolve())]
    if any(out.is_relative_to(source) for _,source in inputs):
        parser.error('--out must be outside both input export directories')
    out.mkdir(parents=True,exist_ok=False)
    results={};commands=[]
    for name,source in inputs:
        before=hashes(source);baseline=out/(name+'-original');shutil.copytree(source,baseline)
        original=run([sys.executable,str(args.repo/'tools/check_export.py'),str(baseline),'--library',str(args.library)],baseline,'strict.log',commands)
        assert original[0]['exit_code']==0,original[1][-4000:]
        document=json.loads((baseline/'contract.json').read_text());node=document['manifest']['design']
        primitives={p['id']:p['rtl_path'].split('.')[-1] for p in node['primitives']}
        checks=json.loads(original[1])['mapping_checks']
        required='CONTRACT_PROBES_PASS:'+str(checks)
        probe_hash=hashlib.sha256((baseline/'contract_probe.sv').read_bytes()).hexdigest()
        results[name]=dict(source=str(source),source_before_sha256=before,strict=original[0],mapping_checks=checks,cases={})
        print(name,'original strict PASS',checks,flush=True)
        cases=[('baseline',None,None),('request-input-disconnected','request_delay','a'),
               ('capture-trigger-disconnected','observation','trigger')]
        for prefix in (('capture_gate',) if name=='click' else ('frame_publish','snapshot_publish')):
            cases += [(primitive+'-internal-'+pin+'-disconnected',primitive,pin)
                      for primitive,pin in ((prefix+'_or','a'),(prefix+'_or','b'),(prefix,'a'))]
        for label,primitive,pin in cases:
            case=out/(name+'-'+label);shutil.copytree(baseline,case)
            rtl=case/'I2cPublication.sv'
            if primitive:
                rtl.write_text(mutate_pin(rtl.read_text(),primitives[primitive],pin),encoding='utf-8')
            assert hashlib.sha256((case/'contract_probe.sv').read_bytes()).hexdigest()==probe_hash
            sources=[str((case/x.strip()).resolve()) for x in (case/'filelist.f').read_text().splitlines() if x.strip()]
            command=['iverilog','-s','ContractProbe','-g2012','-DCHISEL_ASYNC_MAPPING','-s','I2cPublication','-o','contract_probe.vvp',*sources,'contract_probe.sv']
            compiled,log=run(command,case,'negative-control-compile.log',commands)
            assert compiled['exit_code']==0,log[-4000:]
            simulated,log=run(['vvp','contract_probe.vvp'],case,'negative-control-simulation.log',commands)
            expected='DATA_PATH_BINDING_MISMATCH' if primitive else required
            assert expected in log,log[-4000:]
            assert (simulated['exit_code']!=0)==bool(primitive),log[-4000:]
            results[name]['cases'][label]=dict(compile=compiled,simulation=simulated,expected=expected,probe_sha256=probe_hash,rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest())
            print(name,label,'PASS',expected,flush=True)
        after=hashes(source);assert before==after,'ORIGINAL_EXPORT_MODIFIED'
        results[name]['original_preserved']=True
        (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    print('ALL_ACTUAL_WIRING_CONTROLS_PASS',flush=True)

if __name__=='__main__':main()
