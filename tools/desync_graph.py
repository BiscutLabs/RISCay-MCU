# SPDX-License-Identifier: Apache-2.0
"""Semi-decoupled marked-graph screening, not an electrical/controller proof.

The five arcs per adjacent latch pair are Fig. 11 of Cortadella et al., TCAD
2006. CPU FF contraction is an experiment: timing apertures are not places.
Mixed-edge, macro and gated-clock composition must be supplied before this
screen can qualify the real MCU. A projected positive-edge pass is not a pass.
"""
import argparse
from collections import defaultdict, deque
import heapq
import json
from pathlib import Path


def compose(partition, flop_banks=(), *, phase_aware=False):
    banks, flops = set(partition['banks']), set(flop_banks)
    if not flops <= banks:
        raise ValueError('DESYNC_UNKNOWN_FLOP_BANK')
    arcs, apertures, transparent = {}, set(), []

    def event(latch, sign):
        bank, phase = latch.split('.')
        if bank in flops:
            return bank + ('.rise' if (phase, sign) in (('m', '-'), ('s', '+')) else '.fall')
        return latch + sign

    def put(a, b, tokens):
        left, right = event(*a), event(*b)
        if left == right:
            # Only the local FF's two atomic aperture relations may contract.
            # Never discard an inter-bank edge or turn it into a delay.
            if (a[0].split('.')[0] != b[0].split('.')[0] or tokens or
                    (a[0].split('.')[1], a[1], b[0].split('.')[1], b[1]) not in
                    (('s', '-', 'm', '+'), ('m', '-', 's', '+'))):
                raise ValueError('DESYNC_ILLEGAL_ATOMIC_CONTRACTION')
            apertures.add((a[0] + a[1], b[0] + b[1]))
            return
        key = left, right
        if key in arcs and arcs[key] != tokens:
            raise ValueError('DESYNC_CONFLICTING_MARKING')
        arcs[key] = tokens

    def link(a, b, a_open):
        for latch, opened in ((a, a_open), (b, not a_open)):
            put((latch, '+'), (latch, '-'), int(opened))
        put((a, '+'), (b, '+'), int(a_open))
        put((a, '-'), (b, '-'), int(not a_open))
        put((b, '-'), (a, '+'), 0)

    for bank in sorted(banks):
        phases = {r['falling'] for r in partition['registers'] if r['transformed'] and r['bank'] == bank}
        if not phase_aware or not phases or False in phases:
            link(bank + '.m', bank + '.s', True)
        if phase_aware and True in phases:
            link(bank + '.s', bank + '.m', False)
    if not phase_aware:
        for edge in partition['edges']:
            if edge['source'] not in banks or edge['target'] not in banks or not edge['witnesses']:
                raise ValueError('DESYNC_UNWITNESSED_DEPENDENCY')
            link(edge['source'] + '.s', edge['target'] + '.m', False)
    else:
        if any(r['bank'] in flops and r['falling'] for r in partition['registers'] if r['transformed']):
            raise ValueError('DESYNC_MIXED_FLOP_BANK')
        for edge in partition['phase_edges']:
            source, target = edge['source'], edge['target']
            if source.startswith('@'):
                if edge['role'] in ('gate', 'falling_gate'):
                    raise ValueError('DESYNC_EXTERNAL_GATE_QUALIFIER')
                continue
            if source not in banks or target not in banks or not edge['witnesses']:
                raise ValueError('DESYNC_UNWITNESSED_DEPENDENCY')
            ap, bp = edge['source_phase'], edge['target_phase']
            if ap not in ('rise', 'fall', 'macro') or bp not in ('rise', 'fall', 'macro'):
                raise ValueError('DESYNC_UNKNOWN_CAPTURE_PHASE')
            a = source + ('.m' if ap == 'fall' else '.s')
            if edge['role'] in ('gate', 'falling_gate'):
                # The source holds the qualifier throughout the *architectural*
                # slave enable. Masters track while disabled; no copy is added.
                if (edge['role'] == 'gate' and bp == 'fall'):
                    continue  # falling capture uses previous, not new enabled
                b = target + ('.m' if bp == 'fall' else '.s')
                if a == b:
                    raise ValueError('DESYNC_GATE_QUALIFIER_TRANSPARENT')
                put((a, '-'), (b, '+'), 0)
                put((b, '-'), (a, '+'), 0)
            else:
                b = target + ('.s' if bp in ('fall', 'macro') else '.m')
                if a[-1] != b[-1]:
                    link(a, b, a.endswith('.m'))
                else:
                    # Opposite-edge storage produces a transparent same-phase
                    # cone. Keep cross-bank causal order, but never pretend its
                    # settling/pulse aperture is proved by a token count.
                    transparent.append(dict(source=a, target=b, witnesses=edge['witnesses']))
                    if a != b:
                        put((a, '+'), (b, '+'), 0)
                        put((a, '-'), (b, '-'), 0)
                    put((b, '-'), (a, '+'), int(a.endswith('.s')))
        for macro in partition.get('macros', []):
            # The SRAM rising access may change Q. Close the old-value master
            # before that event, even if a semi-decoupled latch would overlap.
            b = macro['bank']
            put((b + '.m', '-'), (b + '.s', '+'), 0)
    return dict(arcs=[dict(source=a, target=b, tokens=m) for (a, b), m in sorted(arcs.items())],
                flop_banks=sorted(flops), aperture_obligations=sorted(apertures),
                phase_aware=phase_aware, transparent_cones=transparent)


