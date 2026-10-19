# SPDX-License-Identifier: Apache-2.0
"""Conditional transistor keeper experiment with extracted inter-cell RC.

A selected internal victim has its actual transistor driver and receivers, and
the complete mapped owner retains its feedback. Boundary inputs and external
aggressors are ideal stimuli; external sink loads use actual PVT Liberty caps.
This is a representative experiment, not receiver-noise or physical signoff.
"""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re
import subprocess

from characterize_gf180_keeper import CORNERS
from check_gf180_cells import vectors
from check_gf180_coupling import read_spef, rank, simulator, unescape, require
from gf180_estimate import direct_groups, library, linux, scalar
from gf180_physical import ROOT, SC, pdk_verify, sha, write_json
from native_routing import read_report
from run_receipt import RunReceipt

LIB_CORNERS = dict(tt='tt_025C_3v30', ss_hot='ss_125C_3v00', ss_cold='ss_n40C_3v00',
                   ff_hot='ff_125C_3v60', ff_cold='ff_n40C_3v60')
LIMITS = [
    'Selected owner and two histories of one holding input condition, not all protocol states',
    'Ideal primary-input boundaries and coherent local full-rail aggressor stimuli; no aggressor-driver timing proof',
    'External sink loads are actual PVT Liberty pin capacitances, not nonlinear external receivers',
    'Schematic transistor cells omit extracted cell-internal RC; supplied MOS diffusion areas/perimeters default to zero',
    'Deterministic PVT only: no statistical mismatch, metastability, power-grid noise or reset-distribution qualification',
    '50% VDD marks an observed owner transition; it is not a characterized input-noise immunity threshold',
    '10%/90% rail windows check simulation settling only; they are not device noise-immunity specifications',
]


def connectivity(path):
    """Read the same named OpenDB inventory already bound by the P&R proof."""
    cells, nets = {}, defaultdict(list)
    with Path(path).open() as stream:
        for line in stream:
            row = line.rstrip('\n').split('\t')
            if row[0] == 'C':
                name = unescape(row[1])
                require(len(row) == 3 and name not in cells, 'KEEPER_CELL_INVENTORY')
                cells[name] = dict(master=row[2], pins={}, directions={})
            elif row[0] == 'P':
                require(len(row) == 5 and row[3] in ('input', 'output'), 'KEEPER_PIN_INVENTORY')
                name, pin, net = unescape(row[1]), row[2], unescape(row[4])
                require(name in cells and pin not in cells[name]['pins'], 'KEEPER_PIN_INVENTORY')
                cells[name]['pins'][pin] = net; cells[name]['directions'][pin] = row[3]
                nets[net].append(dict(pin=name+':'+pin, direction=row[3], master=cells[name]['master'], port=pin))
            elif row[0] == 'T':
                require(len(row) == 4, 'KEEPER_PORT_INVENTORY')
                nets[unescape(row[3])].append(dict(pin=unescape(row[1]), direction=row[2], master=None, port=row[1]))
            else:
                raise ValueError('KEEPER_INVENTORY_ROW')
    require(cells and nets, 'KEEPER_EMPTY_INVENTORY')
    return cells, dict(nets)


def holding_sequences(binding):
    """Reuse the independently tested Gray walk; never force keeper state."""
    k = binding['parameters']; events = vectors(binding); pairs = defaultdict(dict)
    for index, (inputs, q) in enumerate(events):
        normalized = {p: inputs[p] ^ k[p.upper()+'_INVERT'] for p in ('common', 'rising', 'falling')}
        set_bit = normalized['common'] == (1 << k['COMMON'])-1 and normalized['rising'] == (1 << k['RISING'])-1
        hold = bool(normalized['common'] or normalized['falling'])
        if not inputs['reset'] and not set_bit and hold:
            pairs[tuple(sorted(inputs.items()))].setdefault(q, index)
    complete = [(key, value) for key, value in pairs.items() if set(value) == {0, 1}]
    require(complete, 'KEEPER_TWO_RETAINED_HISTORIES_REQUIRED')
    selected, indices = min(complete, key=lambda item: (max(item[1].values()), item[0]))
    return dict(inputs=dict(selected), available_holding_conditions=len(complete),
                sequences={str(q): events[:indices[q]+1] for q in (0, 1)})


