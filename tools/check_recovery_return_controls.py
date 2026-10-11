# SPDX-License-Identifier: Apache-2.0
"""Mutate actual native final-return RTL and temporary client receipts."""
import argparse,copy,hashlib,json,re,shutil
from pathlib import Path
from check_admission_controls import replace_pin
from check_i2c_wiring_controls import hashes,run
from check_publication_source_export import validate_publication_source
from check_recovery_return_export import validate_recovery_return,validate_return_receipt_rtl


def metadata_controls(node):
    validate_recovery_return(node);bad=[]
    for field,value in (('module','ClockedReturn'),('capacity',2)):
        x=copy.deepcopy(node);x[field]=value;bad.append(x)
    for field in ('channels','children'):
        x=copy.deepcopy(node);x[field].append({});bad.append(x)
    for field in ('endpoints','primitives','timing'):
        for i in range(len(node[field])):
            x=copy.deepcopy(node);x[field].pop(i);bad.append(x)
            x=copy.deepcopy(node);x[field].append(copy.deepcopy(x[field][i]));bad.append(x)
    for i,e in enumerate(node['endpoints']):
        x=copy.deepcopy(node);x['endpoints'][i]['width']+=1;bad.append(x)
    for i,p in enumerate(node['primitives']):
        for field,value in (('reset','application_reset'),('model','ChiselAsyncPhaseRegister_v1')):
            x=copy.deepcopy(node);x['primitives'][i][field]=value;bad.append(x)
        for field,value in p['parameters'].items():
            x=copy.deepcopy(node);x['primitives'][i]['parameters'][field]=str(int(value)+1);bad.append(x)
    for i,t in enumerate(node['timing']):
        fields=('logic','source','sink','delay_cell') if t['kind']=='bundled-data-path-v1' else ('launch','transaction','data_valid','capture','captured')
        for field in fields:
            x=copy.deepcopy(node);x['timing'][i][field]='wrong';bad.append(x)
        if t['kind']=='bundled-data-path-v1':
            for field in ('min_fs','max_fs','model_fs'):
                x=copy.deepcopy(node);x['timing'][i]['budget'][field]='1';bad.append(x)
        else:
            for field in ('setup_fs','hold_fs'):
                x=copy.deepcopy(node);x['timing'][i][field]='1';bad.append(x)
    for x in bad:
        try:validate_recovery_return(x)
        except ValueError:pass
        else:raise AssertionError('RETURN_METADATA_MUTATION_ACCEPTED')
    return len(bad)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--keep-going',action='store_true')
    args=parser.parse_args();sources=json.loads(args.sources.read_text());out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    results={};commands=[];failures=[]
    def record():
        for name,value in (('results',results),('commands',commands)):
            (out/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    def run_case(label,source,native,mutation=None,helper=False):
        source=Path(source).resolve();before=hashes(source)
        if out.is_relative_to(source):raise ValueError('RETURN_CONTROL_SOURCE_OVERLAP')
        case=out/label;shutil.copytree(source/'export' if native else source,case)
        if native:shutil.copy2(source/'seed-1/testbench.sv',case/'testbench.sv')
        manifest=json.loads((case/'contract.json').read_text())['manifest'];node=manifest['design']
        if native:validate_publication_source(node)
        if helper:node=next(c['contract'] for c in node['children'] if c['id']=='recovery_return')
        rtl=case/(node['module']+'.sv');oracle=hashlib.sha256((case/'testbench.sv').read_bytes()).hexdigest();expected=None
        if mutation:
            changed,expected=mutation(rtl.read_text(),node);rtl.write_text(changed,encoding='utf-8')
        files=[str((case/p.strip()).resolve()) for p in (case/'filelist.f').read_text().splitlines() if p.strip()]
        compiled,log=run(['iverilog','-g2012','-s','Testbench','-o','sim.vvp',*files,'testbench.sv'],case,'compile.log',commands)
        assert compiled['exit_code']==0,log[-4000:]
        simulated,log=run(['vvp','sim.vvp'],case,'simulation.log',commands)
        results[label]=dict(source=str(source),oracle_sha256=oracle,mutated=mutation is not None,expected=expected,
            compile=compiled,simulation=simulated,rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest())
        record()
        if expected:assert simulated['exit_code']!=0 and any(x in log for x in expected) and 'DEADLINE' not in log and 'TIMEOUT' not in log,log[-4000:]
        else:assert simulated['exit_code']==0 and ('CA_TEST_PASS' if native else 'RISCAY_SOC_PASS') in log,log[-4000:]
        assert hashlib.sha256((case/'testbench.sv').read_bytes()).hexdigest()==oracle,'RETURN_CONTROL_ORACLE_CHANGED'
        assert hashes(source)==before,'RETURN_CONTROL_SOURCE_CHANGED'
        results[label]['original_preserved']=True;record();print(label,'PASS',flush=True)
    def simulate(label,*args_,**kwargs):
        try:run_case(label,*args_,**kwargs)
        except (AssertionError,ValueError) as error:
            if not args.keep_going:raise
            failures.append(label);results.setdefault(label,{})['failure']=str(error);record()
            print(label,'FAILED',str(error)[-1000:],flush=True)
    for variant in ('bd','click'):
        s=sources[variant];click=variant=='click'
        node=json.loads((Path(s['none'])/'export/contract.json').read_text())['manifest']['design']
        proof=next(c['contract'] for c in node['children'] if c['id']=='recovery_return')
        results[variant+'-metadata']=dict(rejected=metadata_controls(proof));record()
        def primitive(n,name):return next(p['rtl_path'].rsplit('.',1)[1] for p in n['primitives'] if p['id']==name)
        def pin(t,n,name,port,value):return replace_pin(t,primitive(n,name),port,value)
        for campaign in ('none','receipt','cleanup'):simulate(variant+'-'+campaign+'-baseline',s[campaign],True)
        def admission_bypass(t,n):
            child=next(c['contract'] for c in n['children'] if c['id']=='reservation')
            return replace_pin(t,child['rtl_path'].rsplit('.',1)[1],'in_req','reserve_req'),('FINAL_RETURN_EARLY_ADMISSION',)
        simulate(variant+'-admission-bypass',s['none'],True,admission_bypass)
        simulate(variant+'-clear-without-proof',s['none'],True,
            lambda t,n:(pin(t,n,'clear_na','a',"1'b1"),('FINAL_RETURN_BEFORE_OLD_DRAIN',)),helper=True)
        simulate(variant+'-stale-proof-clear',s['receipt'],True,
            lambda t,n:(pin(t,n,'clear_nb','a',"1'b1"),('FINAL_RETURN_NEW_OWNER_BOUND',)),helper=True)
        def capacity(t,n):
            changed=pin(t,n,'admission_selected_nb','a','originalReturned') if click else pin(t,n,'admission','rising',"{originalReturned,1'b1}")
            return changed,('FINAL_RETURN_EARLY_ADMISSION',)
        simulate(variant+'-capacity-before-proof-return',s['none'],True,capacity,helper=True)
        if click:
            simulate('click-proof-history-from-input',s['none'],True,
                lambda t,n:(pin(t,n,'target_data_delay','a','requested'),('FINAL_RETURN_OFFER_BOUND',)),helper=True)
            simulate('click-final-ack-bypass',s['none'],True,
                lambda t,n:(pin(t,n,'complete_wire_na','a',"1'b1"),('FINAL_RETURN_OFFER_BOUND','FINAL_RETURN_EARLY_ADMISSION')),helper=True)
        else:
            simulate('bd-original-return-bypass',s['none'],True,
                lambda t,n:(replace_pin(t,'ca_child_recovery_return','originalReturned',"1'b1"),('FINAL_RETURN_BEFORE_ORIGINAL_RTZ',)))
            simulate('bd-final-ack-return-bypass',s['none'],True,
                lambda t,n:(pin(t,n,'done','rising','{'+primitive(n,'ack_seen')+".q,finalRequest,1'b0}"),
                    ('FINAL_RETURN_BEFORE_ACK_RTZ',)),helper=True)
        for key in ('client0','client1','client_reset')+(() if click else ('ack_return',)):
            simulate(variant+'-'+key+'-baseline',s[key],False)
        for owner in ('telemetry','housekeeping'):
            simulate(variant+'-'+owner+'-quiet-bypass',s['client0'],False,
                lambda t,n,owner=owner:(replace_pin(t,'ca_child_'+owner+'_final_return','quiet',"1'b1"),('FINAL_CLIENT_OFFER_BOUND',)))
            simulate(variant+'-'+owner+'-request-bypass',s['client0'],False,
                lambda t,n,owner=owner:(replace_pin(t,'ca_child_'+owner+'_final_return','request',"1'b1"),('FINAL_CLIENT_INITIAL_SETTLEMENT','FINAL_CLIENT_OFFER_BOUND')))
        # Close the actual emitted receipt. The negative controls change every
        # sequential writer, combinational output and unauthorized state writer.
        folder=Path(s['client0']);m=json.loads((folder/'contract.json').read_text())['manifest']
        receipt=next(c['contract'] for c in m['design']['children'] if c['id']=='telemetry_final_return')
        original=(folder/(receipt['module']+'.sv')).read_text();validate_return_receipt_rtl(receipt,original)
        mutations=[]
        for name in ('localReset_release_0','localReset_release_1','requestMeta','requestSync','ack'):
            match=re.search(r'\b'+name+r'\s*<=\s*([^;]+);',original);assert match
            mutations.append(original[:match.start(1)]+"1'bx"+original[match.end(1):])
            changed,count=re.subn(r'(\breg\s+'+name+r')\s*;',lambda m:m[1]+" = 1'b1;",original)
            assert count==1;mutations.append(changed)
        mutations.extend([original.replace('assign acknowledge = ack;','assign acknowledge = request;'),
            original.replace('endmodule','initial ack = 1;\nendmodule'),
            original.replace('endmodule','always @(posedge clock) ack <= 1;\nendmodule'),
            original.replace('endmodule','initial force ack = 1;\nendmodule'),
            original.replace('requestMeta <= request;','requestMeta <= quiet;'),
            original.replace('requestSync <= requestMeta;','requestSync <= request;'),
            original.replace('posedge localReset','posedge reset')])
        for i,text in enumerate(mutations):
            assert text!=original
            case=out/(variant+'-receipt-rtl-'+str(i));case.mkdir();(case/'mutated.sv').write_text(text,encoding='utf-8')
            try:validate_return_receipt_rtl(receipt,text)
            except ValueError as error:diagnostic=str(error)
            else:raise AssertionError('RETURN_RECEIPT_RTL_MUTATION_ACCEPTED')
            results[case.name]=dict(actual_rtl=True,diagnostic=diagnostic,original_preserved=True)
        record()
    if failures:raise AssertionError('RETURN_CONTROLS_FAILED:'+','.join(failures))
    results['summary']=dict(positive_replays=sum('simulation' in r and not r['mutated'] for r in results.values()),
        functional_mutations=sum('simulation' in r and r['mutated'] for r in results.values()),
        receipt_rtl_mutations=sum(r.get('actual_rtl',False) for r in results.values()),
        metadata_mutations=sum(r.get('rejected',0) for r in results.values()),originals_preserved=True)
    record();print('ALL_RETURN_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()
