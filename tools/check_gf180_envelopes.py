# SPDX-License-Identifier: Apache-2.0
"""Conservative async guard feasibility using measured PVT cell envelopes.

This proves the prelayout envelopes fit the selected protocol inequalities.
Extracted interconnect, keeper behavior and event coverage remain independent.
"""
import argparse
import json
import math
from pathlib import Path
from gf180_physical import nodes, sha, write_json

def strict(available,required,name):
    if not all(math.isfinite(x) and x>=0 for x in (available,required)) or available<=required:
        raise ValueError("RELATIVE_ENVELOPE_FAILED_"+name)
    return dict(check=name,available_ns=available,required_ns=required,margin_ns=available-required)

def run(mapping,pvt,stages,output):
    record=json.loads((mapping/"mapping.json").read_text())
    measurements=json.loads((pvt/"results.json").read_text())
    data=json.loads((stages/"results.json").read_text())
    if measurements["mapping_sha256"]!=sha(mapping/"mapping.json") or measurements["status"]!="bounds-pass":
        raise ValueError("UNQUALIFIED_OR_STALE_CELL_ENVELOPES")
    if data["netlist_sha256"]!=sha(mapping/"netlist.v") or data["status"]!="pass":
        raise ValueError("UNQUALIFIED_OR_STALE_DATA_PATHS")
    results={r["module"]:r for r in measurements["adapters"]}
    bypath={i:results[b["module"]] for b in record["bindings"] for i in b["instances"]}
    manifest=json.loads((mapping/"timing-intent.json").read_text())["manifest"]
    checks=[]
    for node in nodes(manifest["design"]):
        cells={p["id"]:bypath[p["rtl_path"]] for p in node["primitives"] if p["rtl_path"] in bypath}
        for t in node["timing"]:
            name=node["rtl_path"]
            if t["kind"]=="click-bundling-v1":
                ns=lambda key:int(t["times"][key])/1e6
                phase=[cells[k] for k in ("input_phase","output_phase") if k in cells]
                compare=[cells[k] for k in ("input_compare","output_compare")]
                feedback=min(p["minimum_ns"] for p in phase)+min(p["minimum_ns"] for p in compare)+cells["fire"]["minimum_ns"]
                settled=ns("CLOCK_SKEW_FS")+max(p["maximum_ns"] for p in phase)+max(p["maximum_ns"] for p in compare)+cells["fire"]["maximum_ns"]
                checks.append(strict(feedback,ns("PULSE_HIGH_FS")+ns("CLOCK_SKEW_FS"),name+".pulse_high"))
                for guard in ("acknowledge_guard","output_guard"):
                    checks.append(strict(cells[guard]["minimum_ns"],settled+ns("PULSE_LOW_FS"),name+"."+guard+".low"))
                checks.append(strict(cells["acknowledge_guard"]["minimum_ns"],ns("CLOCK_SKEW_FS")+ns("HOLD_FS"),name+".hold"))
                checks.append(strict(cells["output_guard"]["minimum_ns"],ns("CLOCK_SKEW_FS")+cells["payload"]["maximum_ns"],name+".visibility"))
                checks.append(strict(cells["request_delay"]["minimum_ns"],int(t["cells"]["data_delay"]["max_fs"])/1e6+ns("SETUP_FS"),name+".setup"))
            elif t["kind"]=="long-hold-bundling-v2":
                checks.append(strict(cells["request_delay"]["minimum_ns"],int(t["data_delay"]["max_fs"])/1e6+8,name+".setup"))
                # Use declared controller/storage bounds, not a favorable
                # correlated-corner pairing. Latch closure is included in 10 ns.
                checks.append(strict(cells["output_delay"]["minimum_ns"],30,name+".offer"))
        if "request_guard" in cells and "register_arrival" in cells:
            registers=next(c["contract"] for c in node["children"] if c["id"]=="register_file")
            select=[bypath[p["rtl_path"]]["maximum_ns"] for p in registers["primitives"] if p["id"].startswith("select")]
            banks=[bypath[p["rtl_path"]]["maximum_ns"] for p in registers["primitives"] if p["id"].startswith("x")]
            checks.append(strict(cells["request_guard"]["minimum_ns"],cells["register_arrival"]["maximum_ns"]+max(select)+max(banks),node["rtl_path"]+".writeback"))
    expected={"bd":11,"click":31}.get(record["variant"])
    if len(checks)!=expected: raise ValueError("MISSING_RELATIVE_ENVELOPES")
    write_json(output,dict(status="prelayout-envelopes-pass",checks=checks,
        mapping_sha256=sha(mapping/"mapping.json"),pvt_sha256=sha(pvt/"results.json"),stages_sha256=sha(stages/"results.json"),
        pending=["routed branch/clock/data wiring", "extracted pulse/aperture/reset behavior", "CDC and electrical closure"]))
    print(f'PASS {len(checks)} conservative relative envelopes; routed checks pending')

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("mapping","pvt","stages","output"): p.add_argument(name,type=Path)
    a=p.parse_args(); run(a.mapping,a.pvt,a.stages,a.output)