def reachable_stop(marked, stop, *, limit=100000):
    """Exhaustive *abstract* stop check, from every reachable graph marking.

    Control-wire correspondence is a separate obligation. A state-space limit
    is a failure, not evidence. No fairness assumption hides a stop-time cycle.
    """
    analyze(marked, stop)
    incoming, outgoing, initial = defaultdict(int), defaultdict(int), 0
    for i, row in enumerate(marked['arcs']):
        incoming[row['target']] |= 1 << i
        outgoing[row['source']] |= 1 << i
        initial |= row['tokens'] << i
    nodes = sorted(incoming)
    masks = [(incoming[n], outgoing[n]) for n in nodes]
    stop_index = nodes.index(stop)
    states, seen, successors = [initial], {initial: 0}, []
    cursor = 0
    while cursor < len(states):
        value, next_rows = states[cursor], []
        for transition, (pre, post) in enumerate(masks):
            if value & pre != pre:
                continue
            remainder = value & ~pre
            if remainder & post:
                raise ValueError('DESYNC_REACHABLE_UNSAFE_PLACE:' + nodes[transition])
            after = remainder | post
            if after not in seen:
                if len(states) >= limit:
                    raise ValueError('DESYNC_GRAPH_STATE_LIMIT')
                seen[after] = len(states); states.append(after)
            if transition != stop_index:
                next_rows.append(seen[after])
        successors.append(next_rows)
        cursor += 1
    # Acyclic restricted graph => every possible ordering drains. Longest path
    # counts all firings after stop, including starting from noninitial states.
    indegree = [0] * len(states)
    for rows in successors:
        for nxt in rows:
            indegree[nxt] += 1
    todo = deque(i for i, d in enumerate(indegree) if not d)
    order = []
    while todo:
        i = todo.popleft(); order.append(i)
        for nxt in successors[i]:
            indegree[nxt] -= 1
            if not indegree[nxt]:
                todo.append(nxt)
    if len(order) != len(states):
        raise ValueError('DESYNC_STOP_REACHABLE_CYCLE')
    terminal = [i for i, rows in enumerate(successors) if not rows]
    if len(terminal) != 1:
        raise ValueError('DESYNC_STOP_MULTIPLE_REST_MARKINGS')
    distance = [0] * len(states)
    for i in reversed(order):
        distance[i] = max((1 + distance[n] for n in successors[i]), default=0)
    rest = states[terminal[0]]
    levels = {row['source'][:-1]: (rest >> i) & 1 for i, row in enumerate(marked['arcs'])
              if row['source'].endswith('+') and row['target'] == row['source'][:-1] + '-'}
    for bank in marked['flop_banks']:
        index = next(i for i, row in enumerate(marked['arcs'])
                     if (row['source'], row['target']) == (bank + '.rise', bank + '.fall'))
        levels[bank + '.pulse'] = (rest >> index) & 1
    return dict(reachable_markings=len(states), maximum_firings_after_stop=max(distance),
                unique_rest_marking=True, rest_levels=levels, control_wire_rest_proved=False)


