# SPDX-License-Identifier: Apache-2.0
# Ordinary synchronous baseline. No async constraints, disabled arcs or waivers.
set_thread_count 8
set corners {tt_025C_3v30 ss_125C_3v00 ss_n40C_3v00 ff_125C_3v60 ff_n40C_3v60}
define_corners {*}$corners
foreach c $corners {
  read_liberty -corner $c $liberty/${sc}${c}.lib
  read_liberty -corner $c $sram/${sram_cell}__${c}.lib
}
read_lef $routing/technology.tlef
read_lef $pdk/gf180mcu_fd_sc_mcu7t5v0.lef
read_lef $sram/${sram_cell}.lef
read_verilog $out/prepared.v
link_design RiscayMcuDigital
initialize_floorplan -die_area {0 0 1940 2530} -core_area {30 30 1910 2500} -site GF018hv5v_mcu_sc7
foreach layer {Metal1 Metal2 Metal3 Metal4} {make_tracks $layer -x_offset .28 -x_pitch .56 -y_offset .28 -y_pitch .56}
make_tracks Metal5 -x_offset .45 -x_pitch .9 -y_offset .9 -y_pitch .9
foreach name $macros x {100 819.35 1540} {
  place_macro -macro_name $name -location [list $x 1954] -orientation R0 -exact
  create_blockage -region [list [expr {$x-24}] 1914 [expr {$x+325.3}] 2493.81]
}
create_clock -name service -period 50 -waveform {0 25} [get_ports serviceClock]
create_generated_clock -name work -source [get_ports serviceClock] -divide_by 1 -combinational [get_pins $work_root]
create_clock -name lf -period 83333333.333 [get_ports watchdogClock]
create_clock -name i2c_start -period 2500 [get_ports sda]
set_clock_uncertainty .5 [get_clocks {service work}]
set_clock_transition .5 [get_clocks {service work}]
set_clock_transition 2 [get_clocks {lf i2c_start}]
set_input_transition 2 [all_inputs]
set_load .05 [all_outputs]
# Ordinary logic uses 80% of each corner's own Liberty limit. Only clock
# distribution uses the 2 ns control limit. Tables themselves are unchanged.
set_max_transition 2 -clock_path [get_clocks {service work lf i2c_start}]
set_dont_use [get_lib_cells */*dff*]
set_dont_use [get_lib_cells */*lat*]
set_wire_rc -resistance 0 -capacitance 0
repair_design -max_wire_length 0
write_verilog $out/repaired.v
foreach c $corners {report_check_types -corner $c -max_slew -max_capacitance -violators -digits 6 -no_line_splits > $out/repaired-$c-electrical.rpt}
# Same corrected ohm/um conversion as the routed BD flow.
foreach {layer r cap} {Metal3 .206673 .000146141 Metal4 .168609 .000150688} {
  set_layer_rc -layer $layer -resistance [sta::resistance_sta_ui $r] -capacitance [sta::capacitance_sta_ui [expr {$cap*1e-12}]]
}
set_wire_rc -signal -layer Metal3
set_wire_rc -clock -layer Metal4
place_pins -hor_layers Metal3 -ver_layers Metal2
global_placement -density .60 -overflow .15
detailed_placement
check_placement -verbose
estimate_parasitics -placement
repair_design -slew_margin 10 -cap_margin 10
detailed_placement
check_placement -verbose
estimate_parasitics -placement
write_verilog $out/placed.v
set_cts_config -skip_nets {sda}
clock_tree_synthesis -root_buf ${sc}clkbuf_16 -buf_list [list ${sc}clkbuf_2 ${sc}clkbuf_4 ${sc}clkbuf_8] -sink_clustering_enable -sink_clustering_size 16 -sink_clustering_max_diameter 100 -obstruction_aware -dont_use_dummy_load
detailed_placement
check_placement -verbose
set_propagated_clock [get_clocks {service work lf}]
estimate_parasitics -placement
write_verilog $out/cts.v
write_db $out/cts.odb
write_sdc $out/cts.sdc
report_cts -out_file $out/cts.rpt
set f [open $out/clock-sinks.tsv w]
foreach c {service work lf i2c_start} {
  foreach edge {rise fall} {
    foreach pin [all_registers -${edge}_clock [get_clocks $c] -clock_pins] {puts $f "$c\t$edge\t[get_full_name $pin]"}
  }
}
close $f
foreach c $corners {
  report_check_types -corner $c -max_slew -max_capacitance -violators -digits 6 -no_line_splits > $out/cts-$c-electrical.rpt
  report_checks -corner $c -path_delay min_max -group_path_count 10 -format full_clock_expanded -digits 6 > $out/cts-$c-timing.rpt
}
puts CLOCKED_PHYSICAL_COMPLETE
