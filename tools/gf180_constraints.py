# SPDX-License-Identifier: Apache-2.0
"""Bind implementation constraints to the audited synthesized hierarchy.

Clocked STA, async propagation constraints, relative-order checks, and event
monitors are separate outputs. None is allowed to stand in for the other three.
"""
import argparse
import json
from pathlib import Path
from gf180_physical import ROOT, SC, nodes, sha, write_json

def brace(s):
    if any(c in s for c in '{}\r\n'): raise ValueError("UNSAFE_TCL_NAME")
    return '{'+s+'}'

def pin(s): return '[rp '+brace(s)+']'

PRELUDE='''# Exact object binding: an empty selection is always an error.
proc rp {name} {
  set p [get_pins -quiet $name]
  if {[llength $p] != 1} {error "UNRESOLVED_PHYSICAL_PIN $name"}
  return $p
}
proc rbus {name width} {
  if {$width == 1} {
    set p [get_pins -quiet $name]
    if {[llength $p] == 1} {return $p}
  }
  set result {}
  for {set i 0} {$i < $width} {incr i} {lappend result [rp [format {%s[%d]} $name $i]]}
  return $result
}
'''

def hierarchy(modules,top,prefix=""):
    result={prefix:modules[top]}
    for name,c in modules[top].get("cells",{}).items():
        if c["type"] in modules and not c["type"].startswith(SC) and "sram" not in c["type"]:
            result.update(hierarchy(modules,c["type"],prefix+name+"/"))
    return result

def driver(module,net,index=0):
    bits=module["netnames"][net]["bits"]
    bit=bits[index]
    if isinstance(bit,str): return None
    found=[(name,pin) for name,c in module["cells"].items() for pin,conn in c["connections"].items()
        if c["port_directions"][pin]=="output" and bit in conn]
    if len(found)!=1: raise ValueError("AMBIGUOUS_DRIVER_"+net)
    return found[0]