def shortest(arcs, start):
    successors = defaultdict(list)
    for (a, b), weight in arcs.items():
        successors[a].append((b, weight))
    distance, todo = {start: 0}, [(0, start)]
    while todo:
        cost, node = heapq.heappop(todo)
        if distance[node] != cost:
            continue
        for target, weight in successors[node]:
            value = cost + weight
            if value < distance.get(target, float('inf')):
                distance[target] = value
                heapq.heappush(todo, (value, target))
    return distance


def analyze(marked, stop):
    arcs = {}
    for row in marked['arcs']:
        key = row['source'], row['target']
        if key in arcs or type(row['tokens']) is not int or row['tokens'] not in (0, 1):
            raise ValueError('DESYNC_INVALID_MARKED_GRAPH')
        arcs[key] = row['tokens']
    nodes = {n for pair in arcs for n in pair}
    if not nodes or stop not in nodes:
        raise ValueError('DESYNC_GRAPH_STOP_MISSING')
    distances = {n: shortest(arcs, n) for n in nodes}
    if any(set(d) != nodes for d in distances.values()):
        raise ValueError('DESYNC_GRAPH_NOT_STRONGLY_CONNECTED')
    for (a, b), mark in arcs.items():
        cycle = mark + distances[b][a]
        if cycle == 0:
            raise ValueError(f'DESYNC_TOKENLESS_CYCLE:{a}->{b}')
        if cycle != 1:
            raise ValueError(f'DESYNC_ONE_SAFE_CERTIFICATE_MISSING:{a}->{b}')
    # For each path from inhibited stop to t: firings(t) <= initial path tokens.
    # This is a finite drain bound from this marking, NOT proof that all latch
    # enables finish closed or that the same marking is reached after any stop.
    return dict(live=True, one_safe=True, drain_bound_from_initial=distances[stop],
                handshake_rest_proved=False, cycle_time_ns=None)


def screen(partition, flop_banks=(), *, phase_aware=False, exhaustive=False):
    marked = compose(partition, flop_banks, phase_aware=phase_aware)
    stop = partition['stop_bank'] + ('.rise' if partition['stop_bank'] in flop_banks else '.m-')
    result = analyze(marked, stop)
    obligations = []
    if any(r['transformed'] and r['falling'] for r in partition['registers']):
        obligations.append('opposite-phase launch, half-cycle aperture and reset marking')
    if partition['gated_domains']:
        obligations.append('per-register enable gating and stable gate phase')
    if any(e['source_phase'] == 'macro' or e['target_phase'] == 'macro' for e in partition['phase_edges']):
        obligations.append('macro access, launch/capture phases and absolute pulse widths')
    if flop_banks:
        obligations.append('contracted FF setup/hold and minimum high/low pulse widths')
    return dict(status='incomplete', scope=('mixed-edge abstract graph' if phase_aware else 'positive-edge topology projection only'),
                projection=result, graph=marked, unresolved=obligations + [
                    'controller implementation correspondence', 'arbitrary-stop handshake rest',
                    'reset epochs, clocked external inputs and synchronizer sampling',
                    'loaded per-corner timing and cycle time'],
                abstract_stop=reachable_stop(marked, stop) if exhaustive else None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('partition', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--flop-bank', action='append', default=[])
    parser.add_argument('--phase-aware', action='store_true')
    parser.add_argument('--reachable-stop', action='store_true')
    args = parser.parse_args()
    report = screen(json.loads(args.partition.read_text()), args.flop_bank,
                    phase_aware=args.phase_aware, exhaustive=args.reachable_stop)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'graph'}))
    # Deliberately cannot be mistaken for whole-chip graph acceptance.
    raise SystemExit(2)
