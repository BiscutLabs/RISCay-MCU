# SPDX-License-Identifier: Apache-2.0
"""Shared coverage and margin properties; independent of campaign size."""
from collections import Counter
import math


def require(ok, diagnostic):
    if not ok:
        raise ValueError(diagnostic)


def validate_cases(records, cases, residual, corners, slews):
    """Every selected owner/corner/slew must have its actual guard obligations."""
    owners = {r['owner'] for r in records}
    expected = {(owner, f'{corner}-s{slew}') for owner in owners
                for corner in corners for slew in slews}
    counts = Counter((c['instance'], c['key']) for c in cases)
    require(bool(expected) and set(counts) == expected and all(n == 1 for n in counts.values()),
            'TIMING_CASE_COVERAGE')
    require(math.isfinite(residual) and residual >= 0, 'TIMING_RESIDUAL')
    requirements = {}
    for record in records:
        metrics = {'output_delay': ('publication-rise', 'publication-fall'),
                   'request_delay': ('setup',),
                   'acknowledge_guard': ('hold', 'pulse-high', 'ack-after-rearm')}[record['primitive_id']]
        requirements.setdefault(record['owner'], set()).update(metrics)
    minima = {}; by_owner = {}
    for case in cases:
        required = requirements[case['instance']]
        require(required <= case['minima'].keys(), 'TIMING_METRIC_MISSING')
        require(all(isinstance(v, (int, float)) and math.isfinite(v)
                    for v in case['minima'].values()), 'TIMING_NONFINITE')
        require(all(case['minima'][m] >= residual for m in required), 'TIMING_NEGATIVE_MARGIN')
        if 'setup' in required:
            require(case['minima'].get('hold', -1) >= 0, 'TIMING_REQUEST_HOLD')
        target = by_owner.setdefault(case['instance'], {})
        for metric, value in case['minima'].items():
            minima[metric] = min(minima.get(metric, math.inf), value)
            target[metric] = min(target.get(metric, math.inf), value)
    return dict(case_count=len(cases), owner_count=len(owners), minima_ns=minima,
                owner_minima_ns=by_owner)


def period_invariant(before, after):
    """Changing an analysis clock's period must leave every measured row intact."""
    require(bool(before) and before == after, 'TIMING_PERIOD_DEPENDENCE')
