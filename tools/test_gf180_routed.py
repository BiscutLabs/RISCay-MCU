# SPDX-License-Identifier: Apache-2.0
"""Execute the production Tcl probe helper against bounded OpenSTA results.

Only the OpenSTA object/query API is mocked. The production batching, endpoint
counting, pair coverage and result classification execute in headless Tcl.
"""
import tkinter
import unittest

from check_gf180_routed import PAIR_HELPER, reset_exclusions, run_suffix
from gf180_physical import SC
from gf180_probe_plan import plan


class ProbeOutputIsolation(unittest.TestCase):
    def test_new_run_tag_keeps_the_original_output_name_distinct(self):
        self.assertEqual(run_suffix(None), '')
        self.assertEqual(run_suffix('context-r3'), '-run-context-r3')

    def test_run_tag_cannot_select_a_path_or_empty_attempt(self):
        for tag in ('', '.', '..', '../old', r'..\old', 'C:old', 'bad\nname', 3):
            with self.subTest(tag=tag):
                with self.assertRaisesRegex(ValueError, 'INVALID_PROBE_RUN_TAG'):
                    run_suffix(tag)


STA_FIXTURE = r'''
set captured {}
set query_count 0
set retained_probe_slews(root/source) {}
proc puts {args} {lappend ::captured [lindex $args end]}
proc rp {name} {return $name}
proc get_full_name {pin} {return $pin}
proc get_timing_edges {args} {return {}}
proc set_min_delay {args} {}
proc set_max_delay {args} {}
proc unset_path_exceptions {args} {}

proc find_timing_paths {args} {
  incr ::query_count
  set from [expr {[lsearch -exact $args -rise_from] >= 0 ? "rise" : "fall"}]
  set result {}
  foreach record $::fixture_endpoints {
    lassign $record sink polarity count
    # Distinct path handles represent reconvergent paths ending at the same
    # physical pin, split between rising and falling endpoint transitions.
    for {set i 0} {$i < $count} {incr i} {
      lappend result [list path $from $sink $polarity $i]
    }
  }
  return $result
}
proc get_property {object property} {
  if {$property eq "points"} {
    lassign $object kind from sink to ordinal
    return [list source_$from ${sink}_$to]
  }
  regexp {^(.*)_(rise|fall)$} $object unused pin polarity
  if {$property eq "pin"} {return root/$pin}
  if {$property eq "arrival"} {
    if {[info exists ::fixture_arrivals($pin,$polarity)]} {return $::fixture_arrivals($pin,$polarity)}
    if {[info exists ::fixture_arrivals($pin)]} {return $::fixture_arrivals($pin)}
    return [expr {$pin eq "source" ? 2.0 : 3.5}]
  }
  error "UNEXPECTED_FIXTURE_PROPERTY $property"
}
foreach pin {source sink0 sink1} {
  proc ${pin}_rise {property} {return ^}
  proc ${pin}_fall {property} {return v}
}
'''


