# SPDX-License-Identifier: Apache-2.0
"""Conditional hold STA for a direct, ungated native latch-pair handoff.

One actual receiver-A frontier drives both capture and sender reopening. Keep
the real repaired trees, paired Q/D wires and all removed pin capacitance.
This sampled steady-cycle check does not qualify pulses, reset, setup, gated
storage, CPU flops, macros, same-phase edges or a continuous slew envelope.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
import math
from pathlib import Path
import re
from characterize_gf180_liberty import CORNERS
from gf180_estimate import groups, direct_groups, scalar
from gf180_physical import ROOT, SC, SRAM, write_json
from physical_tools import tool
from primitives import resolve_candidate, transition_contexts
from repair_gf180_design import ident
from run_receipt import RunReceipt


def prepare(original, analysis, loads, bindings, roots, routes, bank):
    """Restore only the causal reopen controller and receiver enable inverter."""
    view=deepcopy(analysis); loads=deepcopy(loads)
    before=original['modules']['RiscayMcuDigital']; body=view['modules']['RiscayMcuDigital']
    indexed={b['instance']:b for b in bindings}
    source=indexed['desync_control/'+bank+'.m']; target=indexed['desync_control/'+bank+'.s']
    if source['ports']['acknowledgeIn']!=target['ports']['acknowledgeOut']:
        raise ValueError('HANDOFF_NOT_DIRECT_ACK')
    context=next(c for c in transition_contexts(source['primitive'],source['parameters'])
                 if c['label']=='Aminus_acknowledgeIn')
    helpers={c['type']:c['connections']['I'][0] for c in body['cells'].values()
             if c['type'].startswith('DesyncAnalysisLoad')}
    loadmap={helpers[r['cell']]:r['pins'] for r in loads}; cuts=[]
    for binding in (source,target):
        recipe=resolve_candidate(binding['primitive'],binding.get('parameters'))
        restore=recipe['cells'] if binding==source else [c for c in recipe['cells'] if c['name']=='enable_invert__cell']
        for leaf in restore:
            name=binding['instance']+'/'+leaf['name']; cell=deepcopy(before['cells'][name])
            for pin,net in leaf['pins'].items():
                if cell['port_directions'][pin]=='output':
                    body['ports'].pop(roots.get(binding['instance']+'/'+net),None)
                    continue
                fixed=None
                if binding==source:
                    fixed=context['fixed'].get(net)
                    for frontier,paths in context['frontiers'].items():
                        if leaf['name']+'/'+pin in paths:fixed=context['fixed'][frontier]
                bit=cell['connections'][pin][0]
                if fixed is not None:
                    cell['connections'][pin]=[str(fixed)]; cuts.append(dict(cell=name,pin=pin,bit=bit,value=fixed))
                elif bit in loadmap:loadmap[bit].remove([cell['type'],pin])
            body['cells'][name]=cell
    pairs=pair_inventory(body,routes,roots,source,target)
    audit_view(original,view,loads,bindings,cuts)
    return view,loads,pairs,cuts,roots[target['instance']+'/acknowledgeOut']


def pair_inventory(body,routes,roots,source,target):
    by_phase={}
    loads=defaultdict(list)
    for name,cell in body['cells'].items():
        for pin,bits in cell['connections'].items():
            if cell['port_directions'][pin]=='input':
                for bit in bits:loads[bit].append((name,pin))
    for phase,binding in (('source',source),('target',target)):
        # Independently enumerate from real mapped pins. A stale routes.json
        # must not hide a paired bit or an inconvenient gated/macro sink.
        root=body['cells'][binding['instance']+'/enable_invert__cell']['connections']['ZN'][0]
        todo=[(root,True)];seen=set();actual=set()
        while todo:
            bit,clean=todo.pop()
            if (bit,clean) in seen:continue
            seen.add((bit,clean))
            for name,pin in loads[bit]:
                c=body['cells'][name]
                if c['type'].startswith((SC+'lat',SC+'dff')) or c['type']==SRAM:
                    if pin not in ('E','CLK','CLKN'):continue
                    if pin!='E' or not c['type'].startswith(SC+'lat'):raise ValueError('HANDOFF_NOT_LATCH')
                    if not clean:raise ValueError('HANDOFF_GATED_OR_INVERTED_TREE')
                    actual.add(name)
                elif not name.startswith('desync_control/'):
                    plain=c['type'].startswith((SC+'buf_',SC+'clkbuf_'))
                    todo += [(b,clean and plain) for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs]
        names=[]
        for pin,path in routes.items():
            if path['root']!=roots[binding['instance']+'/enable']:continue
            name,port=pin.rsplit('/',1)
            if port!='E':continue
            if not body['cells'][name]['type'].startswith(SC+'lat'):raise ValueError('HANDOFF_NOT_LATCH')
            if any(not body['cells'][arc[0]]['type'].startswith((SC+'buf_',SC+'clkbuf_')) for arc in path['arcs']):
                raise ValueError('HANDOFF_GATED_OR_INVERTED_TREE')
            names.append(name)
        if set(names)!=actual:raise ValueError('HANDOFF_TREE_INVENTORY')
        by_phase[phase]=names
    source_bits={body['cells'][n]['connections']['Q'][0]:n for n in by_phase['source']}
    pairs=[]
    for name in by_phase['target']:
        bit=body['cells'][name]['connections']['D'][0]
        if bit not in source_bits:raise ValueError('HANDOFF_NOT_DIRECT_DATA')
        pairs.append((source_bits[bit]+'/Q',name+'/D'))
    if not pairs or len(pairs)!=len(source_bits) or len(source_bits)!=len(by_phase['source']) or len({q for q,d in pairs})!=len(pairs):
        raise ValueError('HANDOFF_NOT_ONE_TO_ONE')
    return sorted(pairs)


def audit_view(original,view,loads,bindings,cuts):
    before=original['modules']['RiscayMcuDigital']; after=view['modules']['RiscayMcuDigital']
    native={b['instance']+'/'+c['name'] for b in bindings
            for c in resolve_candidate(b['primitive'],b.get('parameters'))['cells']}
    helpers={n:c for n,c in after['cells'].items() if c['type'].startswith('DesyncAnalysisLoad')}
    ordinary={n:c for n,c in after['cells'].items() if n not in native and n not in helpers}
    if ordinary!={n:c for n,c in before['cells'].items() if n not in native}:raise ValueError('HANDOFF_ORDINARY_GRAPH_CHANGED')
    expected=deepcopy(before['cells'])
    for cut in cuts:expected[cut['cell']]['connections'][cut['pin']]=[str(cut['value'])]
    for n,c in after['cells'].items():
        if n in native and c!=expected[n]:raise ValueError('HANDOFF_NATIVE_GRAPH_CHANGED')
    live={b for c in after['cells'].values() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs}
    live.update(b for p in after['ports'].values() if p['direction']=='input' for b in p['bits'])
    def inventory(cells):
        return Counter((c['type'],p,b) for c in cells.values() for p,bs in c['connections'].items()
                       if c['port_directions'][p]=='input' for b in bs if isinstance(b,int) and b in live)
    actual=inventory({n:c for n,c in after['cells'].items() if n not in helpers})
    loadtypes={r['cell']:r['pins'] for r in loads}
    for c in helpers.values():actual.update((kind,pin,c['connections']['I'][0]) for kind,pin in loadtypes[c['type']])
    if actual!=inventory(before['cells']):raise ValueError('HANDOFF_PIN_LOAD_CHANGED')


def clock_cone(body,root,pairs):
    """The two actual hold arms; unrelated unclocked cones are not qualified."""
    drivers={b:(n,p) for n,c in body['cells'].items() for p,bs in c['connections'].items()
             if c['port_directions'][p]=='output' for b in bs}
    rootbit=body['ports'][root]['bits'][0]; active=set();cache={};pins=set()
    def walk(bit):
        if bit==rootbit:return True
        if not isinstance(bit,int):return False
        if bit in cache:return cache[bit]
        if bit in active:raise ValueError('HANDOFF_CLOCK_LOOP')
        if bit not in drivers:raise ValueError('HANDOFF_UNKNOWN_CLOCK_FRONTIER')
        active.add(bit);n,p=drivers[bit];c=body['cells'][n];live=False
        for ip,bs in c['connections'].items():
            if c['port_directions'][ip]!='input':continue
            if any(walk(b) for b in bs):pins.add(n+'/'+ip);live=True
        active.remove(bit);cache[bit]=live
        if live:pins.add(n+'/'+p)
        return live
    for q,d in pairs:
        for endpoint in (q,d):
            n=endpoint.rsplit('/',1)[0]
            if not walk(body['cells'][n]['connections']['E'][0]):raise ValueError('HANDOFF_CLOCK_NOT_REACHED')
            pins.add(n+'/E')
        # Direct Q->D wiring means the receiver's data slew is this Q slew.
        pins.update((q,d))
    return sorted(pins)


def parse(text,pairs,slews,edges=('rise','fall')):
    if 'HOLD_DONE' not in text or 'Error:' in text or 'Warning:' in text or 'combinational loop' in text.lower():raise ValueError('HANDOFF_STA_INCOMPLETE')
    expected={(slew,edge,q,d) for slew in slews for edge in edges for q,d in pairs}; rows={}; electrical={}; case=None
    for line in text.splitlines():
        if line.startswith('CASE '):
            _,slew,edge=line.split();case=(float(slew),edge)
        if line.startswith('HOLD '):
            fields=re.fullmatch(r'HOLD (\{[^}]+\}|\S+) (\{[^}]+\}|\S+) (\S+)',line)
            if fields is None or case is None:raise ValueError('HANDOFF_ROW_INVALID')
            key=(*case,fields[1].strip('{}'),fields[2].strip('{}'));value=float(fields[3])
            if key in rows or not math.isfinite(value):raise ValueError('HANDOFF_ROW_INVALID')
            rows[key]=value
        if line.startswith('PATH_SLEW '):
            value=float(line.split()[1])
            if case is None or case in electrical or not math.isfinite(value) or not 0<value<=2.000001:
                raise ValueError('HANDOFF_PATH_SLEW')
            electrical[case]=value
    if set(rows)!=expected:raise ValueError('HANDOFF_PAIR_COVERAGE')
    if set(electrical)!={(s,e) for s in slews for e in edges}:raise ValueError('HANDOFF_ELECTRICAL_COVERAGE')
    return [dict(slew_ns=s,edge=e,source=q,target=d,margin_ns=v) for (s,e,q,d),v in rows.items()]


def run(mapping,repaired,segments,output,mutex_libs,bank,period,derate,late_capture):
    if not all(math.isfinite(v) for v in (period,derate,late_capture)) or period<=0 or derate<1.2 or late_capture<0:
        raise ValueError('HANDOFF_INVALID_TIMING_POLICY')
    output.mkdir(parents=True,exist_ok=False); sta=tool('sta'); yosys=tool('yosys')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    libraries=[p for corner in CORNERS for p in (ROOT/'.tools/physical/pdk'/(SC+corner+'.lib'),
        ROOT/'.tools/gf180-sram'/(SRAM+'__'+corner+'.lib'),mutex_libs/('ca_mutex_gf180_candidate__'+corner+'__scenarios.lib'))]
    receipt=RunReceipt(output/'receipt.json',inputs=[mapping/'control.json',repaired/'repaired.json',
        *[segments/f for f in ('analysis.json','restored-loads.json','roots.json','routes.json')],*libraries],
        tools=[Path(__file__),*[ROOT/'tools'/f for f in ('primitives.py','gf180_estimate.py','gf180_physical.py',
            'characterize_gf180_liberty.py','repair_gf180_design.py','physical_tools.py','run_receipt.py')],*yosys.input_files(),*sta.input_files()])
    reports=[]
    try:
        bindings=read(mapping/'control.json')['bindings']; original=read(repaired/'repaired.json')
        original['modules']['RiscayMcuDigital']['cells']={ident(n):c for n,c in original['modules']['RiscayMcuDigital']['cells'].items()}
        view,loads,pairs,cuts,root=prepare(original,read(segments/'analysis.json'),read(segments/'restored-loads.json'),
            bindings,read(segments/'roots.json'),read(segments/'routes.json'),bank)
        write_json(output/'analysis.json',view);write_json(output/'cuts.json',cuts);write_json(output/'pairs.json',pairs)
        cone=clock_cone(view['modules']['RiscayMcuDigital'],root,pairs)
        write_json(output/'clock-cone.json',cone)
        script=output/'emit.ys';script.write_text(f'read_json "{yosys.path(output/"analysis.json")}"\nwrite_verilog -norename -noattr -noexpr "{yosys.path(output/"analysis.v")}"\n',encoding='utf-8')
        if receipt.command(yosys.command(['-s',yosys.path(script)],timeout=120),cwd=ROOT,log=output/'emit.log'):raise ValueError('HANDOFF_EMIT')
        for corner in CORNERS:
            files=[p for p in libraries if corner in p.name]
            lib={k:v for p in files for k,v in groups(p.read_text(encoding='utf-8'),'cell')}
            pins={k:dict(direct_groups(v,'pin'))|dict(direct_groups(v,'bus')) for k,v in lib.items()}
            loadtext=['library(desync_analysis_loads) { time_unit : "1ns"; capacitive_load_unit(1,pf);']
            loadtext += [f'{kind}_threshold_pct_{edge} : {value};' for edge in ('rise','fall') for kind,value in (('input',50),('output',50),('slew_lower',30),('slew_upper',70))]
            for row in loads:
                cap=sum(scalar(pins[k][p],'capacitance') for k,p in row['pins'])
                loadtext.append('cell('+row['cell']+') { area : 0; pin(I) { direction : input; capacitance : '+str(cap)+';} }')
            loadlib=output/(corner+'-loads.lib');loadlib.write_text('\n'.join(loadtext+['}']),encoding='utf-8')
            text=[f'read_liberty {{{sta.path(p)}}}' for p in [loadlib,*files[:2]]]
            text += [f'read_verilog {{{sta.path(output/"analysis.v")}}}','link_design RiscayMcuDigital',
                f'create_clock -name close -period {period} [get_ports {root}]','set_propagated_clock [all_clocks]',
                'set_input_transition .02 [all_inputs]',f'set_timing_derate -late {derate}']
            for n,c in view['modules']['RiscayMcuDigital']['cells'].items():
                if c['type'].startswith(SC+'lat'):text.append(f'set_disable_timing -from D -to Q [get_cells {{{n}}}]')
            if late_capture:
                cell='desync_control/'+bank+'.s/enable_invert__cell'
                # The analysis netlist is flat: slashes AND dots are literal
                # characters in an escaped Verilog instance identifier.
                instance=cell.replace('/',r'\/').replace('.',r'\.')
                kind=view['modules']['RiscayMcuDigital']['cells'][cell]['type']
                sdf=output/'late-capture.sdf'
                sdf.write_text('(DELAYFILE (SDFVERSION "3.0") (DESIGN "RiscayMcuDigital") (DIVIDER /) (TIMESCALE 1ns)\n'
                    f'(CELL (CELLTYPE "{kind}") (INSTANCE {instance}) (DELAY (ABSOLUTE '
                    f'(IOPATH I ZN ({late_capture}:{late_capture}:{late_capture}) ({late_capture}:{late_capture}:{late_capture}))))))\n',encoding='utf-8')
                text.append(f'read_sdf {{{sta.path(sdf)}}}')
            text += ['set qs [get_pins {'+' '.join(q for q,d in pairs)+'}]','set ds [get_pins {'+' '.join(d for q,d in pairs)+'}]',
                     'set cone [get_pins {'+' '.join(cone)+'}]']
            slews=(.02,.07922,.2871,.6841,1.303,2.)
            for slew in slews:
                for edge in ('rise','fall'):
                    text += [f'set_clock_transition {slew} [all_clocks]',f'puts {{CASE {slew} {edge}}}',
                        f'report_checks -from $qs -{edge}_to $ds -path_delay min -format full_clock_expanded -fields {{slew cap}} -digits 9',
                        f'set paths [find_timing_paths -from $qs -{edge}_to $ds -path_delay min -group_path_count {len(pairs)+1} -endpoint_path_count 1]',
                        'foreach p $paths {puts [list HOLD [get_full_name [get_property $p startpoint]] [get_full_name [get_property $p endpoint]] [get_property $p slack]]}',
                        'set worst 0; foreach pin $cone {foreach mode {min max} {foreach pol {rise fall} {set v [get_property $pin slew_${mode}_${pol}]; if {$v > $worst} {set worst $v}}}}',
                        'puts "PATH_SLEW $worst"; if {$worst > 2.000001} {error HANDOFF_PATH_SLEW}']
            text += ['puts HOLD_DONE','exit']; script=output/(corner+'.tcl');script.write_text('\n'.join(text),encoding='utf-8')
            log=output/(corner+'.log')
            if receipt.command(sta.command(['-exit',sta.path(script)],timeout=180),cwd=ROOT,log=log):raise ValueError('HANDOFF_STA')
            rows=parse(log.read_text(encoding='utf-8'),pairs,slews)
            reports.append(dict(corner=corner,rows=rows,minimum_margin_ns=min(r['margin_ns'] for r in rows)))
        write_json(output/'summary.json',dict(scope='Conditional steady-cycle sampled direct handoff hold; no pulse/reset/setup/routed qualification',
            bank=bank,period_ns=period,late_derate=derate,late_capture_mutation_ns=late_capture,pairs=len(pairs),corners=reports))
        if any(r['minimum_margin_ns']<.1 for r in reports):raise ValueError('HANDOFF_MARGIN_BELOW_100PS')
    except BaseException:
        if not receipt.finished:receipt.finish(outputs=[p for p in output.iterdir() if p.is_file() and p.name!='receipt.json'],status='fail')
        raise
    receipt.finish(outputs=[p for p in output.iterdir() if p.is_file() and p.name!='receipt.json'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('mapping','repaired','segments','output'):p.add_argument(name,type=Path)
    p.add_argument('--mutex-libs',type=Path,required=True);p.add_argument('--bank',default='i2c')
    p.add_argument('--period',type=float,default=1000);p.add_argument('--derate',type=float,default=1.2)
    p.add_argument('--late-capture',type=float,default=0,help='Analysis-only mutation, ns; never changes the mapped chip')
    a=p.parse_args();run(a.mapping,a.repaired,a.segments,a.output,a.mutex_libs,a.bank,a.period,a.derate,a.late_capture)
