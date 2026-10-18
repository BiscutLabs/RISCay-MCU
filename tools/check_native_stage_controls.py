# SPDX-License-Identifier: Apache-2.0
"""Actual-arc controls for contract-selected stage widths and constant lanes."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import control_relative_timing as r
import native_leaf_timing as leaf
from check_control_relative_controls import fault_sdf
from run_receipt import RunReceipt
from timing_properties import period_invariant


def parent_data_fault(plan, saved, index, buffers):
    """Mutate the real repaired elapsed mode distribution, never a report value."""
    roots={r['source'] for r in plan['input_lanes'] if r['port']=='in_bits_state_mode' and r['kind']=='pin'}
    r.require(roots,'STAGE_PARENT_MODE_SOURCE')
    candidates=[]
    for points in saved['results']['data']['paths'].values():
        if points[0] not in roots:continue
        candidates += [p.rsplit('/',1)[0] for p in points if p.endswith('/Z') and p.rsplit('/',1)[0] in buffers]
    r.require(candidates,'STAGE_PARENT_BUFFER_MISSING')
    path=candidates[0];cell=index.after['cells'][path]
    r.require(cell['type'].startswith(r.SC+'buf_'),'STAGE_PARENT_BUFFER_KIND')
    reached={cell['connections']['Z'][0]}
    changed=True
    while changed:
        old=len(reached)
        for c in index.after['cells'].values():
            if c['type'].startswith((r.SC+'dff',r.SC+'lat')) or not c['type'].startswith(r.SC):continue
            if any(n in reached for p,ns in c['connections'].items() if c['directions'][p]=='input' for n in ns):
                reached.update(n for p,ns in c['connections'].items() if c['directions'][p]=='output' for n in ns)
        changed=len(reached)!=old
    lanes={l['lane'] for l in plan['lane_map'] if index.live_net('pin',l['D']) in reached}
    r.require(lanes,'STAGE_PARENT_NO_DATA_FANOUT')
    instance=path.replace('.',r'\.')
    sdf='(DELAYFILE (SDFVERSION "3.0") (DESIGN "RiscayMcuDigital") (DIVIDER /) (TIMESCALE 1ns)\n'
    sdf+=f'(CELL (CELLTYPE "{cell["type"]}") (INSTANCE {instance}) (DELAY (ABSOLUTE (IOPATH I Z (1000:1000:1000) (1000:1000:1000)))))\n)\n'
    return sdf,[dict(cell=path,source='I',sink='Z',delay_ns=1000)],lanes


def parent_verdict(before, after, plan, expected):
    old={(v['lane'],v['phase']):v for v in before['lanes']}
    new={(v['lane'],v['phase']):v for v in after['lanes']}
    dynamic={k for k,v in old.items() if v['maximum_input_data_lag_ns'] is not None}
    expected={k for k in dynamic if k[0] in expected}
    changed={k for k in dynamic if new[k]['maximum_input_data_lag_ns']<old[k]['maximum_input_data_lag_ns']-1e-6}
    r.require(changed==expected,'STAGE_PARENT_FAULT_SCOPE')
    for k in old:
        for metric in ('zero_reuse_hold_margin_ns','ack_after_capture_ns'):
            r.require(old[k][metric]==new[k][metric],'STAGE_PARENT_CONTROL_CHANGED')
    r.require(all(old[k]['maximum_input_data_lag_ns']>0 and new[k]['maximum_input_data_lag_ns']<0 for k in expected),
              'STAGE_PARENT_NO_NEW_FAILURE')
    return dict(fault='late_parent_data',status='EXPECTED',changed=sorted(changed),arc_count=1)


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
    r.require(not output.exists() and indices and len(indices)<=2 and len(indices)==len(set(indices)),"STAGE_CONTROL_SELECTION")
    r.require(faults and len(faults)==len(set(faults)) and set(faults)<={"period","short_request","early_ack","late_capture","late_parent_data"},"STAGE_CONTROL_FAULT_SELECTION")
    receipt=json.loads((baseline/"receipt.json").read_text());sta=r.tool("sta")
    r.require(receipt['status']=='pass','STAGE_CONTROL_FAILED_BASE')
    sources=[Path(__file__),Path(__file__).with_name("check_control_relative_controls.py"),
             Path(__file__).with_name("timing_properties.py"),Path(__file__).with_name("run_receipt.py")]
    run_receipt=RunReceipt(output/'receipt.json',inputs=[baseline/'receipt.json',*receipt['sha256']],
                           tools=[*sources,*sta.input_files()])
    r.require(all(run_receipt.files[p]==h for p,h in receipt['sha256'].items()),'STAGE_CONTROL_BASE_CHANGED')
    r.require(all(str(p.resolve()) in receipt['sha256'] for p in sta.input_files()),'STAGE_CONTROL_RUNTIME_CHANGED')
    output.mkdir(parents=True);verdicts=[]
    netlist=next(Path(p) for p in receipt['inputs'] if Path(p).name=="netlist.v")
    status='fail'
    try:
        mapping=netlist.parent
        proof=json.loads((mapping/'electrical-repair/proof.json').read_text())
        leaf_index=leaf.LeafIndex(json.loads((mapping/'electrical-repair/reference/netlist.json').read_text()),
            json.loads((mapping/'netlist.json').read_text()),proof['added_buffers'],proof['added_ties'])
        for index in indices:
            source=baseline/str(index);plan=json.loads((source/"plan.json").read_text())
            key="tt_025C_3v30-s0.2";saved=json.loads((source/(key+".json")).read_text())
            r.require(saved["case"]["failure"] is None,"STAGE_CONTROL_UNRESOLVED_BASE")
            sub=output/str(index);sub.mkdir()
            for fault in faults:
                results=deepcopy(saved["results"]);arcs=[]
                if fault!="period":
                    if fault=='late_parent_data':sdf,arcs,parent_lanes=parent_data_fault(plan,saved,leaf_index,set(proof['added_buffers']))
                    else:sdf,arcs=fault_sdf(plan,fault,capture_fault_pin(plan) if fault=="late_capture" else None)
                    (sub/(fault+".sdf")).write_text(sdf,newline="\n")
                for ctx in plan["contexts"]:
                    relevant=(True if fault=='period' else ctx['kind']=='data' if fault=='late_parent_data' else ctx['kind']=='request' if fault=='short_request'
                              else ctx['kind'] in ('common','sequential_ack'))
                    if not relevant:continue
                    if plan.get('leaf_anchored') and ctx['kind'] in ('common','sequential_ack'):
                        prior=[v['event_slew_ns'] for name,v in saved['results'].items() if name.startswith(('request-','release-'))]
                        ctx['root_slew_ns']=dict(min=min(v[0] for v in prior),max=max(v[1] for v in prior))
                    tcl=sub/(fault+"-"+ctx["id"]+".tcl");log=tcl.with_suffix(".log")
                    text=(leaf.script(netlist,r.CORNERS[0],.2,plan,ctx,period=2000 if fault=='period' else 1000,sta=sta)
                          if plan.get('leaf_anchored') else
                          r.script(netlist,r.CORNERS[0],.2,plan,ctx,2000 if fault=="period" else 1000,path=sta.path))
                    if fault!="period":text=text.replace('row RELATIVE_BEGIN',f'read_sdf {r.brace(sta.path(sub/(fault+".sdf")))}\nrow RELATIVE_BEGIN')
                    tcl.write_text(text,newline="\n")
                    with log.open("w") as stream:
                        subprocess.run(sta.command(["-no_init","-exit",sta.path(tcl)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
                    results[ctx["id"]]=(leaf.parse(log.read_text(),plan,ctx,.2,leaf_index) if plan.get('leaf_anchored')
                                         else r.parse(log.read_text(),plan,ctx))
                summary=r.margins(results,plan,saved["aperture"])
                if fault=="period":
                    period_invariant((results,summary),(saved["results"],saved["summary"]))
                    checked=dict(fault=fault,status="IDENTICAL")
                elif fault=='late_parent_data':checked=parent_verdict(saved['summary'],summary,plan,parent_lanes)
                else:checked=verdict(saved["summary"],summary,plan,fault,arcs)
                r.write_json(sub/(fault+".json"),dict(verdict=checked,summary=summary,results=results,arcs=arcs))
                verdicts.append(dict(index=index,instance=plan["descriptor"]["instance"],**checked))
                print(json.dumps({k:len(v) if isinstance(v,list) else v for k,v in verdicts[-1].items()}),flush=True)
        r.write_json(output/"controls.json",dict(status="PASS",physical_qualification=False,verdicts=verdicts))
        status='pass'
    finally:
        run_receipt.finish(outputs=[p for p in output.rglob('*') if p.is_file()],status=status,
                           coverage=dict(requested=[dict(index=i,fault=f) for i in indices for f in faults],verdicts=verdicts))



if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("baseline",type=Path);p.add_argument("output",type=Path)
    p.add_argument("--index",type=int,action="append",required=True)
    p.add_argument("--fault",choices=("period","short_request","early_ack","late_capture","late_parent_data"),action="append")
    a=p.parse_args();run(a.baseline,a.output,a.index,a.fault or ("period","short_request","early_ack","late_capture"))
