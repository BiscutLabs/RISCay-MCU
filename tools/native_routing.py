# SPDX-License-Identifier: Apache-2.0
"""Bind native routing constraints to audited primitive leaves.

NDR assignment is an implementation constraint, not a geometric clearance or
noise-immunity proof. Pin-access taper and actual routed spacing remain open.
"""
import json
from collections import Counter
from pathlib import Path

from gf180_constraints import brace
from gf180_control_roles import DATA, PASSIVE_MODEL
from gf180_physical import sha, write_json
from gf180_slew_policy import native_recipe_pins


def anchors(mapping, audit):
    expected = [i for b in mapping['bindings'] for i in b['instances']]
    if len(expected) != len(set(expected)) or set(expected) != set(audit['adapter_instances']):
        raise ValueError('NATIVE_ROUTING_ADAPTER_INVENTORY')
    result = []
    passive = []
    for binding in mapping['bindings']:
        if binding['model'] == PASSIVE_MODEL:
            if binding['cells'] or binding['requirements'].get('role') != DATA:
                raise ValueError('NATIVE_ROUTING_PASSIVE_RECIPE')
            passive.extend(binding['instances'])
            continue
        selected = native_recipe_pins(binding)
        if not selected:
            raise ValueError('NATIVE_ROUTING_EMPTY_RECIPE')
        cells = {c['name']: c for c in binding['cells']}
        for instance in binding['instances']:
            root = audit['adapter_instances'][instance]
            for local in selected:
                cell, pin = local.rsplit('/', 1)
                result.append(dict(pin=root+'/'+local, master=cells[cell]['cell'],
                                   owner=instance, model=binding['model'],
                                   logical_net=cells[cell]['pins'][pin]))
    result.sort(key=lambda r: r['pin'])
    if not result or len({r['pin'] for r in result}) != len(result):
        raise ValueError('NATIVE_ROUTING_ANCHOR_INVENTORY')
    return result, sorted(passive)


def generate(mapping, out):
    mapping, out = Path(mapping), Path(out)
    rows, passive = anchors(json.loads((mapping/'mapping.json').read_text()),
                            json.loads((mapping/'netlist-audit.json').read_text()))
    record = dict(schema='riscay-native-routing-v1', status='constraints-only',
                  ndr='riscay_native_2s', spacing_multiplier=2, width_multiplier=1,
                  anchors=rows, passive_aliases=passive,
                  primitive_instances=dict(Counter({model: len({r['owner'] for r in rows if r['model']==model})
                      for model in sorted({r['model'] for r in rows})})),
                  mapping_sha256=sha(mapping/'mapping.json'),
                  audit_sha256=sha(mapping/'netlist-audit.json'),
                  limitations=['No geometric spacing or pin-taper coverage proof',
                               'No shielding or crosstalk/glitch qualification'])
    write_json(out/'native-routing.json', record)
    text = '# Typed protected leaf anchors; reassess live nets after repair.\n'
    text += 'set native_routing_rule riscay_native_2s\nset native_routing_seeds [list \\\n'
    text += ''.join('  [list '+brace(r['pin'])+' '+brace(r['master'])+'] \\\n' for r in rows)
    text += ']\n'
    (out/'native-routing.tcl').write_text(text)
    return record


def read_report(path, expected_anchors):
    """Validate assignment coverage; never interpret it as routed clearance."""
    pins, nets, layers = {}, {}, {}
    status = None
    for line in Path(path).read_text().splitlines():
        row = line.split('\t')
        if row[0] == 'P' and len(row) == 3:
            if row[1] in pins: raise ValueError('NATIVE_ROUTING_DUPLICATE_PIN')
            pins[row[1]] = row[2]
        elif row[0] == 'N' and len(row) == 3:
            if row[1] in nets: raise ValueError('NATIVE_ROUTING_DUPLICATE_NET')
            nets[row[1]] = row[2]
        elif row[0] == 'L' and len(row) == 4:
            if row[1] in layers: raise ValueError('NATIVE_ROUTING_DUPLICATE_LAYER')
            layers[row[1]] = [int(x) for x in row[2:]]
        elif row == ['STATUS', 'assigned-unqualified'] and status is None:
            status = row[1]
        else:
            raise ValueError('NATIVE_ROUTING_REPORT_SHAPE')
    if (set(pins) != set(expected_anchors) or not pins or not nets or not layers or
            not set(pins.values()) <= set(nets) or set(nets.values()) != {'riscay_native_2s'} or
            any(v <= 0 for values in layers.values() for v in values) or status is None):
        raise ValueError('NATIVE_ROUTING_REPORT_COVERAGE')
    return dict(status=status, pin_count=len(pins), net_count=len(nets),
                nets=sorted(nets), layers_dbu=layers, geometric_spacing_qualified=False)
