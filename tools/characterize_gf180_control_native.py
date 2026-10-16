# SPDX-License-Identifier: Apache-2.0
"""Bounded, uncut transistor-level Control controller/capture experiment.

The transform is cut at the actual storage D pins. This is conditional schematic
evidence, never complete-stage setup/hold, reset-tree or routed qualification.
"""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re
import subprocess

from gf180_estimate import linux
from gf180_physical import ROOT, SC, pdk_verify, sha, write_json
from repair_gf180_control import TARGETS, require
from characterize_gf180_keeper import CORNERS

OWNERS = {
    "bd": {"a", "b", "acknowledge", "long_hold", "output_delay", "payload", "request_delay"},
    "click": {"acknowledge_guard", "fire", "input_compare", "input_phase", "output_compare",
              "output_guard", "payload", "request_delay"},
}
LIMITS = "Unextracted, deterministic transistor models; ideal boundary reset/request/ACK/D sources; no transform, upstream source alignment/reuse, chip reset distribution, statistical variation or metastability qualification. Each payload Q and public ACK/offer has a chosen 0.05pF load, not extracted fanout."


def expected_binding(variant,owner):
    model="ChiselAsync"; params={"DELAY_FS":1000000}
    if owner in ("a","b","acknowledge"):
        model+="AsymmetricC_v1"
        params.update(COMMON=1,COMMON_INVERT=int(owner!="b"),FALLING=1,FALLING_INVERT=int(owner=="a"),
                      RISING=int(owner!="b"),RISING_INVERT=0,RESET_VALUE=0)
    elif owner=="payload":
        model+=("ClosingLatch_v1" if variant=="bd" else "EventRegister_v1")
        params["WIDTH"]=315
        if variant=="click":params["RESET_VALUE"]=0
    elif owner=="input_phase":model+="PhaseRegister_v1";params["RESET_VALUE"]=0
    elif owner in ("input_compare","output_compare"):model+="Xor_v1"
    elif owner=="fire":model+="And_v1";params.update(INPUTS=2,INVERT=2)
    else:
        model+="ControlGate_v1";params.update(OP=2 if owner=="long_hold" else 0,RESET_VALUE=0,WIDTH=1)
        params["DELAY_FS"]={"request_delay":11000000,"output_delay":31000000,"acknowledge_guard":32000000,
                            "output_guard":32000000,"long_hold":1000000}[owner]
    return model,params


def audit_bindings(netlist, record, plan):
    """Independently check each selected adapter against the mapper's cell graph."""
    modules=netlist["modules"]
    selected=set(plan.get("verify_roots",[a["path"].split("/")[0] for a in plan["aliases"]]))
    stage=modules[plan["module"]]
    bindings={b["module"]:b for b in record["bindings"]}
    require(len(bindings)==len(record["bindings"]),"NATIVE_DUPLICATE_BINDING")
    def resolve(kind,seen=()):
        require(kind not in seen and len(seen)<10,"NATIVE_HIERARCHY_CYCLE")
        if kind in bindings:return [kind]
        require(kind in modules and not kind.startswith(SC) and modules[kind]["cells"],"NATIVE_BINDING_WRAPPER")
        return [b for c in modules[kind]["cells"].values() for b in resolve(c["type"],seen+(kind,))]
    for root in selected:
        resolved=resolve(stage["cells"][root]["type"])
        require(len(resolved)==1,"NATIVE_BINDING_MULTIPLICITY")
        if "variant" in plan:
            b=bindings[resolved[0]]
            expected=plan.get("expected_bindings",{}).get(root)
            if expected is None:expected=expected_binding(plan["variant"],root.removeprefix("ca_primitive_"))
            require((b["model"],b["parameters"])==tuple(expected),
                    "NATIVE_BINDING_SPECIALIZATION")
    used=set()
    for binding in record["bindings"]:
        name=binding["module"]
        # Resolve by actual wrapper descent rather than a name-suffix assumption.
        def visit(kind):
            if kind==name: return True
            return kind in modules and not kind.startswith(SC) and any(visit(c["type"]) for c in modules[kind]["cells"].values())
        if not any(visit(stage["cells"][root]["type"]) for root in selected): continue
        used.add(name); body=modules[name]
        require(set(body["cells"])=={c["name"] for c in binding["cells"]},"NATIVE_BINDING_CELL_SET")
        def bit(net):
            if net in ("1'b0","1'b1"): return net[-1]
            m=re.fullmatch(r'(\w+)\[(\d+)\]',net)
            n,i=(m[1],int(m[2])) if m else (net,0)
            return body["netnames"][n]["bits"][i]
        for c in binding["cells"]:
            actual=body["cells"][c["name"]]
            require(actual["type"]==c["cell"] and actual["connections"]=={p:[bit(n)] for p,n in c["pins"].items()},"NATIVE_BINDING_CONNECTION")
    # Every physical leaf must come from one of the verified binding modules.
    def covered(kind):
        if kind in used: return True
        return kind in modules and not kind.startswith(SC) and bool(modules[kind]["cells"]) and all(covered(c["type"]) for c in modules[kind]["cells"].values())
    require(all(covered(stage["cells"][r]["type"]) for r in selected),"NATIVE_BINDING_COVERAGE")


