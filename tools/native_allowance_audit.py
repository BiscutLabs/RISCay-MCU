# SPDX-License-Identifier: Apache-2.0
"""Audit every whole-transform allowance's invalid-data consumers.

Run on the matched resettable parent graph before removing its output mask.
Every unmasked output must terminate at native payload D, possibly through
ordinary combinational data logic and another audited allowance. Never stop at
an arbitrary hierarchy boundary or treat a periodic register as a safe sink.
The result records each actual storage/capture/reset owner, including literal
initial-token paths. Passive q=a aliases merge upstream fanout: their pre-existing
source consumers are not newly exposed consumers of the removed mask.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from gf180_physical import SC, nodes, sha, write_json
from repair_gf180_design import flat
from passive_allowance_policy import PASSIVE

STORAGE = {'ChiselAsyncEventRegister_v1', 'ChiselAsyncClosingLatch_v1'}
DATA = 'whole-transform-allowance'


def require(condition, diagnostic):
    if not condition:
        raise ValueError('ALLOWANCE_AUDIT_' + diagnostic)


class FanoutIndex:
    """The actual mapped hierarchy and leaf graph, with no timing inference."""
    def __init__(self, graph, mapping, audit):
        self.graph = graph
        self.adapters = {}
        self.by_input = defaultdict(list)
        self.allowances = {}
        protected = set()
        self.capture_leaves = defaultdict(list)
        for binding in mapping['bindings']:
            for instance in binding['instances']:
                path = audit['adapter_instances'][instance]
                require(path not in self.adapters, 'DUPLICATE_ADAPTER')
                self.adapters[path] = (instance, binding)
                for leaf in binding['cells']:
                    name = path + '/' + leaf['name']
                    require(name in graph['cells'], 'MISSING_NATIVE_LEAF')
                    protected.add(name)
                    if 'D' in graph['cells'][name]['connections']:
                        for bit in graph['cells'][name]['connections']['D']:
                            self.capture_leaves[(path, bit)].append(name + '/D')
                for port in binding['ports']:
                    if port['direction'] != 'input':
                        continue
                    key = path + '/' + port['name']
                    bits = graph['boundaries'].get(key)
                    if bits is None:
                        # A zero-logical-width C input is physically unused and
                        # can be omitted by synthesis. A live pin cannot vanish.
                        require(not any(port['name'] in cell['pins'].values()
                                        for cell in binding['cells']), 'MISSING_LIVE_PORT')
                        continue
                    for lane, bit in enumerate(bits):
                        self.by_input[bit].append((path, port['name'], lane))
                if binding['requirements'].get('role') == DATA:
                    self.allowances[instance] = (path, binding)
        self.loads = defaultdict(list)
        self.top_outputs = defaultdict(list)
        self.direct_loads = Counter()
        for name, cell in graph['cells'].items():
            for pin, bits in cell['connections'].items():
                if cell['directions'][pin] == 'input':
                    for bit in bits:
                        self.direct_loads[bit] += 1
                        if name not in protected:
                            self.loads[bit].append((name, pin))
        for port, data in graph['ports'].items():
            if data['direction'] == 'output':
                for lane, bit in enumerate(data['bits']):
                    self.top_outputs[bit].append((port, lane))

    def trace_sinks(self, instance, *, require_capture_only=True, source_lanes=None):
        require(instance in self.allowances, 'UNKNOWN_INSTANCE')
        path, binding = self.allowances[instance]
        require(path + '/q' in self.graph['boundaries'], 'MISSING_Q')
        outputs = self.graph['boundaries'][path + '/q']
        reached, sinks, bad, combinational = set(), set(), set(), set()
        selected = range(len(outputs)) if source_lanes is None else source_lanes
        require(all(isinstance(i, int) and 0 <= i < len(outputs) for i in selected), 'SOURCE_LANES')
        stack = [outputs[i] for i in selected]
        while stack:
            bit = stack.pop()
            if bit in reached or bit[0] == 'constant':
                continue
            reached.add(bit)
            for target, pin, lane in self.by_input[bit]:
                name, spec = self.adapters[target]
                model = spec['model']
                if pin == 'd' and model in STORAGE:
                    sinks.add((name, target, lane))
                elif pin == 'a' and spec['requirements'].get('role') == DATA:
                    # An allowance is a lane-preserving alias, not a bus fork.
                    stack.append(self.graph['boundaries'][target + '/q'][lane])
                else:
                    bad.add((name, model, pin))
            for name, pin in self.loads[bit]:
                cell = self.graph['cells'][name]
                combinational.add(name)
                if (not cell['type'].startswith(SC) or
                        any(p in cell['connections'] for p in ('CLK', 'E', 'RN', 'SETN', 'CEN', 'GCLK'))):
                    bad.add((name, cell['type'], pin))
                    continue
                stack.extend(net for p, nets in cell['connections'].items()
                             if cell['directions'][p] == 'output' for net in nets)
            for port, lane in self.top_outputs[bit]:
                bad.add(('top', port, str(lane)))
        if require_capture_only:
            require(not bad, 'INVALID_DATA_ESCAPE:' + instance + ':' + repr(sorted(bad)[:3]))
        captures = []
        for name, target, lane in sorted(sinks):
            spec = self.adapters[target][1]
            event = 'closed' if spec['model'].endswith('ClosingLatch_v1') else 'trigger'
            require(target + '/' + event in self.graph['boundaries'] and
                    target + '/reset' in self.graph['boundaries'], 'CAPTURE_RESET_OWNER')
            # Actual protected leaf D pins, not potentially obsolete hierarchy ports.
            bit = self.graph['boundaries'][target + '/d'][lane]
            pins = sorted(self.capture_leaves[(target, bit)])
            require(pins, 'CAPTURE_LEAF_MISSING')
            captures.append(dict(instance=name, lane=lane, model=spec['model'], leaf_pins=pins,
                                 capture=target + '/' + event, reset=target + '/reset'))
        return dict(instance=instance, model=binding['model'], width=int(binding['parameters']['WIDTH']),
                    disposition='native-capture-only' if not bad else 'source-alias-fanout-or-escape',
                    maximum_output_leaf_fanout=max((self.direct_loads[b] for b in outputs), default=0),
                    constant_output_lanes=sum(b[0] == 'constant' for b in outputs),
                    storage_data_sinks=captures, combinational_cells=sorted(combinational), escapes=sorted(bad),
                    initial_literal='ca_child_initial.' in instance)


def trace_sinks(graph, mapping, audit, instance, *, require_capture_only=True):
    return FanoutIndex(graph, mapping, audit).trace_sinks(instance, require_capture_only=require_capture_only)


def audit_mapping(mapping_path, candidate=None, removed=()):
    mapping_path = Path(mapping_path).resolve()
    paths = [mapping_path / name for name in ('netlist.json', 'mapping.json', 'netlist-audit.json')]
    frozen = {str(p): sha(p) for p in paths}
    graph = flat(json.loads(paths[0].read_text()), 'RiscayMcuDigital')
    bindings, net_audit = (json.loads(p.read_text()) for p in paths[1:])
    index = FanoutIndex(graph, bindings, net_audit)
    require(index.allowances, 'EMPTY_INVENTORY')
    rows = [index.trace_sinks(instance) for instance in sorted(index.allowances)]
    result = dict(schema='riscay-passive-allowance-audit-v1', inputs=frozen, instances=rows,
                  instance_count=len(rows), data_lanes=sum(r['width'] for r in rows),
                  literal_initial_instances=sum(r['initial_literal'] for r in rows),
                  scope='Actual parent-mask output fanout; invalid-data isolation, not physical setup/hold or routed qualification')
    if candidate:
        candidate = Path(candidate).resolve()
        manifest_path = candidate / 'contract.json'
        manifest = json.loads(manifest_path.read_text())['manifest']
        primitives = {p['rtl_path']: p for n in nodes(manifest['design']) for p in n['primitives']}
        removed = set(removed)
        require(removed <= index.allowances.keys(), 'UNKNOWN_REMOVAL')
        expected = index.allowances.keys() - removed
        actual = {p for p, spec in primitives.items() if spec['model'] == PASSIVE}
        require(actual == expected, 'CANDIDATE_INVENTORY:' + repr(sorted(actual ^ expected)))
        for name in expected:
            prior = index.allowances[name][1]
            require(primitives[name]['parameters'] == {k: str(prior['parameters'][k]) for k in ('WIDTH', 'DELAY_FS')},
                    'CANDIDATE_PARAMETERS:' + name)
            require({p['name']: (p['direction'], p['width']) for p in primitives[name]['ports']} ==
                    {'a': ('input', int(prior['parameters']['WIDTH'])),
                     'q': ('output', int(prior['parameters']['WIDTH']))}, 'CANDIDATE_PORTS:' + name)
        result['candidate'] = dict(contract=str(manifest_path), sha256=sha(manifest_path),
                                   passive_instances=len(actual), removed_instances=sorted(removed))
    require(all(sha(p) == digest for p, digest in frozen.items()), 'INPUT_CHANGED')
    return result


def audit_elaborated(database, manifest):
    """Actual emitted fanout before physical q=a aliasing merges source nets.

    Uses the independently prepared RDC graph: native primitives are black boxes,
    preserving separate a/q nets. Every ordinary combinational cell is traversed;
    all control, reset, periodic D and functional output escapes are rejected.
    """
    from check_reset_crossings import COMB
    top = manifest['top']
    modules = database['modules']; body = modules[top]; cells = body['cells']
    primitive_specs = {p['rtl_path'].removeprefix(top + '.'): p
                       for node in nodes(manifest['design']) for p in node['primitives']}
    def model(cell):
        kind = cell['type']
        return modules.get(kind, {}).get('attributes', {}).get('hdlname', kind).split()[0]
    from passive_constant_proof import ConstantProof, parameter
    constants = ConstantProof(cells, model)
    loads = defaultdict(list); outputs = defaultdict(list)
    for name, cell in cells.items():
        for pin, bits in cell['connections'].items():
            if cell['port_directions'][pin] == 'input':
                for lane, bit in enumerate(bits):
                    if isinstance(bit, int): loads[bit].append((name, pin, lane))
    for name, port in body['ports'].items():
        if port['direction'] == 'output':
            for lane, bit in enumerate(port['bits']):
                if isinstance(bit, int): outputs[bit].append((name, lane))
    rows = []
    for name, spec in sorted(primitive_specs.items()):
        if spec['model'] != PASSIVE: continue
        require(name in cells and model(cells[name]) == PASSIVE, 'ELABORATED_SOURCE:' + name)
        source = cells[name]
        require(source['port_directions'] == {'a':'input', 'q':'output'}, 'ELABORATED_SOURCE_PORTS')
        require(len(source['connections']['a']) == len(source['connections']['q']) == int(spec['parameters']['WIDTH']),
                'ELABORATED_SOURCE_WIDTH')
        queue = [(b, i) for i, b in enumerate(source['connections']['q'])]
        visited, targets, glue, escapes = set(), defaultdict(set), set(), set()
        while queue:
            bit, source_lane = queue.pop()
            if not isinstance(bit, int) or (bit, source_lane) in visited: continue
            visited.add((bit, source_lane))
            for target, pin, lane in loads[bit]:
                cell = cells[target]; kind = model(cell)
                if kind in STORAGE and pin == 'd':
                    require(target in primitive_specs and primitive_specs[target]['model'] == kind,
                            'ELABORATED_UNDECLARED_CAPTURE')
                    event = 'closed' if kind.endswith('ClosingLatch_v1') else 'trigger'
                    require(event in cell['connections'] and 'reset' in cell['connections'], 'ELABORATED_CAPTURE_RESET')
                    targets[(target, lane, kind, event)].add(source_lane)
                elif kind == PASSIVE and pin == 'a':
                    require(target in primitive_specs, 'ELABORATED_UNDECLARED_ALLOWANCE')
                    queue.append((cell['connections']['q'][lane], source_lane))
                elif cell['type'] in COMB:
                    glue.add(target)
                    pins = cell['connections']; kind = cell['type']
                    # Preserve exact per-lane identity for wiring and bitwise
                    # cells. Arithmetic/control cones conservatively depend on
                    # all input lanes; that cannot manufacture a constant proof.
                    output = pins.get('Y', [])
                    if kind == '$mux' and pin in ('A', 'B'):
                        following = output[lane:lane + 1]
                    elif kind in ('$and', '$or', '$xor', '$xnor', '$not', '$pos'):
                        following = output[lane:lane + 1]
                        if lane == len(pins[pin]) - 1 and parameter(cell, pin + '_SIGNED'):
                            following += output[len(pins[pin]):]
                    elif kind == '$concat':
                        offset = 0 if pin == 'A' else len(pins['A'])
                        following = output[offset + lane:offset + lane + 1]
                    else:
                        following = [b for p, bits in pins.items()
                                     if cell['port_directions'][p] == 'output' for b in bits]
                    queue.extend((b, source_lane) for b in following)
                else:
                    escapes.add((target, kind, pin))
            escapes.update(('top', port, str(lane)) for port, lane in outputs[bit])
        require(not escapes, 'ELABORATED_INVALID_DATA_ESCAPE:' + name + ':' + repr(sorted(escapes)[:3]))
        require(targets, 'ELABORATED_NO_CAPTURE:' + name)
        rows.append(dict(instance=top + '.' + name, width=int(spec['parameters']['WIDTH']),
            disposition='native-capture-only', maximum_direct_fanout=max((len(loads[b]) for b in source['connections']['q']), default=0),
            capture_sinks=[dict(instance=top + '.' + n, lane=i, model=k, data_pin=top + '.' + n + '.d',
                                event_pin=top + '.' + n + '.' + e, reset_pin=top + '.' + n + '.reset',
                                source_lanes=sorted(targets[(n, i, k, e)]),
                                constant_value=constants.bit(cells[n]['connections']['d'][i]))
                           for n, i, k, e in sorted(targets)], combinational_cells=sorted(glue),
            initial_literal='ca_child_initial.' in name))
    return dict(schema='riscay-elaborated-passive-allowance-audit-v2', top=top,
        constant_proof='unconditional-bitwise-propagation; all state outputs and runtime inputs unconstrained',
        checker_sha256={p.name: sha(p) for p in
                        (Path(__file__), Path(__file__).with_name('passive_constant_proof.py'))},
        instances=rows, instance_count=len(rows), data_lanes=sum(r['width'] for r in rows),
        literal_initial_instances=sum(r['initial_literal'] for r in rows),
        scope='Actual emitted primitive-q fanout before physical aliasing; no periodic or unqualified control consumer; not timing qualification')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mapping', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--removed-instance', action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit_mapping(args.mapping, args.candidate, args.removed_instance)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print('ALLOWANCE_FANOUT_PASS:' + str(result['instance_count']))


if __name__ == '__main__':
    main()
