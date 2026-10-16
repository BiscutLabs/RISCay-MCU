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
    if (mapping/'electrical-repair').exists(): raise ValueError('REPAIR_FRESH_MAPPING_REQUIRED')
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
    # Electrical repair is part of the default mapping flow. Native internals
    # remain protected; exact graph/Liberty proofs precede output publication.
    from repair_gf180_design import repair
    repair(mapping)

def audit(mapping, *, adapter_instances=None):
    """Audit native recipes at their actual instantiated modules.

    Fresh synthesis discovers the original module names. A graph-proved repair
    may supply the validated source audit's exact instance paths because the
    hierarchical writer clones module names. This never searches for a renamed
    replacement: every original path must still resolve, and its live module
    must retain the complete original cell/master/pin recipe. The caller owns
    source-audit provenance and the separate whole-graph connectivity proof.
    """
    record=json.loads((mapping/"mapping.json").read_text())
    modules=json.loads((mapping/"netlist.json").read_text())["modules"]
    hierarchy=dict(instances(modules,"RiscayMcuDigital"))
    actual=dict(leaves(modules,"RiscayMcuDigital")); counts=Counter(c["type"] for c in actual.values())
    if counts[SRAM]!=3: raise ValueError("SRAM_COUNT_MUST_BE_THREE")
    instance_ids=[i for b in record["bindings"] for i in b["instances"]]
    if len(set(instance_ids))!=len(instance_ids): raise ValueError("DUPLICATE_ADAPTER_INSTANCE")
    if adapter_instances is not None:
        if not isinstance(adapter_instances,dict) or set(adapter_instances)!=set(instance_ids):
            raise ValueError("ADAPTER_INSTANCE_INVENTORY_CHANGED")
        paths=list(adapter_instances.values())
        if any(not isinstance(path,str) or not path for path in paths):
            raise ValueError("INVALID_ADAPTER_INSTANCE_PATH")
        if len(set(paths))!=len(paths): raise ValueError("DUPLICATE_ADAPTER_INSTANCE_PATH")
    expected={}; bound={}
    for b in record["bindings"]:
        for instance in b["instances"]:
            prefix="soc/"+"/".join(instance.split('.')[1:])+"/"
            if adapter_instances is None:
                matches=[path for path,kind in hierarchy.items() if path.startswith(prefix) and kind==b["module"]]
                if len(matches)!=1: raise ValueError("AMBIGUOUS_OR_MISSING_ADAPTER_"+instance)
                path=matches[0]
            else:
                path=adapter_instances[instance]
                if not path.startswith(prefix) or path not in hierarchy:
                    raise ValueError("ORIGINAL_ADAPTER_PATH_CHANGED_"+instance)
            adapter_module=modules[hierarchy[path]]
            cells=adapter_module.get("cells",{})
            if set(cells)!={c["name"] for c in b["cells"]}:
                raise ValueError("PRESERVED_CELL_INVENTORY_CHANGED_"+path)
            def bit(net):
                if net in ("1'b0","1'b1"): return net[-1]
                match=re.fullmatch(r'(\w+)\[(\d+)\]',net)
                name,index=(match[1],int(match[2])) if match else (net,0)
                try: return adapter_module["netnames"][name]["bits"][index]
                except (KeyError,IndexError):
                    raise ValueError("PRESERVED_NET_MISSING_"+path+"/"+net) from None
            for c in b["cells"]:
                actual_cell=cells[c["name"]]
                if actual_cell["type"]!=c["cell"]:
                    raise ValueError("PRESERVED_CELL_MISSING_"+path+"/"+c["name"])
                if set(actual_cell["connections"])!=set(c["pins"]):
                    raise ValueError("PRESERVED_PIN_INVENTORY_CHANGED_"+path+"/"+c["name"])
                for p,n in c["pins"].items():
                    if actual_cell["connections"][p]!=[bit(n)]:
                        raise ValueError("PRESERVED_CONNECTION_CHANGED_"+path+"/"+c["name"]+"/"+p)
            bound[instance]=path
            root=path+"/"
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
