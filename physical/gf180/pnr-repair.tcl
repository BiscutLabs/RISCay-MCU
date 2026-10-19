# SPDX-License-Identifier: Apache-2.0
# Serialize actual OpenDB signal pins, independently of the Verilog writer.
# Python verifies the complete graph before accepting the checkpoint.
proc repair_graph {filename} {
  set f [open $filename w]
  set block [ord::get_db_block]
  foreach inst [$block getInsts] {
    set name [$inst getName]
    puts $f "C\t$name\t[[$inst getMaster] getName]"
    foreach pin [$inst getITerms] {
      if {[$pin getSigType] in {POWER GROUND}} {continue}
      set terminal [$pin getMTerm]
      set direction [string tolower [$terminal getIoType]]
      if {$direction ni {input output} || [$pin getNet] eq "NULL"} {error "REPAIR_PIN_SHAPE $name/[$terminal getName]"}
      puts $f "P\t$name\t[$terminal getName]\t$direction\t[[$pin getNet] getName]"
    }
  }
  foreach port [$block getBTerms] {
    if {[$port getSigType] in {POWER GROUND}} {continue}
    if {[$port getNet] eq "NULL"} {error "REPAIR_PORT_DISCONNECTED [$port getName]"}
    puts $f "T\t[$port getName]\t[string tolower [$port getIoType]]\t[[$port getNet] getName]"
  }
  close $f
}
proc electrical_reports {prefix} {
  global out pvt_corners
  foreach corner $pvt_corners {
    report_check_types -corner $corner -max_slew -max_capacitance -violators -digits 6 -no_line_splits > $out/$prefix-$corner-electrical.rpt
  }
}
proc wire_repair {} {
  global out stage protected_cells
  # The resizer otherwise tries (and errors) to insert a cell before protected
  # native input pins. Lock native input nets and nets joining multiple pins of the same primitive:
  # inserting on such a branch is forbidden by the unchanged native partition.
  # Their electrical failures stay in every report; they need a recipe change.
  set groups [dict create]
  set locked {}
  set block [ord::get_db_block]
  protect_native_output_feeders
  foreach record $protected_cells {
    lassign $record name master pins
    set owner [string range $name 0 [expr {[string last / $name]-1}]]
    set inst [$block findInst $name]
    foreach pin $pins {
      set terminal [$inst findITerm $pin]
      set dbnet [$terminal getNet]
      set net [$dbnet getName]
      if {[[$terminal getMTerm] getIoType] eq "INPUT"} {lappend locked $net}
      # Port buffering moves a direct native output onto a different net.
      # Keep the exact protected-pin snapshot; retain this boundary's failure
      # until an explicit parent-driver recipe is reviewed.
      if {[llength [$dbnet getBTerms]]} {lappend locked $net}
      dict incr groups [list $owner $net]
    }
  }
  dict for {key count} $groups {
    if {$count>1} {
      set net [lindex $key 1]
      lappend locked $net
    }
  }
  foreach net [lsort -unique $locked] {set_dont_touch [get_nets $net]}
  set f [open $out/$stage-native-protected-nets.txt w]
  puts $f [join [lsort -unique $locked] \n]
  close $f
  electrical_reports $stage-before-repair
  repair_graph $out/$stage-repair-before.tsv
  # Diagnostic input only: this is not an accepted repaired checkpoint.
  write_db $out/$stage-before-repair.odb
  # The graph proof permits ordinary combinational resizing, never changing
  # a sequential master. Existing native cells are protected independently.
  set_dont_use [get_lib_cells */*dff*]
  set_dont_use [get_lib_cells */*lat*]
  set placement_baseline [native_repair_baseline]
  repair_design -slew_margin 10 -cap_margin 10
  native_detailed_placement $placement_baseline
  repair_graph $out/$stage-repair-after.tsv
  puts "WIRE_REPAIR_COMPLETE $stage"
}
