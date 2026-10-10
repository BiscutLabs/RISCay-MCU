# SPDX-License-Identifier: Apache-2.0
"""Check custom Click program-register pins with retained functional oracles.

Standard Click buffers have library timing monitors. These custom reservation,
eligibility, Stored and retirement registers need their own pin checks. This
digital campaign does not qualify physical routing, cell apertures or reset.
"""
import argparse,hashlib,json,re,shutil,subprocess
from pathlib import Path
from check_admission_controls import replace_pin
from check_i2c_wiring_controls import hashes,run
from check_program_source_export import validate_program_source


CAPTURES={'armed_phase':'request_guard','eligibility':'request_guard',
          'stored_phase':'stored_fire','retired_phase':'retire_fire',
          'decision_phase':'retire_fire','publication_phase':'retire_fire'}
CAMPAIGNS=('native','mixed','publication_native','stored_native','fast')


def source_oracles(sources):
    """Fail before simulation when any required positive campaign is absent."""
    selected={k:Path(sources[k]).resolve() for k in CAMPAIGNS}
    result={}
    for name,source in selected.items():
        if not (source/'export/contract.json').is_file():
            raise ValueError('PROGRAM_CAPTURE_MISSING_SOURCE:'+name)
        expected={'seed-'+str(i) for i in range(1,25)}
        if name in ('publication_native','stored_native'):
            expected.update('selected-skew-'+x for x in ('issue','publication','stored'))
        oracles=sorted(source.glob('seed-*/testbench.sv'))+sorted(source.glob('selected-skew-*/testbench.sv'))
        if {p.parent.name for p in oracles}!=expected:
            raise ValueError('PROGRAM_CAPTURE_ORACLE_INVENTORY:'+name)
        result[name]=oracles
    return selected,result


