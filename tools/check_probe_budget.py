# SPDX-License-Identifier: Apache-2.0
"""Fail before allocating an impractically large paired mapping probe.

This bounds the *additional* paired campaign, not available host memory or the
ordinary campaign. It never removes samples, changes a comparison or establishes
an export pass. Call only for paired=True, before the library probe generator.
The manifest and elaborated scopes must already have passed library validation.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json


# Fingerprints omit only the leading docstring, comments and source locations.
# A changed driver inventory or pairing algorithm requires a reviewed update;
# otherwise these size formulas must not authorize source allocation.
ALGORITHM_SHA256 = {
    'nodes': '0dd5a620436ea469eb81ab696d80def0bc7290d4c7e524bea10534441f447d60',
    'paired_probe_values': '014c220c41e95e831b2f8df3e06492ea1ac98817410ca776a4196a2910bde9e7',
    'probe_source': 'ae264a622707cefa7951332597394acfb7e7ca444c57c1956647cce086c8d6e8',
}
LIMITS = {
    'paired_samples': 250_000,
    'extra_lines': 1_000_000,
    'extra_source_bytes_upper_bound': 64 * 1024 * 1024,
}


def need(value, detail):
    if not value:
        raise ValueError('PAIRED_PROBE_INVALID_INVENTORY:' + detail)


def require_known_algorithm(library_source):
    """Bind resource arithmetic to the actual source used by the caller."""
    try:
        tree = ast.parse(library_source)
        selected = {name: [n for n in tree.body if isinstance(n, ast.FunctionDef)
                           and n.name == name] for name in ALGORITHM_SHA256}
        for name, expected in ALGORITHM_SHA256.items():
            if len(selected[name]) != 1:
                raise ValueError(name)
            node = selected[name][0]
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
            digest = hashlib.sha256(ast.dump(node, annotate_fields=True,
                                            include_attributes=False).encode()).hexdigest()
            if digest != expected:
                raise ValueError(name)
    except (SyntaxError, TypeError, ValueError) as error:
        raise ValueError('PAIRED_PROBE_UNSUPPORTED_LIBRARY_ALGORITHM:' + str(error)) from error


def driver_inventory(manifest, scopes):
    """Mirror the known generator's ordered collection, retaining duplicates."""
    top = manifest['top']
    need(isinstance(top, str) and bool(top), 'TOP')
    drivers, endpoint_count, pending, seen = [], 0, [manifest['design']], set()

    def add(path, width):
        need(isinstance(path, str) and bool(path) and '\n' not in path and '\r' not in path, 'PATH')
        need(type(width) is int and width > 0, 'WIDTH')
        drivers.append((path, width))

    while pending:
        node = pending.pop()
        path = node['rtl_path']
        need(isinstance(path, str) and path not in seen, 'NODE_IDENTITY')
        seen.add(path)
        need(path in scopes, 'MISSING_SCOPE:' + path)
        endpoint_count += len(node['endpoints'])
        scope = scopes[path]
        if path == top:
            for name, port in scope['ports'].items():
                need(port['direction'] in ('input', 'output', 'inout'), 'PORT_DIRECTION')
                if port['direction'] == 'input':
                    add(top + '.' + name, port['width'])
        for name, width in scope['registers'].items():
            add(path + '.' + name, width)
        for primitive in node['primitives']:
            for port in primitive['ports']:
                need(port['direction'] in ('input', 'output', 'inout'), 'PRIMITIVE_DIRECTION')
                if port['direction'] == 'output':
                    add(primitive['rtl_path'] + '.' + port['name'], port['width'])
        need(isinstance(node['children'], list), 'CHILDREN')
        pending.extend(child['contract'] for child in reversed(node['children']))
    need(top in seen, 'MISSING_TOP')
    return drivers, endpoint_count


def value_counts(width):
    """Exact compact/expanded set cardinalities, without allocating big ints."""
    need(type(width) is int and width > 0, 'WIDTH')
    return (1, 2) if width == 1 else (2, 3) if width == 2 else (2, 2 * width + 1)


def paired_probe_budget(manifest, scopes):
    """O(drivers) count and conservative source-byte bound; no pairs allocated."""
    drivers, endpoints = driver_inventory(manifest, scopes)
    total_c = total_e = diagonal_ec = diagonal_cc = 0
    for _, width in drivers:
        compact, expanded = value_counts(width)
        total_c += compact
        total_e += expanded
        diagonal_ec += compact * expanded
        diagonal_cc += compact * compact
    # |Ea x Cb union Ca x Eb| = ea*cb + ca*eb - ca*cb.
    # Sum over unordered driver pairs, preserving repeated inventory entries.
    samples = total_e * total_c - diagonal_ec - (total_c * total_c - diagonal_cc) // 2
    count = len(drivers)
    pairs = count * (count - 1) // 2
    byte_bound = 11 * samples  # '#1; check;\n' for every sample.
    for path, width in drivers:
        compact, expanded = value_counts(width)
        appearances = (expanded * (total_c - compact)
                       + compact * (total_e - expanded)
                       - compact * (total_c - compact))
        # UTF-8 bytes of "force PATH = WIDTH'hHEX;\n". Every value fits
        # ceil(width/4) digits. Zero restores have exactly one hex digit.
        prefix = len(path.encode('utf-8')) + len(str(width)) + 13
        byte_bound += appearances * (prefix + (width + 3) // 4)
        byte_bound += count * (prefix + 1)  # initial zero plus every pair's return.
    width_sum = sum(width for _, width in drivers)
    base_checks = 4 * width_sum * endpoints
    # Include growth of the final CONTRACT_PROBES_PASS decimal count as well.
    byte_bound += len(str(base_checks + samples * endpoints)) - len(str(base_checks))
    result = dict(schema='riscay-paired-probe-budget-v1', driver_count=count,
                  driver_width_sum=width_sum,
                  driver_width_histogram=dict(sorted(Counter(width for _, width in drivers).items())),
                  driver_pairs=pairs, paired_samples=samples,
                  extra_lines=count + 3 * samples + 2 * pairs,
                  extra_source_bytes_upper_bound=byte_bound,
                  endpoint_count=endpoints, extra_mapping_checks=samples * endpoints,
                  limits=dict(LIMITS))
    result['exceeded'] = [key for key, limit in LIMITS.items() if result[key] > limit]
    return result


def require_paired_probe_budget(manifest, scopes, library_source):
    """Raise before allocation; within budget still requires every real check."""
    require_known_algorithm(library_source)
    result = paired_probe_budget(manifest, scopes)
    if result['exceeded']:
        raise ValueError('PAIRED_PROBE_RESOURCE_BUDGET_EXCEEDED:'
                         + json.dumps(result, sort_keys=True, separators=(',', ':')))
    return result
