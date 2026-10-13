# SPDX-License-Identifier: Apache-2.0
"""Compile actual receiver wiring faults against the strict probe's bindings.

This small mapping campaign uses the same validator/injection as check_export;
it supplements, never replaces, the full generic strict mapping campaigns.
Only catalogued retained storage is forced. Reset/clock stay quiescent because
these tests prove aliases, not functional protocol or physical capture timing.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from check_held_receipts import catalog, validate_held_receipts, held_receipt_probe, leaf
from check_frame_store_controls import replace_pin, pin_value
from check_program_return_fatals import classify_fatal


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('export',type=Path);p.add_argument('--library',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    export=args.export.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(args.library/'tools'))
    spec=importlib.util.spec_from_file_location('library_checker',args.library/'tools/check_export.py')
    library=importlib.util.module_from_spec(spec);spec.loader.exec_module(library)
    manifest=json.loads((export/'contract.json').read_text())['manifest'];top=manifest['top']
    scopes=library.read_vvp((export/'contract_probe.vvp').read_text())
    bindings=validate_held_receipts(manifest,export,scopes);items=catalog(manifest)
    pins=[]
    for name,port in scopes[top]['ports'].items():
        pins.append('.'+name+'('+((str(port['width'])+"'d"+('1' if name=='reset' else '0')) if port['direction']=='input' else '')+')')
    sources={x['storage']:x['width'] for x in items}
    body=[f"force {source} = {width}'h0;" for source,width in sources.items()]
    body.append('#1; check;')
    for source,width in sources.items():
        for bit in range(width):
            for value in (1<<bit,((1<<width)-1)^(1<<bit)):
                body.append(f"force {source} = {width}'h{value:x}; #1; check;")
        body.append(f"force {source} = {width}'h0; #1; check;")
    test='`timescale 1ns/1ps\nmodule Testbench;\n'+top+' '+top+'('+','.join(pins)+');\ntask check; begin\nend endtask\ninitial begin\n'+'\n'.join(body)+'\n$display("HELD_BINDINGS_PASS"); $finish;\nend\nendmodule\n'
    test=held_receipt_probe(test,bindings)
    files=[(export/name.strip()).resolve() for name in (export/'filelist.f').read_text().splitlines() if name.strip()]
    inputs={str(f):sha(f) for f in files}
    records=[]
    def execute(label,changed=None,expected=None):
        directory=out/label;directory.mkdir();tb=directory/'testbench.sv';tb.write_text(test)
        actual=[]
        for f in files:
            if changed and f.name==changed[0]:
                target=directory/f.name;target.write_text(changed[1]);actual.append(target)
            else:actual.append(f)
        command=['iverilog','-g2012','-DCHISEL_ASYNC_MAPPING','-s','Testbench','-o','probe.vvp','testbench.sv',*map(str,actual)]
        compile=subprocess.run(command,cwd=directory,capture_output=True,text=True,timeout=300)
        (directory/'compile.log').write_text(compile.stdout+compile.stderr)
        if compile.returncode:raise ValueError('HELD_WIRING_COMPILE:'+label)
        sim=subprocess.run(['vvp','probe.vvp'],cwd=directory,capture_output=True,text=True,timeout=120)
        log=sim.stdout+sim.stderr;(directory/'simulation.log').write_text(log)
        fatal=None
        if expected:
            sites=[dict(source='testbench.sv',line=i,message=expected,scope='Testbench.check')
                   for i,line in enumerate(test.splitlines(),1) if f'$fatal(1,"{expected}");' in line]
            fatal=classify_fatal(dict(exit_code=compile.returncode),dict(exit_code=sim.returncode),log,sites)
        elif sim.returncode or log.count('HELD_BINDINGS_PASS')!=1 or 'FATAL' in log:
            raise ValueError('HELD_WIRING_BASELINE:'+label+':'+log[-500:])
        records.append(dict(label=label,compile_command=command,fatal=fatal,
            hashes={str(f.relative_to(out)):sha(f) for f in directory.iterdir() if f.is_file()}))
        print(label,'PASS',flush=True)
    execute('positive')
    for item in items:
        path=item['node']['rtl_path'];parent,instance=path.rsplit('.',1)
        filename=scopes[parent]['model']+'.sv';text=(export/filename).read_text()
        field=item['fields'][0][0];pin='in_bits'+('_'+leaf(field) if field else '')
        mutant=replace_pin(text,instance,pin,'~('+pin_value(text,instance,pin)+')')
        label=path.removeprefix(top+'.').replace('.','-')
        execute(label,(filename,mutant),'HELD_RECEIPT_BINDING:'+path+'.'+pin)
    result=dict(status='PASS',positive=1,negative=len(items),records=records,inputs=inputs,
        helpers={str(Path(__file__).with_name(n)):sha(Path(__file__).with_name(n)) for n in
                 ('check_held_receipt_wiring_controls.py','check_held_receipts.py','check_service_reply_receipt.py',
                  'check_frame_store_controls.py','check_program_return_fatals.py')})
    (out/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
