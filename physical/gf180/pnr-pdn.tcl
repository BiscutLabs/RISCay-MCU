# SPDX-License-Identifier: Apache-2.0
# Single 3.3 V domain; exploratory geometry, no IR-drop qualification.
set_voltage_domain -name CORE -power VDD -ground VSS
define_pdn_grid -name core -voltage_domains CORE -pins {Metal5} -starts_with POWER
add_pdn_ring -grid core -layers {Metal4 Metal5} -widths 2 -spacings 2 -core_offsets 6
add_pdn_stripe -grid core -layer Metal1 -width 0.6 -followpins -extend_to_core_ring
add_pdn_stripe -grid core -layer Metal4 -width 2 -pitch 100 -offset 16 -spacing 2 -extend_to_core_ring
add_pdn_stripe -grid core -layer Metal5 -width 2 -pitch 100 -offset 16 -spacing 2 -extend_to_core_ring
add_pdn_connect -grid core -layers {Metal1 Metal4}
add_pdn_connect -grid core -layers {Metal4 Metal5}
define_pdn_grid -macro -name memories -cells $sram_cell -halo 12 -grid_over_pg_pins
add_pdn_stripe -grid memories -layer Metal4 -width 2 -pitch 30 -offset 5 -spacing 2
add_pdn_connect -grid memories -layers {Metal3 Metal4}
add_pdn_connect -grid memories -layers {Metal4 Metal5}
