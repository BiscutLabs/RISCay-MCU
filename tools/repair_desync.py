# SPDX-License-Identifier: Apache-2.0
"""Electrical preparation of the connected experimental bank network.

Delay apertures remain open. This is not a timing or complete-chip acceptance
gate; final per-corner electrical reports, not repair summaries, are decisive.
"""
import argparse
import json
from pathlib import Path
from gf180_physical import ROOT, SC, SRAM, write_json
from gf180_estimate import library, scalar, groups
from characterize_gf180_liberty import CORNERS
from physical_tools import tool
from primitives import resolve_candidate
from desync_distribution import prepare, validate_trees, failed_drivers
from repair_gf180_design import read_verilog_json, graph_proof, flat
from gf180_slew_policy import write_views, report_rows, classify, compose_reports
from run_receipt import RunReceipt


def run(mapping, out, mutex_libs, mutex_lef, failures=None):
    out.mkdir(parents=True,exist_ok=False)
    pdk=ROOT/'.tools/physical/pdk'; sr=ROOT/'.tools/gf180-sram'; routing=ROOT/'.tools/physical/routing'
    source=json.loads((mapping/'netlist.json').read_text(encoding='utf-8'))
    bindings=json.loads((mapping/'control.json').read_text(encoding='utf-8'))['bindings']
    protected={b['instance']+'/'+c['name']:b['instance'] for b in bindings for c in b['cells']}
    yosys,road=tool('yosys'),tool('openroad')
    libs=[library(pdk/(SC+c+'.lib')) for c in CORNERS]
    all_libs={**libs[0],**dict(groups((sr/(SRAM+'__'+CORNERS[0]+'.lib')).read_text(encoding='utf-8'),'cell')),
              **dict(groups((mutex_libs/('ca_mutex_gf180_candidate__'+CORNERS[0]+'__scenarios.lib')).read_text(encoding='utf-8'),'cell'))}
    inputs=[mapping/'netlist.json',mapping/'netlist.v',mapping/'control.json',mutex_lef,
            *[pdk/(SC+c+'.lib') for c in CORNERS],*[sr/(SRAM+'__'+c+'.lib') for c in CORNERS],
            *[mutex_libs/('ca_mutex_gf180_candidate__'+c+'__scenarios.lib') for c in CORNERS],
            routing/'technology.tlef',pdk/'gf180mcu_fd_sc_mcu7t5v0.lef',sr/(SRAM+'.lef')]
    if failures:inputs += [failures/'repaired.json',failures/'violations.json']
    receipt=RunReceipt(out/'receipt.json',inputs=inputs,tools=[Path(__file__),ROOT/'tools/desync_distribution.py',
        ROOT/'tools/primitives.py',ROOT/'tools/repair_gf180_design.py',ROOT/'tools/gf180_slew_policy.py',
        *yosys.input_files(),*road.input_files()])
    try:
        write_views(pdk,out/'liberty',CORNERS)
        targets=failed_drivers(json.loads((failures/'repaired.json').read_text(encoding='utf-8')),
            json.loads((failures/'violations.json').read_text(encoding='utf-8')),bindings) if failures else []
        prepared,distribution=prepare(source,bindings,all_libs,repair_drivers=targets)
        write_json(out/'distribution.json',distribution);write_json(out/'prepared.json',prepared)
        write_json(out/'distribution-proof.json',graph_proof(source,prepared,'RiscayMcuDigital',protected,libs))
        script=out/'prepare.ys'
        script.write_text(f'read_json "{yosys.path(out/"prepared.json")}"\n'
            f'write_verilog -norename -noattr -noexpr "{yosys.path(out/"prepared.v")}"\n',encoding='utf-8')
        if receipt.command(yosys.command(['-s',yosys.path(script)],timeout=180),cwd=ROOT,log=out/'prepare.log'):
            raise ValueError('DESYNC_DISTRIBUTION_SERIALIZATION')
        tied=read_verilog_json(out/'prepared.v',out/'tied.json','RiscayMcuDigital',yosys,pdk,source,tie_verilog=out/'tied.v')
        write_json(out/'tie-proof.json',graph_proof(source,tied,'RiscayMcuDigital',protected,libs))
        brace=lambda path:'{'+road.path(path)+'}'
        text=['set_thread_count 8','define_corners '+' '.join(CORNERS)]
        for c in CORNERS:
            text += [f'read_liberty -corner {c} '+brace(f) for f in
                (out/'liberty'/(SC+c+'.lib'),sr/(SRAM+'__'+c+'.lib'),
                 mutex_libs/('ca_mutex_gf180_candidate__'+c+'__scenarios.lib'))]
        text += ['read_lef '+brace(f) for f in (routing/'technology.tlef',pdk/'gf180mcu_fd_sc_mcu7t5v0.lef',sr/(SRAM+'.lef'),mutex_lef)]
        text += ['read_verilog '+brace(out/'tied.v'),'link_design RiscayMcuDigital',
                 'initialize_floorplan -die_area {0 0 1940 2530} -core_area {30 30 1910 2500} -site GF018hv5v_mcu_sc7']
        for layer in ('Metal1','Metal2','Metal3','Metal4'):
            text += [f'make_tracks {layer} -x_offset .28 -x_pitch .56 -y_offset .28 -y_pitch .56']
        text += ['set macros {}; foreach inst [[ord::get_db_block] getInsts] {if {[[$inst getMaster] getName] eq {'+SRAM+'}} {lappend macros [$inst getName]}}',
                 'if {[llength $macros] != 3} {error DESYNC_MACRO_INVENTORY}',
                 'foreach name [lsort $macros] x {100 819.35 1540} {place_macro -macro_name $name -location [list $x 1954] -orientation R0 -exact; create_blockage -region [list [expr {$x-24}] 1914 [expr {$x+325.3}] 2493.81]}']
        text += ['set mutexes {}; foreach inst [[ord::get_db_block] getInsts] {if {[[$inst getMaster] getName] eq {ca_mutex_gf180_candidate}} {lappend mutexes [$inst getName]}}',
                 'if {[llength $mutexes] != 1} {error DESYNC_MUTEX_INVENTORY}',
                 'place_macro -macro_name [lindex $mutexes 0] -location {80 1800} -orientation R0 -exact',
                 'create_blockage -region {76 1796 112 1839.28}']
        # Ideal analysis roots expose the data cones for electrical repair;
        # loaded controller transitions are a separate mandatory coverage gate.
        for b in bindings:
            if b['primitive']!='RiscayDesyncQualifiedController':continue
            port='acknowledgeOut' if b['instance'].endswith('/cpu.m') else 'enable'
            r=resolve_candidate(b['primitive'],b.get('parameters'))
            drivers=[b['instance']+'/'+c['name']+'/'+p for c in r['cells'] for p,n in c['pins'].items()
                     if n==port and p in ('Z','ZN')]
            if len(drivers)!=1:raise ValueError('DESYNC_ANALYSIS_ROOT')
            text += [f'create_clock -name {{{b["instance"]}}} -period 1000 [get_pins {{{drivers[0]}}}]']
        text += ['create_clock -name lf -period 83333333.333 [get_ports watchdogClock]',
                 'create_clock -name sda_event -period 2500 [get_ports sda]',
                 'set_clock_transition 2 [all_clocks]']
        text += ['set_dont_touch [get_cells {'+' '.join('{'+p+'}' for p in sorted(protected))+'}]']
        native_outputs=[b['instance']+'/'+c['name']+'/'+p for b in bindings for c in b['cells']
                        for p in c['pins'] if p in ('Z','ZN','G0','G1')]
        text += ['set_dont_touch [get_nets -of_objects [get_pins {'+' '.join('{'+p+'}' for p in native_outputs)+'}]]']
        # These cuts are for electrical preparation only. Residual controller
        # cycles require transition contexts before any delay query is accepted.
        for b in bindings:
            for cell,src,dst in resolve_candidate(b['primitive'],b.get('parameters'))['local_keeper_arcs']:
                text += [f'set_disable_timing -from {src} -to {dst} [get_cells {{{b["instance"]}/{cell}}}]']
        text += ['set_input_transition 2 [all_inputs]','set_load .05 [all_outputs]',
                 'set_dont_use [get_lib_cells */*dff*]','set_dont_use [get_lib_cells */*lat*]',
                 'set_wire_rc -resistance 0 -capacitance 0',
                 'buffer_ports -outputs -buffer_cell '+SC+'buf_8',
                 'place_pins -hor_layers Metal3 -ver_layers Metal2',
                 'global_placement -density .60 -overflow .15','detailed_placement',
                 'repair_design -max_wire_length 0 -slew_margin 10 -cap_margin 10',
                 'detailed_placement','check_placement -verbose']
        text += [f'report_check_types -corner {c} -max_slew -max_capacitance -violators -digits 6 -no_line_splits > '+brace(out/(c+'-electrical.rpt')) for c in CORNERS]
        text += ['set_max_transition 2 [current_design]']
        text += [f'report_check_types -corner {c} -max_slew -max_capacitance -violators -digits 6 -no_line_splits > '+brace(out/(c+'-strict.rpt')) for c in CORNERS]
        text += ['write_verilog '+brace(out/'repaired.v'),'write_db '+brace(out/'repaired.odb'),
                 'write_sdc '+brace(out/'repaired.sdc'),'puts DESYNC_ELECTRICAL_PREPARATION_COMPLETE']
        script=out/'run.tcl';script.write_text('\n'.join(text)+'\n',encoding='utf-8')
        if receipt.command(road.command(['-exit',road.path(script)],timeout=1800),cwd=ROOT,log=out/'run.log'):
            raise ValueError('DESYNC_ELECTRICAL_FLOW')
        repaired=read_verilog_json(out/'repaired.v',out/'repaired.json','RiscayMcuDigital',yosys,pdk,source)
        proof=graph_proof(source,repaired,'RiscayMcuDigital',protected,libs)
        write_json(out/'graph-proof.json',proof)
        write_json(out/'tree-audit.json',validate_trees(prepared,repaired,distribution))
        seeds=[b['instance']+'/'+c['name']+'/'+p for b in bindings for c in b['cells'] for p in c['pins']]
        inventory=classify(flat(repaired,'RiscayMcuDigital'),seeds)
        rows={c:compose_reports((out/(c+'-electrical.rpt')).read_text(encoding='utf-8'),
                               (out/(c+'-strict.rpt')).read_text(encoding='utf-8'),inventory) for c in CORNERS}
        write_json(out/'violations.json',rows)
        area=sum(scalar(all_libs[c['type']],'area') for c in repaired['modules']['RiscayMcuDigital']['cells'].values() if c['type']!=SRAM)/1e6
        write_json(out/'summary.json',dict(logic_mm2=area,electrical_violations={c:len(r) for c,r in rows.items()},
            scope='Zero-wire electrical preparation; delay apertures open; not timing acceptance',
            native_transition_coverage='not yet measured; ideal analysis roots do not qualify controller slew',
            graph=proof['status'],complete_chip=False))
        if any(rows.values()):raise ValueError('DESYNC_FINAL_ELECTRICAL_VIOLATIONS')
    except BaseException:
        receipt.finish(outputs=[p for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'],status='fail')
        raise
    receipt.finish(outputs=[p for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mapping',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--mutex-libs',type=Path,required=True);p.add_argument('--mutex-lef',type=Path,required=True)
    p.add_argument('--failures',type=Path,help='Previous measured electrical failures, never guessed repairs')
    a=p.parse_args();run(a.mapping.resolve(),a.output.resolve(),a.mutex_libs.resolve(),a.mutex_lef.resolve(),a.failures.resolve() if a.failures else None)
