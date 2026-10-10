# SPDX-License-Identifier: Apache-2.0
"""Reject real SoC constant rewires with the original strict probe unchanged."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
from check_completion_integration import completion_constants_probe
from check_i2c_wiring_controls import hashes, run


def rewire(source, instance, pin, expression):
    matches=list(re.finditer(r'\b'+re.escape(instance)+r'\s*\((.*?)\n\s*\);',source,re.S))
    assert len(matches)==1,(instance,len(matches))
    match=matches[0]
    changed,count=re.subn(r'(\.'+pin+r'\s*\()([^)]*)(\))',lambda m:m[1]+expression+m[3],match[1])
    assert count==1,(instance,pin,count)
    return source[:match.start(1)]+changed+source[match.end(1):]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bd',type=Path,required=True);parser.add_argument('--click',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--library',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    inputs=[('bd',args.bd.resolve()),('click',args.click.resolve())]
    if any(out.is_relative_to(source) for _,source in inputs):parser.error('output must be separate from input exports')
    sys.path.insert(0,str(args.library.resolve()/'tools'))
    spec=importlib.util.spec_from_file_location('completion_control_library',args.library.resolve()/'tools/check_export.py')
    lib=importlib.util.module_from_spec(spec);spec.loader.exec_module(lib)
    out.mkdir(parents=True,exist_ok=False);commands=[];results={}
    for name,source in inputs:
        before=hashes(source)
        receipt=json.loads((source/'resolved.json').read_text())
        assert receipt['status']=='PASS','STRICT_BASELINE_REQUIRED'
        manifest=copy.deepcopy(json.loads((source/'contract.json').read_text())['manifest']);top=manifest['top']
        macros=lib.read_probe_abi((source/f'ref_{top}.sv').read_text(),top)
        for node in lib.nodes(manifest['design']):
            for e in node['endpoints']:e['rtl_path']=top+'.'+macros[e['probe']]
        scopes=lib.read_vvp((source/'contract_probe.vvp').read_text())
        probe=(source/'contract_probe.sv').read_bytes();probe_hash=hashlib.sha256(probe).hexdigest()
        assert f"CONTRACT_PROBES_PASS:{receipt['mapping_checks']}" in (source/'contract_simulation.log').read_text()
        assert probe.count(b'COMPLETION_CONSTANT_BINDING:')==3
        original=(source/(top+'.sv')).read_text()
        results[name]=dict(strict_semantic_sha256=receipt['semantic_sha256'],mapping_checks=receipt['mapping_checks'],
                           probe_sha256=probe_hash,cases={})
        # Classification runs on a fresh, unmasked coverage shape, independently
        # of the original strict probe used to simulate actual literal rewires.
        # Match the generator's LF string; preserve the original CRLF probe bytes
        # in every actual simulation copy below.
        unmasked=probe.decode().replace('\r\n','\n')
        for width,one,zero in ((33,'1fffffffe','1ffffffff'),(1,'1','0')):
            unmasked=re.sub(r"(if \(ones_\d+ !== )"+str(width)+"'h"+one+r"( \|\| zeros_\d+ !== )"+
                            str(width)+"'h"+zero+r'(\) \$fatal\(1, "INACTIVE_ENDPOINT:[^"\n]*ca_child_completion_[^"\n]*"\);)',
                            lambda m:m[1]+f"{width}'h{(1<<width)-1:x}"+m[2]+f"{width}'h{(1<<width)-1:x}"+m[3],unmasked)
        completion_constants_probe(unmasked,manifest,scopes,original)
        for token,pin,literal in (('memory','in_bits_error',1),('telemetry','in_bits',0),('housekeeping','in_bits',0)):
            instance='ca_child_completion_'+token+'_bridge'
            for label,expression in (('flipped-literal',f"1'h{literal}"),('dynamic-driver','fabric_io_completionIdle_REG')):
                changed=rewire(original,instance,pin,expression)
                try:completion_constants_probe(unmasked,manifest,scopes,changed)
                except ValueError as error:
                    assert str(error)=='COMPLETION_CONSTANT_LITERAL:'+token,str(error)
                else:raise AssertionError('CONSTANT_CLASSIFICATION_ACCEPTED')
                record=dict(classification='COMPLETION_CONSTANT_LITERAL:'+token)
                if label=='flipped-literal':
                    case=out/(name+'-'+token);shutil.copytree(source,case)
                    (case/(top+'.sv')).write_text(changed,encoding='utf-8')
                    assert hashlib.sha256((case/'contract_probe.sv').read_bytes()).hexdigest()==probe_hash
                    sources=[str((case/x.strip()).resolve()) for x in (case/'filelist.f').read_text().splitlines() if x.strip()]
                    compiled,log=run(['iverilog','-s','ContractProbe','-g2012','-DCHISEL_ASYNC_MAPPING','-s',top,
                        '-o','contract_probe.vvp',*sources,'contract_probe.sv'],case,'compile.log',commands)
                    assert compiled['exit_code']==0,log[-3000:]
                    simulated,log=run(['vvp','contract_probe.vvp'],case,'simulation.log',commands)
                    assert simulated['exit_code']!=0 and 'COMPLETION_CONSTANT_BINDING:'+token in log,log[-3000:]
                    record.update(compile=compiled,simulation=simulated,probe_sha256=probe_hash)
                results[name]['cases'][token+'-'+label]=record
                print(name,token,label,'REJECTED',flush=True)
        assert hashes(source)==before,'ORIGINAL_EXPORT_MODIFIED'
        results[name]['original_preserved']=True
        (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    print('ALL_COMPLETION_BOUNDARY_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()
