# SPDX-License-Identifier: Apache-2.0
# Native NDR assignment is not geometric spacing or SI qualification. The pinned
# router automatically tapers pin access and its final DRC omits some NDR checks.
proc native_routing_inventory {} {
  global native_routing_seeds sc
  set block [ord::get_db_block]
  set strict [dict create]; set adjacency [dict create]; set pins [dict create]
  foreach record $native_routing_seeds {
    lassign $record name expected_master
    set slash [string last / $name]
    set inst [$block findInst [string range $name 0 [expr {$slash-1}]]]
    if {$inst eq "NULL" || [[$inst getMaster] getName] ne $expected_master} {
      error "NATIVE_ROUTING_CELL_CHANGED $name"
    }
    set pin [$inst findITerm [string range $name [expr {$slash+1}] end]]
    if {$pin eq "NULL" || [$pin getNet] eq "NULL" || [$pin getSigType] in {POWER GROUND}} {
      error "NATIVE_ROUTING_PIN_MISSING $name"
    }
    set net [[$pin getNet] getName]
    if {[dict exists $pins $name]} {error "NATIVE_ROUTING_DUPLICATE_PIN $name"}
    dict set pins $name $net; dict set strict $net 1
  }
  if {![dict size $pins]} {error NATIVE_ROUTING_EMPTY_INVENTORY}
  # Traverse only transparent buffer/inverter connectivity, in both directions.
  # Do not cross combinational gates, storage, or unrelated top-level ports.
  foreach inst [$block getInsts] {
    set master [[$inst getMaster] getName]
    if {![regexp "^${sc}(buf|clkbuf|inv)_\[0-9\]+$" $master -> kind]} {continue}
    set output [expr {$kind eq "inv" ? "ZN" : "Z"}]
    set a [$inst findITerm I]; set b [$inst findITerm $output]
    if {$a eq "NULL" || $b eq "NULL" || [$a getNet] eq "NULL" || [$b getNet] eq "NULL"} {
      error "NATIVE_ROUTING_BUFFER_SHAPE [$inst getName]"
    }
    set a [[$a getNet] getName]; set b [[$b getNet] getName]
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
  return [list $strict $pins]
}

proc native_routing_check_rule {} {
  global native_routing_rule
  set rule [[ord::get_db_block] findNonDefaultRule $native_routing_rule]
  if {$rule eq "NULL" || ![$rule getHardSpacing]} {error NATIVE_ROUTING_RULE_MISSING}
  set layers [dict create]
  foreach layer [[ord::get_db_tech] getLayers] {
    if {[$layer getType] ne "ROUTING"} {continue}
    set lr [$rule getLayerRule $layer]
    if {$lr eq "NULL" || [$layer getSpacing]<=0 || [$layer getWidth]<=0 ||
        [$lr getWidth]!=[$layer getWidth] || [$lr getSpacing]!=2*[$layer getSpacing]} {
      error "NATIVE_ROUTING_RULE_CHANGED [$layer getName]"
    }
    dict set layers [$layer getName] [list [$lr getWidth] [$lr getSpacing]]
  }
  if {![dict size $layers]} {error NATIVE_ROUTING_NO_LAYERS}
  return [list $rule $layers]
}

proc verify_native_routing {{tag ""}} {
  global native_routing_rule out stage
  if {$tag eq ""} {set tag $stage}
  if {![regexp {^[A-Za-z0-9_-]+$} $tag]} {error NATIVE_ROUTING_REPORT_TAG}
  lassign [native_routing_check_rule] rule layers
  lassign [native_routing_inventory] strict pins
  set block [ord::get_db_block]
  foreach name [dict keys $strict] {
    set net [$block findNet $name]
    if {$net eq "NULL" || [$net getNonDefaultRule] ne $rule} {error "NATIVE_ROUTING_UNASSIGNED $name"}
  }
  # A stale or unrelated assignment must not silently expand the selected set.
  foreach net [$block getNets] {
    if {[$net getNonDefaultRule] eq $rule && ![dict exists $strict [$net getName]]} {
      error "NATIVE_ROUTING_EXTRA_NET [$net getName]"
    }
  }
  set f [open $out/$tag-native-routing.tsv w]
  foreach name [lsort [dict keys $pins]] {puts $f "P\t$name\t[dict get $pins $name]"}
  foreach name [lsort [dict keys $strict]] {puts $f "N\t$name\t$native_routing_rule"}
  foreach name [lsort [dict keys $layers]] {puts $f "L\t$name\t[join [dict get $layers $name] \t]"}
  puts $f "STATUS\tassigned-unqualified"
  close $f
  puts "NATIVE_ROUTING_ASSIGNED [dict size $pins] [dict size $strict] geometric-spacing-and-SI-unqualified"
  return [dict size $strict]
}

proc apply_native_routing {{tag ""}} {
  global native_routing_rule
  set block [ord::get_db_block]
  set rule [$block findNonDefaultRule $native_routing_rule]
  if {$rule eq "NULL"} {
    create_ndr -name $native_routing_rule -spacing {*2} -width {*1}
    set rule [$block findNonDefaultRule $native_routing_rule]
    $rule setHardSpacing true
  }
  native_routing_check_rule
  lassign [native_routing_inventory] strict pins
  foreach name [dict keys $strict] {
    set net [$block findNet $name]
    set existing [$net getNonDefaultRule]
    if {$existing ne "NULL" && $existing ne $rule} {error "NATIVE_ROUTING_RULE_CONFLICT $name"}
    assign_ndr -ndr $native_routing_rule -net $name
  }
  return [verify_native_routing $tag]
}
