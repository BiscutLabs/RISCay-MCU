# SPDX-License-Identifier: Apache-2.0
"""Diagnostic extracted async-path probes, separate from clocked STA.

Reports measured violations and missing endpoints. Does not prove protocol,
setup/hold, reset or complete end-to-end relative timing closure.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from gf180_physical import ROOT, SC, SRAM, sha, write_json
from gf180_constraints import brace, PRELUDE
from gf180_estimate import linux
from gf180_pnr import OPENROAD, validate_provenance, rc_inputs, RC_CORNERS
from gf180_netgraph import graph
from gf180_probe_plan import plan

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

PAIR_HELPER=r'''
proc retain_probe_slews {pins} {
  global retained_probe_slews
  sta::find_delays
  foreach source $pins {
    foreach vertex [$source vertices] {
      foreach mode {min max} {foreach rf {rise fall} {
        lappend retained_probe_slews([get_full_name $source]) [list $vertex $mode $rf [$vertex slew_corner $rf [sta::cmd_corner] $mode]]
      }}
    }
  }
}
proc prepare_probe_context {sinks} {
  global retained_probe_slews
  # This fresh STA context measures independent local forward paths. Cut every
  # selected output/capture boundary once; keep the physical connections,
  # extracted loads, keeper cuts and original source slews unchanged.
  set cut_count 0
  foreach sink $sinks {
    foreach edge [get_timing_edges -from $sink] {
      set_disable_timing $edge
      incr cut_count
    }
  }
  set sources {}
  foreach source_name [array names retained_probe_slews] {
    lappend sources [rp $source_name]
    foreach row $retained_probe_slews($source_name) {
      lassign $row vertex mode rf slew
      sta::set_annotated_slew $vertex [sta::cmd_corner] $mode $rf $slew
    }
  }
  if {[llength $sources]} {
    # Per-group set/unset exceptions would invalidate arrivals over the whole
    # design repeatedly. Queries below retain exact group/pair/polarity checks.
    set_min_delay 0 -from $sources -to $sinks
    set_max_delay 1000000000 -from $sources -to $sinks
  }
  puts "LOCAL_PROBE_CONTEXT [llength $sinks] $cut_count [llength $sources]"
}
proc local_probe {id root sinks pairs minimum maximum constant_count} {
  set values {}; set data_values {}; set missing 0; set covered 0
  set sources {}
  foreach pair $pairs {
    lassign $pair source_name sink_name inverted reset_only
    lappend sources [rp $source_name]
  }
  set sources [lsort -unique $sources]
  # One query per source polarity and min/max, retaining all endpoint paths.
  # Validate every expected pair afterwards: batching must not reduce coverage.
  if {[llength $pairs]} {
    foreach from_rf {rise fall} {foreach mode {min max} {
      set paths [find_timing_paths -${from_rf}_from $sources -to $sinks -path_delay $mode -unconstrained -group_path_count 100000 -endpoint_path_count 10000]
      if {[llength $paths]>=100000} {error PROBE_PATH_CAP_EXHAUSTED}
      array unset endpoint_count
      foreach path $paths {
        set points [get_property $path points]; set first [lindex $points 0]; set last [lindex $points end]
        set source_name [get_full_name [get_property $first pin]]
        set sink_name [get_full_name [get_property $last pin]]
        set to_rf [expr {[$last edge] eq "^" ? "rise" : "fall"}]
        if {[$first edge] ne [expr {$from_rf eq "rise" ? "^" : "v"}]} {error PROBE_POLARITY_MISMATCH}
        foreach point $points {if {![string match "$root/*" [get_full_name [get_property $point pin]]]} {error PROBE_ESCAPED_ADAPTER}}
        # OpenSTA caps paths per endpoint vertex, across both polarities.
        set endpoint $sink_name
        if {![info exists endpoint_count($endpoint)]} {set endpoint_count($endpoint) 0}
        incr endpoint_count($endpoint)
        if {$endpoint_count($endpoint)>=10000} {error PROBE_ENDPOINT_CAP_EXHAUSTED}
        set key [list $source_name $sink_name $from_rf $to_rf $mode]
        set delay [expr {[get_property $last arrival]-[get_property $first arrival]}]
        if {[info exists measured($key)]} {set delay [tcl::mathfunc::$mode $delay $measured($key)]}
        set measured($key) $delay
      }
    }}
  }
  foreach pair $pairs {
    lassign $pair source_name sink_name inverted reset_only
    foreach from_rf {rise fall} {
      set to_rf $from_rf
      if {$inverted} {set to_rf [expr {$from_rf eq "rise" ? "fall" : "rise"}]}
      foreach mode {min max} {
        set key [list $source_name $sink_name $from_rf $to_rf $mode]
        if {![info exists measured($key)]} {
          incr missing; puts "PAIR_UNCOVERED $id $source_name $sink_name $from_rf $to_rf $mode"; continue
        }
        set delay $measured($key)
        lappend values $delay
        if {!$reset_only} {lappend data_values $delay}
        incr covered
        puts "LOCAL_PAIR $id $source_name $sink_name $from_rf $to_rf $mode $delay $reset_only"
      }
    }
  }
  set lo -1; set hi -1; set status CONSTANT
  if {[llength $values]} {set lo [tcl::mathfunc::min {*}$values]; set hi [tcl::mathfunc::max {*}$values]; set status RESET_ONLY}
  if {[llength $data_values]} {
    set status PASS
    set dl [tcl::mathfunc::min {*}$data_values]; set dh [tcl::mathfunc::max {*}$data_values]
    if {($minimum ne "none" && $dl<$minimum) || ($maximum ne "none" && $dh>$maximum)} {set status VIOLATION}
  }
  if {$missing} {set status UNCOVERED}
  puts "ROUTED_PROBE $id $status $lo $hi $covered [expr {4*[llength $pairs]}]"
}
'''

def run_suffix(run_tag):
    if run_tag is None:return ''
    if not isinstance(run_tag,str) or re.fullmatch(r'[A-Za-z0-9-]+',run_tag) is None:
        raise ValueError('INVALID_PROBE_RUN_TAG')
    return '-run-'+run_tag


def run(mapping,routed,corner,wire_corner="nom",only_ids=None,run_tag=None):
    tag_suffix=run_suffix(run_tag)
    validate_provenance(mapping,routed,"extract")
    odb,spef=rc_inputs(mapping,routed,wire_corner)
    suffix='-selected-'+hashlib.sha256(json.dumps(sorted(only_ids)).encode()).hexdigest()[:12] if only_ids else ''
    out=routed/("async-"+corner+"-"+wire_corner+suffix+tag_suffix); out.mkdir(exist_ok=False)
    d=json.loads((mapping/"constraints-bound.json").read_text())
    grouped={}
    for row in d["paths"]:
        id=row["id"].split(".distribution.")[0]+".distribution" if ".distribution." in row["id"] else row["id"]
        if id not in grouped: grouped[id]=dict(row,id=id,to_pins=[])
        grouped[id]["to_pins"].extend(row["to_pins"])
    full_count=len(grouped)
    if only_ids:
        if len(set(only_ids))!=len(only_ids) or not set(only_ids).issubset(grouped):raise ValueError('UNKNOWN_OR_DUPLICATE_PROBE_SELECTION')
        grouped={id:grouped[id] for id in only_ids}
    record=json.loads((mapping/'mapping.json').read_text())
    audit=json.loads((mapping/'netlist-audit.json').read_text())
    byinstance={i:b for b in record['bindings'] for i in b['instances']}
    cells,_=graph(json.loads((mapping/'netlist.json').read_text())['modules'])
    plans={id:plan(row,byinstance[id.removesuffix('.distribution')],
                  audit['adapter_instances'][id.removesuffix('.distribution')],cells) for id,row in grouped.items()}
    write_json(out/'probe-plan.json',plans)
    pdk=ROOT/".tools/physical/pdk"; sram=ROOT/".tools/gf180-sram"
    t=f'read_liberty {brace(linux(pdk/(SC+corner+".lib")))}\n'
    t+=f'read_liberty {brace(linux(sram/(SRAM+"__"+corner+".lib")))}\n'
    t+=f'read_db {brace(linux(odb))}\nread_spef {brace(linux(spef))}\n'
    t+=f'source {brace(linux(mapping/"feedback-cuts.tcl"))}\nset_input_transition 2 [all_inputs]\n'
    t+=PRELUDE+PAIR_HELPER
    refs=lambda pins:'[concat '+" ".join('[rp '+brace(p)+']' for p in sorted(set(pins)))+']'
    all_sources={pair['source'] for p in plans.values() for pair in p['pairs']}
    t+='retain_probe_slews '+refs(all_sources)+'\n'
    all_sinks={p for row in grouped.values() for p in row['to_pins']}
    t+='prepare_probe_context '+refs(all_sinks)+'\n'
    for row in grouped.values():
        p=plans[row['id']]
        pairs='[list '+' '.join('[list '+brace(x['source'])+' '+brace(x['sink'])+' '+str(int(x['inverted']))+' '+str(int(x['reset_only']))+']' for x in p['pairs'])+']'
        t+='local_probe '+brace(row["id"])+" "+brace(p['root'])+" "+refs(row["to_pins"])+" "+pairs
        t+=' '+str(row["minimum_ns"] if row["minimum_ns"] is not None else "none")
        t+=' '+str(row["maximum_ns"] if row["maximum_ns"] is not None else "none")+' '+str(len(p['constant_sinks']))+'\n'
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
    counts={s:sum(r["status"]==s for r in rows) for s in ("PASS","VIOLATION","UNCOVERED","CONSTANT","RESET_ONLY")}
    write_json(out/"results.json",dict(status="diagnostic-only",corner=corner,wire_corner=wire_corner,counts=counts,paths=rows,
        selection=only_ids,full_group_count=full_count,run_tag=run_tag,
        measurement_context='all selected boundaries isolated once; original source slews retained',
        odb_sha256=sha(odb),spef_sha256=sha(spef),probe_plan_sha256=sha(out/'probe-plan.json'),
        limits="Internal-path measurements only; no protocol, aperture, reset or end-to-end timing qualification"))
    print(corner,counts,flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("mapping",type=Path); p.add_argument("routed",type=Path)
    p.add_argument("--corner",default="tt_025C_3v30")
    p.add_argument("--wire-corner",choices=RC_CORNERS,default="nom")
    p.add_argument('--only',action='append',help='Exact grouped probe ID; report explicitly remains partial')
    p.add_argument('--run-tag',help='Fresh output suffix: nonempty letters, digits and hyphens only')
    a=p.parse_args(); run(a.mapping.resolve(),a.routed.resolve(),a.corner,a.wire_corner,a.only,a.run_tag)