def prepare(mapping):
    record=json.loads((mapping/"mapping.json").read_text())
    audit=json.loads((mapping/"netlist-audit.json").read_text())
    if audit["netlist_sha256"]!=sha(mapping/"netlist.v") or audit["mapping_sha256"]!=sha(mapping/"mapping.json"):
        raise ValueError("STA_INPUT_CHANGED")
    manifest=json.loads((mapping/"timing-intent.json").read_text())["manifest"]
    modules=json.loads((mapping/"netlist.json").read_text())["modules"]
    tree=hierarchy(modules,"RiscayMcuDigital")
    sdc=[PRELUDE,"# Clocked island, bounded async entry points and SRAM half cycles."]
    cdc=[]
    # Select registers by retained RTL net aliases and verify actual DFF drivers.
    def reg_d(path,net,indices=None):
        module=tree[path]; bits=module["netnames"][net]["bits"]
        pins=[]
        for index in range(len(bits)) if indices is None else indices:
            d=driver(module,net,index)
            if d is None: continue
            cell=module["cells"][d[0]]
            if not cell["type"].startswith(SC+"dff"): raise ValueError("CDC_NOT_DFF_"+net)
            pins.append(path+d[0]+"/D")
        if not pins: raise ValueError("EMPTY_CDC_REGISTER_"+net)
        return pins
    for net,indices in (("cpuResetActive_first",None),("watchdogReasonActive_first",None),
        ("gate_demandFirst",None),("fabric_gpio_first",None),("fabric_host_sclSync",[0]),
        ("fabric_host_sdaSync",[0]),("wake_host0",None),("watchdog_sync",[0]),("fabric_ack0",None)):
        pins=reg_d("soc/",net,indices)
        cdc.append(dict(net=net,first_stage_d=pins))
    for path,net in (("soc/ca_child_request_bridge/","request_stages_0"),
                     ("soc/ca_child_response_bridge/","ack_stages_0")):
        cdc.append(dict(net=path+net,first_stage_d=reg_d(path,net)))
    for group in cdc:
        for p in group["first_stage_d"]: sdc.append('set_false_path -to '+pin(p))
    # Gray synchronization has a physical datapath constraint rather than a
    # false path that would silently override that constraint.
    gray_d=reg_d("soc/","gate_first")
    if len(gray_d)!=32: raise ValueError("GRAY_WIDTH_CHANGED")
    gray_q=[]
    for i in range(32):
        d=driver(tree["soc/"],"timebase_gray",i)
        if not d: raise ValueError("GRAY_SOURCE_CONSTANT")
        gray_q.append("soc/"+d[0]+"/"+d[1])
    for q,d in zip(gray_q,gray_d):
        # Conventional STA startpoint is the source register's clock pin.
        # Including clock-to-Q makes this bound more conservative than Q-to-D.
        sdc.append(f'set_max_delay 50 -ignore_clock_latency -from {pin(q.rsplit("/",1)[0]+"/CLK")} -to {pin(d)}')
    # 50 ns is much less than the shortest 83 ms Gray update interval. Matching
    # bits separately keeps ordinary logic out of an unconstrained clock group.
    gate=driver(tree["soc/"],"gate_io_clockOut")
    gatepin="soc/"+gate[0]+"/"+gate[1]
    sdc.append('create_generated_clock -name work -source [get_ports serviceClock] -divide_by 1 '+pin(gatepin))
    sdc.append('set_clock_uncertainty 0.5 [get_clocks work]')
    sdc.append('# START detector clock: 400 kHz interface envelope, falling SDA.')
    sdc.append('create_clock -name i2c_start -period 2500 [get_ports sda]')
    sdc.append('set_clock_transition 2 [get_clocks i2c_start]')
    # Input/output timing here is an explicit digital-boundary budget; final
    # pad/ADC/board timing must replace it at chip integration.
    sdc.append('set_input_delay -clock service -max 10 [get_ports adcMiso]')
    sdc.append('set_input_delay -clock service -min 0 [get_ports adcMiso]')
    sdc.append('set_output_delay -clock service -max 10 [get_ports {adcCsN adcSclk}]')
    (mapping/"clocked.sdc").write_text("\n".join(sdc)+"\n")

    # Binding records use exact synthesized leaf pins. Whole-path source ports
    # are preserved module interfaces; data paths include register-read muxes.
    async_sdc=[PRELUDE]; measurements=[PRELUDE]; cuts=[]; bounds=[]; preserve=[]; monitor=[]
    byinstance={i:b for b in record["bindings"] for i in b["instances"]}
    def leaf(instance,logical,outputs=False):
        b=byinstance[instance]; root=audit["adapter_instances"][instance]
        found=[]
        for c in b["cells"]:
            for port,net in c["pins"].items():
                if (port in ("Z","ZN","Q"))!=outputs: continue
                if net==logical or net.startswith(logical+'['): found.append(root+"/"+c["name"]+"/"+port)
        if not found: raise ValueError("NO_BOUND_LEAF_"+instance+"."+logical)
        return found
    def expr(paths): return '[concat '+" ".join(pin(p) for p in sorted(set(paths)))+']'
    def rule(id,sources,sinks,minimum=None,maximum=None):
        args=' -from '+expr(sources)+' -to '+expr(sinks)
        # Internal path breaks belong ONLY to a separate measurement context;
        # putting them all into clocked STA would truncate unrelated paths.
        bounds.append(dict(id=id,from_pins=sources,to_pins=sinks,minimum_ns=minimum,maximum_ns=maximum))
    for instance,b in byinstance.items():
        root=audit["adapter_instances"][instance]
        preserve += [f'set_dont_touch [get_cells {brace(root+"/"+c["name"])}]' for c in b["cells"]]
        if "AsymmetricC" in b["model"]:
            c=next(c for c in b["cells"] if c["pins"].get("A1")=="state")
            cuts.append(f'set_disable_timing -from A1 -to ZN [get_cells {brace(root+"/"+c["name"])}]')
        req=b["requirements"]
        async_sdc.append('set_max_capacitance 0.05 '+expr(leaf(instance,"q",True)))
        if any(x in b["model"] for x in ("ControlGate","And_v1","Xor_v1","AsymmetricC")):
            sources=[]
            for p in b["ports"]:
                if p["direction"]!="input" or p["name"]=="reset": continue
                used=any(c["pins"].get(k,"").split('[')[0]==p["name"] for c in b["cells"] for k in c["pins"])
                if used: sources += leaf(instance,p["name"])
            rule(instance,sources,leaf(instance,"q",True),req.get("control_min_ns"),req.get("control_max_ns"))
        if any(x in b["model"] for x in ("EventRegister","PhaseRegister","ClosingLatch")):
            for c in b["cells"]:
                if not any(x in c["cell"] for x in ("dffrnq","dffsnq","latrnq")): continue
                latch="latrnq" in c["cell"]
                clock=root+"/"+c["name"]+("/E" if latch else "/CLK")
                rule(instance+".distribution."+c["name"],leaf(instance,"closed" if latch else "trigger"),
                    [clock],maximum=req["clock_distribution_max_ns"])
                monitor.append(dict(instance=instance,clock=clock,data=root+"/"+c["name"]+"/D",
                    reset_n=root+"/"+c["name"]+("/SETN" if "dffsnq" in c["cell"] else "/RN"),
                    edge="fall" if latch else "rise",setup_ns=8 if latch else 5,hold_ns=1,
                    high_ns=1.8,low_ns=2,phase="PhaseRegister" in b["model"]))
    # Expose every source bit in every transform, including all RF read inputs.
    stages=[]
    for n in nodes(manifest["design"]):
        path="soc/"+"/".join(n["rtl_path"].split('.')[1:])
        if path=="soc/": path="soc"
        payload=next((p for p in n["primitives"] if p["id"]=="payload"),None)
        if payload is None: continue
        timing=next((t for t in n["timing"] if t["kind"] in ("long-hold-bundling-v2","click-bundling-v1")),None)
        if timing is None: raise ValueError("UNREGISTERED_STORAGE_TIMING")
        data_budget=(timing["cells"]["data_delay"]["max_fs"] if timing["kind"]=="click-bundling-v1" else timing["data_delay"]["max_fs"])
        ports=tree[path+"/"]["ports"]
        sources=[f'[rbus {brace(path+"/"+p)} {len(v["bits"])}]' for p,v in ports.items() if p.startswith("in_bits_")]
        if not sources: raise ValueError("EMPTY_STAGE_DATA_SOURCE")
        sink=leaf(payload["rtl_path"],"d")
        async_sdc.append(f'set_max_delay {int(data_budget)/1e6} -ignore_clock_latency -from [all_registers -clock_pins] -through [concat '+" ".join(sources)+'] -to '+expr(sink))
        stages.append(dict(path=path,data_budget_ns=int(data_budget)/1e6,source_ports=[p for p in ports if p.startswith("in_bits_")],sink_pins=sink,timing=timing))
        for t in n["timing"]:
            if t["kind"]=="long-hold-fork-v1":
                hold=next(p for p in n["primitives"] if p["id"]=="long_hold")
                source='[rbus '+brace(path+"/out_ack")+' 1]'
                # Separate branch constraints imply strict 0.5 ns ordering.
                # Input bubbles remain inside the preserved C-element.
                early=expr(leaf(hold["rtl_path"],"b")); late=expr(leaf(hold["rtl_path"],"a"))
                async_sdc.append('set_data_check -rise_from '+early+' -fall_to '+late+' -setup 0.5')
                stages[-1]["fork_margin_ns"]=0.5
    measurements.append(MEASURE_HELPER)
    for b in bounds:
        minimum=0 if b["minimum_ns"] is None else b["minimum_ns"]
        maximum="none" if b["maximum_ns"] is None else b["maximum_ns"]
        measurements.append(f'rmeasure {brace(b["id"])} {expr(b["from_pins"])} {expr(b["to_pins"])} {minimum} {maximum}')
    measurements.append('puts {ASYNC_PROPAGATION_CHECKS_COMPLETE}')
    (mapping/"check-async-paths.tcl").write_text("\n".join(measurements)+"\n")
    (mapping/"async.sdc").write_text("\n".join(async_sdc)+"\n")
    (mapping/"feedback-cuts.tcl").write_text('# Analysis cuts ONLY. Never remove or optimize these physical feedback wires.\n'+"\n".join(cuts)+"\n")
    (mapping/"preserve-mapped.tcl").write_text("\n".join(preserve)+"\n")
    write_json(mapping/"constraints-bound.json",dict(status="bound-unqualified",netlist_sha256=sha(mapping/"netlist.v"),
        mapping_sha256=sha(mapping/"mapping.json"),cdc=cdc,gray_sources=gray_q,gray_sinks=gray_d,
        paths=bounds,stages=stages,event_monitors=monitor,
        obligations=["BD fork ordering after extraction","Click feedback high/low pulse inequalities",
            "SDF event/aperture monitors", "reset recovery/removal including source stopping",
            "local clock distribution", "SRAM setup/hold on both edges", "electrical slew/load limits"],
        board_assumptions=dict(i2c_max_hz=400000,adc_input_max_ns=10,adc_output_budget_ns=10)))
    monitors(mapping,monitor)
    print(f'Bound {len(bounds)} paths, {len(stages)} stages, {len(monitor)} capture monitors; qualification pending')

