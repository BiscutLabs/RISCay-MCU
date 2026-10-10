# SPDX-License-Identifier: Apache-2.0
"""Mutate isolated emitted SPI RTL, retaining each original oracle unchanged.

The functional oracle verifies the player's actual register loads and wire
timing. The mapping oracle separately verifies the immutable native constants.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time


def hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


def run(argv, folder, label):
    start=time.monotonic()
    result=subprocess.run(argv,cwd=folder,text=True,capture_output=True,timeout=600)
    output=result.stdout+result.stderr
    (folder/(label+'.log')).write_text(output,encoding='utf-8')
    return dict(argv=argv,exit_code=result.returncode,seconds=round(time.monotonic()-start,3)),output


def nodes(n):
    yield n
    for c in n['children']: yield from nodes(c['contract'])


def replace_once(source,old,new):
    assert source.count(old)==1,('MUTATION_SITE_CHANGED',old,source.count(old))
    return source.replace(old,new)


def main():
    parser=argparse.ArgumentParser()
    for name in ('bd','click','bd-strict','click-strict','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve()
    roots=[getattr(args,key).resolve() for key in ('bd','click','bd_strict','click_strict')]
    if any(out.is_relative_to(root) or root.is_relative_to(out) for root in roots):
        parser.error('--out must not overlap any input directory')
    out.mkdir(parents=True,exist_ok=False)
    results={}
    player_cases=[('baseline',None,None,None),
        ('occupied-load','occupied <= recipe_occupied;',"occupied <= 32'h7fffffff;",'SPI_FRAME_TOO_LONG'),
        ('cs-sequence-load','csLevels <= recipe_csN;',"csLevels <= 32'h20000000;",'SPI_FRAME_LENGTH'),
        ('sclk-sequence-load','clockLevels <= recipe_sclk;',"clockLevels <= 32'h55555554;",'SPI_HALF_PHASE'),
        ('initial-cs-load','cs <= recipe_initialCsN;',"cs <= 1'h1;",'SPI_FRAME_START'),
        ('initial-sclk-load','clockLevel <= recipe_initialSclk;',"clockLevel <= 1'h1;",'SPI_FRAME_START'),
        ('miso-capture','samples <= {miso, samples[31:1]};','samples <= {~miso, samples[31:1]};','SPI_WIRE_RESULT')]
    for name in ('bd','click'):
        wire=getattr(args,name).resolve(); strict=getattr(args,name+'_strict').resolve()
        before={str(p):hashes(p) for p in (wire,strict)}
        entries={};results[name]=entries
        for label,old,new,expected in player_cases:
            folder=out/(name+'-player-'+label);shutil.copytree(wire,folder)
            model=folder/'SpiAdc.sv'
            if old: model.write_text(replace_once(model.read_text(),old,new),encoding='utf-8')
            assert (folder/'testbench.sv').read_bytes()==(wire/'testbench.sv').read_bytes()
            manifest=json.loads((folder/'contract.json').read_text())['manifest']
            sources=[str((folder/p.strip()).resolve()) for p in (folder/'filelist.f').read_text().splitlines() if p.strip()]
            sources += [str(folder/Path(p['resource']).name) for n in nodes(manifest['design']) for p in n['primitives']]
            compile_result,log=run(['iverilog','-g2012','-s','Testbench','-o','mutation.vvp',*dict.fromkeys(sources),'testbench.sv'],folder,'compile-control')
            assert compile_result['exit_code']==0,log[-4000:]
            simulation,log=run(['vvp','mutation.vvp'],folder,'simulation-control')
            assert (simulation['exit_code']==0)==(old is None),log[-4000:]
            assert (expected or 'RISCAY_SOC_PASS') in log,log[-4000:]
            entries['player-'+label]=dict(compile=compile_result,simulation=simulation,expected=expected or 'RISCAY_SOC_PASS',
                oracle_sha256=hashlib.sha256((folder/'testbench.sv').read_bytes()).hexdigest())
            print(name,'player',label,'PASS',flush=True)
        # The completed strict run supplies the positive mapping control. Every
        # mutant retains its exact probe and mutates only one real native output.
        probe=strict/'contract_probe.sv'
        positive=strict/'contract_simulation.log'
        assert positive.exists() and 'CONTRACT_PROBES_PASS:' in positive.read_text(),'MISSING_POSITIVE_STRICT_CONTROL'
        entries['positive-strict']=dict(log=str(positive),sha256=hashlib.sha256(positive.read_bytes()).hexdigest())
        manifest=json.loads((strict/'contract.json').read_text())['manifest']
        native='ClickSpiAdc' if name=='click' else 'FourPhaseSpiAdc'
        for field,width,value in (('initialCsN',1,0),('initialSclk',1,0),('occupied',32,0xffffffff),('csN',32,0x80000000),('sclk',32,0x55555555)):
            folder=out/(name+'-native-'+field);shutil.copytree(strict,folder)
            model=folder/(native+'.sv')
            pattern=rf'(assign\s+program_{field}\s*=\s*){width}\x27h{value:X}(\s*;)'
            source,count=re.subn(pattern,lambda m:m[1]+f"{width}'h{value^1:X}"+m[2],model.read_text(),flags=re.I)
            assert count==1,('NATIVE_MUTATION_SITE_CHANGED',field,count)
            model.write_text(source,encoding='utf-8')
            assert (folder/'contract_probe.sv').read_bytes()==probe.read_bytes()
            sources=[str((folder/p.strip()).resolve()) for p in (folder/'filelist.f').read_text().splitlines() if p.strip()]
            compile_result,log=run(['iverilog','-g2012','-DCHISEL_ASYNC_MAPPING','-s',manifest['top'],'-s','ContractProbe','-o','mutation.vvp',*sources,'contract_probe.sv'],folder,'compile-control')
            assert compile_result['exit_code']==0,log[-4000:]
            simulation,log=run(['vvp','mutation.vvp'],folder,'simulation-control')
            expected='MCU_SPI_PROGRAM_VALUE:'+field
            assert simulation['exit_code']!=0 and expected in log,log[-4000:]
            entries['native-'+field]=dict(compile=compile_result,simulation=simulation,expected=expected,
                oracle_sha256=hashlib.sha256(probe.read_bytes()).hexdigest())
            print(name,'native',field,'PASS',flush=True)
        assert all(hashes(p)==before[str(p)] for p in (wire,strict)),'ORIGINAL_EXPORT_MODIFIED'
        entries['originals_preserved']=True
        (out/'results.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    print('ALL_ACTUAL_SPI_WIRING_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()
