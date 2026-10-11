# SPDX-License-Identifier: Apache-2.0
"""Replay unchanged native admission oracles against isolated actual RTL mutations."""
import argparse, copy, hashlib, json, re, shutil, sys
from pathlib import Path
from check_i2c_wiring_controls import hashes, run
from check_admission_export import validate_admission, admission_probe


def replace_pin(source, instance, pin, value):
    """Replace one complete named-port expression, preserving surrounding RTL.

    Only named-port instances are accepted. Comments and strings are masked at
    their original offsets so their identifiers and delimiters cannot select a
    target or terminate a nested expression.
    """
    masked=list(source); position=0
    while position<len(source):
        start=position
        if source.startswith('//',position):
            end=source.find('\n',position+2)
            position=len(source) if end<0 else end
        elif source.startswith('/*',position):
            end=source.find('*/',position+2)
            if end<0: raise ValueError('ADMISSION_MUTATION_INSTANCE')
            position=end+2
        elif source[position]=='"':
            position+=1
            while position<len(source) and source[position]!='"':
                position+=2 if source[position]=='\\' else 1
            if position>=len(source): raise ValueError('ADMISSION_MUTATION_INSTANCE')
            position+=1
        else:
            position+=1
            continue
        masked[start:position]=['\n' if c=='\n' else ' ' for c in source[start:position]]
    code=''.join(masked)

    def close_group(start):
        stack=[]; closing={')':'(',']':'[','}':'{'}
        for index in range(start,len(code)):
            char=code[index]
            if char in '([{': stack.append(char)
            elif char in closing:
                if not stack or stack.pop()!=closing[char]:
                    raise ValueError('ADMISSION_MUTATION_INSTANCE')
                if not stack: return index
        raise ValueError('ADMISSION_MUTATION_INSTANCE')

    matches=list(re.finditer(r'(?<![\w$])'+re.escape(instance)+r'(?![\w$])\s*\(',code))
    if len(matches)!=1: raise ValueError('ADMISSION_MUTATION_INSTANCE')
    opening=matches[0].end()-1; ending=close_group(opening)
    if not re.match(r'\s*;',code[ending+1:]): raise ValueError('ADMISSION_MUTATION_INSTANCE')
    position=opening+1; targets=[]; names=set()
    while position<ending:
        while position<ending and code[position].isspace(): position+=1
        if position==ending: break
        port=re.match(r'\.([A-Za-z_$][\w$]*)\s*\(',code[position:ending])
        if port is None or port[1] in names: raise ValueError('ADMISSION_MUTATION_PIN')
        names.add(port[1]); start=position+port.end()-1; end=close_group(start)
        if port[1]==pin: targets.append((start+1,end))
        position=end+1
        while position<ending and code[position].isspace(): position+=1
        if position==ending: break
        if code[position]!=',': raise ValueError('ADMISSION_MUTATION_PIN')
        position+=1
        if not code[position:ending].strip(): raise ValueError('ADMISSION_MUTATION_PIN')
    if len(targets)!=1: raise ValueError('ADMISSION_MUTATION_PIN')
    start,end=targets[0]
    return source[:start]+value+source[end:]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bd',type=Path,required=True);parser.add_argument('--click',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--bd-services',type=Path);parser.add_argument('--click-services',type=Path)
    parser.add_argument('--bd-soc',type=Path);parser.add_argument('--click-soc',type=Path)
    parser.add_argument('--library',type=Path,required=True);args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False);commands=[];results={}
    for name,source in [('bd',args.bd.resolve()),('click',args.click.resolve())]:
        if out.is_relative_to(source): raise ValueError('CONTROLS_OVERLAP_SOURCE')
        before=hashes(source);top='ClickAdmission' if name=='click' else 'FourPhaseAdmission'
        node=json.loads((source/'export/contract.json').read_text())['manifest']['design']
        validate_admission(node);metadata=[]
        bad=copy.deepcopy(node);bad['module']='UnrecognizedCreditOwner';metadata.append(bad)
        for channel in range(2):
            for field,value in [('signed',True),('width',2),('lsb',1),('source','unrecognized')]:
                bad=copy.deepcopy(node);bad['channels'][channel]['layout'][0][field]=value;metadata.append(bad)
        bad=copy.deepcopy(node);bad['channels'].append(copy.deepcopy(bad['channels'][0]));metadata.append(bad)
        bad=copy.deepcopy(node);bad['channels'].pop();metadata.append(bad)
        for bad in metadata:
            try:validate_admission(bad)
            except ValueError:pass
            else:raise AssertionError('ADMISSION_METADATA_MUTATION_ACCEPTED')
        results[name+'-metadata']=dict(rejected=len(metadata))
        # The second-credit mutation injects one unauthorized offer into the
        # initially empty slot. The original grant-count oracle must reject it.
        cases=[('baseline',None,None,None),('unearned-second-credit','ca_child_pending','in_req',"1'b1")]
        if name=='bd': cases.append(('response-return-bypass','ca_primitive_return_barrier','rising',"1'b1"))
        cases.append(('grant-consumption-bypass','ca_child_credit','out_ack','grant_req'))
        for label,instance,pin,value in cases:
            case=out/(name+'-'+label);shutil.copytree(source/'export',case)
            strict=label=='grant-consumption-bypass'
            if strict:
                checked,log=run([sys.executable,str(Path(__file__).resolve().with_name('check_export.py')),
                    str(case),'--library',str(args.library.resolve())],case,'strict-baseline.log',commands)
                assert checked['exit_code']==0,log[-4000:]
            else: shutil.copy2(source/'seed-1/testbench.sv',case/'testbench.sv')
            oracle_file='contract_probe.sv' if strict else 'testbench.sv'
            oracle=hashlib.sha256((case/oracle_file).read_bytes()).hexdigest()
            rtl=case/(top+'.sv')
            if instance: rtl.write_text(replace_pin(rtl.read_text(),instance,pin,value),encoding='utf-8')
            sources=[str((case/x.strip()).resolve()) for x in (case/'filelist.f').read_text().splitlines() if x.strip()]
            options=['-DCHISEL_ASYNC_MAPPING','-s',top,'-s','ContractProbe'] if strict else ['-s','Testbench']
            compiled,log=run(['iverilog','-g2012',*options,'-o','sim.vvp',*sources,oracle_file],case,'compile.log',commands)
            assert compiled['exit_code']==0,log[-4000:]
            simulated,log=run(['vvp','sim.vvp'],case,'simulation.log',commands)
            assert (simulated['exit_code']==0)==(instance is None),log[-4000:]
            if instance:
                assert any(tag in log for tag in ('ADMISSION_','PROTOCOL_','HANDSHAKE_ORDER')),log[-4000:]
                assert 'DEADLINE' not in log and 'TIMEOUT' not in log,log[-4000:]
            assert hashlib.sha256((case/oracle_file).read_bytes()).hexdigest()==oracle
            results[name+'-'+label]=dict(compile=compiled,simulation=simulated,oracle_sha256=oracle,
                oracle_kind='strict-mapping' if strict else 'native-behavior',
                rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest())
            print(name,label,'PASS',flush=True)
            (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        assert hashes(source)==before,'ORIGINAL_ADMISSION_EVIDENCE_CHANGED'
    for name,source in [('bd',args.bd_services),('click',args.click_services)]:
        if source is None: continue
        source=source.resolve();before=hashes(source)
        if out.is_relative_to(source): raise ValueError('CONTROLS_OVERLAP_SOURCE')
        top=json.loads((source/'contract.json').read_text())['manifest']['top']
        for changed in (False,True):
            label=name+('-services-bypass' if changed else '-services-baseline')
            case=out/label;shutil.copytree(source,case)
            oracle=hashlib.sha256((case/'testbench.sv').read_bytes()).hexdigest()
            rtl=case/(top+'.sv')
            if changed:
                text=rtl.read_text();m=re.search(r'wire\s+fabric_cpuAvailable\s*=([^;]*);',text)
                assert m and m[1].count('fabric_io_admissionGrant_valid')==1,'SERVICE_ADMISSION_MUTATION_SHAPE'
                text=text[:m.start(1)]+m[1].replace('fabric_io_admissionGrant_valid',"1'b1")+text[m.end(1):]
                rtl.write_text(text,encoding='utf-8')
            sources=[str((case/x.strip()).resolve()) for x in (case/'filelist.f').read_text().splitlines() if x.strip()]
            compiled,log=run(['iverilog','-g2012','-s','Testbench','-o','sim.vvp',*sources,'testbench.sv'],case,'control-compile.log',commands)
            assert compiled['exit_code']==0,log[-4000:]
            simulated,log=run(['vvp','sim.vvp'],case,'control-simulation.log',commands)
            assert (simulated['exit_code']==0)==(not changed),log[-4000:]
            assert ('ADMISSION_IGNORED_GRANT_STALL' if changed else 'RISCAY_SOC_PASS') in log,log[-4000:]
            assert hashlib.sha256((case/'testbench.sv').read_bytes()).hexdigest()==oracle
            results[label]=dict(compile=compiled,simulation=simulated,oracle_kind='integrated-behavior',
                oracle_sha256=oracle,rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest())
            print(label,'PASS',flush=True)
            (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        assert hashes(source)==before,'ORIGINAL_INTEGRATION_EVIDENCE_CHANGED'
    for name,source in [('bd',args.bd_soc),('click',args.click_soc)]:
        if source is None:continue
        manifest=json.loads((source/'contract.json').read_text())['manifest']
        for owner in ('admission','completion'):
            bad=copy.deepcopy(manifest)
            next(c['contract'] for c in bad['design']['children'] if c['id']==owner)['module']='UnrecognizedOwner'
            try:admission_probe('task check; begin',bad,{})
            except ValueError as error:assert str(error)=='ADMISSION_SOC_OWNER',str(error)
            else:raise AssertionError('ADMISSION_OWNER_MUTATION_ACCEPTED')
        results[name+'-production-metadata']=dict(rejected=2)
    (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    print('ALL_ADMISSION_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()
