# SPDX-License-Identifier: Apache-2.0
"""Single catalogue for desynchronization primitives (not the frozen BD flow).

An unavailable physical recipe is an error, never an ordinary-logic substitute.
The GF180 mutex currently has schematic evidence but no LEF/Liberty/layout.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Primitive:
    role: str
    pins: tuple
    timing: tuple
    reset: str
    recipe: str | None
    keeper_bits: int = 0
    protect: tuple = ('cells', 'internal_nets')


REGISTRY = {
    'RiscayDesyncController': Primitive('controller',
        ('reset', 'run', 'delayed', 'cycleGrant', 'pauseGrant', 'clockOut', 'cycleRequest', 'pauseRequest'), ('relative', 'absolute'),
        'POR clears clock/pause state and both requests; release enables cycling; stop completes the pulse and pending pause waits for grant', None, 2),
    'RiscayDesyncDelay': Primitive('delay_line', ('reset', 'in', 'out'), ('relative', 'absolute'),
        'POR clears feedback; physical discharge/release implementation unqualified', None),
    'RiscayDesyncMutex': Primitive('mutex',
        ('reset', 'request0', 'request1', 'grant0', 'grant1'), ('absolute',),
        'POR aborts grants; operational stop must not reset an active grant', None, 1),
}


def primitive(name):
    if name not in REGISTRY:
        raise ValueError('DESYNC_UNKNOWN_PRIMITIVE:' + name)
    return REGISTRY[name]


def require_recipe(name):
    entry = primitive(name)
    if entry.recipe is None:
        raise ValueError('DESYNC_PHYSICAL_RECIPE_UNAVAILABLE:' + name)
    return entry.recipe


def classified_cells(bindings):
    """Return exact leaf membership; never classify by name substring."""
    result = {}
    for binding in bindings:
        entry = primitive(binding['primitive'])
        require_recipe(binding['primitive'])
        if set(binding['ports']) != set(entry.pins) or not binding['cells']:
            raise ValueError('DESYNC_PRIMITIVE_SHAPE')
        for cell in binding['cells']:
            path = binding['instance'] + '/' + cell['name']
            if path in result:
                raise ValueError('DESYNC_DUPLICATE_PRIMITIVE_CELL')
            result[path] = (entry.role, cell)
    return result