def bind_owner(record, audit, cells, nets, owner, victim):
    bindings = [b for b in record['bindings'] if owner in b['instances']]
    require(len(bindings) == 1 and bindings[0]['model'] == 'ChiselAsyncAsymmetricC_v1', 'KEEPER_OWNER_KIND')
    binding = bindings[0]; root = unescape(audit['adapter_instances'][owner])
    selected = {}; logical = defaultdict(set)
    for cell in binding['cells']:
        name = root+'/'+cell['name']
        require(name in cells and cells[name]['master'] == cell['cell'] and
                set(cells[name]['pins']) == set(cell['pins']), 'KEEPER_ACTUAL_CELL_MISMATCH')
        selected[name] = cells[name]
        for pin, net in cell['pins'].items(): logical[net].add(cells[name]['pins'][pin])
    require(all(len(values) == 1 for values in logical.values()), 'KEEPER_INTERNAL_REPAIR_REQUIRES_EXPLICIT_CLUSTER')
    logical = {key: next(iter(values)) for key, values in logical.items()}
    own_pins = {name+':'+pin for name, cell in selected.items() for pin in cell['pins']}
    victim = unescape(victim)
    require(victim in logical.values() and all(t['pin'] in own_pins for t in nets[victim]), 'KEEPER_VICTIM_NOT_INTERNAL')
    require(sum(t['direction'] == 'output' for t in nets[victim]) == 1 and len(nets[victim]) > 1,
            'KEEPER_VICTIM_DRIVER_RECEIVERS')
    # Reject an unnoticed merge of distinct adapter signals or an external feedback cut.
    require(len(set(logical.values())) == len(logical), 'KEEPER_LOGICAL_NET_ALIAS')
    inputs = {p['name']: p['width'] for p in binding['ports'] if p['direction'] == 'input'}
    boundaries = {}
    for local, net in logical.items():
        match = re.fullmatch(r'(\w+)\[(\d+)\]', local)
        port, bit = (match[1], int(match[2])) if match else (local, 0)
        if port in inputs:
            require(bit < inputs[port], 'KEEPER_INPUT_BIT')
            boundaries[net] = (port, bit)
        elif local != 'q':
            require(all(t['pin'] in own_pins for t in nets[net]), 'KEEPER_EXTERNAL_INTERNAL_NET')
    require('q' in logical and 'state' in logical, 'KEEPER_STATE_OUTPUT_REQUIRED')
    return dict(owner=owner, victim=victim, cells=selected, logical=logical, boundaries=boundaries,
                terminals={n: nets[n] for n in logical.values()}, holding=holding_sequences(binding))


def eligible_hotspots(record, audit, cells, nets, hotspots):
    """Rank measured eligible internal victims by external coupling capacitance.

    Internal feedback coupling is simulated, but does not count as an unrelated
    switching aggressor when selecting the representative keeper experiment.
    """
    ranking = {unescape(row['net']): row for row in hotspots}; result = []; rejected = []
    require(len(ranking) == len(hotspots), 'KEEPER_HOTSPOT_NAME_COLLISION')
    for binding in record['bindings']:
        if binding['model'] != 'ChiselAsyncAsymmetricC_v1': continue
        for owner in binding['instances']:
            root = unescape(audit['adapter_instances'][owner])
            names = [root+'/'+c['name'] for c in binding['cells']]
            require(all(name in cells for name in names), 'KEEPER_SELECTION_OWNER_MISSING')
            owner_nets = {n for name in names for n in cells[name]['pins'].values()}
            own_pins = {name+':'+pin for name in names for pin in cells[name]['pins']}
            candidates = [n for n in owner_nets & ranking.keys() if len(nets[n]) > 1 and
                          all(t['pin'] in own_pins for t in nets[n])]
            if not candidates: continue
            try: bind_owner(record,audit,cells,nets,owner,sorted(candidates)[0])
            except ValueError as error:
                rejected.append(dict(owner=owner,reason=str(error))); continue
            for net in candidates:
                row = ranking[net]
                external = sum(a['coupling_pf'] for a in row['aggressors'] if unescape(a['net']) not in owner_nets)
                if external > 0:
                    result.append(dict(owner=owner,net=row['net'],external_coupling_pf=external,
                                       total_coupling_pf=row['coupling_pf'],ground_pf=row['ground_pf']))
    result.sort(key=lambda row:(-row['external_coupling_pf'],row['owner'],row['net']))
    return dict(ranked=result,rejected_owners=rejected,criterion='largest measured external coupling among eligible internal keeper-owner nets')


