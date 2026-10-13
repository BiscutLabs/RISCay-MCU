# SPDX-License-Identifier: Apache-2.0
"""Diagnostic extracted async-path probes, separate from clocked STA.

Reports measured violations and missing endpoints. Does not prove protocol,
setup/hold, reset or complete end-to-end relative timing closure.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
from gf180_physical import ROOT, SC, SRAM, sha, write_json
from gf180_constraints import brace, PRELUDE
from gf180_estimate import linux
from gf180_pnr import OPENROAD, validate_provenance

HELPER=r'''
proc probe {id sources sinks minimum maximum} {
  set_min_delay 0 -from $sources -to $sinks
  set_max_delay 1000000000 -from $sources -to $sinks
  set bounds {}; set covered {}
  foreach mode {min max} {
    set paths [find_timing_paths -from $sources -to $sinks -path_delay $mode -group_path_count 100000 -endpoint_path_count 2]
    set values {}
    foreach path $paths {
      set points [get_property $path points]
      set first [lindex $points 0]; set last [lindex $points end]
      lappend values [expr {[get_property $last arrival]-[get_property $first arrival]}]
      if {$mode eq "max"} {lappend covered [get_full_name [get_property $last pin]]}
    }
    lappend bounds [expr {[llength $values] ? [tcl::mathfunc::$mode {*}$values] : -1}]
  }
  unset_path_exceptions -from $sources -to $sinks
  lassign $bounds lo hi
  set count [llength [lsort -unique $covered]]
  set status PASS
  if {$lo<0 || $hi<0 || $count!=[llength $sinks]} {set status UNCOVERED}
  if {$status eq "PASS" && (($minimum ne "none" && $lo<$minimum) || ($maximum ne "none" && $hi>$maximum))} {set status VIOLATION}
  puts "ROUTED_PROBE $id $status $lo $hi $count [llength $sinks]"
}
'''

def run(mapping,routed,corner):
    validate_provenance(mapping,routed,"extract")
    out=routed/("async-"+corner); out.mkdir(exist_ok=False)
    d=json.loads((mapping/"constraints-bound.json").read_text())
    grouped={}
    for row in d["paths"]:
        id=row["id"].split(".distribution.")[0]+".distribution" if ".distribution." in row["id"] else row["id"]
        if id not in grouped: grouped[id]=dict(row,id=id,to_pins=[])
        grouped[id]["to_pins"].extend(row["to_pins"])
    pdk=ROOT/".tools/physical/pdk"; sram=ROOT/".tools/gf180-sram"
    t=f'read_liberty {brace(linux(pdk/(SC+corner+".lib")))}\n'
    t+=f'read_liberty {brace(linux(sram/(SRAM+"__"+corner+".lib")))}\n'
    t+=f'read_db {brace(linux(routed/"extract.odb"))}\nread_spef {brace(linux(routed/"routed.spef"))}\n'
    t+=f'source {brace(linux(mapping/"feedback-cuts.tcl"))}\nset_input_transition 2 [all_inputs]\n'
    t+=PRELUDE+HELPER
    for row in grouped.values():
        refs=lambda pins:'[concat '+" ".join('[rp '+brace(p)+']' for p in sorted(set(pins)))+']'
        t+='probe '+brace(row["id"])+" "+refs(row["from_pins"])+" "+refs(row["to_pins"])
        t+=' '+str(row["minimum_ns"] if row["minimum_ns"] is not None else "none")
        t+=' '+str(row["maximum_ns"] if row["maximum_ns"] is not None else "none")+'\n'
    t+='puts ROUTED_PROBES_COMPLETE\nexit\n'
    (out/"check.tcl").write_text(t)
    with (out/"check.log").open("w") as log:
        result=subprocess.run(["wsl","-d","nixos-librelane","-e",OPENROAD,"-exit",linux(out/"check.tcl")],stdout=log,stderr=subprocess.STDOUT)
    log=(out/"check.log").read_text()
    if result.returncode or "ROUTED_PROBES_COMPLETE" not in log: raise RuntimeError(log[-3000:])
    if re.search(r'STA-(1648|1650)',log): raise ValueError("SPEF_ANNOTATION_INCOMPLETE")
    rows=[]
    for id,status,lo,hi,covered,total in re.findall(r'^ROUTED_PROBE (\S+) (\S+) (\S+) (\S+) (\d+) (\d+)',log,re.M):
        rows.append(dict(id=id,status=status,min_ns=float(lo),max_ns=float(hi),covered=int(covered),total=int(total)))
    if len(rows)!=len(grouped): raise ValueError("MISSING_ROUTED_PROBES")
    counts={s:sum(r["status"]==s for r in rows) for s in ("PASS","VIOLATION","UNCOVERED")}
    write_json(out/"results.json",dict(status="diagnostic-only",corner=corner,wire_corner="nominal",counts=counts,paths=rows,
        odb_sha256=sha(routed/"extract.odb"),spef_sha256=sha(routed/"routed.spef"),
        limits="Internal-path measurements only; no protocol, aperture, reset or end-to-end timing qualification"))
    print(corner,counts,flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("mapping",type=Path); p.add_argument("routed",type=Path)
    p.add_argument("--corner",default="tt_025C_3v30"); a=p.parse_args(); run(a.mapping.resolve(),a.routed.resolve(),a.corner)
