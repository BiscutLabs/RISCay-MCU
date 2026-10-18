# SPDX-License-Identifier: Apache-2.0
"""Custom passive fan-in inventory; conservative reachability, not sensitization."""
from pathlib import Path
from collections import Counter, defaultdict
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from gf180_physical import nodes, sha
from check_reset_crossings import NATIVE_STATE, NATIVE_COMB, COMB
from passive_constant_proof import ConstantProof, parameter

CANONICAL = {'FourPhaseStage', 'LongHoldBuffer', 'ClickStage', 'ClickBuffer'}
PASSIVE = 'ChiselAsyncPassiveDataAllowance_v1'


def inventory(root, top):
    root = Path(root)
    paths = [root / 'contract.json', root / 'reset-crossings/netlist.json',
             root / 'reset-crossings/allowance-audit.json']
    inputs = {str(p): sha(p) for p in paths}
    manifest = json.loads(paths[0].read_text())['manifest']
    database = json.loads(paths[1].read_text())
    audit = json.loads(paths[2].read_text())
    from native_allowance_audit import audit_elaborated
    computed = audit_elaborated(database, manifest)
    if set(audit) != set(computed) | {'inputs'} or any(audit[k] != v for k,v in computed.items()):
        raise ValueError('PASSIVE_SOURCE_STALE_FANOUT_AUDIT')
    if audit['inputs']['netlist_sha256'] != sha(paths[1]) or audit['inputs']['contract_sha256'] != sha(paths[0]):
        raise ValueError('PASSIVE_SOURCE_STALE_GRAPH_IDENTITY')
    filelist = root/'filelist.f'
    names = [name for name in filelist.read_text().splitlines() if name.strip()]
    if audit['inputs']['filelist_sha256'] != sha(filelist) or set(names) != set(audit['inputs']['sources']):
        raise ValueError('PASSIVE_SOURCE_STALE_SOURCE_INVENTORY')
    inputs[str(filelist)] = sha(filelist)
    for name,digest in audit['inputs']['sources'].items():
        source = (root/name.strip()).resolve()
        if not source.is_relative_to(root.resolve()) or sha(source) != digest:
            raise ValueError('PASSIVE_SOURCE_STALE_RTL')
        inputs[str(source)] = digest
    cells = database['modules'][top]['cells']
    owners = {p['rtl_path']: (n, p) for n in nodes(manifest['design']) for p in n['primitives']}

    def model(cell):
        return database['modules'].get(cell['type'], {}).get('attributes', {}).get('hdlname', cell['type']).split()[0]

    proof = ConstantProof(cells, model)
    drivers = {}
    for name, cell in cells.items():
        for pin, bits in cell['connections'].items():
            if cell['port_directions'][pin] != 'output':
                continue
            for lane, bit in enumerate(bits):
                if isinstance(bit, int):
                    assert bit not in drivers
                    drivers[bit] = name, pin, lane
    cache, active = {}, set()

    def origins(bit):
        if not isinstance(bit, int):
            return frozenset()
        if bit in cache:
            return cache[bit]
        if bit in active:
            return frozenset({('UNRESOLVED_CYCLE', str(bit), '', -1)})
        if bit not in drivers:
            return frozenset({('EXTERNAL_INPUT', str(bit), '', -1)})
        name, pin, lane = drivers[bit]
        cell = cells[name]
        kind = model(cell)
        if kind in NATIVE_STATE or cell['type'] not in COMB and kind not in NATIVE_COMB:
            return frozenset({(kind, name, pin, lane)})
        ports = cell['connections']
        if kind == PASSIVE:
            following = [ports['a'][lane]]
        elif cell['type'] == '$mux':
            following = [ports['A'][lane], ports['B'][lane], *ports['S']]
        elif cell['type'] in ('$and', '$or', '$xor', '$xnor', '$not', '$pos'):
            following = []
            signed = bool(parameter(cell, 'A_SIGNED'))
            if 'B' in ports:
                signed = signed and bool(parameter(cell, 'B_SIGNED'))
            for port in ('A', 'B'):
                if port not in ports:
                    continue
                vector = ports[port]
                if lane < len(vector):
                    following.append(vector[lane])
                elif signed and vector:
                    following.append(vector[-1])
        elif cell['type'] == '$concat':
            following = [(ports['A'] + ports['B'])[lane]]
        elif cell['type'] == '$slice':
            following = [ports['A'][parameter(cell, 'OFFSET') + lane]]
        else:
            # Arithmetic, native combinational control, mux select and other
            # supported logic conservatively depend on every runtime input.
            # Reset transitions are separately owned by reset isolation; they
            # are not functional data launches in this narrow inventory.
            following = [b for p, bits in ports.items()
                         if cell['port_directions'][p] == 'input' and p != 'reset' for b in bits]
        active.add(bit)
        result = frozenset().union(*(origins(b) for b in following))
        active.remove(bit)
        cache[bit] = result
        return result

    result = []
    families = Counter()
    for row in audit['instances']:
        owner, primitive = owners[row['instance']]
        family = re.sub(r'_\d+$', '', owner['module'])
        if family in CANONICAL:
            continue
        families[family] += 1
        source = cells[row['instance'].removeprefix(top + '.')]
        launches = [origins(b) for b in source['connections']['a']]
        constant_lanes = {str(i): proof.bit(b) for i, b in enumerate(source['connections']['a'])
                          if proof.bit(b) in (0, 1)}
        targets = defaultdict(list)
        for sink in row['capture_sinks']:
            targets[sink['instance']].append(sink)
        captures = []
        for target, sinks in sorted(targets.items()):
            state = cells[target.removeprefix(top + '.')]
            event_pin = 'trigger' if 'trigger' in state['connections'] else 'closed'
            event = state['connections'][event_pin]
            source_points = defaultdict(lambda: {'source_lanes': set(), 'capture_lanes': set()})
            for sink in sinks:
                if sink['constant_value'] in (0, 1):
                    continue
                for allowance_lane in sink['source_lanes']:
                    for kind, name, pin, lane in launches[allowance_lane]:
                        record = source_points[kind, name, pin]
                        record['source_lanes'].add(lane)
                        record['capture_lanes'].add(sink['lane'])
            points = []
            categories = set()
            for (kind, name, pin), binding in sorted(source_points.items()):
                tags = []
                original = cells.get(name)
                source_event = None
                if original is not None:
                    source_event = original['connections'].get('trigger', original['connections'].get('closed'))
                if name == target.removeprefix(top + '.'):
                    tags.append('self-feedback')
                if source_event is not None and source_event == event:
                    tags.append('same-event-net')
                if kind == 'ChiselAsyncPhaseRegister_v1':
                    tags.append('native-phase-as-data')
                elif kind in NATIVE_STATE and kind not in ('ChiselAsyncEventRegister_v1', 'ChiselAsyncClosingLatch_v1'):
                    tags.append('native-control-state-as-data')
                if not tags:
                    tags.append('different-event-retained-source' if kind in NATIVE_STATE else
                                'periodic-held-source' if kind in ('$adff', '$dff') else 'unresolved-origin')
                categories.update(tags)
                points.append(dict(primitive_path=top + '.' + name, model=kind,
                    output_pin=top + '.' + name + '.' + pin if pin else None,
                    source_lanes=sorted(binding['source_lanes']), capture_lanes=sorted(binding['capture_lanes']),
                    source_event_bits=source_event, categories=tags))
            captures.append(dict(primitive_path=target, model=model(state), event_pin=target + '.' + event_pin,
                event_bits=event, capture_lanes=[s['lane'] for s in sinks],
                exact_capture_constant_lanes={str(s['lane']): s['constant_value'] for s in sinks if s['constant_value'] in (0, 1)},
                allowance_lane_provenance={str(s['lane']): s['source_lanes'] for s in sinks},
                categories=sorted(categories), source_outputs=points))
        result.append(dict(allowance_path=row['instance'], owner_path=owner['rtl_path'],
            owner_family=family, width=row['width'], input_constant_lanes=constant_lanes, captures=captures))
    assert all(sha(Path(p)) == digest for p, digest in inputs.items())
    candidates = {capture['primitive_path']: capture['model'] for row in result for capture in row['captures']
                  if set(capture['categories']) & {'self-feedback', 'same-event-net'}}
    return dict(top=top, inputs_sha256=inputs, allowances=result, family_counts=dict(families),
        custom_allowance_count=len(result), self_or_same_event_capture_count=len(candidates),
        self_or_same_event_capture_models=dict(Counter(candidates.values())))


