# SPDX-License-Identifier: Apache-2.0
"""Actual mapped-arc negative controls and event-period invariance for the pilot."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import control_relative_timing as r


def fault_sdf(plan, fault, capture=None):
    cells=plan["native"]["cells"]
    prefix=plan['native'].get('physical_prefix','')
    if fault=="short_request":
        selected=[c for c in cells if c["path"].startswith(prefix+"ca_primitive_request_delay/") and c["cell"]==r.SC+"dlyd_1"]
        value=0.000001
    elif fault=="early_ack":
        roots=("ca_primitive_acknowledge/",) if plan["variant"]=="bd" else ("ca_primitive_acknowledge_guard/","ca_primitive_input_phase/")
        roots=tuple(prefix+p for p in roots)
        selected=[c for c in cells if c["path"].startswith(roots)]
        value=0.000001
    else:
        r.require(fault=="late_capture","RELATIVE_CONTROL_FAULT")
        # Delay the branch that drives lane zero's actual E/CLK, including its
        # other 15 payload pins. No payload or protocol pin is rewired.
        cap=capture or next(c for c in plan["contexts"] if c["id"]=="common")["queries"][0]["sink"]
        storage,pin=cap.rsplit("/",1)
        node=next(c for c in cells if c["path"]==storage)["pins"][pin]
        selected=[c for c in cells if c["pins"].get("Z")==node]
        r.require(len(selected)==1 and selected[0]["cell"]==r.SC+"buf_4","RELATIVE_CAPTURE_BRANCH")
        value=1000
    r.require(bool(selected),"RELATIVE_CONTROL_EMPTY")
    rows=[];arcs=[]
    for c in selected:
        output=next(p for p in ("Z","ZN","Q") if p in c["pins"])
        inputs=["CLK"] if output=="Q" else [p for p in c["pins"] if p!=output]
        paths=[]
        for p in inputs:
            # Do not annotate storage RN-to-Q arcs. Reset stays inactive;
            # phase-owner reset buffers can be included but cannot cause ACK.
            if p=="RN":continue
            number=f"{value:.6f}"
            paths.append(f'(IOPATH {p} {output} ({number}:{number}:{number}) ({number}:{number}:{number}))')
            arcs.append(dict(cell=c["path"],source=p,sink=output,delay_ns=value))
        instance=c["path"].replace(".","\\.")
        rows.append(f'(CELL (CELLTYPE "{c["cell"]}") (INSTANCE {instance}) (DELAY (ABSOLUTE '+" ".join(paths)+')))')
    return '(DELAYFILE (SDFVERSION "3.0") (DESIGN "'+plan["module"]+'") (DIVIDER /) (TIMESCALE 1ns)\n'+"\n".join(rows)+')\n',arcs


def verify_runtime(sta, inputs):
    selected={str(p.resolve()):r.sha(p) for p in sta.input_files()}
    r.require(all(inputs.get(p)==h for p,h in selected.items()),"RELATIVE_CONTROL_RUNTIME_CHANGED")
    return selected


def run(baseline, netlist, output):
    r.require(not output.exists(),"RELATIVE_CONTROL_OUTPUT_EXISTS")
    source_hash=r.sha(Path(__file__))
    sta=r.tool("sta")
    receipt=json.loads((baseline/"results.json").read_text())
    runtime=verify_runtime(sta,receipt["inputs_sha256"])
    for f,h in receipt["files_sha256"].items():r.require(r.sha(baseline/f)==h,"RELATIVE_CONTROL_STALE_BASE")
    # A final control run must use the same source implementation as its pilot.
    for f,h in receipt["inputs_sha256"].items():r.require(r.sha(Path(f))==h,"RELATIVE_CONTROL_STALE_SOURCE")
    plan=json.loads((baseline/"plan.json").read_text())["plan"]
    case=next(c for c in receipt["cases"] if c["corner"]==r.CORNERS[0])
    key=case["key"]; saved=json.loads((baseline/(key+".json")).read_text())
    r.require(str(netlist.resolve()) in receipt["inputs_sha256"],"RELATIVE_CONTROL_NETLIST")
    output.mkdir(parents=True); verdicts=[]
    for fault in ("period","short_request","early_ack","late_capture"):
        results=deepcopy(saved["results"]);arcs=[]
        if fault!="period":
            sdf,arcs=fault_sdf(plan,fault);(output/(fault+".sdf")).write_text(sdf,newline="\n")
        for ctx in plan["contexts"]:
            relevant=(ctx["source_kind"]=="clock" if fault=="period" else
                      ctx["kind"]=="request" if fault=="short_request" else
                      ctx["source_kind"]=="clock")
            if not relevant:continue
            tcl=output/(fault+"-"+ctx["id"]+".tcl");log=tcl.with_suffix(".log")
            text=r.script(netlist,case["corner"],case["slew_ns"],plan,ctx,2000 if fault=="period" else 1000,path=sta.path)
            if fault!="period":text=text.replace('row RELATIVE_BEGIN',f'read_sdf {r.brace(sta.path(output/(fault+".sdf")))}\nrow RELATIVE_BEGIN')
            tcl.write_text(text,newline="\n")
            with log.open("w") as stream:
                subprocess.run(sta.command(["-no_init","-exit",sta.path(tcl)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
            results[ctx["id"]]=r.parse(log.read_text(),plan,ctx)
        summary=r.margins(results,plan,saved["aperture"])
        if fault=="period":
            r.require(results==saved["results"] and summary==saved["summary"],"RELATIVE_PERIOD_DEPENDENCE")
            affected=[]
        else:
            field={"short_request":"maximum_input_data_lag_ns","early_ack":"ack_after_capture_ns","late_capture":"zero_reuse_hold_margin_ns"}[fault]
            r.require(all(v[field]>0 for v in saved["summary"]["lanes"]),"RELATIVE_FAULT_BASELINE_FAILED")
            changed={(a["lane"],a["phase"]) for a,b in zip(summary["lanes"],saved["summary"]["lanes"]) if a[field]<b[field]-1e-6}
            affected=[(v["lane"],v["phase"]) for v in summary["lanes"] if v[field]<0]
            r.require(bool(affected),"RELATIVE_FAULT_NOT_DETECTED_"+fault)
            if fault=="late_capture":
                # Bind exact shared capture-net members, rather than accepting
                # any conveniently failing lane or a coincidental tool error.
                c=next(c for c in plan["native"]["cells"] if c["path"]==arcs[0]["cell"])
                node=c["pins"]["Z"]; cp="E" if plan["variant"]=="bd" else "CLK"
                members={c["path"]+"/"+cp for c in plan["native"]["cells"] if c["pins"].get(cp)==node}
                ctx=next(c for c in plan["contexts"] if c["id"]=="common")
                lanes={q["lane"] for q in ctx["queries"] if q["role"]=="capture" and q["sink"] in members}
                expected={(lane,p) for lane in lanes for p in ([0] if plan["variant"]=="bd" else [0,1])}
                r.require(set(affected)==changed==expected,"RELATIVE_FAULT_WRONG_LANES")
            else:
                expected={(v["lane"],v["phase"]) for v in saved["summary"]["lanes"]}
                r.require(changed==expected,"RELATIVE_FAULT_NO_PATH_MOVEMENT")
            # Setup cannot change in controls that only annotate ACK/capture
            # distribution in the independent common-event context.
            if fault!="short_request":
                r.require(all(a["maximum_input_data_lag_ns"]==b["maximum_input_data_lag_ns"] for a,b in zip(summary["lanes"],saved["summary"]["lanes"])),"RELATIVE_FAULT_SCOPE")
        r.write_json(output/(fault+".json"),dict(summary=summary,results=results,arcs=arcs,affected=affected))
        verdicts.append(dict(fault=fault,affected=affected,status="EXPECTED",arc_count=len(arcs)))
    for f,h in receipt["inputs_sha256"].items():r.require(r.sha(Path(f))==h,"RELATIVE_CONTROL_INPUT_CHANGED")
    r.require(r.sha(Path(__file__))==source_hash,"RELATIVE_CONTROL_SOURCE_CHANGED")
    for f,h in receipt["files_sha256"].items():r.require(r.sha(baseline/f)==h,"RELATIVE_CONTROL_BASE_CHANGED")
    r.write_json(output/"controls.json",dict(status="PASS",physical_qualification=False,verdicts=verdicts,
        baseline_sha256=r.sha(baseline/"results.json"),source_sha256=source_hash,
        runtime_sha256=runtime,
        files_sha256={p.name:r.sha(p) for p in output.iterdir() if p.is_file()}))
    print(json.dumps([dict(fault=v["fault"],affected=len(v["affected"]),status=v["status"]) for v in verdicts]))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("baseline","netlist","output"):p.add_argument(name,type=Path)
    a=p.parse_args();run(a.baseline,a.netlist,a.output)
