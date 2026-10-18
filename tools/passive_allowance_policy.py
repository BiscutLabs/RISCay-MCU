# SPDX-License-Identifier: Apache-2.0
"""Closed passive-allowance model compatibility for reviewed data primitives.

Legacy exports retain their resettable model. New exports may replace exactly
named whole-transform data markers with the public unmasked model; no control
primitive or reset/phase storage is normalized or exempted.
"""
from copy import deepcopy

PASSIVE = 'ChiselAsyncPassiveDataAllowance_v1'
RESETTABLE = 'ChiselAsyncControlGate_v1'


def data_spec(actual, expected):
    model, params = expected
    if actual.get('model') != PASSIVE:
        return expected
    if model != RESETTABLE or params.get('OP') != '0' or params.get('RESET_VALUE') != '0':
        raise ValueError('PASSIVE_NOT_DATA_BUFFER')
    return PASSIVE, {k: params[k] for k in ('WIDTH', 'DELAY_FS')}


def data_specs(node, expected):
    """Caller enumerates all data-delay IDs in its independent owner policy."""
    actual = {p['id']: p for p in node['primitives']}
    result = dict(expected)
    for name, spec in expected.items():
        if name == 'data_delay' or name.endswith('_data_delay'):
            result[name] = data_spec(actual.get(name, {}), spec)
    return result


def return_policy(node, expected):
    result = deepcopy(expected)
    actual = {p['id']: p for p in node['primitives']}
    for name, spec in result['cells'].items():
        if name == 'data_delay' or name.endswith('_data_delay'):
            spec['model'], spec['parameters'] = data_spec(actual.get(name, {}), (spec['model'], spec['parameters']))
            if spec['model'] == PASSIVE:
                spec['pins'] = {'a': spec['pins']['a']}
    return result