def bind_networks(plan, parsed):
    require(not parsed['missing'], 'KEEPER_MISSING_EXTRACTED_NET')
    networks = parsed['networks']; own_pins = {n+':'+p for n,c in plan['cells'].items() for p in c['pins']}
    internal = Counter((net,other,a,b,cap) for net,data in networks.items()
                       for a,b,cap,other in data['coupling'] if other in networks)
    require(all(internal[other,net,b,a,cap] == count for (net,other,a,b,cap),count in internal.items()),
            'KEEPER_NONRECIPROCAL_INTERNAL_COUPLING')
    pin_nodes = {}; external_loads = {}; boundary_drivers = {}
    for net, data in networks.items():
        actual = {t['pin']: t for t in plan['terminals'][net]}
        require(len(actual) == len(data['connections']) and set(actual) == {c['pin'] for c in data['connections']},
                'KEEPER_SPEF_TERMINAL_MISMATCH')
        drivers = []
        for connection in data['connections']:
            pin = connection['pin']; term = actual[pin]
            is_driver = term['direction'] == ('input' if term['master'] is None else 'output')
            require(connection['direction'] == ('O' if is_driver and term['master'] else 'I' if is_driver else
                    'I' if term['master'] else 'O'), 'KEEPER_SPEF_PIN_DIRECTION')
            require(pin not in pin_nodes, 'KEEPER_MULTINET_PIN'); pin_nodes[pin] = connection['node']
            if is_driver: drivers.append(pin)
            elif pin not in own_pins:
                require(term['master'] is not None, 'KEEPER_TOP_OUTPUT_LOAD_UNKNOWN')
                external_loads[connection['node']] = term
        require(len(drivers) == 1, 'KEEPER_NET_DRIVER_COUNT')
        if net in plan['boundaries']:
            require(drivers[0] not in own_pins, 'KEEPER_BOUNDARY_DRIVER_INTERNAL')
            boundary_drivers[net] = pin_nodes[drivers[0]]
        else: require(drivers[0] in own_pins, 'KEEPER_OWNER_DRIVER_EXTERNAL')
        require(all(r > 0 for _,_,r in data['resistors']), 'KEEPER_ZERO_RESISTOR')
    nodes = set(pin_nodes.values())
    for data in networks.values():
        nodes.update(data['ground'])
        for a,b,_ in data['resistors']: nodes.update((a,b))
    require(len(nodes) <= 4000 and len(plan['cells']) <= 128, 'KEEPER_CLUSTER_BOUND')
    require(set(own_pins) <= set(pin_nodes), 'KEEPER_OWN_PIN_COVERAGE')
    return dict(networks=networks, labels={n:'n'+str(i) for i,n in enumerate(sorted(nodes))},
                pin_nodes=pin_nodes, external_loads=external_loads, boundary_drivers=boundary_drivers)


def external_caps(cluster, lib):
    result = {}
    for node, term in cluster['external_loads'].items():
        require(term['master'] in lib, 'KEEPER_EXTERNAL_MASTER_NOT_LOADED')
        pins = dict(direct_groups(lib[term['master']], 'pin'))
        require(term['port'] in pins, 'KEEPER_EXTERNAL_LIBERTY_PIN')
        cap = scalar(pins[term['port']], 'capacitance')
        require(math.isfinite(cap) and cap >= 0, 'KEEPER_EXTERNAL_PIN_CAP')
        result[node] = cap
    return result


