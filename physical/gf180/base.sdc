# SPDX-License-Identifier: Apache-2.0
# ns / pF; fastest supported sources. This file alone is NOT async signoff.
create_clock -name service -period 50.0 -waveform {0 25} [get_ports serviceClock]
create_clock -name lf -period 83333333.333333 -waveform {0 41666666.666667} [get_ports watchdogClock]
set_clock_uncertainty 0.5 [get_clocks service]
set_clock_uncertainty 1000 [get_clocks lf]
set_clock_transition 0.5 [get_clocks service]
set_clock_transition 2.0 [get_clocks lf]
set_input_transition 2.0 [get_ports {reset powerGood scl sda adcMiso gpioIn*}]
set_load 0.05 [all_outputs]
set_max_transition 2.0 [current_design]
# Use each cell's Liberty capacitance limit. Characterized adapter outputs have
# the tighter 0.05 pF bound in async.sdc; clock-tree BUF4/BUF8 cells need fanout.
# The retained work clock is a gated service clock, not an unrelated clock.
# SRAM falling-edge launch to rising-edge capture gets 25 ns, minus uncertainty,
# macro setup and route delay. Do not add a multicycle/false-path exception.
# CDC exceptions are intentionally NOT broad clock groups or reset false paths.
# The generated endpoint audit must bind only synchronizer first-stage D pins;
# recovery/removal, second stages and bundled data remain checked.
