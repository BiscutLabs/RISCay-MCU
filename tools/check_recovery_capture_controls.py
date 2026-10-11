# SPDX-License-Identifier: Apache-2.0
"""Actual debt-register capture pins in BD and Click, with unchanged native oracles.

The six pre-existing Click captures retain their publication campaign. This
campaign adds the new debt register in both implementations, including reset
overlap and every original seed/directed-skew fixture. No physical qualification.
"""
import argparse,hashlib,json,re,shutil
from pathlib import Path
from check_admission_controls import replace_pin
from check_capture_pins import capture_monitors
from check_i2c_wiring_controls import hashes,run
from check_publication_source_export import validate_publication_source

CAMPAIGNS=('roles','required','capture_reset','fast')
CAPTURES={'debt_storage':'recovery_clear'}


def source_oracles(sources):
    selected={k:Path(sources[k]).resolve() for k in CAMPAIGNS};oracles={}
    for name,source in selected.items():
        if not (source/'export/contract.json').is_file():raise ValueError('RECOVERY_CAPTURE_MISSING_SOURCE:'+name)
        expected={'seed-'+str(i) for i in range(1,25)}
        if name!='required':expected.update('selected-skew-'+x for x in ('selector','clear','reset'))
        cases=sorted(source.glob('seed-*/testbench.sv'))+sorted(source.glob('selected-skew-*/testbench.sv'))
        if {p.parent.name for p in cases}!=expected:raise ValueError('RECOVERY_CAPTURE_ORACLE_INVENTORY:'+name)
        oracles[name]=cases
    return selected,oracles


def monitors(node):
    click=validate_publication_source(node)
    actual={p['id'] for p in node['primitives'] if p['model']=='ChiselAsyncEventRegister_v1'}
    expected={'eligibility','debt_storage'}
    if click:expected.update(('armed_phase','publication_phase','drain_phase','retired_phase','decision_phase'))
    if actual!=expected:raise ValueError('RECOVERY_CAPTURE_INVENTORY')
    return capture_monitors(node,CAPTURES,'RECOVERY_CAPTURE')


def reset_overlap(node):
    cell=next(p for p in node['primitives'] if p['id']=='debt_storage')
    path='dut.'+cell['rtl_path'].split('.',1)[1]
    declarations=f'''
integer recovery_reset_before=0,recovery_reset_during=0,recovery_reset_after=0;
always @(posedge dut.applicationReset) if(!dut.reset) begin
  if({path}.q === 1'b0) recovery_reset_after=recovery_reset_after+1;
  else if({path}.q === 1'b1) recovery_reset_before=recovery_reset_before+1;
end
always @(posedge {path}.trigger)
  if(!dut.reset && dut.applicationReset) recovery_reset_during=recovery_reset_during+1;
'''
    checks='''
if(recovery_reset_before==0 || recovery_reset_during==0 || recovery_reset_after==0)
  $fatal(1,"RECOVERY_RESET_CAPTURE_INACTIVE before=%0d during=%0d after=%0d",
    recovery_reset_before,recovery_reset_during,recovery_reset_after);
$display("RECOVERY_RESET_CAPTURE_COVERAGE:%0d:%0d:%0d",recovery_reset_before,recovery_reset_during,recovery_reset_after);
'''
    return declarations,checks


def pin_expression(text,instance,pin):
    block=re.search(r'\b'+re.escape(instance)+r'\s*\((.*?)\n\s*\);',text,re.S)
    if not block:raise ValueError('RECOVERY_CAPTURE_INSTANCE:'+instance)
    values=re.findall(r'\.'+pin+r'\s*\(([^()]*)\)',block[1])
    if len(values)!=1:raise ValueError('RECOVERY_CAPTURE_PIN:'+pin)
    return values[0].strip()


