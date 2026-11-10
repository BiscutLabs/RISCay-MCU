# SPDX-License-Identifier: Apache-2.0
"""Partition proc/opt Yosys JSON by storage ownership and actual data fan-in.

Hierarchy is retained in identifiers. Vector combinational cells conservatively
depend on all their input bits; reset and external-input frontiers are separate.
This inventory is not a timing result or permission to remove a storage stage.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

FF = re.compile(r'\$(?:dff|dffe|adff|adffe|sdff|sdffe|sdffce)$')
# Only pure combinational proc/opt cells. Unknown generic cells fail instead of
# silently treating stateful $sr/$fsm (or formal $anyseq) as a logic gate.
COMBINATIONAL = frozenset('$' + name for name in (
    'add and eq ge gt le logic_and logic_not logic_or lt mux ne not or pmux '
    'reduce_and reduce_bool reduce_or reduce_xor reduce_xnor shift shiftx shl shr sshr sub xor xnor'
).split())


def flatten(modules, top):
    parent, cells, aliases = {}, {}, {}
    def find(x):
        p = parent.setdefault(x, x)
        if p != x:
            parent[x] = find(p)
        return parent[x]
    def join(a, b):
        a, b = find(a), find(b)
        if a == b:
            return
        if a[0] == b[0] == 'constant':
            raise ValueError('DESYNC_CONFLICTING_CONSTANTS')
        if a[0] == 'constant':
            parent[b] = a
        else:
            parent[a] = b
    def walk(kind, path, ports):
        module = modules[kind]
        def net(bit):
            return ('constant', bit) if isinstance(bit, str) else (path, bit)
        for name, port in module.get('ports', {}).items():
            if name in ports:
                if not ports[name] and port['direction'] == 'output':
                    continue
                if len(port['bits']) != len(ports[name]):
                    raise ValueError(f'DESYNC_PORT_WIDTH:{path}{name}:{len(port["bits"])}:{len(ports[name])}')
                for a, b in zip(port['bits'], ports[name]):
                    join(net(a), b)
        for name, wire in module.get('netnames', {}).items():
            aliases[path + name] = list(map(net, wire['bits']))
        for name, cell in module.get('cells', {}).items():
            connections = {p: list(map(net, bits)) for p, bits in cell['connections'].items()}
            target = modules.get(cell['type'])
            if target is not None and not int(target.get('attributes', {}).get('blackbox', '0'), 2):
                walk(cell['type'], path + name + '/', connections)
            else:
                cells[path + name] = dict(cell, connections=connections)
    walk(top, '', {})
    for cell in cells.values():
        cell['connections'] = {p: list(map(find, bits)) for p, bits in cell['connections'].items()}
    return cells, {n: list(map(find, bits)) for n, bits in aliases.items()}


def assign(path, names, policy):
    for rule in policy['rules']:
        if rule.get('alias') in names or ('prefix' in rule and path.startswith(rule['prefix'])):
            if rule['bank'] not in policy['banks']:
                raise ValueError('DESYNC_UNKNOWN_BANK')
            return rule['bank']
    raise ValueError('DESYNC_UNASSIGNED_REGISTER:' + path)


def partition(netlist, policy):
    if not 0 < len(policy['banks']) <= 10 or len(set(policy['banks'])) != len(policy['banks']):
        raise ValueError('DESYNC_BANK_INVENTORY')
    cells, aliases = flatten(netlist['modules'], policy['top'])
    if policy['stop_bank'] not in policy['banks']:
        raise ValueError('DESYNC_STOP_BANK')
    clocks = {}
    for name, domain in policy['clock_roots'].items():
        if name not in aliases or len(aliases[name]) != 1:
            raise ValueError('DESYNC_CLOCK_ROOT:' + name)
        bit = aliases[name][0]
        if bit in clocks and clocks[bit] != (domain, False):
            raise ValueError('DESYNC_CONFLICTING_CLOCK_ROOTS:' + name)
        clocks[bit] = (domain, False)
    for domain, name in policy['gated_domains'].items():
        if domain in policy['retained_domains'] or name not in aliases or len(aliases[name]) != 1:
            raise ValueError('DESYNC_GATE_CONDITION:' + name)
    # A pin-derived event can have an inverter before the FF clock. Never
    # traverse ordinary data gates or turn a data level into an inferred clock.
    changed = True
    while changed:
        changed = False
        for cell in cells.values():
            if cell['type'] == '$not' and len(cell['connections']['A']) == len(cell['connections']['Y']) == 1:
                a, y = cell['connections']['A'][0], cell['connections']['Y'][0]
                if a in clocks and y not in clocks:
                    domain, inverted = clocks[a]; clocks[y] = domain, not inverted; changed = True
    reverse = defaultdict(set)
    for name, bits in aliases.items():
        for bit in bits:
            reverse[bit].add(name)
    records, sources, drivers, macro_inputs = [], {}, {}, []
    top = netlist['modules'][policy['top']]
    external_inputs = {bit for name, port in top['ports'].items() if port['direction'] == 'input'
                       for bit in aliases[name]}
    for path, cell in cells.items():
        ports = cell['connections']
        if FF.fullmatch(cell['type']):
            clock = ports['CLK']
            if len(clock) != 1 or clock[0] not in clocks:
                raise ValueError('DESYNC_UNCLASSIFIED_CLOCK:' + path)
            domain, inversion = clocks[clock[0]]
            names = {n for bit in ports['Q'] for n in reverse[bit] if n.rpartition('/')[0] == path.rpartition('/')[0]}
            bank = assign(path, names, policy)
            active = domain not in policy['retained_domains']
            falling = not (bool(int(cell['parameters']['CLK_POLARITY'], 2)) ^ inversion)
            source = (bank if active else '@' + domain, 'fall' if falling else 'rise')
            for bit in ports['Q']:
                if bit in sources:
                    raise ValueError('DESYNC_MULTIPLE_STORAGE_DRIVERS')
                sources[bit] = source
            params = cell['parameters']
            reset = 'async' if 'ARST' in ports else 'sync' if 'SRST' in ports else 'none'
            inputs = [b for p, bs in ports.items() if p not in ('Q', 'CLK', 'ARST') for b in bs]
            records.append(dict(path=path, bank=bank, aliases=sorted(names), bits=len(ports['Q']),
                domain=domain, transformed=active, cell=cell['type'], reset=reset,
                falling=falling, inputs=inputs))
        elif cell['type'].startswith('gf180mcu_ocd_ip_sram__'):
            bank = assign(path, [], policy)
            for pin, bits in ports.items():
                if cell['port_directions'][pin] == 'output':
                    for bit in bits:
                        if bit in sources:
                            raise ValueError('DESYNC_MULTIPLE_STORAGE_DRIVERS')
                        sources[bit] = (bank, 'macro')
                elif pin != 'CLK':
                    macro_inputs.append((bank, path + '/' + pin, bits))
        else:
            if cell['type'] not in COMBINATIONAL:
                raise ValueError('DESYNC_UNSUPPORTED_CELL:' + cell['type'])
            inputs = {bit for p, bits in ports.items() if cell['port_directions'][p] == 'input' for bit in bits}
            for p, bits in ports.items():
                if cell['port_directions'][p] == 'output':
                    for bit in bits:
                        if bit in drivers:
                            raise ValueError('DESYNC_MULTIPLE_COMBINATIONAL_DRIVERS')
                        drivers[bit] = inputs
    if sources.keys() & drivers.keys():
        raise ValueError('DESYNC_MULTIPLE_MIXED_DRIVERS')
    def origins(bits):
        seen, pending, result = set(), list(bits), set()
        while pending:
            bit = pending.pop()
            if bit in seen or bit[0] == 'constant':
                continue
            seen.add(bit)
            if bit in sources:
                result.add(sources[bit])
            elif bit in drivers:
                pending.extend(drivers[bit])
            elif bit in external_inputs:
                result.add(('@external', 'external'))
            else:
                raise ValueError('DESYNC_UNDRIVEN_INPUT:' + repr(bit))
        return result
    edges, external, phase_edges = defaultdict(set), defaultdict(set), defaultdict(set)
    def add(bits, bank, phase, path, role):
        for source, source_phase in origins(bits):
            (external if source.startswith('@') else edges)[source, bank].add(path)
            phase_edges[source, source_phase, bank, phase, role].add(path)
    for row in records:
        inputs = row.pop('inputs')
        if row['transformed']:
            phase = 'fall' if row['falling'] else 'rise'
            add(inputs, row['bank'], phase, row['path'], 'data')
            if row['domain'] in policy['gated_domains']:
                add(aliases[policy['gated_domains'][row['domain']]], row['bank'], phase, row['path'], 'gate')
    for bank, path, bits in macro_inputs:
        add(bits, bank, 'macro', path, 'macro_input')
    summaries = {}
    for bank in policy['banks']:
        members = [r for r in records if r['bank'] == bank and r['transformed']]
        summaries[bank] = dict(bits=sum(r['bits'] for r in members), registers=len(members),
            reset_bits=dict(Counter({kind: sum(r['bits'] for r in members if r['reset'] == kind) for kind in ('none', 'sync', 'async')})),
            falling_bits=sum(r['bits'] for r in members if r['falling']))
    return dict(schema=1, scope='Generic proc/opt dependency inventory, before ordinary synthesis removes unused bits',
        banks=summaries, registers=records,
        edges=[dict(source=a, target=b, witnesses=sorted(w)) for (a, b), w in sorted(edges.items())],
        phase_edges=[dict(source=a, source_phase=ap, target=b, target_phase=bp, role=role, witnesses=sorted(w))
                     for (a, ap, b, bp, role), w in sorted(phase_edges.items())],
        external=[dict(source=a, target=b, witnesses=sorted(w)) for (a, b), w in sorted(external.items())],
        gated_domains=policy['gated_domains'], stop_bank=policy['stop_bank'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist', type=Path); parser.add_argument('bank_map', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = partition(json.loads(args.netlist.read_text()), json.loads(args.bank_map.read_text()))
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(banks=result['banks'], edges=[(r['source'], r['target']) for r in result['edges']]), indent=2))
