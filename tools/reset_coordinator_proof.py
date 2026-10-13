# SPDX-License-Identifier: Apache-2.0
"""Finite proof of the actual service/work reset-coordination boundary.

This closes the integration assumptions of the local receiver proofs. It proves
clocked receipt ownership, complete joins, actual control pins and coordinator
equations; it does not qualify related-clock timing or native reset propagation.
"""
from itertools import product
import re

from reset_bridge_proof import Cone


BRIDGES = ('request', 'admission_grant', 'completion_plan',
           'completion_telemetry', 'completion_housekeeping')
REGISTERS = dict(state=(2, 1), stopped=(1, 1), nativeHeld=(1, 1),
                 coreHeld=(1, 1), rebasing=(1, 0), count=(3, 0))


def require(condition, reason):
    if not condition:
        raise ValueError('RDC_COORDINATOR_' + reason)


def register(cone, name, clock, reset, width, value):
    identity, cell = cone.flop(name)
    pins, parameters = cell['connections'], cell['parameters']
    require(len(pins['Q']) == width and pins['CLK'] == clock and pins['ARST'] == reset
            and parameters['CLK_POLARITY'] == '1' and parameters['ARST_POLARITY'] == '1'
            and int(parameters['ARST_VALUE'], 2) == value, 'REGISTER_' + name)
    return identity, cell


def receipt(cone, name, clock, reset, source):
    identity, cell = register(cone, name, clock, reset, 1, 0)
    require(cell['connections']['D'] == source, 'RECEIPT_' + name)
    return identity, cell['connections']['Q']


def work_clock(cone):
    # Inline and ordinary emitters retain different aliases of the same gate
    # output. Require exact agreement when more than one alias survives, and
    # prove the gate equation rather than trusting any alias name alone.
    aliases = [cone.bits(name) for name in ('workClock', 'gate_io_clockOut', 'fabric_clock')
               if name in cone.module['netnames']]
    require(bool(aliases) and all(value == aliases[0] for value in aliases), 'WORK_CLOCK_ALIASES')
    clock = aliases[0]
    for service, enabled in product(range(2), repeat=2):
        env = {}
        cone.bind(env, cone.bits('serviceClock'), service)
        cone.bind(env, cone.bits('gate_enabled'), enabled)
        require(cone.evaluate(clock, env) == (service and enabled), 'WORK_CLOCK_EQUATION')
    return clock


def helper(cone, rows, reason):
    """Find one owner-local Boolean cone by its complete truth table.

    Inline assertions change firtool's anonymous helper numbering. Equivalent
    aliases of one bit are harmless; two different candidate bits are rejected.
    A candidate is usable only when every input combination proves its equation.
    The later D-equation proof must actually use the proved cone: unrelated or
    bypassed receipt inputs remain unbound and cannot become proof assumptions.
    """
    matches = set()
    for name, net in cone.module['netnames'].items():
        if not re.fullmatch(r'resetBoundary_(?:_[0-9]+)?', name) or len(net['bits']) != 1:
            continue
        try:
            valid = all(cone.evaluate(net['bits'], env) == expected for env, expected in rows)
        except ValueError:
            valid = False
        if valid:
            matches.add(tuple(net['bits']))
    require(len(matches) == 1, reason)
    return list(matches.pop())


def transition(state, stopped, native, core, rebase, count, observed,
               closed, holding_blocked, reopen_ready):
    """Independent four-state service-clock contract, including retrigger."""
    if state == 0:
        if observed:
            stopped, state = 1, 1
    elif state == 1:
        if closed:
            native, core, rebase, count, state = 1, 1, 1, 0, 2
    elif state == 2:
        if holding_blocked:
            count = 0
        elif count == 7:
            native, rebase, count, state = 0, 0, 0, 3
        else:
            count += 1
    elif observed:
        state, count = 1, 0
    elif reopen_ready:
        stopped, core, state = 0, 0, 0
    elif count == 0:
        count = 1
    return dict(state=state, stopped=stopped, nativeHeld=native,
                coreHeld=core, rebasing=rebase, count=count)


