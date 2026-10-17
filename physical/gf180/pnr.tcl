# SPDX-License-Identifier: Apache-2.0
# Experimental digital-only flow. Keep every failed timing report visible.
set_thread_count $threads
set pvt_corners {tt_025C_3v30 ss_125C_3v00 ss_n40C_3v00 ff_125C_3v60 ff_n40C_3v60}
define_corners {*}$pvt_corners
foreach corner $pvt_corners {
  read_liberty -corner $corner $pdk/${sc}${corner}.lib
  read_liberty -corner $corner $sram/${sram_cell}__${corner}.lib
}
source $source/pnr-repair.tcl
if {$stage eq "floorplan"} {
  read_lef $routing/technology.tlef
  read_lef $pdk/gf180mcu_fd_sc_mcu7t5v0.lef
  read_lef $sram/${sram_cell}.lef
  read_verilog $mapping/netlist.v
  link_design RiscayMcuDigital
} else {
  read_db $out/$previous.odb
}
source $mapping/base.sdc
source $mapping/clocked.sdc
source $mapping/feedback-cuts.tcl
# Electrical optimization must not expand the legacy all-register/wide-bus
# async path matrix. Its complete constraints are saved and hashed separately;
# native timing is measured in the contract-driven analysis campaigns.
source $out/async-electrical.sdc
source $out/protected.tcl
proc connect_power {} {
  global protected_cells mapping source
  # OpenDB's dont-touch also blocks power connections. Release protection only
  # around this power-only operation, then restore it before any optimization.
  foreach record $protected_cells {unset_dont_touch [get_cells [lindex $record 0]]}
  source $source/power.tcl
  source $mapping/preserve-mapped.tcl
  foreach inst [[ord::get_db_block] getInsts] {
    foreach pin [$inst getITerms] {
      if {[$pin getSigType] in {POWER GROUND} && [$pin getNet] eq "NULL"} {
        error "UNCONNECTED_SUPPLY [$inst getName]/[[$pin getMTerm] getName]"
      }
    }
  }
}
connect_power
# Published fit in this pinned PDK's LibreLane config (kohm/um, pF/um).
foreach {layer resistance capacitance} {
  Metal2 3.85861e-4 1.35357e-4
  Metal3 2.06673e-4 1.46141e-4
  Metal4 1.68609e-4 1.50688e-4
  Metal5 7.92778e-5 1.55595e-4
} {set_layer_rc -layer $layer -resistance $resistance -capacitance $capacitance}
set_wire_rc -signal -layer Metal3
set_wire_rc -clock -layer Metal4

proc protected_snapshot {} {
  global protected_cells
  set block [ord::get_db_block]
  set snapshot {}
  foreach record $protected_cells {
    lassign $record name master pins
    set inst [$block findInst $name]
    if {$inst eq "NULL" || [[$inst getMaster] getName] ne $master} {error "PROTECTED_CELL_CHANGED $name"}
    foreach pin $pins {
      set terminal [$inst findITerm $pin]
      if {$terminal eq "NULL" || [$terminal getNet] eq "NULL"} {error "PROTECTED_PIN_MISSING $name/$pin"}
      lappend snapshot [list $name $pin [[$terminal getNet] getName]]
    }
  }
  return $snapshot
}

