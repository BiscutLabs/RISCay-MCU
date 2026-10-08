# SPDX-License-Identifier: Apache-2.0
"""Synthesize the candidate digital top; audit all physical leaf instances."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
from gf180_physical import ROOT, SC, SRAM, pdk_verify, sha, write_json
from gf180_estimate import linux

def run(command,log,timeout=600):
    with log.open("w") as stream:
        subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=timeout)

def leaves(modules,top,prefix=""):
    for name,cell in modules[top].get("cells",{}).items():
        path=prefix+name
        if cell["type"].startswith(SC) or cell["type"]==SRAM:
            yield path,cell
        elif cell["type"] in modules:
            yield from leaves(modules,cell["type"],path+"/")
        else: raise ValueError("UNMAPPED_CELL_"+cell["type"])

def instances(modules,top,prefix=""):
    for name,cell in modules[top].get("cells",{}).items():
        path=prefix+name
        yield path,cell["type"]
        if cell["type"] in modules and not cell["type"].startswith(SC) and cell["type"]!=SRAM:
            yield from instances(modules,cell["type"],path+"/")

def synth(mapping,pdk):
    pdk_verify(pdk)
    record=json.loads((mapping/"mapping.json").read_text())
    for f,h in record["files_sha256"].items():
        if sha(mapping/f)!=h: raise ValueError("MAPPED_INPUT_CHANGED_"+f)
    files=[mapping/x for x in (mapping/"filelist.f").read_text().splitlines()]
    lib=pdk/(SC+"tt_025C_3v30.lib")
    # Normalize time-typed parameters with sv2v. No library simulation view.
    run(["wsl","-e",linux(ROOT/".tools/physical/sv2v"),"-DSYNTHESIS",*map(linux,files)],mapping/"converted.v",120)
    script=f'read_liberty -lib {linux(lib)}\nread_verilog -defer -sv {linux(mapping/"converted.v")}\n'
    script+='hierarchy -check -top RiscayMcuDigital\nsynth -top RiscayMcuDigital -noabc\n'
    script+=f'dfflibmap -liberty {linux(lib)}\n'
    script+=f'abc -exe {linux(ROOT/".tools/physical/root/usr/bin/yosys-abc")} -liberty {linux(lib)}\n'
    script+=f'clean\ncheck\nstat -liberty {linux(lib)}\nwrite_json {linux(mapping/"netlist.json")}\n'
    script+=f'write_verilog -norename -noattr -noexpr {linux(mapping/"netlist.v")}\n'
    (mapping/"synth.ys").write_text(script)
    run(["wsl","-e",linux(ROOT/".tools/physical/root/usr/bin/yosys"),"-s",linux(mapping/"synth.ys")],mapping/"synth.log")
    audit(mapping)

def audit(mapping):
    record=json.loads((mapping/"mapping.json").read_text())
    modules=json.loads((mapping/"netlist.json").read_text())["modules"]
    hierarchy=dict(instances(modules,"RiscayMcuDigital"))
    actual=dict(leaves(modules,"RiscayMcuDigital")); counts=Counter(c["type"] for c in actual.values())
    if counts[SRAM]!=3: raise ValueError("SRAM_COUNT_MUST_BE_THREE")
    expected={}; bound={}
    for b in record["bindings"]:
        adapter_module=modules[b["module"]]
        def bit(net):
            if net in ("1'b0","1'b1"): return net[-1]
            match=re.fullmatch(r'(\w+)\[(\d+)\]',net)
            name,index=(match[1],int(match[2])) if match else (net,0)
            return adapter_module["netnames"][name]["bits"][index]
        for c in b["cells"]:
            actual_cell=adapter_module["cells"][c["name"]]
            for p,n in c["pins"].items():
                if actual_cell["connections"][p]!=[bit(n)]:
                    raise ValueError("PRESERVED_CONNECTION_CHANGED_"+b["module"]+"."+c["name"]+"."+p)
        for instance in b["instances"]:
            prefix="soc/"+"/".join(instance.split('.')[1:])+"/"
            matches=[path for path,kind in hierarchy.items() if path.startswith(prefix) and kind==b["module"]]
            if len(matches)!=1: raise ValueError("AMBIGUOUS_OR_MISSING_ADAPTER_"+instance)
            bound[instance]=matches[0]
            root=matches[0]+"/"
            for c in b["cells"]: expected[root+c["name"]]=c["cell"]
    # Yosys generates a dot inside each generate-block instance name. Match
    # exact names; no wildcard/count-only audit can detect a shortened chain.
    for path,kind in expected.items():
        if path not in actual or actual[path]["type"]!=kind: raise ValueError("PRESERVED_CELL_MISSING_"+path)
    pins=[path+"/"+pin for path,c in actual.items() for pin in c["connections"]]
    write_json(mapping/"netlist-audit.json",dict(status="pass",leaf_cells=len(actual),sram_count=counts[SRAM],
        preserved_async_cells=len(expected),cell_counts=dict(counts),leaf_pins=pins,adapter_instances=bound,
        mapping_sha256=sha(mapping/"mapping.json"),netlist_sha256=sha(mapping/"netlist.v")))
    print(f"PASS {len(actual)} physical cells; {len(expected)} preserved async cells; three SRAMs")

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("mapping",type=Path)
    p.add_argument("--pdk",type=Path,default=ROOT/".tools/physical/pdk"); p.add_argument("--audit-only",action="store_true")
    a=p.parse_args(); audit(a.mapping) if a.audit_only else synth(a.mapping,a.pdk)