MEASURE_HELPER='''# Run in a fresh, unclocked STA context with feedback-cuts.tcl.
# OpenSTA diagnoses internal path-break endpoints as nonstandard SDC endpoints.
# These are isolated measurements, NOT exceptions for the clocked implementation.
# Every pin is resolved by rp; every measurement must produce a nonempty path.
proc rmeasure {id sources sinks minimum maximum} {
  set_min_delay 0 -from $sources -to $sinks
  set_max_delay 1000000000 -from $sources -to $sinks
  set bounds {}
  foreach mode {min max} {
    set paths [find_timing_paths -from $sources -to $sinks -path_delay $mode -group_path_count 100000 -endpoint_path_count 2]
    if {[llength $paths] == 0} {error "ASYNC_PATH_UNCOVERED $id"}
    set values {}
    foreach path $paths {
      set points [get_property $path points]
      set first [lindex $points 0]; set last [lindex $points end]
      lappend values [expr {[get_property $last arrival]-[get_property $first arrival]}]
    }
    lappend bounds [tcl::mathfunc::$mode {*}$values]
  }
  unset_path_exceptions -from $sources -to $sinks
  lassign $bounds lo hi
  puts "ASYNC_PATH $id $lo $hi"
  if {$lo < $minimum || ($maximum ne "none" && $hi > $maximum)} {error "ASYNC_BOUND_VIOLATION $id $lo $hi"}
}
'''

