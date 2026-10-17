# SPDX-License-Identifier: Apache-2.0
"""Actual targeted-repair control with an unclipped slow input and no-op fault."""
import argparse
from dataclasses import replace
from pathlib import Path
import subprocess

from gf180_constraints import brace
from gf180_physical import ROOT, SC, sha, write_json
from gf180_slew_policy import report_rows
from physical_tools import tool
from repair_gf180_control import require


def verdict(before,after,netlist,decisions):
    a={r['pin']:r for r in report_rows(before) if r['kind']=='max slew'}
    b={r['pin']:r for r in report_rows(after) if r['kind']=='max slew'}
    require(a['native/D']['value']==b['native/D']['value']==8,'SLEW_CONTROL_INPUT_CLIPPED')
    require('event\ttargeted-repair' in decisions,'SLEW_CONTROL_NOT_TARGETED')
    require(b['parent/Z']['value']<a['parent/Z']['value']/2 and
            SC+'buf_4 parent' in netlist,'SLEW_CONTROL_NO_REPAIR')
    # This is a control for actual optimizer activity, not electrical closure.
    require(b['parent/Z']['value']>2,'SLEW_CONTROL_LOST_RESIDUAL')
    return dict(before_ns=a['parent/Z']['value'],after_ns=b['parent/Z']['value'],
                slow_input_ns=b['native/D']['value'],residual_violation=True)


def run(out,executable=None):
    require(not out.exists(),'SLEW_CONTROLS_OUTPUT_EXISTS');out.mkdir(parents=True)
    runtime=tool('openroad')
    if executable:runtime=replace(runtime,executable=executable)
    helper=ROOT/'physical/gf180/slew-policy.tcl'
    pdk=ROOT/'.tools/physical/pdk'
    inputs=[Path(__file__),ROOT/'tools/gf180_slew_policy.py',helper,
            *[ROOT/'tools'/n for n in ('repair_gf180_control.py','gf180_constraints.py','gf180_physical.py')],
            *runtime.input_files(),
            pdk/(SC+'ss_125C_3v00.lib'),pdk/'gf180mcu_fd_sc_mcu7t5v0.lef',
            ROOT/'.tools/physical/routing/technology.tlef']
    wrapped=runtime.host_path().with_name('.'+runtime.host_path().name+'-wrapped')
    if wrapped.exists():inputs.append(wrapped)
    frozen={str(p.resolve()):sha(p) for p in inputs}
    body='module fixture(input data,clk,enable,resetn, output [127:0] q); wire event,native_launch;\n'
    body+=SC+'latrnq_1 native (.D(data),.E(enable),.RN(resetn),.Q(native_launch));\n'
    body+=SC+'buf_1 parent (.I(native_launch),.Z(event));\n'
    for i in range(128):body+=SC+f'dffrnq_1 sink{i} (.D(event),.CLK(clk),.RN(resetn),.Q(q[{i}]));\n'
    results={}
    for fault in (False,True):
        directory=out/('noop-fault' if fault else 'positive');directory.mkdir()
        v=directory/'fixture.v';v.write_text(body+'endmodule\n',newline='\n')
        selected=directory/'policy.tcl';text=helper.read_text()
        if fault:
            call='rsz::repair_net_cmd $sta_net 0 10 10'
            require(text.count(call)==1,'SLEW_CONTROL_MUTATION_SHAPE')
            text=text.replace(call,'# injected no-op: '+call)
        selected.write_text(text,newline='\n')
        b=lambda p:brace(runtime.path(p))
        lines=[f'set sc {SC}','set pvt_corners {ss_125C_3v00}','define_corners {*}$pvt_corners',
            'read_liberty -corner ss_125C_3v00 '+b(pdk/(SC+'ss_125C_3v00.lib')),
            'read_lef '+b(ROOT/'.tools/physical/routing/technology.tlef'),
            'read_lef '+b(pdk/'gf180mcu_fd_sc_mcu7t5v0.lef'),
            'read_verilog '+b(v),'link_design fixture',
            'initialize_floorplan -die_area {0 0 200 200} -core_area {10 10 190 190} -site GF018hv5v_mcu_sc7',
            'set_wire_rc -resistance 0 -capacitance 0','set_input_transition 2 [all_inputs]',
            'set_input_transition 8 [get_ports data]','set_load 0.002 [all_outputs]',
            'create_clock -name service -period 50 [get_ports clk]',
            'set_dont_touch [get_cells native]','set_dont_use [get_lib_cells */*dff*]',
            'set_dont_use [get_lib_cells */*lat*]','set slew_native_seeds {native/Q}',
            'source '+b(selected),'slew_strict_repair '+b(directory/'strict'),
            'slew_raw_reports '+b(directory/'after'),'write_verilog '+b(directory/'after.v'),
            'puts SLEW_CONTROL_COMPLETE','exit']
        script=directory/'run.tcl';script.write_text('\n'.join(lines)+'\n',newline='\n')
        generated={str(p):sha(p) for p in (v,selected,script)}
        with (directory/'run.log').open('w') as log:
            subprocess.run(runtime.command(['-exit',runtime.path(script)],timeout=90),
                           stdout=log,stderr=subprocess.STDOUT,check=True,timeout=105)
        require('SLEW_CONTROL_COMPLETE' in (directory/'run.log').read_text(),'SLEW_CONTROL_INCOMPLETE')
        require(all(sha(Path(p))==h for p,h in generated.items()),'SLEW_CONTROL_INPUT_CHANGED')
        args=[(directory/n).read_text() for n in ('strict-ss_125C_3v00.rpt',
              'after-ss_125C_3v00.rpt','after.v','strict-decisions.tsv')]
        if fault:
            try:verdict(*args)
            except ValueError as error:
                require(str(error)=='SLEW_CONTROL_NO_REPAIR','SLEW_CONTROL_WRONG_FAILURE')
                results['noop_fault']=str(error)
            else:raise ValueError('SLEW_CONTROL_MUTATION_SURVIVED')
        else:results['positive']=verdict(*args)
    require(all(sha(Path(p))==h for p,h in frozen.items()),'SLEW_CONTROL_SOURCE_CHANGED')
    write_json(out/'result.json',dict(status='controls-pass',physical_qualification=False,
        inputs_sha256=frozen,results=results,
        evidence_sha256={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()}))
    print('SLEW_TARGET_CONTROLS_PASS',results)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('out',type=Path)
    parser.add_argument('--openroad');args=parser.parse_args();run(args.out,args.openroad)
