# SPDX-License-Identifier: Apache-2.0
"""Closed policy for native program ownership and loader Stored delivery."""
import re

PROGRAM_ARM_PATH = "program reservation phase before eligibility arm"
PROGRAM_RETIRE_PATH = "program selected publication and reservation phase feedback before retirement"
PROGRAM_STORED_PATH = "Program Stored target before native issue and phase feedback"
PROGRAM_PATHS = (PROGRAM_ARM_PATH, PROGRAM_RETIRE_PATH, PROGRAM_STORED_PATH)
CHANNELS = ("reserve", "grant", "decision", "publication", "stored")


def validate_stored_receipt(node):
    if not re.fullmatch(r"(?:FourPhase|Click)StoredReceipt(?:_[0-9]+)?",node["module"]):
        raise ValueError("STORED_RECEIPT_OWNER")
    click=node["module"].startswith("Click")
    expected={"in":("two-phase-bundled-v1" if click else "four-phase-bundled-v1","input"),
              "out":("decoupled-v1","output")}
    if (node["capacity"]!=1 or len(node["channels"])!=2 or
        {c["id"]:(c["protocol"],c["role"]) for c in node["channels"]}!=expected or
        any(c["layout"]!=[dict(field="bits",lsb=0,width=1,signed=False,
            source=f"~|{node['module']}>{c['id']}.bits")] for c in node["channels"])):
        raise ValueError("STORED_RECEIPT_SCHEMA")
    ids={"in_request","in_data","in_acknowledge","out_valid","out_data","out_ready","out_clock",
         "reset","local_reset","request_meta","request_sync","acknowledge"}
    if (len(node["endpoints"])!=len(ids) or {e["id"]:e["width"] for e in node["endpoints"]}!={n:1 for n in ids}
        or node["primitives"] or node["children"] or node["timing"]):
        raise ValueError("STORED_RECEIPT_INVENTORY")
    return click


def stored_receipt_bindings(node,scopes):
    click=validate_stored_receipt(node);path=node["rtl_path"]
    regs=scopes.get(path,{}).get("registers",{})
    expected={"localReset_release_0","localReset_release_1","requestMeta","requestSync","acknowledge"}
    if regs!={n:1 for n in expected}:raise ValueError("STORED_RECEIPT_REGISTER_INVENTORY")
    e={x["id"]:x["rtl_path"] for x in node["endpoints"]}
    active=f"({e['request_sync']} != {e['acknowledge']})" if click else f"({e['request_sync']} && !{e['acknowledge']})"
    return [(e["request_meta"],path+".requestMeta"),(e["request_sync"],path+".requestSync"),
        (e["acknowledge"],path+".acknowledge"),(e["local_reset"],path+".localReset_release_1"),
        (e["out_clock"],path+".clock"),(e["in_acknowledge"],e["acknowledge"]),
        (e["out_data"],e["in_data"]),(e["out_valid"],f"({active} && !{e['local_reset']})")]