class ProbeFixture(unittest.TestCase):
    def fixture(self, records, helper=None):
        # Tcl() requires no display and never creates a Tk window. Missing Tcl
        # is a test failure, rather than silently skipped coverage.
        interp = tkinter.Tcl()
        interp.eval(STA_FIXTURE)
        interp.eval(PAIR_HELPER if helper is None else helper)
        interp.call('set', 'fixture_endpoints', tuple(records))
        sinks = sorted({record[0] for record in records})
        interp.call('set', 'fixture_sinks', tuple('root/'+sink for sink in sinks))
        interp.call('set', 'fixture_pairs', tuple(
            ('root/source', 'root/'+sink, inverted, 0)
            for sink in sinks for inverted in (0, 1)))
        return interp

    def invoke(self, interp, minimum=0, maximum=2, exclusions=None):
        args = ['local_probe', 'example', 'root', interp.eval('set fixture_sinks'),
                interp.eval('set fixture_pairs'), minimum, maximum, 0]
        if exclusions is not None:
            args.append(tuple(exclusions))
        interp.call(*args)
        return interp.splitlist(interp.eval('set captured'))

    def route_fixture(self, routes, pairs):
        interp = self.fixture([])
        interp.call('set', 'fixture_routes', tuple(routes))
        interp.call('set', 'fixture_sinks', tuple('root/'+sink for sink in sorted({p[1] for p in pairs})))
        interp.call('set', 'fixture_pairs', tuple(('root/'+src, 'root/'+sink, inv, reset)
                                                 for src, sink, inv, reset in pairs))
        interp.eval(r'''
proc find_timing_paths {args} {
  incr ::query_count
  set from [expr {[lsearch -exact $args -rise_from]>=0 ? "rise" : "fall"}]
  set result {}
  foreach route $::fixture_routes {
    lassign $route source sink inverted
    set to $from
    if {$inverted} {set to [expr {$from eq "rise" ? "fall" : "rise"}]}
    lappend result [list path $from $sink $to 0 $source]
  }
  return $result
}
rename get_property original_get_property
proc get_property {object property} {
  if {$property eq "points"} {
    lassign $object kind from sink to ordinal source
    return [list ${source}_$from ${sink}_$to]
  }
  return [original_get_property $object $property]
}
proc reset_rise {property} {return ^}
proc reset_fall {property} {return v}
set fixture_arrivals(reset) 2.0
''')
        return interp


class BatchedEndpointCaps(ProbeFixture):
    def test_cap_combines_rising_and_falling_paths_at_one_endpoint(self):
        interp = self.fixture([('sink0', 'rise', 5000), ('sink0', 'fall', 5000)])
        with self.assertRaisesRegex(tkinter.TclError, '^PROBE_ENDPOINT_CAP_EXHAUSTED$'):
            self.invoke(interp)
        self.assertEqual(int(interp.eval('set query_count')), 1)
        self.assertNotIn('ROUTED_PROBE', interp.eval('set captured'))

    def test_just_below_cap_retains_every_expected_polarity_and_mode(self):
        interp = self.fixture([('sink0', 'rise', 4999), ('sink0', 'fall', 5000)])
        lines = self.invoke(interp)
        self.assertEqual(int(interp.eval('set query_count')), 4)
        self.assertEqual(sum(line.startswith('LOCAL_PAIR ') for line in lines), 8)
        self.assertEqual(lines[-1], 'ROUTED_PROBE example PASS 1.5 1.5 8 8')

    def test_separate_endpoint_counts_do_not_share_the_limit(self):
        interp = self.fixture([
            (sink, polarity, 3000)
            for sink in ('sink0', 'sink1') for polarity in ('rise', 'fall')])
        lines = self.invoke(interp)
        self.assertEqual(int(interp.eval('set query_count')), 4)
        self.assertEqual(lines[-1], 'ROUTED_PROBE example PASS 1.5 1.5 16 16')

    def test_previous_split_polarity_bug_would_accept_a_truncated_query(self):
        original = 'set endpoint $sink_name'
        self.assertEqual(PAIR_HELPER.count(original), 1)
        mutant = PAIR_HELPER.replace(original, 'set endpoint [list $sink_name $to_rf]')
        interp = self.fixture([('sink0', 'rise', 5000), ('sink0', 'fall', 5000)], mutant)
        # This accepted result demonstrates why pair presence alone cannot
        # certify an exhaustive query: the production test above must reject it.
        self.assertEqual(self.invoke(interp)[-1], 'ROUTED_PROBE example PASS 1.5 1.5 8 8')


