# SPDX-License-Identifier: Apache-2.0
"""Bound custom same-event passive feedback to real FF hold checks.

This is a local, zero-wire-RC sampled screen, not continuous/PVT-mismatch or
routed signoff. No datapath-only exception replaces a Liberty hold check.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re
import subprocess

import control_relative_timing as relative
import native_leaf_timing as leaf
import native_stage_timing as stages
import passive_source_inventory as sources
from gf180_estimate import library, direct_groups, scalar, numbers, table_value
from gf180_physical import ROOT, SC, SRAM, sha, write_json
from physical_tools import tool
from repair_gf180_control import require
from repair_gf180_design import validate_receipt
from screen_gf180_control_repair import brace

SAME = {'self-feedback', 'same-event-net'}
STATE = {'ChiselAsyncEventRegister_v1', 'ChiselAsyncPhaseRegister_v1'}


def storage(record, audit, index, name):
    rows = [b for b in record['bindings'] if name in b['instances']]
    require(len(rows) == 1 and rows[0]['model'] in STATE, 'FEEDBACK_STORAGE_MODEL')
    binding = rows[0]; path = audit['adapter_instances'][name]
    require(index.scalar(path, 'trigger')[0] == 'pin', 'FEEDBACK_EVENT_ROOT')
    root = index.scalar(path, 'trigger')[1]
    result = {}
    for cell in binding['cells']:
        if 'D' not in cell['pins']:
            continue
        output = cell['pins']['Q']
        match = re.fullmatch(r'q(?:\[(\d+)\])?', output)
        require(match is not None, 'FEEDBACK_STORAGE_OUTPUT')
        lane = int(match[1] or 0)
        expected = SC+('dffsnq_1' if (int(binding['parameters']['RESET_VALUE']) >> lane) & 1 else 'dffrnq_1')
        require(cell['cell'] == expected, 'FEEDBACK_STORAGE_RECIPE')
        name = path+'/'+cell['name']
        require(name in index.after['cells'] and index.after['cells'][name]['type'] == cell['cell'],
                'FEEDBACK_LIVE_STORAGE')
        require(lane not in result, 'FEEDBACK_DUPLICATE_LANE')
        result[lane] = dict(Q=name+'/Q', D=name+'/D', CLK=name+'/CLK')
    require(result, 'FEEDBACK_EMPTY_STORAGE')
    return root, result


def bind(inventory, record, audit, index):
    groups = {}; banks = set()
    for allowance in inventory['allowances']:
        for capture in allowance['captures']:
            candidates = [s for s in capture['source_outputs'] if SAME & set(s['categories'])]
            if not candidates:
                continue
            name = capture['primitive_path']; banks.add(name)
            require(capture['model'] in STATE, 'FEEDBACK_CAPTURE_MODEL')
            root, targets = storage(record, audit, index, name)
            group = groups.setdefault(root, dict(root=root, sources=set(), targets={}, banks=set()))
            group['banks'].add(name)
            for source in candidates:
                source_root, launches = storage(record, audit, index, source['primitive_path'])
                require(source_root == root, 'FEEDBACK_DIFFERENT_EVENT')
                for lane in source['source_lanes']:
                    require(lane in launches, 'FEEDBACK_SOURCE_LANE')
                    group['sources'].add(launches[lane]['Q'])
                for lane in source['capture_lanes']:
                    require(lane in targets and str(lane) not in capture['exact_capture_constant_lanes'],
                            'FEEDBACK_TARGET_LANE')
                    group['targets'][targets[lane]['D']] = dict(bank=name, lane=lane, **targets[lane])
    require(len(banks) == inventory['self_or_same_event_capture_count'], 'FEEDBACK_BANK_COVERAGE')
    require(groups, 'FEEDBACK_EMPTY_COHORT')
    return [dict(g, sources=sorted(g['sources']), banks=sorted(g['banks'])) for _, g in sorted(groups.items())]


def bind_cone(plan,record,audit,index,lib):
    """Complete eligible Q-to-D cone; stop at independently held state outputs."""
    from check_reset_crossings import NATIVE_STATE
    if not hasattr(index,'_feedback_cone_base'):
        drivers={};state=set()
        for path,cell in index.after['cells'].items():
            for pin,bits in cell['connections'].items():
                if cell['directions'][pin]=='output':
                    for net in bits:
                        require(net not in drivers,'FEEDBACK_MULTIPLE_DRIVERS');drivers[net]=(path,pin)
        for binding in record['bindings']:
            if binding['model'] not in NATIVE_STATE:continue
            for instance in binding['instances']:
                path=audit['adapter_instances'][instance]
                for port in binding['ports']:
                    if port['direction']!='output':continue
                    for net in index.before['boundaries'][path+'/'+port['name']]:
                        for kind,label in index.drivers[net]:state.add(index.live_net(kind,label))
        sequential={kind for kind in lib if list(direct_groups(lib[kind],'ff')) or list(direct_groups(lib[kind],'latch'))}
        index._feedback_cone_base=(drivers,state,sequential,{})
    drivers,state,sequential,pin_cache=index._feedback_cone_base
    source_nets={index.live_net('pin',q) for q in plan['sources']}
    arcs=set();cache={};active=set()
    def related(kind,pin):
        key=kind,pin
        if key not in pin_cache:
            require(kind in lib,'FEEDBACK_CONE_CELL')
            body=dict(direct_groups(lib[kind],'pin'))[pin]
            pin_cache[key]=sorted({m[1] for _,arc in direct_groups(body,'timing')
                if (m:=re.search(r'related_pin\s*:\s*"(\w+)"\s*;',arc)) and
                not re.search(r'timing_type\s*:\s*(?:recovery|removal|setup|hold|clear|preset)',arc)})
        return pin_cache[key]
    def reaches(net):
        if net in source_nets:return True
        if net in state:return False
        if net in cache:return cache[net]
        if net not in drivers:return False
        require(net not in active,'FEEDBACK_COMBINATIONAL_CYCLE');active.add(net)
        path,pin=drivers[net];cell=index.after['cells'][path];kind=cell['type']
        if kind in sequential:
            result=False
        else:
            result=False
            for p in sorted(k for k,d in cell['directions'].items() if d=='input'):
                require(len(cell['connections'][p])==1,'FEEDBACK_CONE_VECTOR')
                if reaches(cell['connections'][p][0]):
                    require(p in related(kind,pin),'FEEDBACK_REACHABLE_ARC_MISSING')
                    arcs.add((path+'/'+p,path+'/'+pin));result=True
        active.remove(net);cache[net]=result;return result
    unreachable={}
    for dest in list(plan['targets']):
        if not reaches(index.live_net('pin',dest)):
            unreachable[dest]=plan['targets'].pop(dest)
    require(plan['targets'],'FEEDBACK_NO_REACHABLE_TARGETS')
    root_net=index.live_net('pin',plan['root'])
    def clock_walk(net):
        if net==root_net:return
        require(net in drivers,'FEEDBACK_CLOCK_DRIVER');path,pin=drivers[net]
        cell=index.after['cells'][path]
        require(pin=='Z' and re.fullmatch(re.escape(SC)+r'buf_\d+',cell['type']) is not None and
                set(cell['connections'])=={'I','Z'},'FEEDBACK_CLOCK_TREE')
        arcs.add((path+'/I',path+'/Z'));clock_walk(cell['connections']['I'][0])
    for q in plan['sources']:
        clk=q.rsplit('/',1)[0]+'/CLK';clock_walk(index.live_net('pin',clk));arcs.add((clk,q))
    for target in plan['targets'].values():clock_walk(index.live_net('pin',target['CLK']))
    plan['cone_arcs']=sorted(arcs)
    plan['cone_pins']=sorted({p for arc in arcs for p in arc}|set(plan['targets'])|{plan['root']}|
                             {v['CLK'] for v in plan['targets'].values()})
    plan['structurally_unreachable_targets']=unreachable
    plan['reachability_scope']='Complete Liberty-combinational fan-in; other native/periodic state outputs are independent roots'


def pin_load(index, lib, label):
    cache = getattr(index,'_feedback_loads',None)
    if cache is None or cache[0] is not lib:
        caps={};totals=defaultdict(float);unknown=set()
        for cell in index.after['cells'].values():
            for pin,bits in cell['connections'].items():
                if cell['directions'][pin]!='input':continue
                key=cell['type'],pin
                if cell['type'] not in lib:
                    unknown.update(bits);continue
                if key not in caps:
                    body=dict(direct_groups(lib[cell['type']], 'pin'))[pin]
                    caps[key]=scalar(body,'capacitance')
                for net in bits:totals[net]+=caps[key]
        index._feedback_loads=(lib,totals,unknown)
    require(index.live_net('pin',label) not in index._feedback_loads[2],'FEEDBACK_UNKNOWN_LOAD')
    total=index._feedback_loads[1][index.live_net('pin',label)]
    require(all(index.live_net('pin',label) not in p['bits'] for p in index.after['ports'].values()
                if p['direction']=='output'),'FEEDBACK_TOP_OUTPUT_LOAD')
    require(total > 0, 'FEEDBACK_EMPTY_LOAD')
    return total


def slew_envelope(index, lib, root):
    path, pin = root.rsplit('/', 1); cell = index.after['cells'][path]
    body = dict(direct_groups(lib[cell['type']], 'pin'))[pin]
    load = pin_load(index, lib, root); values = []; axes = []
    for _, arc in direct_groups(body, 'timing'):
        for table in ('rise_transition', 'fall_transition'):
            for _, data in direct_groups(arc, table):
                xs, ys = numbers(data, 'index_1'), numbers(data, 'index_2')
                require(ys[0] <= load <= ys[-1], 'FEEDBACK_ROOT_LOAD_EXTRAPOLATION')
                values += [table_value(data, x, load) for x in xs]
                axes.append(xs)
    require(values and all(math.isfinite(v) and v > 0 for v in values), 'FEEDBACK_ROOT_SLEW')
    low, high = min(values), max(values)
    # Every root-driver output-table knot at this actual load, plus endpoint
    # values. This is an explicit sampled set; do not infer continuous closure.
    return dict(load_pf=load, minimum_ns=low, maximum_ns=high,
                samples_ns=sorted(set(values)), characterized_input_axes_ns=axes)


def hold_aperture(lib):
    values = []
    for model in ('dffrnq_1','dffsnq_1'):
        for _, pin in direct_groups(lib[SC+model], 'pin'):
            for _, arc in direct_groups(pin, 'timing'):
                if re.search(r'timing_type\s*:\s*hold_rising\s*;', arc):
                    for table in ('rise_constraint', 'fall_constraint'):
                        for _, data in direct_groups(arc, table):
                            values += numbers(data, 'values')
    require(values and all(math.isfinite(v) for v in values), 'FEEDBACK_HOLD_APERTURE')
    # Maximum over the entire characterized table, avoiding any assumption
    # that hold constraints are monotonic in data/clock slew.
    return max(values)


TCL = r'''
set pin_ids [dict create]
proc pin_id {name} {
  global pin_ids
  if {![dict exists $pin_ids $name]} {
    set id [dict size $pin_ids]; dict set pin_ids $name $id; row PIN $id $name
  }
  return [dict get $pin_ids $name]
}
proc exact {name} {
  set p [get_pins -quiet $name]
  if {[llength $p] != 1 || [get_full_name [lindex $p 0]] ne $name} {error FEEDBACK_PIN}
  return [lindex $p 0]
}
proc row {args} {puts [join $args "\t"]}
proc check_hold {sample sources targets cone_pins} {
  foreach edge {rise fall} {
    set pending [dict create]; set qs {}; set ds {}
    foreach q $sources {lappend qs [exact $q]}
    foreach d $targets {dict set pending $d 1; lappend ds [exact $d]}
    set paths [find_timing_paths -from $qs -${edge}_to $ds -path_delay min -group_path_count [expr {[llength $targets]+1}] -endpoint_path_count 1]
    foreach end $paths {
      set d [get_full_name [$end pin]]
      if {![dict exists $pending $d]} {error FEEDBACK_DUPLICATE_ENDPOINT}
      dict unset pending $d
      if {[$end is_unconstrained] || [$end is_path_delay] || ![$end is_check] || [$end check_role] ne "hold" || [$end min_max] ne "min"} {error FEEDBACK_REAL_HOLD_REQUIRED}
      set p [$end path]; set start [$p start_path]; set q [get_full_name [$start pin]]
      if {[lsearch -exact $sources $q] < 0} {error FEEDBACK_SOURCE_SET}
      set actual [string map {^ rise v fall} [$end end_transition]]
      if {$actual ne $edge || [get_full_name [$end target_clk]] ne "native_event"} {error FEEDBACK_CLOCK_OR_POLARITY}
      row HOLD $sample [pin_id $d] $edge [pin_id $q] [sta::time_sta_ui [$end slack]] [sta::time_sta_ui [$end margin]] [sta::time_sta_ui [$end data_arrival_time]] [sta::time_sta_ui [$end data_required_time]]
      row PATH $sample [pin_id $d] $edge {*}[lreverse [lmap pin [$p pins] {pin_id [get_full_name $pin]}]]
      set cp [$end target_clk_path]
      row CLOCK $sample [pin_id $d] $edge {*}[lreverse [lmap pin [$cp pins] {pin_id [get_full_name $pin]}]]
    }
    dict for {d unused} $pending {row MISSING $sample $d $edge}
  }
  foreach name $cone_pins {
    set pin [exact $name]
    set values {}
    foreach mode {min max} {foreach edge {rise fall} {
      set v {}; foreach vertex [$pin vertices] {lappend v [sta::time_sta_ui [$vertex slew_corner $edge [sta::cmd_corner] $mode]]}
      lappend values [tcl::mathfunc::$mode {*}$v]
    }}
    row SLEW $sample [pin_id $name] {*}$values
  }
}
'''


def script(mapping, corner, plan, envelope, cuts, sta, period=1000):
    result = 'read_liberty '+brace(sta.path(ROOT/'.tools/physical/pdk'/(SC+corner+'.lib')))+'\n'
    result += 'read_liberty '+brace(sta.path(ROOT/'.tools/gf180-sram'/(SRAM+'__tt_025C_3v30.lib')))+'\n'
    result += TCL+'\nread_verilog '+brace(sta.path(mapping/'netlist.v'))+'\nlink_design RiscayMcuDigital\n'
    result += 'set_input_transition 0.1 [all_inputs]\nset_load 0.05 [all_outputs]\n'
    for path in cuts:
        result += 'set_disable_timing -from A1 -to ZN [get_cells '+brace(path)+']\n'
    result += 'set root [exact '+brace(plan['root'])+']\n'
    result += f'create_clock -name native_event -period {period} -waveform {{0 1}} $root\nset_propagated_clock [all_clocks]\nsta::find_delays\n'
    samples = [('split', envelope['minimum_ns'], envelope['maximum_ns'])]
    samples += [(str(i), v, v) for i, v in enumerate(envelope['samples_ns'])]
    for name, low, high in samples:
        for mode, value in [('min', low), ('max', high)]:
            result += 'foreach vertex [$root vertices] {foreach edge {rise fall} {sta::set_annotated_slew $vertex [sta::cmd_corner] '+mode+' $edge [sta::time_ui_sta '+str(value)+']}}\n'
        result += 'check_hold '+brace(name)+' [list '+' '.join(map(brace, plan['sources']))+'] [list '+' '.join(map(brace, plan['targets']))+'] [list '+' '.join(map(brace,plan['cone_pins']))+']\n'
    result += 'row FEEDBACK_COMPLETE\nexit\n'
    return result, [s[0] for s in samples]


def parse(text, plan, samples, aperture):
    require(text.count('FEEDBACK_COMPLETE') == 1 and not re.search(r'(?m)^Error:', text), 'FEEDBACK_INCOMPLETE')
    expected = {(s, d, e) for s in samples for d in plan['targets'] for e in ('rise', 'fall')}
    rows = {}; paths = {}; clocks = {}; slews = {}; pins={}
    for line in text.splitlines():
        parts = line.split('\t')
        if parts[0]=='PIN':
            require(len(parts)==3 and parts[1] not in pins and parts[2] not in pins.values(),'FEEDBACK_PIN_ID')
            pins[parts[1]]=parts[2]
        elif parts[0] == 'HOLD':
            require(len(parts) == 9, 'FEEDBACK_ROW_SHAPE')
            _, sample, dest, edge, source, slack, margin, arrival, required = parts
            dest,source=pins[dest],pins[source]
            key = sample, dest, edge
            require(key in expected and key not in rows and source in plan['sources'], 'FEEDBACK_ROW_BINDING')
            values = list(map(float, [slack, margin, arrival, required]))
            require(all(math.isfinite(v) for v in values), 'FEEDBACK_NONFINITE')
            rows[key] = dict(sample=sample, target=dest, edge=edge, source=source,
                            slack_ns=values[0], library_hold_ns=values[1],
                            selected_path_maximum_aperture_diagnostic_ns=values[0]+values[1]-aperture)
        elif parts[0] == 'PATH':
            key = parts[1],pins[parts[2]],parts[3]; require(key not in paths, 'FEEDBACK_DUPLICATE_PATH')
            paths[key] = [pins[p] for p in parts[4:]]
        elif parts[0] == 'CLOCK':
            key = parts[1],pins[parts[2]],parts[3]; require(key not in clocks, 'FEEDBACK_DUPLICATE_CLOCK')
            clocks[key] = [pins[p] for p in parts[4:]]
        elif parts[0] == 'SLEW':
            key = parts[1],pins[parts[2]]; require(key not in slews and len(parts) == 7, 'FEEDBACK_SLEW_ROW')
            slews[key] = list(map(float, parts[3:]))
    require(set(rows) == expected and set(paths) == expected and set(clocks) == expected, 'FEEDBACK_PATH_COVERAGE')
    for key, row in rows.items():
        require(row['source'] in paths[key] and row['target'] == paths[key][-1], 'FEEDBACK_PATH_IDENTITY')
        require(paths[key][0] == clocks[key][0] == plan['root'] and
                clocks[key][-1] == plan['targets'][row['target']]['CLK'], 'FEEDBACK_CLOCK_IDENTITY')
        pos=paths[key].index(row['source'])
        require(pos>0 and paths[key][pos-1]==row['source'].rsplit('/',1)[0]+'/CLK','FEEDBACK_LAUNCH_CLOCK_IDENTITY')
        # Exact expanded paths remain in the compact pin-ID log. Do not copy
        # multi-kilobyte pin lists into every sampled numerical JSON row.
    return list(rows.values()), slews


def table_ranges(rows, slews, index, lib, plan):
    """Reject extrapolated loads/slews on the measured data and clock paths.

    Both polarities/modes are checked conservatively, including conditional
    Liberty arcs. An unresolved table is not silently treated as a timing pass.
    """
    errors = []; checked = set(); loads = {}; pin_bodies = {}; arc_cache={}; hold_cache={}
    def pins(cell):
        if cell not in pin_bodies: pin_bodies[cell] = dict(direct_groups(lib[cell], 'pin'))
        return pin_bodies[cell]
    def within(values, axis):
        return all(math.isfinite(v) and axis[0]-1e-6 <= v <= axis[-1]+1e-6 for v in values)
    def arc_tables(kind,ap,bp):
        key=kind,ap,bp
        if key not in arc_cache:
            tables=[]
            for _,arc in direct_groups(pins(kind)[bp],'timing'):
                if not re.search(r'related_pin\s*:\s*"'+re.escape(ap)+r'"\s*;',arc):continue
                for table in ('cell_rise','cell_fall','rise_transition','fall_transition'):
                    for _,body in direct_groups(arc,table):tables.append((table,numbers(body,'index_1'),numbers(body,'index_2')))
            require(tables,'FEEDBACK_ARC_TABLE_MISSING');arc_cache[key]=tables
        return arc_cache[key]
    def hold_tables(kind,pin):
        key=kind,pin
        if key not in hold_cache:
            tables=[]
            for _,arc in direct_groups(pins(kind)[pin],'timing'):
                if not re.search(r'timing_type\s*:\s*hold_rising\s*;',arc):continue
                for table in ('rise_constraint','fall_constraint'):
                    for _,body in direct_groups(arc,table):tables.append((table,numbers(body,'index_1'),numbers(body,'index_2')))
            require(tables,'FEEDBACK_HOLD_TABLE_MISSING');hold_cache[key]=tables
        return hold_cache[key]
    for sample in sorted({row['sample'] for row in rows}):
        for path in plan['cone_arcs']:
            for a,b in [path]:
                ac,ap = a.rsplit('/',1); bc,bp = b.rsplit('/',1)
                if ac != bc or (sample,a,b) in checked: continue
                checked.add((sample,a,b)); kind = index.after['cells'][bc]['type']
                require(kind in lib, 'FEEDBACK_ARC_CELL')
                values = slews.get((sample,a)); require(values is not None,'FEEDBACK_SLEW_MISSING')
                if b not in loads: loads[b] = pin_load(index,lib,b)
                for table,xs,ys in arc_tables(kind,ap,bp):
                    if not within(values,xs) or not within([loads[b]],ys):
                        errors.append(dict(sample=sample,input=a,output=b,table=table,
                            slew_ns=values,load_pf=loads[b],slew_axis=[xs[0],xs[-1]],load_axis=[ys[0],ys[-1]]))
        # Aperture is globally maximized, but it is still only characterized
        # within the data/clock slew axes. No out-of-table extrapolation credit.
        for dest in plan['targets']:
            cell,pin=dest.rsplit('/',1); kind=index.after['cells'][cell]['type']
            dv=slews[(sample,dest)];cv=slews[(sample,cell+'/CLK')]
            for table,xs,ys in hold_tables(kind,pin):
                if not within(dv,xs) or not within(cv,ys):
                    errors.append(dict(sample=sample,input=dest,output=cell+'/CLK',table=table,
                        slew_ns=dv,clock_slew_ns=cv,slew_axis=[xs[0],xs[-1]],clock_axis=[ys[0],ys[-1]]))
    return dict(checked_cell_arcs=len(checked),range_errors=errors)


def run(mapping, export, output, campaign=False, selected=None, period=1000):
    require(not output.exists(), 'FEEDBACK_OUTPUT_EXISTS')
    receipt = validate_receipt(mapping)
    record = json.loads((mapping/'mapping.json').read_text()); live = json.loads((mapping/'netlist.json').read_text())
    audit = json.loads((mapping/'netlist-audit.json').read_text())
    require(audit['status'] == 'pass' and audit['netlist_sha256'] == sha(mapping/'netlist.v'), 'FEEDBACK_STALE_AUDIT')
    require(sha(export/'contract.json') == sha(mapping/'timing-intent.json'), 'FEEDBACK_EXPORT_IDENTITY')
    manifest = json.loads((export/'contract.json').read_text())['manifest']
    inventory = sources.inventory(export, manifest['top'])
    original = stages.receipt_original(mapping, receipt); proof = stages.receipt_proof(mapping, receipt)
    index = leaf.LeafIndex(original, live, proof['added_buffers'], proof['added_ties'])
    plans = bind(inventory, record, audit, index); cuts = leaf.keeper_cuts(index, audit)
    require(selected is None or 0<=selected<len(plans),'FEEDBACK_GROUP_OUT_OF_RANGE')
    topology_lib=library(ROOT/'.tools/physical/pdk'/(SC+relative.CORNERS[0]+'.lib'))
    for plan in plans:
        bind_cone(plan,record,audit,index,topology_lib)
    sta = tool('sta'); corners = relative.CORNERS if campaign else relative.CORNERS[-1:]
    files = [mapping/f for f in ('mapping.json','netlist.json','netlist.v','netlist-audit.json','timing-intent.json',
        'electrical-repair/receipt.json','electrical-repair/proof.json','electrical-repair/reference/netlist.json')]
    files += [ROOT/'tools'/f for f in ('passive_feedback_hold.py','passive_source_inventory.py',
        'passive_constant_proof.py','native_allowance_audit.py','check_reset_crossings.py','gf180_physical.py','gf180_estimate.py',
        'native_stage_timing.py','native_leaf_timing.py','physical_tools.py','repair_gf180_design.py',
        'control_relative_timing.py','screen_gf180_control_repair.py','repair_gf180_control.py')]
    files += [ROOT/'.tools/physical/pdk'/(SC+c+'.lib') for c in corners]
    files += [ROOT/'.tools/gf180-sram'/(SRAM+'__tt_025C_3v30.lib')]+sta.input_files()
    frozen = {str(p.resolve()): sha(p) for p in files}; frozen.update(inventory['inputs_sha256'])
    output.mkdir(parents=True); write_json(output/'inventory.json', inventory); write_json(output/'plans.json', plans)
    write_json(output/'inputs.json',frozen)
    cases = []
    for corner in corners:
        lib = library(ROOT/'.tools/physical/pdk'/(SC+corner+'.lib')); aperture = hold_aperture(lib)
        for i, plan in enumerate(plans):
            if selected is not None and i != selected:
                continue
            envelope = slew_envelope(index, lib, plan['root'])
            tcl = output/(corner+'-'+str(i)+'.tcl'); log = tcl.with_suffix('.log')
            text, samples = script(mapping, corner, plan, envelope, cuts, sta, period)
            tcl.write_text(text, newline='\n'); error = None; rows = []
            try:
                with log.open('w') as stream:
                    subprocess.run(sta.command(['-no_init','-exit',sta.path(tcl)], timeout=300),
                        stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=310)
                rows, slews = parse(log.read_text(), plan, samples, aperture)
                ranges = table_ranges(rows,slews,index,lib,plan)
            except (ValueError, subprocess.SubprocessError) as exc:
                error = str(exc)
            case = dict(corner=corner, group=i, root=plan['root'], envelope=envelope,
                        maximum_liberty_hold_ns=aperture, samples=samples, rows=rows, error=error,
                        table_ranges=ranges if error is None else None,
                        minimum_hold_ns=min((r['slack_ns'] for r in rows), default=None),
                        minimum_selected_path_aperture_diagnostic_ns=min((r['selected_path_maximum_aperture_diagnostic_ns'] for r in rows), default=None),
                        evidence_sha256={str(p):sha(p) for p in (tcl,log)})
            cases.append(case); write_json(output/'cases.json', cases)
            print(corner, i, case['minimum_hold_ns'], error, flush=True)
    require(all(sha(Path(p)) == digest for p, digest in frozen.items()), 'FEEDBACK_INPUT_CHANGED')
    validate_receipt(mapping)
    expected={(c,i) for c in corners for i in range(len(plans)) if selected is None or selected==i}
    require({(c['corner'],c['group']) for c in cases}==expected and len(cases)==len(expected),'FEEDBACK_CASE_COVERAGE')
    report = dict(schema='riscay-passive-feedback-hold-v1', scope=__doc__, physical_qualification=False,
                  inputs_sha256=frozen, cases=cases, inventory_bank_count=inventory['self_or_same_event_capture_count'],
                  files_sha256={name:sha(output/name) for name in ('plans.json','inventory.json','inputs.json','cases.json')},
                  queried_banks=sorted({b for i,p in enumerate(plans) if selected is None or selected==i for b in p['banks']}),
                  full_corner_and_group_cohort=campaign and selected is None)
    write_json(output/'results.json', report)
    require(all(c['error'] is None and not c['table_ranges']['range_errors'] and
                c['minimum_hold_ns'] >= 0 for c in cases), 'FEEDBACK_HOLD_FAILED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mapping','export','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--campaign', action='store_true')
    parser.add_argument('--group', type=int)
    parser.add_argument('--period', type=float, default=1000.)
    args = parser.parse_args()
    run(args.mapping.resolve(), args.export.resolve(), args.output.resolve(), args.campaign, args.group, args.period)
