# SPDX-License-Identifier: Apache-2.0
"""Actual-arc controls for contract-selected stage widths and constant lanes."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import control_relative_timing as r
from check_control_relative_controls import fault_sdf, verify_runtime


def capture_fault_pin(plan):
    queries=next(c for c in plan["contexts"] if c["id"]=="common")["queries"]
    constants=plan.get("constant_lanes",{})
    return next(q["sink"] for q in queries if q.get("role")=="capture" and
                (not constants or str(q["lane"]) in constants))


def verdict(before, after, plan, fault, arcs):
    field="maximum_input_data_lag_ns" if fault=="short_request" else "ack_after_capture_ns"
    old={(v["lane"],v["phase"]):v[field] for v in before["lanes"]}
    new={(v["lane"],v["phase"]):v[field] for v in after["lanes"]}
    r.require(old.keys()==new.keys(),"STAGE_CONTROL_LANE_SET")
    dynamic={k for k,v in old.items() if v is not None}
    r.require({k for k,v in new.items() if v is not None}==dynamic,"STAGE_CONTROL_STATIC_MASK")
    changed={k for k in dynamic if new[k]<old[k]-1e-6}
    if fault=="late_capture":
        branch=next(c for c in plan["native"]["cells"] if c["path"]==arcs[0]["cell"])
        cap="E" if plan["variant"]=="bd" else "CLK"
        members={c["path"]+"/"+cap for c in plan["native"]["cells"] if c["pins"].get(cap)==branch["pins"]["Z"]}
        lanes={q["lane"] for c in plan["contexts"] if c["id"]=="common" for q in c["queries"] if q.get("role")=="capture" and q["sink"] in members}
        expected={k for k in dynamic if k[0] in lanes}
    else:expected=dynamic
    r.require(changed==expected,"STAGE_CONTROL_FAULT_SCOPE")
    r.require(all(abs(new[k]-old[k])<1e-6 for k in dynamic-expected),"STAGE_CONTROL_OFF_BRANCH_CHANGE")
    # Existing failures are never credited to a mutation. CPU execute already
    # has negative local setup allowance in a few lanes at the nominal corner.
    baseline_negative={k for k in dynamic if old[k]<0}
    newly_negative={k for k in dynamic if old[k]>0 and new[k]<0}
    r.require(bool(newly_negative),"STAGE_CONTROL_NO_NEW_FAILURE")
    if fault!="short_request":
        r.require(not baseline_negative and newly_negative==expected,"STAGE_CONTROL_BASE_OR_BRANCH_FAILED")
        r.require([v["maximum_input_data_lag_ns"] for v in before["lanes"]]==
                  [v["maximum_input_data_lag_ns"] for v in after["lanes"]],"STAGE_CONTROL_SETUP_CHANGED")
    static_members=[]
    if fault=="late_capture":
        static_members=sorted(k for k in expected if str(k[0]) in plan.get("constant_lanes",{}))
        r.require(not plan.get("constant_lanes") or bool(static_members),"STAGE_CONTROL_STATIC_BRANCH_MISSING")
        for a,b in zip(before["lanes"],after["lanes"]):
            k=(a["lane"],a["phase"]);x=a["zero_reuse_hold_margin_ns"];y=b["zero_reuse_hold_margin_ns"]
            if x is None:r.require(y is None,"STAGE_CONTROL_STATIC_HOLD")
            elif k in expected:r.require(x>0 and y<0,"STAGE_CONTROL_DYNAMIC_HOLD_NOT_FAILED")
            else:r.require(y is not None and abs(x-y)<1e-6,"STAGE_CONTROL_OFF_BRANCH_HOLD")
    return dict(fault=fault,status="EXPECTED",baseline_negative=sorted(baseline_negative),
                newly_negative=sorted(newly_negative),changed=sorted(changed),arc_count=len(arcs),static_capture_members=static_members)


def run(baseline, output, indices, faults=("period","short_request","early_ack","late_capture")):
    r.require(not output.exists() and indices and len(indices)<=4 and len(indices)==len(set(indices)),"STAGE_CONTROL_SELECTION")
    r.require(faults and len(faults)==len(set(faults)) and set(faults)<={"period","short_request","early_ack","late_capture"},"STAGE_CONTROL_FAULT_SELECTION")
    receipt=json.loads((baseline/"results.json").read_text());sta=r.tool("sta")
    runtime=verify_runtime(sta,receipt["inputs_sha256"])
    sources=[Path(__file__),Path(__file__).with_name("check_control_relative_controls.py")]
    frozen={str(p.resolve()):r.sha(p) for p in sources}
    def verify():
        for p,h in {**receipt["inputs_sha256"],**frozen}.items():r.require(r.sha(Path(p))==h,"STAGE_CONTROL_INPUT_CHANGED")
        for p,h in receipt["files_sha256"].items():r.require(r.sha(baseline/p)==h,"STAGE_CONTROL_BASE_CHANGED")
    verify();output.mkdir(parents=True);verdicts=[]
    netlist=next(Path(p) for p in receipt["inputs_sha256"] if Path(p).name=="netlist.v")
    for index in indices:
        source=baseline/str(index);plan=json.loads((source/"plan.json").read_text())
        key="tt_025C_3v30-s0.2";saved=json.loads((source/(key+".json")).read_text())
        r.require(saved["case"]["failure"] is None,"STAGE_CONTROL_UNRESOLVED_BASE")
        sub=output/str(index);sub.mkdir()
        for fault in faults:
            results=deepcopy(saved["results"]);arcs=[]
            if fault!="period":
                sdf,arcs=fault_sdf(plan,fault,capture_fault_pin(plan) if fault=="late_capture" else None)
                (sub/(fault+".sdf")).write_text(sdf,newline="\n")
            for ctx in plan["contexts"]:
                relevant=ctx["kind"]=="request" if fault=="short_request" else ctx["source_kind"]=="clock"
                if not relevant:continue
                tcl=sub/(fault+"-"+ctx["id"]+".tcl");log=tcl.with_suffix(".log")
                text=r.script(netlist,r.CORNERS[0],.2,plan,ctx,2000 if fault=="period" else 1000,path=sta.path)
                if fault!="period":text=text.replace('row RELATIVE_BEGIN',f'read_sdf {r.brace(sta.path(sub/(fault+".sdf")))}\nrow RELATIVE_BEGIN')
                tcl.write_text(text,newline="\n")
                with log.open("w") as stream:
                    subprocess.run(sta.command(["-no_init","-exit",sta.path(tcl)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
                results[ctx["id"]]=r.parse(log.read_text(),plan,ctx)
            summary=r.margins(results,plan,saved["aperture"])
            if fault=="period":
                r.require(results==saved["results"] and summary==saved["summary"],"STAGE_CONTROL_PERIOD_DEPENDENCE")
                checked=dict(fault=fault,status="IDENTICAL")
            else:checked=verdict(saved["summary"],summary,plan,fault,arcs)
            r.write_json(sub/(fault+".json"),dict(verdict=checked,summary=summary,results=results,arcs=arcs))
            verdicts.append(dict(index=index,instance=plan["descriptor"]["instance"],**checked))
            print(json.dumps({k:len(v) if isinstance(v,list) else v for k,v in verdicts[-1].items()}),flush=True)
    verify()
    r.write_json(output/"controls.json",dict(status="PASS",physical_qualification=False,verdicts=verdicts,
        baseline_sha256=r.sha(baseline/"results.json"),runtime_sha256=runtime,sources_sha256=frozen,
        files_sha256={str(p.relative_to(output)).replace("\\","/"):r.sha(p) for p in output.rglob("*") if p.is_file()}))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("baseline",type=Path);p.add_argument("output",type=Path)
    p.add_argument("--index",type=int,action="append",required=True)
    p.add_argument("--fault",choices=("period","short_request","early_ack","late_capture"),action="append")
    a=p.parse_args();run(a.baseline,a.output,a.index,a.fault or ("period","short_request","early_ack","late_capture"))
