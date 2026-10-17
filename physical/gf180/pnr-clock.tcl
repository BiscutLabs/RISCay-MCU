# SPDX-License-Identifier: Apache-2.0
# Audit real periodic sinks before/after automatic discovery. The external SDA
# event remains timed by SDC but is explicitly excluded from CTS construction.
proc periodic_clock_inventory {filename} {
  global sram_cell
  set names {}; foreach clock [all_clocks] {lappend names [get_full_name $clock]}
  if {[lsort $names] ne {i2c_start lf service work}} {error CTS_CLOCK_INVENTORY}
  set roots [dict create]
  foreach name {service work lf i2c_start} {
    set clock [get_clocks $name]; set pins [$clock sources]
    if {[llength $pins]!=1} {error "CTS_ROOT_COUNT $name"}
    set pin [lindex $pins 0]; set full [get_full_name $pin]
    if {$name eq "work"} {
      if {![$clock is_generated]} {error CTS_WORK_NOT_GENERATED}
      set slash [string last / $full]
      set inst [[ord::get_db_block] findInst [string range $full 0 [expr {$slash-1}]]]
      if {$inst eq "NULL"} {error CTS_WORK_ROOT_MISSING}
      set net [[[$inst findITerm [string range $full [expr {$slash+1}] end]] getNet] getName]
      if {$net ne "soc/gate_io_clockOut"} {error CTS_WORK_ROOT_CHANGED}
    } else {
      set expected [dict get {service serviceClock lf watchdogClock i2c_start sda} $name]
      if {$full ne $expected || [$clock is_generated]} {error "CTS_ROOT_CHANGED $name"}
    }
    dict set roots $name $full
  }
  set f [open $filename w]
  dict for {name pin} $roots {puts $f "R\t$name\t$pin"}
  # Serialize the actual clock objects, rather than trusting only the SDC input
  # or is_generated flag. The checker requires the exact service->work relation.
  sta::update_generated_clks
  write_sdc -no_timestamp ${filename}.sdc
  set sdc [open ${filename}.sdc r]; set body [read $sdc]; close $sdc
  foreach line [split $body \n] {
    if {[string match "create_generated_clock *" $line]} {puts $f "G\t$line"}
  }
  foreach name {service work lf i2c_start} {
    set clock [get_clocks $name]
    puts $f "W\t$name\t[$clock period]\t[join [$clock waveform] ,]"
  }
  foreach name {service work lf i2c_start} {
    foreach edge {rise fall} {
      foreach pin [all_registers -${edge}_clock [get_clocks $name] -clock_pins] {
        puts $f "P\t$name\t$edge\t[get_full_name $pin]"
      }
    }
  }
  # Macro clock pins are not necessarily enumerated as standard registers.
  set macros 0
  foreach inst [[ord::get_db_block] getInsts] {
    if {[[$inst getMaster] getName] ne $sram_cell} {continue}
    incr macros
    puts $f "M\twork\trise\t[$inst getName]/CLK"
  }
  if {$macros!=3} {error CTS_SRAM_INVENTORY}
  close $f
}
