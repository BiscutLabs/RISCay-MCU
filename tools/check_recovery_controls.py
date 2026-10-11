# SPDX-License-Identifier: Apache-2.0
"""Actual RTL recovery ownership, attribution and return-fence negative controls."""
import argparse,hashlib,json,re,shutil
from pathlib import Path
from check_admission_controls import replace_pin
from check_i2c_wiring_controls import hashes,run
from check_publication_source_export import validate_publication_source


def isolate_child(case, manifest, child):
    """Clone the actual emitted module for one instance, including dedup aliases."""
    parent=case/(manifest['top']+'.sv');text=parent.read_text(encoding='utf-8')
    instance='ca_child_'+child
    matches=list(re.finditer(r'^\s*([A-Za-z_][A-Za-z0-9_$]*)\s+'+re.escape(instance)+r'\s*\(',text,re.M))
    if len(matches)!=1:raise ValueError('RECOVERY_CHILD_INSTANCE:'+child)
    match=matches[0];module=match[1];definitions=[]
    filelist=case/'filelist.f';listed=filelist.read_text(encoding='utf-8').splitlines()
    for filename in listed:
        if not filename.strip():continue
        path=(case/filename.strip()).resolve()
        if not path.is_relative_to(case.resolve()):raise ValueError('RECOVERY_CHILD_EXTERNAL_FILE')
        body=path.read_text(encoding='utf-8')
        declarations=list(re.finditer(r'\bmodule\s+('+re.escape(module)+r')\b',body))
        definitions.extend((path,body,declaration) for declaration in declarations)
    if len(definitions)!=1:raise ValueError('RECOVERY_CHILD_DEFINITION:'+module)
    original,body,declaration=definitions[0]
    if len(re.findall(r'\bmodule\s+[A-Za-z_]',body))!=1 or len(re.findall(r'\bendmodule\b',body))!=1:
        raise ValueError('RECOVERY_CHILD_MODULE_FILE_SHAPE')
    cloned=module+'__recovery_control_'+child
    target=case/(cloned+'.sv')
    if target.exists() or re.search(r'\b'+re.escape(cloned)+r'\b',text+body):
        raise ValueError('RECOVERY_CHILD_CLONE_COLLISION')
    # Keep the original definition and all other instance bindings byte-identical.
    target.write_text(body[:declaration.start(1)]+cloned+body[declaration.end(1):],encoding='utf-8')
    parent.write_text(text[:match.start(1)]+cloned+text[match.end(1):],encoding='utf-8')
    filelist.write_text('\n'.join(listed+[target.name])+'\n',encoding='utf-8')
    return target,dict(instance=instance,emitted_module=module,isolated_module=cloned,
        original_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
        parent_sha256=hashlib.sha256(parent.read_bytes()).hexdigest())


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--keep-going',action='store_true',help='Retain every failure, then fail the complete campaign')
    args=parser.parse_args()
    sources=json.loads(args.sources.read_text());out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    results={};commands=[];failures=[]
    def record():
        (out/'results.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n',encoding='utf-8')
    def run_case(label,source,native,mutation=None,child=None):
        source=Path(source).resolve();before=hashes(source)
        if out.is_relative_to(source):raise ValueError('RECOVERY_CONTROL_SOURCE_OVERLAP')
        case=out/label;shutil.copytree(source/'export' if native else source,case)
        if native:shutil.copy2(source/'seed-1/testbench.sv',case/'testbench.sv')
        manifest=json.loads((case/'contract.json').read_text())['manifest']
        node=manifest['design'] if child is None else next(c['contract'] for c in manifest['design']['children'] if c['id']==child)
        isolation=None
        if child is None:rtl=case/(node['module']+'.sv')
        else:rtl,isolation=isolate_child(case,manifest,child)
        oracle=hashlib.sha256((case/'testbench.sv').read_bytes()).hexdigest()
        expected=None
        if mutation:
            changed,expected=mutation(rtl.read_text(),node);rtl.write_text(changed,encoding='utf-8')
        files=[str((case/p.strip()).resolve()) for p in (case/'filelist.f').read_text().splitlines() if p.strip()]
        compiled,log=run(['iverilog','-g2012','-s','Testbench','-o','sim.vvp',*files,'testbench.sv'],case,'compile.log',commands)
        assert compiled['exit_code']==0,log[-4000:]
        simulated,log=run(['vvp','sim.vvp'],case,'simulation.log',commands)
        results[label]=dict(source=str(source),oracle_sha256=oracle,mutated=mutation is not None,expected=expected,
            compile=compiled,simulation=simulated,rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest(),
            child_isolation=isolation)
        record()
        if expected:assert simulated['exit_code']!=0 and any(d in log for d in expected) and 'DEADLINE' not in log and 'TIMEOUT' not in log,log[-4000:]
        else:assert simulated['exit_code']==0 and ('CA_TEST_PASS' if native else 'RISCAY_SOC_PASS') in log,log[-4000:]
        assert hashlib.sha256((case/'testbench.sv').read_bytes()).hexdigest()==oracle,'RECOVERY_CONTROL_ORACLE_CHANGED'
        assert hashes(source)==before,'RECOVERY_CONTROL_SOURCE_CHANGED'
        results[label]['original_preserved']=True;record();print(label,'PASS',flush=True)
    def simulate(label,*arguments,**keywords):
        try:run_case(label,*arguments,**keywords)
        except (AssertionError,ValueError) as error:
            if not args.keep_going:raise
            failures.append(label);results.setdefault(label,{})['failure']=str(error)
            record();print(label,'FAILED',str(error)[-1000:],flush=True)
    for variant in ('bd','click'):
        s=sources[variant];click=variant=='click'
        node=json.loads((Path(s['roles'])/'export/contract.json').read_text())['manifest']['design'];validate_publication_source(node)
        def primitive(node,name):return next(p['rtl_path'].rsplit('.',1)[1] for p in node['primitives'] if p['id']==name)
        def pin(text,node,name,port,value):return replace_pin(text,primitive(node,name),port,value)
        def selected(text,node,omit):
            if click:
                name={'role':'recovery_selected_na','eligible':'recovery_live_nb','committed':'recovery_live_na'}[omit]
                return pin(text,node,name,'a',"1'b1")
            values=['ownerRecovery',primitive(node,'drain_issue')+'.q',primitive(node,'receipt_seen')+'.q','eligible']
            values[{'role':0,'committed':1,'publication':2,'eligible':3}[omit]]="1'b1"
            return pin(text,node,'recovery_clear','rising','{'+','.join(values)+'}')
        def retirement(text,node,omit):
            if click:
                return pin(text,node,{'publication':'retire_effect_nb','drain':'retire_decision_na'}[omit],'a',"1'b1")
            values=['reserved',primitive(node,'request_guard')+'.q',
                '(!decision_bits | ('+primitive(node,'drain_issue')+'.q & drain_ack))',
                '(!decision_bits | '+primitive(node,'receipt_seen')+'.q | !eligible)',
                '(!publication_req & !publication_ack)','(!grant_req & !grant_ack)']
            values[{'publication':3,'drain':2}[omit]]="1'b1"
            return pin(text,node,'retirement','rising','{'+','.join(values)+'}')
        for key in ('roles','required','capture_reset','fast'):simulate(variant+'-'+key+'-baseline',s[key],True)
        for role in ('role','eligible'):
            simulate(variant+'-clear-'+role+'-bypass',s['roles'],True,
                lambda t,n,role=role:(selected(t,n,role),('RECOVERY_RETIREMENT_DEBT','RECOVERY_CLEARED_BEFORE_DRAIN')))
        def no_publication(text,node):
            changed=retirement(text,node,'publication')
            if not click:changed=selected(changed,node,'publication')
            return changed,('RECOVERY_CLEARED_WITHOUT_PUBLICATION',)
        simulate(variant+'-publication-proof-bypass',s['required'],True,no_publication)
        simulate(variant+'-drain-proof-bypass',s['roles'],True,
            lambda t,n:(retirement(t,n,'drain'),('RECOVERY_CLEARED_BEFORE_DRAIN',)))
        simulate(variant+'-debt-reset-bypass',s['capture_reset'],True,
            lambda t,n:(pin(t,n,'debt_storage','reset','reset'),('RECOVERY_RESET_CAPTURE_STALE_CLEAR',)))
        simulate(variant+'-eligibility-reset-bypass',s['roles'],True,
            lambda t,n:(pin(t,n,'eligibility','reset','reset'),('RECOVERY_RETIREMENT_DEBT','RECOVERY_CLEARED_BEFORE_DRAIN')))
        simulate(variant+'-debt-does-not-clear',s['fast'],True,
            lambda t,n:(pin(t,n,'debt_storage','d',"1'b1"),('RECOVERY_FAST_CLEAR_MISSING',)))
        simulate(variant+'-debt-clear-from-grant',s['roles'],True,
            lambda t,n:(pin(t,n,'debt_storage','trigger','grant_req'),('RECOVERY_CLEARED_BEFORE_DRAIN','RECOVERY_RETIREMENT_DEBT')))
        for case in ('stale0','stale1','grant_reset','return_reset','maintenance'):simulate(variant+'-'+case+'-baseline',s[case],False)
        for owner in ('telemetry','housekeeping'):
            def marker(text,node,owner=owner):
                return replace_pin(text,'ca_child_'+owner+'_command_bridge','in_bits_recovery',"1'b0"),(
                    'RECOVERY_OLD_REPLY_BOUND','TELEMETRY_RECOVERY_ATTRIBUTION','HOUSEKEEPING_RECOVERY_ATTRIBUTION')
            simulate(variant+'-'+owner+'-command-marker',s['stale0'],False,marker)
            simulate(variant+'-'+owner+'-reply-marker',s['stale1'],False,
                lambda t,n,owner=owner:(replace_pin(t,'ca_child_'+owner+'_reply_bridge','in_bits_recovery',"1'b0"),
                    ('RECOVERY_OLD_REPLY_BOUND','TELEMETRY_RECOVERY_ATTRIBUTION','HOUSEKEEPING_RECOVERY_ATTRIBUTION')))
            def fence(text,node,owner=owner):
                # The safe proof must not clear during pre-recovery quiet.
                pattern=r'(wire\s+'+owner+r'ReturnFence_safe\s*=)(.*?);'
                match=re.search(pattern,text,re.S);assert match,'RECOVERY_FENCE_SAFE_SHAPE'
                old='& ~_ca_child_'+owner+'_source_recoveryDebt';assert match[2].count(old)==1
                return text[:match.start(2)]+match[2].replace(old,'')+text[match.end(2):],('RECOVERY_MISSING_FULL_RETURN_FENCE',)
            simulate(variant+'-'+owner+'-early-fence-release',s['return_reset'],False,fence)
            simulate(variant+'-'+owner+'-stale-eligibility',s['stale0'],False,
                lambda t,n:(pin(t,n,'eligibility','reset','reset'),('RECOVERY_STALE_PUBLICATION_RESTORED_APPLICATION',
                    'RECOVERY_STALE_IDENTITY_COUNTS')),child=owner+'_source')
    if failures:raise AssertionError('RECOVERY_CONTROLS_FAILED:'+','.join(failures))
    results['summary']=dict(positive_replays=sum(not r['mutated'] for r in results.values()),
        mutations=sum(r['mutated'] for r in results.values()),originals_preserved=True)
    record();print('ALL_RECOVERY_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()
