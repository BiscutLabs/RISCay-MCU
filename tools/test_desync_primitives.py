# SPDX-License-Identifier: Apache-2.0
from itertools import product
import unittest
from characterize_desync_primitives import measurements, retained_wave
from primitives import candidate_recipe, emit_candidate, require_recipe, qualified_controller, capture_join_candidate, resolve_candidate, transition_contexts
from measure_desync_transitions import fixture, arc_polarities


def outputs(recipe, state, inputs):
    """Evaluate standard-cell functions with keeper outputs cut only in this
    next-state truth-table test. Physical characterization keeps every loop.
    """
    values = {'0':0,'1':1} | state | inputs
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
            elif kind == 'or2': v = a['A1'] or a['A2']
            elif kind == 'nand2': v = not (a['A1'] and a['A2'])
            elif kind == 'nand3': v = not (a['A1'] and a['A2'] and a['A3'])
            elif kind == 'nand4': v = not (a['A1'] and a['A2'] and a['A3'] and a['A4'])
            elif kind == 'mux2': v = a['I1'] if a['S'] else a['I0']
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
    def test_counted_delay_is_noninverting_and_resets_every_unit(self):
        for units in (1,7,69):
            r=resolve_candidate('RiscayDesyncDelay',dict(units=units))
            self.assertEqual(r['keeper_bits'],0)
            for reset,value in product((0,1),repeat=2):
                got=outputs(r,{},dict(reset=reset,**{'in':value}))
                self.assertEqual(got['out'],value and not reset)
                if reset:
                    self.assertTrue(all(got['unit'+str(i)]==0 for i in range(units-1)))
            with self.assertRaisesRegex(ValueError,'PHYSICAL_RECIPE_UNAVAILABLE'):
                require_recipe('RiscayDesyncDelay')
        for units in (None,False,0,-1,1.5):
            with self.assertRaisesRegex(ValueError,'COUNT_REQUIRED'):
                resolve_candidate('RiscayDesyncDelay',dict(units=units))

    def test_earliest_return_checks_both_thresholds_and_the_whole_window(self):
        times=[i*.01 for i in range(12001)]
        progress=[max(0,min(1,t-40)) for t in times]
        for initial in (False,True):
            def points(values):return [(t*1e-9,3.3*(1-v if initial else v)) for t,v in zip(times,values)]
            good=points(progress);self.assertAlmostEqual(retained_wave(good,initial,3.3)['accepted_ns'],40.3)
            with self.assertRaisesRegex(ValueError,'COVERAGE'):retained_wave(good[:5001],initial,3.3)
            with self.assertRaisesRegex(ValueError,'STEP'):retained_wave(good[::4],initial,3.3)
            for when,value,message in ((40.5,.2,'ACK_WITHDRAWN'),(90,.6,'KEEPER_LOST')):
                bad=list(progress);bad[round(when*100)]=value
                with self.assertRaisesRegex(ValueError,message):retained_wave(points(bad),initial,3.3)
            bad=list(progress);bad[11499]=.8;bad[11501]=.4
            wave=points(bad);wave.pop(11500) # 20 ps interval crosses the end of the window.
            with self.assertRaisesRegex(ValueError,'KEEPER_LOST'):retained_wave(wave,initial,3.3)

    def test_sta_polarity_fails_closed_when_a_library_arc_is_missing(self):
        recipe=dict(cells=[dict(name='g',cell='inv',pins=dict(I='in',ZN='out'))])
        body='pin(ZN) { timing() { related_pin : "I"; timing_sense : negative_unate; } }'
        self.assertEqual(arc_polarities(recipe,dict(inv=body)),{('g/I','g/ZN'):True})
        for broken in (body.replace('negative_unate','non_unate'),body.replace('"I"','"J"')):
            with self.assertRaisesRegex(ValueError,'POLARITY_MISSING'):arc_polarities(recipe,dict(inv=broken))

    def test_each_conditional_sta_target_is_a_real_monotonic_transition(self):
        cases=[('RiscayDesyncJoin',dict(initial_open=opened)) for opened in (False,True)]
        cases += [('RiscayDesyncStop',{}),('RiscayDesyncCaptureJoin',{})]
        cases += [('RiscayDesyncQualifiedController',dict(initial_open=opened,same_count=same,
                  closed_count=closed,rise_qualified=rise))
                  for opened,same,closed,rise in product((False,True),(0,3),(0,2),(False,True))]
        for name,parameters in cases:
            recipe=resolve_candidate(name,parameters)
            for context in transition_contexts(name,parameters):
                view,cuts=fixture(recipe,context['frontiers'])
                self.assertEqual(len(cuts),len({(c['cell'],c['pin']) for c in cuts}))
                before=outputs(view,{},context['fixed']|{context['source']:not context['rise']})
                after=outputs(view,{},context['fixed']|{context['source']:context['rise']})
                for target,direction in context['targets'].items():
                    self.assertEqual((before[target],after[target]),(not direction,direction),
                                     (name,parameters,context['label'],target))
        # The B-last return context is a pulse at B; only A/N are monotonic.
        rows=transition_contexts('RiscayDesyncQualifiedController',dict(initial_open=True))
        row=next(r for r in rows if r['label']=='Aminus_state_B')
        self.assertNotIn('requestOut',row['targets'])
        self.assertTrue(any(r['label']=='N_to_B_10' for r in rows))

    def test_qualification_preserves_keeper_state_and_one_sided_closure(self):
        for opened in (False, True):
            r = qualified_controller(initial_open=opened, same_count=2, closed_count=2, rise_qualified=True)
            for bits in product((0,1), repeat=10):
                reset,rq,ao,a,b,s0,s1,c0,c1,rise = bits
                got=outputs(r,dict(acknowledgeOut=a,requestOut=b),dict(reset=reset,
                    requestIn=rq,acknowledgeIn=ao,same0=s0,same1=s1,closed0=c0,closed1=c1,riseAllowed=rise))
                expected=(not opened if reset else
                    (rq and not b and s0 and s1 and rise) or
                    (a and (rq or not b or not ao or s0 or s1 or not(c0 and c1))))
                self.assertEqual(got['acknowledgeOut'],expected)
            self.assertEqual(r['keeper_bits'],2)
        # Closure is allowed to hold A high; it must not inhibit A rising.
        r=qualified_controller(initial_open=True,closed_count=1)
        got=outputs(r,dict(acknowledgeOut=0,requestOut=0),dict(reset=0,requestIn=1,acknowledgeIn=0,closed0=0))
        self.assertEqual(got['acknowledgeOut'],1)

    def test_capture_join_waits_for_current_rearm_and_releases_on_request_return(self):
        r=capture_join_candidate()
        for reset,request,downstream,rearmed,q in product((0,1),repeat=5):
            got=outputs(r,dict(out=q),dict(reset=reset,request=request,downstream=downstream,rearmed=rearmed))
            self.assertEqual(got['out'],not reset and request and (q or (downstream and rearmed)))

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
