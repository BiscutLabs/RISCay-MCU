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


    def test_previous_split_polarity_bug_would_accept_a_truncated_query(self):
        original = 'set endpoint $sink_name'
        self.assertEqual(PAIR_HELPER.count(original), 1)
        mutant = PAIR_HELPER.replace(original, 'set endpoint [list $sink_name $to_rf]')
        interp = self.fixture([('sink0', 'rise', 5000), ('sink0', 'fall', 5000)], mutant)
        # The broken helper accepts truncation; production must reject it.
        self.assertEqual(self.invoke(interp)[-1], 'ROUTED_PROBE example PASS 1.5 1.5 8 8')
        with self.assertRaisesRegex(tkinter.TclError, 'PROBE_ENDPOINT_CAP_EXHAUSTED'):
            self.invoke(self.fixture([('sink0', 'rise', 5000), ('sink0', 'fall', 5000)]))


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


class PathRoles(ProbeFixture):


    def test_reset_exclusion_cannot_mask_a_dynamic_source(self):
        interp = self.route_fixture([('source', 'sink0', 0)], [('source', 'sink0', 0, 0)])
        with self.assertRaisesRegex(tkinter.TclError, '^PROBE_INVALID_RESET_EXCLUSION$'):
            self.invoke(interp, exclusions=[('root/source', 'root/sink0', 1)])


if __name__ == '__main__':
    unittest.main()
