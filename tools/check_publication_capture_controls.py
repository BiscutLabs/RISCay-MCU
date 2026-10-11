# SPDX-License-Identifier: Apache-2.0
"""Check custom Click publication-register pins with retained functional oracles.

Standard Click buffers have library timing monitors. These custom reservation,
eligibility, publication, drain and retirement registers need their own pin checks. This
digital campaign does not qualify physical routing, cell apertures or reset.
"""
import argparse,hashlib,json,re,shutil,subprocess
from pathlib import Path
from check_admission_controls import replace_pin
from check_i2c_wiring_controls import hashes,run
from check_publication_source_export import validate_publication_source
from check_capture_pins import capture_monitors


CAPTURES={'armed_phase':'request_guard','eligibility':'request_guard',
          'publication_phase':'publication_fire','retired_phase':'retire_fire',
          'decision_phase':'retire_fire','drain_phase':'drain_fire'}
CAMPAIGNS=('mixed','required','duplicate','capture_reset','fast')


def source_oracles(sources):
    """Fail before simulation when any required positive campaign is absent."""
    selected={k:Path(sources[k]).resolve() for k in CAMPAIGNS}
    result={}
    for name,source in selected.items():
        if not (source/'export/contract.json').is_file():
            raise ValueError('PUBLICATION_CAPTURE_MISSING_SOURCE:'+name)
        expected={'seed-'+str(i) for i in range(1,25)}
        if name in ('mixed','capture_reset','fast'):
            expected.update('selected-skew-'+x for x in ('publication','drain','retirement'))
        oracles=sorted(source.glob('seed-*/testbench.sv'))+sorted(source.glob('selected-skew-*/testbench.sv'))
        if {p.parent.name for p in oracles}!=expected:
            raise ValueError('PUBLICATION_CAPTURE_ORACLE_INVENTORY:'+name)
        result[name]=oracles
    return selected,result


def monitors(node):
    validate_publication_source(node)
    if node['module']!='ClickPublicationSource':raise ValueError('PUBLICATION_CAPTURE_OWNER')
    cells={p['id']:p for p in node['primitives']}
    actual={p['id'] for p in node['primitives'] if p['model']=='ChiselAsyncEventRegister_v1'}
    # The recovery-specific campaign checks the new debt capture in both
    # variants. This retained campaign continues checking all six earlier cells.
    if actual!=set(CAPTURES)|{'debt_storage'}:raise ValueError('PUBLICATION_CAPTURE_INVENTORY')
    for child in node['children']:
        timing=[t for t in child['contract']['timing'] if t['kind']=='click-bundling-v1']
        if len(timing)!=1 or any(timing[0]['times'][key]!='100000' for key in
            ('SETUP_FS','HOLD_FS','PULSE_HIGH_FS','PULSE_LOW_FS','CLOCK_SKEW_FS')):
            raise ValueError('PUBLICATION_CAPTURE_ENVELOPE')
    return capture_monitors(node,CAPTURES,'PUBLICATION_CAPTURE')


