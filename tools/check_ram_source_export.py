# SPDX-License-Identifier: Apache-2.0
"""Closed digital policy for native RAM reservations; no physical signoff claim."""
import re

ARM_PATH = "RAM reservation phase before eligibility arm"
RETIRE_PATH = "RAM selected publication and reservation phase feedback before retirement"


def validate_ram_source(node):
    if not re.fullmatch(r"(?:FourPhase|Click)RamSource(?:_[0-9]+)?", node["module"]):
        raise ValueError("RAM_SOURCE_OWNER")
    click=node["module"].startswith("Click")
    protocol="two-phase-bundled-v1" if click else "four-phase-bundled-v1"
    if (node["capacity"] != 1 or len(node["channels"]) != 4 or
        {c["id"]:(c["protocol"],c["role"]) for c in node["channels"]} !=
        {n:(protocol,"output" if n=="grant" else "input") for n in ("reserve","grant","decision","publication")} or
        any(c["layout"] != [dict(field="bits",lsb=0,width=1,signed=False,
            source=f"~|{node['module']}>{c['id']}.bits")] for c in node["channels"])):
        raise ValueError("RAM_SOURCE_SCHEMA")
    if (len(node["children"]) != 1 or node["children"][0]["id"] != "reservation" or
        not re.fullmatch(("ClickBuffer" if click else "LongHoldBuffer")+r"(?:_[0-9]+)?",
            node["children"][0]["contract"]["module"]) or node["children"][0]["contract"]["capacity"] != 1):
        raise ValueError("RAM_SOURCE_STORAGE")
    widths={n+"_"+f:1 for n in ("reserve","grant","decision","publication") for f in ("request","data","acknowledge")}
    widths.update({n:1 for n in ("reset","eligibility_reset","application_reset","word_drained","eligible","idle","reserved")})
    if click: widths.update(arm_data=1,arm_event=1,armed=1,retire_sources=5,register_data=3,capture_event=1,captured=3)
    if len(node["endpoints"]) != len(widths) or {e["id"]:e["width"] for e in node["endpoints"]} != widths:
        raise ValueError("RAM_SOURCE_ENDPOINTS")
    timings={t["id"]:t for t in node["timing"]}
    expected={"arm_path","arm_aperture","retirement_path","retirement_aperture"} if click else set()
    if len(node["timing"]) != len(expected) or set(timings) != expected:
        raise ValueError("RAM_SOURCE_TIMING")
    if click:
        for name,logic,source,sink,cell in (("arm_path",ARM_PATH,"reserved","arm_data","arm_data_delay"),
                ("retirement_path",RETIRE_PATH,"retire_sources","register_data","data_delay")):
            expected=dict(kind="bundled-data-path-v1",logic=logic,source=source,sink=sink,delay_owner=[],delay_cell=cell,
                          logic_model_fs="0",budget=dict(min_fs="10000000",max_fs="10000000",model_fs="10000000"))
            if any(timings[name].get(k)!=v for k,v in expected.items()): raise ValueError("RAM_SOURCE_PATH")
        for name,launch,transaction,data,capture,captured in (
            ("arm_aperture","reserved","reserved","arm_data","arm_event","armed"),
            ("retirement_aperture","decision_request","decision_data","register_data","capture_event","captured")):
            expected=dict(kind="bundled-setup-hold-v1",launch=launch,transaction=transaction,data_valid=data,
                          capture=capture,captured=captured,setup_fs="100000",hold_fs="100000")
            if any(timings[name].get(k)!=v for k,v in expected.items()): raise ValueError("RAM_SOURCE_APERTURE")
    cells={p["id"]:p for p in node["primitives"]}; expected={}
    def cell(name,model,**params): expected[name]=("ChiselAsync"+model+"_v1",{k:str(v) for k,v in params.items()})
    def gate(name,width=1,op=0,delay=1000000,initial=0):
        cell(name,"ControlGate",WIDTH=width,OP=op,DELAY_FS=delay,RESET_VALUE=initial)
    def and_gate(name):
        gate(name+"_na",op=1,initial=1);gate(name+"_nb",op=1,initial=1)
        gate(name+"_or",op=2,initial=1);gate(name,op=1)
    def phase(name): cell(name,"EventRegister",WIDTH=1,DELAY_FS=1000000,RESET_VALUE=0)
    phase("eligibility");gate("request_guard",delay=11000000)
    gate("output_guard",delay=221200001 if click else 200000000)
    gate("acknowledge_guard",width=3 if click else 1,delay=221200001 if click else 200000000)
    if click:
        for n in ("armed_phase","retired_phase","decision_phase","publication_phase"): phase(n)
        for n in ("arm_pending","owned","decision_pending","publication_pending"):cell(n,"Xor",DELAY_FS=1000000)
        gate("arm_data_delay",delay=10000000);gate("data_delay",width=3,delay=10000000)
        gate("request_delay",width=6,delay=11000000)
        gate("return_guard",delay=221200001)
        for n in ("source_ready","effect_ready","ownership_ready","settled","retire_fire"): and_gate(n)
    else:
        and_gate("publication_ack")
        for n,r,f in (("retirement",5,2),("reservation_return",0,3)):
            cell(n,"AsymmetricC",COMMON=1,RISING=r,FALLING=f,DELAY_FS=1000000,RESET_VALUE=0,
                 COMMON_INVERT=0,RISING_INVERT=0,FALLING_INVERT=0)
    markers={t["marker"] for t in node["timing"]}
    if len(cells)!=len(node["primitives"]) or set(cells)!=set(expected)|markers:
        raise ValueError("RAM_SOURCE_CELL_INVENTORY")
    for name,(model,params) in expected.items():
        actual=cells[name]
        if actual["model"]!=model or actual["parameters"]!=params:
            raise ValueError("RAM_SOURCE_CELL_POLICY:"+name)
    for name,c in cells.items():
        if c["reset"] != ("eligibility_reset" if name=="eligibility" else "reset"):
            raise ValueError("RAM_SOURCE_RESET_OWNER:"+name)
        if name in markers and c["model"]!="ChiselAsyncTimingMarker_v1":raise ValueError("RAM_SOURCE_MARKER")
    return click


