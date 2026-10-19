# SPDX-License-Identifier: Apache-2.0
# Soft experiment: unattached SUGGESTED metadata and movable GPL seeds.
# Bounded experiment: EXCLUSIVE regions with explicit original/helper groups.
# Guided experiment: bounded GPL/initial legalization, then local repair may spill.
proc check_released_module_guides {} {
  global module_regions module_units
  set block [ord::get_db_block]
  foreach row $module_regions {
    set name [lindex $row 0]; set region [$block findRegion riscay_$name]
    if {$region eq "NULL" || [$region getRegionType] ne "SUGGESTED" ||
        [llength [$region getGroups]] || [$block findGroup riscay_$name] ne "NULL"} {
      error "MODULE_GUIDE_NOT_RELEASED $name"
    }
  }
  foreach row $module_units {foreach name [lindex $row 1] {
    set inst [$block findInst $name]
    if {$inst eq "NULL" || ![$inst isPlaced] || [$inst getGroup] ne "NULL"} {
      error "MODULE_GUIDE_MEMBER $name"
    }
  }}
  puts MODULE_GUIDES_RELEASED
}

proc release_module_guides {} {
  global module_region_guided module_region_bounded module_regions out
  if {!$module_region_guided} {return}
  check_module_bounds
  check_placement -verbose
  report_module_regions guided-legal
  write_db $out/guided-legal.odb
  set before [native_locations]
  set block [ord::get_db_block]
  set graph_before [module_release_graph]
  foreach row $module_regions {
    set name [lindex $row 0]
    # OpenDB destroy removes membership, not instances or nets. Native placement
    # clusters use a separate GPL API and are untouched by this operation.
    odb::dbGroup_destroy [$block findGroup riscay_$name]
    [$block findRegion riscay_$name] setRegionType SUGGESTED
  }
  set module_region_bounded 0
  if {[native_locations] ne $before || [module_release_graph] ne $graph_before} {
    error MODULE_RELEASE_CHANGED_CIRCUIT
  }
  check_released_module_guides
}

proc module_release_graph {} {
  set result {}
  foreach inst [[ord::get_db_block] getInsts] {
    set pins {}
    foreach pin [$inst getITerms] {lappend pins $pin [$pin getNet]}
    dict set result $inst [list [$inst getMaster] $pins]
  }
  return $result
}

proc seed_module_regions {} {
  global module_regions module_units module_region_seed module_region_bounded module_region_grid
  if {!$module_region_seed} {return}
  set block [ord::get_db_block]; set dbu [$block getDbUnitsPerMicron]
  # Verify generated LEF-grid fences against actual OpenDB rows, rather than
  # assuming initialize_floorplan kept the requested core origin unrounded.
  set first_row [lindex [$block getRows] 0]
  if {$first_row eq ""} {error MODULE_ROWS_MISSING}
  lassign [$first_row getOrigin] ox oy
  set site [$first_row getSite]
  lassign $module_region_grid sx sy
  set gx [expr {round($sx*$dbu)}]; set gy [expr {round($sy*$dbu)}]
  if {[$site getWidth]!=$gx || [$site getHeight]!=$gy} {error MODULE_SITE_GRID_CHANGED}
  foreach row [$block getRows] {
    lassign [$row getOrigin] rx ry
    if {[$row getSite] ne $site || [$row getDirection] ne "HORIZONTAL" ||
        [$row getSpacing]!=$gx || ($rx-$ox)%$gx || ($ry-$oy)%$gy} {
      error MODULE_MIXED_ROW_GRID
    }
  }
  set boxes {}; set counts {}; set indices {}
  foreach row $module_units {dict incr counts [lindex $row 0]}
  foreach row $module_regions {
    lassign $row name box; dict set boxes $name $box
    set region [odb::dbRegion_create $block riscay_$name]
    $region setRegionType [expr {$module_region_bounded ? "EXCLUSIVE" : "SUGGESTED"}]
    set coords [lmap value $box {expr {round($value*$dbu)}}]
    lassign $coords x0 y0 x1 y1
    if {($x0-$ox)%$gx || ($x1-$ox)%$gx || ($y0-$oy)%$gy || ($y1-$oy)%$gy} {
      error "MODULE_FENCE_OFF_ROW_GRID $name"
    }
    odb::dbBox_create $region {*}$coords
    if {$module_region_bounded} {
      set group [odb::dbGroup_create $block riscay_$name]
      $region addGroup $group
      if {[$group getRegion] ne $region} {error MODULE_GROUP_REGION}
    }
    dict set indices $name 0
  }
  foreach row $module_units {
    lassign $row name cells
    set owner $name
    lassign [dict get $boxes $name] x0 y0 x1 y1
    set count [dict get $counts $name]; set index [dict get $indices $name]
    set nx [expr {max(1,int(ceil(sqrt($count*($x1-$x0)/($y1-$y0)))))}]
    set ny [expr {int(ceil(double($count)/$nx))}]
    set ix [expr {$index % $nx}]; set iy [expr {$index / $nx}]
    if {$iy % 2} {set ix [expr {$nx-1-$ix}]}
    set x [expr {$x0+($ix+.5)*($x1-$x0)/$nx}]
    set y [expr {$y0+($iy+.5)*($y1-$y0)/$ny}]
    # Native groups start co-located; the existing bounded native legalizer owns
    # their final spread. All cells remain movable throughout global placement.
    foreach name $cells {
      set inst [$block findInst $name]
      if {$inst eq "NULL" || [$inst isFixed]} {error "MODULE_SEED_CELL $name"}
      if {$module_region_bounded} {
        if {[$inst getGroup] ne "NULL"} {error "MODULE_PREEXISTING_GROUP $name"}
        [$block findGroup riscay_$owner] addInst $inst
      }
      set w [expr {[[$inst getMaster] getWidth]/double($dbu)}]
      set h [expr {[[$inst getMaster] getHeight]/double($dbu)}]
      if {$w>$x1-$x0 || $h>$y1-$y0} {error "MODULE_SEED_CELL_TOO_LARGE $name"}
      $inst setLocation [expr {round(max($x0,min($x1-$w,$x-$w/2))*$dbu)}] \
                       [expr {round(max($y0,min($y1-$h,$y-$h/2))*$dbu)}]
      $inst setPlacementStatus PLACED
    }
    dict incr indices [lindex $row 0]
  }
  puts "MODULE_REGIONS_SEEDED [llength $module_regions] [llength $module_units]"
  check_module_bounds
  assign_module_helpers
}

