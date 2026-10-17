# SPDX-License-Identifier: Apache-2.0
# Loaded, cofactored first-transition arc composition. Never full-cycle STA.
proc reviewed_arc {from to from_rf to_rf role} {
  set edges [get_timing_edges -from [get_pins $from] -to [get_pins $to]]
  if {[llength $edges] != 1} {error FORK_EDGE_COUNT}
  set edge [lindex $edges 0]
  if {[$edge role] ne $role} {error FORK_EDGE_ROLE}
  set found {}
  foreach arc [$edge timing_arcs] {
    if {[$arc from_edge] eq $from_rf && [$arc to_edge] eq $to_rf} {lappend found $arc}
  }
  if {[llength $found] != 1} {error FORK_ARC_COUNT}
  return [list $edge [lindex $found 0]]
}
proc reviewed_wire {from to rf mode} {
  lassign [reviewed_arc $from $to $rf $rf wire] edge arc
  set delay [sta::time_sta_ui [$edge arc_delay $arc [sta::cmd_corner] $mode]]
  if {![string is double -strict $delay] || !($delay >= 0 && $delay < 1e6)} {error FORK_WIRE_DELAY}
  set annotated [$edge delay_annotated $arc [sta::cmd_corner] $mode]
  # Slew-preserving wires here are either prelayout zero-RC nets or explicit
  # pure transport fault annotations. A routed RC model needs a new contract.
  if {!$annotated && $delay != 0} {error FORK_UNMODELED_WIRE}
  row FORK_WIRE $mode $from $to $rf $delay $annotated
  return $delay
}
proc reviewed_path {root sink mode source_slew path} {
  set arrival 0.0; set slew $source_slew; set previous $root; set rf ^
  foreach step $path {
    lassign $step from to from_rf to_rf
    if {$rf ne $from_rf} {error FORK_PATH_POLARITY}
    set arrival [expr {$arrival + [reviewed_wire $previous $from $rf $mode]}]
    set vertices [[get_pins $from] vertices]
    if {[llength $vertices] != 1} {error FORK_INPUT_VERTEX}
    foreach vertex $vertices {
      sta::set_annotated_slew $vertex [sta::cmd_corner] $mode [expr {$rf eq "^" ? "rise" : "fall"}] [sta::time_ui_sta $slew]
    }
    lassign [reviewed_arc $from $to $from_rf $to_rf combinational] edge arc
    # Unlike graph arc_delay, the calculator evaluates even a loop-disabled arc.
    set report [sta::report_delay_calc_cmd $edge $arc [sta::cmd_corner] $mode 9]
    if {![regexp -line {^Delay = ([^\n]+)$} $report all delay] ||
        ![regexp -line {^Slew = ([^\n]+)$} $report all output_slew] ||
        ![regexp -line {^------- input_net_transition = ([^\n]+)$} $report all input_slew] ||
        ![regexp -line {^\|       total_output_net_capacitance = ([^\n]+)$} $report all load]} {error FORK_DCALC_SHAPE}
    foreach value [list $delay $output_slew $input_slew $load] {
      if {![string is double -strict $value] || !($value >= 0 && $value < 1e6)} {error FORK_DCALC_VALUE}
    }
    if {abs($input_slew-$slew) > 0.000002} {error FORK_SLEW_BINDING}
    set annotated [$edge delay_annotated $arc [sta::cmd_corner] $mode]
    set effective $delay
    if {$annotated} {set effective [sta::time_sta_ui [$edge arc_delay $arc [sta::cmd_corner] $mode]]}
    if {![string is double -strict $effective] || !($effective >= 0 && $effective < 1e6)} {error FORK_ANNOTATED_DELAY}
    row FORK_CELL $mode $from $to $from_rf $to_rf $input_slew $load $delay $output_slew $effective $annotated
    row FORK_DCALC_BEGIN $mode $from $to
    puts $report
    row FORK_DCALC_END
    set arrival [expr {$arrival + $effective}]
    set slew $output_slew; set previous $to; set rf $to_rf
  }
  set arrival [expr {$arrival + [reviewed_wire $previous $sink $rf $mode]}]
  row FORK_PATH $mode $arrival $slew $rf
}
