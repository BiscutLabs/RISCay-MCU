# Local stage screen. No created clock, reset case, false path or manual loop cut.
proc row {args} {
  # Pinned OpenROAD corrupts long Tcl stdout writes at its 4096-byte boundary.
  # Bound each write while preserving the existing complete TSV record.
  set text [join $args "\t"]
  for {set start 0} {$start < [string length $text]} {incr start 1024} {
    puts -nonewline [string range $text $start [expr {$start+1023}]]
  }
  puts ""
}
proc exact_object {kind name} {
  if {$kind eq "port"} {set objects [get_ports -quiet $name]} else {set objects [get_pins -quiet $name]}
  if {[llength $objects] != 1 || [get_full_name [lindex $objects 0]] ne $name} {error "CONTROL_OBJECT_BINDING $kind $name"}
  return [lindex $objects 0]
}
proc control_batch {mode source_edge sink_edge sources sink_kind members} {
  set sinks {}; set ids [dict create]
  foreach {id name} $members {
    if {[dict exists $ids $name]} {error CONTROL_DUPLICATE_ENDPOINT}
    dict set ids $name $id
    lappend sinks [exact_object $sink_kind $name]
  }
  if {$source_edge eq "any"} {set from -from} else {set from -${source_edge}_from}
  if {$sink_edge eq "any"} {set to -to} else {set to -${sink_edge}_to}
  # One transition, one path PER endpoint; enough global capacity for every
  # endpoint plus one overflow sentinel. This batches search, not coverage.
  set paths [find_timing_paths $from $sources $to $sinks -path_delay $mode -group_path_count [expr {[dict size $ids]+1}] -endpoint_path_count 1]
  foreach end $paths {
    set name [get_full_name [$end pin]]
    if {![dict exists $ids $name]} {error CONTROL_DUPLICATE_OR_UNKNOWN_PATH}
    control_path [dict get $ids $name] $end
    dict unset ids $name
  }
  dict for {name id} $ids {row CONTROL_MISSING $id}
}
proc control_path {id end} {
  if {[$end is_unconstrained] || ![$end is_path_delay]} {error CONTROL_PATH_DELAY_REQUIRED}
  set path [$end path]; set start [$path start_path]
  set source [sta::time_sta_ui [$start arrival]]
  set arrival [sta::time_sta_ui [$path arrival]]
  set propagation [expr {$arrival - $source}]
  set max_slew 0.0
  set names {}
  foreach pin [$path pins] {
    lappend names [get_full_name $pin]
    foreach edge {rise fall} {
      set s [get_property $pin slew_max_$edge]
      if {$s > $max_slew} {set max_slew $s}
    }
  }
  set start_edge [string map {^ rise v fall} [$start edge]]
  set end_edge [string map {^ rise v fall} [$end end_transition]]
  row CONTROL_PATH $id $source $arrival [sta::time_sta_ui [$end data_arrival_time]] $propagation $max_slew [get_full_name [$start pin]] [get_full_name [$end pin]] $start_edge $end_edge
  row CONTROL_POINTS $id {*}[lreverse $names]
}