if {$stage eq "floorplan"} {
  initialize_floorplan -die_area $die_area -core_area $core_area -site GF018hv5v_mcu_sc7
  foreach layer {Metal1 Metal2 Metal3 Metal4} {make_tracks $layer -x_offset 0.28 -x_pitch 0.56 -y_offset 0.28 -y_pitch 0.56}
  make_tracks Metal5 -x_offset 0.45 -x_pitch 0.90 -y_offset 0.45 -y_pitch 0.90
  foreach record $macro_locations {
    lassign $record name x y
    place_macro -macro_name $name -location [list $x $y] -orientation R0 -exact
  }
  tapcell -tapcell_master ${sc}filltie -endcap_master ${sc}endcap -distance 20 -halo_width_x 12 -halo_width_y 12
  insert_tiecells ${sc}tieh/Z
  insert_tiecells ${sc}tiel/ZN
  repair_tie_fanout -separation 1 ${sc}tieh/Z
  repair_tie_fanout -separation 1 ${sc}tiel/ZN
  place_pins -hor_layers Metal3 -ver_layers Metal2
  connect_power
  source $source/pnr-pdn.tcl
  pdngen -failed_via_report $out/pdn-vias.rpt
  check_power_grid -net VDD -floorplanning -error_file $out/pdn-vdd.rpt
  check_power_grid -net VSS -floorplanning -error_file $out/pdn-vss.rpt
  set f [open $out/protected-baseline.tcl w]; puts $f [list set expected_protected [protected_snapshot]]; close $f
}
if {$stage eq "place"} {
  # The input has already passed default global pre-placement repair and its
  # graph audit. Wire-dependent electrical closure remains a separate gate;
  # do not silently alter protected native graphs during placement.
  global_placement -density $placement_density -routability_driven
  detailed_placement
  check_placement -verbose
  estimate_parasitics -placement
  wire_repair
  estimate_parasitics -placement
}
if {$stage eq "clock"} {
  # Explicit roots exclude SDA and all self-timed capture networks. The service
  # tree follows the related gated work branch; async local trees stay intact.
  clock_tree_synthesis -clk_nets {serviceClock soc/gate_io_clockOut watchdogClock} \
    -root_buf ${sc}clkbuf_16 -buf_list [list ${sc}clkbuf_2 ${sc}clkbuf_4 ${sc}clkbuf_8] \
    -sink_clustering_enable -sink_clustering_size 16 -sink_clustering_max_diameter 100 \
    -obstruction_aware -dont_use_dummy_load
  detailed_placement
  check_placement -verbose
  set_propagated_clock [get_clocks {service work lf}]
  estimate_parasitics -placement
  report_cts -out_file $out/cts.rpt
}
if {$stage eq "global"} {
  set_propagated_clock [get_clocks {service work lf}]
  set_routing_layers -signal Metal2-Metal5 -clock Metal2-Metal5
  set_global_routing_layer_adjustment Metal2-Metal5 0.15
  global_route -guide_file $out/route.guide -congestion_iterations 100 -congestion_report_file $out/congestion.rpt -verbose
  estimate_parasitics -global_routing
  # Track added cells, moved cells and changed nets in the existing route.
  global_route -start_incremental
  wire_repair
  global_route -end_incremental -guide_file $out/route.guide -congestion_iterations 100
  estimate_parasitics -global_routing
}
if {$stage eq "route"} {
  set_propagated_clock [get_clocks {service work lf}]
  set_routing_layers -signal Metal2-Metal5 -clock Metal2-Metal5
  read_guides $out/route.guide
  detailed_route -output_drc $out/route-drc.rpt -output_guide_coverage $out/guide-coverage.rpt \
    -droute_end_iter 32 -or_seed 42
}
if {$stage eq "extract"} {
  set_propagated_clock [get_clocks {service work lf}]
  # Hierarchical-looking names on newly inserted flat tie cells confuse SPEF
  # instance lookup after an ODB reload. Rename only these physical instances;
  # no cell, connection, placement or route changes.
  set tie_index 0
  foreach inst [[ord::get_db_block] getInsts] {
    if {[[$inst getMaster] getName] in [list ${sc}tieh ${sc}tiel] && [string first / [$inst getName]]>=0} {
      if {![$inst rename riscay_pnr_tie_$tie_index]} {error TIE_RENAME_FAILED}
      incr tie_index
    }
  }
  define_process_corner -ext_model_index 0 $rc_corner
  extract_parasitics -ext_model_file $routing/rcx.$rc_corner
  write_spef $out/routed-$rc_corner.spef
  if {$rc_corner eq "nom"} {file copy -force $out/routed-nom.spef $out/routed.spef}
}
source $out/protected-baseline.tcl
if {[protected_snapshot] ne $expected_protected} {error "PROTECTED_CONNECTIVITY_CHANGED"}
puts "PROTECTED_AUDIT_PASS [llength $protected_cells]"
connect_power
write_db $out/$checkpoint.odb
write_def $out/$checkpoint.def
write_verilog -include_pwr_gnd $out/$checkpoint.v
write_sdc $out/$checkpoint.sdc
if {$stage in {place clock global extract}} {
  report_checks -path_delay min_max -group_path_count 10 -format full_clock_expanded > $out/$checkpoint-clocked-timing.rpt
  report_check_types -max_slew -max_capacitance -violators > $out/$checkpoint-electrical.rpt
  electrical_reports $checkpoint
}
report_design_area
puts "PNR_STAGE_COMPLETE $stage"
exit
