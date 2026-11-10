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
    estimated_area_bound_mm2: float | None = None
    candidate: str | None = None
    initial_markings: tuple = (False,)


REGISTRY = {
    'RiscayDesyncController': Primitive('controller',
        ('reset', 'requestIn', 'acknowledgeIn', 'requestOut', 'acknowledgeOut', 'enable'), ('relative', 'absolute'),
        'Semi-decoupled latch controller; master open/slave closed initial marking requires per-instance reset binding', None, 2,
        candidate='gf180-semi-decoupled', initial_markings=(False, True)),
    'RiscayDesyncFlopBank': Primitive('controller',
        ('reset', 'requestIn', 'acknowledgeIn', 'requestOut', 'acknowledgeOut'), ('relative', 'absolute'),
        'CPU exception: open master, closed slave, both readiness joins zero; acknowledgeOut is the FF capture clock',
        None, 6, candidate='gf180-flop-pair'),
    'RiscayDesyncJoin': Primitive('join', ('reset', 'inputs', 'out'), ('relative',),
        'C-element join initial marking follows its controller-graph place', None, 1, candidate='gf180-c-element',
        initial_markings=(False, True)),
    'RiscayDesyncEnableGate': Primitive('controller', ('enable', 'condition', 'out'), ('relative', 'absolute'),
        'Combinational AND; gate condition stable throughout the enabled phase', None, protect=(), candidate='gf180-enable-and'),
    'RiscayDesyncStop': Primitive('controller',
        ('reset', 'run', 'wake', 'requestIn', 'requestOut', 'pauseRequest', 'pauseGrant'), ('relative', 'absolute'),
        'Persistent stop request; one external filtered mutex arbitrates wake; operational stop does not reset grants', None, 1),
    'RiscayDesyncDelay': Primitive('delay_line', ('reset', 'in', 'out'), ('relative', 'absolute'),
        'POR clears feedback; physical discharge/release implementation unqualified', None),
    'RiscayDesyncMutex': Primitive('mutex',
        ('reset', 'request0', 'request1', 'grant0', 'grant1'), ('absolute',),
        'POR aborts grants; operational stop must not reset an active grant', None, 1,
        estimated_area_bound_mm2=.001),
}


