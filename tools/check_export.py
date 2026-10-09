# SPDX-License-Identifier: Apache-2.0
"""Run chisel-async export checks with MCU timeout/generated-reset support.

The library defaults to 60 seconds, which its small component probes fit. This
adapter extends the contract probe's compilation and simulation limits. With
--soc it checks CPU child resets against the generated system-reset endpoint and
the named persistent Control children against POR. All endpoint/timing/coverage
checks are retained.
The library checkout is an explicit development dependency.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import re
import json
import hashlib


def sram_array_shapes(contents, scopes):
    """Icarus prints the upstream descending array as `0 1023`, whereas the
    library's SyncReadMem parser handles `1023 0`. Admit that spelling only
    inside this named technology macro; shape/view validation still follows.
    """
    model = "gf180mcu_ocd_ip_sram__sram1024x8m8wm1"
    blocks = re.finditer(r'^S_\w+ \.scope module, "([^"]+)" "' + model +
                         r'" [^\n]*;\n(.*?)(?=^S_\w+ \.scope |\Z)', contents, re.M | re.S)
    for block in blocks:
        paths = [path for path, scope in scopes.items()
                 if scope["model"] == model and path.rsplit(".", 1)[-1] == block[1]]
        if len(paths) != 1:
            raise ValueError("AMBIGUOUS_SRAM_SCOPE")
        arrays = re.findall(r'^v\w+ \.array "(\w+)", 0 (\d+), (\d+) 0;', block[2], re.M)
        for name, high, bits in arrays:
            scopes[paths[0]]["memories"][name] = (int(high) + 1, int(bits) + 1)
    return scopes


def sram_scopes(directory, node, scopes):
    """Admit only pinned GF180 macros, with an explicit physical inventory.

    Keep the library's closed module inventory and all async probes intact.
    This validates macro identity/shape, not physical timing or memory behavior.
    """
    if "." in node["rtl_path"]:
        return set()
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "soc/sram-lock.json").read_text())
    model = lock["macro"]
    present = {path for path, scope in scopes.items() if scope["model"] == model}
    inventory = directory / "sram.json"
    if not present and not inventory.exists():
        return set()  # Standalone CPU exports have no SoC SRAM.
    if not inventory.exists():
        raise ValueError("MISSING_SRAM_INVENTORY")
    data = json.loads(inventory.read_text())
    if (set(data) != {"schema", "macro", "program_bytes", "working_ram_bytes", "instances"}
            or data["schema"] != "riscay-gf180-sram-v1" or data["macro"] != model):
        raise ValueError("INVALID_SRAM_INVENTORY")
    expected = []
    for bank, key in (("program", "program_bytes"), ("ram", "working_ram_bytes")):
        size = data[key]
        if type(size) is not int or size <= 0 or size % 4:
            raise ValueError("INVALID_SRAM_CAPACITY")
        expected += [dict(path=f'{node["rtl_path"]}.fabric_{bank}_macros_{i}', bank=bank, index=i)
                     for i in range((size + 1023) // 1024)]
    if data["instances"] != expected or present != {x["path"] for x in expected}:
        raise ValueError("SRAM_INSTANCE_MISMATCH")
    def view(suffix):
        name = model + suffix
        raw = (root / "soc/src/main/resources/riscay/sram" / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != lock["assets"][name]["sha256"]:
            raise ValueError("SRAM_UPSTREAM_HASH_MISMATCH")
        return raw.decode().replace("\r\n", "\n")
    behavior = view(".v")
    if behavior.count("mem[i] = 8'd0;") != 1:
        raise ValueError("SRAM_MODEL_INITIALIZER_CHANGED")
    expected_source = ("`ifdef SYNTHESIS\n" + view(".blackbox.v") + "\n`else\n" +
                       behavior.replace("mem[i] = 8'd0;", "mem[i] = 8'bx;") + "\n`endif\n")
    actual = (directory / (model + ".sv")).read_text().split("\n", 1)[1]
    if actual.strip() != expected_source.strip():
        raise ValueError("SRAM_EMITTED_VIEW_MISMATCH")
    pins = {name: dict(name=name, width=width, direction="output" if name == "Q" else "input")
            for name, width in (("CLK",1), ("CEN",1), ("GWEN",1), ("WEN",8), ("A",10), ("D",8), ("Q",8))}
    for path in present:
        if scopes[path]["ports"] != pins or scopes[path]["memories"] != {"mem": (1024, 8)}:
            raise ValueError("SRAM_ELABORATED_SHAPE_MISMATCH")
    return present


def probe_timeout(command, original, simulation, compilation):
    """Extend only the generated probe, not unrelated commands or RTL checks."""
    if not isinstance(command, (list, tuple)) or len(command) < 2:
        return original
    executable = Path(command[0]).stem
    if executable == "vvp" and command[1] == "contract_probe.vvp":
        return simulation
    if (executable == "iverilog" and "contract_probe.sv" in command and
            any(command[i] == "-o" and command[i+1] == "contract_probe.vvp" for i in range(len(command)-1))):
        return compilation
    return original


def sleep_clock_background(source: str, manifest: dict, scopes: dict, checks: int):
    """Append an existing single-driver campaign with the gate enable held high.

    The library's all-low background closes the gate; its all-high background
    asserts responseValid and blocks new acceptance. Keep both campaigns intact
    and add a third. This forces only a native register already in the library's
    driver inventory, never a derived endpoint. The paired fallback is retained.
    """
    top = manifest["top"]
    if scopes.get(top, {}).get("registers", {}).get("gate_enabled") != 1:
        raise ValueError("SLEEP_GATE_REGISTER_MISMATCH")
    anchor = f"initial begin\nforce {top}.reset = 1'b1; #1;\n"
    if source.count(anchor) != 1:
        raise ValueError("SLEEP_PROBE_SHAPE_CHANGED")
    start = source.index(anchor) + len(anchor)
    header_end = source.index("\n#1;\n", start) + len("\n#1;\n")
    zero_header = source[start:header_end]
    one_header = re.sub(r"(force \S+ = 1'h)0;", r"\g<1>1;", zero_header)
    if source.count(one_header) != 1 or one_header == zero_header:
        raise ValueError("SLEEP_PROBE_SHAPE_CHANGED")
    end = source.index(one_header)
    campaign = source[start:end]
    gate = f"force {top}.gate_enabled = 1'h0;"
    if gate not in zero_header or end <= start:
        raise ValueError("SLEEP_GATE_DRIVER_MISSING")
    coverage = list(re.finditer(r"^if \(ones_\d+ !==.*INACTIVE_ENDPOINT:.*$", source, re.M))
    steps = campaign.count("#1; check;")
    completion = f"CONTRACT_PROBES_PASS:{checks}"
    if not coverage or not steps or source.count(completion) != 1:
        raise ValueError("SLEEP_PROBE_SHAPE_CHANGED")
    additional = campaign.replace(gate, f"force {top}.gate_enabled = 1'h1;")
    count = checks + steps * len(coverage)
    position = coverage[0].start()
    result = source[:position] + additional + source[position:]
    return result.replace(completion, f"CONTRACT_PROBES_PASS:{count}"), count


def register_file_background(source: str, manifest: dict, checks: int):
    """Exercise operand muxes with a nonzero bank and a valid register index.

    The library backgrounds zero wide data drivers, and its paired fallback
    uses only 1/all-ones values. Neither selects a valid RV32E source field
    while another wide driver holds register data. Add the original bit walk
    with x1 prefilled. Force only a catalogued primitive output, never an
    endpoint, operand mux or decoder. Keep all original checks and campaigns.
    """
    def nodes(node):
        yield node
        for child in node.get("children", []):
            yield from nodes(child["contract"])
    banks = []
    for node in nodes(manifest["design"]):
        if node.get("module") == "ArchitecturalRegisters":
            bank = next((p for p in node["primitives"] if p["id"] == "x1"), None)
            if bank is None or not any(p["name"] == "q" and p["direction"] == "output" and p["width"] == 32
                                      for p in bank["ports"]):
                raise ValueError("REGISTER_FILE_DRIVER_MISMATCH")
            banks.append(bank["rtl_path"] + ".q")
    if not banks:
        return source, checks
    anchor = f"initial begin\nforce {manifest['top']}.reset = 1'b1; #1;\n"
    if source.count(anchor) != 1:
        raise ValueError("REGISTER_FILE_PROBE_SHAPE_CHANGED")
    start = source.index(anchor) + len(anchor)
    header_end = source.index("\n#1;\n", start) + len("\n#1;\n")
    header = source[start:header_end]
    ones = re.sub(r"(force \S+ = 1'h)0;", r"\g<1>1;", header)
    if ones == header or source.count(ones) != 1:
        raise ValueError("REGISTER_FILE_PROBE_SHAPE_CHANGED")
    campaign = source[start:source.index(ones)]
    coverage = list(re.finditer(r"^if \(ones_\d+ !==.*INACTIVE_ENDPOINT:.*$", source, re.M))
    steps = campaign.count("#1; check;")
    completion = f"CONTRACT_PROBES_PASS:{checks}"
    if not coverage or not steps or source.count(completion) != 1:
        raise ValueError("REGISTER_FILE_PROBE_SHAPE_CHANGED")
    extra = ""
    for bank in banks:
        driver = f"force {bank} = 32'h0;"
        if driver not in header:
            raise ValueError("REGISTER_FILE_DRIVER_MISSING")
        extra += campaign.replace(driver, f"force {bank} = 32'hffffffff;")
    count = checks + steps * len(coverage) * len(banks)
    position = coverage[0].start()
    result = source[:position] + extra + source[position:]
    return result.replace(completion, f"CONTRACT_PROBES_PASS:{count}"), count


def control_background(source: str, manifest: dict, scopes: dict, checks: int):
    """Exercise native command decodes using only catalogued storage outputs.

    Single-bit and all-ones paired backgrounds do not form valid frame lengths,
    opcodes or MMIO addresses. Keep those campaigns and all coverage/comparisons;
    add explicit input vectors, never forces of endpoints or combinational muxes.
    """
    root = manifest["design"]
    controls = [c["contract"] for c in root.get("children", []) if c["id"] == "control"]
    if not controls:
        return source, checks
    top = manifest["top"]
    click = top == "ClickSoc"
    owner = "ClickControl" if click else "FourPhaseControl"
    if len(controls) != 1 or controls[0]["module"] != owner:
        raise ValueError("CONTROL_PROBE_OWNER_MISMATCH")
    join = next((c["contract"] for c in controls[0]["children"] if c["id"] == "join"), None)
    if join is None:
        raise ValueError("CONTROL_PROBE_DRIVER_MISMATCH")
    def payload(child, width):
        node = next((c["contract"] for c in join["children"] if c["id"] == child), {})
        cell = next((p for p in node.get("primitives", []) if p["id"] == "payload"), {})
        if not any(p == {"name": "q", "width": width, "direction": "output"}
                   for p in cell.get("ports", [])):
            raise ValueError("CONTROL_PROBE_DRIVER_MISMATCH")
        return cell["rtl_path"] + ".q"
    state = payload("left_storage" if click else "left", 305)
    command = payload("right_storage" if click else "right", 379)
    request = top + ".ca_child_request_bridge.data_address"
    now = top + ".fabric_now"
    for path, width in ((request, 32), (now, 32)):
        node, name = path.rsplit(".", 1)
        if scopes.get(node, {}).get("registers", {}).get(name) != width:
            raise ValueError("CONTROL_PROBE_DRIVER_MISMATCH")
    anchor = f"initial begin\nforce {top}.reset = 1'b1; #1;\n"
    if source.count(anchor) != 1:
        raise ValueError("CONTROL_PROBE_SHAPE_CHANGED")
    start = source.index(anchor) + len(anchor)
    end = source.index("\n#1;\n", start) + len("\n#1;\n")
    header = source[start:end]
    coverage = list(re.finditer(r"^if \(ones_\d+ !==.*INACTIVE_ENDPOINT:.*$", source, re.M))
    completion = f"CONTRACT_PROBES_PASS:{checks}"
    if not coverage or source.count(completion) != 1:
        raise ValueError("CONTROL_PROBE_SHAPE_CHANGED")
    extra, steps = [header], 0
    def force(path, width, value):
        if f"force {path} = {width}'h0;" not in header:
            raise ValueError("CONTROL_PROBE_DRIVER_MISMATCH")
        extra.append(f"force {path} = {width}'h{value:x};\n")
    def check():
        nonlocal steps
        extra.append("#1; check;\n"); steps += 1
    def walk(width):
        return [0, (1 << width)-1] + [v for bit in range(width)
            for v in (1 << bit, ((1 << width)-1) ^ (1 << bit))]
    # Full-width peripheral snapshot data through a real selected MMIO address.
    force(request, 32, 4)
    for value in walk(32):
        force(now, 32, value); check()
    extra.append(header)
    # Frame payload selection requires a nonempty mailbox, whose count is wide.
    force(top + ".fabric_hostFrames_count", 2, 1)
    for name, width in [("length", 6), ("overflow", 1)] + [(f"bytes_{i}", 8) for i in range(33)]:
        path = top + ".fabric_hostFrames_first_frame_" + name
        for value in walk(width):
            force(path, width, value); check()
        force(path, width, 0)
    extra.append(header)
    force(top + ".fabric_mmioCommitPending", 1, 1)
    force(top + ".fabric_mmioCommit_applicationWritable", 1, 1); check()
    extra.append(header)
    def pack(fields):
        value = 0
        for width, field in fields:
            if field < 0 or field >= 1 << width:
                raise ValueError("CONTROL_PROBE_VECTOR_RANGE")
            value = (value << width) | field
        return value
    def command_value(kind=0, frame=(), operation=0, address=0, snapshot=0):
        return pack([(3, kind), (6, len(frame)), (1, 0)] +
                    [(8, b) for b in reversed(list(frame) + [0]*(33-len(frame)))] +
                    [(1, 0), (1, 0), (2, operation), (32, address), (32, 0),
                     (4, 15), (32, snapshot), (1, 0)])
    def frame(op, *words):
        return [op] + [(w >> (8*i)) & 255 for w in words for i in range(4)]
    # All state fields start cold except LOADING/imageLength for WRITE admission.
    state_widths = [3, 1, 1, 1, 8, 32, 32, 32, 32, 32, 32, 1, 32, 24, 4, 32, 6]
    loading = [1, 0, 0, 0, 0, 12] + [0]*11
    force(state, 305, pack(zip(state_widths, loading)))
    force(command, 379, command_value(frame=frame(2, 0, 0xffffffff))); check()
    force(state, 305, 0)
    force(command, 379, command_value(frame=frame(8))); check()
    for value in walk(32) + [1000]:
        force(command, 379, command_value(frame=frame(7, value))); check()
    for value in walk(32):
        force(command, 379, command_value(kind=4, operation=1, address=0x30000004, snapshot=value)); check()
    count = checks + steps * len(coverage)
    position = coverage[0].start()
    result = source[:position] + "".join(extra) + source[position:]
    return result.replace(completion, f"CONTRACT_PROBES_PASS:{count}"), count


def generated_reset_probe(source: str, manifest: dict) -> str:
    """Retarget only the library's flat-reset assumption; fail closed on API drift."""
    top = manifest["top"]
    if top not in {"FourPhaseSoc", "ClickSoc"}:
        raise ValueError("SOC_RESET_UNKNOWN_TOP")
    root = manifest["design"]
    endpoints = [e for e in root["endpoints"] if e["id"] == "system_reset"]
    if len(endpoints) != 1 or endpoints[0]["width"] != 1 or endpoints[0]["source"] != f"~|{top}>systemReset":
        raise ValueError("SOC_RESET_ENDPOINT_MISMATCH")
    reset = endpoints[0]["rtl_path"]

    persistent = {"control": "ClickControl" if top == "ClickSoc" else "FourPhaseControl",
                  "control_command_bridge": "DecoupledToClick" if top == "ClickSoc" else "DecoupledToFourPhase",
                  "control_reply_bridge": "ClickToDecoupled" if top == "ClickSoc" else "FourPhaseToDecoupled"}
    present = {c.get("id") for c in root["children"]} & persistent.keys()
    if present and present != persistent.keys():
        raise ValueError("SOC_PERSISTENT_RESET_INVENTORY")
    telemetry = {"telemetry": "ClickTelemetry" if top == "ClickSoc" else "FourPhaseTelemetry",
                 "telemetry_command_bridge": "DecoupledToClick" if top == "ClickSoc" else "DecoupledToFourPhase",
                 "telemetry_reply_bridge": "ClickToDecoupled" if top == "ClickSoc" else "FourPhaseToDecoupled"}
    present = {c.get("id") for c in root["children"]} & telemetry.keys()
    if present and present != telemetry.keys():
        raise ValueError("SOC_PERSISTENT_RESET_INVENTORY")
    persistent.update(telemetry)
    for child in root["children"]:
        if child.get("id") in persistent and not re.fullmatch(
                re.escape(persistent[child["id"]]) + r"(?:_[0-9]+)?", child["contract"].get("module", "")):
            raise ValueError("SOC_PERSISTENT_RESET_OWNER")

    def children(node, persistent_domain=False):
        for child in node["children"]:
            por = persistent_domain or (node is root and child.get("id") in persistent)
            yield child["contract"], por
            yield from children(child["contract"], por)

    for node, por in children(root):
        old = f'if ({node["rtl_path"]}.reset !== {top}.reset) $fatal(1, "RESET_BINDING_MISMATCH");'
        target = f"{top}.reset" if por else reset
        new = f'if ({node["rtl_path"]}.reset !== {target}) $fatal(1, "RESET_BINDING_MISMATCH");'
        if source.count(old) != 1:
            raise ValueError("SOC_RESET_CHECK_SHAPE_CHANGED")
        source = source.replace(old, new)
    # Preserve/check the external POR contribution as well as generated reset fanout.
    anchor = "task check; begin"
    if source.count(anchor) != 1:
        raise ValueError("SOC_RESET_CHECK_SHAPE_CHANGED")
    return source.replace(anchor, anchor + f'\nif ({top}.reset === 1\'b1 && {reset} !== 1\'b1) $fatal(1, "SOC_POR_BINDING_MISMATCH");')


