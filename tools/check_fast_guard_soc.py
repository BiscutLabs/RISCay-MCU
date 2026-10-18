# SPDX-License-Identifier: Apache-2.0
"""Replay an unchanged SoC activity oracle with accelerated selected guard models.

Model values (8 ns publication/ACK, 35 ns elapsed request) are stress settings,
not conversions from physical DLYD counts. Only exact selected guard parameter
sites change; the original fixture and every assertion remain intact.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from gf180_physical import ROOT, nodes, key, sha, write_json
from repair_gf180_control import require


def run(source, policy_path, output, variant):
    require(not output.exists(), 'FAST_GUARD_SOC_OUTPUT_EXISTS')
    policy=json.loads(policy_path.read_text())
    manifest=json.loads((source/'contract.json').read_text())['manifest']
    owners=list(nodes(manifest['design'])); actual={manifest['top']:manifest['top']}
    primitives={p['rtl_path']:(n,p) for n in owners for p in n['primitives']}
    for owner in owners:
        text=(source/(actual[owner['rtl_path']]+'.sv')).read_text()
        for child in owner['children']:
            path=child['contract']['rtl_path']; local=path.split('.')[-1]
            names=re.findall(r'\b(\w+)\s+'+re.escape(local)+r'\s*\(',text)
            require(len(names)==1,'FAST_GUARD_SOC_CHILD_BINDING')
            actual[path]=names[0]
    compiler=Path(shutil.which('iverilog') or ROOT/'.tools/iverilog/bin/iverilog.exe')
    runtime=Path(shutil.which('vvp') or compiler.with_name('vvp.exe'))
    files=[*source.rglob('*.sv'),source/'filelist.f',source/'contract.json',policy_path,Path(__file__),compiler,runtime]
    backend=compiler.parent.parent/'lib/ivl'
    files += [p for p in backend.iterdir() if p.is_file()]
    frozen={str(p.resolve()):sha(p) for p in files}
    output.mkdir(parents=True)
    for path in [*source.rglob('*.sv'),source/'filelist.f',source/'contract.json']:
        dest=output/path.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
    slots={};changed=[]
    for row in policy['variants'][variant]:
        owner,primitive=primitives[row['instance']]
        require(owner['rtl_path']==row['owner'] and re.sub(r'_\d+$','',owner['module'])==row['owner_module'] and
                primitive['id']==row['primitive_id'] and dict(key(primitive)[1])==row['original_parameters'],
                'FAST_GUARD_SOC_POLICY_BINDING')
        delay=35_000_000 if primitive['id']=='request_delay' else 8_000_000
        slot=(actual[owner['rtl_path']],row['instance'].split('.')[-1])
        require(slot not in slots or slots[slot]['delay_fs']==delay,'FAST_GUARD_SOC_DEDUP_CONFLICT')
        slots.setdefault(slot,dict(delay_fs=delay,original_fs=row['original_parameters']['DELAY_FS'],instances=[]))['instances'].append(row['instance'])
    for (module,local),spec in slots.items():
        path=output/(module+'.sv');text=path.read_text()
        pattern=r'(\bChiselAsyncControlGate_v1\s*#\s*\()(.*?)(\)\s*'+re.escape(local)+r'\s*\()'
        matches=list(re.finditer(pattern,text,re.S))
        # Restrict to the immediately preceding primitive parameter block.
        matches=[m for m in matches if ';' not in m[2]]
        if not matches:
            start=text.rfind('ChiselAsyncControlGate_v1',0,text.index(local+' ('))
            tail=text.index(local+' (',start)
            block=text[start:tail]
            require(block.count('ChiselAsyncControlGate_v1')==1 and ';' not in block,'FAST_GUARD_SOC_INSTANCE')
            value,count=re.subn(r'\.DELAY_FS\('+str(spec['original_fs'])+r'\)',f'.DELAY_FS({spec["delay_fs"]})',block)
            require(count==1,'FAST_GUARD_SOC_PARAMETER')
            text=text[:start]+value+text[tail:]
        else:
            require(len(matches)==1,'FAST_GUARD_SOC_INSTANCE')
            match=matches[0]
            value,count=re.subn(r'\.DELAY_FS\('+str(spec['original_fs'])+r'\)',f'.DELAY_FS({spec["delay_fs"]})',match[2])
            require(count==1,'FAST_GUARD_SOC_PARAMETER')
            text=text[:match.start(2)]+value+text[match.end(2):]
        path.write_text(text,newline='\n');changed.append(dict(module=module,primitive=local,**spec))
    require(sha(source/'testbench.sv')==sha(output/'testbench.sv'),'FAST_GUARD_SOC_ORACLE_CHANGED')
    command=[str(compiler),'-g2012','-s','Testbench','-o','stress.vvp','-f','filelist.f',
             *[str(p.relative_to(output)) for p in sorted((output/'chip').rglob('*.sv'))],'testbench.sv']
    result=subprocess.run(command,cwd=output,capture_output=True,text=True,timeout=180)
    (output/'compile.log').write_text(result.stdout+result.stderr)
    require(result.returncode==0,'FAST_GUARD_SOC_COMPILE')
    result=subprocess.run([str(runtime),'stress.vvp'],cwd=output,capture_output=True,text=True,timeout=600)
    log=result.stdout+result.stderr;(output/'simulation.log').write_text(log)
    require(result.returncode==0 and log.count('RISCAY_SOC_PASS')==1 and log.count('ESTIMATE_ACTIVITY_COMPLETE')==1 and
            'FATAL:' not in log,'FAST_GUARD_SOC_ORACLE_FAILED')
    require(all(sha(Path(p))==h for p,h in frozen.items()),'FAST_GUARD_SOC_INPUT_CHANGED')
    write_json(output/'results.json',dict(status='PASS',physical_qualification=False,variant=variant,
        changed=changed,inputs_sha256=frozen,command=command,
        files_sha256={str(p.relative_to(output)):sha(p) for p in output.rglob('*') if p.is_file()}))
    print(json.dumps(dict(status='PASS',variant=variant,primitive_instances=sum(len(x['instances']) for x in changed))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','policy','output'):parser.add_argument(name,type=Path)
    parser.add_argument('--variant',choices=('bd','click'),required=True)
    args=parser.parse_args();run(args.source.resolve(),args.policy.resolve(),args.output.resolve(),args.variant)
