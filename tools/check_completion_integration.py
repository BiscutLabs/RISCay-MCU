# SPDX-License-Identifier: Apache-2.0
"""Strict mapping obligations at the clocked/native completion boundary."""
import re


def completion_bridges(manifest):
    top = manifest.get("top")
    if top not in ("FourPhaseSoc", "ClickSoc"):
        return {}
    children = {c["id"]: c["contract"] for c in manifest["design"].get("children", [])}
    names = {"completion_"+n+"_bridge" for n in ("plan", "memory", "telemetry", "housekeeping")}
    found = names & children.keys()
    if not found:
        return {}
    if found != names:
        raise ValueError("COMPLETION_BRIDGE_INVENTORY")
    prefix = "DecoupledToClick" if top == "ClickSoc" else "DecoupledToFourPhase"
    protocol = "two-phase-bundled-v1" if top == "ClickSoc" else "four-phase-bundled-v1"
    for name in names:
        node = children[name]
        if (not re.fullmatch(prefix+r"(?:_[0-9]+)?", node["module"]) or
                node["rtl_path"] != top+".ca_child_"+name or
                {c["id"]: (c["protocol"], c["role"]) for c in node["channels"]} !=
                {"in": ("decoupled-v1", "input"), "out": (protocol, "output")}):
            raise ValueError("COMPLETION_BRIDGE_OWNER")
    return {name: children[name] for name in names}


def completion_constants_probe(source, manifest, scopes, top_rtl):
    """Replace impossible polarity coverage ONLY for three literal input leaves.

    Require their exact values on every check. All dynamic bits keep both-polarity
    coverage; storage outputs, native inputs, comparisons and drivers are untouched.
    The public schema and elaborated scalar leaf must agree before applying a mask.
    """
    bridges = completion_bridges(manifest)
    if not bridges:
        return source
    comparisons = []
    for name, width, pin, value, layout in (
            ("memory", 33, "in_bits_error", 0, [("bits.error", 0, 1), ("bits.data", 1, 32)]),
            ("telemetry", 1, "in_bits", 1, [("bits", 0, 1)]),
            ("housekeeping", 1, "in_bits", 1, [("bits", 0, 1)])):
        node = bridges["completion_"+name+"_bridge"]
        channel = next(c for c in node["channels"] if c["id"] == "in")
        fields = [(f["field"], f["lsb"], f["width"]) for f in channel["layout"]]
        endpoints = {e["id"]: e for e in node["endpoints"]}
        path = node["rtl_path"]
        if (channel.get("data") != "in_data" or fields != layout or
                any(f["signed"] for f in channel["layout"]) or
                endpoints.get("in_data", {}).get("width") != width or
                scopes.get(path, {}).get("ports", {}).get(pin) !=
                dict(name=pin, width=1, direction="input")):
            raise ValueError("COMPLETION_CONSTANT_SCHEMA")
        # The pinned emitter emits one named instance per line and a closing
        # `);` on its own line. Reject changed syntax instead of inferring a
        # constant from finite simulation samples of a potentially dynamic net.
        clean = re.sub(r"/\*.*?\*/|//[^\n]*", "", top_rtl, flags=re.S)
        instance = path.rsplit(".", 1)[1]
        blocks = list(re.finditer(r"^\s*(\w+)\s+"+re.escape(instance)+r"\s*\((.*?)^\s*\);", clean, re.M | re.S))
        if (len(blocks) != 1 or blocks[0][1] != scopes[path]["model"]):
            raise ValueError("COMPLETION_CONSTANT_INSTANCE")
        bindings = re.findall(r"\."+pin+r"\s*\(([^()]*)\)", blocks[0][2])
        if bindings != [f"1'h{value}"]:
            raise ValueError("COMPLETION_CONSTANT_LITERAL:"+name)
        endpoint = endpoints["in_data"]["rtl_path"]
        comparisons.append(f'if ({path}.{pin} !== 1\'h{value}) $fatal(1,"COMPLETION_CONSTANT_BINDING:{name}");')
        # Also assert the corresponding packed endpoint bit, independent of aliases.
        bit = endpoint+"[0]" if width > 1 else endpoint
        comparisons.append(f'if ({bit} !== {path}.{pin}) $fatal(1,"COMPLETION_CONSTANT_ENDPOINT:{name}");')
        full = (1 << width)-1
        pattern = (r"^if \(ones_(\d+) !== "+str(width)+"'h"+f"{full:x}"+
                   r" \|\| zeros_\1 !== "+str(width)+"'h"+f"{full:x}"+
                   r'\) \$fatal\(1, "INACTIVE_ENDPOINT:'+re.escape(endpoint)+r'"\);$')
        matches = list(re.finditer(pattern, source, re.M))
        if len(matches) != 1:
            raise ValueError("COMPLETION_CONSTANT_COVERAGE_SHAPE")
        match = matches[0]; index = match[1]
        ones, zeros = (full if value else full ^ 1), (full ^ 1 if value else full)
        replacement = (f"if (ones_{index} !== {width}'h{ones:x} || zeros_{index} !== {width}'h{zeros:x}) "
                       f'$fatal(1, "INACTIVE_ENDPOINT:{endpoint}");')
        source = source[:match.start()] + replacement + source[match.end():]
    anchor = "task check; begin"
    if source.count(anchor) != 1:
        raise ValueError("COMPLETION_CONSTANT_PROBE_SHAPE")
    return source.replace(anchor, anchor+"\n"+"\n".join(comparisons))