def candidate_recipe(name, *, initial_open=False):
    """Unqualified standard-cell candidates, NOT accepted physical bindings.

    Restore the causal A+ condition described in Cortadella et al. (2006),
    Fig. 12 footnote 5, rather than assume Ro falls before Ri rises. With
    A=Ai, B=Ro and R=Ri: A_next=(R & !B) | (A & (R | !B | !Ao)).
    The original simplified recipe stalled under loaded composition. This
    factorization connects the missing dependency instead of adding a wait.
    The registered request input is AFTER the separately measured delay line.
    """
    entry = primitive(name)
    if entry.candidate is None:
        raise ValueError('DESYNC_CANDIDATE_UNAVAILABLE:' + name)
    if initial_open not in entry.initial_markings:
        raise ValueError('DESYNC_CANDIDATE_RESET_MARKING:' + name)
    if entry.candidate == 'gf180-flop-pair':
        return flop_bank_candidate()
    cells, cuts = [], []
    def cell(instance, kind, **pins):
        cells.append(dict(name=instance, cell='gf180mcu_fd_sc_mcu7t5v0__' + kind, pins=pins))
    if entry.candidate == 'gf180-semi-decoupled':
        cell('request_invert', 'inv_1', I='requestIn', ZN='requestLow')
        cell('request_feedback', 'inv_1', I='requestOut', ZN='requestFeedback')
        cell('request_set', 'and2_1', A1='requestIn', A2='requestFeedback', Z='set')
        cell('request_hold', 'nand3_1', A1='requestLow', A2='requestOut', A3='acknowledgeIn', ZN='hold')
        cell('ack_keeper', 'aoi21_1', A1='acknowledgeOut', A2='hold', B='set', ZN='ackLow')
        if initial_open:
            cell('reset_state', 'nor2_1', A1='ackLow', A2='reset', ZN='acknowledgeOut')
        else:
            cell('reset_invert', 'inv_1', I='reset', ZN='resetLow')
            cell('reset_state', 'nand2_1', A1='ackLow', A2='resetLow', ZN='acknowledgeOut')
        cell('enable_invert', 'inv_1', I='acknowledgeOut', ZN='enable')
        if initial_open:
            cell('request_keeper', 'aoi21_1', A1='acknowledgeIn', A2='requestFeedback', B='enable', ZN='requestOut')
        else:
            cell('request_keeper', 'aoi211_1', A1='acknowledgeIn', A2='requestFeedback', B='enable', C='reset', ZN='requestOut')
        # Internal keeper cuts only. The A->enable->request path remains intact.
        cuts = [('ack_keeper', 'A1', 'ZN'), ('request_feedback', 'I', 'ZN')]
    elif entry.candidate == 'gf180-c-element':
        cell('majority', 'aoi222_1', A1='input0', A2='input1', B1='input0', B2='out', C1='input1', C2='out', ZN='stateLow')
        if initial_open:
            cell('reset_invert', 'inv_1', I='reset', ZN='resetLow')
            cell('reset_state', 'nand2_1', A1='stateLow', A2='resetLow', ZN='out')
        else:
            cell('reset_state', 'nor2_1', A1='stateLow', A2='reset', ZN='out')
        cuts = [('majority', 'B2', 'ZN'), ('majority', 'C2', 'ZN')]
    elif entry.candidate == 'gf180-enable-and':
        cell('gate', 'and2_1', A1='enable', A2='condition', Z='out')
    else:
        raise ValueError('DESYNC_UNKNOWN_CANDIDATE')
    ports = (dict(reset='input', input0='input', input1='input', out='output') if entry.role == 'join' else
             {p: ('output' if p in ('requestOut', 'acknowledgeOut', 'enable') else 'input') for p in entry.pins})
    if entry.candidate == 'gf180-enable-and':
        ports = dict(enable='input', condition='input', out='output')
    if entry.candidate == 'gf180-semi-decoupled':
        stimulus = dict(reset=[(0, 1), (10, 0)])
        if initial_open:
            stimulus.update(requestIn=[(0, 0), (40, 1), (120, 0)], acknowledgeIn=[(0, 1), (80, 0), (160, 1)])
            expected = [(25, 0, 0, 1), (65, 1, 0, 0), (105, 1, 1, 0), (145, 1, 1, 0), (185, 0, 0, 1)]
            transitions = [('requestIn', 40, 1, 'acknowledgeOut', 1), ('acknowledgeIn', 80, 0, 'requestOut', 1),
                           ('acknowledgeIn', 160, 1, 'acknowledgeOut', 0), ('acknowledgeIn', 160, 1, 'requestOut', 0)]
        else:
            stimulus.update(requestIn=[(0, 0), (80, 1), (160, 0)], acknowledgeIn=[(0, 0), (40, 1), (120, 0), (200, 1)])
            expected = [(25, 1, 1, 0), (65, 0, 0, 1), (105, 1, 0, 0), (145, 1, 1, 0), (185, 1, 1, 0), (225, 0, 0, 1)]
            transitions = [('acknowledgeIn', 40, 1, 'acknowledgeOut', 0), ('acknowledgeIn', 40, 1, 'requestOut', 0),
                           ('requestIn', 80, 1, 'acknowledgeOut', 1), ('acknowledgeIn', 120, 0, 'requestOut', 1)]
        samples = [dict(at_ns=t, values=dict(acknowledgeOut=a, requestOut=b, enable=e)) for t, a, b, e in expected]
        samples.insert(0, dict(at_ns=5, values=dict(acknowledgeOut=int(not initial_open), requestOut=0, enable=int(initial_open))))
    elif entry.candidate == 'gf180-c-element':
        start = int(initial_open)
        stimulus = dict(reset=[(0, 1), (10, 0)], input0=[(0, start), (40, 1-start), (120, start)],
                        input1=[(0, start), (80, 1-start), (160, start)])
        samples = [dict(at_ns=t, values={'out': v}) for t, v in [(25, start), (65, start), (105, 1-start), (145, 1-start), (185, start)]]
        samples.insert(0, dict(at_ns=5, values={'out': start}))
        transitions = [('input1', 80, 1-start, 'out', 1-start), ('input1', 160, start, 'out', start)]
    else:
        stimulus = dict(enable=[(0, 0), (40, 1), (160, 0)], condition=[(0, 0), (80, 1), (120, 0)])
        samples = [dict(at_ns=t, values={'out': v}) for t, v in [(25, 0), (65, 0), (105, 1), (145, 0), (185, 0)]]
        transitions = [('condition', 80, 1, 'out', 1), ('condition', 120, 0, 'out', 0)]
    return dict(primitive=name, initial_open=initial_open, status='unqualified-candidate',
                ports=ports, cells=cells, local_keeper_arcs=cuts, keeper_bits=entry.keeper_bits,
                stimulus=stimulus, samples=samples, transitions=transitions)