proc check_module_bounds {} {
  global module_region_bounded module_regions module_units native_placement_groups
  if {!$module_region_bounded} {return}
  set block [ord::get_db_block]; set dbu [$block getDbUnitsPerMicron]; set boxes {}
  foreach row $module_regions {
    lassign $row owner box
    set region [$block findRegion riscay_$owner]; set group [$block findGroup riscay_$owner]
    if {$region eq "NULL" || $group eq "NULL" || [$group getRegion] ne $region ||
        [$region getRegionType] ne "EXCLUSIVE" || [llength [$region getBoundaries]]!=1} {error MODULE_REGION_CHANGED}
    set coords [lmap v $box {expr {round($v*$dbu)}}]
    set b [lindex [$region getBoundaries] 0]
    if {[list [$b xMin] [$b yMin] [$b xMax] [$b yMax]] ne $coords} {error MODULE_REGION_BOX_CHANGED}
    dict set boxes $owner $coords
  }
  set seen {}
  foreach row $module_units {
    lassign $row owner names
    foreach name $names {
      if {[dict exists $seen $name]} {error MODULE_DUPLICATE_MEMBER}
      dict set seen $name $owner
      set inst [$block findInst $name]; set group [$block findGroup riscay_$owner]
      if {$inst eq "NULL" || ![$inst isPlaced] || [$inst getGroup] ne $group} {error "MODULE_MEMBER_CHANGED $name"}
      lassign [dict get $boxes $owner] x0 y0 x1 y1; set b [$inst getBBox]
      if {[$b xMin]<$x0-1 || [$b yMin]<$y0-1 || [$b xMax]>$x1+1 || [$b yMax]>$y1+1} {
        error "MODULE_CELL_OUTSIDE $owner $name"
      }
    }
  }
  foreach row $native_placement_groups {
    set owners [lsort -unique [lmap name [lindex $row 2] {dict get $seen $name}]]
    if {[llength $owners]!=1} {error "MODULE_SPLIT_NATIVE_GROUP [lindex $row 0]"}
  }
  foreach inst [$block getInsts] {
    set group [$inst getGroup]
    if {$group eq "NULL" || [$inst isFixed] || [dict exists $seen [$inst getName]]} {continue}
    set owner [string range [$group getName] 7 end]
    if {![dict exists $boxes $owner] || [$group getRegion] ne [$block findRegion riscay_$owner] || ![$inst isPlaced]} {
      error "MODULE_HELPER_GROUP [$inst getName]"
    }
    lassign [dict get $boxes $owner] x0 y0 x1 y1; set b [$inst getBBox]
    if {[$b xMin]<$x0-1 || [$b yMin]<$y0-1 || [$b xMax]>$x1+1 || [$b yMax]>$y1+1} {
      error "MODULE_HELPER_OUTSIDE $owner [$inst getName]"
    }
  }
  puts "MODULE_BOUNDS_PASS [dict size $seen]"
}