def prove_coordinator(module, por_reset):
    cone = Cone(module)
    bits = cone.bits
    por, service, work = bits('reset'), bits('serviceClock'), work_clock(cone)
    registers = {name: register(cone, 'resetBoundary_' + name, service, por, width, initial)
                 for name, (width, initial) in REGISTERS.items()}
    cutoff, rebase = bits('applicationCancel'), bits('resetBoundary_rebasing')
    observed = bits('cpuResetActive')
    first = register(cone, 'cpuResetActive_first', service, por, 1, 1)
    second = register(cone, 'cpuResetActive', service, por, 1, 1)
    require(first[1]['connections']['D'] == bits('systemReset') and
            second[1]['connections']['D'] == first[1]['connections']['Q'], 'RESET_OBSERVER')

    closures, rebases, receipt_registers = [], [], []
    for name in BRIDGES:
        prefix = 'ca_child_' + name + '_bridge'
        clock = service if name == 'request' else work
        local_reset = bits(prefix + '.localReset_release_1')
        require(bits(prefix + '.clock') == clock and por_reset(local_reset, clock),
                'BRIDGE_CLOCK_RESET_' + name)
        require(bits(prefix + '.close') == cutoff and bits(prefix + '.rebase') == rebase,
                'BRIDGE_CONTROL_' + name)
        for field, source, collection in (('closed', cutoff, closures), ('rebased', rebase, rebases)):
            identity, value = receipt(cone, prefix + '.' + field, clock, local_reset, source)
            receipt_registers.append(identity)
            collection.append(value)
    # Inlining can erase the Services input alias. The actual receipt D pin
    # below still has to be the shared cutoff, without an alias exemption.
    identity, value = receipt(cone, 'fabric_io_presentationClosed_REG', work, por, cutoff)
    receipt_registers.append(identity)
    closures.append(value)
    require(len({tuple(v) for v in closures}) == 6 and len({tuple(v) for v in rebases}) == 5,
            'DISTINCT_RECEIPTS')

    # Prove every combination of the six actual receipt outputs before using
    # their joined result as a cutpoint in the sequential equation proof.
    closed = bits('resetBoundary_io_closed')
    for values in product(range(2), repeat=6):
        env = {}
        for vector, value in zip(closures, values):
            cone.bind(env, vector, value)
        require(cone.evaluate(closed, env) == all(values), 'CLOSURE_JOIN')

    # Complete truth tables identify the actual ACK-high and ACK-low helper
    # cones despite anonymous helper renumbering between emitter modes.
    blocked_rows, ready_rows = [], []
    for values in product(range(2), repeat=5):
        for seen in range(2):
            env = {}
            for vector, value in zip(rebases, values):
                cone.bind(env, vector, value)
            cone.bind(env, observed, seen)
            blocked_rows.append((env, seen or not all(values)))
        for count in range(8):
            env = {}
            for vector, value in zip(rebases, values):
                cone.bind(env, vector, value)
            cone.bind(env, bits('resetBoundary_count'), count)
            ready_rows.append((env, count == 1 and not any(values)))
    blocked = helper(cone, blocked_rows, 'REBASE_JOIN')
    ready = helper(cone, ready_rows, 'WITHDRAWAL_JOIN')

    for p, stopped, native, core, seen in product(range(2), repeat=5):
        env = {}
        for vector, value in ((por, p), (bits('resetBoundary_stopped'), stopped),
                              (bits('resetBoundary_nativeHeld'), native),
                              (bits('resetBoundary_coreHeld'), core), (observed, seen)):
            cone.bind(env, vector, value)
        for name, expected in (('applicationCancel', stopped or seen),
                               ('nativeApplicationReset', p or native), ('nativeCoreReset', p or core)):
            require(cone.evaluate(bits(name), env) == expected, 'OUTPUT_' + name)

    rows = 0
    for state, flags, count, inputs in product(range(4), range(16), range(8), range(16)):
        stopped, native, core, rebase_value = ((flags >> bit) & 1 for bit in range(4))
        seen, closed_value, blocked_value, ready_value = ((inputs >> bit) & 1 for bit in range(4))
        current = dict(state=state, stopped=stopped, nativeHeld=native, coreHeld=core,
                       rebasing=rebase_value, count=count)
        env = {}
        for name, value in current.items():
            cone.bind(env, registers[name][1]['connections']['Q'], value)
        for vector, value in ((observed, seen), (closed, closed_value),
                              (blocked, blocked_value), (ready, ready_value)):
            cone.bind(env, vector, value)
        expected = transition(state, stopped, native, core, rebase_value, count,
                              seen, closed_value, blocked_value, ready_value)
        cache = {}
        for name, value in expected.items():
            require(cone.evaluate(registers[name][1]['connections']['D'], env, cache) == value,
                    'TRANSITION_' + name)
        rows += 1
    return dict(prefix='applicationResetCoordinator', rows=rows,
                closure_rows=64, rebase_rows=64, withdrawal_rows=256, output_rows=32,
                receipt_registers=receipt_registers,
                scope='actual POR receipt pins, complete joins and finite service FSM; no physical timing claim')