def vector_coverage_probe(source: str, manifest: dict) -> str:
    """Equivalent packed coverage accumulation; X/Z count as neither zero nor one.

    SystemVerilog assignment into a two-state bit vector maps X/Z to zero. Thus
    converting v and ~v independently implements the original case-equality bit
    tests exactly. Drivers, comparisons, endpoint coverage and check counts stay
    unchanged. See the exhaustive four-state equivalence test.
    """
    def nodes(node):
        yield node
        for child in node["children"]:
            yield from nodes(child["contract"])

    index = 0
    declarations = []
    for node in nodes(manifest["design"]):
        for endpoint in node["endpoints"]:
            path, width = endpoint["rtl_path"], endpoint["width"]
            scalar = []
            for bit in range(width):
                value = path if width == 1 else f"{path}[{bit}]"
                scalar += [f"if ({value} === 1'b1) ones_{index}[{bit}] = 1'b1;",
                           f"if ({value} === 1'b0) zeros_{index}[{bit}] = 1'b1;"]
            old = "\n".join(scalar)
            if source.count(old) != 1:
                raise ValueError("COVERAGE_CHECK_SHAPE_CHANGED")
            declarations.append(f"bit [{width-1}:0] known_one_{index}, known_zero_{index};")
            new = (f"known_one_{index} = {path}; known_zero_{index} = ~{path};\n"
                   f"ones_{index} = ones_{index} | known_one_{index};\n"
                   f"zeros_{index} = zeros_{index} | known_zero_{index};")
            source = source.replace(old, new)
            index += 1
    return source.replace("task check; begin", "\n".join(declarations) + "\ntask check; begin")