def validate_stored_receipt_rtl(node,rtl):
    """Pin the complete emitted sequential logic, not just its visible aliases.

    A changed emitter requires inspection. Count every always block and every
    nonblocking writer so an additional block cannot bypass the closed policy.
    """
    click=validate_stored_receipt(node)
    clean=lambda s:re.sub(r"\s+","",re.sub(r"/\*.*?\*/|//[^\n]*","",s,flags=re.S))
    blocks=[clean(b) for b in re.findall(r"\balways\s*@\(.*?^\s*end\s*//\s*always[^\n]*",rtl,re.S|re.M)]
    release=("always@(posedgeclockorposedgereset)beginif(reset)begin"
        "localReset_release_0<=1'h1;localReset_release_1<=1'h1;endelsebegin"
        "localReset_release_0<=1'h0;localReset_release_1<=localReset_release_0;endend")
    ack=("if(out_ready&packed_6)acknowledge<=requestSync;" if click else
         "acknowledge<=out_ready&packed_6|requestSync&acknowledge;")
    receipt=("always@(posedgeclockorposedgelocalReset)begin"
        "if(localReset)beginrequestMeta<=1'h0;requestSync<=1'h0;acknowledge<=1'h0;"
        "endelsebeginrequestMeta<=in_req;requestSync<=requestMeta;"+ack+"endend")
    uncommented=re.sub(r"/\*.*?\*/|//[^\n]*","",rtl,flags=re.S)
    writers=re.findall(r"\b(\w+)\s*<=",uncommented)
    expected={n:2 for n in ("localReset_release_0","localReset_release_1","requestMeta","requestSync","acknowledge")}
    if (blocks!=[release,receipt] or len(re.findall(r"\balways(?:_\w+)?\b",uncommented))!=2 or
        {n:writers.count(n) for n in set(writers)}!=expected):
        raise ValueError("STORED_RECEIPT_SEQUENTIAL_LOGIC")
    # CIRCT's optional simulation initializer is the only blocking state writer.
    # Close it too: an added initial/force can corrupt a register without adding
    # an always block or a nonblocking assignment.
    initial="""initial begin
      `ifdef INIT_RANDOM_PROLOG_
        `INIT_RANDOM_PROLOG_
      `endif
      `ifdef RANDOMIZE_REG_INIT
        _RANDOM[1'b0] = `RANDOM;
        localReset_release_0 = _RANDOM[1'b0][0];
        localReset_release_1 = _RANDOM[1'b0][1];
        requestMeta = _RANDOM[1'b0][2];
        requestSync = _RANDOM[1'b0][3];
        acknowledge = _RANDOM[1'b0][4];
      `endif
      if(reset) begin localReset_release_0 = 1'h1; localReset_release_1 = 1'h1; end
      if(localReset) begin requestMeta = 1'h0; requestSync = 1'h0; acknowledge = 1'h0; end
    end"""
    initials=[clean(b) for b in re.findall(r"\binitial\s+begin.*?^\s*end\s*//\s*initial[^\n]*",rtl,re.S|re.M)]
    if (initials!=[clean(initial)] or len(re.findall(r"\binitial\b",uncommented))!=1 or
        re.search(r"\b(?:force|release|final)\b",uncommented)):
        raise ValueError("STORED_RECEIPT_INITIALIZERS")
    valid="requestSync!=acknowledge&~packed_10_probe" if click else "requestSync&~acknowledge&~packed_10_probe"
    wire_drivers=re.findall(r"\bwire\s+(\w+)\s*=\s*([^;]+);",uncommented)
    wires={n:clean(v) for n,v in wire_drivers}
    continuous=[clean(s) for s in re.findall(r"\bassign\s+[^;]+;",uncommented)]
    if (len(wire_drivers)!=6 or len(re.findall(r"\bwire\b",uncommented))!=6 or
        wires!={"packed_9_probe":"clock","packed_11_probe":"reset","localReset":"localReset_release_1",
                "packed_10_probe":"localReset","packed_6":valid,"in_ack_0":"acknowledge"} or
        continuous!=["assignin_ack=in_ack_0;","assignout_valid=packed_6;","assignout_bits=in_bits;"]):
        raise ValueError("STORED_RECEIPT_COMBINATIONAL_LOGIC")


def validate_program_receipts(manifest,directory):
    def visit(node):
        if re.fullmatch(r"(?:FourPhase|Click)StoredReceipt(?:_[0-9]+)?",node["module"]):
            validate_stored_receipt_rtl(node,(directory/(node["module"]+".sv")).read_text(encoding="utf-8"))
        for child in node["children"]:visit(child["contract"])
    visit(manifest["design"])