def monitors(mapping,records):
    # A testbench defines RISCAY_DUT to its instance path and includes this file
    # after SDF annotation. Reference the exact leaf pins, using escaped Verilog
    # identifiers for synthesized/generate-block instance components.
    def verilog(path):
        return '`RISCAY_DUT.'+'.'.join('\\'+part+' ' for part in path.split('/'))
    text='''// Generated SDF event monitors; compile with -g2012 and `RISCAY_DUT defined.
module riscay_capture_check #(parameter real SETUP=5, HOLD=1, HIGH=1.8, LOW=2,
    parameter integer LATCH=0, PHASE=0)(input wire clk,d,rn);
  timeunit 1ns; timeprecision 1ps;
  realtime last_data=0, last_rise=0, last_fall=0, last_capture=0;
  realtime last_release=0;
  bit have_data=0, have_rise=0, have_fall=0, have_capture=0;
  integer captures=0;
  always @(posedge rn) last_release=$realtime;
  always @(negedge rn) begin
    have_data=0; have_rise=0; have_fall=0; have_capture=0;
  end
  always @(d) begin
    if(rn && have_capture && !PHASE && $realtime-last_capture < HOLD)
      $fatal(1,"ASYNC_HOLD %m");
    last_data=$realtime; have_data=1;
  end
  always @(posedge clk) if(rn) begin
    if(have_fall && $realtime-last_fall < LOW) $fatal(1,"ASYNC_LOW_PULSE %m");
    if(!LATCH) begin
      if($realtime-last_release < 8) $fatal(1,"ASYNC_RECOVERY %m");
      if(have_data && !PHASE && $realtime-last_data < SETUP) $fatal(1,"ASYNC_SETUP %m");
      last_capture=$realtime; have_capture=1; captures=captures+1;
    end
    last_rise=$realtime; have_rise=1;
  end
  always @(negedge clk) if(rn) begin
    if(have_rise && $realtime-last_rise < HIGH) $fatal(1,"ASYNC_HIGH_PULSE %m");
    if(LATCH) begin
      if($realtime-last_release < 8) $fatal(1,"ASYNC_RECOVERY %m");
      if(have_data && $realtime-last_data < SETUP) $fatal(1,"ASYNC_LATCH_SETUP %m");
      last_capture=$realtime; have_capture=1; captures=captures+1;
    end
    last_fall=$realtime; have_fall=1;
  end
  final $display("RISCAY_CAPTURE_COVERAGE %m captures=%0d",captures);
endmodule
module riscay_physical_monitors;
'''
    for i,r in enumerate(records):
        text+=f'riscay_capture_check #(.SETUP({r["setup_ns"]}),.HOLD({r["hold_ns"]}),.HIGH({r["high_ns"]}),.LOW({r["low_ns"]}),.LATCH({int(r["edge"]=="fall")}),.PHASE({int(r["phase"])})) m{i} ('
        text+=','.join(verilog(r[k]) for k in ("clock","data","reset_n"))+');\n'
    text+='endmodule\n'
    (mapping/"event-monitors.sv").write_text(text)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("mapping",type=Path); a=p.parse_args(); prepare(a.mapping)