class DelayValidity(ProbeFixture):
    def delay_fixture(self, arrivals, reset_sinks=(), helper=None):
        interp = self.fixture([
            (sink, polarity, 1)
            for sink in arrivals for polarity in ('rise', 'fall')], helper)
        for sink, arrival in arrivals.items():
            interp.call('set', 'fixture_arrivals('+sink+')', arrival)
        interp.call('set', 'fixture_pairs', tuple(
            ('root/source', 'root/'+sink, inverted, int(sink in reset_sinks))
            for sink in arrivals for inverted in (0, 1)))
        return interp

    def test_negative_dynamic_without_minimum_or_maximum_is_a_violation(self):
        interp = self.delay_fixture({'sink0': 1.5})
        lines = self.invoke(interp, 'none', 'none')
        self.assertEqual(lines[-1], 'ROUTED_PROBE example VIOLATION -0.5 -0.5 8 8')
        self.assertEqual(sum(line.startswith('NEGATIVE_LOCAL_PATH ') for line in lines), 8)
        self.assertIn('LOCAL_PAIR example root/source root/sink0 rise rise min -0.5 0', lines)

    def test_negative_dynamic_without_minimum_is_not_accepted_by_maximum(self):
        interp = self.delay_fixture({'sink0': 1.5})
        self.assertEqual(self.invoke(interp, 'none', 2)[-1],
                         'ROUTED_PROBE example VIOLATION -0.5 -0.5 8 8')

    def test_maximum_reduction_cannot_hide_a_negative_reconvergent_path(self):
        interp = self.fixture([('sink0', 'rise', 2), ('sink0', 'fall', 2)])
        interp.eval(r'''
rename find_timing_paths original_find_timing_paths
proc find_timing_paths {args} {
  set ::fixture_mode [lindex $args [expr {[lsearch -exact $args -path_delay]+1}]]
  return [original_find_timing_paths {*}$args]
}
rename get_property original_get_property
proc get_property {object property} {
  if {$property eq "points"} {
    lassign $object kind from sink to ordinal
    return [list source_$from ${sink}_${to}_$ordinal]
  }
  if {![regexp {^(.*)_(rise|fall)_([01])$} $object unused pin polarity ordinal]} {
    return [original_get_property $object $property]
  }
  if {$property eq "pin"} {return root/$pin}
  if {$property eq "arrival"} {
    return [expr {$::fixture_mode eq "max" && $ordinal==0 ? 1.5 : 3.5}]
  }
  error "UNEXPECTED_FIXTURE_PROPERTY $property"
}
foreach ordinal {0 1} {
  proc sink0_rise_$ordinal {property} {return ^}
  proc sink0_fall_$ordinal {property} {return v}
}
''')
        lines = self.invoke(interp, 'none', 'none')
        # Both final extrema are positive: the discarded max-mode candidate
        # still makes the dynamic measurement invalid and remains in the log.
        self.assertEqual(lines[-1], 'ROUTED_PROBE example VIOLATION 1.5 1.5 8 8')
        self.assertEqual(sum(line.startswith('NEGATIVE_LOCAL_PATH ') for line in lines), 4)

    def test_finite_zero_and_positive_dynamic_delays_remain_valid(self):
        for arrival, delay in ((2.0, '0.0'), (3.5, '1.5')):
            with self.subTest(arrival=arrival):
                interp = self.delay_fixture({'sink0': arrival})
                self.assertEqual(self.invoke(interp, 'none', 'none')[-1],
                                 f'ROUTED_PROBE example PASS {delay} {delay} 8 8')

    def test_negative_reset_only_delays_remain_signed_unqualified_diagnostics(self):
        interp = self.delay_fixture({'sink0': 1.5}, reset_sinks=('sink0',))
        lines = self.invoke(interp, 'none', 'none')
        self.assertEqual(lines[-1], 'ROUTED_PROBE example RESET_ONLY -0.5 -0.5 8 8')
        self.assertIn('LOCAL_PAIR example root/source root/sink0 rise rise min -0.5 1', lines)
        self.assertTrue(all(line.endswith('reset-only') for line in lines
                            if line.startswith('NEGATIVE_LOCAL_PATH ')))

    def test_reset_diagnostics_do_not_replace_dynamic_bound_classification(self):
        interp = self.route_fixture([('reset', 'sink0', 0), ('source', 'sink1', 0)],
                                   [('reset', 'sink0', 0, 1), ('source', 'sink1', 0, 0)])
        interp.call('set', 'fixture_arrivals(sink0)', 1.5)
        self.assertEqual(self.invoke(interp)[-1], 'ROUTED_PROBE example PASS -0.5 1.5 8 8')

    def test_nonfinite_dynamic_arrivals_fail_with_raw_evidence(self):
        for arrival in ('Inf', '-Inf', 'NaN'):
            with self.subTest(arrival=arrival):
                interp = self.delay_fixture({'sink0': arrival})
                with self.assertRaisesRegex(tkinter.TclError, r'^PROBE_NONFINITE_DELAY .* dynamic$'):
                    self.invoke(interp, 'none', 'none')
                lines = interp.splitlist(interp.eval('set captured'))
                self.assertEqual(lines[-1],
                    f'INVALID_LOCAL_PATH example root/source root/sink0 rise rise min dynamic 2.0 {arrival}')
                self.assertFalse(any(line.startswith('ROUTED_PROBE ') for line in lines))

    def test_nonfinite_reset_arrivals_fail_as_reset_diagnostics(self):
        interp = self.delay_fixture({'sink0': 'Inf'}, reset_sinks=('sink0',))
        with self.assertRaisesRegex(tkinter.TclError, r'^PROBE_NONFINITE_DELAY .* reset-only$'):
            self.invoke(interp, 'none', 'none')
        self.assertNotIn('ROUTED_PROBE', interp.eval('set captured'))
        self.assertIn('reset-only 2.0 Inf', interp.eval('set captured'))

    def test_finite_arrival_overflow_is_rejected(self):
        interp = self.delay_fixture({'sink0': '1e308'})
        interp.call('set', 'fixture_arrivals(source)', '-1e308')
        with self.assertRaisesRegex(tkinter.TclError, '^PROBE_NONFINITE_DELAY '):
            self.invoke(interp, 'none', 'none')