def ram_source_bindings(node):
    click=validate_ram_source(node)
    e={x["id"]:x["rtl_path"] for x in node["endpoints"]}
    c={x["id"]:x["rtl_path"] for x in node["primitives"]}
    r={x["id"]:x["rtl_path"] for x in node["children"][0]["contract"]["endpoints"]}
    cat=lambda xs:"{"+",".join(xs)+"}"
    pairs=[(e["eligibility_reset"],f"({e['reset']} | {e['application_reset']})"),
        (c["eligibility"]+".reset",e["eligibility_reset"]),(c["eligibility"]+".d","1'b1"),
        (e["eligible"],c["eligibility"]+".q"),(e["reserved"],r["in_acknowledge"]),
        (e["reserve_request"],r["in_request"]),(e["reserve_data"],r["in_data"]),
        (e["grant_data"],r["out_data"]),(e["grant_acknowledge"],r["out_acknowledge"]),
        (e["grant_request"],c["output_guard"]+".q"),(r["out_request"],c["output_guard"]+".a")]
    if click:
        pairs += [(e["reserved"],c["arm_pending"]+".a"),(c["armed_phase"]+".q",c["arm_pending"]+".b"),
            (c["arm_pending"]+".q",c["request_guard"]+".a"),(c["request_guard"]+".q",e["arm_event"]),
            (e["reserved"],c["arm_data_delay"]+".a"),(c["arm_data_delay"]+".q",e["arm_data"]),
            (e["arm_data"],c["armed_phase"]+".d"),(e["armed"],c["armed_phase"]+".q"),
            (e["arm_event"],c["armed_phase"]+".trigger"),(e["arm_event"],c["eligibility"]+".trigger"),
            (e["reserved"],c["owned"]+".a"),(c["retired_phase"]+".q",c["owned"]+".b")]
        pairs += [(e["decision_request"],c["return_guard"]+".a"),
            (c["return_guard"]+".q",c["decision_pending"]+".a"),
            (c["decision_phase"]+".q",c["decision_pending"]+".b"),
            (e["publication_request"],c["publication_pending"]+".a"),
            (c["publication_phase"]+".q",c["publication_pending"]+".b")]
        parts=[c["owned"]+".q",c["decision_pending"]+".q",f"(!{e['decision_data']} || {c['publication_pending']}.q)",
            e["word_drained"],f"({e['grant_request']} == {e['reserved']} && {e['grant_acknowledge']} == {e['reserved']})",
            f"({e['armed']} == {e['reserved']})"]
        pairs += [(cat(parts),c["request_delay"]+".a")]
        for name,a,b in (("source_ready",c["request_delay"]+".q[0]",c["request_delay"]+".q[1]"),
                         ("effect_ready",c["request_delay"]+".q[2]",c["request_delay"]+".q[3]"),
                         ("ownership_ready",c["request_delay"]+".q[4]",c["request_delay"]+".q[5]"),
                         ("settled",c["source_ready"]+".q",c["effect_ready"]+".q"),
                         ("retire_fire",c["settled"]+".q",c["ownership_ready"]+".q")):
            pairs += [(a,c[name+"_na"]+".a"),(b,c[name+"_nb"]+".a")]
        mux=f"({e['decision_data']} ? {e['publication_request']} : {c['publication_phase']}.q)"
        pairs += [(cat([mux,e["decision_request"],e["reserved"]]),c["data_delay"]+".a"),
            (cat([e["decision_data"],e["publication_request"],e["decision_request"],e["reserved"],c["publication_phase"]+".q"]),e["retire_sources"]),
            (e["register_data"],c["data_delay"]+".q"),(e["capture_event"],c["retire_fire"]+".q")]
        for bit,(phase,port) in enumerate((("retired_phase","reserve"),("decision_phase","decision"),("publication_phase","publication"))):
            pairs += [(e["register_data"]+f"[{bit}]",c[phase]+".d"),(e["capture_event"],c[phase]+".trigger"),
                (c[phase]+".q",e["captured"]+f"[{bit}]"),(c[phase]+".q",c["acknowledge_guard"]+f".a[{bit}]"),
                (e[port+"_acknowledge"],c["acknowledge_guard"]+f".q[{bit}]")]
        idle=" && ".join(f"({e[n+'_request']} == {e[n+'_acknowledge']})" for n in ("reserve","decision","publication","grant"))
        idle+=f" && ({e['reserved']} == {e['reserve_acknowledge']}) && !{e['capture_event']} && !{e['arm_event']}"
        prefixes=("source_ready","effect_ready","ownership_ready","settled","retire_fire")
    else:
        pairs += [(e["reserved"],c["eligibility"]+".trigger"),(e["decision_request"],c["request_guard"]+".a"),
            (e["reserve_request"],c["retirement"]+".common"),
            (cat([e["reserved"],c["request_guard"]+".q",f"(!{e['decision_data']} || {e['publication_request']})",
                  e["word_drained"],f"(!{e['grant_request']} && !{e['grant_acknowledge']})"]),c["retirement"]+".rising"),
            (cat([e["decision_request"],f"({e['decision_data']} && {e['publication_request']})"]),c["retirement"]+".falling"),
            (e["decision_acknowledge"],c["retirement"]+".q"),(c["retirement"]+".q",c["publication_ack_na"]+".a"),
            (e["decision_data"],c["publication_ack_nb"]+".a"),(e["publication_acknowledge"],c["publication_ack"]+".q"),
            (c["retirement"]+".q",c["reservation_return"]+".common"),("1'b1",c["reservation_return"]+".rising"),
            (cat([e["decision_acknowledge"],e["publication_acknowledge"],e["reserved"]]),c["reservation_return"]+".falling"),
            (c["reservation_return"]+".q",c["acknowledge_guard"]+".a"),(e["reserve_acknowledge"],c["acknowledge_guard"]+".q")]
        idle=" && ".join("!"+e[n+"_"+f] for n in ("reserve","decision","publication","grant") for f in ("request","acknowledge"))+" && !"+e["reserved"]
        prefixes=("publication_ack",)
    pairs.append((e["idle"],"("+idle+")"))
    for n in prefixes:
        pairs += [(c[n+"_na"]+".q",c[n+"_or"]+".a"),(c[n+"_nb"]+".q",c[n+"_or"]+".b"),(c[n+"_or"]+".q",c[n]+".a")]
    return pairs


