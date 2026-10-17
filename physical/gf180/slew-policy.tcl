# SPDX-License-Identifier: Apache-2.0
# Strict control repair is deliberately a separate context. No analysis clocks
# or false paths are introduced. Native leaf/net protection is never lifted.
proc slew_native_inventory {} {
  global slew_native_seeds sc
  set block [ord::get_db_block]
  set strict [dict create]; set adjacency [dict create]
  foreach name $slew_native_seeds {
    set slash [string last / $name]
    set inst [$block findInst [string range $name 0 [expr {$slash-1}]]]
    if {$inst eq "NULL"} {error "SLEW_NATIVE_CELL_MISSING $name"}
    set pin [$inst findITerm [string range $name [expr {$slash+1}] end]]
    if {$pin eq "NULL" || [$pin getNet] eq "NULL"} {error "SLEW_NATIVE_PIN_MISSING $name"}
    dict set strict [[$pin getNet] getName] 1
  }
  foreach port [$block getBTerms] {
    if {[$port getSigType] in {POWER GROUND}} {continue}
    if {[$port getNet] eq "NULL"} {error SLEW_PORT_DISCONNECTED}
    dict set strict [[$port getNet] getName] 1
  }
  foreach inst [$block getInsts] {
    set master [[$inst getMaster] getName]
    if {![regexp "^${sc}(buf|clkbuf|inv)_\[0-9\]+$" $master -> kind]} {continue}
    set output [expr {$kind eq "inv" ? "ZN" : "Z"}]
    set a [[[$inst findITerm I] getNet] getName]
    set b [[[$inst findITerm $output] getNet] getName]
    dict lappend adjacency $a $b; dict lappend adjacency $b $a
  }
  set queue [dict keys $strict]
  for {set i 0} {$i<[llength $queue]} {incr i} {
    set net [lindex $queue $i]
    if {![dict exists $adjacency $net]} {continue}
    foreach next [dict get $adjacency $net] {
      if {![dict exists $strict $next]} {dict set strict $next 1; lappend queue $next}
    }
  }
  return $strict
}

proc slew_raw_reports {prefix} {
  global pvt_corners
  foreach corner $pvt_corners {
    report_check_types -corner $corner -max_slew -max_capacitance -violators -digits 6 -no_line_splits > ${prefix}-${corner}.rpt
  }
}

proc slew_strict_repair {prefix} {
  global pvt_corners sc
  set strict [slew_native_inventory]
  set block [ord::get_db_block]
  set_max_transition 2 [current_design]
  slew_raw_reports $prefix
  set candidates [dict create]
  foreach corner $pvt_corners {
    set f [open ${prefix}-${corner}.rpt]; set report [read $f]; close $f
    foreach line [split $report \n] {
      if {![regexp {^(\S+)\s+[-+.0-9eE]+\s+[-+.0-9eE]+\s+[-+.0-9eE]+\s+\(VIOLATED\)$} $line -> pin]} {
        if {[string first VIOLATED $line]>=0} {error SLEW_REPORT_SHAPE}
        continue
      }
      # Names are literal OpenDB pins, never wildcard expressions.
      set slash [string last / $pin]
      if {$slash<0} {
        set term [$block findBTerm $pin]
      } else {
        set inst [$block findInst [string range $pin 0 [expr {$slash-1}]]]
        if {$inst eq "NULL"} {error "SLEW_REPORT_CELL_MISSING $pin"}
        set term [$inst findITerm [string range $pin [expr {$slash+1}] end]]
      }
      if {$term eq "NULL" || [$term getNet] eq "NULL"} {error "SLEW_REPORT_PIN_MISSING $pin"}
      set net [[$term getNet] getName]
      if {[dict exists $strict $net]} {dict set candidates $net 1}
    }
  }
  set log [open ${prefix}-decisions.tsv w]
  foreach name [lsort [dict keys $candidates]] {
    set net [$block findNet $name]
    if {$net eq "NULL"} {error "SLEW_REPAIR_NET_DISAPPEARED $name"}
    set reason ""; set drivers {}; set clock_sink false
    if {[$net isDoNotTouch]} {set reason protected-net}
    if {[$net isSpecial] || [$net isConnectedByAbutment]} {set reason special-or-abutment}
    foreach pin [$net getITerms] {
      set inst [$pin getInst]; set mt [$pin getMTerm]
      if {[$mt getIoType] eq "OUTPUT"} {lappend drivers $pin}
      if {[$mt getIoType] eq "INPUT" && [$inst isDoNotTouch]} {set reason protected-input}
      if {[$mt getName] in {CLK CLKN}} {set clock_sink true}
    }
    foreach port [$net getBTerms] {
      if {[$port getIoType] eq "INPUT"} {lappend drivers $port; set reason top-input}
      if {[$port getIoType] eq "OUTPUT"} {set reason top-output}
    }
    if {[llength $drivers]!=1} {set reason driver-count}
    if {$clock_sink || [$net getSigType] eq "CLOCK"} {set reason clock-net}
    if {$reason eq ""} {
      set driver [lindex $drivers 0]; set inst [$driver getInst]
      # Top ports were excluded above. The driver is now an actual leaf pin.
      set driver_name "[$inst getName]/[[$driver getMTerm] getName]"
      set sta_pin [sta::find_pin $driver_name]
      if {$sta_pin eq "NULL" || [get_full_name $sta_pin] ne $driver_name} {error "SLEW_DRIVER_BINDING $driver_name"}
      if {[sta::is_clock $sta_pin]} {set reason clock-net}
      if {[sta::pin_sim_logic_value $sta_pin] in {0 1}} {set reason constant}
    }
    if {$reason ne ""} {puts $log "$name\tskipped\t$reason"; continue}
    puts $log "$name\ttargeted-repair"
    # This upstream entry point avoids repair_design's global temporary input
    # slew clipping. Eligibility was checked above; residual failures remain.
    set sta_net [sta::find_net $name]
    if {$sta_net eq "NULL" || [get_full_name $sta_net] ne $name} {error "SLEW_NET_BINDING $name"}
    rsz::repair_net_cmd $sta_net 0 10 10
  }
  close $log
  return [dict size $candidates]
}
