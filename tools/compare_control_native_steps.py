# SPDX-License-Identifier: Apache-2.0
"""Fail closed on native-control timestep sensitivity; no timing qualification."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
from gf180_physical import sha,write_json
from repair_gf180_control import require


def compare(coarse,fine,tolerance_ns=.05):
    require(0<tolerance_ns<=.05,"NATIVE_STEP_TOLERANCE")
    require(coarse["source_sha256"]==fine["source_sha256"],"NATIVE_STEP_SOURCE_MISMATCH")
    require(isinstance(coarse.get("tool_sha256"),str) and coarse["tool_sha256"] and
            coarse["tool_sha256"]==fine.get("tool_sha256"),"NATIVE_STEP_TOOL_MISMATCH")
    require(coarse.get("plan_sha256") and coarse["plan_sha256"]==fine.get("plan_sha256"),"NATIVE_STEP_PLAN_MISMATCH")
    a={c["name"]:c for c in coarse["cases"]};b={c["name"]:c for c in fine["cases"]}
    require(a.keys()==b.keys() and len(a)==len(coarse["cases"]) and len(b)==len(fine["cases"]) and a,"NATIVE_STEP_CASES")
    rows=[];issues=[];below_resolution=[]
    for name,c in a.items():
        f=b[name]
        require(c["corner"]==f["corner"] and c["ramp_ns"]==f["ramp_ns"] and c["order"]==f["order"] and
                c["fault"]==f["fault"] and (f.get("mesh_step_ns") or f["maximum_step_ns"])<=
                (c.get("mesh_step_ns") or c["maximum_step_ns"])/2,"NATIVE_STEP_CONDITIONS")
        require(c["events"].keys()==f["events"].keys(),"NATIVE_STEP_NODES")
        deltas=[]
        for node,events in c["events"].items():
            fe=f["events"][node]
            if [e for _,e in events]!=[e for _,e in fe]:
                issues.append(dict(id="NATIVE_STEP_EDGE_HISTORY",case=name,node=node));continue
            for (t,_),(ft,_) in zip(events,fe):
                require(math.isfinite(t) and math.isfinite(ft),"NATIVE_STEP_NONFINITE")
                delta=abs(t-ft);deltas.append(delta)
                if delta>tolerance_ns:issues.append(dict(id="NATIVE_STEP_EDGE_TIME",case=name,node=node,delta_ns=delta))
        if any(i["id"]=="NATIVE_EDGE_UNRESOLVED" for i in c["issues"]+f["issues"]):
            issues.append(dict(id="NATIVE_STEP_UNRESOLVED_INPUT",case=name))
        identities=lambda case:Counter(json.dumps({k:i[k] for k in
            ("id","node","lane","transaction","sample","signal","window_ns","threshold") if k in i},sort_keys=True) for i in case["issues"])
        if identities(c)!=identities(f):
            issues.append(dict(id="NATIVE_STEP_VERDICT",case=name))
        def numeric(value,prefix=""):
            if isinstance(value,dict):return {k:v for n,x in value.items() for k,v in numeric(x,prefix+"/"+n).items()}
            if isinstance(value,list):return {k:v for i,x in enumerate(value) for k,v in numeric(x,prefix+"/"+str(i)).items()}
            return {prefix:value} if isinstance(value,(int,float)) else {}
        cm,fm=numeric(c["metrics"]),numeric(f["metrics"])
        require(cm.keys()==fm.keys(),"NATIVE_STEP_METRICS")
        for key,value in cm.items():
            require(math.isfinite(value) and math.isfinite(fm[key]),"NATIVE_STEP_NONFINITE")
            if abs(value-fm[key])>tolerance_ns:issues.append(dict(id="NATIVE_STEP_DERIVED_METRIC",case=name,metric=key,delta_ns=abs(value-fm[key])))
            if any(x in key for x in ("pulse_ns","clock_to_q_ns","capture_spread_ns","after_last_capture_ns")) and min(abs(value),abs(fm[key]))<2*tolerance_ns:
                below_resolution.append(dict(case=name,metric=key,declared_resolution_ns=2*tolerance_ns))
        # Edges alone don't bound slew; compare every same node/direction edge.
        require(len(c["slews"])==len(f["slews"]),"NATIVE_STEP_SLEW_COUNT")
        sd=[]
        ordered=lambda rows:sorted(rows,key=lambda x:(x["node"],x["edge"],x["time_ns"]))
        for x,y in zip(ordered(c["slews"]),ordered(f["slews"])):
            require((x["node"],x["edge"])==(y["node"],y["edge"]),"NATIVE_STEP_SLEW_BINDING")
            require(math.isfinite(x["slew_ns"]) and math.isfinite(y["slew_ns"]),"NATIVE_STEP_NONFINITE")
            delta=abs(x["slew_ns"]-y["slew_ns"]);sd.append(delta)
            if delta>tolerance_ns:issues.append(dict(id="NATIVE_STEP_SLEW",case=name,node=x["node"],delta_ns=delta))
        rows.append(dict(case=name,maximum_edge_delta_ns=max(deltas,default=0),maximum_slew_delta_ns=max(sd,default=0)))
    return dict(status="step-sensitive" if issues else "step-comparison-pass",tolerance_ns=tolerance_ns,
                cases=rows,issues=issues,subresolution_metrics=below_resolution,physical_qualification=False,
                limits="Only the paired stimuli/corners are compared; smaller steps, different corners, extracted RC and complete setup/hold remain separate gates.")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("coarse",type=Path);p.add_argument("fine",type=Path);p.add_argument("output",type=Path)
    a=p.parse_args();require(not a.output.exists(),"NATIVE_STEP_OUTPUT_EXISTS")
    r=compare(json.loads(a.coarse.read_text()),json.loads(a.fine.read_text()))
    r["inputs_sha256"]={str(x.resolve()):sha(x) for x in (a.coarse,a.fine)}
    write_json(a.output,r);print(r["status"],r["cases"])
    if r["issues"]:raise SystemExit(1)
