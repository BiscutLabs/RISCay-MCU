# SPDX-License-Identifier: Apache-2.0
"""Mutate actual exported completion wiring while keeping strict probe unchanged."""
import argparse, copy, hashlib, json, re, shutil, sys
from pathlib import Path
from check_i2c_wiring_controls import hashes, run, mutate_pin
from check_completion_export import validate_completion


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bd',type=Path,required=True); parser.add_argument('--click',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True); parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--click-selection',type=Path,help='AsyncCompletionSpec selected-absent fixture with directed skew cases')
    args=parser.parse_args(); repo=Path(__file__).resolve().parents[1]; out=args.out.resolve()
    inputs=[('bd',args.bd.resolve()),('click',args.click.resolve())]
    if any(out.is_relative_to(source) for _,source in inputs): parser.error('output must be separate from input exports')
    out.mkdir(parents=True,exist_ok=False); commands=[]; results={}
    for name,source in inputs:
        before=hashes(source); baseline=out/(name+'-original'); shutil.copytree(source,baseline)
        receipt,log=run([sys.executable,str(repo/'tools/check_export.py'),str(baseline),'--library',str(args.library.resolve())],baseline,'strict.log',commands)
        assert receipt['exit_code']==0,log[-4000:]
        node=json.loads((baseline/'contract.json').read_text())['manifest']['design']; top=node['module']
        primitives={p['id']:p['rtl_path'].split('.')[-1] for p in node['primitives']}
        count=json.loads(log)['mapping_checks']; required='CONTRACT_PROBES_PASS:'+str(count)
        probe_hash=hashlib.sha256((baseline/'contract_probe.sv').read_bytes()).hexdigest()
        results[name]=dict(source=str(source),strict=receipt,mapping_checks=count,cases={},contract_mutations=0)
        # These mutations must be rejected even before RTL mapping begins.
        validate_completion(node)
        bads=[]
        for index in range(len(node['timing'])):
            bad=copy.deepcopy(node); bad['timing'].pop(index); bads.append(bad)
        for index in range(len(node['channels'])):
            bad=copy.deepcopy(node); bad['channels'][index]['protocol']='unrecognized'; bads.append(bad)
        bad=copy.deepcopy(node); bad['primitives'].append(copy.deepcopy(bad['primitives'][0])); bads.append(bad)
        bad=copy.deepcopy(node); bad['primitives'][0]['id']='unknown'; bads.append(bad)
        for id in ('request_guard',)+(('acknowledge_guard','request_delay','output_guard') if name=='click' else ('rendezvous','plan_ack')):
            bad=copy.deepcopy(node); next(p for p in bad['primitives'] if p['id']==id)['parameters']['DELAY_FS']='1'; bads.append(bad)
        if name=='click':
            for endpoint in ('register_data','captured','result_sources'):
                bad=copy.deepcopy(node); next(e for e in bad['endpoints'] if e['id']==endpoint)['width']-=1; bads.append(bad)
        for bad in bads:
            try: validate_completion(bad)
            except ValueError: results[name]['contract_mutations']+=1
            else: raise AssertionError('CONTRACT_MUTATION_ACCEPTED')
        cases=[('baseline',None,None),('request-disconnected','request_guard','a'),
               ('credit-payload-literal','literal',None)]
        if name=='click':
            cases += [('response-and-feedback-mux','data_delay','a'),('selected-phase-load','memory_phase','d'),
                      ('selected-phase-trigger','telemetry_phase','trigger'),('readiness-selection','request_delay','a'),
                      ('output-backpressure','runnable_nb','a'),('join-cascade','housekeeping_available_na','a'),
                      ('acknowledgment-feedback','acknowledge_guard','a'),
                      ('retained-credit-ownership','response_occupied','b')]
        else:
            cases += [('rendezvous-common','rendezvous','common'),('rendezvous-selection','rendezvous','rising'),
                      ('rendezvous-return','rendezvous','falling'),('source-ack-selection','memory_ack_nb','a'),
                      ('source-ack-return','memory_ack_or','a'),('plan-return','plan_ack','falling'),
                      ('retirement-storage-release','reply','out_ack')]
            primitives['reply']=node['children'][0]['contract']['rtl_path'].split('.')[-1]
        for label,primitive,pin in cases:
            case=out/(name+'-'+label); shutil.copytree(baseline,case); rtl=case/(top+'.sv')
            if primitive=='literal':
                changed,count=re.subn(r'(assign creditReturn_bits\s*=\s*)1\'h0;',r"\g<1>1'h1;",rtl.read_text())
                assert count==1,'CREDIT_LITERAL_MUTATION_SHAPE'
                rtl.write_text(changed,encoding='utf-8')
            elif primitive: rtl.write_text(mutate_pin(rtl.read_text(),primitives[primitive],pin),encoding='utf-8')
            assert hashlib.sha256((case/'contract_probe.sv').read_bytes()).hexdigest()==probe_hash
            sources=[str((case/x.strip()).resolve()) for x in (case/'filelist.f').read_text().splitlines() if x.strip()]
            compiled,log=run(['iverilog','-s','ContractProbe','-g2012','-DCHISEL_ASYNC_MAPPING','-s',top,
                              '-o','contract_probe.vvp',*sources,'contract_probe.sv'],case,'compile.log',commands)
            assert compiled['exit_code']==0,log[-4000:]
            simulated,log=run(['vvp','contract_probe.vvp'],case,'simulation.log',commands)
            expected=('ENDPOINT_MAPPING_MISMATCH' if primitive=='literal' else 'DATA_PATH_BINDING_MISMATCH') if primitive else required
            assert expected in log and (simulated['exit_code']!=0)==bool(primitive),log[-4000:]
            results[name]['cases'][label]=dict(compile=compiled,simulation=simulated,expected=expected,probe_sha256=probe_hash)
            print(name,label,'PASS',flush=True)
        assert hashes(source)==before,'ORIGINAL_EXPORT_MODIFIED'
        results[name]['original_preserved']=True
        (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    if args.click_selection:
        source=args.click_selection.resolve()
        if out.is_relative_to(source):raise ValueError('SELECTION_CONTROLS_OVERLAP_SOURCE')
        before=hashes(source)
        node=json.loads((source/'export/contract.json').read_text())['manifest']['design']
        validate_completion(node)
        instance=next(p['rtl_path'].split('.')[-1] for p in node['primitives'] if p['id']=='request_guard')
        for selected in ('memory','telemetry'):
            oracle_source=source/('selected-skew-'+selected)/'testbench.sv'
            oracle=hashlib.sha256(oracle_source.read_bytes()).hexdigest()
            for mutated in (False,True):
                label='selection-'+selected+('-short-guard' if mutated else '-baseline')
                case=out/label;shutil.copytree(source/'export',case)
                shutil.copy2(oracle_source,case/'testbench.sv');rtl=case/'ClickCompletion.sv'
                if mutated:
                    pattern=r'(ChiselAsyncControlGate_v1\s+#\(\s*\.DELAY_FS\()210200001(\),(?:\s*\.\w+\([^)]*\),?)+\s*\)\s+'+re.escape(instance)+r'\s*\()'
                    changed,count=re.subn(pattern,lambda m:m[1]+'11000000'+m[2],rtl.read_text())
                    assert count==1,'SELECTION_GUARD_MUTATION_SHAPE'
                    rtl.write_text(changed,encoding='utf-8')
                files=[str((case/x.strip()).resolve()) for x in (case/'filelist.f').read_text().splitlines() if x.strip()]
                compiled,log=run(['iverilog','-g2012','-s','Testbench','-o','control.vvp',*files,'testbench.sv'],case,'compile.log',commands)
                assert compiled['exit_code']==0,log[-4000:]
                simulated,log=run(['vvp','control.vvp'],case,'simulation.log',commands)
                expected='COMPLETION_SELECTED_SOURCE_ABSENT' if mutated else 'CA_TEST_PASS'
                assert expected in log and (simulated['exit_code']!=0)==mutated,log[-4000:]
                assert hashlib.sha256((case/'testbench.sv').read_bytes()).hexdigest()==oracle
                results['click']['cases'][label]=dict(compile=compiled,simulation=simulated,
                    expected=expected,oracle_sha256=oracle,oracle_kind='native-selected-source-skew')
                print('click',label,'PASS',flush=True)
        assert hashes(source)==before,'ORIGINAL_SELECTION_ORACLE_MODIFIED'
        results['click']['selection_original_preserved']=True
        (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    print('ALL_COMPLETION_WIRING_CONTROLS_PASS',flush=True)

if __name__=='__main__': main()
