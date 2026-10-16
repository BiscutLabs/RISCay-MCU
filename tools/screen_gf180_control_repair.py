# SPDX-License-Identifier: Apache-2.0
"""Bounded, explicit-polarity stage comparison; never reports physical closure.

Every payload D lane gets min/max for each endpoint transition. With exactly one
endpoint/edge and identical zero source arrival, slack ordering is propagation
ordering (unlike the previous all-endpoint worst-slack sample). Capture queries
target the actual E/CLK leaf pins. Inferred data-lead/hold margins are conditional local
boundary diagnostics, not proof of upstream launch or legal phase sensitization.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re
import subprocess

from gf180_estimate import linux
from gf180_physical import ROOT, SC, sha, write_json, pdk_verify
from gf180_implement import leaves
from characterize_gf180_liberty import CORNERS, STA
from repair_gf180_control import TARGETS, PREFIX, audit, require

PROBE = ROOT/"physical/gf180/control-repair-probe.tcl"
TIMEOUT = "/nix/store/2lwxwsaixnaq561hbq02v5236935ass8-coreutils-full-9.8/bin/coreutils"


def brace(s):
    require(not any(c in s for c in "{}\n\r"), "CONTROL_TCL_IDENTIFIER")
    return "{"+s+"}"


def stage_plan(netlist, variant, descriptor=None):
    module = descriptor["module"] if descriptor else TARGETS[variant][0]
    width = descriptor["payload_width"] if descriptor else 315
    input_width = descriptor["input_width"] if descriptor else 655
    body = netlist["modules"][module]
    sources = []
    for name, p in body["ports"].items():
        if name=="in_bits" or name.startswith("in_bits_"):
            require(p["direction"] == "input", "CONTROL_SOURCE_DIRECTION")
            sources += [name] if len(p["bits"]) == 1 else [f"{name}[{i}]" for i in range(len(p["bits"]))]
    require(len(sources) == input_width, "CONTROL_SOURCE_WIDTH")
    kind = SC+("latrnq_1" if variant == "bd" else "dffrnq_1")
    payload = [(p,c) for p,c in leaves(netlist["modules"],module)
               if p.startswith("ca_primitive_payload/") and c["type"] == kind]
    require(len(payload) == width, "CONTROL_PAYLOAD_WIDTH")
    capture_pin = "E" if variant == "bd" else "CLK"
    capture_edge = "fall" if variant == "bd" else "rise"
    phases = ["rise"] if variant == "bd" else ["rise", "fall"]
    queries = []
    for lane,(p,c) in enumerate(sorted(payload)):
        require(all(len(c["connections"][x]) == 1 for x in ("D",capture_pin)), "CONTROL_STORAGE_PINS")
        for mode in ("min", "max"):
            for edge in ("rise", "fall"):
                queries.append(dict(id=f"data:{lane}:{mode}:{edge}", role="data", lane=lane,
                    mode=mode, source_edge="any", sink_edge=edge, sink_kind="pin", sink=p+"/D"))
            for phase in phases:
                queries.append(dict(id=f"capture:{lane}:{mode}:{phase}", role="capture", lane=lane,
                    mode=mode, source_edge=phase, sink_edge=capture_edge, sink_kind="pin", sink=p+"/"+capture_pin))
    for mode in ("min", "max"):
        for phase in phases:
            queries.append(dict(id=f"ack:{mode}:{phase}", role="ack", mode=mode, source_edge=phase,
                sink_edge=phase, sink_kind="port", sink="in_ack"))
    # Resolve the guard's actual scalar output driver, not a hierarchy boundary.
    # This gets its own linked design so the added measurement endpoint cannot
    # stop propagation in the independent request-to-capture query context.
    owner="ca_primitive_request_delay"
    guard_module=body["cells"][owner]["type"]
    port="q"
    for _ in range(64):
        gm=netlist["modules"][guard_module]
        bits=gm["ports"][port]["bits"]
        require(len(bits)==1,"CONTROL_GUARD_WIDTH")
        drivers=[(n,c,p) for n,c in gm["cells"].items() for p,bs in c["connections"].items()
                 if c["port_directions"][p]=="output" and bs==bits]
        require(len(drivers)==1,"CONTROL_GUARD_DRIVER")
        name,c,port=drivers[0];owner+="/"+name
        if c["type"].startswith(SC):
            require(c["type"]==SC+"dlyd_1" and port=="Z","CONTROL_GUARD_LEAF")
            break
        guard_module=c["type"]
    else:raise ValueError("CONTROL_GUARD_HIERARCHY_LIMIT")
    for mode in ("min","max"):
        for phase in phases:
            queries.append(dict(id=f"guard:{mode}:{phase}",role="guard",mode=mode,source_edge=phase,
                sink_edge=phase,sink_kind="pin",sink=owner+"/"+port))
    require(len(queries) <= (16384 if descriptor else 2600) and len({q["id"] for q in queries}) == len(queries), "CONTROL_QUERY_LIMIT")
    electrical = [] if descriptor else [TARGETS[variant][1]+"/ZN"] + [n+"/Z" for n in body["cells"] if n.startswith(PREFIX)]
    return dict(module=module, sources=sources, queries=queries, electrical=sorted(electrical))


def script(netlist, corner, slew, plan):
    text = f'read_liberty {brace(linux(ROOT/".tools/physical/pdk"/(SC+corner+".lib")))}\n'
    text += PROBE.read_text()+"\n"
    text += 'row CONTROL_BEGIN\n'
    for guard_only in (True,False):
        text += f'read_verilog {brace(linux(netlist))}\nlink_design {brace(plan["module"])}\n'
        text += f'set_input_transition {slew} [all_inputs]\nset_load 0.05 [all_outputs]\nset_max_transition 2 [current_design]\n'
        text += 'set data_sources {}; foreach name [list '+" ".join(map(brace,plan["sources"]))+'] {lappend data_sources [exact_object port $name]}\n'
        text += 'set request [exact_object port in_req]\nset targets {}\n'
        cohort=[q for q in plan["queries"] if (q["role"]=="guard")==guard_only]
        for kind,name in sorted({(q["sink_kind"],q["sink"]) for q in cohort}):
            text += f'lappend targets [exact_object {kind} {brace(name)}]\n'
        text += 'set_max_delay 10 -from [all_inputs] -to $targets\nset_min_delay 0 -from [all_inputs] -to $targets\n'
        batches=defaultdict(list)
        for q in cohort:
            batches[tuple(q[k] for k in ("role","mode","source_edge","sink_edge","sink_kind"))].append(q)
        for (role,mode,source_edge,sink_edge,kind), qs in batches.items():
            text += 'control_batch '+" ".join(map(brace,(mode,source_edge,sink_edge)))
            text += ' '+('$data_sources' if role=="data" else '$request')+' '+kind+' [list '
            text += " ".join(brace(q[k]) for q in qs for k in ("id","sink"))+']\n'
    for pin in plan["electrical"]:
        text += f'set p [exact_object pin {brace(pin)}]\n'
        text += f'row CONTROL_SLEW {brace(pin)} [get_property $p slew_max_rise] [get_property $p slew_max_fall]\n'
    text += 'row CONTROL_ELECTRICAL_BEGIN\nreport_check_types -max_slew -max_capacitance -violators -digits 6\nrow CONTROL_ELECTRICAL_END\n'
    return text+'row CONTROL_COMPLETE\nexit\n'


def parse(log, plan):
    require(log.count("CONTROL_BEGIN\n") == 1 and log.count("CONTROL_COMPLETE\n") == 1, "CONTROL_INCOMPLETE")
    require(not re.search(r"(^|\n)Error:|(^|\n)ERROR",log), "CONTROL_TOOL_ERROR")
    expected = {q["id"]:q for q in plan["queries"]}
    found, points, missing, slews = {}, {}, [], {}
    for line in log.splitlines():
        fields = line.split("\t")
        if fields[0] == "CONTROL_MISSING":
            require(len(fields)==2 and fields[1] in expected and fields[1] not in found and fields[1] not in missing, "CONTROL_MISSING_ID")
            missing.append(fields[1])
        elif fields[0] == "CONTROL_PATH":
            require(len(fields)==11, "CONTROL_ROW_SHAPE")
            _,key,*v = fields
            require(key in expected and key not in found and key not in missing, "CONTROL_QUERY_ID")
            numbers = list(map(float,v[:5]))
            require(all(math.isfinite(x) for x in numbers), "CONTROL_NONFINITE")
            source,arrival,data,delay,slew = numbers
            require(abs(source)<1e-6 and abs(arrival-data)<1e-6 and abs(arrival-source-delay)<1e-6 and delay>=0 and slew>=0, "CONTROL_NUMERIC_CROSSCHECK")
            q = expected[key]
            start,end,start_edge,end_edge = v[5:]
            require(end == q["sink"] and end_edge == q["sink_edge"], "CONTROL_ENDPOINT_BINDING")
            require(start in (plan["sources"] if q["role"]=="data" else ["in_req"]), "CONTROL_SOURCE_BINDING")
            require(start_edge in ("rise","fall") and (q["source_edge"]=="any" or start_edge==q["source_edge"]), "CONTROL_SOURCE_POLARITY")
            found[key] = dict(delay_ns=delay, path_max_slew_ns=slew, start=start, end=end,
                              start_edge=start_edge, end_edge=end_edge)
        elif fields[0] == "CONTROL_POINTS":
            require(len(fields)>=4 and fields[1] in found and fields[1] not in points, "CONTROL_POINTS_BINDING")
            points[fields[1]] = fields[2:]
        elif fields[0] == "CONTROL_SLEW":
            require(len(fields)==4 and fields[1] in plan["electrical"] and fields[1] not in slews, "CONTROL_SLEW_BINDING")
            nums = list(map(float,fields[2:]))
            require(all(math.isfinite(x) and x>=0 for x in nums), "CONTROL_NONFINITE_SLEW")
            slews[fields[1]] = nums
    require(set(found)|set(missing)==set(expected) and set(points)==set(found) and set(slews)==set(plan["electrical"]), "CONTROL_COVERAGE")
    for key,row in found.items():
        require(points[key][0]==row["start"] and points[key][-1]==row["end"], "CONTROL_POINTS_ENDPOINTS")
    bounds=defaultdict(dict)
    for key,q in expected.items():
        if key in found:
            bounds[(q["sink"],q["source_edge"],q["sink_edge"])][q["mode"]]=found[key]["delay_ns"]
    require(all(b["min"] <= b["max"]+1e-6 for b in bounds.values() if set(b)=={"min","max"}), "CONTROL_REVERSED_BOUNDS")
    require(log.count("CONTROL_ELECTRICAL_BEGIN\n")==1 and log.count("CONTROL_ELECTRICAL_END\n")==1, "CONTROL_ELECTRICAL_COVERAGE")
    electrical_log = log.split("CONTROL_ELECTRICAL_BEGIN\n")[1].split("CONTROL_ELECTRICAL_END\n")[0]
    violations = [line for line in electrical_log.splitlines() if "(VIOLATED)" in line]
    return dict(rows=found, paths=points, missing=missing, selected_slews_ns=slews,
                electrical_violations=violations, loop_warnings=[l for l in log.splitlines() if re.search(r"loop|cycle",l,re.I)])


def summarize(result, variant):
    rows = result["rows"]
    data = {k:v for k,v in rows.items() if k.startswith("data:")}
    capture = {k:v for k,v in rows.items() if k.startswith("capture:")}
    summary = dict(query_count=len(rows)+len(result["missing"]), missing_count=len(result["missing"]),
        max_data_ns=max(v["delay_ns"] for k,v in data.items() if ":max:" in k),
        min_data_ns=min(v["delay_ns"] for k,v in data.items() if ":min:" in k),
        data_budget_ns=10, electrical_violation_rows=len(result["electrical_violations"]),
        selected_max_slew_ns=max(max(x) for x in result["selected_slews_ns"].values()),
        physical_qualification=False)
    summary["data_budget_numerically_met"] = summary["max_data_ns"] <= 10 and not any(k.startswith("data:") for k in result["missing"])
    # Numeric data allowance is separate from missing capture/ACK coverage and
    # electrical validity. Neither is converted into a qualification pass.
    guards={k:v["delay_ns"] for k,v in rows.items() if k.startswith("guard:")}
    summary["request_guard_ns"]=guards
    if guards:
        summary["data_plus_setup_before_request_guard_ns"] = min(v for k,v in guards.items() if ":min:" in k)-summary["max_data_ns"]-(8 if variant=="bd" else 5)
        # This compares data and an earlier control node. It does not replace
        # capture-pin, legal phase, source-reuse or hold qualification.
    if capture:
        summary["capture_min_ns"] = min(v["delay_ns"] for k,v in capture.items() if ":min:" in k)
        summary["capture_max_ns"] = max(v["delay_ns"] for k,v in capture.items() if ":max:" in k)
    phases = ["rise"] if variant=="bd" else ["rise","fall"]
    margins = []
    for lane in range(315):
        for phase in phases:
            needed = [f"data:{lane}:{m}:{e}" for m in ("min","max") for e in ("rise","fall")]
            needed += [f"capture:{lane}:{m}:{phase}" for m in ("min","max")]
            if all(k in rows for k in needed):
                dmin = min(rows[f"data:{lane}:min:{e}"]["delay_ns"] for e in ("rise","fall"))
                dmax = max(rows[f"data:{lane}:max:{e}"]["delay_ns"] for e in ("rise","fall"))
                cmin,cmax = [rows[f"capture:{lane}:{m}:{phase}"]["delay_ns"] for m in ("min","max")]
                ack = rows.get(f"ack:min:{phase}")
                margins.append(dict(lane=lane,phase=phase,
                    required_data_lead_ns=dmax+(8 if variant=="bd" else 5)-cmin,
                    immediate_reuse_hold_margin_ns=ack["delay_ns"]+dmin-cmax-1 if ack else None))
    summary["conditional_lane_margins"] = margins
    return summary


def run(before, after, output, variant, corners, slews):
    require(not output.exists(), "CONTROL_OUTPUT_EXISTS")
    pdk_verify(ROOT/".tools/physical/pdk")
    receipt = json.loads((after/"repair.json").read_text())
    require(receipt["variant"]==variant and receipt["status"]=="repaired-unqualified", "CONTROL_REPAIR_RECEIPT")
    frozen = dict(receipt["inputs_sha256"])
    for f,h in receipt["files_sha256"].items():
        require(sha(after/f)==h, "CONTROL_REPAIR_CHANGED")
        frozen[str((after/f).resolve())]=h
    for f,h in receipt["source_sha256"].items():
        require(sha(before/f)==h,"CONTROL_SOURCE_CHANGED")
    before_json=json.loads((before/"netlist.json").read_text()); after_json=json.loads((after/"netlist.json").read_text())
    audit(before_json,after_json,variant)
    plans = {"before":stage_plan(before_json,variant), "after":stage_plan(after_json,variant)}
    require(plans["before"]["queries"]==plans["after"]["queries"],"CONTROL_PLAN_DRIFT")
    for p in (Path(__file__),PROBE,after/"repair.json"):
        frozen[str(p.resolve())]=sha(p)
    # Bind the exact installed STA executable (Nix store transitively pins its dependencies).
    sta_windows=Path("//wsl.localhost/nixos-librelane"+STA)
    timeout_windows=Path("//wsl.localhost/nixos-librelane"+TIMEOUT)
    frozen[str(sta_windows)]=sha(sta_windows); frozen[str(timeout_windows)]=sha(timeout_windows)
    require(all(sha(Path(p))==h for p,h in frozen.items()), "CONTROL_STALE_INPUT")
    output.mkdir(parents=True)
    write_json(output/"plan.json",dict(variant=variant,plans=plans,corners=corners,slews=slews,inputs_sha256=frozen))
    cases=[]
    for corner in corners:
        for slew in slews:
            for side,path in (("before",before),("after",after)):
                key=f"{side}-{corner}-s{slew}"
                tcl=output/(key+".tcl"); log=output/(key+".log")
                tcl.write_text(script(path/"netlist.v",corner,slew,plans[side]),newline="\n")
                command=["wsl","-d","nixos-librelane","-e",TIMEOUT,"--coreutils-prog=timeout","--signal=TERM","--kill-after=5s","110s",STA,"-no_init","-exit",linux(tcl)]
                with log.open("w") as stream:
                    subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
                result=parse(log.read_text(),plans[side]); summary=summarize(result,variant)
                write_json(output/(key+".json"),result)
                cases.append(dict(key=key,side=side,corner=corner,slew_ns=slew,summary=summary,
                    tcl_sha256=sha(tcl),log_sha256=sha(log),result_sha256=sha(output/(key+".json"))))
                print(key,json.dumps({k:v for k,v in summary.items() if k!="conditional_lane_margins"}),flush=True)
    require(all(sha(Path(p))==h for p,h in frozen.items()),"CONTROL_INPUT_CHANGED_DURING_RUN")
    write_json(output/"screen.json",dict(status="MEASURED_PHYSICAL_OPEN",physical_qualification=False,
        variant=variant,cases=cases,inputs_sha256=frozen,
        limitations=["Isolated stage; no wire RC", "No upstream data/request launch alignment proof",
                    "No protocol sensitization, reset, pulse or BD RTZ proof",
                    "Explicit min/max measurement constraints; no false paths, created clocks, reset cases or manual loop cuts",
                    "All electrical violations remain open; numbers outside limits are diagnostic only",
                    "Hold expression assumes immediate source reuse after ACK; full upstream path remains open"]))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("before",type=Path);p.add_argument("after",type=Path);p.add_argument("output",type=Path)
    p.add_argument("--variant",required=True,choices=TARGETS)
    p.add_argument("--corner",action="append",choices=CORNERS)
    p.add_argument("--slew",action="append",type=float,choices=(0.02,2.0))
    a=p.parse_args();run(a.before,a.after,a.output,a.variant,a.corner or CORNERS,a.slew or [0.02,2.0])