def extra_wires(text,module,declarations,assignments):
    text,count=re.subn(r'(\bmodule\s+'+module+r'\b.*?\);)',lambda m:m[1]+'\n'+declarations+'\n',text,count=1,flags=re.S)
    assert count==1 and text.count('endmodule')==1
    return '`timescale 1fs/1fs\n'+text.replace('endmodule',assignments+'\nendmodule')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    sources=json.loads(args.sources.read_text());out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    results={};commands=[];originals={}
    def record():
        (out/'results.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n',encoding='utf-8')
    def simulate(label,source,oracle,overlap=False,mutation=None):
        if out.is_relative_to(source):raise ValueError('RECOVERY_CAPTURE_SOURCE_OVERLAP')
        case=out/label;shutil.copytree(source/'export',case)
        node=json.loads((case/'contract.json').read_text())['manifest']['design']
        original=oracle.read_text();marker='$display("CA_TEST_PASS'
        assert original.count(marker)==1
        declarations,checks=reset_overlap(node) if overlap else ('','')
        activity='''if(pc_debt_storage_count==0) $fatal(1,"RECOVERY_CAPTURE_INACTIVE:debt_storage");
$display("RECOVERY_CAPTURE_ACTIVITY:%0d",pc_debt_storage_count);
'''+checks
        test=original.replace(marker,activity+marker);anchor='timeunit 1fs; timeprecision 1fs;'
        assert test.count(anchor)==1
        test=test.replace(anchor,anchor+'\n'+monitors(node)+'\n'+declarations)
        (case/'testbench.sv').write_text(test,encoding='utf-8')
        rtl=case/(node['module']+'.sv');expected=None
        if mutation:
            changed,expected=mutation(rtl.read_text(),node);rtl.write_text(changed,encoding='utf-8')
        files=[str((case/p.strip()).resolve()) for p in (case/'filelist.f').read_text().splitlines() if p.strip()]
        compiled,log=run(['iverilog','-g2012','-s','Testbench','-o','sim.vvp',*files,'testbench.sv'],case,'compile.log',commands)
        assert compiled['exit_code']==0,log[-3000:]
        simulated,log=run(['vvp','sim.vvp'],case,'simulation.log',commands)
        results[label]=dict(source=str(source),oracle=str(oracle),original_oracle_sha256=hashlib.sha256(oracle.read_bytes()).hexdigest(),
            assertions_only_added=True,mutated=mutation is not None,expected=expected,compile=compiled,simulation=simulated)
        record()
        if expected:assert simulated['exit_code']!=0 and expected in log and 'DEADLINE' not in log and 'TIMEOUT' not in log,log[-3000:]
        else:assert simulated['exit_code']==0 and 'CA_TEST_PASS' in log,log[-3000:]
        print(label,'PASS',flush=True)
    for variant in ('bd','click'):
        selected,oracles=source_oracles(sources[variant])
        for name,source in selected.items():
            originals[str(source)]=hashes(source)
            for oracle in oracles[name]:simulate(variant+'-'+name+'-'+oracle.parent.name,source,oracle,name=='capture_reset')
        source=selected['fast'];oracle=source/'seed-1/testbench.sv'
        def mutate(kind,delay=0,expected=None):
            def change(text,node):
                cell=next(p for p in node['primitives'] if p['id']=='debt_storage')
                instance=cell['rtl_path'].rsplit('.',1)[1];trigger=pin_expression(text,instance,'trigger')
                if kind=='setup':return replace_pin(text,instance,'d',trigger),'RECOVERY_CAPTURE_SETUP:debt_storage'
                if kind=='hold':
                    text=replace_pin(text,instance,'d','recovery_late_clock')
                    wires='wire recovery_late_clock;';assignments=f'assign #100000 recovery_late_clock = {trigger};'
                else:
                    text=replace_pin(text,instance,'trigger','recovery_test_clock')
                    wires='wire recovery_test_clock,recovery_late_clock,recovery_second_clock;'
                    if kind=='skew':assignments=f'assign #{delay} recovery_test_clock = {trigger};'
                    elif kind=='high':assignments=(f'assign #100000 recovery_late_clock = {trigger};\n'
                        f'assign recovery_test_clock = {trigger} & ~recovery_late_clock;')
                    else:assignments=(f'assign #1000000 recovery_late_clock = {trigger};\n'
                        f'assign #1100000 recovery_second_clock = {trigger};\n'
                        f'assign recovery_test_clock = {trigger} & (~recovery_late_clock | recovery_second_clock);')
                return extra_wires(text,node['module'],wires,assignments),expected
            return change
        simulate(variant+'-legal-distribution',source,oracle,mutation=mutate('skew',100000))
        simulate(variant+'-bad-setup',source,oracle,mutation=mutate('setup'))
        for kind,diagnostic in (('hold','HOLD'),('high','PULSE_HIGH'),('low','PULSE_LOW')):
            simulate(variant+'-bad-'+kind,source,oracle,mutation=mutate(kind,expected='RECOVERY_CAPTURE_'+diagnostic+':debt_storage'))
        simulate(variant+'-bad-distribution',source,oracle,mutation=mutate('skew',100001,'RECOVERY_CAPTURE_SKEW:debt_storage'))
    assert all(hashes(Path(path))==value for path,value in originals.items()),'RECOVERY_CAPTURE_ORIGINAL_CHANGED'
    results['summary']=dict(positive_replays=sum(r['expected'] is None for r in results.values()),
        mutations=sum(r['expected'] is not None for r in results.values()),registers_per_variant=1,
        originals_preserved=True,scope='new BD and Click debt storage actual pins; reset overlap; no physical qualification')
    record();print('ALL_RECOVERY_CAPTURE_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()
