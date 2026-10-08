# SPDX-License-Identifier: Apache-2.0
# OpenROAD, after LEFs and netlist load. These are real standard-cell/SRAM LEF
# pins, not added logic ports. Supply and well ties must survive DEF export.
add_global_connection -net VDD -inst_pattern {.*} -pin_pattern {^(VDD|VNW)$} -power
add_global_connection -net VSS -inst_pattern {.*} -pin_pattern {^(VSS|VPW)$} -ground
global_connect
# Analog macros/pad ring are not part of RiscayMcuDigital. Their separately
# qualified power/well pins must be connected when the chip shell is assembled.
