# SPDX-License-Identifier: Apache-2.0
"""Opt-in, source-bound buffer repair of two ordinary Control update nets.

This is a post-map experiment, not the default mapper or a timing qualification.
It adds only noninverting buffers; no native cell, guard or clock is changed.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess

from gf180_estimate import library, direct_groups, scalar, cell_metrics, linux
from gf180_physical import ROOT, SC, sha, write_json, pdk_verify
from gf180_implement import instances
from characterize_gf180_liberty import CORNERS

TARGETS = {
    "bd": ("FourPhaseStage_20", "$abc$169128$auto$blifparse.cc:386:parse_blif$169911", "nor2_1", 1759, 125),
    "click": ("ClickStage_19", "$abc$155002$auto$blifparse.cc:386:parse_blif$155552", "nor4_1", 1526, 33),
}
PREFIX = "control_load_repair_"
BUFFER = SC + "buf_4"


def require(ok, diagnostic):
    if not ok:
        raise ValueError(diagnostic)


def target(netlist, variant):
    module, driver, kind, bit, count = TARGETS[variant]
    modules = netlist["modules"]
    require([p for p, k in instances(modules, "RiscayMcuDigital") if k == module] ==
            ["soc/ca_child_control/ca_child_update"], "REPAIR_INSTANCE_BINDING")
    body = modules[module]
    cell = body["cells"][driver]
    require(cell["type"] == SC + kind and cell["connections"]["ZN"] == [bit], "REPAIR_DRIVER_BINDING")
    require(not any(bit in p["bits"] for p in body["ports"].values()), "REPAIR_PORT_ALIAS")
    sinks = []
    drivers = []
    for name, c in body["cells"].items():
        for pin, bits in c["connections"].items():
            for lane, b in enumerate(bits):
                if b != bit:
                    continue
                if c["port_directions"][pin] == "output":
                    drivers.append((name, pin, lane))
                else:
                    require((c["type"], pin) in {(SC+"mux2_1", "S"), (SC+"nor2_1", "A2"),
                                               (SC+"oai21_1", "A2")}, "REPAIR_NONORDINARY_SINK")
                    sinks.append((name, pin, lane))
    require(drivers == [(driver, "ZN", 0)] and len(sinks) == count, "REPAIR_NET_MEMBERSHIP")
    return module, bit, sorted(sinks)


def repair(before, variant):
    module, bit, sinks = target(before, variant)
    after = deepcopy(before)
    body = after["modules"][module]
    used = [b for n in body["netnames"].values() for b in n["bits"] if isinstance(b, int)]
    used += [b for p in body["ports"].values() for b in p["bits"] if isinstance(b, int)]
    used += [b for c in body["cells"].values() for bs in c["connections"].values() for b in bs if isinstance(b, int)]
    cursor = max(used) + 1
    require(not any(n.startswith(PREFIX) for n in body["cells"] | body["netnames"]), "REPAIR_ALREADY_PRESENT")

    def buffer(source, name, kind=BUFFER):
        nonlocal cursor
        out = cursor
        cursor += 1
        body["cells"][name] = dict(hide_name=0, type=kind, parameters={},
            attributes={"keep": "1", "dont_touch": "yes"}, port_directions={"I": "input", "Z": "output"},
            connections={"I": [source], "Z": [out]})
        body["netnames"][name+"_out"] = dict(hide_name=0, bits=[out], attributes={})
        return out

    root = buffer(bit, PREFIX + "root", SC+"buf_2" if variant=="click" else BUFFER)
    for group in range(0, len(sinks), 8):
        branch = buffer(root, PREFIX + f"branch_{group//8}")
        for name, pin, lane in sinks[group:group+8]:
            body["cells"][name]["connections"][pin][lane] = branch
    audit(before, after, variant)
    return after


def audit(before, after, variant):
    """Independently contract added buffers and demand exact original JSON equality.

    Also restrict edits to the enumerated ordinary input pins: contraction alone
    would otherwise permit insertion into protected/native or unrelated nets.
    """
    module, bit, sinks = target(before, variant)
    old = before["modules"][module]
    body = after["modules"][module]
    added = set(body["cells"]) - set(old["cells"])
    require(len(added) == 1 + (len(sinks)+7)//8 and all(n.startswith(PREFIX) for n in added), "REPAIR_ADDED_CELLS")
    aliases = {}
    old_bits = {b for c in old["cells"].values() for bs in c["connections"].values() for b in bs}
    old_bits.update(b for p in old["ports"].values() for b in p["bits"])
    old_bits.update(b for n in old["netnames"].values() for b in n["bits"])
    for name in added:
        c = body["cells"][name]
        kind = SC+"buf_2" if variant=="click" and name==PREFIX+"root" else BUFFER
        require(c["type"] == kind and c["parameters"] == {} and
                c["port_directions"] == {"I": "input", "Z": "output"} and
                set(c["connections"]) == {"I", "Z"} and
                all(len(x) == 1 for x in c["connections"].values()), "REPAIR_BUFFER_BINDING")
        src, dst = c["connections"]["I"][0], c["connections"]["Z"][0]
        require(isinstance(dst, int) and dst not in old_bits and dst not in aliases, "REPAIR_NEW_NET")
        aliases[dst] = src
        require(body["netnames"].get(name+"_out") == dict(hide_name=0, bits=[dst], attributes={}), "REPAIR_NETNAME")

    def contract(b):
        seen = set()
        while b in aliases:
            require(b not in seen, "REPAIR_BUFFER_CYCLE")
            seen.add(b)
            b = aliases[b]
        return b

    require(all(contract(b) == bit for b in aliases), "REPAIR_BUFFER_SOURCE")
    allowed = set(sinks)
    changed = set()
    restored = deepcopy(after)
    rb = restored["modules"][module]
    for name, oc in old["cells"].items():
        nc = rb["cells"][name]
        for pin, bits in oc["connections"].items():
            for lane, b in enumerate(bits):
                if nc["connections"][pin][lane] != b:
                    require((name, pin, lane) in allowed, "REPAIR_UNLISTED_EDIT")
                    require(nc["connections"][pin][lane] in aliases, "REPAIR_SINK_NOT_BUFFERED")
                    nc["connections"][pin][lane] = contract(nc["connections"][pin][lane])
                    changed.add((name, pin, lane))
    require(changed == allowed, "REPAIR_MISSING_SINK")
    used = {b for c in body["cells"].values() for p, bs in c["connections"].items()
            if c["port_directions"][p] == "input" for b in bs}
    require(set(aliases) <= used, "REPAIR_UNUSED_BUFFER")
    for name in added:
        del rb["cells"][name]
        del rb["netnames"][name+"_out"]
    require(restored == before, "REPAIR_ORIGINAL_GRAPH_CHANGED")
    return dict(status="exact-original-graph-after-buffer-contraction", module=module,
                original_net=bit, sinks=sinks, buffers=sorted(added))


def electrical(netlist, variant, libs):
    module, driver, _, bit, _ = TARGETS[variant]
    body = netlist["modules"][module]
    # This local check deliberately covers only the changed net/tree. The timing
    # screen separately retains unmodified stage electrical violations.
    names = [driver] + sorted(n for n in body["cells"] if n.startswith(PREFIX))
    result = {}
    for corner, lib in libs.items():
        pin_tables = {kind: dict(direct_groups(lib[kind], "pin")) for kind in
                      {c["type"] for c in body["cells"].values() if c["type"].startswith(SC)}}
        rows = []
        for name in names:
            c = body["cells"][name]
            op = "ZN" if name == driver else "Z"
            out = c["connections"][op][0]
            load = 0.0
            count = 0
            for sink in body["cells"].values():
                for pin, bits in sink["connections"].items():
                    if out in bits and sink["port_directions"][pin] == "input":
                        require(sink["type"] in pin_tables, "REPAIR_UNKNOWN_LOAD")
                        load += bits.count(out) * scalar(pin_tables[sink["type"]][pin], "capacitance")
                        count += bits.count(out)
            limit = scalar(pin_tables[c["type"]][op], "max_capacitance")
            rows.append(dict(cell=name, output=op, sinks=count, pin_load_pf=load,
                             max_capacitance_pf=limit, within_limit=load <= limit))
        result[corner] = rows
    return result


def connectivity(netlist):
    """Net-number/name-independent graph used to audit the emitted Verilog."""
    # Yosys reimports escaped private identifiers as public \$... identifiers.
    # Normalize that one documented emitter transformation, with no collisions.
    def ident(n):
        return n[1:] if n.startswith("\\$") else n

    result = {}
    for name, body in netlist["modules"].items():
        if name.startswith(SC):
            continue  # Liberty black boxes are reloaded independently.
        nets = defaultdict(list)
        ports = {}
        cells = {}
        for p, v in body["ports"].items():
            ports[p] = (v["direction"], len(v["bits"]))
            for i, b in enumerate(v["bits"]):
                nets[b].append(("port", p, i))
        for c, v in body["cells"].items():
            c = ident(c)
            require(c not in cells, "REPAIR_IDENTIFIER_COLLISION")
            cells[c] = (ident(v["type"]), v["parameters"],
                        {p:d for p,d in v["port_directions"].items() if v["connections"].get(p)})
            for p, bs in v["connections"].items():
                for i, b in enumerate(bs):
                    nets[b].append(("cell", c, p, i))
        require(ident(name) not in result, "REPAIR_IDENTIFIER_COLLISION")
        result[ident(name)] = dict(ports=ports, cells=cells,
            nets=sorted((str(b) if isinstance(b, str) else "wire", sorted(ps)) for b, ps in nets.items()))
    return result


def run(mapping, output, variant, pdk):
    require(not output.exists(), "REPAIR_OUTPUT_EXISTS")
    pdk_verify(pdk)
    yosys = ROOT/".tools/physical/root/usr/bin/yosys"
    inputs = [mapping/f for f in ("netlist.json", "netlist.v", "mapping.json", "netlist-audit.json")]
    inputs += [pdk/(SC+c+".lib") for c in CORNERS]
    inputs += [yosys] + [ROOT/"tools"/f for f in ("repair_gf180_control.py", "gf180_estimate.py",
                "gf180_physical.py", "gf180_implement.py", "characterize_gf180_liberty.py")]
    frozen = {str(p.resolve()):sha(p) for p in inputs}
    before = json.loads((mapping/"netlist.json").read_text())
    source_audit = json.loads((mapping/"netlist-audit.json").read_text())
    require(source_audit["status"] == "pass" and source_audit["netlist_sha256"] == sha(mapping/"netlist.v") and
            source_audit["mapping_sha256"] == sha(mapping/"mapping.json"), "REPAIR_STALE_SOURCE_AUDIT")
    # JSON/Verilog consistency is checked below for BOTH the input and output.
    after = repair(before, variant)
    libs = {c: library(pdk/(SC+c+".lib")) for c in CORNERS}
    pre, post = electrical(before, variant, libs), electrical(after, variant, libs)
    require(all(r["within_limit"] for rows in post.values() for r in rows), "REPAIR_CAPACITANCE_LIMIT")
    proof = audit(before, after, variant)
    output.mkdir(parents=True)
    write_json(output/"netlist.json", after)
    write_json(output/"blackboxes.json", dict(modules={n:b for n,b in before["modules"].items()
               if not n.startswith(SC) and int(b.get("attributes", {}).get("blackbox", "0"), 2)}))
    script = f'read_json {linux(output/"netlist.json")}\nwrite_verilog -norename -noattr -noexpr {linux(output/"netlist.v")}\n'
    for side, path in (("before", mapping), ("after", output)):
        script += f'design -reset\nread_liberty -lib {linux(pdk/(SC+"tt_025C_3v30.lib"))}\n'
        script += f'read_json {linux(output/"blackboxes.json")}\n'
        script += f'read_verilog {linux(path/"netlist.v")}\nhierarchy -check -top RiscayMcuDigital\n'
        script += f'write_json {linux(output/(side+"-roundtrip.json"))}\n'
    (output/"emit.ys").write_text(script)
    with (output/"emit.log").open("w") as stream:
        subprocess.run(["wsl", "-e", linux(yosys), "-s", linux(output/"emit.ys")],
                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
    for side, expected in (("before", before), ("after", after)):
        actual = json.loads((output/(side+"-roundtrip.json")).read_text())
        require(connectivity(actual) == connectivity(expected), "REPAIR_VERILOG_GRAPH_MISMATCH_"+side)
    metrics = [cell_metrics(libs[CORNERS[0]][after["modules"][proof["module"]]["cells"][n]["type"]])
               for n in proof["buffers"]]
    require(all(sha(Path(p)) == h for p,h in frozen.items()), "REPAIR_INPUT_CHANGED_DURING_RUN")
    n = len(proof["buffers"])
    receipt = dict(schema="riscay-control-electrical-repair-v1", status="repaired-unqualified", variant=variant,
        source=str(mapping.resolve()), graph_proof=proof, before_electrical=pre, after_electrical=post,
        inputs_sha256=frozen,
        added_cells=n, added_area_um2=sum(m["area_um2"] for m in metrics),
        added_tt_leakage_uw={k:sum(m[k] for m in metrics) for k in ("leak_min_uw", "leak_mean_uw", "leak_max_uw")},
        source_sha256={f:sha(mapping/f) for f in ("netlist.json", "netlist.v", "mapping.json", "netlist-audit.json")},
        files_sha256={f:sha(output/f) for f in ("netlist.json", "netlist.v", "emit.ys", "emit.log")},
        liberty_sha256={c:sha(pdk/(SC+c+".lib")) for c in CORNERS}, yosys_sha256=sha(yosys),
        tool_sha256=sha(Path(__file__)), limitations=["No wire parasitics", "No timing or slew acceptance yet",
            "Unchanged native cells, guards and RTL", "Not integrated into default mapping/P&R"])
    write_json(output/"repair.json", receipt)
    print(json.dumps({k:receipt[k] for k in ("variant", "status", "added_cells", "added_area_um2", "added_tt_leakage_uw")}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mapping", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--variant", required=True, choices=TARGETS)
    p.add_argument("--pdk", type=Path, default=ROOT/".tools/physical/pdk")
    args = p.parse_args()
    run(args.mapping, args.output, args.variant, args.pdk)
