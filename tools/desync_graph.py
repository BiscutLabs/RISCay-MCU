# SPDX-License-Identifier: Apache-2.0
"""Semi-decoupled marked-graph screening, not an electrical/controller proof.

The five arcs per adjacent latch pair are Fig. 11 of Cortadella et al., TCAD
2006. CPU FF contraction is an experiment: timing apertures are not places.
Mixed-edge, macro and gated-clock composition must be supplied before this
screen can qualify the real MCU. A projected positive-edge pass is not a pass.
"""
import argparse
from collections import defaultdict
import heapq
import json
from pathlib import Path


def compose(partition, flop_banks=()):
    banks, flops = set(partition['banks']), set(flop_banks)
    if not flops <= banks:
        raise ValueError('DESYNC_UNKNOWN_FLOP_BANK')
    arcs, apertures = {}, set()

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
        link(bank + '.m', bank + '.s', True)
    for edge in partition['edges']:
        if edge['source'] not in banks or edge['target'] not in banks or not edge['witnesses']:
            raise ValueError('DESYNC_UNWITNESSED_DEPENDENCY')
        link(edge['source'] + '.s', edge['target'] + '.m', False)
    return dict(arcs=[dict(source=a, target=b, tokens=m) for (a, b), m in sorted(arcs.items())],
                flop_banks=sorted(flops), aperture_obligations=sorted(apertures))


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


def screen(partition, flop_banks=()):
    marked = compose(partition, flop_banks)
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
    return dict(status='incomplete', scope='positive-edge topology projection only',
                projection=result, graph=marked, unresolved=obligations + [
                    'controller implementation correspondence', 'arbitrary-stop handshake rest',
                    'reset epochs, clocked external inputs and synchronizer sampling',
                    'loaded per-corner timing and cycle time'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('partition', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--flop-bank', action='append', default=[])
    args = parser.parse_args()
    report = screen(json.loads(args.partition.read_text()), args.flop_bank)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'graph'}))
    # Deliberately cannot be mistaken for whole-chip graph acceptance.
    raise SystemExit(2)