def validate_program_source(node):
    if not re.fullmatch(r"(?:FourPhase|Click)ProgramSource(?:_[0-9]+)?", node["module"]):
        raise ValueError("PROGRAM_SOURCE_OWNER")
    click = node["module"].startswith("Click")
    protocol = "two-phase-bundled-v1" if click else "four-phase-bundled-v1"
    if (node["capacity"] != 1 or len(node["channels"]) != 5 or
        {c["id"]:(c["protocol"],c["role"]) for c in node["channels"]} !=
        {n:(protocol,"output" if n in ("grant","stored") else "input") for n in CHANNELS} or
        any(c["layout"] != [dict(field="bits",lsb=0,width=1,signed=False,
            source=f"~|{node['module']}>{c['id']}.bits")] for c in node["channels"])):
        raise ValueError("PROGRAM_SOURCE_SCHEMA")
    if (len(node["children"]) != 2 or {c["id"] for c in node["children"]} != {"reservation","stored_buffer"} or
        any(not re.fullmatch(("ClickBuffer" if click else "LongHoldBuffer")+r"(?:_[0-9]+)?", c["contract"]["module"])
            or c["contract"]["capacity"] != 1 for c in node["children"])):
        raise ValueError("PROGRAM_SOURCE_STORAGE")
    widths={n+"_"+f:1 for n in CHANNELS for f in ("request","data","acknowledge")}
    widths.update({n:1 for n in ("reset","eligibility_reset","application_reset","word_drained","eligible","idle","reserved","owner_loader")})
    if click:
        widths.update(arm_data=2,arm_event=1,armed=2,arm_sources=2,retire_sources=5,register_data=3,
            capture_event=1,captured=3,stored_target=1,stored_phase_data=1,stored_event=1,stored_issued=1)
    if len(node["endpoints"]) != len(widths) or {e["id"]:e["width"] for e in node["endpoints"]} != widths:
        raise ValueError("PROGRAM_SOURCE_ENDPOINTS")
    timings={t["id"]:t for t in node["timing"]}
    expected={"arm_path","arm_aperture","retirement_path","retirement_aperture","stored_path","stored_aperture"} if click else set()
    if len(node["timing"]) != len(expected) or set(timings) != expected:
        raise ValueError("PROGRAM_SOURCE_TIMING")
    if click:
        for name,logic,source,sink,delay in (
            ("arm_path",PROGRAM_ARM_PATH,"arm_sources","arm_data","arm_data_delay"),
            ("retirement_path",PROGRAM_RETIRE_PATH,"retire_sources","register_data","data_delay"),
            ("stored_path",PROGRAM_STORED_PATH,"stored_target","stored_phase_data","stored_data_delay")):
            policy=dict(kind="bundled-data-path-v1",logic=logic,source=source,sink=sink,delay_owner=[],delay_cell=delay,
                logic_model_fs="0",budget=dict(min_fs="10000000",max_fs="10000000",model_fs="10000000"))
            if any(timings[name].get(k)!=v for k,v in policy.items()): raise ValueError("PROGRAM_SOURCE_PATH")
        for name,launch,transaction,data,capture,captured in (
            ("arm_aperture","reserved","arm_sources","arm_data","arm_event","armed"),
            ("retirement_aperture","decision_request","decision_data","register_data","capture_event","captured"),
            ("stored_aperture","decision_request","decision_data","stored_phase_data","stored_event","stored_issued")):
            policy=dict(kind="bundled-setup-hold-v1",launch=launch,transaction=transaction,data_valid=data,
                capture=capture,captured=captured,setup_fs="100000",hold_fs="100000")
            if any(timings[name].get(k)!=v for k,v in policy.items()): raise ValueError("PROGRAM_SOURCE_APERTURE")
    cells={p["id"]:p for p in node["primitives"]}; expected={}
    def cell(name,model,**params): expected[name]=("ChiselAsync"+model+"_v1",{k:str(v) for k,v in params.items()})
    def gate(name,width=1,op=0,delay=1000000,initial=0): cell(name,"ControlGate",WIDTH=width,OP=op,DELAY_FS=delay,RESET_VALUE=initial)
    def and_gate(name):
        gate(name+"_na",op=1,initial=1);gate(name+"_nb",op=1,initial=1)
        gate(name+"_or",op=2,initial=1);gate(name,op=1)
    def phase(name,width=1): cell(name,"EventRegister",WIDTH=width,DELAY_FS=1000000,RESET_VALUE=0)
    phase("eligibility")
    gate("request_guard",delay=11000000 if click else 200000000)
    gate("output_guard",delay=241200001 if click else 200000000)
    gate("acknowledge_guard",width=3 if click else 1,delay=241200001 if click else 200000000)
    if click:
        phase("armed_phase",2)
        for n in ("retired_phase","decision_phase","publication_phase","stored_phase"): phase(n)
        for n in ("arm_pending","owned","decision_pending","publication_pending","stored_pending"):cell(n,"Xor",DELAY_FS=1000000)
        gate("arm_data_delay",width=2,delay=10000000);gate("data_delay",width=3,delay=10000000)
        gate("stored_data_delay",delay=10000000);gate("stored_request_delay",width=5,delay=11000000)
        gate("request_delay",width=7,delay=11000000);gate("return_guard",delay=241200001)
        for n in ("source_ready","effect_ready","ownership_ready","settled","retire_fire","stored_retired",
                  "stored_fire","stored_selection","stored_ownership","stored_decision"): and_gate(n)
    else:
        for n in ("publication_ack","stored_offer","stored_selected"): and_gate(n)
        for n,r,f in (("retirement",6,2),("reservation_return",0,7),("stored_accepted",1,0)):
            cell(n,"AsymmetricC",COMMON=1,RISING=r,FALLING=f,DELAY_FS=1000000,RESET_VALUE=0,
                COMMON_INVERT=0,RISING_INVERT=0,FALLING_INVERT=0)
    markers={t["marker"] for t in node["timing"]}
    if len(cells)!=len(node["primitives"]) or set(cells)!=set(expected)|markers:
        raise ValueError("PROGRAM_SOURCE_CELL_INVENTORY")
    for name,(model,params) in expected.items():
        if cells[name]["model"]!=model or cells[name]["parameters"]!=params: raise ValueError("PROGRAM_SOURCE_CELL_POLICY:"+name)
    for name,c in cells.items():
        if c["reset"] != ("eligibility_reset" if name=="eligibility" else "reset"): raise ValueError("PROGRAM_SOURCE_RESET_OWNER:"+name)
        if name in markers and c["model"]!="ChiselAsyncTimingMarker_v1":raise ValueError("PROGRAM_SOURCE_MARKER")
    return click