# These two path kinds describe MCU-owned controllers, not library primitives.
BD_FABRIC_PATH = "ROM/static permission decode and service response mux"
CLICK_FABRIC_PATH = "complete ROM/static permission decode and service response mux before event register"


def validate_fabric_inventory(manifest):
    """Required obligations cannot vanish along with their passive markers."""
    def visit(node):
        module = node["module"]
        if re.fullmatch(r"(?:FourPhase|Click)Fabric(?:_[0-9]+)?", module):
            click = module.startswith("Click")
            expected = {"response_mux": ("bundled-data-path-v1", CLICK_FABRIC_PATH if click else BD_FABRIC_PATH)}
            if click:
                expected["capture_aperture"] = ("bundled-setup-hold-v1", None)
            actual = {t["id"]: (t["kind"], t.get("logic")) for t in node["timing"]}
            if actual != expected or len(node["timing"]) != len(expected):
                raise ValueError("MCU_FABRIC_TIMING_INVENTORY")
            if click:
                validate_click_fabric_controls(node)
        for child in node["children"]:
            visit(child["contract"])
    visit(manifest["design"])


def validate_click_fabric_controls(node):
    """Independent fixed digital policy for the MCU's composed Click network.

    These are the 1..10 ns experiment bounds, not characterized cell timing.
    ClickFabric rejects other policies; default AsyncTest routing variation uses
    exactly this envelope. Check actual model parameters and composed guards,
    rather than applying the library's atomic-AND ClickStage formula here.
    """
    cells = {p["id"]: p for p in node["primitives"]}
    aperture = next((t for t in node["timing"] if t["id"] == "capture_aperture"), {})
    if any(aperture.get(k) != v for k, v in {
            "kind": "bundled-setup-hold-v1", "launch": "request_request", "transaction": "request_data",
            "data_valid": "register_data", "capture": "capture_event", "captured": "response_data",
            "setup_fs": "100000", "hold_fs": "100000"}.items()):
        raise ValueError("MCU_CLICK_FABRIC_APERTURE")
    expected = {"accepted_phase": "ChiselAsyncPhaseRegister_v1",
                "service_request_phase": "ChiselAsyncPhaseRegister_v1",
                "service_response_phase": "ChiselAsyncEventRegister_v1",
                "payload": "ChiselAsyncEventRegister_v1", "dispatch": "ChiselAsyncAsymmetricC_v1",
                "request_pending": "ChiselAsyncXor_v1", "response_occupied": "ChiselAsyncXor_v1"}
    for prefix in ("runnable", "capture"):
        expected.update({prefix + suffix: "ChiselAsyncControlGate_v1" for suffix in ("_na", "_nb", "_or", "")})
    for name, model in expected.items():
        cell = cells.get(name, {})
        if cell.get("model") != model or cell.get("parameters", {}).get("DELAY_FS") != "1000000":
            raise ValueError("MCU_CLICK_FABRIC_CELL_POLICY")
    for name, delay in (("request_guard", 11000000), ("request_delay", 11000000),
                        ("output_delay", 32000000), ("data_delay", 10000000)):
        if cells.get(name, {}).get("parameters", {}).get("DELAY_FS") != str(delay):
            raise ValueError("MCU_CLICK_FABRIC_FIXED_GUARD")
    # Phase propagation + XOR + two three-cell ANDs + skew + low/hold margin.
    limit = 10000000 + 7 * 10000000 + 100000 + 100000
    for name in ("acknowledge_guard", "output_guard", "return_guard"):
        if int(cells.get(name, {}).get("parameters", {}).get("DELAY_FS", "0")) <= limit:
            raise ValueError("MCU_CLICK_FABRIC_DRAIN_GUARD")