def ram_source_probe(source,manifest,scopes):
    pairs=[]
    def visit(node):
        nonlocal source
        if re.fullmatch(r"(?:FourPhase|Click)RamSource(?:_[0-9]+)?",node["module"]):
            pairs.extend(ram_source_bindings(node))
            e={x["id"]:x["rtl_path"] for x in node["endpoints"]}
            cell=next(p["rtl_path"] for p in node["primitives"] if p["id"]=="eligibility")
            # The library assumes every primitive uses its parent's reset.
            # Replace that assumption only for this validated cancellation cell;
            # require its exact POR OR application reset equation at every step.
            old=f'if ({cell}.reset !== {e["eligibility_reset"]} || {e["eligibility_reset"]} !== {node["rtl_path"]}.reset) $fatal(1, "RESET_BINDING_MISMATCH");'
            new=f'if ({cell}.reset !== {e["eligibility_reset"]} || {e["eligibility_reset"]} !== ({e["reset"]} | {e["application_reset"]})) $fatal(1, "RESET_BINDING_MISMATCH");'
            if source.count(old)!=1:raise ValueError("RAM_SOURCE_RESET_PROBE_SHAPE")
            source=source.replace(old,new)
        for c in node["children"]:visit(c["contract"])
    visit(manifest["design"])
    top=manifest["top"]
    if top in ("FourPhaseSoc","ClickSoc"):
        cs={c["id"]:c["contract"] for c in manifest["design"]["children"]}
        names={"ram_source"}|{"ram_"+n+"_bridge" for n in ("reserve","grant","decision","publication")}
        if not names<=cs.keys():raise ValueError("RAM_SOURCE_SOC_INVENTORY")
        click=top=="ClickSoc"; prefix="Click" if click else "FourPhase"
        if not re.fullmatch(prefix+r"RamSource(?:_[0-9]+)?",cs["ram_source"]["module"]):raise ValueError("RAM_SOURCE_SOC_OWNER")
        e={x["id"]:x["rtl_path"] for x in cs["ram_source"]["endpoints"]}
        for name in ("reserve","grant","decision","publication"):
            n=cs["ram_"+name+"_bridge"];output=name=="grant"
            model=("ClickToDecoupled" if click else "FourPhaseToDecoupled") if output else ("DecoupledToClick" if click else "DecoupledToFourPhase")
            protocol="two-phase-bundled-v1" if click else "four-phase-bundled-v1"
            if (not re.fullmatch(model+r"(?:_[0-9]+)?",n["module"]) or
                {c["id"]:(c["protocol"],c["role"]) for c in n["channels"]} !=
                {"in":(protocol if output else "decoupled-v1","input"),"out":("decoupled-v1" if output else protocol,"output")} or
                any(c["layout"] != [dict(field="bits",lsb=0,width=1,signed=False,source=f"~|{n['module']}>{c['id']}.bits")] for c in n["channels"])):
                raise ValueError("RAM_SOURCE_BRIDGE_SCHEMA")
            b={x["id"]:x["rtl_path"] for x in n["endpoints"]}
            pairs += [(e[name+"_"+f],b[("in_" if output else "out_")+f]) for f in ("request","data","acknowledge")]
        pairs += [(e["application_reset"],top+".systemReset"),(e["word_drained"],"!"+cs["ram_access"]["rtl_path"]+".io_busy")]
    anchor="task check; begin"
    if source.count(anchor)!=1:raise ValueError("RAM_SOURCE_PROBE_SHAPE")
    comparisons=[f'if ({a} !== {b}) $fatal(1,"RAM_SOURCE_BINDING:{a}");' for a,b in pairs]
    return source.replace(anchor,anchor+"\n"+"\n".join(comparisons))
