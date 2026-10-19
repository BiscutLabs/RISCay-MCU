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
proc native_locations {} {
  set saved {}
  foreach inst [[ord::get_db_block] getInsts] {
    set box [$inst getBBox]
    dict set saved $inst [list [$box xMin] [$box yMin] [$inst getOrient] [$inst getPlacementStatus]]
  }
  return $saved
}
proc restore_native_locations {saved} {
  dict for {inst record} $saved {
    set b [$inst getBBox]
    if {[list [$b xMin] [$b yMin] [$inst getOrient] [$inst getPlacementStatus]] eq $record} {continue}
    lassign $record x y orient status
    $inst setPlacementStatus PLACED
    $inst setOrient $orient
    $inst setLocation $x $y
    $inst setPlacementStatus $status
  }
}
proc native_group_geometry {row} {
  lassign $row id limit names
  set block [ord::get_db_block]
  set dbu [$block getDbUnitsPerMicron]
  set xmin Inf; set ymin Inf; set xmax -Inf; set ymax -Inf
  set cells {}
  foreach name $names {
    set inst [$block findInst $name]
    if {$inst eq "NULL" || ![$inst isPlaced]} {error "NATIVE_PLACEMENT_MISSING $name"}
    set box [$inst getBBox]
    set x0 [expr {[$box xMin]/double($dbu)}]; set y0 [expr {[$box yMin]/double($dbu)}]
    set x1 [expr {[$box xMax]/double($dbu)}]; set y1 [expr {[$box yMax]/double($dbu)}]
    set xmin [expr {min($xmin,$x0)}]; set ymin [expr {min($ymin,$y0)}]
    set xmax [expr {max($xmax,$x1)}]; set ymax [expr {max($ymax,$y1)}]
    lappend cells [list $name $x0 $y0 $x1 $y1]
  }
  return [list [expr {$xmax-$xmin}] [expr {$ymax-$ymin}] $cells]
}
proc oversized_native_groups {} {
  global native_placement_groups
  set bad {}
  foreach row $native_placement_groups {
    lassign [native_group_geometry $row] dx dy cells
    if {[catch {native_span_bound [lindex $row 0] [lindex $row 1] $dx $dy}]} {lappend bad $row}
  }
  return $bad
}
proc native_repack_neighbors {bad saved targets} {
  global native_placement_groups
  set block [ord::get_db_block]
  set radius [expr {96*[$block getDbUnitsPerMicron]}]
  set regions {}
  foreach row $bad {
    set box [[$block findInst [lindex $row 2 0]] getBBox]
    lappend regions [list [expr {[$box xMin]-$radius}] [expr {[$box yMin]-$radius}] \
      [expr {[$box xMax]+$radius}] [expr {[$box yMax]+$radius}]]
  }
  set eligible {}
  dict for {inst record} $saved {
    if {[lindex $record 3] in {FIRM LOCKED COVER}} {continue}
    set box [$inst getBBox]
    foreach region $regions {
      lassign $region x0 y0 x1 y1
      if {[$box xMin]>=$x0 && [$box yMin]>=$y0 && [$box xMax]<=$x1 && [$box yMax]<=$y1} {
        dict set eligible $inst 1; break
      }
    }
  }
  # A neighboring native group moves as a complete group or not at all.
  # Groups are disjoint by construction. Original bad groups remain targets.
  foreach row $native_placement_groups {
    set instances [lmap name [lindex $row 2] {$block findInst $name}]
    set complete 1
    foreach inst $instances {if {![dict exists $eligible $inst]} {set complete 0}}
    if {!$complete} {foreach inst $instances {dict unset eligible $inst}}
  }
  return [dict merge $eligible $targets]
}
proc repack_native_groups {{depth 0} {parentTrial ""}} {
  global out stage
  if {!(($depth eq "0" && $parentTrial eq "") ||
        ($depth eq "1" && $parentTrial in {regional-first regional-midpoint}))} {error NATIVE_REPACK_DEPTH}
  set tag [expr {$depth ? "-cascade-$parentTrial" : ""}]
  if {$stage ni {place clock global}} {error "NATIVE_REPACK_AFTER_ROUTING $stage"}
  set bad [oversized_native_groups]
  if {![llength $bad]} {return}
  puts "NATIVE_REPACK_GROUPS [lmap row $bad {lindex $row 0}]"
  set block [ord::get_db_block]
  set dbu [$block getDbUnitsPerMicron]
  set original_targets {}
  foreach row $bad {
    foreach name [lindex $row 2] {dict set original_targets [$block findInst $name] 1}
  }
  set saved [native_locations]
  if {[catch {write_db $out/$stage$tag-before-native-repack.odb} diagnostic]} {
    puts "NATIVE_REPACK_DIAGNOSTIC_FAILED $diagnostic"
  }
  # Select once from the legal baseline, never from a failed trial's movement.
  # 96um selects neighbors; it is not a fence on their final position.
  set regional_targets [native_repack_neighbors $bad $saved $original_targets]
  # DPL imports placement statuses on every invocation. FIRM pins all other
  # cells temporarily; source/parent masters and connectivity never change.
  foreach trial {first midpoint last regional-first regional-midpoint} {
    set targets $original_targets
    set anchor $trial
    if {[string match regional-* $trial]} {
      set targets $regional_targets
      set anchor [string range $trial 9 end]
    }
    puts "NATIVE_REPACK_TRIAL $trial [dict size $targets]"
    set accepted 0
    try {
      dict for {inst record} $saved {
        set status [lindex $record 3]
        if {[dict exists $targets $inst]} {
          if {$status in {FIRM LOCKED COVER}} {error "NATIVE_REPACK_FIXED_TARGET [$inst getName]"}
        } elseif {$status ni {FIRM LOCKED COVER}} {$inst setPlacementStatus FIRM}
      }
      foreach row $bad {
        lassign [native_group_geometry $row] dx dy cells
        # Deterministic neighborhoods; lexical order need not put source first.
        # These are search choices, not wider acceptance limits.
        set first [lindex $cells 0]; set last [lindex $cells end]
        set x [lindex $first 1]; set y [lindex $first 2]
        if {$anchor eq "last"} {set x [lindex $last 1]; set y [lindex $last 2]}
        if {$anchor eq "midpoint"} {
          set x [expr {([lindex $first 1]+[lindex $last 1])/2}]
          set y [expr {([lindex $first 2]+[lindex $last 2])/2}]
        }
        set offset 0; set row_y 0; set row_height 0
        foreach cell $cells {
          lassign $cell name x0 y0 x1 y1
          set width [expr {$x1-$x0}]; set height [expr {$y1-$y0}]
          if {$offset+$width>32 && $offset>0} {
            set offset 0; set row_y [expr {$row_y+$row_height}]; set row_height 0
          }
          set inst [$block findInst $name]
          $inst setLocation [expr {int(round(($x+$offset)*$dbu))}] [expr {int(round(($y+$row_y)*$dbu))}]
          $inst setPlacementStatus PLACED
          set offset [expr {$offset+$width}]; set row_height [expr {max($row_height,$height)}]
        }
      }
      if {$anchor eq "first"} {
        # Keep the first member's legal hole. Otherwise a small cell can take
        # it first and leave no legal hole for a larger member.
        foreach row $bad {
          set inst [$block findInst [lindex $row 2 0]]
          lassign [dict get $saved $inst] x y orient status
          $inst setOrient $orient; $inst setLocation $x $y
          $inst setPlacementStatus FIRM
        }
      }
      detailed_placement -max_displacement {48 48}
      check_placement -verbose
      # A regional legalization can repair the original groups but displace a
      # neighboring complete group. Allow one bounded local correction, keeping
      # everything outside this trial's region fixed. Nested failure rolls back
      # through both saved placements. The span and per-call DPL search bounds
      # stay unchanged; these do not bound cumulative movement from seeding.
      if {$depth==0 && [string match regional-* $trial] && [llength [oversized_native_groups]]} {
        dict for {inst unused} $targets {
          $inst setPlacementStatus [lindex [dict get $saved $inst] 3]
        }
        puts "NATIVE_REPACK_CASCADE $trial"
        repack_native_groups 1 $trial
        check_placement -verbose
      }
      dict for {inst record} $saved {
        if {[dict exists $targets $inst]} {continue}
        set box [$inst getBBox]
        if {[list [$box xMin] [$box yMin] [$inst getOrient]] ne [lrange $record 0 2]} {
          error "NATIVE_REPACK_MOVED_NEIGHBOR [$inst getName]"
        }
      }
      if {[llength [oversized_native_groups]]} {error NATIVE_REPACK_SPREAD}
      set accepted 1
    } on error {message options} {
      if {[catch {write_db $out/$stage$tag-native-repack-$trial-failed.odb} diagnostic]} {
        puts "NATIVE_REPACK_DIAGNOSTIC_FAILED $diagnostic"
      }
      puts "NATIVE_REPACK_REJECTED $trial $message"
      # DPL can move instances before throwing. Every retry starts from the
      # same legal placement, including orientation and original statuses.
    } finally {
      if {!$accepted} {restore_native_locations $saved} else {
        dict for {inst record} $saved {$inst setPlacementStatus [lindex $record 3]}
      }
    }
    if {$accepted} {puts "NATIVE_REPACK_PASS $trial [llength $bad]"; return}
  }
  error NATIVE_REPACK_NO_LEGAL_NEIGHBORHOOD
}
# Capture only compact-group geometry before electrical repair. Same-master
# members keep these legal holes; changed masters and new cells stay movable.
proc native_repair_baseline {} {
  global native_placement_groups
  set baseline {}; set block [ord::get_db_block]
  if {[llength [oversized_native_groups]]} {error NATIVE_REPAIR_BASELINE_SPREAD}
  foreach row $native_placement_groups {foreach name [lindex $row 2] {
    set inst [$block findInst $name]
    if {[dict exists $baseline $inst]} {error NATIVE_REPAIR_BASELINE_DUPLICATE}
    set b [$inst getBBox]
    dict set baseline $inst [list [[$inst getMaster] getName] [$b xMin] [$b yMin] [$inst getOrient] [$inst getPlacementStatus]]
  }}
  return $baseline
}
proc native_anchor_legalization {{baseline {}}} {
  global native_placement_groups protected_cells out stage
  if {$baseline eq "" && [llength [oversized_native_groups]]} {return 0}
  set saved [native_locations]; set changed {}; set anchored {}; set accepted 0
  set block [ord::get_db_block]
  set protected {}
  foreach row $protected_cells {dict set protected [lindex $row 0] 1}
  try {
    set members {}
    foreach row $native_placement_groups {foreach name [lindex $row 2] {
      set inst [$block findInst $name]
      dict set members $inst 1
    }}
    if {$baseline ne "" && [lsort [dict keys $baseline]] ne [lsort [dict keys $members]]} {
      error NATIVE_REPAIR_BASELINE_INVENTORY
    }
    dict for {inst unused} $members {
      set name [$inst getName]
      set status [lindex [dict get $saved $inst] 3]
      set expected [lrange [dict get $saved $inst] 0 2]
      if {$baseline ne ""} {
        lassign [dict get $baseline $inst] master x y orient old_status
        if {$status in {FIRM LOCKED COVER} || $old_status in {FIRM LOCKED COVER}} {
          if {$status ne $old_status || $expected ne [list $x $y $orient] ||
              [[$inst getMaster] getName] ne $master} {error NATIVE_REPAIR_FIXED_CHANGED}
          dict set anchored $inst $expected
          continue
        }
        if {[[$inst getMaster] getName] ne $master} {
          if {[dict exists $protected $name]} {error NATIVE_REPAIR_PROTECTED_MASTER}
          continue
        }
        # Repair can grow neighboring ordinary cells. Preserve the complete
        # previously legal compact group, not a dispersed post-DPL location.
        $inst setPlacementStatus PLACED
        $inst setOrient $orient; $inst setLocation $x $y
        set expected [list $x $y $orient]
      } elseif {![dict exists $protected $name]} {continue}
      dict set anchored $inst $expected
      if {$status ni {FIRM LOCKED COVER} || $baseline ne ""} {
        dict set changed $inst $status
        $inst setPlacementStatus FIRM
      }
    }
    detailed_placement -max_displacement {500 500}
    check_placement -verbose
    dict for {inst expected} $anchored {
      set b [$inst getBBox]
      if {[list [$b xMin] [$b yMin] [$inst getOrient]] ne $expected} {
        error "NATIVE_ANCHOR_MOVED [$inst getName]"
      }
    }
    # Newly inserted ordinary buffers may have started UNPLACED. Preserve their
    # successful legalization; restore only statuses temporarily changed here.
    dict for {inst status} $changed {$inst setPlacementStatus $status}
    check_placement -verbose
    repack_native_groups
    check_placement -verbose
    check_native_placement
    check_module_bounds
    set accepted 1
  } on error {message options} {
    if {[catch {write_db $out/$stage-native-anchor-failed.odb} diagnostic]} {
      puts "NATIVE_DPL_DIAGNOSTIC_FAILED $diagnostic"
    }
    puts "NATIVE_ANCHOR_REJECTED $message"
  } finally {
    if {!$accepted} {restore_native_locations $saved}
  }
  if {$accepted} {puts NATIVE_ANCHOR_PASS}
  return $accepted
}
proc native_detailed_placement {{baseline {}}} {
  global out stage
  assign_module_helpers
  if {[native_anchor_legalization $baseline]} {return}
  # Search radius is not a native span allowance. A wider ordinary-cell retry
  # can legalize macro-pin congestion; native groups still must fit within 64um.
  set saved [native_locations]
  foreach radius {100 500} {
    set accepted 0
    try {
      detailed_placement -max_displacement [list $radius $radius]
      set accepted 1
    } on error {message options} {
      if {[catch {write_db $out/$stage-dpl-$radius-failed.odb} diagnostic]} {
        puts "NATIVE_DPL_DIAGNOSTIC_FAILED $diagnostic"
      }
      puts "NATIVE_ORDINARY_DPL_REJECTED $radius $message"
      if {$radius==500} {return -options $options $message}
    } finally {
      if {!$accepted} {restore_native_locations $saved}
    }
    if {$accepted} {break}
  }
  check_placement -verbose
  repack_native_groups
  check_placement -verbose
  check_native_placement
  check_module_bounds
}
proc check_native_placement {} {
  global native_placement_groups native_output_feeders native_input_feeders out stage
  set block [ord::get_db_block]
  set f [open $out/$stage-native-placement.tsv w]
  set failures {}
  foreach row $native_placement_groups {
    lassign $row id limit names
    lassign [native_group_geometry $row] dx dy cells
    foreach cell $cells {
      lassign $cell name x0 y0 x1 y1
      puts $f "C\t$id\t$name\t$x0\t$y0\t$x1\t$y1"
    }
    puts $f "G\t$id\t$limit\t$dx\t$dy"
    if {[catch {native_span_bound $id $limit $dx $dy} message]} {lappend failures $message}
  }
  if {[llength $failures]} {
    close $f
    write_db $out/$stage-native-spread-failed.odb
    error [join $failures \n]
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
  foreach row $native_input_feeders {
    lassign $row parent receivers
    set inst [$block findInst $parent]
    if {$inst eq "NULL" || ![regexp {__(clk)?buf_[0-9]+$} [[$inst getMaster] getName]]} {
      error "NATIVE_INPUT_PARENT_POLARITY $parent"
    }
    set net [[$inst findITerm Z] getNet]
    if {$net eq "NULL" || [llength [$net getBTerms]]} {error "NATIVE_INPUT_LOCAL_NET $parent"}
    set expected [list [list $parent Z]]
    foreach receiver $receivers {
      lassign $receiver name pin
      set sink [[$block findInst $name] findITerm $pin]
      if {[$sink getNet] ne $net || [[$sink getMTerm] getIoType] ne "INPUT"} {
        error "NATIVE_INPUT_RECEIVER_CHANGED $name/$pin"
      }
      lappend expected [list $name $pin]
    }
    set actual {}
    foreach terminal [$net getITerms] {
      if {[$terminal getSigType] in {POWER GROUND}} {continue}
      lappend actual [list [[$terminal getInst] getName] [[$terminal getMTerm] getName]]
    }
    if {[llength $receivers]==0 || [lsort $actual] ne [lsort $expected]} {
      error "NATIVE_INPUT_EXTERNAL_BYPASS $parent"
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
    # This short native-to-parent link is immutable. Upstream distribution at
    # an isolated receiver is repairable; unisolated native inputs still lock
    # their net and retain their electrical failures in the reports.
    [$terminal getNet] setDoNotTouch true
  }
}