def deck(plan, cluster, pdk, corner, caps, history, slew, edge, *, step_scale=1.):
    """External coupling pairs are local sources; internal reciprocal rows count once."""
    _, model, temp, vdd = corner; labels = cluster['labels']; networks = cluster['networks']
    orders = {m[0]: m[1].split() for m in re.findall(r'^\.SUBCKT\s+(\S+)\s+([^\r\n]+)',
                (pdk/'gf180mcu_fd_sc_mcu7t5v0.spice').read_text(), re.M|re.I)}
    text = 'Conditional routed-wire transistor keeper experiment\n'
    text += f'.include "{linux(pdk/"design.ngspice")}"\n.lib "{linux(pdk/"sm141064.ngspice")}" {model}\n'
    text += f'.include "{linux(pdk/"gf180mcu_fd_sc_mcu7t5v0.spice")}"\n'
    text += f'.param sw_stat_global=0 sw_stat_mismatch=0\n.temp {temp}\nVDD vdd 0 {vdd}\n'
    for i,(name, cell) in enumerate(plan['cells'].items()):
        pins = {p: labels[cluster['pin_nodes'][name+':'+p]] for p in cell['pins']}
        pins.update(VDD='vdd', VNW='vdd', VPW='0', VSS='0')
        require(set(pins) == set(orders[cell['master']]), 'KEEPER_SPICE_PIN_SET')
        text += 'X'+str(i)+' '+' '.join(pins[p] for p in orders[cell['master']])+' '+cell['master']+'\n'
    events = plan['holding']['sequences'][str(history)]
    perturb = len(events)*100.+50.; end = perturb+100.
    for i,(net, (port, bit)) in enumerate(plan['boundaries'].items()):
        points = []; old = None
        for index,(inputs,_) in enumerate(events):
            value = ((inputs[port] >> bit)&1)*vdd
            if old is None: points.append(f'0 {value}')
            elif value != old: points.extend((f'{index*100}n {old}', f'{index*100+.2}n {value}'))
            old = value
        text += f'VIN{i} {labels[cluster["boundary_drivers"][net]]} 0 PWL('+ ' '.join(points)+')\n'
    active = {c[3] for c in networks[plan['victim']]['coupling'] if c[3] not in networks}
    require(active, 'KEEPER_NO_EXTERNAL_VICTIM_COUPLING')
    aggs = sorted({c[3] for d in networks.values() for c in d['coupling'] if c[3] not in networks})
    sources = {n:'ag'+str(i) for i,n in enumerate(aggs)}
    for i,net in enumerate(aggs):
        first = vdd if edge == 'fall' else 0.; last = vdd-first
        wave = f'PWL(0 {first} {perturb}n {first} {perturb+slew}n {last})' if net in active and edge != 'quiet' else str(first)
        text += f'VAG{i} {sources[net]} 0 {wave}\n'
    resistors = []; capacitors = []
    for net, data in networks.items():
        resistors += [(labels[a], labels[b], r) for a,b,r in data['resistors']]
        capacitors += [(labels[n], '0', c) for n,c in data['ground'].items() if c]
        for a,b,cap,other in data['coupling']:
            if other in networks:
                if net < other: capacitors.append((labels[a], labels[b], cap))
            else: capacitors.append((labels[a], sources[other], cap))
    capacitors += [(labels[n], '0', c) for n,c in caps.items() if c]
    for i,(a,b,r) in enumerate(resistors): text += f'R{i} {a} {b} {r:.12g}\n'
    for i,(a,b,c) in enumerate(capacitors): text += f'C{i} {a} {b} {c:.12g}p\n'
    output = next(t['pin'] for t in plan['terminals'][plan['logical']['q']] if t['direction'] == 'output')
    state = next(t['pin'] for t in plan['terminals'][plan['logical']['state']] if t['direction'] == 'output')
    observed = dict(q=labels[cluster['pin_nodes'][output]], state=labels[cluster['pin_nodes'][state]])
    observed.update({'victim'+str(i):labels[c['node']] for i,c in enumerate(networks[plan['victim']]['connections'])})
    step = .02*step_scale
    # Force fine integration breakpoints only near the disturbance. This uses
    # the existing controller harness's isolated numerical PWL technique;
    # numerical_mesh has no connection to the DUT and is not a hardware clock.
    fine = min(.02, slew/20)*step_scale
    if edge != 'quiet' and fine < step:
        begin, finish = perturb-1., perturb+slew+20.
        points = ['0 0']+[f'{begin+i*fine:.9f}n {i%2*1e-12:.1g}' for i in range(math.ceil((finish-begin)/fine)+1)]
        text += 'VNUM numerical_mesh 0 PWL('+' '.join(points)+')\n'
    text += '.save '+' '.join('v('+n+')' for n in set(observed.values()))+'\n'
    text += f'.tran {step}n {end}n 0 {step}n\n'
    for key,node in observed.items():
        text += f'.meas tran {key}_before FIND v({node}) AT={perturb-5}n\n'
        text += f'.meas tran {key}_after FIND v({node}) AT={end-1}n\n'
        for op in ('min','max'):
            text += f'.meas tran {key}_{op} {op.upper()} v({node}) FROM={perturb-1}n TO={end}n\n'
    text += '.end\n'
    return text, observed