def completion_background(source, manifest, scopes, checks):
    """Append joint acceptance/publication scenarios using catalogued registers.

    Each scenario starts at the original all-zero source header. No derived port,
    endpoint, activity counter, native combinational signal or constant is forced.
    """
    if not completion_bridges(manifest):
        return source, checks
    top = manifest["top"]
    anchor = f"initial begin\nforce {top}.reset = 1'b1; #1;\n"
    if source.count(anchor) != 1:
        raise ValueError("COMPLETION_BACKGROUND_SHAPE")
    start = source.index(anchor)+len(anchor)
    end = source.index("\n#1;\n", start)+len("\n#1;\n")
    header = source[start:end]
    coverage = list(re.finditer(r"^if \(ones_\d+ !==.*INACTIVE_ENDPOINT:.*$", source, re.M))
    marker = f"CONTRACT_PROBES_PASS:{checks}"
    if not coverage or source.count(marker) != 1:
        raise ValueError("COMPLETION_BACKGROUND_SHAPE")
    extra, steps = [], 0

    def force(path, width, value, primitive=False):
        node, field = path.rsplit(".", 1)
        source_valid = (scopes.get(node, {}).get("ports", {}).get(field) == dict(name=field,width=width,direction="output")) if primitive else (
            scopes.get(node, {}).get("registers", {}).get(field) == width)
        if (not source_valid or
                f"force {path} = {width}'h0;" not in header):
            raise ValueError("COMPLETION_BACKGROUND_DRIVER")
        if not 0 <= value < 1 << width:
            raise ValueError("COMPLETION_BACKGROUND_RANGE")
        extra.append(f"force {path} = {width}'h{value:x};\n")

    def check():
        nonlocal steps
        extra.append("#1; check;\n"); steps += 1

    def walk(width):
        return [0, (1 << width)-1] + [v for bit in range(width)
            for v in (1 << bit, ((1 << width)-1) ^ (1 << bit))]

    if top == "ClickSoc":
        # Generic one-hot/one-cold walks of a two-bit register never produce
        # 11. Exercise the real reset-release source, including its AND-reduced
        # startup state; never force Admission.start or relax its coverage.
        extra.append(header)
        for value in (0, 1, 2, 3):
            force(top+".ca_child_admission_start_stages", 2, value); check()

    request = top+".ca_child_request_bridge"
    control = top+".ca_child_control_reply_bridge"

    def plan(operation, address, mmio=False):
        extra.append(header)
        force(top+".gate_enabled", 1, 1)
        force(top+".fabric_io_completionIdle_REG", 1, 1)
        force(top+".ca_child_admission_grant_bridge.state", 2, 2)
        for bank in ("program", "ram"):
            for group in ("returned_stages", "bytesReturned_stages", "bytesReturned_stages_1",
                          "bytesReturned_stages_2", "bytesReturned_stages_3"):
                for stage in (0, 1):
                    force(top+f".ca_child_{bank}_access.{group}_{stage}", 1, 1)
        force(request+".state", 2, 2)
        force(request+".data_mask", 4, 15)
        force(request+".data_operation", 2, operation)
        force(request+".data_address", 32, address)
        if address == 0x20000000:
            force(top+".ca_child_ram_grant_bridge.state", 2, 2)
        if mmio:
            force(top+".fabric_controlOutstanding", 1, 1)
            force(top+".fabric_mmioCurrent", 1, 1)
            force(control+".state", 2, 2)
            force(control+".data_kind", 3, 4)
        check()

    plan(1, 0x30000004, True)
    for value in walk(32):
        force(control+".data_memory_data", 32, value); check()
    force(control+".data_memory_error", 1, 1); check()
    plan(1, 0x20000000)
    plan(2, 0x30000008, True)
    extra.append(header)
    # RAM completion eligibility now belongs to its native reservation owner.
    owner=next(c["contract"] for c in manifest["design"]["children"] if c["id"]=="ram_source")
    cell=next(p for p in owner["primitives"] if p["id"]=="eligibility")
    if cell["model"]!="ChiselAsyncEventRegister_v1" or cell["parameters"].get("WIDTH")!="1":
        raise ValueError("COMPLETION_RAM_ELIGIBILITY_OWNER")
    force(cell["rtl_path"]+".q", 1, 1, primitive=True)
    force(top+".ca_child_ram_access.active", 1, 1)
    memory = top+".ca_child_ram_access.ca_child_reply_bridge"
    force(memory+".state", 2, 2)
    for value in walk(32):
        force(memory+".data", 32, value); check()
    for name, field, width in (("telemetry", "data_kind", 2), ("housekeeping", "data_cpuCompletion", 1)):
        extra.append(header)
        force(top+f".fabric_{name}Outstanding", 1, 1)
        force(top+f".fabric_{name}CpuPending", 1, 1)
        force(top+f".ca_child_{name}_reply_bridge.state", 2, 2)
        force(top+f".ca_child_{name}_reply_bridge.{field}", width, 1); check()
    count = checks+steps*len(coverage)
    position = coverage[0].start()
    result = source[:position]+"".join(extra)+source[position:]
    return result.replace(marker, f"CONTRACT_PROBES_PASS:{count}"), count