def program_source_bindings(node):
    click=validate_program_source(node)
    e={x["id"]:x["rtl_path"] for x in node["endpoints"]};c={x["id"]:x["rtl_path"] for x in node["primitives"]}
    children={x["id"]:x["contract"] for x in node["children"]}
    r={x["id"]:x["rtl_path"] for x in children["reservation"]["endpoints"]}
    s={x["id"]:x["rtl_path"] for x in children["stored_buffer"]["endpoints"]}
    cat=lambda xs:"{"+",".join(xs)+"}"
    pairs=[(e["eligibility_reset"],f"({e['reset']} | {e['application_reset']})"),
        (c["eligibility"]+".reset",e["eligibility_reset"]),(c["eligibility"]+".d","1'b1"),
        (e["eligible"],c["eligibility"]+".q"),(e["reserved"],r["in_acknowledge"]),
        (e["reserve_request"],r["in_request"]),(e["reserve_data"],r["in_data"]),
        (e["grant_data"],r["out_data"]),(e["owner_loader"],r["out_data"]),
        (e["grant_acknowledge"],r["out_acknowledge"]),
        (e["grant_request"],c["output_guard"]+".q"),(r["out_request"],c["output_guard"]+".a"),
        (s["in_data"],r["out_data"])]
    pairs += [(e["stored_"+f],s["out_"+f]) for f in ("request","data","acknowledge")]
    ands=[]
    def and_inputs(name,a,b):
        ands.append(name);pairs.extend([(a,c[name+"_na"]+".a"),(b,c[name+"_nb"]+".a")])
    if click:
        pairs += [(e["reserved"],c["arm_pending"]+".a"),(c["armed_phase"]+".q[0]",c["arm_pending"]+".b"),
            (c["arm_pending"]+".q",c["request_guard"]+".a"),(c["request_guard"]+".q",e["arm_event"]),
            (cat(["!"+c["stored_phase"]+".q",e["reserved"]]),c["arm_data_delay"]+".a"),
            (c["arm_data_delay"]+".a",e["arm_sources"]),(c["arm_data_delay"]+".q",e["arm_data"]),
            (e["arm_data"],c["armed_phase"]+".d"),(e["armed"],c["armed_phase"]+".q"),
            (e["arm_event"],c["armed_phase"]+".trigger"),(e["arm_event"],c["eligibility"]+".trigger"),
            (e["reserved"],c["owned"]+".a"),(c["retired_phase"]+".q",c["owned"]+".b"),
            (e["decision_request"],c["return_guard"]+".a"),(c["return_guard"]+".q",c["decision_pending"]+".a"),
            (c["decision_phase"]+".q",c["decision_pending"]+".b"),
            (e["publication_request"],c["publication_pending"]+".a"),(c["publication_phase"]+".q",c["publication_pending"]+".b"),
            (e["stored_target"],c["armed_phase"]+".q[1]"),(e["stored_target"],c["stored_pending"]+".a"),
            (c["stored_phase"]+".q",c["stored_pending"]+".b"),
            (e["stored_target"],c["stored_data_delay"]+".a"),(e["stored_phase_data"],c["stored_data_delay"]+".q"),
            (e["stored_phase_data"],c["stored_phase"]+".d"),(e["stored_event"],c["stored_phase"]+".trigger"),
            (e["stored_issued"],c["stored_phase"]+".q"),(e["stored_event"],c["stored_fire"]+".q"),
            (s["in_request"],c["stored_phase"]+".q")]
        parts=[c["owned"]+".q",f"({e['armed']}[0] == {e['reserved']})",c["decision_pending"]+".q",
            f"({e['decision_data']} && {r['out_data']} && {c['publication_pending']}.q)",c["stored_pending"]+".q"]
        pairs.append((cat(parts),c["stored_request_delay"]+".a"))
        d=c["stored_request_delay"]+".q"
        for name,a,b in (("stored_selection",d+"[0]",d+"[1]"),("stored_decision",d+"[2]",d+"[3]"),
            ("stored_ownership",c["stored_decision"]+".q",d+"[4]"),
            ("stored_fire",c["stored_selection"]+".q",c["stored_ownership"]+".q")):and_inputs(name,a,b)
        returned=" && ".join(f"({x} == {e['stored_target']})" for x in
            (c["stored_phase"]+".q",s["in_acknowledge"],e["stored_request"],e["stored_acknowledge"]))
        parts=[f"(!{e['decision_data']} || !{r['out_data']} || ({returned}))",c["owned"]+".q",c["decision_pending"]+".q",
            f"(!{e['decision_data']} || {c['publication_pending']}.q)",e["word_drained"],
            f"({e['grant_request']} == {e['reserved']} && {e['grant_acknowledge']} == {e['reserved']})",
            f"({e['armed']}[0] == {e['reserved']})"]
        pairs.append((cat(parts),c["request_delay"]+".a"));d=c["request_delay"]+".q"
        for name,a,b in (("source_ready",d+"[0]",d+"[1]"),("effect_ready",d+"[2]",d+"[3]"),
            ("ownership_ready",d+"[4]",d+"[5]"),("settled",c["source_ready"]+".q",c["effect_ready"]+".q"),
            ("stored_retired",c["ownership_ready"]+".q",d+"[6]"),
            ("retire_fire",c["settled"]+".q",c["stored_retired"]+".q")):and_inputs(name,a,b)
        mux=f"({e['decision_data']} ? {e['publication_request']} : {c['publication_phase']}.q)"
        pairs += [(cat([mux,e["decision_request"],e["reserved"]]),c["data_delay"]+".a"),
            (cat([e["decision_data"],e["publication_request"],e["decision_request"],e["reserved"],c["publication_phase"]+".q"]),e["retire_sources"]),
            (e["register_data"],c["data_delay"]+".q"),(e["capture_event"],c["retire_fire"]+".q")]
        for bit,(phase,port) in enumerate((("retired_phase","reserve"),("decision_phase","decision"),("publication_phase","publication"))):
            pairs += [(e["register_data"]+f"[{bit}]",c[phase]+".d"),(e["capture_event"],c[phase]+".trigger"),
                (c[phase]+".q",e["captured"]+f"[{bit}]"),(c[phase]+".q",c["acknowledge_guard"]+f".a[{bit}]"),
                (e[port+"_acknowledge"],c["acknowledge_guard"]+f".q[{bit}]")]
        idle=" && ".join(f"({e[n+'_request']} == {e[n+'_acknowledge']})" for n in CHANNELS)
        idle+=f" && ({e['reserved']} == {e['reserve_acknowledge']}) && !{e['capture_event']} && !{e['arm_event']} && !{e['stored_event']} && ({s['in_request']} == {s['in_acknowledge']})"
    else:
        pairs += [(e["reserved"],c["eligibility"]+".trigger"),(e["decision_request"],c["request_guard"]+".a"),
            (e["reserve_request"],c["retirement"]+".common"),
            (cat([e["reserved"],c["request_guard"]+".q",f"(!{e['decision_data']} || {e['publication_request']})",
                e["word_drained"],f"(!{e['grant_request']} && !{e['grant_acknowledge']})",
                f"(!{e['decision_data']} || !{r['out_data']} || {c['stored_accepted']}.q)"]),c["retirement"]+".rising"),
            (cat([e["decision_request"],f"({e['decision_data']} && {e['publication_request']})"]),c["retirement"]+".falling"),
            (e["decision_acknowledge"],c["retirement"]+".q"),(e["publication_acknowledge"],c["publication_ack"]+".q"),
            (s["in_request"],c["stored_offer"]+".q"),(c["stored_accepted"]+".common",e["reserve_request"]),
            (c["stored_accepted"]+".rising",e["stored_acknowledge"]),(c["stored_accepted"]+".falling","1'b0"),
            (c["retirement"]+".q",c["reservation_return"]+".common"),("1'b1",c["reservation_return"]+".rising"),
            (cat([e["decision_acknowledge"],e["publication_acknowledge"],e["reserved"],s["in_acknowledge"],
                e["stored_request"],e["stored_acknowledge"],c["stored_accepted"]+".q"]),c["reservation_return"]+".falling"),
            (c["reservation_return"]+".q",c["acknowledge_guard"]+".a"),(e["reserve_acknowledge"],c["acknowledge_guard"]+".q")]
        and_inputs("publication_ack",c["retirement"]+".q",e["decision_data"])
        and_inputs("stored_selected",e["reserved"],f"({r['out_data']} && {e['decision_data']})")
        and_inputs("stored_offer",c["stored_selected"]+".q",f"({c['request_guard']}.q && {e['publication_request']})")
        idle=" && ".join("!"+e[n+"_"+f] for n in CHANNELS for f in ("request","acknowledge"))
        idle+=f" && !{e['reserved']} && !{s['in_acknowledge']} && !{c['stored_accepted']}.q"
    pairs.append((e["idle"],"("+idle+")"))
    for n in ands:
        pairs += [(c[n+"_na"]+".q",c[n+"_or"]+".a"),(c[n+"_nb"]+".q",c[n+"_or"]+".b"),(c[n+"_or"]+".q",c[n]+".a")]
    return pairs


