# SPDX-License-Identifier: Apache-2.0
"""Single catalogue for desynchronization primitives (not the frozen BD flow).

An unavailable physical recipe is an error, never an ordinary-logic substitute.
The GF180 mutex has experimental layout/views; no accepted physical binding.
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
    'RiscayDesyncQualifiedController': Primitive('controller',
        ('reset', 'requestIn', 'acknowledgeIn', 'same', 'closed', 'riseAllowed',
         'requestOut', 'acknowledgeOut', 'enable'), ('relative', 'absolute'),
        'Existing A/B keepers with one-sided closure and same-phase qualification; no added state',
        None, 2, candidate='gf180-qualified-controller', initial_markings=(False, True)),
    'RiscayDesyncCaptureJoin': Primitive('join',
        ('reset', 'request', 'downstream', 'rearmed', 'out'), ('relative', 'absolute'),
        'CPU readiness clears on request return; set requires current slave rearm',
        None, 1, candidate='gf180-capture-join'),
    'RiscayDesyncStop': Primitive('controller',
        ('reset', 'run', 'pauseRequest', 'pauseGrant'), ('relative', 'absolute'),
        'Persistent stop request; one external filtered mutex arbitrates wake; operational stop does not reset grants', None, 1),
    'RiscayDesyncDelay': Primitive('delay_line', ('reset', 'in', 'out'), ('relative', 'absolute'),
        'POR clears feedback; physical discharge/release implementation unqualified', None),
    'RiscayDesyncMutex': Primitive('mutex',
        ('reset', 'request0', 'request1', 'grant0', 'grant1'), ('absolute',),
        'POR aborts grants; operational stop must not reset an active grant', None, 1,
        estimated_area_bound_mm2=.001),
}


def qualified_controller(*, initial_open, same_count=0, closed_count=0, rise_qualified=False):
    """Approved closure qualification, folded into the existing A keeper.

    A+ requires all same-phase predecessors and optional CPU gate closure.
    A- requires all same-phase returns and one-sided receiver closure. A
    symmetric join on the latter would also constrain A+ and can deadlock.
    All reduction gates belong to this registered controller, not data logic.
    Gate-level hazards/isochronic forks still require physical qualification.
    """
    if type(same_count) is not int or type(closed_count) is not int or min(same_count, closed_count) < 0:
        raise ValueError('DESYNC_QUALIFIER_WIDTH')
    result = candidate_recipe('RiscayDesyncController', initial_open=initial_open)
    result['primitive'] = 'RiscayDesyncQualifiedController'
    result.pop('stimulus'); result.pop('samples'); result.pop('transitions')
    ports, cells = result['ports'], result['cells']
    def add(label, kind, **pins):
        cells.append(dict(name=label, cell='gf180mcu_fd_sc_mcu7t5v0__'+kind, pins=pins))
    set_net, hold_net = 'set', 'hold'
    for index in range(same_count):
        pin = 'same'+str(index); ports[pin] = 'input'
        next_set, next_hold = pin+'_set', pin+'_hold'
        add(next_set, 'and2_1', A1=set_net, A2=pin, Z=next_set)
        add(next_hold, 'or2_1', A1=hold_net, A2=pin, Z=next_hold)
        set_net, hold_net = next_set, next_hold
    for index in range(closed_count):
        pin = 'closed'+str(index); ports[pin] = 'input'
        low, next_hold = pin+'_low', pin+'_hold'
        add(low, 'inv_1', I=pin, ZN=low)
        add(next_hold, 'or2_1', A1=hold_net, A2=low, Z=next_hold)
        hold_net = next_hold
    if rise_qualified:
        ports['riseAllowed'] = 'input'
        add('qualified_set', 'and2_1', A1=set_net, A2='riseAllowed', Z='qualifiedSet')
        set_net = 'qualifiedSet'
    keeper = next(c for c in cells if c['name']=='ack_keeper')
    keeper['pins'].update(A2=hold_net, B=set_net)
    result['qualification'] = dict(same_count=same_count, closed_count=closed_count, rise_qualified=rise_qualified)
    return result


def capture_join_candidate():
    """Same one-bit storage as the old readiness join; explicit rearm cause."""
    return dict(primitive='RiscayDesyncCaptureJoin', initial_open=False,
        status='unqualified-candidate', keeper_bits=1,
        ports=dict(reset='input', request='input', downstream='input', rearmed='input', out='output'),
        cells=[dict(name=n, cell='gf180mcu_fd_sc_mcu7t5v0__'+k, pins=p) for n,k,p in (
            ('ready', 'and2_1', dict(A1='downstream', A2='rearmed', Z='ready')),
            ('hold', 'or2_1', dict(A1='ready', A2='out', Z='hold')),
            ('set', 'nand2_1', dict(A1='request', A2='hold', ZN='stateLow')),
            ('reset_state', 'nor2_1', dict(A1='stateLow', A2='reset', ZN='out')))],
        local_keeper_arcs=[('hold','A2','Z')])


def resolve_candidate(name, parameters=None):
    result=_resolve_candidate(name,parameters)
    # Yosys JSON has one namespace for cells and wires. Keep recipe labels
    # distinct from internal nets without teaching each consumer a renamer.
    for cell in result['cells']:cell['name']+='__cell'
    result['local_keeper_arcs']=[(n+'__cell',a,b) for n,a,b in result['local_keeper_arcs']]
    return result


def _resolve_candidate(name, parameters=None):
    """Registry-owned parameter and port expansion for experimental bindings.

    It never makes require_recipe succeed: candidate connectivity/area and
    qualified physical acceptance are different operations.
    """
    parameters=parameters or {}
    if name=='RiscayDesyncQualifiedController':return qualified_controller(**parameters)
    if name=='RiscayDesyncCaptureJoin':
        if parameters:raise ValueError('DESYNC_CANDIDATE_PARAMETERS')
        return capture_join_candidate()
    if name=='RiscayDesyncStop':
        if parameters:raise ValueError('DESYNC_CANDIDATE_PARAMETERS')
        r=candidate_recipe('RiscayDesyncJoin')
        rename=dict(input0='runLow',input1='grantLow',out='pauseRequest')
        for c in r['cells']:c['pins']={p:rename.get(n,n) for p,n in c['pins'].items()}
        r['cells'] += [dict(name='run_invert',cell='gf180mcu_fd_sc_mcu7t5v0__inv_1',pins=dict(I='run',ZN='runLow')),
                       dict(name='grant_invert',cell='gf180mcu_fd_sc_mcu7t5v0__inv_1',pins=dict(I='pauseGrant',ZN='grantLow'))]
        r.update(primitive=name,ports=dict(reset='input',run='input',pauseGrant='input',pauseRequest='output'))
        return r
    if name=='RiscayDesyncMutex':
        if parameters:raise ValueError('DESYNC_CANDIDATE_PARAMETERS')
        return dict(primitive=name,status='experimental-layout-only',keeper_bits=1,
            ports={p:('output' if p.startswith('grant') else 'input') for p in REGISTRY[name].pins},
            cells=[dict(name='mutex',cell='ca_mutex_gf180_candidate',
                pins=dict(RESET='reset',R0='request0',R1='request1',G0='grant0',G1='grant1'))],local_keeper_arcs=[])
    return candidate_recipe(name,**parameters)


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
    if entry.candidate == 'gf180-qualified-controller':
        r=qualified_controller(initial_open=initial_open,same_count=1,closed_count=1)
        base=candidate_recipe('RiscayDesyncController',initial_open=initial_open)
        r.update({k:base[k] for k in ('stimulus','samples','transitions')})
        r['stimulus']['same0']=([(0,0),(35,1),(150,0)] if initial_open else
                               [(0,1),(35,0),(75,1),(190,0)])
        r['stimulus']['closed0']=[(0,1)]
        return r
    if entry.candidate == 'gf180-capture-join':
        r=capture_join_candidate()
        r['stimulus']=dict(reset=[(0,1),(10,0)],request=[(0,0),(40,1),(160,0),(200,1),(320,0)],
            downstream=[(0,0),(80,1),(280,0)],rearmed=[(0,0),(120,1),(190,0),(240,1)])
        r['samples']=[dict(at_ns=t,values={'out':v}) for t,v in
            [(5,0),(25,0),(65,0),(105,0),(145,1),(185,0),(225,0),(265,1),(305,1),(345,0)]]
        r['transitions']=[('rearmed',120,1,'out',1),('request',160,0,'out',0),
                          ('rearmed',240,1,'out',1),('request',320,0,'out',0)]
        return r
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


def classified_cells(bindings, *, experimental=False):
    """Return exact leaf membership; never classify by name substring."""
    result = {}
    for binding in bindings:
        entry = primitive(binding['primitive'])
        if experimental:
            expected=resolve_candidate(binding['primitive'],binding.get('parameters'))
            pins=expected['ports']
            if binding['cells']!=expected['cells']:raise ValueError('DESYNC_CANDIDATE_RECIPE_CHANGED')
        else:
            require_recipe(binding['primitive']);pins=entry.pins
        if set(binding['ports']) != set(pins) or not binding['cells']:
            raise ValueError('DESYNC_PRIMITIVE_SHAPE')
        for cell in binding['cells']:
            path = binding['instance'] + '/' + cell['name']
            if path in result:
                raise ValueError('DESYNC_DUPLICATE_PRIMITIVE_CELL')
            result[path] = (entry.role, cell)
    return result
