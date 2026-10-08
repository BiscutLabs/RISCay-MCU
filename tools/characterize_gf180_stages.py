# SPDX-License-Identifier: Apache-2.0
"""Measure whole transforms in isolated stage contexts (including RF read muxes).

An async latch network cannot be treated as a periodic pipeline for this check.
Stage input ports are explicit measurement startpoints; payload D pins terminate
the combinational path. Routed qualification must include inter-stage wiring.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
from characterize_gf180_liberty import CORNERS, STA
from gf180_constraints import hierarchy
from gf180_estimate import linux
from gf180_physical import ROOT, SC, pdk_verify, write_json, sha

def run(mapping,pdk,out):
    pdk_verify(pdk); out.mkdir(parents=True,exist_ok=False)
    bound=json.loads((mapping/"constraints-bound.json").read_text())
    modules=json.loads((mapping/"netlist.json").read_text())["modules"]
    tree=hierarchy(modules,"RiscayMcuDigital")
    def one(corner):
        t=f'read_liberty {linux(pdk/(SC+corner+".lib"))}\n'
        for s in bound["stages"]:
            # Equality uses the actual module dictionary, after firtool/Yosys
            # deduplication. Do not assume a pre-elaboration module name.
            module=next(k for k,v in modules.items() if v is tree[s["path"]+"/"])
            t+=f'read_verilog {linux(mapping/"netlist.v")}\nlink_design {module}\n'
            t+='set_case_analysis 0 [get_ports reset]\nset_input_transition 2 [all_inputs]\nset_load 0.05 [all_outputs]\n'
            prefix=s["path"]+'/'
            sinks=[p.removeprefix(prefix) for p in s["sink_pins"]]
            t+=f'set sinks [get_pins {{{" ".join(sinks)}}}]\n'
            t+=f'if {{[llength $sinks]!={len(sinks)}}} {{error {{STAGE_PIN_MISSING}}}}\n'
            t+='set starts [get_ports {in_bits_*}]\n'
            t+='set_max_delay 1000000 -from $starts -to $sinks\n'
            t+='set paths [find_timing_paths -from $starts -to $sinks -path_delay max -group_path_count 1]\n'
            t+='if {[llength $paths]==0} {error {STAGE_PATH_UNCOVERED}}\n'
            t+='foreach path $paths {set p [get_property $path points]; set delay [expr {[get_property [lindex $p end] arrival]-[get_property [lindex $p 0] arrival]}]; '
            t+=f'puts "DATA_PATH {s["path"]} $delay"}}\n'
            t+='report_checks -from $starts -to $sinks -path_delay max -group_path_count 1\n'
        t+='puts {STAGE_CHARACTERIZATION_COMPLETE}\nexit\n'
        f=out/(corner+".tcl"); f.write_text(t)
        r=subprocess.run(["wsl","-d","nixos-librelane","-e",STA,"-exit",linux(f)],capture_output=True,text=True,timeout=120)
        log=r.stdout+r.stderr; (out/(corner+".log")).write_text(log)
        values={path:float(value) for path,value in re.findall(r'^DATA_PATH (\S+) (\S+)',log,re.M)}
        if r.returncode or 'Error:' in log or 'STAGE_CHARACTERIZATION_COMPLETE' not in log or len(values)!=len(bound["stages"]):
            raise ValueError("STAGE_CHARACTERIZATION_FAILED_"+corner)
        return dict(corner=corner,paths=values)
    with ThreadPoolExecutor(max_workers=3) as pool: results=list(pool.map(one,CORNERS))
    stages=[dict(path=s["path"],budget_ns=s["data_budget_ns"],max_ns=max(r["paths"][s["path"]] for r in results)) for s in bound["stages"]]
    write_json(out/"results.json",dict(status="pass" if all(s["max_ns"]<=s["budget_ns"] for s in stages) else "data-budget-fail",
        netlist_sha256=sha(mapping/"netlist.v"),stages=stages,corners=results,limits="No inter-stage routed wire delay or reset/CDC signoff"))
    print(json.dumps(stages,indent=2))
    if any(s["max_ns"]>s["budget_ns"] for s in stages): raise ValueError("STAGE_DATA_BUDGET_FAILED")

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("mapping",type=Path); p.add_argument("output",type=Path)
    p.add_argument("--pdk",type=Path,default=ROOT/".tools/physical/pdk"); a=p.parse_args(); run(a.mapping,a.pdk,a.output)