class PathRoles(ProbeFixture):
    def test_unexpected_dynamic_polarity_cannot_hide_behind_planned_positive_paths(self):
        interp = self.route_fixture([('source', 'sink0', 0), ('source', 'sink0', 1)],
                                   [('source', 'sink0', 0, 0)])
        # Planned noninverted rise/fall delays are both +1.5 ns; the unexpected
        # rising-source/falling-sink path is -0.5 ns and used to be ignored.
        interp.call('set', 'fixture_arrivals(source,fall)', 0.0)
        interp.call('set', 'fixture_arrivals(sink0,fall)', 1.5)
        with self.assertRaisesRegex(tkinter.TclError, r'^PROBE_UNPLANNED_PATH .* rise fall min$'):
            self.invoke(interp, 'none', 'none')
        self.assertIn('UNPLANNED_LOCAL_PATH example root/source root/sink0 rise fall min 2.0 1.5',
                      interp.splitlist(interp.eval('set captured')))
        self.assertNotIn('ROUTED_PROBE', interp.eval('set captured'))

    def test_unplanned_dynamic_sink_and_source_are_rejected_even_with_positive_delay(self):
        for route in (('source', 'sink1', 0), ('reset', 'sink0', 0)):
            with self.subTest(route=route):
                interp = self.route_fixture([('source', 'sink0', 0), route], [('source', 'sink0', 0, 0)])
                with self.assertRaisesRegex(tkinter.TclError, '^PROBE_UNPLANNED_PATH '):
                    self.invoke(interp)
                self.assertNotIn('ROUTED_PROBE', interp.eval('set captured'))

    def test_proved_reset_crosspath_remains_signed_diagnostic_with_complete_data_coverage(self):
        interp = self.route_fixture(
            [('source', 'sink0', 0), ('reset', 'sink1', 1), ('reset', 'sink0', 1)],
            [('source', 'sink0', 0, 0), ('reset', 'sink1', 1, 1)])
        interp.call('set', 'fixture_arrivals(reset)', 4.0)
        lines = self.invoke(interp, exclusions=[('root/reset', 'root/sink0', 1)])
        self.assertEqual(lines[-1], 'ROUTED_PROBE example PASS -0.5 1.5 8 8')
        self.assertEqual(sum(line.startswith('EXCLUDED_RESET_PATH ') for line in lines), 4)
        self.assertIn('EXCLUDED_RESET_PATH example root/reset root/sink0 rise fall min -0.5', lines)
        self.assertEqual(sum(line.startswith('LOCAL_PAIR ') for line in lines), 8)

    def test_reset_source_identity_alone_does_not_excuse_an_unproved_crosspath(self):
        interp = self.route_fixture(
            [('source', 'sink0', 0), ('reset', 'sink1', 1), ('reset', 'sink0', 1)],
            [('source', 'sink0', 0, 0), ('reset', 'sink1', 1, 1)])
        with self.assertRaisesRegex(tkinter.TclError, '^PROBE_UNPLANNED_PATH '):
            self.invoke(interp)

    def test_reset_exclusion_cannot_mask_a_dynamic_source(self):
        interp = self.route_fixture([('source', 'sink0', 0)], [('source', 'sink0', 0, 0)])
        with self.assertRaisesRegex(tkinter.TclError, '^PROBE_INVALID_RESET_EXCLUSION$'):
            self.invoke(interp, exclusions=[('root/source', 'root/sink0', 1)])

    def test_unexpected_reset_polarity_is_not_covered_by_a_proved_exclusion(self):
        interp = self.route_fixture(
            [('source', 'sink0', 0), ('reset', 'sink1', 1), ('reset', 'sink0', 0)],
            [('source', 'sink0', 0, 0), ('reset', 'sink1', 1, 1)])
        with self.assertRaisesRegex(tkinter.TclError, '^PROBE_UNPLANNED_PATH '):
            self.invoke(interp, exclusions=[('root/reset', 'root/sink0', 1)])

    def test_nonfinite_proved_reset_exclusion_still_fails(self):
        interp = self.route_fixture(
            [('source', 'sink0', 0), ('reset', 'sink0', 1), ('reset', 'sink1', 1)],
            [('source', 'sink0', 0, 0), ('reset', 'sink1', 1, 1)])
        interp.call('set', 'fixture_arrivals(reset)', 'Inf')
        with self.assertRaisesRegex(tkinter.TclError, r'^PROBE_NONFINITE_DELAY .* reset-excluded$'):
            self.invoke(interp, exclusions=[('root/reset', 'root/sink0', 1)])


