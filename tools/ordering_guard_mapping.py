# SPDX-License-Identifier: Apache-2.0
"""Apply measured guard counts before synthesis, retaining contract identities."""
from collections import defaultdict
import math
import json
import re
from gf180_physical import nodes, key


def require(condition, message):
    if not condition:
        raise ValueError('ORDERING_GUARD_' + message)


def specialize(export, manifest, groups, policy, variant, floor, *, candidate=False):
    require(policy['schema'] == 'riscay-gf180-ordering-guards-v1', 'SCHEMA')
    require(policy['status'] == 'locally-measured' or
            candidate and policy['status'] == 'candidate-not-yet-accepted', 'NOT_ACCEPTED')
    require(policy['engineering_derate'] == .2 and math.isfinite(policy['residual_ns']) and policy['residual_ns'] >= 2 and
            policy['statistical_qualification'] is False, 'MISMATCH_POLICY')
    owners = list(nodes(manifest['design']))
    primitives = {p['rtl_path']: (n,p) for n in owners for p in n['primitives']}
    # The caller validates this generation audit before any physical rewrite.
    # Its typed compiler hierarchy resolves deduplicated module names directly.
    actual=json.loads((export/'structure.json').read_text())['owner_modules']
    require(set(actual)=={n['rtl_path'] for n in owners},'OWNER_INVENTORY')
    requested = {}
    for row in policy['variants'][variant]:
        instance = row['instance']
        require(instance in primitives and instance not in requested, 'INSTANCE:' + instance)
        owner, primitive = primitives[instance]
        require(owner['rtl_path'] == row['owner'] and
                owner['module'] == row.get('owner_metadata_module',row['owner_module']) and
                primitive['id'] == row['primitive_id'], 'OWNER:' + instance)
        family=re.sub(r'_\d+$','',owner['module'])
        canonical={('bd','FourPhaseStage','request_delay'):'ordering-bundling',
            ('bd','FourPhaseStage','output_delay'):'ordering-publication',
            ('bd','LongHoldBuffer','request_delay'):'ordering-bundling',
            ('bd','LongHoldBuffer','output_delay'):'ordering-publication',
            ('click','ClickStage','acknowledge_guard'):'ordering-and-pulse-acknowledge_guard',
            ('click','ClickBuffer','acknowledge_guard'):'ordering-and-pulse-acknowledge_guard'}
        expected=canonical.get((variant,family,primitive['id']))
        require(expected is not None and row['owner_module']==family and row['purpose']==expected,
                'FIXED_TIME_OR_UNREVIEWED_PURPOSE:' + instance)
        parameters = dict(key(primitive)[1])
        require(primitive['model'] == 'ChiselAsyncControlGate_v1' and
                parameters == row['original_parameters'], 'PARAMETERS:' + instance)
        require(parameters['WIDTH'] == 1 and parameters['OP'] == 0 and parameters['RESET_VALUE'] == 0,
                'NOT_ORDERING_BUFFER:' + instance)
        require(type(row['stages']) is int and row['stages'] > 0, 'COUNT')
        baseline = max(1, math.ceil(1.2 * parameters['DELAY_FS'] / 1e6 / floor))
        require(row['previous_stages'] == baseline, 'BASELINE_COUNT:' + instance)
        requested[instance] = row
    # A deduplicated owner SV cannot use different cells at the same primitive
    # location. Use the maximum of all its instances, including any unselected
    # member's unchanged baseline. Sharing a count never shares measurements.
    slots = defaultdict(list)
    for instance, (owner,p) in primitives.items():
        if p['model'] != 'ChiselAsyncControlGate_v1': continue
        slots[(actual[owner['rtl_path']], instance.split('.')[-1])].append(instance)
    applied, rewrites, wrappers = {}, defaultdict(dict), {}
    for (module, local), members in slots.items():
        if not any(i in requested for i in members): continue
        require(len({key(primitives[i][1]) for i in members}) == 1, 'DEDUP_PARAMETERS')
        baseline = max(1, math.ceil(1.2 * dict(key(primitives[members[0]][1])[1])['DELAY_FS'] / 1e6 / floor))
        count = max(requested[i]['stages'] if i in requested else baseline for i in members)
        wrapper = 'ChiselAsyncControlGate_v1_RiscayStages_' + str(count)
        wrappers[wrapper] = dict(model='ChiselAsyncControlGate_v1', stages=count)
        rewrites[module + '.sv'][local] = wrapper
        for instance in members:
            applied[instance] = dict(stages=count, requested=requested.get(instance),
                                     shared_module=module, shared_instances=sorted(members))
    regrouped = defaultdict(list)
    for group in groups.values():
        for p in group:
            model, parameters = key(p)
            if p['rtl_path'] in applied:
                model = 'ChiselAsyncControlGate_v1_RiscayStages_' + str(applied[p['rtl_path']]['stages'])
            regrouped[(model, parameters)].append(p)
    return regrouped, wrappers, rewrites, applied


def rewrite_owner(source, replacements):
    for local, wrapper in replacements.items():
        parameters = r'(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?'
        pattern = r'\bChiselAsyncControlGate_v1(?=\s*' + parameters + re.escape(local) + r'\s*\()'
        source, count = re.subn(pattern, wrapper, source, flags=re.S)
        require(count == 1, 'PRIMITIVE_REWRITE:' + local)
    return source
