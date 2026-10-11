# SPDX-License-Identifier: Apache-2.0
"""Actual native proof capture pins; immutable functional oracles and gate skew."""
import argparse,hashlib,json,re,shutil
from pathlib import Path
from check_capture_pins import capture_monitors
from check_publication_source_export import validate_publication_source
from check_recovery_capture_controls import monitors as debt_monitors,pin_expression,extra_wires
from check_admission_controls import replace_pin
from check_i2c_wiring_controls import hashes,run

CAPTURES={'admitted_phase':'request_guard','target_phase':None,
          'issued_phase':'request_delay','completed_phase':'return_guard'}
CAMPAIGNS=('none','receipt','cleanup')


def source_oracles(sources):
    selected={n:Path(sources[n]).resolve() for n in CAMPAIGNS};result={}
    for n,p in selected.items():
        cases=sorted(p.glob('seed-*/testbench.sv'))
        if not (p/'export/contract.json').is_file() or {c.parent.name for c in cases}!={'seed-'+str(i) for i in range(1,25)}:
            raise ValueError('RETURN_CAPTURE_ORACLE_INVENTORY:'+n)
        result[n]=cases
    return selected,result


def monitors(node):
    click=validate_publication_source(node)
    proof=next(c['contract'] for c in node['children'] if c['id']=='recovery_return')
    actual={p['id'] for p in proof['primitives'] if p['model']=='ChiselAsyncEventRegister_v1'}
    if actual!=(set(CAPTURES) if click else set()):raise ValueError('RETURN_CAPTURE_INVENTORY')
    parent={p['id']:p['rtl_path'] for p in node['primitives']}
    return debt_monitors(node)+(capture_monitors(proof,CAPTURES,'RETURN_CAPTURE',
        {'target_phase':parent['recovery_clear']+'.q'}) if click else '')