def evaluate(log, observed, expected, voltage):
    matches = re.findall(r'^(\w+_(?:before|after|min|max))\s*=\s*([-+.0-9eE]+)', log, re.M)
    values = {k:float(v) for k,v in matches}
    require(len(matches) == len(values) and set(values) == {k+'_'+s for k in observed for s in ('before','after','min','max')} and
            all(math.isfinite(v) for v in values.values()), 'KEEPER_MEASUREMENTS_INCOMPLETE')
    require(all(values[k+'_min'] <= values[k+'_max'] for k in observed), 'KEEPER_MEASUREMENTS_REVERSED')
    unsettled = []
    for key in ('q', 'state'):
        v = values[key+'_before']
        require((v >= .9*voltage if expected else v <= .1*voltage) and -.1*voltage <= v <= 1.1*voltage,
                'KEEPER_INITIAL_HISTORY_UNSETTLED')
        final = values[key+'_after']
        if not (-.1*voltage <= final <= 1.1*voltage and (final <= .1*voltage or final >= .9*voltage)):
            unsettled.append(key)
    # Crossing this output marker is an explicit failed event observation.
    crossings = [k for k in ('q','state') if
                   (values[k+'_min'] < .5*voltage if expected else values[k+'_max'] > .5*voltage)]
    retained_changed = (values['state_after'] < .5*voltage if expected else values['state_after'] > .5*voltage)
    transitions = (['q'] if 'q' in crossings else []) + (['retained-state'] if retained_changed else [])
    excursion = max(max(abs(values[k+'_min']-values[k+'_before']), abs(values[k+'_max']-values[k+'_before'])) for k in observed)
    return dict(verdict='observed-spurious-owner-transition' if transitions else 'unresolved-final-state' if unsettled else 'analog-excursion-only',
                transition_nodes=transitions, internal_state_marker_crossed='state' in crossings,
                retained_state_changed=retained_changed, values=values, maximum_excursion_v=excursion,
                final_state_settled=not unsettled, unsettled_nodes=unsettled,
                owner_excursion_v=max(abs(values['q_min']-expected*voltage), abs(values['q_max']-expected*voltage)),
                physical_qualification=False)