def reset_overlap(node):
    cells={p['id']:'dut.'+p['rtl_path'].split('.',1)[1] for p in node['primitives']}
    # These are the standalone top's verified public ports; metadata rtl_path
    # initially names mapping-only probes that are absent from functional runs.
    e={'reset':'dut.reset','application_reset':'dut.applicationReset',
       'publication_request':'dut.publication_req','publication_acknowledge':'dut.publication_ack'}
    declarations=f'''
integer reset_publication_capture=0, reset_drain_capture=0, reset_publication_ack=0;
always @(posedge {cells['publication_phase']}.trigger)
  if(!{e['reset']} && {e['application_reset']}) reset_publication_capture=reset_publication_capture+1;
always @(posedge {cells['drain_phase']}.trigger)
  if(!{e['reset']} && {e['application_reset']}) reset_drain_capture=reset_drain_capture+1;
always @(posedge {e['application_reset']})
  if(!{e['reset']} && {cells['publication_phase']}.q === {e['publication_request']} && {e['publication_request']} !== {e['publication_acknowledge']})
    reset_publication_ack=reset_publication_ack+1;
'''
    checks='''
if(reset_publication_capture==0 || reset_drain_capture==0 || reset_publication_ack==0)
  $fatal(1,"PUBLICATION_RESET_CAPTURE_INACTIVE pub=%0d drain=%0d ack=%0d",
    reset_publication_capture,reset_drain_capture,reset_publication_ack);
$display("PUBLICATION_RESET_CAPTURE_COVERAGE:%0d:%0d:%0d",
  reset_publication_capture,reset_drain_capture,reset_publication_ack);
'''
    return declarations,checks


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();sources=json.loads(args.sources.read_text())['click']
    selected,oracles=source_oracles(sources)
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False);results={};commands=[]
    originals={k:hashes(p) for k,p in selected.items()}
    def record():
        (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    def simulate(label,source,oracle,mutation=None):
        if out.is_relative_to(source):raise ValueError('PUBLICATION_CAPTURE_OVERLAP_SOURCE')
        case=out/label;shutil.copytree(source/'export',case)
        m=json.loads((case/'contract.json').read_text())['manifest'];node=m['design']
        original=oracle.read_text();assert original.count('endmodule')==1
        marker='$display("CA_TEST_PASS'
        assert original.count(marker)==1
        activity='\n'.join(f'$display("PUBLICATION_CAPTURE_ACTIVITY:{n}:%0d",pc_{n}_count);' for n in CAPTURES)
        overlap,overlap_checks=reset_overlap(node) if source==selected['capture_reset'] else ('','')
        activity+='\n'+overlap_checks
        if source in (selected['mixed'],selected['fast']):
            activity+='\n'+'\n'.join(f'if(pc_{n}_count==0) $fatal(1,"PUBLICATION_CAPTURE_INACTIVE:{n}");' for n in CAPTURES)
        test=original.replace(marker,activity+'\n'+marker)
        anchor='timeunit 1fs; timeprecision 1fs;'
        assert test.count(anchor)==1
        test=test.replace(anchor,anchor+'\n'+monitors(node)+'\n'+overlap)
        (case/'testbench.sv').write_text(test)
        rtl=case/(m['top']+'.sv')
        expected=None
        if mutation:
            text,expected=mutation(rtl.read_text(),node);rtl.write_text(text)
        files=[str((case/x.strip()).resolve()) for x in (case/'filelist.f').read_text().splitlines() if x.strip()]
        compiled,log=run(['iverilog','-g2012','-s','Testbench','-o','sim.vvp',*files,'testbench.sv'],case,'compile.log',commands)
        assert compiled['exit_code']==0,log[-3000:]
        simulated,log=run(['vvp','sim.vvp'],case,'simulation.log',commands)
        results[label]=dict(source=str(source),oracle=str(oracle),
            original_oracle_sha256=hashlib.sha256(oracle.read_bytes()).hexdigest(),
            assertions_only_added=True,mutated=mutation is not None,expected=expected,
            compile=compiled,simulation=simulated)
        record()
        if expected:assert simulated['exit_code']!=0 and expected in log and 'DEADLINE' not in log and 'TIMEOUT' not in log,log[-3000:]
        else:assert simulated['exit_code']==0 and 'CA_TEST_PASS' in log,log[-3000:]
        print(label,'PASS',flush=True)
    for name,source in selected.items():
        for oracle in oracles[name]:
            simulate(name+'-'+oracle.parent.name,source,oracle)
    # The required-only fixture does not exercise every cancellation history; use the independently
    # checked mixed history so every mutated register actually captures.
    source=selected['mixed'];oracle=source/'seed-1/testbench.sv'
    def pin_expression(text,instance,pin):
        block=re.search(r'\b'+re.escape(instance)+r'\s*\((.*?)\n\s*\);',text,re.S)
        assert block,instance
        matches=re.findall(r'\.'+pin+r'\s*\(([^()]*)\)',block[1]);assert len(matches)==1,(instance,pin)
        return matches[0].strip()
    for name in CAPTURES:
        def wrong_data(text,node,name=name):
            cell=next(p for p in node['primitives'] if p['id']==name)
            instance=cell['rtl_path'].rsplit('.',1)[1]
            trigger=pin_expression(text,instance,'trigger')
            data='{'+cell['parameters']['WIDTH']+'{'+trigger+'}}'
            return replace_pin(text,instance,'d',data),'PUBLICATION_CAPTURE_SETUP:'+name
        simulate('bad-setup-'+name,source,oracle,wrong_data)
    def extra_wires(text,declarations,assignments):
        text,count=re.subn(r'(\bmodule\s+ClickPublicationSource\b.*?\);)',
            lambda m:m[1]+'\n'+declarations+'\n',text,count=1,flags=re.S)
        assert count==1 and text.count('endmodule')==1
        return '`timescale 1fs/1fs\n'+text.replace('endmodule',assignments+'\nendmodule')
    def clock_distribution(delay,expected):
      def change(text,node):
        cell=next(p for p in node['primitives'] if p['id']=='armed_phase')
        instance=cell['rtl_path'].rsplit('.',1)[1];trigger=pin_expression(text,instance,'trigger')
        text=replace_pin(text,instance,'trigger','capture_late_clock')
        return extra_wires(text,'wire capture_late_clock;',f'assign #{delay} capture_late_clock = {trigger};'),expected
      return change
    simulate('legal-clock-distribution',source,oracle,clock_distribution(100000,None))
    simulate('bad-clock-distribution',source,oracle,clock_distribution(100001,'PUBLICATION_CAPTURE_SKEW:armed_phase'))
    def short_high(text,node):
        cell=next(p for p in node['primitives'] if p['id']=='armed_phase')
        instance=cell['rtl_path'].rsplit('.',1)[1];trigger=pin_expression(text,instance,'trigger')
        text=replace_pin(text,instance,'trigger','capture_short_clock')
        return (extra_wires(text,'wire capture_late_clock, capture_short_clock;',
            f'assign #100000 capture_late_clock = {trigger};\nassign capture_short_clock = {trigger} & ~capture_late_clock;'),
            'PUBLICATION_CAPTURE_PULSE_HIGH:armed_phase')
    simulate('bad-pulse-high',source,oracle,short_high)
    def short_low(text,node):
        cell=next(p for p in node['primitives'] if p['id']=='armed_phase')
        instance=cell['rtl_path'].rsplit('.',1)[1];trigger=pin_expression(text,instance,'trigger')
        text=replace_pin(text,instance,'trigger','capture_short_clock')
        return (extra_wires(text,'wire capture_late_clock, capture_recovery_clock, capture_short_clock;',
            f'assign #1000000 capture_late_clock = {trigger};\n'
            f'assign #1100000 capture_recovery_clock = {trigger};\n'
            f'assign capture_short_clock = {trigger} & (~capture_late_clock | capture_recovery_clock);'),
            'PUBLICATION_CAPTURE_PULSE_LOW:armed_phase')
    simulate('bad-pulse-low',source,oracle,short_low)
    def short_hold(text,node):
        cell=next(p for p in node['primitives'] if p['id']=='armed_phase')
        instance=cell['rtl_path'].rsplit('.',1)[1];trigger=pin_expression(text,instance,'trigger')
        data=pin_expression(text,instance,'d')
        text=replace_pin(text,instance,'d',f'({data} ^ {{3{{capture_late_clock}}}})')
        return (extra_wires(text,'wire capture_late_clock;',f'assign #100000 capture_late_clock = {trigger};'),
            'PUBLICATION_CAPTURE_HOLD:armed_phase')
    simulate('bad-data-hold',source,oracle,short_hold)
    assert all(hashes(p)==originals[k] for k,p in selected.items()),'PUBLICATION_CAPTURE_ORIGINAL_CHANGED'
    results['summary']=dict(baselines=sum(r['expected'] is None for r in results.values()),
        mutations=sum(r['expected'] is not None for r in results.values()),registers=6,originals_preserved=True,
        scope='digital actual-pin setup/hold, high/low pulse and distribution checks; no physical qualification')
    record();print('ALL_PUBLICATION_CAPTURE_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()
