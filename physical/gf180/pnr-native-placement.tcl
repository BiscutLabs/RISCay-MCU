# SPDX-License-Identifier: Apache-2.0
# GPL combines each group. DPL's displacement limit and the independent geometry
# gate keep legalization/repair honest; soft clustering alone is not a guarantee.
proc native_span_bound {id limit dx dy} {
  if {![string is double -strict $dx] || ![string is double -strict $dy] ||
      [catch {expr {$dx>=0 && $dy>=0 && $dx<=$limit && $dy<=$limit}} accepted] || !$accepted} {
    error "NATIVE_PLACEMENT_SPREAD $id $dx $dy > $limit"
  }
}
proc cluster_native_cells {} {
  global native_placement_groups
  set block [ord::get_db_block]
  foreach row $native_placement_groups {
    set instances {}
    foreach name [lindex $row 2] {
      set inst [$block findInst $name]
      if {$inst eq "NULL" || [$inst getName] ne $name} {error "NATIVE_CLUSTER_INSTANCE $name"}
      lappend instances $inst
    }
    # Public wrapper interprets names as get_cells patterns; pass exact objects.
    gpl::placement_cluster_cmd $instances
  }
}
proc native_detailed_placement {} {
  # Ordinary macro-pin logic needs more room to legalize. This search radius
  # does not relax the independent 64um native group limit below.
  detailed_placement -max_displacement {100 100}
  check_placement -verbose
  check_native_placement
}
proc check_native_placement {} {
  global native_placement_groups native_output_feeders out stage
  set block [ord::get_db_block]
  set dbu [$block getDbUnitsPerMicron]
  set f [open $out/$stage-native-placement.tsv w]
  foreach row $native_placement_groups {
    lassign $row id limit names
    set xmin Inf; set ymin Inf; set xmax -Inf; set ymax -Inf
    foreach name $names {
      set inst [$block findInst $name]
      if {$inst eq "NULL" || ![$inst isPlaced]} {error "NATIVE_PLACEMENT_MISSING $name"}
      set box [$inst getBBox]
      set x0 [expr {[$box xMin]/double($dbu)}]; set y0 [expr {[$box yMin]/double($dbu)}]
      set x1 [expr {[$box xMax]/double($dbu)}]; set y1 [expr {[$box yMax]/double($dbu)}]
      set xmin [expr {min($xmin,$x0)}]; set ymin [expr {min($ymin,$y0)}]
      set xmax [expr {max($xmax,$x1)}]; set ymax [expr {max($ymax,$y1)}]
      puts $f "C\t$id\t$name\t$x0\t$y0\t$x1\t$y1"
    }
    puts $f "G\t$id\t$limit\t[expr {$xmax-$xmin}]\t[expr {$ymax-$ymin}]"
    if {[catch {native_span_bound $id $limit [expr {$xmax-$xmin}] [expr {$ymax-$ymin}]} message]} {
      close $f; error $message
    }
  }
  foreach row $native_output_feeders {
    lassign $row driver pin parent
    set source [[$block findInst $driver] findITerm $pin]
    set sink [[$block findInst $parent] findITerm I]
    if {[$source getNet] ne [$sink getNet]} {error "NATIVE_OUTPUT_FEEDER_CHANGED $driver/$pin"}
    set net [$source getNet]
    if {[llength [$net getBTerms]]} {error "NATIVE_OUTPUT_TOP_BYPASS $driver/$pin"}
    set owner [string range $driver 0 [string last / $driver]]
    foreach terminal [$net getITerms] {
      if {[$terminal getSigType] in {POWER GROUND}} {continue}
      if {$terminal eq $source || $terminal eq $sink} {continue}
      set name [[$terminal getInst] getName]
      if {[string first $owner $name]!=0 || [[$terminal getMTerm] getIoType] ne "INPUT"} {
        error "NATIVE_OUTPUT_EXTERNAL_BYPASS $driver/$pin $name"
      }
    }
    if {![regexp {__(clk)?buf_[0-9]+$} [[[$block findInst $parent] getMaster] getName]]} {
      error "NATIVE_OUTPUT_PARENT_POLARITY $parent"
    }
  }
  close $f
  puts "NATIVE_PLACEMENT_PASS [llength $native_placement_groups]"
}
proc protect_native_output_feeders {} {
  global native_output_feeders
  set block [ord::get_db_block]
  foreach row $native_output_feeders {
    lassign $row driver pin parent
    set terminal [[$block findInst $driver] findITerm $pin]
    # This short native-to-parent link is immutable. The parent output remains
    # repairable, including buffering, fanout splitting and equivalent resizing.
    [$terminal getNet] setDoNotTouch true
  }
}
