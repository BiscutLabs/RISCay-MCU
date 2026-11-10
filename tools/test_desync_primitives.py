# SPDX-License-Identifier: Apache-2.0
from itertools import product
import unittest
from characterize_desync_primitives import measurements
from primitives import candidate_recipe, emit_candidate, require_recipe


def outputs(recipe, state, inputs):
    """Evaluate standard-cell functions with keeper outputs cut only in this
    next-state truth-table test. Physical characterization keeps every loop.
    """
    values = dict(state, **inputs)
    remaining, next_state = list(recipe['cells']), {}
    while remaining:
        for c in remaining[:]:
            kind, pins = c['cell'].split('__')[1].rsplit('_', 1)[0], c['pins']
            output = 'Z' if 'Z' in pins else 'ZN'
            if any(n not in values for p, n in pins.items() if p != output):
                continue
            a = {p: values[n] for p, n in pins.items() if p != output}
            if kind == 'inv': v = not a['I']
            elif kind == 'buf': v = a['I']
            elif kind == 'and2': v = a['A1'] and a['A2']
            elif kind == 'nand2': v = not (a['A1'] and a['A2'])
            elif kind == 'nand3': v = not (a['A1'] and a['A2'] and a['A3'])
            elif kind == 'nor2': v = not (a['A1'] or a['A2'])
            elif kind == 'aoi22': v = not (a['A1'] and a['A2'] or a['B1'] and a['B2'])
            elif kind == 'aoi21': v = not (a['A1'] and a['A2'] or a['B'])
            elif kind == 'aoi211': v = not (a['A1'] and a['A2'] or a['B'] or a['C'])
            elif kind == 'aoi222': v = not (a['A1'] and a['A2'] or a['B1'] and a['B2'] or a['C1'] and a['C2'])
            else: raise AssertionError('Unsupported test function: ' + kind)
            net = pins[output]
            if net in state: next_state[net] = int(v)
            else: values[net] = int(v)
            remaining.remove(c)
            break
        else:
            raise AssertionError('Recipe has an unbound signal or unexpected state')
    return values | next_state


class PrimitiveTests(unittest.TestCase):
    def test_mutation_constants_remain_valid_verilog(self):
        r = candidate_recipe('RiscayDesyncController')
        next(c for c in r['cells'] if c['name'] == 'request_hold')['pins']['A1'] = '0'
        text = emit_candidate(r)
        self.assertIn(".A1(1'b0)", text)
        self.assertNotIn('wire 0', text)

    def test_factored_controller_matches_the_published_state_equations(self):
        for opened in (False, True):
            r = candidate_recipe('RiscayDesyncController', initial_open=opened)
            for reset, request, downstream, a, b in product((0, 1), repeat=5):
                got = outputs(r, dict(acknowledgeOut=a, requestOut=b),
                              dict(reset=reset, requestIn=request, acknowledgeIn=downstream))
                ack = not opened if reset else (request and not b) or (a and (request or not b or not downstream))
                offer = not ((not a) or (downstream and not b) or (reset and not opened))
                self.assertEqual(got['acknowledgeOut'], ack)
                self.assertEqual(got['requestOut'], offer)
                self.assertEqual(got['enable'], not a)
            self.assertEqual(r['keeper_bits'], len({'acknowledgeOut', 'requestOut'}))
            self.assertIn('module PrimitiveFixture', emit_candidate(r))
            with self.assertRaisesRegex(ValueError, 'RECIPE_UNAVAILABLE'):
                require_recipe('RiscayDesyncController')

    def test_cpu_composition_matches_the_two_joins_and_causal_controllers(self):
        r = candidate_recipe('RiscayDesyncFlopBank')
        names = ('acknowledgeOut', 'masterB', 'slaveA', 'slaveB', 'captureReady', 'publicationReady')
        def join(a, b, old): return a if a == b else old
        def ack(rq, offer, downstream, old): return (rq and not offer) or (old and (rq or not offer or not downstream))
        for bits in product((0, 1), repeat=8):
            a, b, c, d, rq, ao, source, sink = bits
            got = outputs(r, dict(zip(names, bits)), dict(reset=0, requestIn=source, acknowledgeIn=sink))
            expected = (ack(rq, b, c, a), a and (b or not c), ack(b, d, ao, c), c and (d or not ao),
                        join(source, sink, rq), join(sink, a, ao))
            self.assertEqual(tuple(got[n] for n in names), expected)
        self.assertEqual(r['keeper_bits'], len(names))
        with self.assertRaisesRegex(ValueError, 'RESET_MARKING'):
            candidate_recipe('RiscayDesyncFlopBank', initial_open=True)

    def test_join_retains_disagreement_and_honors_both_reset_values(self):
        for initial in (False, True):
            r = candidate_recipe('RiscayDesyncJoin', initial_open=initial)
            for reset, a, b, q in product((0, 1), repeat=4):
                got = outputs(r, dict(out=q), dict(reset=reset, input0=a, input1=b))
                self.assertEqual(got['out'], initial if reset else a if a == b else q)

    def test_spice_checker_rejects_missing_wrong_and_nonpositive_evidence(self):
        r = candidate_recipe('RiscayDesyncController')
        rows = [f'state_{i}_{name.lower()} = {bit*3.3}' for i, s in enumerate(r['samples']) for name, bit in s['values'].items()]
        rows += [f'{kind}_{i} = 1e-9' for i in range(len(r['transitions'])) for kind in ('delay', 'slew')]
        valid = '\n'.join(rows)
        self.assertTrue(measurements(valid, r, 3.3))
        high = next(row for row in rows if row.startswith('state_') and row.endswith('= 3.3'))
        for bad in (valid.replace(high, high.replace('3.3', '0')),
                    '\n'.join(rows[:-1]), valid.replace('delay_0 = 1e-9', 'delay_0 = -1e-9'),
                    valid + '\nError: no convergence'):
            with self.assertRaises(ValueError): measurements(bad, r, 3.3)


if __name__ == '__main__':
    unittest.main()
