# SPDX-License-Identifier: Apache-2.0
"""Run clocked/macro STA preflight at matching standard-cell/SRAM corners.

A successful invocation means the constraints resolve and STA ran. Negative
slack remains an explicit timing-open result, never a physical qualification.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
from characterize_gf180_liberty import CORNERS, STA
from gf180_constraints import prepare
from gf180_estimate import linux
from gf180_physical import ROOT, SC, SRAM, sha, pdk_verify, write_json

def run_corner(mapping,pdk,corner,out):
    text=f'read_liberty {linux(pdk/(SC+corner+".lib"))}\n'
    text+=f'read_liberty {linux(ROOT/".tools/gf180-sram"/(SRAM+"__"+corner+".lib"))}\n'
    text+=f'read_verilog {linux(mapping/"netlist.v")}\nlink_design RiscayMcuDigital\n'
    for file in ("base.sdc","clocked.sdc","feedback-cuts.tcl","async.sdc"):
        text+=f'source {linux(mapping/file)}\n'
    text+='puts {CONSTRAINT_BINDING_PASS}\n'
    text+='report_checks -path_delay min_max -group_path_count 5 -format full_clock_expanded\n'
    bound=json.loads((mapping/"constraints-bound.json").read_text())
    for stage in bound["stages"]:
        names=" ".join(stage["sink_pins"])
        text+=f'set stagepaths [find_timing_paths -to [get_pins {{{names}}}] -path_delay max -group_path_count 1]\n'
        text+='if {[llength $stagepaths]==0} {error {STAGE_TIMING_UNCOVERED}}\n'
        text+=f'foreach path $stagepaths {{puts "STAGE_TIMING {stage["path"]} [get_property $path slack]"}}\n'
    # SRAM input setup/hold are ordinary half-cycle paths, with all three
    # physical macros present. Reporting separately prevents other violations
    # from obscuring a macro interface problem.
    for name in ("program_macros_0","program_macros_1","ram_macros_0"):
        text+=f'set macro [get_cells soc/fabric_{name}]\n'
        text+='if {[llength $macro]!=1} {error {MISSING_SRAM_MACRO}}\n'
        text+='report_checks -to [get_pins -of_objects $macro] -path_delay min_max -group_path_count 2\n'
    text+='report_check_types -max_slew -max_capacitance -violators\nputs {CLOCKED_STA_COMPLETE}\nexit\n'
    script=out/(corner+".tcl"); script.write_text(text)
    result=subprocess.run(["wsl","-d","nixos-librelane","-e",STA,"-exit",linux(script)],capture_output=True,text=True,timeout=120)
    log=result.stdout+result.stderr; (out/(corner+".log")).write_text(log)
    if result.returncode or "Error:" in log or "Warning:" in log or "CLOCKED_STA_COMPLETE" not in log:
        raise ValueError("STA_PREFLIGHT_FAILED_"+corner)
    slacks=[float(x) for x in re.findall(r'([-+\d.]+)\s+slack \(',log)]
    if not slacks: raise ValueError("NO_CLOCKED_TIMING_ACTIVITY")
    return dict(corner=corner,worst_reported_slack_ns=min(slacks),reported_paths=len(slacks),
        stages={name:float(value) for name,value in re.findall(r'^STAGE_TIMING (\S+) (\S+)',log,re.M)},
        log_sha256=sha(out/(corner+".log")),status="timing-open" if min(slacks)<0 else "reported-paths-pass")

def run(mapping,pdk,out):
    pdk_verify(pdk); prepare(mapping); out.mkdir(parents=True,exist_ok=False)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda c:run_corner(mapping,pdk,c,out),CORNERS))
    write_json(out/"results.json",dict(status="constraints-validated-timing-unqualified",corners=results,
        netlist_sha256=sha(mapping/"netlist.v"),
        limits="No placement, CTS, wire parasitics, reset/CDC waivers or async signoff; inspect every violation"))
    print(f'PASS constraint binding and clocked/SRAM STA at {len(results)} corners; timing unqualified')

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("mapping",type=Path); p.add_argument("output",type=Path)
    p.add_argument("--pdk",type=Path,default=ROOT/".tools/physical/pdk"); a=p.parse_args(); run(a.mapping,a.pdk,a.output)