proc assign_module_helpers {} {
  global module_region_bounded module_regions module_units out stage
  if {!$module_region_bounded} {return}
  set block [ord::get_db_block]; set dbu [$block getDbUnitsPerMicron]; set original {}
  foreach row $module_units {foreach name [lindex $row 1] {dict set original $name 1}}
  set f [open $out/$stage-module-helpers.tsv a]
  puts $f "# assignment pass"
  foreach inst [$block getInsts] {
    set name [$inst getName]
    if {[$inst isFixed] || [dict exists $original $name]} {continue}
    set group [$inst getGroup]; set policy retained
    if {$group eq "NULL"} {
      set b [$inst getBBox]; set x [expr {([$b xMin]+[$b xMax])/(2.0*$dbu)}]
      set y [expr {([$b yMin]+[$b yMax])/(2.0*$dbu)}]
      foreach row $module_regions {
        lassign $row owner box; lassign $box x0 y0 x1 y1
        if {$x>=$x0 && $x<$x1 && $y>=$y0 && $y<$y1} {
          set group [$block findGroup riscay_$owner]; set policy location; break
        }
      }
      # Unplaced ties/buffers have no useful location. Assign only when all
      # connected grouped cells agree; shared boundary trees remain outside.
      if {$group eq "NULL"} {
        set adjacent {}
        foreach pin [$inst getITerms] {
          if {[$pin getSigType] in {POWER GROUND} || [$pin getNet] eq "NULL"} {continue}
          foreach term [[$pin getNet] getITerms] {
            set g [[$term getInst] getGroup]
            if {$g ne "NULL"} {lappend adjacent $g}
          }
        }
        set adjacent [lsort -unique $adjacent]
        if {[llength $adjacent]==1} {set group [lindex $adjacent 0]; set policy unique-neighbor}
      }
      if {$group ne "NULL"} {$group addInst $inst}
    }
    set selected [expr {$group eq "NULL" ? "outside" : [$group getName]}]
    puts $f "$name\t$selected\t$policy\t[[$inst getMaster] getName]"
  }
  close $f
}

proc report_module_regions {suffix} {
  global module_units module_region_seed out
  if {![llength $module_units]} {return}
  set block [ord::get_db_block]; set dbu [$block getDbUnitsPerMicron]
  set f [open $out/$suffix-module-geometry.tsv w]
  foreach row $module_units {
    lassign $row owner cells
    foreach name $cells {
      set inst [$block findInst $name]
      if {$inst eq "NULL" || ![$inst isPlaced]} {error "MODULE_GEOMETRY_MISSING $name"}
      set b [$inst getBBox]
      puts $f "$owner\t$name\t[expr {[$b xMin]/double($dbu)}]\t[expr {[$b yMin]/double($dbu)}]\t[expr {[$b xMax]/double($dbu)}]\t[expr {[$b yMax]/double($dbu)}]"
    }
  }
  close $f
}

proc place_module_boundary_pins {} {
  global die_area
  lassign $die_area x0 y0 x1 y1
  # Identical locations in regional and unrestricted runs. Digital boundary
  # pins only; this is not an IO padframe or a package pin assignment.
  set targets [dict create scl [list $x0 745] sda [list $x0 775] sdaLow [list $x0 805] \
    adcMiso [list $x1 1020] adcCsN [list $x1 1050] adcSclk [list $x1 1080] \
    serviceClock [list 150 $y0] watchdogClock [list 180 $y0] reset [list 210 $y0] \
    powerGood [list 240 $y0] serviceClockEnable [list 270 $y0] porReleased [list 300 $y0]]
  foreach term [[ord::get_db_block] getBTerms] {
    set n [$term getName]
    if {[regexp {^gpio(In|Out|Oe)\[([0-9]+)\]$} $n all kind bit]} {
      set slot [dict get {In 0 Out 1 Oe 2} $kind]
      dict set targets $n [list $x1 [expr {440+($bit*3+$slot)*18}]]
    }
    if {[$term getSigType] in {POWER GROUND}} {continue}
    if {![dict exists $targets $n]} {error "MODULE_PIN_UNASSIGNED $n"}
    set pos [dict get $targets $n]
    set layer [expr {[lindex $pos 1]==$y0 ? "Metal2" : "Metal3"}]
    place_pin -pin_name $n -layer $layer -location $pos -force_to_die_boundary
    # Allow only track/grid snapping, not a move to a different edge or module.
    set box [$term getBBox]; set dbu [[ord::get_db_block] getDbUnitsPerMicron]
    set px [expr {([$box xMin]+[$box xMax])/(2.0*$dbu)}]
    set py [expr {([$box yMin]+[$box yMax])/(2.0*$dbu)}]
    if {abs($px-[lindex $pos 0])>1 || abs($py-[lindex $pos 1])>1} {
      error "MODULE_PIN_DISPLACED $n $px $py"
    }
  }
}
