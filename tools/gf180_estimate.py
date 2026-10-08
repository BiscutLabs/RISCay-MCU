# SPDX-License-Identifier: Apache-2.0
"""Pre-layout cost model. Never emits a qualified physical implementation.

Keep atomic async primitives as black boxes during standard-logic synthesis.
Count their storage separately using GF180 cells; unidentified cells fail closed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import statistics
import math

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "gf180mcu_fd_sc_mcu7t5v0__"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_hash(path, expected):
    if sha(path)!=expected:
        raise ValueError("INPUT_HASH_MISMATCH_"+str(path))


def verify_inputs(libdir, mapping=False):
    pinned=json.loads((ROOT/"tools/gf180-estimate-inputs.json").read_text())
    for name,digest in pinned["libraries"].items(): verify_hash(libdir/name,digest)
    if mapping:
        for tool,path in (("sv2v","sv2v"),("yosys","root/usr/bin/yosys"),("abc","root/usr/bin/yosys-abc")):
            verify_hash(ROOT/".tools/physical"/path,pinned["tools"][tool]["sha256"])


def groups(text, kind):
    """Balanced Liberty groups, including nested tables, not regex-only braces."""
    pattern = re.compile(r"\b" + re.escape(kind) + r"\s*\(([^)]*)\)\s*\{")
    for match in pattern.finditer(text):
        start = match.end()
        depth = 1
        quoted = False
        for i in range(start, len(text)):
            ch = text[i]
            if ch == '"' and text[i-1] != "\\":
                quoted = not quoted
            if not quoted:
                depth += (ch == "{") - (ch == "}")
            if not depth:
                yield match.group(1).strip().strip('"'), text[start:i]
                break
        else:
            raise ValueError("UNBALANCED_LIBERTY")


def scalar(text, key):
    m = re.search(r"\b" + re.escape(key) + r'\s*:\s*"?([-+0-9.eE]+)"?\s*;', text)
    if not m:
        raise ValueError("MISSING_LIBERTY_" + key)
    return float(m.group(1))


def direct_groups(text, kind):
    # In particular, do not overwrite real scan-cell pins with test_cell pins.
    pattern=re.compile(r"\b(\w+)\s*\(([^)]*)\)\s*\{")
    cursor=0
    while match:=pattern.search(text,cursor):
        depth=1; quoted=False
        for i in range(match.end(),len(text)):
            ch=text[i]
            if ch=='"' and text[i-1]!="\\": quoted=not quoted
            if not quoted: depth+=(ch=="{")-(ch=="}")
            if depth==0: break
        else: raise ValueError("UNBALANCED_LIBERTY")
        if match.group(1)==kind:
            yield match.group(2).strip().strip('"'),text[match.end():i]
        cursor=i+1


def library(path):
    text = Path(path).read_text()
    if not re.search(r'leakage_power_unit\s*:\s*"?1uW"?', text):
        raise ValueError("UNSUPPORTED_LEAKAGE_UNIT")
    if not re.search(r'time_unit\s*:\s*"?1ns"?', text) or not re.search(r'capacitive_load_unit\s*\(1,\s*pf\)', text):
        raise ValueError("UNSUPPORTED_ENERGY_UNITS")
    if not re.search(r'current_unit\s*:\s*"?1mA"?',text) or not re.search(r'voltage_unit\s*:\s*"?1V"?',text):
        raise ValueError("UNSUPPORTED_POWER_UNITS")
    cells = {name: body for name, body in groups(text, "cell")}
    if not cells:
        raise ValueError("EMPTY_LIBRARY_HEADER_IS_NOT_A_CELL_LIBRARY")
    return cells


def linux(path):
    path = str(Path(path).resolve()).replace("\\", "/")
    return "/mnt/" + path[0].lower() + path[2:] if len(path)>1 and path[1]==":" else path


def prepare(export, output, lib):
    verify_inputs(lib.parent,mapping=True)
    if lib.name!="tt_025C_3v30.lib": raise ValueError("MAPPING_REQUIRES_PINNED_TT_LIBRARY")
    library(lib)
    output.mkdir(parents=True, exist_ok=True)
    top = json.loads((export / "contract.json").read_text())["manifest"]["top"]
    sources = []
    inventory = {}
    for name in (export / "filelist.f").read_text().splitlines():
        source = export / name.strip().replace("\\", "/")
        if not name.strip():
            continue
        text = source.read_text()
        if source.name.startswith("ChiselAsync"):
            # Preserve atomic boundaries, not their unqualified behavioral delays.
            header = text[text.index("module "):text.index(");", text.index("module "))+2]
            header = header.replace("parameter time", "parameter [63:0]")
            header = header.replace("parameter longint unsigned", "parameter [63:0]")
            header = header.replace("parameter bit", "parameter")
            marker = any(x in source.name for x in ("Marker", "ProtocolGuard"))
            text = ("" if marker else "(* blackbox *)\n") + header + "\nendmodule\n"
        destination = output / source.name
        destination.write_text(text)
        inventory[source.name] = sha(source)
        sources.append(linux(destination))
    # Include the production 100,000-cycle reset sequencer. Analog macros remain
    # separate line items; its good/clock inputs are abstract pins for synthesis.
    reset = export / "chip/riscay_reset_hold.sv"
    reset_text = reset.read_text()
    reset_text = re.sub(r"\btime(?:unit|precision)\s+[^;]+;", "", reset_text)
    (output / reset.name).write_text(reset_text)
    # Synthesize digital SoC and reset sequencer independently to keep boundaries
    # visible, and keep the existing trace/commit outputs for conservative sizing.
    for unit, files in ((top, sources), ("riscay_reset_hold", [linux(output/reset.name)])):
        command = [linux(ROOT/".tools/physical/sv2v"), "-DSYNTHESIS", *files]
        if __import__("os").name == "nt":
            command = ["wsl", "-e", *command]
        with (output/(unit+"-converted.v")).open("w") as converted:
            subprocess.run(command,stdout=converted,check=True,timeout=120)
        script = f"read_liberty -lib {linux(lib)}\n"
        script += "read_verilog -sv -DSYNTHESIS " + linux(output/(unit+"-converted.v")) + "\n"
        script += f"synth -top {unit} -flatten -noabc\n"
        script += f"dfflibmap -liberty {linux(lib)}\n"
        script += f"abc -exe {linux(ROOT/'.tools/physical/root/usr/bin/yosys-abc')} -liberty {linux(lib)}\n"
        script += f"clean\nstat -liberty {linux(lib)}\nwrite_json {linux(output/(unit+'.json'))}\n"
        (output/(unit+".ys")).write_text(script)
    (output/"inputs.json").write_text(json.dumps(dict(top=top, export=str(export),
        rtl_sha256=inventory, liberty_sha256=sha(lib),
        library_source="open_pdks 40cee970d8a9b7eaea35a34fe7d6068f05721f0a; installed gf180mcuD",
        sv2v_sha256=sha(ROOT/".tools/physical/sv2v")),indent=2)+"\n")
    return top


def run_mapping(export, output, lib):
    top = prepare(export, output, lib)
    binary = linux(ROOT/".tools/physical/root/usr/bin/yosys")
    for unit in (top, "riscay_reset_hold"):
        command = [binary, "-T", "-s", linux(output/(unit+".ys"))]
        if __import__("os").name == "nt":
            command = ["wsl", "-e", *command]
        with (output/(unit+".log")).open("w") as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
    print("MAPPED_STANDARD_LOGIC_WITH_UNRESOLVED_ASYNC_MACROS", output)


def primitives(export):
    def visit(node):
        yield from node["primitives"]
        for child in node["children"]:
            yield from visit(child["contract"])
    return list(visit(json.loads((export/"contract.json").read_text())["manifest"]["design"]))


def activity(export, output):
    """Add observers to an already passing, exported estimate harness. No DUT edits."""
    output.mkdir(parents=True, exist_ok=True)
    monitors = ["integer eventBits=0,latchBits=0,phaseBits=0;"]
    monitors.append("always @(posedge serviceClockEnable) begin eventBits=0; latchBits=0; phaseBits=0; end")
    monitors.append('always @(negedge serviceClockEnable) if(measured>0) $display("ASYNC,%0d,%0d,%0d",eventBits,latchBits,phaseBits);')
    for primitive in primitives(export):
        model = primitive["model"]
        path = "dut.soc." + primitive["rtl_path"].split(".",1)[1]
        width = int(primitive["parameters"].get("WIDTH",1))
        if model == "ChiselAsyncEventRegister_v1":
            monitors.append(f"always @(posedge {path}.trigger) if(!{path}.reset) eventBits=eventBits+{width};")
        elif model == "ChiselAsyncClosingLatch_v1":
            monitors.append(f"always @(negedge {path}.closed) if(!{path}.reset) latchBits=latchBits+{width};")
        elif model == "ChiselAsyncPhaseRegister_v1":
            monitors.append(f"always @(posedge {path}.trigger) if(!{path}.reset) phaseBits=phaseBits+1;")
    tb = (export/"testbench.sv").read_text()
    # After harness declarations; Icarus rejects a procedural use before declaration.
    tb = tb.replace("endmodule", "\n"+"\n".join(monitors)+"\nendmodule")
    (output/"testbench.sv").write_text(tb)
    sources = [str((export/x.strip().replace("\\","/")).resolve()) for x in (export/"filelist.f").read_text().splitlines() if x.strip()]
    chip = export/"chip"
    sources += [str(x.resolve()) for x in chip.glob("*.sv")]
    # The .sv set includes models/reset/top but excludes analog blackbox .v views.
    command = ["iverilog","-g2012","-s","Testbench","-o",str(output/"sim.vvp"),*sources,str(output/"testbench.sv")]
    for command, filename in ((command,"compile.log"),(["vvp",str(output/"sim.vvp")],"simulation.log")):
        with (output/filename).open("w") as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
    log=(output/"simulation.log").read_text()
    if log.count("ESTIMATE_ACTIVITY_COMPLETE")!=1 or log.count("RISCAY_SOC_PASS")!=1:
        raise ValueError("INCOMPLETE_ACTIVITY")
    print("OBSERVED_NATIVE_MODEL_ACTIVITY",output)


def numbers(text, key):
    match = re.search(r"\b"+key+r"\s*\((.*?)\)\s*;", text, re.S)
    if not match:
        raise ValueError("MISSING_TABLE_"+key)
    return [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?",match.group(1))]


def interpolate(xs, ys, x):
    if len(xs)!=len(ys) or any(b<=a for a,b in zip(xs,xs[1:])):
        raise ValueError("INVALID_TABLE")
    if x<=xs[0]: return ys[0]
    if x>=xs[-1]: return ys[-1]
    for i in range(len(xs)-1):
        if xs[i]<=x<=xs[i+1]:
            t=(x-xs[i])/(xs[i+1]-xs[i])
            return ys[i]*(1-t)+ys[i+1]*t
    raise ValueError("INVALID_INTERPOLATION")


def table_value(body, slew=0.1, load=0.01):
    if "index_1" not in body:
        values=numbers(body,"values")
        if len(values)!=1: raise ValueError("INVALID_SCALAR_TABLE")
        return values[0]
    xs=numbers(body,"index_1")
    values=numbers(body,"values")
    if "index_2" not in body:
        return interpolate(xs,values,slew)
    ys=numbers(body,"index_2")
    if len(values)!=len(xs)*len(ys): raise ValueError("INVALID_2D_TABLE")
    rows=[interpolate(ys,values[i*len(ys):(i+1)*len(ys)],load) for i in range(len(xs))]
    return interpolate(xs,rows,slew)


def pin_cycle(pin, slew=0.1):
    """Mean over listed internal-power conditions; mW*ns = pJ in this library.

    Input clock/E groups have no related_pin and capture no-output-change energy.
    Output groups capture extra data-dependent energy and remain in the activity
    allowance. Negative characterized internal terms are clamped for budgeting.
    """
    values=[]
    for _,power in groups(pin,"internal_power"):
        pair=[]
        for kind in ("rise_power","fall_power"):
            tables=list(groups(power,kind))
            pair.append(max(0,table_value(tables[0][1],slew)) if tables else 0)
        values.append(sum(pair))
    return statistics.mean(values) if values else 0


def cell_metrics(body):
    leaks=[scalar(x,"value") for _,x in groups(body,"leakage_power") if "when" in x]
    if not leaks:
        leaks=[scalar(x,"value") for _,x in groups(body,"leakage_power")]
    if not leaks: raise ValueError("MISSING_LEAKAGE")
    pins=dict(direct_groups(body,"pin"))
    clocks=[name for name,pin in pins.items() if re.search(r"clock\s*:\s*true",pin)]
    clock=clocks[0] if clocks else "E" if "E" in pins and list(direct_groups(body,"latch")) else None
    clock_cap=scalar(pins[clock],"capacitance") if clock else 0
    data_cap=sum(scalar(pin,"capacitance") for name,pin in pins.items()
        if name!=clock and re.search(r"direction\s*:\s*input",pin))
    area=scalar(body,"area")
    if area<0 or any(x<0 or not math.isfinite(x) for x in leaks): raise ValueError("INVALID_CELL_METRICS")
    return dict(area_um2=area,leak_min_uw=min(leaks),leak_mean_uw=statistics.mean(leaks),
        leak_max_uw=max(leaks),clock_pin=clock,clock_cap_pf=clock_cap,
        clock_internal_pj=pin_cycle(pins[clock]) if clock else 0,
        data_cycle_pj=sum(pin_cycle(pin) for name,pin in pins.items() if name!=clock),data_cap_pf=data_cap)


def equivalent_primitives(items, buffers_per_guard=0, c_nands=6):
    """Area/leakage bookkeeping, not synthesizable async replacement circuits."""
    cells=Counter(); inventory=Counter(); guards=0; c_count=0
    for primitive in items:
        model=primitive["model"]; p={k:int(v) for k,v in primitive["parameters"].items()}
        w=p.get("WIDTH",1)
        if "Marker" in model or "ProtocolGuard" in model: continue
        inventory[model]+=1
        if model=="ChiselAsyncClosingLatch_v1":
            cells["latrnq_1"]+=w; cells["inv_1"]+=2
        elif model=="ChiselAsyncEventRegister_v1":
            if not 0<=p["RESET_VALUE"]<2**w: raise ValueError("INVALID_STORAGE_RESET_VALUE")
            ones=p["RESET_VALUE"].bit_count()
            cells["dffrnq_1"]+=w-ones; cells["dffsnq_1"]+=ones; cells["inv_1"]+=1
        elif model=="ChiselAsyncPhaseRegister_v1":
            cells["dffsnq_1" if p["RESET_VALUE"] else "dffrnq_1"]+=1; cells["inv_1"]+=2
        elif model=="ChiselAsyncControlGate_v1":
            cells["inv_1"]+=1
            cells["and2_1"]+=w
            if p["OP"]==1: cells["inv_1"]+=w
            elif p["OP"]==2: cells["or2_1"]+=w
            elif p["OP"]!=0: raise ValueError("UNKNOWN_GATE_OP")
            if p["OP"]==0 and w==1:
                guards+=1; cells["buf_1"]+=buffers_per_guard
        elif model=="ChiselAsyncAnd_v1":
            if p["INPUTS"]!=2: raise ValueError("UNSUPPORTED_AND_WIDTH")
            cells["inv_1"]+=1+p["INVERT"].bit_count(); cells["and3_1"]+=1
        elif model=="ChiselAsyncXor_v1":
            cells["xor2_1"]+=1; cells["and2_1"]+=1; cells["inv_1"]+=1
        elif model=="ChiselAsyncAsymmetricC_v1":
            c_count+=1; cells["nand2_1"]+=c_nands
            cells["inv_1"]+=sum(p[x].bit_count() for x in ("COMMON_INVERT","RISING_INVERT","FALLING_INVERT"))
        else: raise ValueError("UNKNOWN_ASYNC_PRIMITIVE_"+model)
    return Counter({PREFIX+k:v for k,v in cells.items() if v}),dict(inventory),guards,c_count


def mapping_inventory(path,top,metrics):
    module=json.loads(path.read_text())["modules"][top]
    counts=Counter(); domains={k:Counter() for k in ("fast","work","lf","host")}
    clocks={}
    if top=="riscay_reset_hold":
        clocks[module["ports"]["clk"]["bits"][0]]="fast"
    else:
        clocks[module["ports"]["serviceClock"]["bits"][0]]="fast"
        clocks[module["ports"]["watchdogClock"]["bits"][0]]="lf"
        clocks[module["ports"]["sda"]["bits"][0]]="host"
        clocks[module["netnames"]["gate_io_clockOut"]["bits"][0]]="work"
    # The falling-edge gate-enable FF is mapped using a clock inverter.
    changed=True
    while changed:
        changed=False
        for c in module["cells"].values():
            if c["type"]==PREFIX+"inv_1":
                a=c["connections"]["I"][0]; z=c["connections"]["ZN"][0]
                if a in clocks and z not in clocks:
                    clocks[z]=clocks[a];changed=True
    registered_bits=set()
    for c in module["cells"].values():
        kind=c["type"]
        if kind.startswith("ChiselAsync"): continue
        if kind not in metrics: raise ValueError("UNMAPPED_DIGITAL_CELL_"+kind)
        counts[kind]+=1
        pin=metrics[kind]["clock_pin"]
        if pin:
            bit=c["connections"][pin][0]
            if bit not in clocks: raise ValueError("UNKNOWN_CLOCK_DOMAIN_"+str(bit))
            domains[clocks[bit]][kind]+=1
            registered_bits.update(c["connections"].get("Q",[]))
    # Assert that working/program RAM bits have survived full-capacity synthesis.
    memory_bits={}
    for prefix,expected in (("fabric_program_",16384),("fabric_ram_",2048)):
        bits=set()
        for name,net in module["netnames"].items():
            if re.fullmatch(prefix+r"\d+(?:_\d+)?",name): bits.update(net["bits"])
        if top!="riscay_reset_hold" and (len(bits)!=expected or not bits.issubset(registered_bits)
                                       or any(not isinstance(x,int) for x in bits)):
            raise ValueError("MEMORY_CAPACITY_LOST_"+prefix+str(len(bits)))
        memory_bits[prefix]=len(bits)
    return counts,domains,memory_bits


def sum_metric(counts, metrics, key):
    return sum(n*metrics[k][key] for k,n in counts.items())


def read_activity(path):
    log=path.read_text()
    if log.count("ESTIMATE_ACTIVITY_COMPLETE")!=1 or log.count("RISCAY_SOC_PASS")!=1:
        raise ValueError("MISSING_ACTIVITY_COMPLETION")
    wakes=[]; asynchronous=[]
    for line in log.splitlines():
        if line.startswith("WAKE,"):
            x=line.split(",")
            wakes.append(dict(phase=int(x[1]),fast=int(x[2]),work=int(x[3]),retired=int(x[4]),adc=int(x[5]),ns=float(x[6])))
        elif line.startswith("ASYNC,"): asynchronous.append([int(x) for x in line.split(",")[1:]])
    if not wakes or len(wakes)!=len(asynchronous): raise ValueError("MISSING_ASYNC_ACTIVITY")
    # Both lines come from the same falling edge; process scheduling may reverse
    # their order, but their separate lists retain the same chronological index.
    for w,a in zip(wakes,asynchronous):
        if not 0<w["work"]<=w["fast"] or not w["ns"]>0: raise ValueError("EMPTY_WAKE")
        w.update(event_bits=a[0],latch_bits=a[1],phase_bits=a[2])
    result={}
    for kind,predicate in (("maintenance",lambda w:not w["adc"] and not w["retired"]),
                           ("sample",lambda w:w["adc"] and not w["retired"]),
                           ("firmware",lambda w:w["retired"]>0)):
        selected=[w for w in wakes if predicate(w)]
        if len(selected)<2: raise ValueError("INSUFFICIENT_"+kind.upper()+"_WAKES")
        result[kind]=dict(observations=len(selected),**{k:statistics.mean(w[k] for w in selected)
            for k in selected[0] if k!="phase"})
    if result["firmware"]["retired"]!=43: raise ValueError("WORKLOAD_RETIREMENT_CHANGED")
    return result


def report(base,libdir):
    verify_inputs(libdir)
    libs={name:{k:cell_metrics(v) for k,v in library(libdir/(name+".lib")).items()}
          for name in ("tt_025C_3v30","ss_n40C_3v00","ff_125C_3v60")}
    nominal=libs["tt_025C_3v30"]
    result=dict(scope="PRE_LAYOUT_ESTIMATE_NOT_SIGNOFF",voltage=3.3,
        cell_library="GF180 mcu7t5v0; installed open_pdks 40cee970d8a9b7eaea35a34fe7d6068f05721f0a",
        libraries_sha256={n:sha(libdir/(n+".lib")) for n in libs},variants={},
        estimator_sha256=sha(__file__),input_manifest_sha256=sha(ROOT/"tools/gf180-estimate-inputs.json"),
        assumptions=dict(cell_overhead_fraction=[0.10,0.25],utilization=[0.45,0.60],
            analog_area_mm2=[0.233,0.38],pad_depth_mm=0.35,pad_core_gap_mm=0.05,
            clock_energy_multiplier=[1.10,1.50],data_cycles_per_work_cycle=[0.01,0.20],
            slew_ns=0.1,representative_output_load_pf=0.01))
    analog_paths=[ROOT/"build"/name/"report.json" for name in (
        "clock-reset-clock-01","clock-reset-monitor-05","clock-reset-events-03","lf-osc-final-pvt")]
    analog_reports=[json.loads(path.read_text()) for path in analog_paths]
    if not all(p["passed"] for p in analog_reports): raise ValueError("FAILED_ANALOG_EVIDENCE")
    clock_report,monitor_report,event_report,lf_report=analog_reports
    def tt(c): return c["mos"]=="typical" and c["resistor"]=="typical" and c["temperature"]==25
    clock_cases=[r for r in clock_report["results"] if tt(r["case"]) and r["case"]["voltage"]==3.3 and r["case"]["load"]==1e-13]
    monitors=[r for r in event_report["results"] if tt(r["case"]) and r["case"]["bjt"]=="typical"
        and r["case"]["voltage"]==3.3 and r["case"]["profile"]=="plateau"]
    lf_cases=[r for r in lf_report["results"] if r["case"]["name"]=="typical-3.3-25"]
    if not clock_cases or not monitors or len(lf_cases)!=1: raise ValueError("MISSING_NOMINAL_ANALOG_EVIDENCE")
    active_current=statistics.mean(r["active_current_a"] for r in clock_cases)
    stopped_current=statistics.mean(r["stopped_current_a"] for r in clock_cases)
    monitor_current=statistics.mean(r["supply_current_a"] for r in monitors)
    nominal_analog_uw=(monitor_current+stopped_current)*3.3e6+lf_cases[0]["power_nw"]/1000
    # A planning envelope from separately swept analog corners, not a joint PVT bound.
    high_analog_uw=max(r["supply_current_a"] for r in monitor_report["results"])*3.6e6
    high_analog_uw+=max(r["stopped_current_a"]*r["case"]["voltage"] for r in clock_report["results"])*1e6
    high_analog_uw+=max(r["power_nw"] for r in lf_report["results"])/1000
    result["analog"]=dict(nominal_monitor_ua=monitor_current*1e6,nominal_lf_nw=lf_cases[0]["power_nw"],
        nominal_fast_stopped_na=stopped_current*1e9,nominal_fast_active_ua=active_current*1e6,
        nominal_standby_uw=nominal_analog_uw,high_corner_budget_uw=high_analog_uw,
        report_sha256={str(p.relative_to(ROOT)):sha(p) for p in analog_paths})
    for variant,top in (("four-phase","FourPhaseSoc"),("click","ClickSoc")):
        directory=base/variant
        export=Path((base/(variant+"-export.txt")).read_text().strip())
        mapped,domains,memory=mapping_inventory(directory/(top+".json"),top,nominal)
        reset,reset_domains,_=mapping_inventory(directory/"riscay_reset_hold.json","riscay_reset_hold",nominal)
        mapped+=reset
        for domain in domains: domains[domain]+=reset_domains[domain]
        low,inventory,guards,cs=equivalent_primitives(primitives(export))
        high,_,_,_=equivalent_primitives(primitives(export),64,12)
        leaks={corner:{"min_uw":sum_metric(mapped+low,lib,"leak_min_uw"),
                       "mean_uw":sum_metric(mapped+low,lib,"leak_mean_uw"),
                       "max_uw":sum_metric(mapped+high,lib,"leak_max_uw")} for corner,lib in libs.items()}
        clock_per_cycle={domain:sum(n*(nominal[k]["clock_internal_pj"]+nominal[k]["clock_cap_pf"]*3.3**2)
                                   for k,n in counts.items()) for domain,counts in domains.items()}
        # Activity/slew/route margin is an explicit scenario, not a measured bound.
        # Data-dependent allowance: 1..20% complete cycles per service cycle.
        data_all=sum_metric(mapped+high,nominal,"data_cycle_pj")+sum_metric(mapped+high,nominal,"data_cap_pf")*3.3**2
        observed=read_activity(base/(variant+"-activity")/"simulation.log")
        for wake in observed.values():
            clock=(wake["fast"]*clock_per_cycle["fast"]+wake["work"]*clock_per_cycle["work"])
            async_clock=0
            for key,cell in (("event_bits","dffrnq_1"),("latch_bits","latrnq_1"),("phase_bits","dffrnq_1")):
                m=nominal[PREFIX+cell]
                async_clock+=wake[key]*(m["clock_internal_pj"]+m["clock_cap_pf"]*3.3**2)
            source_pj=active_current*3.3*wake["ns"]*1000
            wake["clock_pj"]=clock; wake["async_storage_pj"]=async_clock; wake["source_pj"]=source_pj
            wake["energy_low_nj"]=(1.10*(clock+async_clock)+0.01*data_all*wake["work"]+source_pj)/1000
            wake["energy_high_nj"]=(1.50*(clock+async_clock)+0.20*data_all*wake["work"]+source_pj)/1000
        cell_low=sum_metric(mapped+low,nominal,"area_um2")/1e6
        cell_high=sum_metric(mapped+high,nominal,"area_um2")/1e6
        core_area=[cell_low*1.10/0.60+0.233,cell_high*1.25/0.45+0.38]
        standby=[leaks["tt_025C_3v30"]["min_uw"]*1.10+nominal_analog_uw,
                 leaks["tt_025C_3v30"]["max_uw"]*1.25+nominal_analog_uw]
        # Nominal default 1000-ms intervals round to eight 7.7307-Hz ticks.
        sample_hz=7.7307/8
        average={}
        for app_hz in (0,sample_hz):
            background=7.7307-sample_hz-app_hz
            average[str(app_hz)]=[standby[i]+(background*observed["maintenance"][key]+
                sample_hz*observed["sample"][key]+app_hz*observed["firmware"][key])/1000
                for i,key in enumerate(("energy_low_nj","energy_high_nj"))]
        result["variants"][variant]=dict(mapped_cells=sum(mapped.values()),mapped_area_um2=sum_metric(mapped,nominal,"area_um2"),
            primitive_area_low_um2=sum_metric(low,nominal,"area_um2"),primitive_area_high_um2=sum_metric(high,nominal,"area_um2"),
            primitive_inventory=inventory,guards=guards,c_elements=cs,retained_memory_bits=memory,
            mapped_histogram=dict(mapped),primitive_equivalent_low=dict(low),primitive_equivalent_high=dict(high),
            clock_domain_flops={k:sum(v.values()) for k,v in domains.items()},clock_pj_per_cycle=clock_per_cycle,
            full_data_activity_pj_per_cycle=data_all,leakage=leaks,wakes=observed,
            cell_area_mm2=[cell_low,cell_high],core_and_analog_area_mm2=core_area,
            illustrative_die_area_mm2=[(math.sqrt(a)+0.8)**2 for a in core_area],
            nominal_standby_excluding_pads_uw=standby,
            hot_standby_excluding_pads_uw=[leaks["ff_125C_3v60"]["min_uw"]*1.1+high_analog_uw,
                leaks["ff_125C_3v60"]["max_uw"]*1.25+high_analog_uw],
            sample_frequency_hz=sample_hz,average_power_by_firmware_wakes_per_second_uw=average,
            inputs_sha256={p.name:sha(p) for p in (directory/(top+".json"),directory/"riscay_reset_hold.json",
                base/(variant+"-activity")/"simulation.log",export/"contract.json")})
    (base/"report.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:{x:v[x] for x in ("mapped_area_um2","primitive_area_low_um2","primitive_area_high_um2",
        "clock_domain_flops","leakage","wakes")} for k,v in result["variants"].items()},indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--liberty", type=Path, default=ROOT/".tools/physical/liberty/tt_025C_3v30.lib")
    parser.add_argument("--activity", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if not args.report and args.export is None:
        parser.error("--export is required for mapping or activity")
    if args.report and args.activity:
        parser.error("--report and --activity are mutually exclusive")
    if args.report:
        report(args.output.resolve(),args.liberty.resolve().parent)
    elif args.activity:
        activity(args.export.resolve(),args.output.resolve())
    else:
        run_mapping(args.export.resolve(),args.output.resolve(),args.liberty.resolve())
