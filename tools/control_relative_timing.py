# SPDX-License-Identifier: Apache-2.0
"""State-conditioned, pin-bound Control timing pilot. Never physical signoff.

Separate contexts preserve request-to-capture propagation and common-event
capture/ACK skew. An analysis clock describes one event; its period is never
used in a margin. No hardware, simulation budget, or mapper policy is changed.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re
import subprocess

from gf180_estimate import direct_groups, library, linux
from gf180_physical import ROOT, SC, pdk_verify, sha, write_json
from characterize_gf180_liberty import CORNERS, STA
from characterize_gf180_control_native import extract, audit_bindings
from repair_gf180_control import require
from screen_gf180_control_repair import stage_plan, brace, PROBE, TIMEOUT
from physical_tools import tool


def driver(plan, signal):
    node = plan["signals"][signal]
    pins = [c["path"]+"/"+p for c in plan["cells"] for p,n in c["pins"].items()
            if n == node and p in ("Z", "ZN", "Q")]
    require(len(pins) == 1, "RELATIVE_EVENT_DRIVER")
    return pins[0]


def conditions(plan, phase, common=False):
    """Only the reviewed initial capture cone; not a whole-cycle invariant."""
    cases = [("port", "reset", 0)]
    cuts = []
    if plan["variant"] == "bd":
        cases += [("pin", driver(plan, "b"), 0)]
        for c in plan["cells"]:
            if c["cell"] == SC+"aoi21_1":
                cuts.append(c["path"])
                if not c["path"].startswith("ca_primitive_b/"):
                    cases.append(("pin", c["path"]+"/A1", 0))
        require(len(cuts) == 3, "RELATIVE_KEEPER_COUNT")
        if not common:
            cases.append(("port", "out_ack", 0))
    else:
        # Freeze only comparator inputs, not phase Q or the ACK output cone.
        for c in plan["cells"]:
            if c["cell"] == SC+"xor2_1":
                pins = [p for p,n in c["pins"].items() if n == plan["signals"]["input_phase"]]
                require(len(pins) == 1, "RELATIVE_PHASE_SIDE_INPUT")
                cases.append(("pin", c["path"]+"/"+pins[0], phase))
        require(len(cases) == 3, "RELATIVE_COMPARE_COUNT")
        cases.append(("port", "out_ack", phase))
    return dict(cases=cases, keeper_cuts=cuts)


def lane_bindings(native, payload, allowance, captures):
    require(payload["d"]==allowance["q"],"RELATIVE_DATA_ALLOWANCE_BINDING")
    require(len(allowance["a"])==len(native["q"])==len(captures),"RELATIVE_LOGICAL_WIDTH")
    cells={c["path"]:c for c in native["cells"]};constants={};lane_map=[]
    for lane,pin in enumerate(captures):
        storage=cells[pin.rsplit("/",1)[0]]
        logical=native["q"].index(storage["pins"]["Q"])
        require(storage["pins"]["D"]==native["d"][logical],"RELATIVE_LOGICAL_LANE_PAIRING")
        lane_map.append(dict(lane=lane,logical=logical,D=pin.rsplit("/",1)[0]+"/D",capture=pin,Q=pin.rsplit("/",1)[0]+"/Q"))
        value=allowance["a"][logical]
        if isinstance(value,str):
            require(value in ("0","1"),"RELATIVE_UNKNOWN_DATA_LITERAL")
            constants[str(lane)]=int(value)
    require(len({x["logical"] for x in lane_map})==len(captures),"RELATIVE_DUPLICATE_STORAGE")
    return constants,lane_map


def make_plan(netlist, record, variant, descriptor=None):
    native = extract(netlist, variant, descriptor)
    audit_bindings(netlist, record, native)
    old = stage_plan(netlist, variant, descriptor)
    data = [q for q in old["queries"] if q["role"] == "data"]
    captures = sorted({q["sink"] for q in old["queries"] if q["role"] == "capture"})
    require(all(q["sink"].rsplit("/",1)[0]==captures[q["lane"]].rsplit("/",1)[0] for q in data),
            "RELATIVE_LANE_PAIRING")
    constants={}; lane_map=[]
    if descriptor:
        payload=netlist["modules"][native["module"]]["cells"]["ca_primitive_payload"]["connections"]
        allowance=netlist["modules"][native["module"]]["cells"]["ca_primitive_data_delay"]["connections"]
        constants,lane_map=lane_bindings(native,payload,allowance,captures)
        data=[q for q in data if str(q["lane"]) not in constants]
    event = driver(native, "long_hold" if variant == "bd" else "fire")
    contexts = [dict(id="data", kind="data", state=conditions(native,0),
                     source_kind="port", sources=old["sources"], queries=data)]
    for phase in ([0] if variant == "bd" else [0,1]):
        edge = "rise" if phase == 0 else "fall"
        qs = [dict(id=f"capture:{i}:{m}:{edge}", role="capture", lane=i, mode=m,
                   source_edge=edge, sink_edge="fall" if variant=="bd" else "rise",
                   sink_kind="pin",sink=p) for i,p in enumerate(captures) for m in ("min","max")]
        contexts.append(dict(id=f"request-{phase}",kind="request",state=conditions(native,phase),
                             source_kind="port", sources=["in_req"],queries=qs))
        if variant == "click":
            # A pending request can also capture when downstream releases the
            # occupied slot. Keep this separate from request-referenced setup:
            # the request/data age is unbounded while backpressured.
            state=conditions(native,phase)
            state["cases"]=[c for c in state["cases"] if c[1]!="out_ack"]+[("port","in_req",1-phase)]
            release="fall" if phase==0 else "rise"
            blocked=[dict(q,id=q["id"].replace(edge,release),source_edge=release) for q in qs]
            contexts.append(dict(id=f"release-{phase}",kind="release",state=state,
                                 source_kind="port",sources=["out_ack"],queries=blocked))
    # This event is the shared split to capture and acknowledgment. The driver
    # remains connected: use its propagated slew, then compare it with the
    # request/release contexts. No invented request arrival or clock slack.
    qs = [dict(id=f"capture:{i}:{m}",role="capture",lane=i,mode=m,source_edge="rise",
               sink_edge="fall" if variant=="bd" else "rise",sink_kind="pin",sink=p)
          for i,p in enumerate(captures) for m in ("min","max")]
    if variant == "click":
        qs += [dict(id=f"phase_clock:{m}",role="phase_clock",mode=m,source_edge="rise",
                    sink_edge="rise",sink_kind="pin",sink=native["phase"]["CLK"]["pin"]) for m in ("min","max")]
    else:
        qs += [dict(id=f"ack:{m}:rise",role="ack",mode=m,source_edge="rise",
                    sink_edge="rise",sink_kind="port",sink="in_ack") for m in ("min","max")]
    contexts.append(dict(id="common",kind="common",state=conditions(native,0,True),
                         source_kind="clock",sources=[event],queries=qs))
    if variant == "click":
        qs = [dict(id=f"ack:{m}:{e}",role="ack",mode=m,source_edge=e,sink_edge=e,
                   sink_kind="port",sink="in_ack") for m in ("min","max") for e in ("rise","fall")]
        contexts.append(dict(id="ack",kind="sequential_ack",state=conditions(native,0,True),
                             source_kind="clock",sources=[event],queries=qs))
    return dict(variant=variant,module=native["module"],event=event,contexts=contexts,
                phase=native["phase"],native=native,payload_width=len(captures),
                constant_lanes=constants,lane_map=lane_map,descriptor=descriptor)


def aperture(lib, variant):
    """Conservative maxima over all tabulated D setup/hold values, per corner.

    This avoids assuming a simulation allowance is a cell requirement. Values
    remain diagnostic if actual transitions/caps exceed characterized limits.
    """
    cell = SC+("latrnq_1" if variant=="bd" else "dffrnq_1")
    pin = dict(direct_groups(lib[cell],"pin"))["D"]
    result = {}
    for kind in ("setup","hold"):
        tables = []
        for _,body in direct_groups(pin,"timing"):
            if not re.search(r"timing_type\s*:\s*"+kind+"_",body):
                continue
            for key in ("rise_constraint","fall_constraint"):
                for _,table in direct_groups(body,key):
                    values = re.search(r"values\s*\((.*?)\)\s*;",table,re.S)
                    require(values is not None,"RELATIVE_APERTURE_TABLE")
                    tables += [float(v) for v in re.findall(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?",values[1])]
        require(tables and all(math.isfinite(v) for v in tables),"RELATIVE_APERTURE_MISSING")
        result[kind+"_ns"] = max(0.0,max(tables))
    return result


ACK_TCL = r'''
proc relative_ack {id mode edge phase_q phase_clk} {
  set ends [find_timing_paths -from [get_clocks event] -${edge}_to [get_ports in_ack] -path_delay $mode -group_path_count 1 -endpoint_path_count 1]
  if {[llength $ends] != 1} {error RELATIVE_ACK_MISSING}
  set end [lindex $ends 0]; set path [$end path]; set start [$path start_path]
  if {![$end is_output_delay] || [get_full_name [$start pin]] ne $phase_q} {error RELATIVE_ACK_SOURCE}
  set arc [get_timing_edges -from [exact_object pin $phase_clk] -to [exact_object pin $phase_q]]
  if {[llength $arc] != 1} {error RELATIVE_CLK_Q_ARC}
  set cq [get_property [lindex $arc 0] delay_${mode}_${edge}]
  row RELATIVE_ACK $id [sta::time_sta_ui [$path arrival]] [sta::time_sta_ui [$start arrival]] $cq
  set pins {}; foreach pin [$path pins] {lappend pins [get_full_name $pin]}
  row RELATIVE_ACK_POINTS $id {*}[lreverse $pins]
}
'''


def script(netlist, corner, slew, plan, context, period=1000, path=linux):
    text = f'read_liberty {brace(path(ROOT/".tools/physical/pdk"/(SC+corner+".lib")))}\n'
    text += PROBE.read_text()+"\n"+ACK_TCL+"\n"
    text += f'read_verilog {brace(path(netlist))}\nlink_design {brace(plan["module"])}\n'
    text += f'set_input_transition {slew} [all_inputs]\nset_load 0.05 [all_outputs]\nset_max_transition 2 [current_design]\n'
    for kind,pin,value in context["state"]["cases"]:
        text += f'set_case_analysis {value} [exact_object {kind} {brace(pin)}]\n'
    for cell in context["state"]["keeper_cuts"]:
        text += f'set_disable_timing -from A1 -to ZN [get_cells {brace(cell)}]\n'
    if context["source_kind"] == "clock":
        text += f'create_clock -name event -period {period} [exact_object pin {brace(plan["event"])}]\n'
        text += 'set_propagated_clock [all_clocks]\nset sources [get_clocks event]\n'
    else:
        text += 'set sources {}; foreach name [list '+" ".join(map(brace,context["sources"]))+'] {lappend sources [exact_object port $name]}\n'
    text += 'row RELATIVE_BEGIN\n'
    if context["kind"] == "sequential_ack":
        text += 'set_output_delay 0 -clock event [get_ports in_ack]\n'
        # Expanded report is independent human-readable evidence that the phase
        # CLK distribution and CLK-to-Q remain in the measured ACK arrival.
        text += 'report_checks -path_delay min_max -to [get_ports in_ack] -format full_clock_expanded -fields {slew} -digits 9\n'
        for q in context["queries"]:
            text += 'relative_ack '+" ".join(map(brace,[q["id"],q["mode"],q["sink_edge"],plan["phase"]["Q"]["pin"],plan["phase"]["CLK"]["pin"]]))+'\n'
    else:
        text += 'set targets {}\n'
        for kind,pin in sorted({(q["sink_kind"],q["sink"]) for q in context["queries"]}):
            text += f'lappend targets [exact_object {kind} {brace(pin)}]\n'
        text += 'set_max_delay 100000 -from $sources -to $targets\nset_min_delay 0 -from $sources -to $targets\n'
        batches=defaultdict(list)
        for q in context["queries"]:
            batches[tuple(q[k] for k in ("mode","source_edge","sink_edge","sink_kind"))].append(q)
        for (mode,se,te,kind),qs in batches.items():
            text += 'control_batch '+" ".join(map(brace,(mode,se,te)))+' $sources '+kind+' [list '
            text += " ".join(brace(q[k]) for q in qs for k in ("id","sink"))+']\n'
    text += f'set event_pin [exact_object pin {brace(plan["event"])}]\n'
    text += 'row RELATIVE_EVENT_SLEW [get_property $event_pin slew_min_rise] [get_property $event_pin slew_max_rise]\n'
    text += 'row RELATIVE_ELECTRICAL_BEGIN\nreport_check_types -max_slew -max_capacitance -violators -digits 6\nrow RELATIVE_ELECTRICAL_END\n'
    return text+'row RELATIVE_COMPLETE\nexit\n'


def parse(log, plan, context):
    require(log.count("RELATIVE_BEGIN\n")==1 and log.count("RELATIVE_COMPLETE\n")==1,"RELATIVE_INCOMPLETE")
    require(not re.search(r"(?mi)^(?:Error:|ERROR|Warning:)",log),"RELATIVE_TOOL_DIAGNOSTIC")
    expected={q["id"]:q for q in context["queries"]}; rows={}; points={};event_slew=None
    for line in log.splitlines():
        f=line.split("\t")
        if f[0] in ("CONTROL_PATH","RELATIVE_ACK"):
            key=f[1]
            require(key in expected and key not in rows,"RELATIVE_QUERY_ID")
            q=expected[key]
            if f[0]=="CONTROL_PATH":
                require(context["kind"]!="sequential_ack" and len(f)==11,"RELATIVE_ROW_SHAPE")
                source,arrival,data,delay,slew=map(float,f[2:7])
                require(all(math.isfinite(v) for v in (source,arrival,data,delay,slew)) and
                        abs(source)<1e-6 and abs(arrival-data)<1e-6 and abs(arrival-delay)<1e-6 and delay>=0 and slew>=0,
                        "RELATIVE_NUMERIC")
                start,end,se,te=f[7:]
                require(start in context["sources"] and end==q["sink"] and te==q["sink_edge"] and
                        se in ("rise","fall") and (q["source_edge"]=="any" or q["source_edge"]==se),"RELATIVE_PATH_BINDING")
                rows[key]=dict(delay_ns=delay,start=start,end=end,max_slew_ns=slew)
            else:
                require(context["kind"]=="sequential_ack" and len(f)==5,"RELATIVE_ROW_SHAPE")
                delay,qa,cq=map(float,f[2:])
                require(all(math.isfinite(v) and v>=0 for v in (delay,qa,cq)) and delay>=qa>=cq,"RELATIVE_ACK_NUMERIC")
                rows[key]=dict(delay_ns=delay,q_arrival_ns=qa,clk_q_ns=cq,start=plan["event"],end="in_ack")
        elif f[0] in ("CONTROL_POINTS","RELATIVE_ACK_POINTS"):
            require(f[1] in rows and f[1] not in points,"RELATIVE_POINTS_ID")
            points[f[1]]=f[2:]
        elif f[0]=="RELATIVE_EVENT_SLEW":
            require(len(f)==3 and event_slew is None,"RELATIVE_EVENT_SLEW_ROW")
            event_slew=list(map(float,f[1:]))
            require(all(math.isfinite(v) and v>=0 for v in event_slew) and event_slew[0]<=event_slew[1],"RELATIVE_EVENT_SLEW_NUMERIC")
    require(set(rows)==set(expected) and set(points)==set(expected),"RELATIVE_COVERAGE")
    for key,row in rows.items():
        require(points[key][0]==row["start"] and points[key][-1]==row["end"],"RELATIVE_POINTS_BINDING")
        if context["kind"] in ("request","release"):
            owners = (["request_delay","a","long_hold"] if plan["variant"]=="bd" else
                      (["request_delay","input_compare","fire"] if context["kind"]=="request" else ["output_compare","fire"]))
            required=[driver(plan["native"],owner) for owner in owners]
            require(all(points[key].count(p)==1 for p in required) and
                    [points[key].index(p) for p in required]==sorted(points[key].index(p) for p in required),
                    "RELATIVE_CONTROL_PROVENANCE")
        if context["kind"]=="sequential_ack":
            clk,q=[plan["phase"][p]["pin"] for p in ("CLK","Q")]
            require(points[key].count(clk)==points[key].count(q)==1 and
                    points[key].index(q)==points[key].index(clk)+1,"RELATIVE_ACK_SEQUENTIAL_PATH")
    bounds=defaultdict(dict)
    for key,q in expected.items():
        bounds[(q["sink"],q["source_edge"],q["sink_edge"])][q["mode"]]=rows[key]["delay_ns"]
    require(all(b["min"]<=b["max"]+1e-6 for b in bounds.values()),"RELATIVE_REVERSED_BOUNDS")
    require(log.count("RELATIVE_ELECTRICAL_BEGIN\n")==log.count("RELATIVE_ELECTRICAL_END\n")==1,"RELATIVE_ELECTRICAL_COVERAGE")
    electrical=log.split("RELATIVE_ELECTRICAL_BEGIN\n")[1].split("RELATIVE_ELECTRICAL_END\n")[0]
    require(event_slew is not None,"RELATIVE_EVENT_SLEW_MISSING")
    return dict(rows=rows,paths=points,event_slew_ns=event_slew,
                electrical_violations=[l for l in electrical.splitlines() if "(VIOLATED)" in l])


def margins(results, plan, cell):
    data=results["data"]["rows"]; common=results["common"]["rows"]
    # OpenSTA's pin property prints six decimal places in ns. The 2 fs
    # tolerance covers endpoint rounding only; this is not a mismatch margin.
    low,high=results["common"]["event_slew_ns"]
    for name,result in results.items():
        if name=="data":continue
        lo,hi=result["event_slew_ns"]
        require(lo>=low-2e-6 and hi<=high+2e-6,"RELATIVE_COMMON_SLEW_COVERAGE")
    values=[]
    for phase in ([0] if plan["variant"]=="bd" else [0,1]):
        edge="rise" if phase==0 else "fall"
        request=results[f"request-{phase}"]["rows"]
        acks=common if plan["variant"]=="bd" else results["ack"]["rows"]
        ack=acks[f"ack:min:{edge}"]["delay_ns"]
        if plan["variant"]=="click":
            for mode in ("min","max"):
                a=acks[f"ack:{mode}:{edge}"]
                clk=common[f"phase_clock:{mode}"]["delay_ns"]
                require(abs(a["q_arrival_ns"]-clk-a["clk_q_ns"])<1e-4,"RELATIVE_ACK_CLOCK_ACCOUNTING")
        for lane in range(plan.get("payload_width",315)):
            if str(lane) in plan.get("constant_lanes",{}):
                values.append(dict(lane=lane,phase=phase,constant=plan["constant_lanes"][str(lane)],
                    maximum_input_data_lag_ns=None,zero_reuse_hold_margin_ns=None,
                    ack_after_capture_ns=ack-common[f"capture:{lane}:max"]["delay_ns"]))
                continue
            dmax=max(data[f"data:{lane}:max:{e}"]["delay_ns"] for e in ("rise","fall"))
            dmin=min(data[f"data:{lane}:min:{e}"]["delay_ns"] for e in ("rise","fall"))
            capture=request[f"capture:{lane}:min:{edge}"]["delay_ns"]
            close=common[f"capture:{lane}:max"]["delay_ns"]
            values.append(dict(lane=lane,phase=phase,
                maximum_input_data_lag_ns=capture-dmax-cell["setup_ns"],
                zero_reuse_hold_margin_ns=ack+dmin-close-cell["hold_ns"],
                ack_after_capture_ns=ack-close))
    return dict(lanes=values, minimum_input_data_lag_ns=min((v["maximum_input_data_lag_ns"] for v in values if v["maximum_input_data_lag_ns"] is not None),default=None),
                minimum_zero_reuse_hold_ns=min((v["zero_reuse_hold_margin_ns"] for v in values if v["zero_reuse_hold_margin_ns"] is not None),default=None),
                minimum_ack_after_capture_ns=min(v["ack_after_capture_ns"] for v in values),
                unresolved=["Join storage Q/request launch alignment", "BD pending admission and both returns",
                            "Click feedback pulse and phase self-hold", "local variation/mismatch", "wire RC and reset", "electrical limits"],
                physical_qualification=False)


def run(mapping, repaired, output, variant, corners, slews, period=1000):
    require(not output.exists(),"RELATIVE_OUTPUT_EXISTS")
    pdk=ROOT/".tools/physical/pdk";pdk_verify(pdk)
    receipt=json.loads((repaired/"repair.json").read_text())
    require(receipt["variant"]==variant and receipt["status"]=="repaired-unqualified","RELATIVE_REPAIR_RECEIPT")
    for f,h in receipt["files_sha256"].items():require(sha(repaired/f)==h,"RELATIVE_REPAIR_CHANGED")
    for f,h in receipt["source_sha256"].items():require(sha(mapping/f)==h,"RELATIVE_SOURCE_CHANGED")
    plan=make_plan(json.loads((repaired/"netlist.json").read_text()),json.loads((mapping/"mapping.json").read_text()),variant)
    files=[repaired/"netlist.v",repaired/"netlist.json",repaired/"repair.json",mapping/"mapping.json",PROBE,Path(__file__)]
    files += [ROOT/"tools"/f for f in ("characterize_gf180_control_native.py","screen_gf180_control_repair.py",
        "characterize_gf180_liberty.py","gf180_estimate.py","gf180_physical.py","gf180_implement.py","repair_gf180_control.py")]
    files += [pdk/(SC+c+".lib") for c in CORNERS]
    sta=tool("sta")
    files += sta.input_files()
    frozen={str(p.resolve()):sha(p) for p in files}
    output.mkdir(parents=True); write_json(output/"plan.json",dict(plan=plan,inputs_sha256=frozen,period_ns=period))
    cases=[]
    for corner in corners:
        cell=aperture(library(pdk/(SC+corner+".lib")),variant)
        for slew in slews:
            key=f"{corner}-s{slew}"; results={}
            for ctx in plan["contexts"]:
                name=key+"-"+ctx["id"]; tcl=output/(name+".tcl");log=output/(name+".log")
                tcl.write_text(script(repaired/"netlist.v",corner,slew,plan,ctx,period,path=sta.path),newline="\n")
                with log.open("w") as stream:
                    subprocess.run(sta.command(["-no_init","-exit",sta.path(tcl)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
                results[ctx["id"]]=parse(log.read_text(),plan,ctx)
            summary=margins(results,plan,cell)
            write_json(output/(key+".json"),dict(results=results,aperture=cell,summary=summary))
            cases.append(dict(key=key,corner=corner,slew_ns=slew,summary={k:v for k,v in summary.items() if k!="lanes"}))
            print(json.dumps(cases[-1]),flush=True)
    require(all(sha(Path(p))==h for p,h in frozen.items()),"RELATIVE_INPUT_CHANGED")
    write_json(output/"results.json",dict(status="CONDITIONAL_LOCAL_MEASUREMENTS",physical_qualification=False,
        cases=cases,inputs_sha256=frozen,files_sha256={p.name:sha(p) for p in sorted(output.iterdir()) if p.is_file()}))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("mapping","repaired","output"):p.add_argument(name,type=Path)
    p.add_argument("--variant",required=True,choices=("bd","click"))
    p.add_argument("--campaign",action="store_true")
    p.add_argument("--period",type=int,choices=(1000,2000),default=1000)
    a=p.parse_args();run(a.mapping,a.repaired,a.output,a.variant,CORNERS if a.campaign else CORNERS[:1],
                        [0.02,2.0] if a.campaign else [0.2],a.period)
