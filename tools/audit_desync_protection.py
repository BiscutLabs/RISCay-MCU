# SPDX-License-Identifier: Apache-2.0
"""Reject protected ordinary data and damaged registered primitive recipes."""
import argparse
import json
from pathlib import Path
from gf180_netgraph import graph
from primitives import classified_cells


def enabled(attributes):
    return any(str(attributes.get(k, '0')).strip('0') for k in ('keep', 'dont_touch'))


def audit(netlist, bindings=(), clock_aliases=()):
    cells, _ = graph(netlist['modules'])
    registered = classified_cells(bindings)
    for path, (_, expected) in registered.items():
        actual = cells.get(path)
        if actual is None or actual['type'] != expected['cell']:
            raise ValueError('DESYNC_PRIMITIVE_MISSING_OR_CHANGED:' + path)
    protected = []
    # Map is flat apart from registered primitives. Audit attributes before the
    # Verilog writer removes them; ordinary FFs must remain optimizable.
    def walk(kind, prefix=''):
        module = netlist['modules'][kind]
        if enabled(module.get('attributes', {})) and prefix.rstrip('/') not in {b['instance'] for b in bindings}:
            raise ValueError('DESYNC_PROTECTED_ORDINARY_MODULE:' + kind)
        for name, net in module.get('netnames', {}).items():
            path = prefix + name
            inside = any(path.startswith(b['instance'] + '/') for b in bindings)
            if enabled(net.get('attributes', {})) and not inside and path not in clock_aliases:
                raise ValueError('DESYNC_PROTECTED_DATA_NET:' + path)
        for name, cell in module.get('cells', {}).items():
            path = prefix + name
            if enabled(cell.get('attributes', {})):
                if path not in registered and path not in {b['instance'] for b in bindings}:
                    raise ValueError('DESYNC_PROTECTED_ORDINARY_CELL:' + path)
                protected.append(path)
            if cell['type'] in netlist['modules'] and not netlist['modules'][cell['type']].get('attributes', {}).get('blackbox'):
                walk(cell['type'], path + '/')
    walk('RiscayMcuDigital')
    for path in registered:
        if path not in protected and not any(b['instance'] in protected and path.startswith(b['instance']+'/') for b in bindings):
            raise ValueError('DESYNC_PRIMITIVE_UNPROTECTED:' + path)
    # Exact graph equality inside each primitive: no omitted, added, or rewired
    # leaf is allowed. Local port-net aliases supply the recipe's named nets.
    _, aliases = graph(netlist['modules'])
    for binding in bindings:
        prefix = binding['instance'] + '/'
        actual_paths = {p for p in cells if p.startswith(prefix)}
        expected_paths = {prefix + c['name'] for c in binding['cells']}
        if actual_paths != expected_paths:
            raise ValueError('DESYNC_PRIMITIVE_CELL_SET')
        for cell in binding['cells']:
            actual = cells[prefix + cell['name']]['connections']
            expected = {pin: [('constant', net)] if net in ('0', '1') else aliases[prefix + net]
                        for pin, net in cell['pins'].items()}
            if actual != expected:
                raise ValueError('DESYNC_PRIMITIVE_CONNECTIVITY')
    return dict(status='pass', registered_cells=len(registered), protected_cells=len(protected))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('netlist', type=Path)
    p.add_argument('--bindings', type=Path)
    p.add_argument('--clock-alias', action='append', default=[])
    a = p.parse_args()
    print(json.dumps(audit(json.loads(a.netlist.read_text()),
        json.loads(a.bindings.read_text()) if a.bindings else [], a.clock_alias)))
