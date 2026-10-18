# SPDX-License-Identifier: Apache-2.0
"""Mapped periodic clock sinks by RTL owner, including inlined Services state.

Attribution uses a sink's own hierarchy and local Q aliases, never a downstream
consumer's aliases. Unattributed platform state stays explicit. This is an area
inventory, not clock-tree, CDC or timing qualification.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

from gf180_estimate import groups, scalar
from gf180_netgraph import graph
from gf180_physical import ROOT, SC, SRAM, sha, write_json

ROOTS = {'serviceClock': 'service', 'soc/gate_io_clockOut': 'work',
         'watchdogClock': 'lf', 'sda': 'host_event'}
PERIODIC = ('service', 'work', 'lf')


def clock_nets(cells, aliases):
    clocks = {}
    for name, domain in ROOTS.items():
        bits = aliases[name]
        if len(bits) != 1 or bits[0] in clocks:
            raise ValueError('CLOCK_OWNER_ROOT_ALIAS')
        clocks[bits[0]] = domain
    changed = True
    while changed:
        changed = False
        for c in cells.values():
            if not c['type'].removeprefix(SC).startswith(('buf_', 'clkbuf_', 'inv_', 'clkinv_')):
                continue
            p = c['connections']; source = p['I'][0]; dest = p.get('Z', p.get('ZN'))[0]
            if source not in clocks:
                continue
            if dest in clocks and clocks[dest] != clocks[source]:
                raise ValueError('CLOCK_OWNER_MULTIPLE_DOMAINS')
            if dest not in clocks:
                clocks[dest] = clocks[source]; changed = True
    return clocks


def owner(path, local_aliases):
    parent = path.rsplit('/', 1)[0] if '/' in path else ''
    if path.startswith('soc/fabric_'):
        return 'Services'
    if parent == 'soc':
        for prefix, label in (('fabric_', 'Services'), ('timebase_', 'LF timebase'),
                              ('watchdog_', 'Watchdog'), ('resetBoundary_', 'Reset coordinator'),
                              ('gate_', 'Work clock gate')):
            if any(a.startswith('soc/' + prefix) and not a.startswith('soc/' + prefix + 'io_')
                   for a in local_aliases):
                return label
        return 'Platform (unattributed)'
    return parent or 'Top'


def inventory(cells, aliases, pins, original_cells=None, original_aliases=None):
    missing = {c['type'] for c in cells.values()} - pins.keys()
    if missing:
        raise ValueError('CLOCK_OWNER_MISSING_LIBRARY_CELL: ' + ','.join(sorted(missing)))
    clocks = clock_nets(cells, aliases)
    original_cells = original_cells or cells
    original_aliases = original_aliases or aliases
    originals = {n.replace('\\', ''): c for n, c in original_cells.items()}
    reverse = defaultdict(set)
    for name, bits in original_aliases.items():
        for bit in set(bits):
            reverse[bit].add(name)
    rows = []; other = []
    for path, c in sorted(cells.items()):
        for pin, capacitance in pins.get(c['type'], {}).items():
            domain = clocks.get(c['connections'][pin][0])
            if domain is None:
                # Preserve all unresolved pins. Native storage is expected here,
                # but a new clock gate must not silently vanish from inventory.
                other.append(dict(path=path, clock_pin=pin, cell=c['type']))
                continue
            parent = path.rsplit('/', 1)[0] if '/' in path else ''
            original = originals.get(path.replace('\\', ''))
            if original is None:
                raise ValueError('CLOCK_OWNER_ADDED_SEQUENTIAL_CELL')
            outputs = [bit for p, bits in original['connections'].items()
                       if original['port_directions'][p] == 'output' for bit in bits]
            local = sorted({name for bit in outputs for name in reverse[bit]
                            if name.rpartition('/')[0] == parent})
            rows.append(dict(path=path, clock_pin=pin, cell=c['type'], domain=domain,
                             owner=owner(path, local), state_aliases=local,
                             clock_input_pf=capacitance))
    totals = Counter(r['domain'] for r in rows)
    owners = {}
    for r in rows:
        counts = owners.setdefault(r['owner'], {d: 0 for d in (*PERIODIC, 'host_event')})
        counts[r['domain']] += 1
    return dict(periodic_sinks=sum(totals[d] for d in PERIODIC),
                periodic_macro_pins=sum(r['cell'] == SRAM and r['domain'] in PERIODIC for r in rows),
                native_or_unclassified_clock_sinks=len(other), other_clock_sinks=other,
                clock_domains={d: totals[d] for d in (*PERIODIC, 'host_event')},
                owners=dict(sorted(owners.items())), sinks=rows)


def register_breakdown(sinks, selected_owner):
    """Partition by local Q aliases, retaining ambiguity without double counting.

    Aliases may overlap after synthesis. Each physical sink contributes exactly
    once to its complete alias set; an unnamed register stays explicitly named
    by its cell path rather than disappearing from the totals.
    """
    grouped = {}
    for sink in sinks:
        if sink['owner'] != selected_owner:
            continue
        aliases = tuple(sink['state_aliases'])
        identity = aliases or (sink['path'],)
        key = sink['domain'], identity
        row = grouped.setdefault(key, dict(domain=sink['domain'], aliases=list(aliases),
            identity=list(identity), sinks=0, clock_input_pf=0.0, cells=[]))
        row['sinks'] += 1
        row['clock_input_pf'] += sink['clock_input_pf']
        row['cells'].append(sink['path'])
    return sorted(grouped.values(), key=lambda r: (-r['sinks'], r['domain'], r['identity']))


def report(mapping, output, register_owner=None):
    netlist = mapping / 'netlist.json'
    reference = mapping / 'electrical-repair/reference/netlist.json'
    libraries = [ROOT / '.tools/physical/pdk' / (SC + 'tt_025C_3v30.lib'),
                 ROOT / '.tools/gf180-sram' / (SRAM + '__tt_025C_3v30.lib')]
    inputs = [netlist, reference, *libraries, Path(__file__), ROOT / 'tools/gf180_netgraph.py']
    hashes = {str(p.resolve()): sha(p) for p in inputs}
    cells, aliases = graph(json.loads(netlist.read_text())['modules'])
    used = {c['type'] for c in cells.values()}
    pins = {kind: {pin: scalar(body, 'capacitance') for pin, body in groups(cell, 'pin')
                   if re.search(r'\bclock\s*:\s*true\s*;', body)}
            for lib in libraries for kind, cell in groups(lib.read_text(), 'cell') if kind in used}
    original_cells, original_aliases = graph(json.loads(reference.read_text())['modules'])
    result = inventory(cells, aliases, pins, original_cells, original_aliases)
    if register_owner is not None:
        if register_owner not in result['owners']:
            raise ValueError('CLOCK_OWNER_UNKNOWN_OWNER: ' + register_owner)
        result['register_owner'] = register_owner
        result['registers'] = register_breakdown(result['sinks'], register_owner)
    result['scope'] = 'Mapped clock connectivity and local storage aliases; not timing qualification'
    result['inputs_sha256'] = hashes
    if any(sha(Path(p)) != h for p, h in hashes.items()):
        raise ValueError('CLOCK_OWNER_INPUT_CHANGED')
    if output.exists():
        raise ValueError('CLOCK_OWNER_OUTPUT_EXISTS')
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, result)
    return {k: v for k, v in result.items() if k not in ('sinks', 'other_clock_sinks', 'inputs_sha256')}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mapping', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--registers', metavar='OWNER', help='rank local register alias sets for this owner')
    a = p.parse_args()
    print(json.dumps(report(a.mapping, a.output, a.registers), indent=2))