def monitors(node):
    validate_program_source(node)
    if node['module']!='ClickProgramSource':raise ValueError('PROGRAM_CAPTURE_OWNER')
    cells={p['id']:p for p in node['primitives']}
    actual={p['id'] for p in node['primitives'] if p['model']=='ChiselAsyncEventRegister_v1'}
    if actual!=CAPTURES.keys():raise ValueError('PROGRAM_CAPTURE_INVENTORY')
    for child in node['children']:
        timing=[t for t in child['contract']['timing'] if t['kind']=='click-bundling-v1']
        if len(timing)!=1 or any(timing[0]['times'][key]!='100000' for key in
            ('SETUP_FS','HOLD_FS','PULSE_HIGH_FS','PULSE_LOW_FS','CLOCK_SKEW_FS')):
            raise ValueError('PROGRAM_CAPTURE_ENVELOPE')
    output=[]
    for name,fire in CAPTURES.items():
        path='dut.'+cells[name]['rtl_path'].split('.',1)[1]
        origin='dut.'+cells[fire]['rtl_path'].split('.',1)[1]+'.q'
        output.append(f'''
time pc_{name}_rise=0, pc_{name}_fall=0, pc_{name}_data=0, pc_{name}_fire=0;
reg pc_{name}_rose=0, pc_{name}_fell=0, pc_{name}_changed=0;
integer pc_{name}_count=0;
always @(posedge {origin}) pc_{name}_fire=$time;
always @({path}.d or posedge {path}.reset) begin
  if ({path}.reset) pc_{name}_changed=0;
  else if ({path}.reset === 1'b0) begin
    if (pc_{name}_rose && $time-pc_{name}_rise <= 100000)
      $fatal(1,"PROGRAM_CAPTURE_HOLD:{name}");
    pc_{name}_changed=1; pc_{name}_data=$time;
  end
end
always @(posedge {path}.trigger or posedge {path}.reset) begin
  if ({path}.reset) begin pc_{name}_rose=0; pc_{name}_fell=0; end
  else if ({path}.reset === 1'b0) begin
    #0;
    if (pc_{name}_fell && $time-pc_{name}_fall <= 100000)
      $fatal(1,"PROGRAM_CAPTURE_PULSE_LOW:{name}");
    if ({origin} !== 1'b1 || $time-pc_{name}_fire > 100000)
      $fatal(1,"PROGRAM_CAPTURE_SKEW:{name}");
    if (pc_{name}_changed && $time-pc_{name}_data <= 100000)
      $fatal(1,"PROGRAM_CAPTURE_SETUP:{name}");
    pc_{name}_rise=$time; pc_{name}_rose=1;
    pc_{name}_count=pc_{name}_count+1;
  end
end
always @(negedge {path}.trigger) if ({path}.reset === 1'b0 && pc_{name}_rose) begin
  if ($time-pc_{name}_rise <= 100000) $fatal(1,"PROGRAM_CAPTURE_PULSE_HIGH:{name}");
  pc_{name}_fall=$time; pc_{name}_fell=1;
end
''')
    return '\n'.join(output)


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
        if out.is_relative_to(source):raise ValueError('PROGRAM_CAPTURE_OVERLAP_SOURCE')
        case=out/label;shutil.copytree(source/'export',case)
        m=json.loads((case/'contract.json').read_text())['manifest'];node=m['design']
        original=oracle.read_text();assert original.count('endmodule')==1
        marker='$display("CA_TEST_PASS'
        assert original.count(marker)==1
        activity='\n'.join(f'$display("PROGRAM_CAPTURE_ACTIVITY:{n}:%0d",pc_{n}_count);' for n in CAPTURES)
        if source in (selected['mixed'],selected['fast']):
            activity+='\n'+'\n'.join(f'if(pc_{n}_count==0) $fatal(1,"PROGRAM_CAPTURE_INACTIVE:{n}");' for n in CAPTURES)
        test=original.replace(marker,activity+'\n'+marker)
        anchor='timeunit 1fs; timeprecision 1fs;'
        assert test.count(anchor)==1
        test=test.replace(anchor,anchor+'\n'+monitors(node))
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
    # The CPU-only native fixture never issues Stored; use the independently
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
            return replace_pin(text,instance,'d',data),'PROGRAM_CAPTURE_SETUP:'+name
        simulate('bad-setup-'+name,source,oracle,wrong_data)
    def extra_wires(text,declarations,assignments):
        text,count=re.subn(r'(\bmodule\s+ClickProgramSource\b.*?\);)',
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
    simulate('bad-clock-distribution',source,oracle,clock_distribution(100001,'PROGRAM_CAPTURE_SKEW:armed_phase'))
    def short_high(text,node):
        cell=next(p for p in node['primitives'] if p['id']=='armed_phase')
        instance=cell['rtl_path'].rsplit('.',1)[1];trigger=pin_expression(text,instance,'trigger')
        text=replace_pin(text,instance,'trigger','capture_short_clock')
        return (extra_wires(text,'wire capture_late_clock, capture_short_clock;',
            f'assign #100000 capture_late_clock = {trigger};\nassign capture_short_clock = {trigger} & ~capture_late_clock;'),
            'PROGRAM_CAPTURE_PULSE_HIGH:armed_phase')
    simulate('bad-pulse-high',source,oracle,short_high)
    def short_low(text,node):
        cell=next(p for p in node['primitives'] if p['id']=='armed_phase')
        instance=cell['rtl_path'].rsplit('.',1)[1];trigger=pin_expression(text,instance,'trigger')
        text=replace_pin(text,instance,'trigger','capture_short_clock')
        return (extra_wires(text,'wire capture_late_clock, capture_recovery_clock, capture_short_clock;',
            f'assign #1000000 capture_late_clock = {trigger};\n'
            f'assign #1100000 capture_recovery_clock = {trigger};\n'
            f'assign capture_short_clock = {trigger} & (~capture_late_clock | capture_recovery_clock);'),
            'PROGRAM_CAPTURE_PULSE_LOW:armed_phase')
    simulate('bad-pulse-low',source,oracle,short_low)
    def short_hold(text,node):
        cell=next(p for p in node['primitives'] if p['id']=='armed_phase')
        instance=cell['rtl_path'].rsplit('.',1)[1];trigger=pin_expression(text,instance,'trigger')
        data=pin_expression(text,instance,'d')
        text=replace_pin(text,instance,'d',f'({data} ^ {{2{{capture_late_clock}}}})')
        return (extra_wires(text,'wire capture_late_clock;',f'assign #100000 capture_late_clock = {trigger};'),
            'PROGRAM_CAPTURE_HOLD:armed_phase')
    simulate('bad-data-hold',source,oracle,short_hold)
    assert all(hashes(p)==originals[k] for k,p in selected.items()),'PROGRAM_CAPTURE_ORIGINAL_CHANGED'
    results['summary']=dict(baselines=sum(r['expected'] is None for r in results.values()),
        mutations=sum(r['expected'] is not None for r in results.values()),registers=6,originals_preserved=True,
        scope='digital actual-pin setup/hold, high/low pulse and distribution checks; no physical qualification')
    record();print('ALL_PROGRAM_CAPTURE_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()
