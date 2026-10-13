# SPDX-License-Identifier: Apache-2.0
"""Five cell-corner STA and a compact first-P&R report, using nominal route RC."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
from characterize_gf180_liberty import CORNERS
from gf180_physical import ROOT, SC, SRAM, sha, write_json
from gf180_constraints import brace
from gf180_estimate import linux
from gf180_pnr import OPENROAD, validate_provenance

def corner_report(mapping,out,corner):
    validate_provenance(mapping,out,"extract")
    d=out/("sta-"+corner); d.mkdir(exist_ok=False)
    t=f'read_liberty {brace(linux(ROOT/".tools/physical/pdk"/(SC+corner+".lib")))}\n'
    t+=f'read_liberty {brace(linux(ROOT/".tools/gf180-sram"/(SRAM+"__"+corner+".lib")))}\n'
    t+=f'read_db {brace(linux(out/"extract.odb"))}\n'
    for file in (mapping/"base.sdc",mapping/"clocked.sdc",mapping/"feedback-cuts.tcl",out/"async-pnr.sdc"):
        t+='source '+brace(linux(file))+'\n'
    t+='set_propagated_clock [get_clocks {service work lf}]\n'
    t+=f'read_spef {brace(linux(out/"routed.spef"))}\n'
    t+='report_checks -path_delay min_max -group_path_count 5 -format full_clock_expanded\n'
    for group in ("service","work","lf"):
        t+=f'foreach mode {{min max}} {{foreach path [find_timing_paths -path_group {group} -path_delay $mode -group_path_count 1] {{puts "CLOCKED_SLACK {group} $mode [get_property $path slack]"}}}}\n'
    for macro in ("program_macros_0","program_macros_1","ram_macros_0"):
        t+=f'set macro [get_cells soc/fabric_{macro}]\n'
        t+='foreach mode {min max} {\nset paths [find_timing_paths -to [get_pins -of_objects $macro] -path_delay $mode -group_path_count 1]\n'
        t+='if {[llength $paths]==0} {error MISSING_SRAM_TIMING}\n'
        t+=f'foreach path $paths {{puts "SRAM_SLACK {macro} $mode [get_property $path slack]"}}\n}}\n'
    t+='report_check_types -max_slew -max_capacitance -violators\nputs EXTRACTED_STA_COMPLETE\nexit\n'
    (d/"check.tcl").write_text(t)
    with (d/"check.log").open("w") as log:
        r=subprocess.run(["wsl","-d","nixos-librelane","-e",OPENROAD,"-exit",linux(d/"check.tcl")],stdout=log,stderr=subprocess.STDOUT)
    log=(d/"check.log").read_text()
    if r.returncode or "EXTRACTED_STA_COMPLETE" not in log: raise RuntimeError(log[-3000:])
    if re.search(r'STA-(1648|1650)',log): raise ValueError("SPEF_ANNOTATION_INCOMPLETE")
    def entries(prefix): return [dict(group=g,mode=m,slack_ns=float(s)) for g,m,s in re.findall('^'+prefix+r' (\S+) (\S+) (\S+)',log,re.M)]
    slacks=[float(s) for s in re.findall(r'([-\d.]+)\s+slack \(',log)]
    return dict(corner=corner,status="timing-open",worst_reported_slack_ns=min(slacks),
                clocked=entries("CLOCKED_SLACK"),sram=entries("SRAM_SLACK"),log_sha256=sha(d/"check.log"))

def run(mapping,out):
    validate_provenance(mapping,out,"extract")
    with ThreadPoolExecutor(max_workers=3) as pool:
        reports=list(pool.map(lambda c:corner_report(mapping,out,c),CORNERS))
    log=(out/"route.log").read_text()
    wire=re.findall(r'Total wire length = (\d+) um',log)
    area=re.findall(r'Design area ([\d.]+) um\^2',log)
    # Router DRC is a narrower result than foundry-deck DRC, antenna or LVS.
    drc=(out/"route-drc.rpt").read_text()
    violations=len(re.findall(r'^violation type:',drc,re.M))
    if drc.strip() and violations==0: raise ValueError("UNKNOWN_DRC_REPORT_FORMAT")
    report=dict(status="routed-experiment-timing-open",die_area_mm2=1.44**2,
        placed_logic_and_sram_area_mm2=float(area[-1])/1e6,wirelength_um=int(wire[-1]),
        detailed_router_violations=violations,cell_corners=reports,wire_corner="nominal only",
        protected_audit_pass="PROTECTED_AUDIT_PASS" in log,odb_sha256=sha(out/"extract.odb"),spef_sha256=sha(out/"routed.spef"),
        remaining=["reset fanout/slew and reset release", "complete async relative timing and electrical coverage",
                   "extracted event/feedback verification", "min/max wire corners", "fill, antenna, full DRC/LVS", "pads and analog"])
    write_json(out/"results.json",report)
    print(json.dumps({k:v for k,v in report.items() if k!="cell_corners"},indent=2))

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("mapping",type=Path); p.add_argument("output",type=Path)
    a=p.parse_args(); run(a.mapping.resolve(),a.output.resolve())
