# SPDX-License-Identifier: Apache-2.0
"""Resolve reset-free allowances to their original capture owners, never wires.

The emitted black-box fanout proof retains separate a/q nets. Physical aliases
can merge unrelated source fanout or literal constants, so that proof supplies
the exact sink identities; the mapped graph supplies their actual leaf pins.
"""
import json
from native_allowance_audit import FanoutIndex, require
from repair_gf180_design import flat


def bind_captures(database, mapping, audit, fanout):
    graph = flat(database, 'RiscayMcuDigital')
    index = FanoutIndex(graph, mapping, audit)
    rows = {r['instance']: r for r in fanout['instances']}
    passive = {i for i, (_, b) in index.allowances.items()
               if b['model'] == 'ChiselAsyncPassiveDataAllowance_v1'}
    require(set(rows) == passive, 'PHYSICAL_CAPTURE_INVENTORY')
    bound = {}
    for instance, row in rows.items():
        reached = index.trace_sinks(instance, require_capture_only=False)
        lane_reach = {}
        pins, constants = set(), []
        for sink in row['capture_sinks']:
            target, lane = sink['instance'], sink['lane']
            require(target in audit['adapter_instances'], 'PHYSICAL_CAPTURE_MISSING')
            path = audit['adapter_instances'][target]
            actual, binding = index.adapters[path]
            require(actual == target and binding['model'] == sink['model'], 'PHYSICAL_CAPTURE_MODEL')
            bits = graph['boundaries'][path + '/d']
            require(0 <= lane < len(bits), 'PHYSICAL_CAPTURE_LANE')
            bit = bits[lane]
            source_lanes = sink.get('source_lanes')
            require(isinstance(source_lanes, list) and source_lanes and
                    source_lanes == sorted(set(source_lanes)), 'PHYSICAL_CAPTURE_PROVENANCE')
            if bit[0] == 'constant':
                require(bit[1] in ('0', '1'), 'PHYSICAL_CAPTURE_UNKNOWN_CONSTANT')
                # This value was proved for this exact capture lane in the
                # independently emitted graph, with all state/runtime inputs
                # free. A constant on some *other* q lane proves nothing here.
                require(sink.get('constant_value') in (0, 1) and
                        str(sink['constant_value']) == bit[1], 'PHYSICAL_CAPTURE_CONSTANT_UNPROVED')
                constants.append(dict(instance=target, lane=lane, value=bit[1]))
            else:
                for source_lane in source_lanes:
                    if source_lane not in lane_reach:
                        result = index.trace_sinks(instance, require_capture_only=False,
                                                   source_lanes=[source_lane])
                        lane_reach[source_lane] = {(r['instance'], r['lane'])
                                                  for r in result['storage_data_sinks']}
                require(any((target, lane) in lane_reach[i] for i in source_lanes),
                        'PHYSICAL_CAPTURE_DISCONNECTED')
            leaves = index.capture_leaves[(path, bit)]
            # Equal constant nets can name many storage bits. Select the exact
            # logical lane from the preserved recipe instead of following ties.
            expected = {path + '/' + c['name'] + '/D' for c in binding['cells']
                        if c['pins'].get('D') in (f'd[{lane}]', 'd' if len(bits) == 1 else '')}
            require(expected and expected <= set(leaves), 'PHYSICAL_CAPTURE_LEAF')
            pins.update(expected)
        require(pins, 'PHYSICAL_CAPTURE_EMPTY')
        bound[instance] = dict(sink_pins=sorted(pins), constant_captures=constants,
            ownership='exact-emitted-q-fanout',
            merged_source_fanout=reached['escapes'])
    return bound


def load_bindings(mapping_path, database, mapping, audit):
    path = mapping_path / 'passive-allowance-audit.json'
    from gf180_physical import sha
    require(mapping.get('passive_allowance_audit_sha256') == sha(path), 'PHYSICAL_FANOUT_PROOF_CHANGED')
    return bind_captures(database, mapping, audit, json.loads(path.read_text()))
