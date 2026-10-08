# SPDX-License-Identifier: Apache-2.0
"""Pre-layout OpenSTA characterization of each complete adapter at five PVTs.

No wire parasitics. Schematic C-element evidence must accompany these deliberate
feedback cuts. Report bounds and violations; never turn a failing bound into pass.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
from gf180_physical import ROOT, SC, pdk_verify, sha, write_json
from gf180_estimate import linux

STA="/nix/store/kklj5jbmmhf3cvh4jymwn485ahyzg1mw-opensta/bin/sta"
CORNERS=["tt_025C_3v30","ss_125C_3v00","ss_n40C_3v00","ff_125C_3v60","ff_n40C_3v60"]

def script(mapping,pdk,corner,bindings):
    text=f'read_liberty {linux(pdk/(SC+corner+".lib"))}\n'
    text+='proc bounds {module kind {endpoints {}}} {\n'
    text+='  if {[llength $endpoints] == 0} {set endpoints [all_outputs]}\n'
    text+='  foreach mode {min max} {\n'
    text+='    set paths [find_timing_paths -to $endpoints -path_delay $mode -group_path_count 10000 -endpoint_path_count 2]\n'
    text+='    if {[llength $paths] == 0} {error "NO_PATH $module $kind"}\n'
    text+='    set times {}\n    foreach path $paths {\n'
    text+='      set points [get_property $path points]\n      set last [lindex $points end]\n'
    text+='      set arrival [get_property $last arrival]\n'
    text+='      if {[string match clock_* $kind]} {set arrival [expr {$arrival - [get_property [lindex $points 0] arrival]}]}\n'
    text+='      lappend times $arrival\n    }\n'
    text+='    puts "BOUND $module $kind $mode [tcl::mathfunc::$mode {*}$times]"\n  }\n}\n'
    for b in bindings:
        for slew in (0.02,2.0):
            for load in (0.003,0.05):
                text+=f'read_verilog {linux(mapping/"riscay_gf180_cells.v")}\nlink_design {b["module"]}\n'
                text+=f'set_input_transition {slew} [all_inputs]\nset_load {load} [all_outputs]\nset_case_analysis 0 [get_ports reset*]\n'
                storage=any(x in b["model"] for x in ("EventRegister","PhaseRegister"))
                if storage:
                    text+='create_clock -name capture -period 1000 [get_ports trigger*]\nset_propagated_clock [all_clocks]\n'
                    text+='set_clock_transition '+str(slew)+' [all_clocks]\nset_output_delay 0 -clock capture [all_outputs]\n'
                else:
                    if "AsymmetricC" in b["model"]:
                        keeper=next(c for c in b["cells"] if c["cell"]==SC+"aoi21_1" and c["pins"].get("A1")=="state")
                        text+=f'set_disable_timing -from A1 -to ZN [get_cells {keeper["name"]}]\n'
                    if "ClosingLatch" in b["model"]: text+='set_case_analysis 0 [get_ports closed*]\n'
                    text+='set_min_delay 0 -from [all_inputs] -to [all_outputs]\nset_max_delay 1000000 -from [all_inputs] -to [all_outputs]\n'
                if "ClosingLatch" in b["model"]:
                    text+='set lows {}; set highs {}\n'
                    for c in b["cells"]:
                        if c["cell"]!=SC+"latrnq_1": continue
                        text+=f'foreach edge [get_timing_edges -from [get_pins {c["name"]}/D] -to [get_pins {c["name"]}/Q]] {{\n'
                        text+='foreach transition {rise fall} {lappend lows [get_property $edge delay_min_$transition]; lappend highs [get_property $edge delay_max_$transition]}\n}\n'
                    text+=f'puts "BOUND {b["module"]} s{slew}_c{load} min [tcl::mathfunc::min {{*}}$lows]"\n'
                    text+=f'puts "BOUND {b["module"]} s{slew}_c{load} max [tcl::mathfunc::max {{*}}$highs]"\n'
                else: text+=f'bounds {b["module"]} s{slew}_c{load}\n'
                if "PhaseRegister" in b["model"]:
                    register=next(c["name"] for c in b["cells"] if "dff" in c["cell"])
                    text+=f'set held [find_timing_paths -to [get_pins {register}/D] -path_delay min -group_path_count 2]\n'
                    text+='if {[llength $held]==0} {error {PHASE_FEEDBACK_HOLD_UNCOVERED}}\n'
                    text+='foreach path $held {if {[get_property $path slack]<0} {error {PHASE_FEEDBACK_HOLD_VIOLATION}}}\n'
                    text+=f'puts {{PHASE_FEEDBACK_HOLD_PASS {b["module"]} s{slew}_c{load}}}\n'
                if storage or "ClosingLatch" in b["model"]:
                    clocks=[c["name"]+("/E" if "latrnq" in c["cell"] else "/CLK") for c in b["cells"] if any(x in c["cell"] for x in ("latrnq","dffrnq","dffsnq"))]
                    source="closed*" if "ClosingLatch" in b["model"] else "trigger*"
                    text+=f'set distribution [get_pins {{{" ".join(clocks)}}}]\n'
                    if "ClosingLatch" in b["model"]: text+='unset_case_analysis [get_ports closed*]\n'
                    text+=f'set_max_delay 100000 -from [get_ports {source}] -to $distribution\nset_min_delay 0 -from [get_ports {source}] -to $distribution\n'
                    text+=f'bounds {b["module"]} clock_s{slew}_c{load} $distribution\n'
    return text+'puts {CHARACTERIZATION_COMPLETE}\nexit\n'

def corner_run(mapping,pdk,corner,bindings,out):
    path=out/(corner+".tcl"); path.write_text(script(mapping,pdk,corner,bindings))
    result=subprocess.run(["wsl","-d","nixos-librelane","-e",STA,"-exit",linux(path)],capture_output=True,text=True,timeout=300)
    log=result.stdout+result.stderr; (out/(corner+".log")).write_text(log)
    matches=re.findall(r'^BOUND (\S+) (\S+) (min|max) ([^\s]+)',log,re.M)
    expected=8*sum(2 if any(x in b["model"] for x in ("EventRegister","PhaseRegister","ClosingLatch")) else 1 for b in bindings)
    if result.returncode or "Error:" in log or "CHARACTERIZATION_COMPLETE" not in log or len(matches)!=expected:
        raise ValueError("STA_CHARACTERIZATION_FAILED_"+corner)
    return [dict(corner=corner,module=m,conditions=c,mode=mode,ns=float(v)) for m,c,mode,v in matches]

def run(mapping,pdk,out):
    pdk_verify(pdk); out.mkdir(parents=True,exist_ok=False)
    bindings=json.loads((mapping/"mapping.json").read_text())["bindings"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        measurements=sum(pool.map(lambda c:corner_run(mapping,pdk,c,bindings,out),CORNERS),[])
    summaries=[]
    for b in bindings:
        rows=[r for r in measurements if r["module"]==b["module"] and not r["conditions"].startswith("clock_")]
        lo=min(r["ns"] for r in rows if r["mode"]=="min"); hi=max(r["ns"] for r in rows if r["mode"]=="max")
        req=b["requirements"]
        failures=[]
        if lo<req.get("control_min_ns",0): failures.append("minimum")
        if hi>req.get("control_max_ns",float('inf')): failures.append("maximum")
        clocks=[r["ns"] for r in measurements if r["module"]==b["module"] and r["conditions"].startswith("clock_")]
        if clocks and max(clocks)>req["clock_distribution_max_ns"]: failures.append("clock_distribution")
        if "ClosingLatch" in b["model"] and clocks and hi+max(clocks)>req["control_max_ns"]:
            failures.append("latch_closure_plus_propagation")
        summaries.append(dict(module=b["module"],model=b["model"],minimum_ns=lo,maximum_ns=hi,
            clock_distribution_max_ns=max(clocks) if clocks else None,violations=failures))
    write_json(out/"results.json",dict(status="bounds-pass" if not any(r["violations"] for r in summaries) else "bounds-fail",
        mapping_sha256=sha(mapping/"mapping.json"),corners=CORNERS,adapters=summaries,measurements=measurements,
        limits="Unextracted; no electrical, hazard, setup/hold, pulse or reset closure implied"))
    print(json.dumps(summaries,indent=2))
    if any(r["violations"] for r in summaries): raise ValueError("ADAPTER_TIMING_BOUNDS_FAILED")

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("mapping",type=Path); p.add_argument("output",type=Path)
    p.add_argument("--pdk",type=Path,default=ROOT/".tools/physical/pdk"); a=p.parse_args(); run(a.mapping,a.pdk,a.output)