def validate_fabric_path(node, timing):
    """Fail closed on custom-path identity, schema, storage and native protocol.

    The library still validates every timing field, budget/guard, marker parameter,
    primitive, elaborated pin, endpoint mapping and endpoint activity afterwards.
    """
    logic = timing.get("logic")
    if logic not in (BD_FABRIC_PATH, CLICK_FABRIC_PATH):
        return
    click = logic == CLICK_FABRIC_PATH
    protocol = "two-phase-bundled-v1" if click else "four-phase-bundled-v1"
    expected = ([], "data_delay", "reply_sources", "register_data") if click else (
        ["reply"], "data_delay", "mux_sources", "mux_result")
    if (node["module"] != ("ClickFabric" if click else "FourPhaseFabric") or
            tuple(timing[k] for k in ("delay_owner", "delay_cell", "source", "sink")) != expected or
            {c["id"]: (c["protocol"], c["role"]) for c in node["channels"]} != {
                "request": (protocol, "input"), "response": (protocol, "output"),
                "service_request": (protocol, "output"), "service_response": (protocol, "input")}):
        raise ValueError("MCU_FABRIC_PATH_IDENTITY")
    endpoints = {e["id"]: e for e in node["endpoints"]}
    if any(endpoints.get(name, {}).get("width") != width for name, width in (
            (timing["source"], 103), (timing["sink"], 33),
            ("request_data", 70), ("response_data", 33),
            ("service_request_data", 70), ("service_response_data", 33))):
        raise ValueError("MCU_FABRIC_PATH_WIDTH")
    if click:
        cells = {p["id"]: p for p in node["primitives"]}
        if (node["children"] or endpoints.get("capture_event", {}).get("width") != 1 or
                cells.get("payload", {}).get("model") != "ChiselAsyncEventRegister_v1" or
                cells.get("payload", {}).get("parameters", {}).get("WIDTH") != "33" or
                cells.get("service_response_phase", {}).get("model") != "ChiselAsyncEventRegister_v1" or
                cells.get("service_response_phase", {}).get("parameters", {}).get("WIDTH") != "1"):
            raise ValueError("MCU_FABRIC_CAPTURE_CELL")
        for name in ("request_guard", "request_delay", "output_delay", "acknowledge_guard", "output_guard", "return_guard"):
            cell = cells.get(name, {})
            params = cell.get("parameters", {})
            if (cell.get("model") != "ChiselAsyncControlGate_v1" or
                    any(params.get(k) != v for k, v in {"WIDTH": "1", "OP": "0", "RESET_VALUE": "0"}.items()) or
                    int(params.get("DELAY_FS", "0")) <= 0):
                raise ValueError("MCU_FABRIC_GUARD_CELL")
    else:
        children = node["children"]
        if (len(children) != 1 or children[0]["id"] != "reply" or
                not re.fullmatch(r"FourPhaseStage(?:_[0-9]+)?", children[0]["contract"]["module"])):
            raise ValueError("MCU_FABRIC_REPLY_OWNER")


