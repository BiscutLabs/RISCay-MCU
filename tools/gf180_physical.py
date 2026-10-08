# SPDX-License-Identifier: Apache-2.0
"""Experimental physical binding. No behavioral delays enter implementation RTL.

The library ASIC exporter currently rejects the registered SRAM source and its
timing exporter rejects Click. This adapter inventories the SAME contract, checks
exact parameter tuples, and explicitly admits the pinned SRAM view. It never
reports timing closure: qualification requires the separate evidence checker.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
SC = "gf180mcu_fd_sc_mcu7t5v0__"
SRAM = "gf180mcu_ocd_ip_sram__sram1024x8m8wm1"
ATTR = '(* keep = 1, dont_touch = "yes" *) '

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_json(path, value):
    path.write_text(json.dumps(value,indent=2)+"\n")

def nodes(n):
    yield n
    for child in n["children"]:
        yield from nodes(child["contract"])

def key(p):
    return p["model"], tuple(sorted((k,int(v)) for k,v in p["parameters"].items()))

def passive(p):
    return p["view"] == "constraint-marker" or p["model"] == "ChiselAsyncProtocolGuard_v1"

def inventory(export):
    manifest = json.loads((export/"contract.json").read_text())["manifest"]
    ns = list(nodes(manifest["design"]))
    primitives = [p for n in ns for p in n["primitives"]]
    sources = [export/x.strip() for x in (export/"filelist.f").read_text().splitlines() if x.strip()]
    allowed = {n["module"]+".sv" for n in ns} | {p["model"]+".sv" for p in primitives} | {SRAM+".sv"}
    if any(p.name not in allowed or p.parent.resolve()!=export.resolve() for p in sources):
        raise ValueError("UNREGISTERED_SOURCE")
    # Detect an unregistered use of a registered primitive, including a reused module.
    models = {p["model"] for p in primitives}
    actual_modules={manifest["top"]:manifest["top"]}
    for n in ns:
        rtl = (export/(actual_modules[n["rtl_path"]]+".sv")).read_text()
        # firtool can deduplicate equal modules; follow the emitted instance,
        # rather than assuming the pre-deduplication metadata module exists.
        for child in n["children"]:
            path=child["contract"]["rtl_path"]
            match=re.search(r'\b(\w+)\s+'+re.escape(path.split('.')[-1])+r'\s*\(',rtl)
            if not match: raise ValueError("MISSING_ASYNC_CHILD_"+path)
            actual_modules[path]=match[1]
        observed = {(m,x) for m in models for x in re.findall(
            r'\b'+re.escape(m)+r'\s*(?:#\s*\(.*?\)\s*)?([\w$]+)\s*\(',rtl,re.S)}
        declared = {(p["model"],p["rtl_path"].split('.')[-1]) for p in n["primitives"]}
        if observed != declared: raise ValueError("UNREGISTERED_PRIMITIVE")
    groups = defaultdict(list)
    for p in primitives: groups[key(p)].append(p)
    for ps in groups.values():
        if any(p["ports"] != ps[0]["ports"] for p in ps): raise ValueError("INCONSISTENT_PORTS")
    return manifest, sources, groups

class Circuit:
    """Explicit standard-cell graph, also used to generate SPICE test circuits."""
    def __init__(self):
        self.cells = []
        self.serial = 0
    def cell(self, kind, **pins):
        name = "u"+str(self.serial); self.serial += 1
        self.cells.append(dict(name=name,cell=SC+kind,pins=pins))
    def gate(self, kind, pins, output="Z"):
        net = "n"+str(self.serial)
        self.cell(kind,**pins,**{output:net})
        return net
    def inv(self, a): return self.gate("inv_1",dict(I=a),"ZN")
    def reduce(self, kind, values):
        if not values: return "1'b1" if kind=="and" else "1'b0"
        value = values[0]
        for other in values[1:]: value = self.gate(kind+"2_1",dict(A1=value,A2=other))
        return value
    def chain(self, a, count, q="q",kind="buf_1"):
        for i in range(count):
            out = q if i == count-1 else "n"+str(self.serial)
            self.cell(kind,I=a,Z=out); a=out
    def verilog(self, module, ports):
        declarations = [f'{p["direction"]} wire [{p["width"]-1}:0] {p["name"]}' for p in ports]
        nets = sorted({v for c in self.cells for v in c["pins"].values() if re.fullmatch(r'n\d+',v)})
        body = [f'(* keep_hierarchy = "yes" *) module {module} ('+", ".join(declarations)+");"]
        if nets: body.append(ATTR+"wire "+", ".join(nets)+";")
        body += [ATTR+c["cell"]+" "+c["name"]+" ("+", ".join(f'.{p}({v})' for p,v in c["pins"].items())+");" for c in self.cells]
        return "\n".join(body)+"\nendmodule\n"

def adapter(p, guard_min_ns):
    k=dict(key(p)[1]); model=p["model"].removeprefix("ChiselAsync").removesuffix("_v1")
    c=Circuit(); requirement={"control_max_ns":10}
    # Long guards use GF180's DLYD cell (less area per guaranteed delay than
    # repeated BUFs). Counts derive from all pinned corners with extra stages.
    # Post-route slew/load and delay checks remain
    # mandatory; this is a conservative candidate, NOT a wire-delay model.
    def stages(ns): return max(1,math.ceil(1.2*ns/guard_min_ns))
    def normalize(port,count,mask):
        if count<0 or mask<0 or mask>=(1<<count): raise ValueError("INVALID_INPUT_BUBBLE_MASK")
        return [c.inv(f'{port}[{i}]') if (mask>>i)&1 else f'{port}[{i}]' for i in range(count)]
    if model=="AsymmetricC":
        if k["RESET_VALUE"]!=0 or k["COMMON"]<1: raise ValueError("UNSUPPORTED_C_RESET_OR_INPUTS")
        common=normalize("common",k["COMMON"],k["COMMON_INVERT"])
        rising=normalize("rising",k["RISING"],k["RISING_INVERT"])
        falling=normalize("falling",k["FALLING"],k["FALLING_INVERT"])
        set_net=c.reduce("and",common+rising)
        hold_net=c.reduce("or",common+falling)
        # Entire asymmetric equation in ONE preserved state keeper. Do not
        # replace it with a chain of binary C-elements (different protocol).
        c.cell("aoi21_1",A1="state",A2=hold_net,B=set_net,ZN="next_n")
        c.cell("nor2_1",A1="next_n",A2="reset",ZN="state")
        c.chain("state",9)
        requirement.update(feedback="aoi21/nor2 static keeper",feedback_max_ns=10,control_min_ns=1)
    elif model in ("And","Xor"):
        if model=="And": value=c.reduce("and",normalize("d",k["INPUTS"],k["INVERT"]))
        else: value=c.gate("xor2_1",dict(A1="a",A2="b"))
        value=c.gate("and2_1",dict(A1=value,A2=c.inv("reset")))
        c.chain(value,9); requirement["control_min_ns"]=1
    elif model=="ControlGate":
        width=k["WIDTH"]; op=k["OP"]
        if op not in (0,1,2): raise ValueError("UNKNOWN_CONTROL_OPERATION")
        if width>1 and (op!=0 or k["RESET_VALUE"]!=0): raise ValueError("UNKNOWN_DATA_ALLOWANCE")
        data=width>1
        requirement={"role":"whole-transform-allowance" if data else "matched-control-delay",
                     "data_max_ns" if data else "control_min_ns":k["DELAY_FS"]/1e6}
        nr=c.inv("reset")
        reset_groups={}
        if data:
            reset_root=c.gate("buf_8",dict(I=nr))
            reset_groups={g:c.gate("buf_4",dict(I=reset_root)) for g in range(math.ceil(width/16))}
        for i in range(width):
            value=f'a[{i}]'
            if op==1: value=c.inv(value)
            if op==2: value=c.gate("or2_1",dict(A1=value,A2=f'b[{i}]'))
            value=c.gate("or2_1" if (k["RESET_VALUE"]>>i)&1 else "and2_1",
                dict(A1=value,A2="reset" if (k["RESET_VALUE"]>>i)&1 else reset_groups.get(i//16,nr)))
            long_guard=not data and k["DELAY_FS"]>1000000
            c.chain(value,stages(k["DELAY_FS"]/1e6) if long_guard else 1 if data else 9,
                f'q[{i}]',kind="dlyd_1" if long_guard else "buf_1")
        if not data and k["DELAY_FS"]<=1000000: requirement["control_max_ns"]=10
    elif model in ("EventRegister","ClosingLatch","PhaseRegister"):
        width=k.get("WIDTH",1); nr=c.inv("reset")
        enable=c.inv("closed") if model=="ClosingLatch" else "trigger"
        # Small balanced local tree, including reset, avoids a single cell
        # driving hundreds of clock/reset pins. Bound every leaf after routing.
        root=c.gate("buf_8",dict(I=enable)); reset_root=c.gate("buf_8",dict(I=nr))
        clocks={}; resets={}
        for group in range(math.ceil(width/16)):
            clocks[group]=c.gate("buf_4",dict(I=root))
            resets[group]=c.gate("buf_4",dict(I=reset_root))
        for i in range(width):
            q="state" if model=="PhaseRegister" else f'q[{i}]'
            d=c.inv("state") if model=="PhaseRegister" else f'd[{i}]'
            if model=="ClosingLatch": c.cell("latrnq_1",D=d,E=clocks[i//16],RN=resets[i//16],Q=q)
            elif (k.get("RESET_VALUE",0)>>i)&1: c.cell("dffsnq_1",D=d,CLK=clocks[i//16],SETN=resets[i//16],Q=q)
            else: c.cell("dffrnq_1",D=d,CLK=clocks[i//16],RN=resets[i//16],Q=q)
        requirement.update(storage_bits=width,clock_distribution_max_ns=4 if model=="ClosingLatch" else 2.5)
        if model=="PhaseRegister":
            c.chain("state",9); requirement["control_min_ns"]=1
    else: raise ValueError("UNSUPPORTED_ACTIVE_MODEL_"+model)
    return c,requirement

def pdk_verify(pdk):
    lock=json.loads((ROOT/"physical/gf180/pdk-lock.json").read_text())
    for name,digest in lock["files"].items():
        if sha(pdk/name)!=digest: raise ValueError("PDK_HASH_MISMATCH_"+name)
    return lock

def guard_floor(pdk):
    from gf180_estimate import groups
    minima=[]
    for lib in sorted(pdk.glob("*.lib")):
        body=dict(groups(lib.read_text(),"cell"))[SC+"dlyd_1"]
        for kind in ("cell_rise","cell_fall"):
            for _,table in groups(body,kind):
                slews=[float(x) for x in re.search(r'index_1\("([^"]+)"\)',table)[1].split(',')]
                values=re.search(r'values\s*\((.*?)\)\s*;',table,re.S)
                rows=re.findall(r'"([^"]+)"',values[1])
                # Include the next grid row above our 2 ns slew limit. Slow
                # unconstrained ramps have negative 50%-crossing delay and
                # cannot be used to infer a positive buffer-chain minimum.
                last=next(i for i,x in enumerate(slews) if x>=2.0)
                minima += [float(x) for row in rows[:last+1] for x in row.split(',')]
    value=min(minima)
    if value<=0: raise ValueError("INVALID_BUFFER_FLOOR")
    return value * 0.8 # additional headroom for the sub-20 ps input-slew boundary

def prepare(export,out,pdk):
    if out.exists(): raise ValueError("OUTPUT_ALREADY_EXISTS")
    pdk_verify(pdk)
    from sram_assets import verify
    # Public asset tool also checks the vendored RTL. No memory contents model
    # is copied into the ASIC inventory.
    lock=json.loads((ROOT/"soc/sram-lock.json").read_text())
    for name,asset in lock["assets"].items():
        verify((ROOT/".tools/gf180-sram"/name).read_bytes(),asset["sha256"])
    manifest,sources,groups=inventory(export)
    policy=json.loads((export/"physical-policy.json").read_text())
    if policy["policy_enabled"] is not True: raise ValueError("DISABLED_ESTIMATE_POLICY")
    floor=guard_floor(pdk)
    out.mkdir(parents=True)
    bindings=[]; circuits=[]; filelist=[]
    primitive_files={k[0]+".sv" for k in groups}
    for source in sources:
        if source.name in primitive_files: continue
        if source.name==SRAM+".sv":
            shutil.copyfile(ROOT/".tools/gf180-sram"/(SRAM+".blackbox.v"),out/source.name)
        else: shutil.copyfile(source,out/source.name)
        filelist.append(source.name)
    bymodel=defaultdict(list)
    for index,(k,ps) in enumerate(sorted(groups.items())):
        p=ps[0]
        if passive(p): bymodel[k[0]].append((k,None)); continue
        circuit,requirements=adapter(p,floor)
        module=f'riscay_gf180_cell_{index}'
        text=circuit.verilog(module,p["ports"])
        # Internal keeper nets are explicitly declared, never implicit wires.
        extra=[n for n in ("state","next_n") if any(n in c["pins"].values() for c in circuit.cells)]
        if extra: text=text.replace(");\n", ");\n"+ATTR+"wire "+", ".join(extra)+";\n",1)
        circuits.append(text)
        binding=dict(model=k[0],parameters=dict(k[1]),module=module,ports=p["ports"],
            instances=[x["rtl_path"] for x in ps],requirements=requirements,cells=circuit.cells)
        bindings.append(binding); bymodel[k[0]].append((k,binding))
    for model,variants in sorted(bymodel.items()):
        source=(export/(model+".sv")).read_text(); start=source.index("module "+model)
        header=source[start:source.index(");",start)+2]
        header=header.replace("parameter time", "parameter [63:0]")
        header=header.replace("parameter longint unsigned", "parameter [63:0]")
        body=[]
        if variants[0][1] is not None:
            for i,(k,b) in enumerate(variants):
                b["variant"]=i
                conditions=" && ".join(f'({n} == {max(64,v.bit_length())}\'d{v})' for n,v in k[1])
                body.append(f'{"if" if i==0 else "else if"} ({conditions}) begin : variant_{i}')
                body.append('(* keep_hierarchy = "yes", dont_touch = "yes" *) '+b["module"]+
                    " mapped ("+", ".join(f'.{p["name"]}({p["name"]})' for p in b["ports"])+");\nend")
            body.append("else begin : unmapped\n  RISCAY_UNMAPPED_ASYNC_PARAMETERIZATION reject();\nend")
        (out/(model+".sv")).write_text("// Exact physical binding; no simulation delay body.\n"+header+"\n"+"\n".join(body)+"\nendmodule\n")
        filelist.append(model+".sv")
    (out/"riscay_gf180_cells.v").write_text("// SPDX-License-Identifier: Apache-2.0\n"+"\n".join(circuits))
    filelist.append("riscay_gf180_cells.v")
    physical_top(export,out,manifest,policy)
    filelist += ["RiscayMcuDigital.sv","riscay_reset_hold.sv"]
    (out/"filelist.f").write_text("\n".join(filelist)+"\n")
    shutil.copyfile(export/"contract.json",out/"timing-intent.json")
    shutil.copyfile(export/"physical-policy.json",out/"physical-policy.json")
    timing_contract(out,manifest,bindings)
    write_json(out/"mapping.json",dict(schema="riscay-gf180-mapping-v1",status="mapped-unqualified",
        top="RiscayMcuDigital",variant=policy["variant"],matched_delay_cell="dlyd_1",matched_delay_floor_ns=floor,
        bindings=bindings,inputs={p.name:sha(p) for p in sources},
        files_sha256={f:sha(out/f) for f in filelist},
        qualification="PVT, extracted relative timing, pulse/aperture, reset and C-element checks required"))
    return len(bindings)

def physical_top(export,out,manifest,policy):
    ports=json.loads((export/"ports.json").read_text())["nodes"][0]["ports"]
    names=[p["source"].split('>')[-1].replace('.','_').replace('[','_').replace(']','') for p in ports]
    # I2C and GPIO use separate sense/drive ports at the digital boundary; the
    # chip shell exposes bidirectional package nets. No diagnostic pad bundle.
    external={"scl","sda","sdaLow","gpioIn","gpioOut","gpioOe","adcMiso","adcCsN","adcSclk"}
    n=policy["gpio_count"]
    declarations=["input wire serviceClock, watchdogClock, powerGood, reset",
        "output wire serviceClockEnable, porReleased", "input wire scl, sda, adcMiso",
        "output wire sdaLow, adcCsN, adcSclk",f"input wire [{n-1}:0] gpioIn",
        f"output wire [{n-1}:0] gpioOut, gpioOe"]
    connections=[]
    for name,p in zip(names,ports):
        if name=="reset": value="~porReleased"
        elif name=="gpioIn": value=f"{{{32-n}'b0,gpioIn}}"
        elif name in ("gpioOut","gpioOe"): value=name+"Full"
        elif name in external or name in ("serviceClock","watchdogClock","serviceClockEnable"): value=name
        elif p["direction"]=="output": value=""
        else: raise ValueError("UNBOUND_TOP_INPUT_"+name)
        connections.append(f'.{name}({value})')
    text="// SPDX-License-Identifier: Apache-2.0\nmodule RiscayMcuDigital ("+",\n".join(declarations)+");\n"
    text+="wire [31:0] gpioOutFull, gpioOeFull;\n"
    text+=f"assign gpioOut=gpioOutFull[{n-1}:0];\nassign gpioOe=gpioOeFull[{n-1}:0];\n"
    text+="riscay_reset_hold #(.HOLD_CYCLES(100000)) resetHold (.clk(serviceClock), .power_good(powerGood), .reset(reset), .released(porReleased));\n"
    text+=manifest["top"]+" soc ("+",\n".join(connections)+");\nendmodule\n"
    (out/"RiscayMcuDigital.sv").write_text(text)
    shutil.copyfile(export/"chip/riscay_reset_hold.sv",out/"riscay_reset_hold.sv")
    shell=(ROOT/"physical/gf180/RiscayMcuChip.sv").read_text().replace("@GPIO_COUNT@",str(n))
    (out/"RiscayMcuChip.sv").write_text(shell)
    for f in ("riscay_supply_monitor.v","riscay_lf_osc.v","riscay_service_osc.v"):
        shutil.copyfile(export/"chip"/f,out/f)
    shutil.copyfile(ROOT/"physical/gf180/power.tcl",out/"power.tcl")
    shutil.copyfile(ROOT/"physical/gf180/base.sdc",out/"base.sdc")
    write_json(out/"pins.json",dict(gpio_count=n,package_signals=["reset","scl","sda","adcMiso","adcCsN","adcSclk"]+
        [f"gpio[{i}]" for i in range(n)],supplies=["VDD","VSS"],
        internal_analog_boundary=["serviceClock","watchdogClock","powerGood","serviceClockEnable","porReleased"],
        pad_status="logical shell only; GF180 I/O cells, ESD and padframe still required"))

def timing_contract(out,manifest,bindings):
    # This inventory is deliberately unbound. gf180_constraints.py uses the
    # synthesized instance tree, including generate-block spelling and names.
    checks=[]
    for b in bindings:
        for instance in b["instances"]:
            checks.append(dict(id=instance,module=b["module"],requirements=b["requirements"],
                relative_leaf_pins=[c["name"]+"/"+p for c in b["cells"] for p in c["pins"]]))
    timings=[dict(path=n["rtl_path"],timing=t,endpoints=n["endpoints"]) for n in nodes(manifest["design"]) for t in n["timing"]]
    write_json(out/"async-checks.json",dict(schema="riscay-relative-timing-v1",status="unqualified",
        cells=checks,stages=timings,required_evidence=["cell_pvt","whole_data_paths","relative_ordering",
        "pulse_high_low","setup_hold","reset_recovery_removal","clock_distribution","sram_half_cycle",
        "cdc_first_stage_only","keeper_feedback","postroute_parasitics"]))

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export",type=Path); parser.add_argument("output",type=Path)
    parser.add_argument("--pdk",type=Path,default=ROOT/".tools/physical/pdk")
    args=parser.parse_args()
    print(f"Mapped {prepare(args.export,args.output,args.pdk)} exact specializations; qualification pending")
