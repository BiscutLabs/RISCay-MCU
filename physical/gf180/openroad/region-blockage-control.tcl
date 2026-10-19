# SPDX-License-Identifier: Apache-2.0
# Driver supplies fixture_source and scenario. Uses unchanged upstream data.
read_lef $fixture_source/src/gpl/test/nangate45.lef
read_def $fixture_source/src/gpl/test/simple01.def
set block [ord::get_db_block]; set dbu [$block getDbUnitsPerMicron]
set cells [$block getInsts]
set fixed [lindex $cells 0]
$fixed setLocation [expr {int(.38*$dbu)}] [expr {int(2.8*$dbu)}]
if {$scenario eq "fixed-partial"} {$fixed setLocation [expr {int(14.82*$dbu)}] [expr {int(2.8*$dbu)}]}
$fixed setPlacementStatus LOCKED
set b [$fixed getBBox]
puts "CONTROL_FIXED_AREA [expr {([$b xMax]-[$b xMin])*([$b yMax]-[$b yMin])/double($dbu*$dbu)}]"
if {$scenario ne "top-far"} {
  set region [odb::dbRegion_create $block test_region]
  $region setRegionType EXCLUSIVE
  odb::dbBox_create $region 0 0 [expr {int(15.2*$dbu)}] [expr {int(14*$dbu)}]
  set group [odb::dbGroup_create $block test_group]; $region addGroup $group
  if {$scenario eq "power-domain"} {$group setType POWER_DOMAIN}
  foreach inst [lrange $cells 1 10] {$group addInst $inst}
}
if {$scenario in {far top-far}} {
  create_blockage -region {20.14 19.6 28.5 28}
}
if {$scenario eq "partial"} {
  create_blockage -region {14.06 2.8 17.1 5.6}
}
if {$scenario eq "fixed-overlap"} {
  create_blockage -region [list [expr {[$b xMin]/double($dbu)}] [expr {[$b yMin]/double($dbu)}] \
    [expr {[$b xMax]/double($dbu)}] [expr {[$b yMax]/double($dbu)}]]
}
global_placement -skip_nesterov_place -initial_place_max_iter 1 -density .8
puts REGION_ACCOUNTING_CONTROL_COMPLETE
exit