def extract(netlist, variant, descriptor=None):
    """Flatten selected *actual netlist* roots, including physical feedback.

    No circuit reconstructed from a generic adapter template. Record every cut
    edge and reject any unexplained external connection to a control node.
    """
    modules = netlist["modules"]
    module = descriptor["module"] if descriptor else TARGETS[variant][0]
    width = descriptor["payload_width"] if descriptor else 315
    stage = modules[module]
    roots = {"ca_primitive_"+x for x in OWNERS[variant]}
    require({k for k in stage["cells"] if k.startswith("ca_primitive_")} ==
            roots | {"ca_primitive_data_delay"}, "NATIVE_ROOT_INVENTORY")
    def conn(owner,pin="q"):
        return stage["cells"]["ca_primitive_"+owner]["connections"][pin]
    def port(pin): return stage["ports"][pin]["bits"]
    for owner in OWNERS[variant]:
        require(conn(owner,"reset")==port("reset"),"NATIVE_RESET_WIRING")
    expected={ ("request_delay","a"):port("in_req"), ("request_delay","b"):["0"] }
    if variant=="bd":
        expected.update({("a","common"):conn("b"),("a","rising"):conn("request_delay"),
            ("a","falling"):port("out_ack"),("acknowledge","common"):conn("b"),
            ("acknowledge","rising"):conn("long_hold"),("acknowledge","falling"):conn("request_delay"),
            ("b","common"):conn("acknowledge"),("b","falling"):conn("long_hold"),("b","rising"):["1"],
            ("long_hold","a"):conn("a"),("long_hold","b"):port("out_ack"),
            ("payload","closed"):conn("long_hold"),("output_delay","a"):conn("a"),("output_delay","b"):["0"]})
        require(conn("acknowledge")==port("in_ack") and conn("output_delay")==port("out_req"),"NATIVE_PUBLIC_WIRING")
    else:
        expected.update({("input_compare","a"):conn("request_delay"),("input_compare","b"):conn("input_phase"),
            ("output_compare","a"):conn("input_phase"),("output_compare","b"):port("out_ack"),
            ("fire","d"):conn("input_compare")+conn("output_compare"),("input_phase","trigger"):conn("fire"),
            ("payload","trigger"):conn("fire"),("acknowledge_guard","a"):conn("input_phase"),
            ("output_guard","a"):conn("input_phase"),("acknowledge_guard","b"):["0"],("output_guard","b"):["0"]})
        require(conn("acknowledge_guard")==port("in_ack") and conn("output_guard")==port("out_req"),"NATIVE_PUBLIC_WIRING")
    require(all(conn(o,p)==bs for (o,p),bs in expected.items()),"NATIVE_PROTOCOL_WIRING")
    nodes = {}

    def node(key):
        if key == "0": return "0"
        if key == "1": return "vdd"
        require(key not in ("x", "z"), "NATIVE_UNKNOWN_CONSTANT")
        if key not in nodes: nodes[key] = "n"+str(len(nodes))
        return nodes[key]

    top = {b: node((module, b)) for c in stage["cells"].values()
           for bs in c["connections"].values() for b in bs if isinstance(b, int)}
    top.update({"0": "0", "1": "vdd"})
    cells = []
    aliases = []

    def descend(kind, path, connections,seen=()):
        require(kind not in seen and len(seen)<10,"NATIVE_HIERARCHY_CYCLE")
        if kind.startswith(SC):
            require(all(len(v)==1 for v in connections.values()), "NATIVE_LEAF_WIDTH")
            cells.append(dict(path=path, cell=kind, pins={k:v[0] for k,v in connections.items()}))
            return
        body = modules[kind]
        require(set(connections) == set(body["ports"]), "NATIVE_PORT_SET")
        local = {"0":"0", "1":"vdd"}
        for pin, port in body["ports"].items():
            require(len(port["bits"]) == len(connections[pin]), "NATIVE_PORT_WIDTH")
            for bit, net in zip(port["bits"], connections[pin]):
                require(bit not in local or local[bit] == net, "NATIVE_PORT_ALIAS")
                local[bit] = net
            aliases.append(dict(path=path, port=pin, nodes=connections[pin]))
        for name, cell in sorted(body["cells"].items()):
            mapped = {}
            for pin, bits in cell["connections"].items():
                mapped[pin] = []
                for bit in bits:
                    if bit not in local: local[bit] = node((path, bit))
                    mapped[pin].append(local[bit])
            descend(cell["type"], path+"/"+name, mapped,seen+(kind,))

    for name in sorted(roots):
        cell = stage["cells"][name]
        descend(cell["type"], name, {p:[top[b] for b in bs] for p,bs in cell["connections"].items()})
    payload = stage["cells"]["ca_primitive_payload"]
    d = [top[b] for b in payload["connections"]["d"]]
    q = [top[b] for b in payload["connections"]["q"]]
    ports = {k:top[stage["ports"][k]["bits"][0]] for k in ("reset","in_req","in_ack","out_req","out_ack")}
    require(len(d)==len(q)==width and len(set(d))==len(set(q))==width, "NATIVE_PAYLOAD_WIDTH")
    boundary = set(d+q+list(ports.values()))
    selected = {top[b] for n in roots for bs in stage["cells"][n]["connections"].values() for b in bs}
    cut = []
    for name, cell in sorted(stage["cells"].items()):
        if name in roots: continue
        for pin,bits in cell["connections"].items():
            for bit in bits:
                net=top[bit]
                if net in selected and net not in ("0","vdd"):
                    require(net in boundary, "NATIVE_UNEXPLAINED_CUT")
                    cut.append(dict(path=name, pin=pin, node=net, direction=cell["port_directions"][pin]))
    kind = SC+("latrnq_1" if variant=="bd" else "dffrnq_1")
    cap = "E" if variant=="bd" else "CLK"
    storage = [c for c in cells if c["path"].startswith("ca_primitive_payload/") and c["cell"]==kind]
    require(len(storage)==width, "NATIVE_STORAGE_INVENTORY")
    require({c["pins"]["D"] for c in storage}==set(d), "NATIVE_STORAGE_DATA")
    require({c["pins"]["Q"] for c in storage}==set(q), "NATIVE_STORAGE_OUTPUT")
    captures=defaultdict(list)
    for c in storage: captures[c["pins"][cap]].append(c["path"]+"/"+cap)
    groups=[16]*(width//16)+([width%16] if width%16 else [])
    require(len(captures)==len(groups) and sorted(map(len,captures.values()))==sorted(groups),
            "NATIVE_CAPTURE_MEMBERSHIP")
    # Storage inputs must be driven externally only at the explicit D boundary.
    # Every other non-supply input has a retained physical driver or boundary input.
    directions = {c["type"]:c["port_directions"] for m in modules.values() for c in m["cells"].values() if c["type"].startswith(SC)}
    drivers=Counter(n for c in cells for p,n in c["pins"].items() if directions[c["cell"]][p]=="output")
    external=set(d+[ports[p] for p in ("reset","in_req","out_ack")])
    require(not (external & drivers.keys()), "NATIVE_BOUNDARY_DRIVER")
    require(all(v==1 for v in drivers.values()), "NATIVE_MULTIPLE_DRIVERS")
    require(all(n in external or n in drivers or n in ("0","vdd") for c in cells
                for p,n in c["pins"].items() if directions[c["cell"]][p]=="input"), "NATIVE_UNDRIVEN_NODE")
    signals={k:top[stage["cells"]["ca_primitive_"+k]["connections"]["q"][0]]
             for k in sorted(OWNERS[variant]-{"payload"})}
    phase={}
    if variant=="click":
        flops=[c for c in cells if c["path"].startswith("ca_primitive_input_phase/") and c["cell"]==SC+"dffrnq_1"]
        require(len(flops)==1,"NATIVE_PHASE_REGISTER")
        phase={p:dict(node=flops[0]["pins"][p],pin=flops[0]["path"]+"/"+p) for p in ("D","CLK","Q")}
    result=dict(variant=variant,module=module,cells=cells,aliases=aliases,cuts=cut,ports=ports,
                d=d,q=q,captures=dict(sorted(captures.items())),signals=signals,phase=phase,limits=LIMITS,
                physical_qualification=False)
    if descriptor:
        result.update(expected_bindings=descriptor["expected_bindings"],verify_roots=list(descriptor["expected_bindings"]))
    return result


def wave(initial, events, voltage, ramp):
    points=[f"0 {initial*voltage}"]
    old=initial
    for time,value in events:
        require(time>0 and value in (0,1), "NATIVE_STIMULUS")
        if value != old: points.extend([f"{time}n {old*voltage}",f"{time+ramp}n {value*voltage}"])
        old=value
    return "PWL("+" ".join(points)+")"


def stimuli(variant,order):
    req=[(500,1),(2200,0)]
    ack=[(1400,1),(3100,0)]
    if variant=="bd":
        req=[(500,1),(1000,0),(2200,1),(2700,0)]
        ack=[(1400,1),(1800,0),(3100,1),(3500,0)]
        if order=="output_first":
            req=[(500,1),(1400,0),(2200,1),(3100,0)]
            ack=[(1000,1),(1200,0),(2700,1),(2900,0)]
    return (("reset",1,[(200,0)]),("in_req",0,req),("out_ack",0,ack))


def deck(plan,pdk,corner,ramp,order,path,fault=None,step=2,mesh=None):
    _,model,temp,voltage=corner
    orders={m[0]:m[1].split() for m in re.findall(r'^\.SUBCKT\s+(\S+)\s+([^\r\n]+)',
            (pdk/"gf180mcu_fd_sc_mcu7t5v0.spice").read_text(),re.M|re.I)}
    text=f"Uncut mapped {plan['variant']} Control capture\n"
    text+=f'.include "{linux(pdk/"design.ngspice")}"\n.lib "{linux(pdk/"sm141064.ngspice")}" {model}\n'
    text+=f'.include "{linux(pdk/"gf180mcu_fd_sc_mcu7t5v0.spice")}"\n'
    text+=f'.param sw_stat_global=0 sw_stat_mismatch=0\n.temp {temp}\nVDD vdd 0 {voltage}\n'
    first_capture=next(iter(plan["captures"]))
    for i,c in enumerate(plan["cells"]):
        pins=dict(c["pins"],VDD="vdd",VNW="vdd",VPW="0",VSS="0")
        require(set(pins)==set(orders[c["cell"]]),"NATIVE_SPICE_PIN_SET")
        if fault=="capture_disconnect" and c["path"]+"/"+("E" if plan["variant"]=="bd" else "CLK") in plan["captures"][first_capture]:
            pins["E" if plan["variant"]=="bd" else "CLK"]="vdd" if plan["variant"]=="bd" else "0"
        text+='X'+str(i)+' '+" ".join(pins[p] for p in orders[c["cell"]])+" "+c["cell"]+"\n"
    p=plan["ports"]
    for name,initial,events in stimuli(plan["variant"],order):
        text+=f'V{name} {p[name]} 0 '+wave(initial,events,voltage,ramp)+"\n"
    if mesh:
        require(mesh in (.05,.025),"NATIVE_MESH_STEP")
        require(all("numerical_mesh" not in c["pins"].values() for c in plan["cells"]),"NATIVE_MESH_CONNECTED")
        # Isolated numerical instrumentation only: PWL knots force integration
        # breakpoints near external events. Nothing connects this node to DUT.
        points={0}
        for _,_,events in stimuli(plan["variant"],order):
            for start,_ in events:
                points.update(round(start-1+i*mesh,6) for i in range(round(301/mesh)+1))
        text+='Vnumerical_mesh numerical_mesh 0 PWL('+" ".join(f'{t}n {i%2*1e-12}' for i,t in enumerate(sorted(points)))+')\n'
    for i,n in enumerate(plan["d"]):
        value=1
        # D reuse is deliberately after a measured local ACK; no upstream source
        # timing is inferred from this ideal stimulus.
        text+=f'VD{i} {n} 0 '+wave(0,[(400,value),(850,1-value),(2550,value)],voltage,ramp)+"\n"
    for i,n in enumerate(plan["q"]+[p["in_ack"],p["out_req"]]): text+=f'CQ{i} {n} 0 0.05p\n'
    trace=list(dict.fromkeys(list(p.values())+list(plan["signals"].values())+list(plan["captures"])+
                            [v["node"] for v in plan["phase"].values()]))
    text+='.save '+" ".join("v("+n+")" for n in sorted(set(trace+plan["q"])))+"\n"
    text+=f'.tran {step}n 3800n\n'
    # Both captured values and retention after ideal source reuse, before release.
    for i,n in enumerate(plan["q"]):
        for j,time in enumerate((800,950,2500,2650)):
            text+=f'.meas tran q{i}t{j} FIND v({n}) AT={time}n\n'
        for j,(begin,end) in enumerate(((800,950),(2500,2650))):
            for op in ("MIN","MAX"):
                text+=f'.meas tran q{i}{op.lower()}{j} {op} v({n}) FROM={begin}n TO={end}n\n'
    text+='.control\nset klu\nset num_threads=1\nset wr_singlescale\nset wr_vecnames\nrun\n'
    text+='wrdata '+linux(path.with_suffix('.trace'))+' '+" ".join('v('+n+')' for n in trace)+'\nquit\n.endc\n.end\n'
    path.write_text(text)
    return trace


def crossings(times,values,threshold):
    result=[]
    for i in range(1,len(times)):
        a,b=values[i-1],values[i]
        if (a<threshold<=b) or (a>threshold>=b):
            t=times[i-1]+(times[i]-times[i-1])*(threshold-a)/(b-a)
            result.append((t, "rise" if b>a else "fall"))
    return result


def read_trace(path,nodes):
    lines=path.read_text().splitlines()
    require(lines and lines[0].split()==["time"]+[f"v({n})" for n in nodes],"NATIVE_TRACE_HEADER")
    columns=[[] for _ in range(len(nodes)+1)]
    for line in lines[1:]:
        row=list(map(float,line.split()))
        require(len(row)==len(columns) and all(map(math.isfinite,row)),"NATIVE_TRACE_ROW")
        for c,x in zip(columns,row): c.append(x)
    times=[x*1e9 for x in columns[0]]
    require(len(times)>100 and times[0]==0 and times[-1]>=3800 and all(b>a for a,b in zip(times,times[1:])),"NATIVE_TRACE_TIME")
    return times,dict(zip(nodes,columns[1:]))


def evaluate(plan,corner,ramp,order,log,trace_path,nodes):
    voltage=corner[3]
    matches=re.findall(r'^(q\d+(?:t|min|max)\d+)\s*=\s*(\S+)',log,re.M)
    values={k:float(v) for k,v in matches}
    require(len(values)==len(matches)==2520 and all(map(math.isfinite,values.values())),"NATIVE_Q_MEASUREMENTS")
    expected_keys={f"q{i}t{j}" for i in range(315) for j in range(4)}
    expected_keys|={f"q{i}{op}{j}" for i in range(315) for op in ("min","max") for j in range(2)}
    require(set(values)==expected_keys,"NATIVE_Q_KEYS")
    times,signals=read_trace(trace_path,nodes)
    issues=[]
    for name,initial,events in stimuli(plan["variant"],order):
        observed=crossings(times,signals[plan["ports"][name]],voltage*.5)
        expected=[(t+ramp/2,"rise" if v else "fall") for t,v in events]
        if len(observed)!=len(expected) or any(e!=ee or abs(t-et)>.01 for (t,e),(et,ee) in zip(observed,expected)) or abs(signals[plan["ports"][name]][0]-initial*voltage)>.01*voltage:
            issues.append(dict(id="NATIVE_STIMULUS_MISMATCH",signal=name))
    for i in range(315):
        for j in range(4):
            expected=1 if j<2 else 0
            v=values[f"q{i}t{j}"]
            if not (-.1*voltage<=v<=1.1*voltage and (v>.9*voltage if expected else v<.1*voltage)):
                issues.append(dict(id="NATIVE_PAYLOAD_RETENTION",lane=i,sample=j,volts=v))
        for j in range(2):
            lo,hi=(values[f"q{i}{op}{j}"] for op in ("min","max"))
            require(lo<=hi,"NATIVE_Q_REVERSED_BOUNDS")
            if not (-.1*voltage<=lo<=hi<=1.1*voltage and (lo>.9*voltage if j==0 else hi<.1*voltage)):
                issues.append(dict(id="NATIVE_PAYLOAD_GLITCH",lane=i,transaction=j,minimum_volts=lo,maximum_volts=hi))
    edges={n:crossings(times,v,voltage*.5) for n,v in signals.items()}
    brackets=[]
    for n,vs in signals.items():
        for fraction in (.3,.5,.7):
            threshold=voltage*fraction
            for i in range(1,len(times)):
                if times[i]<300:continue
                a,b=vs[i-1:i+1]
                if (a<threshold<=b) or (a>threshold>=b):
                    gap=times[i]-times[i-1]
                    brackets.append(gap)
                    if gap>.051:issues.append(dict(id="NATIVE_EDGE_UNRESOLVED",node=n,threshold=fraction,bracket_ns=[times[i-1],times[i]],gap_ns=gap))
    for n in list(plan["captures"])+list(plan["signals"].values()):
        expected=1 if n in plan["captures"] and plan["variant"]=="bd" else 0
        for begin,end in ((350,390),(3600,3700)):
            selected=[v for t,v in zip(times,signals[n]) if begin<=t<=end]
            require(selected,"NATIVE_SETTLED_WINDOW_EMPTY")
            if not all(-.1*voltage<=v<=1.1*voltage and (v>.9*voltage if expected else v<.1*voltage) for v in selected):
                issues.append(dict(id="NATIVE_UNSETTLED_CONTROL",node=n,window_ns=[begin,end]))
    events={}
    # Ignore the explicit POR interval only; extra idle/return captures still fail.
    for node in plan["captures"]:
        active=[(t,e) for t,e in edges[node] if t>300]
        expected=["fall","rise","fall","rise"] if plan["variant"]=="bd" else ["rise","fall","rise","fall"]
        if [e for _,e in active]!=expected:
            issues.append(dict(id="NATIVE_CAPTURE_SEQUENCE",node=node,events=active))
        else: events[node]=active
    ack=[(t,e) for t,e in edges[plan["ports"]["in_ack"]] if t>300]
    offer=[(t,e) for t,e in edges[plan["ports"]["out_req"]] if t>300]
    expected=["rise","fall","rise","fall"] if plan["variant"]=="bd" else ["rise","fall"]
    for name,series in (("ack",ack),("offer",offer)):
        if [e for _,e in series]!=expected: issues.append(dict(id="NATIVE_HANDSHAKE_SEQUENCE",signal=name,events=series))
    if [e for _,e in ack]==expected and [e for _,e in offer]==expected:
        req=edges[plan["ports"]["in_req"]]; downstream=edges[plan["ports"]["out_ack"]]
        if plan["variant"]=="bd":
            legal=len(req)==len(downstream)==4
            if legal:
                legal=all(req[2*i][0]<ack[2*i][0]<req[2*i+1][0]<ack[2*i+1][0] and
                          offer[2*i][0]<downstream[2*i][0]<offer[2*i+1][0]<downstream[2*i+1][0]
                          for i in range(2)) and ack[1][0]<req[2][0] and downstream[1][0]<req[2][0]
        else:
            legal=len(req)==len(downstream)==2
            if legal:legal=all(req[i][0]<ack[i][0] and offer[i][0]<downstream[i][0] for i in range(2)) and max(ack[0][0],downstream[0][0])<req[1][0]
        if not legal:issues.append(dict(id="NATIVE_ILLEGAL_ENVIRONMENT"))
    metrics={}
    if len(events)==20 and [e for _,e in ack]==expected and [e for _,e in offer]==expected:
        rows=[]
        for tx,start in enumerate((500+ramp/2,2200+ramp/2)):
            capture=[v[tx*2][0] for v in events.values()]
            a=ack[tx*(2 if plan["variant"]=="bd" else 1)][0]
            o=offer[tx*(2 if plan["variant"]=="bd" else 1)][0]
            row=dict(transaction=tx,request_to_first_capture_ns=min(capture)-start,
                request_to_last_capture_ns=max(capture)-start,capture_spread_ns=max(capture)-min(capture),
                local_ack_after_last_capture_ns=a-max(capture),offer_after_last_capture_ns=o-max(capture),
                local_ack_ns=a,minimum_closed_or_pulse_ns=min(v[tx*2+1][0]-v[tx*2][0] for v in events.values()))
            rows.append(row)
            if a<=max(capture): issues.append(dict(id="NATIVE_ACK_BEFORE_CAPTURE",transaction=tx))
            if o<=max(capture): issues.append(dict(id="NATIVE_OFFER_BEFORE_CAPTURE",transaction=tx))
            if not start<min(capture)<=max(capture)<(850 if tx==0 else 2550): issues.append(dict(id="NATIVE_CAPTURE_WINDOW",transaction=tx))
            if not max(capture)<a<(850 if tx==0 else 2550): issues.append(dict(id="NATIVE_SOURCE_REUSE_WINDOW",transaction=tx))
            if row["minimum_closed_or_pulse_ns"]<1.8: issues.append(dict(id="NATIVE_CAPTURE_PULSE",transaction=tx))
        metrics["transactions"]=rows
    slew=[]
    for n in dict.fromkeys(list(plan["captures"])+list(plan["signals"].values())+[v["node"] for v in plan.get("phase",{}).values()]):
        low=crossings(times,signals[n],voltage*.3); high=crossings(times,signals[n],voltage*.7)
        for t,e in edges[n]:
            if t<=300: continue
            before=low if e=="rise" else high
            after=high if e=="rise" else low
            a=[x for x,d in before if d==e and x<=t]; b=[x for x,d in after if d==e and x>=t]
            require(a and b,"NATIVE_SLEW_CROSSING")
            value=min(b)-max(a); slew.append(dict(node=n,edge=e,time_ns=t,slew_ns=value))
            if value>2: issues.append(dict(id="NATIVE_SLEW_LIMIT",node=n,edge=e,time_ns=t,slew_ns=value))
    metrics["maximum_observed_slew_ns"]=max(x["slew_ns"] for x in slew)
    if plan.get("phase"):
        phase_edges={k:[(t,e) for t,e in edges[v["node"]] if t>300] for k,v in plan["phase"].items()}
        if [e for _,e in phase_edges["CLK"]]!=["rise","fall","rise","fall"] or [e for _,e in phase_edges["Q"]]!=["rise","fall"]:
            issues.append(dict(id="NATIVE_PHASE_SEQUENCE",events=phase_edges))
        else:
            metrics["phase_clock_to_q_ns"]=[phase_edges["Q"][i][0]-phase_edges["CLK"][2*i][0] for i in range(2)]
            metrics["phase_high_pulse_ns"]=[phase_edges["CLK"][2*i+1][0]-phase_edges["CLK"][2*i][0] for i in range(2)]
            if min(metrics["phase_high_pulse_ns"])<1.8:issues.append(dict(id="NATIVE_PHASE_PULSE"))
            if any(x<=0 for x in metrics["phase_clock_to_q_ns"]):issues.append(dict(id="NATIVE_PHASE_CAUSALITY"))
    metrics["provisional_capture_pulse_floor_ns"]=1.8
    metrics["maximum_edge_bracket_ns"]=max(brackets)
    return dict(status="numerically-unresolved" if any(x["id"]=="NATIVE_EDGE_UNRESOLVED" for x in issues) else
                "observed-violations" if issues else "conditional-schematic-observations-pass",
                metrics=metrics,issues=issues,slews=slew,events=edges,physical_qualification=False,limits=LIMITS)


def simulate(path,pdk,mesh):
    """Stream diagnostic output to disk, including when either timeout fires."""
    seconds=600 if mesh else 180
    log_path=path.with_suffix(".log")
    with log_path.open("w") as stream:
        try:
            process=subprocess.run(["wsl","--cd",linux(pdk),"-e","timeout","--signal=TERM","--kill-after=5s",
                str(seconds)+"s","ngspice","-n","-b",linux(path)],stdout=stream,stderr=subprocess.STDOUT,
                text=True,timeout=seconds+15)
        except subprocess.TimeoutExpired as error:
            stream.flush()
            path.with_suffix(".timeout.txt").write_text(str(error))
            raise
    log=log_path.read_text()
    require(process.returncode==0 and "Error:" not in log,"NATIVE_SPICE_FAILED_"+path.stem)
    return log


def run(mapping,out,variant,pdk,pilot=True,fault=None,step=2,mesh=None,only_order=None):
    pdk_verify(pdk)
    out.mkdir(parents=True,exist_ok=False)
    sources=[ROOT/"tools"/n for n in ("characterize_gf180_control_native.py","characterize_gf180_keeper.py",
        "gf180_physical.py","gf180_estimate.py","repair_gf180_control.py","characterize_gf180_liberty.py")]
    sources += [mapping/"netlist.json",mapping/"mapping.json",ROOT/"physical/gf180/pdk-lock.json"]
    before={str(p.resolve()):sha(p) for p in sources}
    netlist=json.loads((mapping/"netlist.json").read_text())
    plan=extract(netlist,variant)
    audit_bindings(netlist,json.loads((mapping/"mapping.json").read_text()),plan)
    write_json(out/"plan.json",dict(plan,source_sha256=before))
    version=subprocess.run(["wsl","-e","ngspice","--version"],capture_output=True,text=True,timeout=15)
    require(version.returncode==0,"NATIVE_SPICE_UNAVAILABLE")
    (out/"ngspice-version.log").write_text(version.stdout+version.stderr)
    executable=subprocess.run(["wsl","-e","sh","-c","sha256sum $(command -v ngspice)"],capture_output=True,text=True,timeout=15)
    require(executable.returncode==0 and re.fullmatch(r"[0-9a-f]{64}\s+\S+\s*",executable.stdout),"NATIVE_SPICE_HASH")
    (out/"ngspice-sha256.log").write_text(executable.stdout)
    cases=[]
    for corner in CORNERS[:1] if pilot else CORNERS:
        for ramp in ([0.2] if pilot else [0.02,2.0]):
            for order in (["input_first","output_first"] if variant=="bd" else ["phase_pair"]):
                if only_order and order!=only_order:continue
                name=f"{corner[0]}-r{ramp}-{order}"; path=out/(name+".spice")
                nodes=deck(plan,pdk,corner,ramp,order,path,fault,step,mesh)
                log=simulate(path,pdk,mesh)
                result=evaluate(plan,corner,ramp,order,log,path.with_suffix('.trace'),nodes)
                result.update(name=name,corner=corner,ramp_ns=ramp,order=order,fault=fault,maximum_step_ns=step,mesh_step_ns=mesh,
                    evidence_sha256={p.name:sha(p) for p in (path,path.with_suffix('.trace'),out/(name+".log"))})
                write_json(out/(name+".json"),result); cases.append(result)
                print(name,result["status"],result["metrics"],flush=True)
    require(cases,"NATIVE_NO_CASES")
    pdk_verify(pdk)
    require(before=={str(p.resolve()):sha(p) for p in sources},"NATIVE_SOURCE_CHANGED")
    executable_after=subprocess.run(["wsl","-e","sh","-c","sha256sum $(command -v ngspice)"],capture_output=True,text=True,timeout=15)
    require(executable_after.returncode==0 and executable_after.stdout==executable.stdout,"NATIVE_SPICE_CHANGED")
    write_json(out/"results.json",dict(cases=cases,source_sha256=before,tool_sha256=executable.stdout,
        physical_qualification=False,limits=LIMITS,plan_sha256=sha(out/"plan.json")))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mapping",type=Path); p.add_argument("output",type=Path)
    p.add_argument("--variant",choices=OWNERS,required=True)
    p.add_argument("--pdk",type=Path,default=ROOT/".tools/physical/pdk")
    cohort=p.add_mutually_exclusive_group()
    cohort.add_argument("--pilot",dest="pilot",action="store_true",default=True,help="bounded TT pilot (default)")
    cohort.add_argument("--campaign",dest="pilot",action="store_false",help="explicit five-corner/two-slew campaign; establish pilot convergence first")
    p.add_argument("--fault",choices=["capture_disconnect"])
    p.add_argument("--step-ns",type=int,choices=[1,2],default=2)
    p.add_argument("--mesh-step-ns",type=float,choices=[.05,.025])
    p.add_argument("--only-order",choices=["input_first","output_first","phase_pair"])
    a=p.parse_args();run(a.mapping.resolve(),a.output.resolve(),a.variant,a.pdk.resolve(),a.pilot,a.fault,a.step_ns,a.mesh_step_ns,a.only_order)