def validate_native_click(manifest):
    """A Click export must remain native throughout its async hierarchy."""
    if manifest["top"] not in ("ClickSoc", "ClickCore", "ClickFabric", "ClickControl", "ClickTelemetry"):
        return
    def nodes(node):
        yield node
        for child in node["children"]:
            yield from nodes(child["contract"])
    for node in nodes(manifest["design"]):
        if ("FourPhase" in node["module"] or
                any(c["protocol"] == "four-phase-bundled-v1" for c in node["channels"]) or
                any(p["model"] == "ChiselAsyncClosingLatch_v1" for p in node["primitives"])):
            raise ValueError("MCU_CLICK_HAS_RTZ_IMPLEMENTATION")


def fabric_path_bindings(node, timing):
    """Actual mux/storage pin comparisons added to the unchanged library probe."""
    endpoints = {e["id"]: e["rtl_path"] for e in node["endpoints"]}
    if timing.get("logic") == BD_FABRIC_PATH:
        owner = next(c["contract"] for c in node["children"] if c["id"] == "reply")
        cell = next(p["rtl_path"] for p in owner["primitives"] if p["id"] == "data_delay")
        storage = next(e["rtl_path"] for e in owner["endpoints"] if e["id"] == "in_data")
        return [(endpoints["mux_result"], storage), (endpoints["mux_result"], cell + ".a")]
    if timing.get("logic") == CLICK_FABRIC_PATH:
        cells = {p["id"]: p["rtl_path"] for p in node["primitives"]}
        return [(endpoints["register_data"], cells["data_delay"] + ".q"),
                (endpoints["register_data"], cells["payload"] + ".d"),
                (endpoints["capture_event"], cells["payload"] + ".trigger"),
                (endpoints["capture_event"], cells["accepted_phase"] + ".trigger"),
                (endpoints["capture_event"], cells["service_response_phase"] + ".trigger"),
                (endpoints["service_response_request"], cells["service_response_phase"] + ".d"),
                (cells["accepted_phase"] + ".q", cells["acknowledge_guard"] + ".a"),
                (cells["accepted_phase"] + ".q", cells["output_guard"] + ".a"),
                (cells["service_response_phase"] + ".q", cells["return_guard"] + ".a"),
                (cells["service_request_phase"] + ".q", cells["output_delay"] + ".a"),
                (endpoints["request_acknowledge"], cells["acknowledge_guard"] + ".q"),
                (endpoints["response_request"], cells["output_guard"] + ".q"),
                (endpoints["service_response_acknowledge"], cells["return_guard"] + ".q"),
                (endpoints["service_request_request"], cells["output_delay"] + ".q")]
    return []