def run(mapping, routed, out, owner, victim, campaign=False, wire_corners=('min','max')):
    from gf180_pnr import validate_provenance, rc_inputs
    require(not out.exists(), 'KEEPER_OUTPUT_EXISTS')
    meta = validate_provenance(mapping, routed, 'extract')
    require(wire_corners and len(set(wire_corners)) == len(wire_corners), 'KEEPER_RC_SELECTION')
    views = {rc:rc_inputs(mapping,routed,rc) for rc in wire_corners}
    pdk = ROOT/'.tools/physical/pdk'; pdk_verify(pdk)
    record = json.loads((mapping/'mapping.json').read_text()); audit = json.loads((mapping/'netlist-audit.json').read_text())
    manifest = json.loads((routed/'native-routing.json').read_text())
    routing = read_report(routed/'route-native-routing.tsv', [r['pin'] for r in manifest['anchors']])
    require(victim in routing['nets'], 'KEEPER_VICTIM_NOT_NATIVE_ROUTED_NET')
    cells,nets = connectivity(routed/'global-repair-after.tsv'); plan = bind_owner(record,audit,cells,nets,owner,victim)
    command, tool = simulator(); require(command is not None, 'KEEPER_NGSPICE_REQUIRED')
    corners = CORNERS if campaign else CORNERS[:1]
    files = [mapping/'mapping.json',mapping/'netlist-audit.json',routed/'run.json',routed/'global-repair-after.tsv',
             routed/'native-routing.json',routed/'route-native-routing.tsv',ROOT/'physical/gf180/pdk-lock.json',
             *[p for pair in views.values() for p in pair],
             *[pdk/n for n in ('design.ngspice','sm141064.ngspice','gf180mcu_fd_sc_mcu7t5v0.spice')],
             *[pdk/(SC+LIB_CORNERS[c[0]]+'.lib') for c in corners]]
    sources = [ROOT/'tools'/n for n in ('check_gf180_keeper_coupling.py','check_gf180_coupling.py','check_gf180_cells.py',
               'characterize_gf180_keeper.py','native_routing.py','gf180_estimate.py','gf180_physical.py','gf180_pnr.py','run_receipt.py')]
    receipt = RunReceipt(out/'receipt.json', inputs=files, tools=sources); status = 'fail'; cases = []; convergence = []
    out.mkdir(parents=True)
    try:
        write_json(out/'plan.json',plan); write_json(out/'simulator.json',tool)
        def experiment(cluster, corner, caps, history, slew, edge, key, step_scale=1.):
            text, observed = deck(plan,cluster,pdk,corner,caps,history,slew,edge,step_scale=step_scale)
            path = out/(key+'.spice'); path.write_text(text)
            try:
                process = subprocess.run(command+['-n','-b',linux(path) if command[0]=='wsl' else str(path)],
                                         capture_output=True,text=True,timeout=120)
            except subprocess.TimeoutExpired as error:
                (out/(key+'.log')).write_text(str(error)+'\n'+str(error.stdout or '')+'\n'+str(error.stderr or ''))
                raise ValueError('KEEPER_NGSPICE_TIMEOUT_'+key) from error
            log = process.stdout+process.stderr; (out/(key+'.log')).write_text(log)
            require(process.returncode == 0, 'KEEPER_NGSPICE_FAILED_'+key)
            result = evaluate(log,observed,history,corner[3])
            result.update(case=key,history=history,slew_ns=slew,edge=edge,corner=corner[0],
                          deck_sha256=sha(path),log_sha256=sha(out/(key+'.log')))
            return result
        for rc,(_,spef) in views.items():
            parsed = read_spef(spef,set(plan['logical'].values())); cluster = bind_networks(plan,parsed)
            write_json(out/(rc+'-cluster.json'),dict(cluster=cluster,hotspot=rank(cluster['networks'][plan['victim']],3.3)))
            for corner in corners:
                caps = external_caps(cluster,library(pdk/(SC+LIB_CORNERS[corner[0]]+'.lib')))
                write_json(out/(rc+'-'+corner[0]+'-external-caps.json'),caps)
                rows = []
                for history in (0,1):
                    for slew,edge in [(.02,'quiet'), *[(s,e) for s in (.02,2.) for e in ('rise','fall')]]:
                        key = f'{rc}-{corner[0]}-h{history}-s{slew}-{edge}'
                        result = experiment(cluster,corner,caps,history,slew,edge,key); result['wire_corner'] = rc
                        cases.append(result); rows.append(result)
                        write_json(out/(key+'.json'),result)
                        require(result['final_state_settled'], 'KEEPER_FINAL_STATE_UNRESOLVED')
                        if edge == 'quiet': require(not result['transition_nodes'], 'KEEPER_QUIET_CONTROL_TRANSITION')
                # Refine the largest input excursion and the largest owner disturbance at every PVT/RC.
                worst = {max(rows,key=lambda r:r[field])['case'] for field in ('maximum_excursion_v','owner_excursion_v')}
                worst |= {r['case'] for r in rows if r['transition_nodes']}
                for row in rows:
                    if row['case'] not in worst: continue
                    refined = experiment(cluster,corner,caps,row['history'],row['slew_ns'],row['edge'],row['case']+'-halfstep',.5)
                    difference = max(abs(v-refined['values'][k]) for k,v in row['values'].items())
                    ok = refined['final_state_settled'] and difference <= max(.001,.01*max(row['maximum_excursion_v'],refined['maximum_excursion_v'])) and row['verdict'] == refined['verdict']
                    convergence.append(dict(case=row['case'],maximum_voltage_difference_v=difference,within_tolerance=ok,refined=refined))
                    require(ok, 'KEEPER_TIMESTEP_UNRESOLVED')
        require(simulator()[1] == tool, 'KEEPER_SIMULATOR_CHANGED')
        validate_provenance(mapping,routed,'extract')
        failed = any(c['transition_nodes'] for c in cases)
        write_json(out/'results.json',dict(status='observed-spurious-owner-transition' if failed else 'representative-no-transition-observed',
            physical_qualification=False,owner=owner,victim=victim,cases=cases,convergence=convergence,limits=LIMITS))
        require(not failed, 'KEEPER_OBSERVED_SPURIOUS_OWNER_TRANSITION')
        status = 'pass'
    finally:
        receipt.finish(outputs=[p for p in out.rglob('*') if p.is_file()],status=status)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('mapping','routed','output'): p.add_argument(name,type=Path)
    p.add_argument('--owner',required=True); p.add_argument('--victim',required=True)
    p.add_argument('--campaign',action='store_true')
    p.add_argument('--wire-corner',choices=('min','max','nom'),action='append')
    a = p.parse_args(); run(a.mapping.resolve(),a.routed.resolve(),a.output.resolve(),a.owner,a.victim,a.campaign,a.wire_corner or ('min','max'))
