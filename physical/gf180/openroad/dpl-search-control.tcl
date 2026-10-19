# SPDX-License-Identifier: Apache-2.0
# Driver supplies fixture_source and scenario. The upstream single-cell fixture
# deliberately starts diagonally outside the clipped region's placement grid.
read_lef $fixture_source/test/Nangate45/Nangate45.lef
read_def $fixture_source/src/dpl/test/simple01.def
set block [ord::get_db_block]; set dbu [$block getDbUnitsPerMicron]
set inst [$block findInst _277_]; set master [$inst getMaster]
set box {2.679 1.54 7.22 7.0}; set start {2.679 1.54}
if {$scenario eq "inside"} {set start {2.85 2.8}}
if {$scenario eq "full"} {
  set box [list 2.85 2.8 [expr {2.85+[$master getWidth]/double($dbu)}] 4.2]
  set start {2.85 2.8}
  set fixed [odb::dbInst_create $block $master fixed_blocker]
  $fixed setLocation [expr {round(2.85*$dbu)}] [expr {round(2.8*$dbu)}]
  $fixed setOrient R0
  $fixed setPlacementStatus LOCKED
}
set region [odb::dbRegion_create $block test_region]
$region setRegionType EXCLUSIVE
set coords [lmap v $box {expr {round($v*$dbu)}}]
odb::dbBox_create $region {*}$coords
set group [odb::dbGroup_create $block test_group]; $region addGroup $group; $group addInst $inst
lassign $start x y
$inst setLocation [expr {round($x*$dbu)}] [expr {round($y*$dbu)}]
$inst setPlacementStatus PLACED
set inventory [lsort [lmap i [$block getInsts] {list [$i getName] [[$i getMaster] getName]}]]
if {[catch {detailed_placement -max_displacement {10 10}} message options]} {
  if {$expected_rejection eq "" || [string first $expected_rejection $message]<0} {
    return -options $options $message
  }
  puts "DPL_CONTROL_REJECTED $message"
  exit
}
if {$expected_rejection ne ""} {error DPL_CONTROL_EXPECTED_REJECTION_MISSING}
check_placement -verbose
if {[lsort [lmap i [$block getInsts] {list [$i getName] [[$i getMaster] getName]}]] ne $inventory} {error DPL_CONTROL_INVENTORY}
lassign $coords x0 y0 x1 y1
set b [$inst getBBox]
if {[$b xMin]<$x0 || [$b yMin]<$y0 || [$b xMax]>$x1 || [$b yMax]>$y1} {error DPL_CONTROL_OUTSIDE}
puts "DPL_CONTROL_PASS [$inst getLocation] [$inst getOrient]"
exit
