# SPDX-License-Identifier: Apache-2.0
"""Execute the production Tcl probe helper against bounded OpenSTA results.

Only the OpenSTA object/query API is mocked. The production batching, endpoint
counting, pair coverage and result classification execute in headless Tcl.
"""
import tkinter
import unittest

from check_gf180_routed import PAIR_HELPER, run_suffix


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
  if {$property eq "arrival"} {return [expr {$pin eq "source" ? 2.0 : 3.5}]}
  error "UNEXPECTED_FIXTURE_PROPERTY $property"
}
foreach pin {source sink0 sink1} {
  proc ${pin}_rise {property} {return ^}
  proc ${pin}_fall {property} {return v}
}
'''


class BatchedEndpointCaps(unittest.TestCase):
    def fixture(self, records, helper=PAIR_HELPER):
        # Tcl() requires no display and never creates a Tk window. Missing Tcl
        # is a test failure, rather than silently skipped coverage.
        interp = tkinter.Tcl()
        interp.eval(STA_FIXTURE)
        interp.eval(helper)
        interp.call('set', 'fixture_endpoints', tuple(records))
        sinks = sorted({record[0] for record in records})
        interp.call('set', 'fixture_sinks', tuple('root/'+sink for sink in sinks))
        interp.call('set', 'fixture_pairs', tuple(
            ('root/source', 'root/'+sink, inverted, 0)
            for sink in sinks for inverted in (0, 1)))
        return interp

    def invoke(self, interp):
        interp.eval('local_probe example root $fixture_sinks $fixture_pairs 0 2 0')
        return interp.splitlist(interp.eval('set captured'))

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


if __name__ == '__main__':
    unittest.main()