def selected_skew(test,node,profile):
    proof=next(c['contract'] for c in node['children'] if c['id']=='recovery_return')
    click=node['module'].startswith('Click')
    prefixes={'selection':('issue_selected','complete_selected','complete_wire','complete_source','admission_selected'),
              'feedback':('admitted_phase','target_phase','issued_phase','completed_phase','issue_pending','complete_pending','admission_pending'),
              'clear':('clear',)} if click else {
              'selection':('issued','ack_seen','done','admission'),
              'feedback':('pending','offer'), 'clear':('clear',)}
    selected=[p for p in proof['primitives'] if any(p['id']==n or p['id'].startswith(n+'_') for n in prefixes[profile])]
    if not selected:raise ValueError('RETURN_CAPTURE_SKEW_INVENTORY')
    paths=[]
    for p in selected:
        path='dut.'+p['rtl_path'].split('.',1)[1]
        old=f'defparam {path}.DELAY_FS=1000000;'
        if test.count(old)!=1:raise ValueError('RETURN_CAPTURE_SKEW_SHAPE:'+p['id'])
        test=test.replace(old,f'defparam {path}.DELAY_FS=10000000;');paths.append(path)
    return test,paths


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    sources=json.loads(args.sources.read_text());out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    results={};commands=[];originals={}
    def record():
        for name,value in (('results',results),('commands',commands)):
            (out/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    def simulate(label,source,oracle,campaign,skew=None,mutation=None):
        if out.is_relative_to(source):raise ValueError('RETURN_CAPTURE_SOURCE_OVERLAP')
        case=out/label;shutil.copytree(source/'export',case)
        node=json.loads((case/'contract.json').read_text())['manifest']['design'];click=validate_publication_source(node)
        proof=next(c['contract'] for c in node['children'] if c['id']=='recovery_return')
        original=oracle.read_text();test=original;paths=[]
        if skew:test,paths=selected_skew(test,node,skew)
        marker='$display("CA_TEST_PASS';anchor='timeunit 1fs; timeprecision 1fs;'
        assert test.count(marker)==test.count(anchor)==1
        names=(list(CAPTURES) if click else [])+(['debt_storage'] if campaign!='receipt' else [])
        activity='\n'.join(f'if(pc_{n}_count==0) $fatal(1,"RETURN_CAPTURE_INACTIVE:{n}");\n'
            f'$display("RETURN_CAPTURE_ACTIVITY:{n}:%0d",pc_{n}_count);' for n in names)
        test=test.replace(marker,activity+'\n'+marker).replace(anchor,anchor+'\n'+monitors(node))
        (case/'testbench.sv').write_text(test,encoding='utf-8')
        expected=None
        if mutation:
            rtl=case/(proof['module']+'.sv');changed,expected=mutation(rtl.read_text(),proof)
            rtl.write_text(changed,encoding='utf-8')
        files=[str((case/p.strip()).resolve()) for p in (case/'filelist.f').read_text().splitlines() if p.strip()]
        compiled,log=run(['iverilog','-g2012','-s','Testbench','-o','sim.vvp',*files,'testbench.sv'],case,'compile.log',commands)
        assert compiled['exit_code']==0,log[-4000:]
        simulated,log=run(['vvp','sim.vvp'],case,'simulation.log',commands)
        results[label]=dict(source=str(source),oracle=str(oracle),original_oracle_sha256=hashlib.sha256(oracle.read_bytes()).hexdigest(),
            assertions_only_added=True,selected_skew=paths,mutated=mutation is not None,expected=expected,compile=compiled,simulation=simulated)
        record()
        if expected:assert simulated['exit_code']!=0 and expected in log and 'DEADLINE' not in log and 'TIMEOUT' not in log,log[-4000:]
        else:assert simulated['exit_code']==0 and 'CA_TEST_PASS' in log,log[-4000:]
        print(label,'PASS',flush=True)
    for variant in ('bd','click'):
        selected,oracles=source_oracles(sources[variant])
        for campaign,source in selected.items():
            originals[str(source)]=hashes(source)
            for oracle in oracles[campaign]:simulate(variant+'-'+campaign+'-'+oracle.parent.name,source,oracle,campaign)
            for skew in ('selection','feedback','clear'):
                simulate(variant+'-'+campaign+'-skew-'+skew,source,source/'seed-1/testbench.sv',campaign,skew=skew)
        if variant!='click':continue
        source=selected['none'];oracle=source/'seed-1/testbench.sv'
        for name in CAPTURES:
            def mutate(kind,delay=0,expected=None,name=name):
                def change(text,node):
                    cell=next(p for p in node['primitives'] if p['id']==name)
                    instance=cell['rtl_path'].rsplit('.',1)[1];trigger=pin_expression(text,instance,'trigger')
                    if kind=='setup':return replace_pin(text,instance,'d',trigger),'RETURN_CAPTURE_SETUP:'+name
                    if kind=='hold':
                        text=replace_pin(text,instance,'d','return_late_clock')
                        wires='wire return_late_clock;';assignments=f'assign #100000 return_late_clock = {trigger};'
                    else:
                        text=replace_pin(text,instance,'trigger','return_test_clock')
                        wires='wire return_test_clock,return_late_clock,return_second_clock;'
                        if kind=='skew':assignments=f'assign #{delay} return_test_clock = {trigger};'
                        elif kind=='high':assignments=(f'assign #100000 return_late_clock = {trigger};\n'
                            f'assign return_test_clock = {trigger} & ~return_late_clock;')
                        else:assignments=(f'assign #1000000 return_late_clock = {trigger};\n'
                            f'assign #1100000 return_second_clock = {trigger};\n'
                            f'assign return_test_clock = {trigger} & (~return_late_clock | return_second_clock);')
                    return extra_wires(text,node['module'],wires,assignments),expected
                return change
            simulate(name+'-legal-distribution',source,oracle,'none',mutation=mutate('skew',100000))
            simulate(name+'-bad-setup',source,oracle,'none',mutation=mutate('setup'))
            for kind,diagnostic in (('hold','HOLD'),('high','PULSE_HIGH'),('low','PULSE_LOW')):
                simulate(name+'-bad-'+kind,source,oracle,'none',mutation=mutate(kind,expected='RETURN_CAPTURE_'+diagnostic+':'+name))
            simulate(name+'-bad-distribution',source,oracle,'none',mutation=mutate('skew',100001,'RETURN_CAPTURE_SKEW:'+name))
    assert all(hashes(Path(p))==h for p,h in originals.items()),'RETURN_CAPTURE_ORIGINAL_CHANGED'
    results['summary']=dict(positive_replays=sum(r['expected'] is None for r in results.values()),
        mutations=sum(r['expected'] is not None for r in results.values()),click_registers=4,
        parent_debt_registers=2,originals_preserved=True,scope='native final return actual pins, stalls/reset and selected gate skew; no physical qualification')
    record();print('ALL_RETURN_CAPTURE_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()