def flop_bank_candidate():
    """Compose existing candidates; no payload copy or new state-machine kind.

    These two joins are additional to the predecessor/successor bundle joins.
    CPU self-dependencies are FF apertures, never external join inputs. This
    fixture does not yet implement the independent CPU/gate return edge.
    """
    name = 'RiscayDesyncFlopBank'
    result = dict(primitive=name, initial_open=False, status='unqualified-candidate',
        ports={p: ('output' if p in ('requestOut', 'acknowledgeOut') else 'input') for p in REGISTRY[name].pins},
        cells=[], local_keeper_arcs=[], keeper_bits=REGISTRY[name].keeper_bits)
    def add(label, recipe, binding):
        def net(n):
            return binding[n] if n in recipe['ports'] else label + '_' + n
        for c in recipe['cells']:
            result['cells'].append(dict(name=label+'_'+c['name'], cell=c['cell'],
                                        pins={p: net(n) for p, n in c['pins'].items()}))
        result['local_keeper_arcs'] += [(label+'_'+c, p, q) for c, p, q in recipe['local_keeper_arcs']]
    add('capture_join', candidate_recipe('RiscayDesyncJoin'),
        dict(reset='reset', input0='requestIn', input1='acknowledgeIn', out='captureReady'))
    add('publication_join', candidate_recipe('RiscayDesyncJoin'),
        dict(reset='reset', input0='acknowledgeIn', input1='acknowledgeOut', out='publicationReady'))
    add('master', candidate_recipe('RiscayDesyncController', initial_open=True),
        dict(reset='reset', requestIn='captureReady', acknowledgeIn='slaveA',
             requestOut='masterB', acknowledgeOut='acknowledgeOut', enable='masterEnable'))
    add('slave', candidate_recipe('RiscayDesyncController'),
        dict(reset='reset', requestIn='masterB', acknowledgeIn='publicationReady',
             requestOut='slaveB', acknowledgeOut='slaveA', enable='slaveEnable'))
    # Isolate the keeper from the sampled external load; no guessed delay chain.
    result['cells'].append(dict(name='publication_driver', cell='gf180mcu_fd_sc_mcu7t5v0__buf_2',
                                pins=dict(I='slaveB', Z='requestOut')))
    # Testbench-only stimuli: both arrival and return orders, including stalls.
    result['stimulus'] = dict(reset=[(0, 1), (10, 0)],
        requestIn=[(0, 0), (40, 1), (160, 0), (240, 1), (280, 0)],
        acknowledgeIn=[(0, 0), (80, 1), (120, 0), (200, 1), (320, 0)])
    result['samples'] = [dict(at_ns=t, values=dict(acknowledgeOut=a, requestOut=r)) for t, a, r in
        [(5, 0, 0), (25, 0, 1), (65, 0, 1), (105, 1, 0), (145, 1, 0), (185, 0, 1),
         (225, 0, 1), (265, 1, 0), (305, 1, 0), (345, 0, 1)]]
    result['transitions'] = [('acknowledgeIn', 80, 1, 'acknowledgeOut', 1),
        ('acknowledgeIn', 80, 1, 'requestOut', 0), ('requestIn', 160, 0, 'acknowledgeOut', 0),
        ('requestIn', 160, 0, 'requestOut', 1), ('acknowledgeIn', 320, 0, 'acknowledgeOut', 0),
        ('acknowledgeIn', 320, 0, 'requestOut', 1)]
    # Threshold-qualified causal propagation and a sampled pulse, not a
    # minimum-pulse guarantee or FF/enable-tree hold check.
    result['ordering'] = [dict(name='return_to_capture', after_ns=79,
        source='slaveB', source_rise=False, source_fraction=.3,
        target='slaveA', target_rise=True, target_fraction=.3),
        dict(name='slave_pulse', after_ns=79, source='slaveEnable', source_rise=True,
             source_fraction=.7, target='slaveEnable', target_rise=False, target_fraction=.7)]
    return result


def emit_candidate(recipe, module='PrimitiveFixture'):
    """Emit the exact candidate for independent simulation/characterization."""
    ports = recipe['ports']
    nets = {n for c in recipe['cells'] for n in c['pins'].values()} - ports.keys() - {'0', '1'}
    lines = ['module ' + module + '(' + ', '.join(ports) + ');']
    lines += [direction + ' wire ' + name + ';' for name, direction in ports.items()]
    if nets:
        lines.append('wire ' + ', '.join(sorted(nets)) + ';')
    def literal(net):
        return "1'b" + net if net in ('0', '1') else net
    lines += [c['cell'] + ' ' + c['name'] + '(' + ', '.join('.' + p + '(' + literal(n) + ')' for p, n in c['pins'].items()) + ');'
              for c in recipe['cells']]
    return '\n'.join([*lines, 'endmodule', ''])


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