def fabric_checker_source(source):
    """Extend the pinned checker's closed path table; reject upstream API drift.

    No original check is deleted. New entries use the same generic budget/marker
    checks and add explicit MCU data/capture pin comparisons to the probe.
    """
    anchor = '"initial-token-literal-mux": ([], "data", "mux_state", "out_data")}'
    if source.count(anchor) != 1:
        raise ValueError("MCU_FABRIC_CHECKER_SHAPE_CHANGED")
    extra = (anchor[:-1] + f', {BD_FABRIC_PATH!r}: (["reply"], "data_delay", "mux_sources", "mux_result"),'
             + f' {CLICK_FABRIC_PATH!r}: ([], "data_delay", "reply_sources", "register_data")}}'
             + "\n                validate_fabric_path(node, timing)")
    source = source.replace(anchor, extra)
    anchor = 'if timing["logic"] in ("exclusive-merge-input-mux", "controlled-multiplexer-input-mux"):'
    if source.count(anchor) != 1:
        raise ValueError("MCU_FABRIC_CHECKER_SHAPE_CHANGED")
    return source.replace(anchor,
        f'if timing["logic"] in ({BD_FABRIC_PATH!r}, {CLICK_FABRIC_PATH!r}):\n'
        '                    pairs = fabric_path_bindings(node, timing)\n'
        '                el' + anchor)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--probe-timeout", type=int, default=600)
    parser.add_argument("--probe-compile-timeout", type=int, default=600)
    parser.add_argument("--soc", action="store_true", help="Validate RISCay generated system-reset fanout")
    parser.add_argument("--vector-coverage", action="store_true", help="Equivalent packed four-state coverage bookkeeping")
    parser.add_argument("--sleep-clock", action="store_true", help="Add a clock-enabled stimulus background for retained-sleep SoCs")
    args = parser.parse_args()
    if args.probe_timeout <= 0 or args.probe_compile_timeout <= 0:
        parser.error("probe compilation and simulation timeouts must be positive")
    source = args.library.resolve() / "tools" / "check_export.py"
    sys.path.insert(0, str(source.parent))
    spec = importlib.util.spec_from_file_location("riscay_library_export_checker", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {source}")
    module = importlib.util.module_from_spec(spec)
    module.validate_fabric_path = validate_fabric_path
    module.fabric_path_bindings = fabric_path_bindings
    exec(compile(fabric_checker_source(source.read_text()), str(source), "exec"), module.__dict__)
    original_run = subprocess.run
    original_manifest = module.validate_manifest
    def manifest(document):
        result = original_manifest(document)
        validate_fabric_inventory(result)
        validate_native_click(result)
        return result
    module.validate_manifest = manifest
    original_probe = module.probe_source
    original_memories = module.validate_memories
    original_vvp = module.read_vvp
    module.read_vvp = lambda contents: sram_array_shapes(contents, original_vvp(contents))
    verified_sram = set()
    def memories(directory, node, scopes):
        macros = sram_scopes(directory, node, scopes)
        verified_sram.update(macros)
        return original_memories(directory, node, scopes) | macros
    module.validate_memories = memories

    def probe(manifest, scopes, paired=False):
        source, count = original_probe(manifest, scopes, paired)
        source, count = register_file_background(source, manifest, count)
        source, count = control_background(source, manifest, scopes, count)
        if args.sleep_clock:
            source, count = sleep_clock_background(source, manifest, scopes, count)
        if args.soc:
            source = generated_reset_probe(source, manifest)
        if args.vector_coverage:
            source = vector_coverage_probe(source, manifest)
        return source, count
    module.probe_source = probe

    def run(command, *pargs, **kwargs):
        kwargs["timeout"] = probe_timeout(command, kwargs.get("timeout"),
                                         args.probe_timeout, args.probe_compile_timeout)
        return original_run(command, *pargs, **kwargs)

    subprocess.run = run
    try:
        result = module.validate_export(args.directory.resolve())
    finally:
        subprocess.run = original_run
        module.validate_manifest = original_manifest
        module.probe_source = original_probe
        module.validate_memories = original_memories
        module.read_vvp = original_vvp
    print(json.dumps({"status": result["status"], "semantic_sha256": result["semantic_sha256"],
                      "endpoints": len(result["endpoints"]), "mapping_checks": result["mapping_checks"],
                      "sram_instances": sorted(verified_sram),
                      "probe_timeout_seconds": args.probe_timeout,
                      "probe_compile_timeout_seconds": args.probe_compile_timeout,
                      "sleep_clock_background": args.sleep_clock,
                      "coverage": "packed-equivalent" if args.vector_coverage else "library-scalar",
                      "reset_contract": "generated-system-reset" if args.soc else "flat-library-reset"}, indent=2))


if __name__ == "__main__":
    main()