class ResetExclusionProof(unittest.TestCase):
    def fixture(self):
        cells = [dict(name='reset', cell=SC+'inv_1', pins={'I': 'reset', 'ZN': 'rn'})]
        for i in range(2):
            cells += [dict(name='gate'+str(i), cell=SC+'and2_1',
                           pins={'A1': 'data'+str(i), 'A2': 'rn', 'Z': 'q'+str(i)})]
        nets = {net: ('local', net) for c in cells for net in c['pins'].values()}
        nets['data1'] = ('constant', '1')
        flat = {'root/'+c['name']: dict(connections={pin: [nets[net]] for pin, net in c['pins'].items()})
                for c in cells}
        row = dict(id='mixed', from_pins=['root/gate0/A1', 'root/gate1/A1'],
                   to_pins=['root/gate0/Z', 'root/gate1/Z'])
        binding = dict(cells=cells)
        return plan(row, binding, 'root', flat), binding

    def test_exact_graph_proves_only_omitted_reset_to_dynamic_polarity(self):
        probe, binding = self.fixture()
        self.assertEqual(reset_exclusions(probe, binding), [
            dict(source='root/reset/I', sink='root/gate0/Z', inverted=True)])

    def test_reset_name_without_actual_reset_pin_binding_is_rejected(self):
        probe, binding = self.fixture()
        binding['cells'][0]['pins']['I'] = 'renamed_input'
        with self.assertRaisesRegex(ValueError, '^PROBE_RESET_SOURCE_NOT_BOUND$'):
            reset_exclusions(probe, binding)

    def test_disconnected_reset_crosspath_is_not_excused(self):
        probe, binding = self.fixture()
        binding['cells'][1]['pins']['A2'] = 'other_input'
        self.assertEqual(reset_exclusions(probe, binding), [])


if __name__ == '__main__':
    unittest.main()
