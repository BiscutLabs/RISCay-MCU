# SPDX-License-Identifier: Apache-2.0
"""Loaded, phase-specific primitive STA using registry-declared frontiers.

No timing waiver is applied to the chip. Local feedback branch input pins are
analysis frontiers; their capacitance is restored on the separately measured
driver. Keeper acquisition, wire forks, reset, mutex contention and full bank
composition remain independent obligations.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
import json
import math
import re
from pathlib import Path
from gf180_physical import ROOT,SC,SRAM,write_json
from gf180_estimate import groups,direct_groups,scalar
from repair_gf180_design import flat
from primitives import resolve_candidate,transition_contexts,emit_candidate
from characterize_gf180_liberty import CORNERS
from physical_tools import tool
from run_receipt import RunReceipt


def fixture(recipe,frontiers):
    result=deepcopy(recipe);cells={c['name']:c for c in result['cells']};cuts=[]
    for frontier,pins in frontiers.items():
        if frontier in result['ports']:raise ValueError('DESYNC_FRONTIER_COLLISION')
        result['ports'][frontier]='input'
        for path in pins:
            n,p=path.rsplit('/',1);old=cells[n]['pins'][p]
            if recipe['ports'].get(old)!='output':raise ValueError('DESYNC_FRONTIER_NOT_FEEDBACK_OUTPUT')
            cells[n]['pins'][p]=frontier;cuts.append(dict(cell=n,pin=p,driver=old,frontier=frontier))
    return result,cuts


def external_loads(netlist,bindings,lib):
    graph=flat(netlist,'RiscayMcuDigital');loads=defaultdict(list);pins={}
    for n,c in graph['cells'].items():
        if c['type'] not in pins:
            pins[c['type']]=dict(direct_groups(lib[c['type']],'pin'))|dict(direct_groups(lib[c['type']],'bus'))
        for p,bits in c['connections'].items():
            if c['directions'][p]=='input':
                for bit in bits:loads[bit].append((n,scalar(pins[c['type']][p],'capacitance')))
    for n,p in graph['ports'].items():
        if p['direction']=='output':
            for bit in p['bits']:loads[bit].append((n,.05))
    result={}
    for b in bindings:
        prefix=b['instance']+'/';r=resolve_candidate(b['primitive'],b.get('parameters'));outputs={}
        for port,d in r['ports'].items():
            if d!='output':continue
            drivers=[(c['name'],p) for c in r['cells'] for p,n in c['pins'].items() if n==port and p in ('Z','ZN','G0','G1')]
            if len(drivers)!=1:raise ValueError('DESYNC_LOADED_OUTPUT_DRIVER')
            n,p=drivers[0];bit=graph['cells'][prefix+n]['connections'][p][0]
            outputs[port]=sum(cap for consumer,cap in loads[bit] if not consumer.startswith(prefix))
        result[b['instance']]=outputs
    return result


def arc_polarities(recipe,lib):
    """Use Liberty unateness to follow the admitted edge, not its reverse.

    A state-conditioned slice may admit only one source edge. A generic slew
    report also checks the impossible reverse edge with the same frozen state.
    Every sampled path point is checked in its actual transition direction.
    """
    result={}
    for cell in recipe['cells']:
        for output,body in direct_groups(lib[cell['cell']],'pin'):
            for _,arc in direct_groups(body,'timing'):
                related=re.search(r'\brelated_pin\s*:\s*"?([A-Za-z0-9_]+)"?\s*;',arc)
                sense=re.search(r'\btiming_sense\s*:\s*(positive_unate|negative_unate)\s*;',arc)
                if related and sense:
                    key=(cell['name']+'/'+related[1],cell['name']+'/'+output)
                    polarity=sense[1]=='negative_unate'
                    if key in result and result[key]!=polarity:raise ValueError('DESYNC_ARC_POLARITY')
                    result[key]=polarity
        outputs=[p for p in cell['pins'] if p in ('Z','ZN')]
        if len(outputs)!=1:raise ValueError('DESYNC_ARC_OUTPUT')
        for pin in cell['pins']:
            if pin not in outputs and (cell['name']+'/'+pin,cell['name']+'/'+outputs[0]) not in result:
                raise ValueError('DESYNC_ARC_POLARITY_MISSING')
    return result


def leaf_envelope(mapping,repaired,out,mutex_libs):
    """Conservative electrical envelope, independent of controller state.

    Each registered combinational leaf sees its real complete pin load. All
    input arcs/polarities are exercised, including branches that do not reach
    a controller output during a particular state transition. This may include
    unreachable combinations; it must never omit a physical input arc.
    """
    out.mkdir(parents=True,exist_ok=False);sta=tool('sta')
    bindings=json.loads((mapping/'control.json').read_text(encoding='utf-8'))['bindings']
    net=json.loads((repaired/'repaired.json').read_text(encoding='utf-8'));graph=flat(net,'RiscayMcuDigital')
    pdk=ROOT/'.tools/physical/pdk';sr=ROOT/'.tools/gf180-sram'
    libs=[pdk/(SC+c+'.lib') for c in CORNERS]+[sr/(SRAM+'__'+c+'.lib') for c in CORNERS]+[
        mutex_libs/('ca_mutex_gf180_candidate__'+c+'__scenarios.lib') for c in CORNERS]
    receipt=RunReceipt(out/'receipt.json',inputs=[mapping/'control.json',repaired/'repaired.json',*libs],
        tools=[Path(__file__),ROOT/'tools/primitives.py',*sta.input_files()]);reports=[]
    try:
        for corner in CORNERS:
            files=[pdk/(SC+corner+'.lib'),sr/(SRAM+'__'+corner+'.lib'),mutex_libs/('ca_mutex_gf180_candidate__'+corner+'__scenarios.lib')]
            lib={k:v for p in files for k,v in groups(p.read_text(encoding='utf-8'),'cell')}
            loads=defaultdict(float);pin_cache={}
            for c in graph['cells'].values():
                if c['type'] not in pin_cache:
                    pin_cache[c['type']]=dict(direct_groups(lib[c['type']],'pin'))|dict(direct_groups(lib[c['type']],'bus'))
                pins=pin_cache[c['type']]
                for pin,bits in c['connections'].items():
                    if c['directions'][pin]=='input':
                        for bit in bits:loads[bit]+=scalar(pins[pin],'capacitance')
            for p in graph['ports'].values():
                if p['direction']=='output':
                    for bit in p['bits']:loads[bit]+=.05
            cases={}
            for binding in bindings:
                if binding['primitive']=='RiscayDesyncMutex':continue
                for cell in resolve_candidate(binding['primitive'],binding.get('parameters'))['cells']:
                    path=binding['instance']+'/'+cell['name'];mapped=graph['cells'][path]
                    outputs={p:loads[bs[0]] for p,bs in mapped['connections'].items() if mapped['directions'][p]=='output'}
                    key=(mapped['type'],tuple(sorted(outputs.items())))
                    if key not in cases:cases[key]=dict(module='Leaf'+str(len(cases)),cell=mapped['type'],outputs=outputs,
                        pins=mapped['directions'],instances=[])
                    cases[key]['instances'].append(path)
            rtl=[];tcl=['read_liberty {'+sta.path(files[0])+'}'];source=out/(corner+'.v')
            for case in cases.values():
                recipe=dict(ports=case['pins'],cells=[dict(name='leaf',cell=case['cell'],pins={p:p for p in case['pins']})])
                rtl.append(emit_candidate(recipe,case['module']))
                # Sampling every library slew knot bounds its piecewise-linear
                # interpolation over the admitted .02..2 ns input interval.
                knots={.02,2.}
                for body in re.findall(r'index_1\s*\(\s*"([^"]+)"\s*\)',lib[case['cell']]):
                    knots.update(v for v in map(float,body.split(',')) if .02<=v<=2.)
                tcl += ['read_verilog {'+sta.path(source)+'}','link_design '+case['module'],
                    'create_clock -name analysis -period 1000000','set_input_delay 0 -clock analysis [all_inputs]',
                    'set_output_delay 0 -clock analysis [all_outputs]','set_max_transition 2 [current_design]']
                tcl += [f'set_load {cap:.12g} [get_ports {p}]' for p,cap in case['outputs'].items()]
                for slew in sorted(knots):
                    tcl += [f'set_input_transition {slew:.12g} [all_inputs]',f'puts {{LEAF {case["module"]} {slew}}}',
                            'report_check_types -max_slew -max_capacitance -violators -digits 9']
            source.write_text('\n'.join(rtl),encoding='utf-8');write_json(out/(corner+'-cases.json'),list(cases.values()))
            script=out/(corner+'.tcl');script.write_text('\n'.join(tcl+['puts ENVELOPE_DONE','exit'])+'\n',encoding='utf-8')
            log=out/(corner+'.log')
            if receipt.command(sta.command(['-exit',sta.path(script)],timeout=120),cwd=ROOT,log=log):raise ValueError('DESYNC_LEAF_STA')
            text=log.read_text(encoding='utf-8')
            if 'ENVELOPE_DONE' not in text or 'Error:' in text:raise ValueError('DESYNC_LEAF_COVERAGE')
            reports.append(dict(corner=corner,violations=text.count('(VIOLATED)'),cells=sum(len(c['instances']) for c in cases.values())))
        write_json(out/'summary.json',dict(scope='Loaded combinational leaves, all arcs and slew knots; no pulse/mutex/reset qualification',corners=reports))
        if any(r['violations'] for r in reports):raise ValueError('DESYNC_LEAF_ELECTRICAL')
    except BaseException:
        if not receipt.finished:receipt.finish(outputs=[p for p in out.iterdir() if p.is_file() and p.name!='receipt.json'],status='fail')
        raise
    receipt.finish(outputs=[p for p in out.iterdir() if p.is_file() and p.name!='receipt.json'])


def run(mapping,repaired,out,mutex_libs):
    out.mkdir(parents=True,exist_ok=False);s=tool('sta')
    bindings=json.loads((mapping/'control.json').read_text(encoding='utf-8'))['bindings']
    net=json.loads((repaired/'repaired.json').read_text(encoding='utf-8'))
    pdk=ROOT/'.tools/physical/pdk';sr=ROOT/'.tools/gf180-sram'
    libraries=[pdk/(SC+c+'.lib') for c in CORNERS]+[sr/(SRAM+'__'+c+'.lib') for c in CORNERS]+[
        mutex_libs/('ca_mutex_gf180_candidate__'+c+'__scenarios.lib') for c in CORNERS]
    receipt=RunReceipt(out/'receipt.json',inputs=[mapping/'control.json',repaired/'repaired.json',*libraries],
        tools=[Path(__file__),ROOT/'tools/primitives.py',*s.input_files()])
    manifest=[];rtl=[]
    for b in bindings:
        if b['primitive']=='RiscayDesyncMutex':continue
        recipe=resolve_candidate(b['primitive'],b.get('parameters'));modes={}
        for context in transition_contexts(b['primitive'],b.get('parameters')):
            key=json.dumps(context['frontiers'],sort_keys=True)
            if key not in modes:
                mod='Fixture'+str(len(manifest));view,cuts=fixture(recipe,context['frontiers'])
                manifest.append(dict(instance=b['instance'],module=mod,recipe=recipe,cuts=cuts,contexts=[]))
                modes[key]=len(manifest)-1;rtl.append(emit_candidate(view,mod))
            manifest[modes[key]]['contexts'].append(context)
    source=out/'fixtures.v';source.write_text('\n'.join(rtl),encoding='utf-8');write_json(out/'manifest.json',manifest)
    results=[]
    try:
        for corner in CORNERS:
            files=[pdk/(SC+corner+'.lib'),sr/(SRAM+'__'+corner+'.lib'),mutex_libs/('ca_mutex_gf180_candidate__'+corner+'__scenarios.lib')]
            lib={k:v for p in files for k,v in groups(p.read_text(encoding='utf-8'),'cell')}
            loads=external_loads(net,bindings,lib);tcl=['read_liberty {'+s.path(files[0])+'}']
            cases=[]
            for item in manifest:
                load=dict(loads[item['instance']]);recipe=item['recipe'];leaves={c['name']:c for c in recipe['cells']}
                for cut in item['cuts']:
                    body=dict(direct_groups(lib[leaves[cut['cell']]['cell']],'pin'))[cut['pin']]
                    load[cut['driver']]+=scalar(body,'capacitance')
                tcl += ['read_verilog {'+s.path(source)+'}','link_design '+item['module'],'create_clock -name analysis -period 1000000',
                        'set_max_transition 2 [current_design]',
                        'set_input_delay 0 -clock analysis [all_inputs]','set_output_delay 0 -clock analysis [all_outputs]',
                        'set_max_delay 1000000 -from [all_inputs] -to [all_outputs]',
                        'set_min_delay 0 -from [all_inputs] -to [all_outputs]']
                tcl += ['set inversions {}']+[f'dict set inversions [list {a} {b}] {int(inv)}'
                           for (a,b),inv in arc_polarities(recipe,lib).items()]
                for port,cap in load.items():tcl.append(f'set_load {cap:.12g} [get_ports {port}]')
                for context in item['contexts']:
                    tcl += ['unset_case_analysis [all_inputs]']+[f'set_case_analysis {v} [get_ports {p}]' for p,v in context['fixed'].items()]
                    for slew in (.02,2.0):
                        tcl.append(f'set_input_transition {slew} [all_inputs]')
                        tcl += [f'puts {{ELECTRICAL {item["instance"]} {context["label"]} {slew}}}',
                                'report_check_types -max_capacitance -violators -digits 9']
                        for target,rise in context['targets'].items():
                            for sense in ('min','max'):
                                index=len(cases);cases.append(dict(instance=item['instance'],context=context['label'],source=context['source'],
                                    source_rise=context['rise'],target=target,target_rise=rise,sense=sense,input_slew_ns=slew,output_load_pf=load[target]))
                                options=f'-{"rise" if context["rise"] else "fall"}_from [get_ports {context["source"]}] -{"rise" if rise else "fall"}_to [get_ports {target}]'
                                tcl += [f'set paths [find_timing_paths {options} -path_delay {sense} -group_path_count 1 -endpoint_path_count 1]',
                                    f'if {{[llength $paths] != 1}} {{error DESYNC_TRANSITION_MISSING:{index}}}',
                                    'set points [get_property [lindex $paths 0] points]',
                                    'set delta [expr {[get_property [lindex $points end] arrival]-[get_property [lindex $points 0] arrival]}]',
                                    f'set rising {int(context["rise"])}; set previous {{}}; set worst 0',
                                    'foreach pt $points {set pin [get_property $pt pin]; set name [get_full_name $pin]; '
                                    'set key [list $previous $name]; '
                                    'if {[string last / $name]>=0 && [file dirname $name] eq [file dirname $previous] && ![dict exists $inversions $key]} {error DESYNC_PATH_ARC_UNKNOWN}; '
                                    'if {[dict exists $inversions $key] && [dict get $inversions $key]} {set rising [expr {!$rising}]}; '
                                    f'set pslew [get_property $pin slew_{sense}_[expr {{$rising ? "rise" : "fall"}}]]; '
                                    'set worst [expr {max($worst,$pslew)}]; set previous $name}',
                                    f'if {{$rising != {int(rise)}}} {{error DESYNC_PATH_POLARITY}}',
                                    f'if {{$worst > 2.000001}} {{error DESYNC_TRANSITION_SLEW:{index}:$worst}}',
                                    f'puts "RESULT {index} $delta [get_property [get_ports {target}] slew_{sense}_{"rise" if rise else "fall"}]"']
            tcl.append('exit');script=out/(corner+'.tcl');script.write_text('\n'.join(tcl)+'\n',encoding='utf-8')
            write_json(out/(corner+'-cases.json'),cases)
            log=out/(corner+'.log')
            if receipt.command(s.command(['-exit',s.path(script)],timeout=600),cwd=ROOT,log=log):raise ValueError('DESYNC_TRANSITION_STA')
            text=log.read_text(encoding='utf-8');observed={}
            for line in text.splitlines():
                if not line.startswith('RESULT '):continue
                _,i,delay,slew=line.split();i=int(i);delay=float(delay);slew=float(slew)
                if i in observed or not all(math.isfinite(v) and v>0 for v in (delay,slew)):
                    raise ValueError('DESYNC_TRANSITION_NONFINITE')
                observed[i]=dict(cases[i],corner=corner,delay_ns=delay,slew_ns=slew)
            if set(observed)!=set(range(len(cases))) or 'combinational loop' in text.lower():raise ValueError('DESYNC_TRANSITION_COVERAGE')
            if '(VIOLATED)' in text:raise ValueError('DESYNC_TRANSITION_ELECTRICAL')
            results+=list(observed.values())
        write_json(out/'summary.json',dict(scope='Local conditional transition samples only; no bank/keeper/reset/mutex qualification',rows=results))
    except BaseException:
        receipt.finish(outputs=[p for p in out.iterdir() if p.is_file() and p.name!='receipt.json'],status='fail');raise
    receipt.finish(outputs=[p for p in out.iterdir() if p.is_file() and p.name!='receipt.json'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mapping',type=Path);p.add_argument('repaired',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--mutex-libs',type=Path,required=True)
    p.add_argument('--leaf-envelope',action='store_true')
    a=p.parse_args();(leaf_envelope if a.leaf_envelope else run)(a.mapping.resolve(),a.repaired.resolve(),a.output.resolve(),a.mutex_libs.resolve())