def program_source_probe(source,manifest,scopes):
    pairs=[]
    def visit(node):
        nonlocal source
        if re.fullmatch(r"(?:FourPhase|Click)StoredReceipt(?:_[0-9]+)?",node["module"]):
            pairs.extend(stored_receipt_bindings(node,scopes))
        if re.fullmatch(r"(?:FourPhase|Click)ProgramSource(?:_[0-9]+)?",node["module"]):
            pairs.extend(program_source_bindings(node))
            e={x["id"]:x["rtl_path"] for x in node["endpoints"]}
            cell=next(p["rtl_path"] for p in node["primitives"] if p["id"]=="eligibility")
            old=f'if ({cell}.reset !== {e["eligibility_reset"]} || {e["eligibility_reset"]} !== {node["rtl_path"]}.reset) $fatal(1, "RESET_BINDING_MISMATCH");'
            new=f'if ({cell}.reset !== {e["eligibility_reset"]} || {e["eligibility_reset"]} !== ({e["reset"]} | {e["application_reset"]})) $fatal(1, "RESET_BINDING_MISMATCH");'
            if source.count(old)!=1:raise ValueError("PROGRAM_SOURCE_RESET_PROBE_SHAPE")
            source=source.replace(old,new)
        for child in node["children"]:visit(child["contract"])
    visit(manifest["design"])
    top=manifest["top"]
    if top in ("FourPhaseSoc","ClickSoc"):
        cs={c["id"]:c["contract"] for c in manifest["design"]["children"]}
        names={"program_source"}|{"program_"+n+"_bridge" for n in CHANNELS}
        if not names<=cs.keys():raise ValueError("PROGRAM_SOURCE_SOC_INVENTORY")
        click=top=="ClickSoc";prefix="Click" if click else "FourPhase"
        if not re.fullmatch(prefix+r"ProgramSource(?:_[0-9]+)?",cs["program_source"]["module"]):raise ValueError("PROGRAM_SOURCE_SOC_OWNER")
        e={x["id"]:x["rtl_path"] for x in cs["program_source"]["endpoints"]}
        consumer_clock=next(x["rtl_path"] for x in cs["control_command_bridge"]["endpoints"] if x["id"]=="in_clock")
        for name in CHANNELS:
            node=cs["program_"+name+"_bridge"];output=name in ("grant","stored")
            model=("ClickToDecoupled" if click else "FourPhaseToDecoupled") if output else ("DecoupledToClick" if click else "DecoupledToFourPhase")
            if name=="stored":model=prefix+"StoredReceipt"
            protocol="two-phase-bundled-v1" if click else "four-phase-bundled-v1"
            if (not re.fullmatch(model+r"(?:_[0-9]+)?",node["module"]) or
                {c["id"]:(c["protocol"],c["role"]) for c in node["channels"]} !=
                {"in":(protocol if output else "decoupled-v1","input"),"out":("decoupled-v1" if output else protocol,"output")} or
                any(c["layout"] != [dict(field="bits",lsb=0,width=1,signed=False,source=f"~|{node['module']}>{c['id']}.bits")] for c in node["channels"])):
                raise ValueError("PROGRAM_SOURCE_BRIDGE_SCHEMA")
            b={x["id"]:x["rtl_path"] for x in node["endpoints"]}
            pairs += [(e[name+"_"+f],b[("in_" if output else "out_")+f]) for f in ("request","data","acknowledge")]
            pairs.append((b["out_clock" if output else "in_clock"],consumer_clock))
        pairs += [(e["application_reset"],top+".systemReset"),(e["word_drained"],"!"+cs["program_access"]["rtl_path"]+".io_busy")]
    anchor="task check; begin"
    if source.count(anchor)!=1:raise ValueError("PROGRAM_SOURCE_PROBE_SHAPE")
    comparisons=[f'if ({a} !== {b}) $fatal(1,"PROGRAM_SOURCE_BINDING:{a}");' for a,b in pairs]
    return source.replace(anchor,anchor+"\n"+"\n".join(comparisons))
