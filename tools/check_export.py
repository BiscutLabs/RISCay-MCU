# SPDX-License-Identifier: Apache-2.0
"""Run chisel-async export checks with MCU timeout/generated-reset support.

The library defaults to 60 seconds, which its small component probes fit. This
adapter extends the contract probe's compilation and simulation limits. With
--soc it checks CPU child resets against the generated system-reset endpoint and
the named persistent Control children against POR. Endpoint/timing checks and
all dynamic polarity coverage are retained. Two literal completion bridge
input leaves have exact binding obligations instead of impossible polarity walks.
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
from check_completion_export import (BD_COMPLETION_PATH, CLICK_COMPLETION_PATH,
                                     validate_completion, completion_bindings)
from check_completion_integration import completion_background, completion_constants_probe, native_return_cell
from check_admission_export import validate_admission, literal_nets, admission_probe
from check_ram_return_contract import PATHS as RAM_RETURN_PATHS, validate_ram_return, ram_return_bindings, policy as ram_return_policy
from check_ram_return_integration import ram_return_probe, apply_return_literal_obligations
from check_program_return_contract import (PATHS as PROGRAM_RETURN_PATHS, validate_program_return,
                                         program_return_bindings, policy as program_return_policy)
from check_program_return_integration import program_return_probe
from check_application_reset import (validate_application_reset, persistent_reset_children,
    coordinated_reset, reset_endpoint, presentation_reset)
from check_reset_crossings import check_reset_crossings
from check_service_reply_receipt import (native_reply_source, pack_reply, service_reply_probe,
    validate_service_reply_rtl, control_widths, validate_control_token)
from check_held_receipts import validate_held_receipts, held_receipt_probe
from check_native_clock_inventory import native_clock_inventory
from check_quiescing_receipt import native_request_source, pack_request, request_receipt_probe
from check_probe_budget import require_paired_probe_budget
from check_program_address import prove_program_address, program_address_probe
from check_ram_source_export import ARM_PATH, RETIRE_PATH, validate_ram_source, ram_source_bindings, ram_source_probe
from check_program_source_export import PROGRAM_PATHS, validate_program_source, program_source_bindings, program_source_probe, validate_program_receipts
from check_frame_receipt import validate_frame_receipts
from check_frame_store import validate_frame_stores, validate_frame_store_metadata, timing_spec as frame_store_timing
from check_frame_integration import frame_receipt_probe
from check_publication_source_export import PATHS as PUBLICATION_PATH_TABLE, validate_publication_source, publication_source_bindings, publication_source_probe, publication_recovery_background
from check_recovery_return_export import (PATHS as RECOVERY_RETURN_PATH_TABLE,validate_recovery_return,
    recovery_return_bindings,validate_return_receipts)
PUBLICATION_PATHS=tuple(p[1] for p in PUBLICATION_PATH_TABLE)
RECOVERY_RETURN_PATHS=tuple(p[1] for p in RECOVERY_RETURN_PATH_TABLE)
FRAME_STORE_PATHS=tuple(frame_store_timing(click)[0]["logic"] for click in (False,True))


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
    # The copied campaign can include native-source settlement checks with
    # longer delays. Count every canonical positive-integer-delay invocation,
    # and reject unrecognized check syntax rather than under-reporting work.
    steps = len(re.findall(r"^[ \t]*#[1-9][0-9]*;[ \t]+check;[ \t]*$", campaign, re.M))
    if steps != len(re.findall(r"\bcheck\b", campaign)):
        raise ValueError("SLEEP_PROBE_CHECK_SHAPE")
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


def control_program_bytes(directory, manifest, scopes):
    """Use the emitter inventory only after its actual SRAM instances validate."""
    if not any(c.get('id') == 'control' for c in manifest.get('design', {}).get('children', [])):
        return None
    if manifest.get('top') not in ('FourPhaseSoc', 'ClickSoc'):
        raise ValueError('CONTROL_PROBE_CAPACITY_OWNER')
    sram_scopes(Path(directory), manifest['design'], scopes)
    inventory = Path(directory) / 'sram.json'
    if not inventory.is_file():
        raise ValueError('CONTROL_PROBE_CAPACITY_MISSING')
    capacity = json.loads(inventory.read_text())['program_bytes']
    control_widths(capacity)
    return capacity


def control_background(source: str, manifest: dict, scopes: dict, checks: int, program_bytes=None):
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
    count_width, entry_width = control_widths(program_bytes)
    state_id = "left_storage" if click else "left"
    state_nodes = [c['contract'] for c in join['children'] if c['id'] == state_id]
    if len(state_nodes) != 1:
        raise ValueError('CONTROL_PROBE_DRIVER_MISMATCH')
    token_width = validate_control_token(state_nodes[0], program_bytes)
    state = payload(state_id, token_width)
    command = payload("right_storage" if click else "right", 379)
    request = top + ".ca_child_request_bridge.state"
    now = top + ".fabric_housekeepingState_now"
    for path, width in ((request, 2), (now, 32)):
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
    native = native_request_source(manifest, scopes, header)
    force(request, 2, 2)
    extra.append(f"force {native['path']} = 70'h{pack_request(address=4):x};\n")
    for value in walk(32):
        force(now, 32, value); check()
    extra.append(header)
    # Frame payloads now live in the four native banks. Keep the nonempty
    # descriptor context and select every bank while walking its complete
    # retained frame, including epoch and source context. Never force a head
    # endpoint or the combinational command mux instead of its actual storage.
    force(top + ".fabric_hostFrames_count", 2, 1)
    targets = [c["contract"] for c in root.get("children", []) if c["id"] == "i2c"]
    stores = [c["contract"] for target in targets for c in target.get("children", []) if c["id"] == "frame_store"]
    if len(targets) != 1 or len(stores) != 1 or not re.fullmatch(
            ("Click" if click else "FourPhase") + r"FrameStore(?:_\d+)?", stores[0]["module"]):
        raise ValueError("CONTROL_PROBE_FRAME_STORE_OWNER")
    store = stores[0]
    for bank in range(4):
        cells = ([p for p in store.get("primitives", []) if p["id"] == "payload" + str(bank)] if click else
                 [p for child in store.get("children", []) if child["id"] == "storage" + str(bank)
                  for p in child["contract"].get("primitives", []) if p["id"] == "payload"])
        if len(cells) != 1 or cells[0]["model"] != ("ChiselAsyncEventRegister_v1" if click else "ChiselAsyncClosingLatch_v1") or \
                {"name": "q", "width": 337, "direction": "output"} not in cells[0].get("ports", []):
            raise ValueError("CONTROL_PROBE_FRAME_STORE_PAYLOAD")
        force(top + ".fabric_hostFrames_first_bank", 2, bank)
        path = cells[0]["rtl_path"] + ".q"
        for value in walk(337):
            force(path, 337, value); check()
        force(path, 337, 0)
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
    state_widths = [3, 1, 1, 1, 8, count_width, entry_width, count_width, 32, 32, 32, 1, 32, 24, 4, 32, 6]
    loading = [1, 0, 0, 0, 0, min(12, program_bytes)] + [0]*11
    force(state, token_width, pack(zip(state_widths, loading)) << 32)
    force(command, 379, command_value(frame=frame(2, 0, 0xffffffff))); check()
    force(state, token_width, 0)
    force(command, 379, command_value(frame=frame(8))); check()
    for value in walk(32) + [1000]:
        force(command, 379, command_value(frame=frame(7, value))); check()
    for value in walk(32):
        force(command, 379, command_value(kind=4, operation=1, address=0x30000004, snapshot=value)); check()
    count = checks + steps * len(coverage)
    position = coverage[0].start()
    result = source[:position] + "".join(extra) + source[position:]
    return result.replace(completion, f"CONTRACT_PROBES_PASS:{count}"), count


def frame_head_background(source: str, manifest: dict, scopes: dict, checks: int):
    """Exercise native-bank idle and selected Host dispatch from retained sources.

    A bit walk cannot set every bit of a four-bit idle guard, or combine a
    nonempty descriptor, observed head and running work gate. Keep the original
    campaigns, comparisons and every activity requirement; force no endpoint.
    """
    top = manifest.get("top")
    if top not in ("FourPhaseSoc", "ClickSoc"):
        return source, checks
    click = top == "ClickSoc"
    targets = [c["contract"] for c in manifest["design"].get("children", []) if c["id"] == "i2c"]
    if len(targets) != 1:
        raise ValueError("FRAME_HEAD_PROBE_OWNER")
    children = targets[0].get("children", [])
    def owner(identity, family):
        found = [c["contract"] for c in children if c["id"] == identity]
        if len(found) != 1 or not re.fullmatch(("Click" if click else "FourPhase") + family + r"(?:_\d+)?", found[0]["module"]):
            raise ValueError("FRAME_HEAD_PROBE_OWNER")
        return found[0]
    store = owner("frame_store", "FrameStore")
    heads = [owner(f"frame_head{i}_bridge", "FrameReceipt") for i in range(4)]
    anchor = f"initial begin\nforce {top}.reset = 1'b1; #1;\n"
    if source.count(anchor) != 1:
        raise ValueError("FRAME_HEAD_PROBE_SHAPE")
    start = source.index(anchor) + len(anchor)
    end = source.index("\n#1;\n", start) + len("\n#1;\n")
    header = source[start:end]
    coverage = list(re.finditer(r"^if \(ones_\d+ !==.*INACTIVE_ENDPOINT:.*$", source, re.M))
    marker = f"CONTRACT_PROBES_PASS:{checks}"
    if not coverage or source.count(marker) != 1:
        raise ValueError("FRAME_HEAD_PROBE_SHAPE")
    extra, steps = [], 0
    def force(path, width, value, primitive=False):
        parent, name = path.rsplit(".", 1)
        if ((not primitive and scopes.get(parent, {}).get("registers", {}).get(name) != width) or
                f"force {path} = {width}'h0;" not in header):
            raise ValueError("FRAME_HEAD_PROBE_DRIVER")
        extra.append(f"force {path} = {width}'h{value:x};\n")
    def check():
        nonlocal steps
        extra.append("#1; check;\n"); steps += 1
    if not click:
        guards = [p for p in store.get("primitives", []) if p["id"] == "return_guard"]
        if len(guards) != 1 or guards[0]["model"] != "ChiselAsyncControlGate_v1" or guards[0]["parameters"] != {
                "WIDTH": "4", "OP": "0", "DELAY_FS": "32000000", "RESET_VALUE": "0"} or \
                {"name": "q", "width": 4, "direction": "output"} not in guards[0]["ports"]:
            raise ValueError("FRAME_HEAD_PROBE_RETURN_GUARD")
        extra.append(header)
        force(guards[0]["rtl_path"] + ".q", 4, 15, primitive=True); check()
    for bank, head in enumerate(heads):
        extra.append(header)
        # Ungated configurations have an already validated constant-running
        # connection and no gate storage. A present gate must still be 1 bit.
        if "gate_enabled" in scopes.get(top, {}).get("registers", {}):
            force(top + ".gate_enabled", 1, 1)
        force(top + ".fabric_hostFrames_count", 2, 1)
        force(top + ".fabric_hostFrames_first_bank", 2, bank)
        force(head["rtl_path"] + ".requestSync", 1, 1)
        check()
    count = checks + steps * len(coverage)
    position = coverage[0].start()
    result = source[:position] + "".join(extra) + source[position:]
    return result.replace(marker, f"CONTRACT_PROBES_PASS:{count}"), count


def i2c_standalone_byte_background(source,manifest,scopes,checks):
    """Coherent byte intents at validated top input ports; keep generic probes."""
    node=manifest["design"];validate_i2c_publication(node)
    top=manifest["top"]
    ports=scopes.get(top,{}).get("ports",{})
    expected={"in_bits_frameValid":1,"in_bits_byteWrite_valid":1,
              "in_bits_byteWrite_index":6,"in_bits_byteWrite_data":8}
    if any(ports.get(name)!={"name":name,"direction":"input","width":width} for name,width in expected.items()):
        raise ValueError("I2C_PROBE_DRIVER_MISMATCH")
    anchor=f"initial begin\nforce {top}.reset = 1'b1; #1;\n"
    if source.count(anchor)!=1:raise ValueError("I2C_PROBE_SHAPE_CHANGED")
    start=source.index(anchor)+len(anchor);end=source.index("\n#1;\n",start)+len("\n#1;\n")
    header=source[start:end]
    if any(f"force {top}.{name} = {width}'h0;" not in header for name,width in expected.items()):
        raise ValueError("I2C_PROBE_DRIVER_MISMATCH")
    coverage=list(re.finditer(r"^if \(ones_\d+ !==.*INACTIVE_ENDPOINT:.*$",source,re.M))
    completion=f"CONTRACT_PROBES_PASS:{checks}"
    if not coverage or source.count(completion)!=1:raise ValueError("I2C_PROBE_SHAPE_CHANGED")
    extra=[header,f"force {top}.in_bits_frameValid = 1'h0;\nforce {top}.in_bits_byteWrite_valid = 1'h1;\n"]
    for index in range(33):
        for value in (0,255):
            extra.append(f"force {top}.in_bits_byteWrite_index = 6'h{index:x};\nforce {top}.in_bits_byteWrite_data = 8'h{value:x};\n#1; check;\n")
    extra.append(header)
    count=checks+66*len(coverage);position=coverage[0].start()
    result=source[:position]+"".join(extra)+source[position:]
    return result.replace(completion,f"CONTRACT_PROBES_PASS:{count}"),count


def i2c_background(source: str, manifest: dict, scopes: dict, checks: int):
    """Exercise native I2C decode conjunctions using only retained sources.

    A one-bit walk cannot form mode=receive, bit=7 and a matching read address,
    or a completed write with STOP. Keep every original campaign and comparison;
    add those contexts at the state payload and immutable edge-slot registers.
    """
    if manifest["design"].get("module")=="I2cPublication":
        return i2c_standalone_byte_background(source,manifest,scopes,checks)
    owners = [c["contract"] for c in manifest["design"].get("children", []) if c["id"] == "i2c"]
    if not owners:
        return source, checks
    if len(owners) != 1 or owners[0]["module"] != "I2cTarget":
        raise ValueError("I2C_PROBE_OWNER_MISMATCH")
    owner = owners[0]
    def child(node, name):
        matches = [c["contract"] for c in node.get("children", []) if c["id"] == name]
        if len(matches) != 1:
            raise ValueError("I2C_PROBE_DRIVER_MISMATCH")
        return matches[0]
    native = child(owner, "native")
    if native["module"] not in ("FourPhaseI2c", "ClickI2c"):
        raise ValueError("I2C_PROBE_OWNER_MISMATCH")
    state = child(native, "state")
    def nodes(node):
        yield node
        for c in node.get("children", []):
            yield from nodes(c["contract"])
    cells = [p for n in nodes(state) for p in n.get("primitives", []) if p["id"] == "payload"]
    if (len(cells) != 1 or cells[0]["model"] not in
            ("ChiselAsyncClosingLatch_v1", "ChiselAsyncEventRegister_v1") or
            {"name": "q", "width": 76, "direction": "output"} not in cells[0].get("ports", [])):
        raise ValueError("I2C_PROBE_DRIVER_MISMATCH")
    payload = cells[0]["rtl_path"] + ".q"
    layouts = [c["layout"] for c in state.get("channels", []) if c["id"] == "out"]
    fields = {"head": (72, 4), "mode": (64, 4), "active": (63, 1),
              "addressByte": (61, 1), "selectedWrite": (60, 1),
              "receive": (52, 8), "bit": (49, 3), "length": (39, 6)}
    if len(layouts) != 1 or any(
            sum(f.get("field") == "bits." + name and (f.get("lsb"), f.get("width")) == shape
                for f in layouts[0]) != 1 for name, shape in fields.items()):
        raise ValueError("I2C_PROBE_LAYOUT_MISMATCH")
    update = child(native,"update")
    update_cells=[p for n in nodes(update) for p in n.get("primitives",[]) if p["id"]=="payload"]
    if (len(update_cells)!=1 or update_cells[0]["model"] not in
            ("ChiselAsyncClosingLatch_v1","ChiselAsyncEventRegister_v1") or
            {"name":"q","width":174,"direction":"output"} not in update_cells[0].get("ports",[])):
        raise ValueError("I2C_PROBE_DRIVER_MISMATCH")
    update_payload=update_cells[0]["rtl_path"]+".q"
    update_layouts=[c["layout"] for c in update.get("channels",[]) if c["id"]=="out"]
    intent_fields={"frameValid":(97,1),"byteWrite.valid":(14,1),"byteWrite.index":(8,6),"byteWrite.data":(0,8)}
    if len(update_layouts)!=1 or any(sum(f.get("field")=="bits."+name and
            (f.get("lsb"),f.get("width"))==shape for f in update_layouts[0])!=1
            for name,shape in intent_fields.items()):
        raise ValueError("I2C_PROBE_LAYOUT_MISMATCH")
    anchor = f"initial begin\nforce {manifest['top']}.reset = 1'b1; #1;\n"
    if source.count(anchor) != 1:
        raise ValueError("I2C_PROBE_SHAPE_CHANGED")
    start = source.index(anchor) + len(anchor)
    end = source.index("\n#1;\n", start) + len("\n#1;\n")
    header = source[start:end]
    coverage = list(re.finditer(r"^if \(ones_\d+ !==.*INACTIVE_ENDPOINT:.*$", source, re.M))
    completion = f"CONTRACT_PROBES_PASS:{checks}"
    if not coverage or source.count(completion) != 1:
        raise ValueError("I2C_PROBE_SHAPE_CHANGED")
    extra, steps = [header], 0
    def force(path, width, value):
        node, name = path.rsplit(".", 1)
        if ((path not in (payload,update_payload) and scopes.get(node, {}).get("registers", {}).get(name) != width) or
                f"force {path} = {width}'h0;" not in header):
            raise ValueError("I2C_PROBE_DRIVER_MISMATCH")
        extra.append(f"force {path} = {width}'h{value:x};\n")
    def check():
        nonlocal steps
        extra.append("#1; check;\n"); steps += 1
    # Head zero selects slot zero. All edge flags other than rise/SDA stay zero.
    force(owner["rtl_path"] + ".slots_0_rise", 1, 1)
    force(owner["rtl_path"] + ".slots_0_sda", 1, 1)
    for address in range(128):
        force(payload, 76, (1 << 64) | (1 << 63) | (1 << 61) | (address << 52) | (7 << 49))
        check()
    extra.append(header)
    force(payload, 76, (1 << 64) | (1 << 63) | (1 << 60) | (1 << 39))
    force(owner["rtl_path"] + ".slots_0_stop", 1, 1); check()
    extra.append(header); check()
    # One/two-bit walks cannot form every valid six-bit byte index. Add all
    # legal intents at the validated retained update source, keeping every
    # original generic comparison and polarity requirement.
    for index in range(33):
        for value in (0,255):
            force(update_payload,174,(1 << 14) | (index << 8) | value)
            check()
    extra.append(header)
    count = checks + steps * len(coverage)
    position = coverage[0].start()
    result = source[:position] + "".join(extra) + source[position:]
    return result.replace(completion, f"CONTRACT_PROBES_PASS:{count}"), count


def sram_background(source: str, manifest: dict, scopes: dict, checks: int, program_bytes=None):
    """Add coherent idle/admission and each byte-return tag to mapping stimulus.

    Five return synchronizers must agree before word admission. All-low,
    all-high and paired drivers cannot form that state. Force only catalogued
    registers, retaining every original campaign, comparison and coverage check.
    This mapping-only stimulus never forces a derived ready/valid or payload.
    """
    owners = {c["id"]: c["contract"] for c in manifest["design"].get("children", [])
              if c["id"] in ("program_access", "ram_access")}
    if not owners:
        return source, checks
    if (set(owners) != {"program_access", "ram_access"} or
            any(not re.fullmatch((r"ProgramAccess" if k=="program_access" else r"RamAccess")+r"(?:_[0-9]+)?", n["module"]) for k,n in owners.items())):
        raise ValueError("SRAM_PROBE_OWNER_MISMATCH")
    top = manifest["top"]
    anchor = f"initial begin\nforce {top}.reset = 1'b1; #1;\n"
    if source.count(anchor) != 1:
        raise ValueError("SRAM_PROBE_SHAPE_CHANGED")
    start = source.index(anchor) + len(anchor)
    end = source.index("\n#1;\n", start) + len("\n#1;\n")
    header = source[start:end]
    coverage = list(re.finditer(r"^if \(ones_\d+ !==.*INACTIVE_ENDPOINT:.*$", source, re.M))
    completion = f"CONTRACT_PROBES_PASS:{checks}"
    if not coverage or source.count(completion) != 1:
        raise ValueError("SRAM_PROBE_SHAPE_CHANGED")
    extra, steps = [], 0

    def force(path, width, value):
        node, name = path.rsplit(".", 1)
        if (scopes.get(node, {}).get("registers", {}).get(name) != width or
                f"force {path} = {width}'h0;" not in header):
            raise ValueError("SRAM_PROBE_DRIVER_MISMATCH")
        if not 0 <= value < 1 << width:
            raise ValueError("SRAM_PROBE_VECTOR_RANGE")
        extra.append(f"force {path} = {width}'h{value:x};\n")

    def check():
        nonlocal steps
        extra.append("#1; check;\n"); steps += 1

    def walk(width):
        return [0, (1 << width)-1] + [v for bit in range(width)
            for v in (1 << bit, ((1 << width)-1) ^ (1 << bit))]

    def idle():
        extra.append(header)
        if "gate_enabled" in scopes.get(top, {}).get("registers", {}):
            force(top + ".gate_enabled", 1, 1)
        for node in owners.values():
            for group in ("returned_stages", "bytesReturned_stages", "bytesReturned_stages_1",
                          "bytesReturned_stages_2", "bytesReturned_stages_3"):
                for stage in (0, 1):
                    force(node["rtl_path"] + f".{group}_{stage}", 1, 1)
            for stage in (0,1):force(node["rtl_path"]+f".ownerReturned_stages_{stage}",1,1)
        check()

    idle()
    reply = top + ".ca_child_control_reply_bridge"
    retained = native_reply_source(manifest, scopes, header, "control", program_bytes)
    values = {}
    def held(field, value):
        values[field] = value
        extra.append(f"force {retained['path']} = {retained['width']}'h{pack_reply(retained, values):x};\n")
    force(top + ".fabric_controlOutstanding", 1, 1)
    force(reply + ".state", 2, 2)
    held("programWrite", 1)
    # The loader's actual word admission now requires its retained tagged grant.
    # Both fields are catalogued crossing registers; never force request.valid,
    # grant.valid or any derived readiness/selection expression.
    force(top + ".ca_child_program_grant_bridge.state", 2, 2)
    force(top + ".ca_child_program_grant_bridge.data", 1, 1)
    check()
    for field, width in (("received", control_widths(program_bytes)[0]), ("loaderWord", 32)):
        for value in walk(width):
            held("state." + field, value); check()
    idle()
    request = top + ".ca_child_request_bridge"
    force(request + ".state", 2, 2)
    native = native_request_source(manifest, scopes, header)
    request_values = dict(address=0x20000000)
    def held_request(**fields):
        request_values.update(fields)
        extra.append(f"force {native['path']} = 70'h{pack_request(**request_values):x};\n")
    held_request()
    for operation in (1, 2):
        held_request(operation=operation); check()
    for field, width in (("data", 32), ("mask", 4)):
        for value in walk(width):
            held_request(**{field:value}); check()
    # Invalid addresses exercise the offered payload, never admitted effects.
    for value in walk(32):
        held_request(address=(0x20000000 + value) & 0xffffffff); check()
    # The retained native word drives publication directly. Walk the actual
    # storage output; the obsolete clocked word reply must not survive this item.
    idle()
    payload=native_return_cell(manifest,scopes,header,'program','payload','ca_primitive_payload',
        'ChiselAsyncEventRegister_v1',dict(WIDTH='32',DELAY_FS='1000000',RESET_VALUE='0'),32)
    for value in walk(32):
        extra.append(f"force {payload} = 32'h{value:x};\n");check()
    extra.append(header)
    for bank in ("program", "ram"):
        force(top + f".fabric_{bank}_state", 2, 3)
        for lane in range(4):
            force(top + f".fabric_{bank}_tag", 2, lane)
            for value in walk(8):
                force(top + f".fabric_{bank}_result", 8, value); check()
    count = checks + steps * len(coverage)
    position = coverage[0].start()
    result = source[:position] + "".join(extra) + source[position:]
    return result.replace(completion, f"CONTRACT_PROBES_PASS:{count}"), count


def service_background(source: str, manifest: dict, scopes: dict, checks: int):
    """Exercise startup, elapsed admission and the selected service response.

    Add source-state combinations missed by individual bit walks; retain all
    generic campaigns and endpoint assertions. This is mapping stimulus only.
    """
    top = manifest.get("top")
    if top not in ("FourPhaseSoc", "ClickSoc"):
        return source, checks
    children = {c["id"]: c["contract"] for c in manifest["design"].get("children", [])}
    elapsed = children.get("elapsed_scaler")
    if elapsed is None:
        return source, checks
    if elapsed["module"] != "ElapsedTicks":
        raise ValueError("SERVICE_PROBE_OWNER_MISMATCH")
    anchor = f"initial begin\nforce {top}.reset = 1'b1; #1;\n"
    if source.count(anchor) != 1:
        raise ValueError("SERVICE_PROBE_SHAPE_CHANGED")
    start = source.index(anchor) + len(anchor)
    end = source.index("\n#1;\n", start) + len("\n#1;\n")
    header = source[start:end]
    coverage = list(re.finditer(r"^if \(ones_\d+ !==.*INACTIVE_ENDPOINT:.*$", source, re.M))
    completion = f"CONTRACT_PROBES_PASS:{checks}"
    if not coverage or source.count(completion) != 1:
        raise ValueError("SERVICE_PROBE_SHAPE_CHANGED")
    extra, steps = [header], 0

    def force(path, width, value, primitive=False):
        node, name = path.rsplit(".", 1)
        if ((not primitive and scopes.get(node, {}).get("registers", {}).get(name) != width) or
                f"force {path} = {width}'h0;" not in header):
            raise ValueError("SERVICE_PROBE_DRIVER_MISMATCH")
        extra.append(f"force {path} = {width}'h{value:x};\n")

    def check():
        nonlocal steps
        extra.append("#1; check;\n"); steps += 1

    if top == "ClickSoc":
        for value in (3, 0):
            force(top + ".controlStart_stages", 2, value); check()
    force(elapsed["rtl_path"] + ".returned_stages_0", 1, 1)
    force(elapsed["rtl_path"] + ".returned_stages_1", 1, 1)
    for value in (1, 0):
        force(top + ".gate_first", 32, value)
        force(top + ".gate_second", 32, value); check()
    if top == "FourPhaseSoc":
        address = next((c["contract"] for c in children.get("core", {}).get("children", [])
                        if c["id"] == "address"), {})
        cell = next((p for p in address.get("primitives", []) if p["id"] == "payload"), {})
        if not any(p == {"name": "q", "width": 70, "direction": "output"}
                   for p in cell.get("ports", [])):
            raise ValueError("SERVICE_PROBE_DRIVER_MISMATCH")
        extra.append(header)
        # MemoryRequest = operation[2], address[32], data[32], mask[4].
        # Select a RAM read using the native address latch.
        force(cell["rtl_path"] + ".q", 70, (1 << 68) | (0x20000000 << 36) | 15, primitive=True)
        completion_owner = children.get("completion", {})
        response_owner = next((c["contract"] for c in completion_owner.get("children", []) if c["id"] == "reply"), {})
        payload = next((p for p in response_owner.get("primitives", []) if p["id"] == "payload"), {})
        if payload.get("parameters", {}).get("WIDTH") != "33":
            raise ValueError("SERVICE_PROBE_DRIVER_MISMATCH")
        # MemoryResponse packs data[32:1] above error[0]. Exercise both fields.
        for offset, width in ((1, 32), (0, 1)):
            for value in [0, (1 << width)-1] + [v for bit in range(width)
                    for v in (1 << bit, ((1 << width)-1) ^ (1 << bit))]:
                force(payload["rtl_path"] + ".q", 33, value << offset, primitive=True); check()
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

    persistent = persistent_reset_children(manifest)

    def children(node, inherited=None):
        for child in node["children"]:
            target=inherited
            if node is root:
                target=(top+'.reset' if child.get('id') in persistent else
                    reset_endpoint(manifest,'core_reset') if coordinated_reset(manifest) and child['id']=='core' else
                    presentation_reset(manifest))
            yield child["contract"], target
            yield from children(child["contract"], target)

    for node, target in children(root):
        old = f'if ({node["rtl_path"]}.reset !== {top}.reset) $fatal(1, "RESET_BINDING_MISMATCH");'
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


I2C_PROJECTION_PATH = "complete I2C projection and retained-effect muxes; digital bound only"
I2C_BYTE_PATH = "complete addressed receive-byte transform; digital budget only"


def validate_i2c_publication(node):
    click = any(c["protocol"] == "two-phase-bundled-v1" for c in node["channels"])
    protocol = "two-phase-bundled-v1" if click else "four-phase-bundled-v1"
    if (node["children"] or len(node["channels"]) != 3 or
            {c["id"]:(c["protocol"],c["role"]) for c in node["channels"]} != {
                "in":(protocol,"input"),"frame":(protocol,"output"),"snapshot":(protocol,"output")}):
        raise ValueError("MCU_I2C_PROTOCOL")
    cells={p["id"]:p for p in node["primitives"] if p["model"]!="ChiselAsyncTimingMarker_v1"}
    selective="receive_0" in cells
    if len({p["id"] for p in node["primitives"]})!=len(node["primitives"]):
        raise ValueError("MCU_I2C_CELL_INVENTORY")
    timing={t["id"]:t for t in node["timing"]}
    apertures={f"byte_aperture_{i}" for i in range(33)} if selective else {"byte_aperture"}
    if len(timing)!=len(node["timing"]) or set(timing)!={"projection","projection_aperture","byte_write_transform"}|apertures:
        raise ValueError("MCU_I2C_TIMING_INVENTORY")
    for name,logic,cell,source,sink in (
            ("projection",I2C_PROJECTION_PATH,"data_delay","sources","register_data"),
            ("byte_write_transform",I2C_BYTE_PATH,"byte_data_delay","byte_sources","byte_register_data")):
        expected=dict(kind="bundled-data-path-v1",logic=logic,delay_owner=[],delay_cell=cell,source=source,sink=sink)
        if any(timing[name].get(k)!=v for k,v in expected.items()):raise ValueError("MCU_I2C_PATH_IDENTITY")
    aperture_specs=[("projection_aperture","register_data","capture","captured")]
    aperture_specs += [(f"byte_aperture_{i}","byte_value",f"byte_trigger_{i}",f"byte_q_{i}") for i in range(33)] if selective else [
        ("byte_aperture","byte_register_data","capture","receive_bytes")]
    for name,data,capture,captured in aperture_specs:
        expected=dict(kind="bundled-setup-hold-v1",launch="in_request",transaction="in_data",data_valid=data,
                      capture=capture,captured=captured,setup_fs="100000",hold_fs="100000")
        if any(timing[name].get(k)!=v for k,v in expected.items()):raise ValueError("MCU_I2C_APERTURE")
    width=362 if click else 360
    endpoints={e["id"]:e["width"] for e in node["endpoints"]}
    if len(endpoints)!=len(node["endpoints"]):raise ValueError("MCU_I2C_PATH_WIDTH")
    widths=dict(in_data=174,frame_data=337,snapshot_data=8,observed=15,capture=1,
        sources=785 if click else 783,register_data=width,captured=width,
        byte_sources=16 if selective else 280,byte_register_data=41 if selective else 264,
        receive_bytes=264,write_legal=1)
    if selective:
        widths.update(byte_value=8,byte_triggers=33,byte_idle=1,byte_complete=1)
        widths.update({f"byte_trigger_{i}":1 for i in range(33)})
        widths.update({f"byte_q_{i}":8 for i in range(33)})
    for name,w in widths.items():
        if endpoints.get(name)!=w:raise ValueError("MCU_I2C_PATH_WIDTH")
    expected={"observation":("EventRegister",15),"frame_payload":("EventRegister",337),
        "snapshot_payload":("EventRegister",8),"data_delay":("ControlGate",width),
        "byte_data_delay":("ControlGate",41 if selective else 264)}
    expected.update({n:("ControlGate",1) for n in ("request_delay","acknowledge_guard","output_guard","return_guard")})
    if selective:
        expected.update({f"receive_{i}":("EventRegister",8) for i in range(33)})
        expected.update({f"byte_capture_{i}":("AsymmetricC",None) for i in range(33)})
        expected.update(byte_completion=("AsymmetricC",None),byte_idle_gate=("ControlGate",1))
        size,level=33,0
        while size>1:
            expected.update({f"byte_any_{level}_{i}":("ControlGate",1) for i in range(size//2)})
            size=(size+1)//2;level+=1
    else:expected["receive_all"]=("EventRegister",264)
    if click:
        expected.update(accepted_phase=("PhaseRegister",None),frame_phase=("EventRegister",1),
                        snapshot_phase=("EventRegister",1),pending=("Xor",None))
        prefixes=() if selective else ("capture_gate",)
        if selective:expected["capture_gate"]=("AsymmetricC",None)
    else:
        expected.update({n:("AsymmetricC",None) for n in ("admission","frame_pending","snapshot_pending")})
        prefixes=("frame_publish","snapshot_publish")
    expected.update({p+s:("ControlGate",1) for p in prefixes for s in ("_na","_nb","_or","")})
    if set(cells)!=set(expected):raise ValueError("MCU_I2C_CELL_INVENTORY")
    for name,(model,w) in expected.items():
        c=cells[name];p=c["parameters"]
        if c["model"]!="ChiselAsync"+model+"_v1" or (w is not None and p.get("WIDTH")!=str(w)):
            raise ValueError("MCU_I2C_CELL_POLICY")
        delay=110000000 if name in ("acknowledge_guard","output_guard","return_guard") else (
            11000000 if name=="request_delay" else 10000000 if name in ("data_delay","byte_data_delay") else 1000000)
        if p.get("DELAY_FS")!=str(delay):raise ValueError("MCU_I2C_GUARD_POLICY")
        if model not in ("Xor","ControlGate","AsymmetricC") and p.get("RESET_VALUE")!="0":
            raise ValueError("MCU_I2C_RESET_POLICY")
        if model=="ControlGate":
            op=1 if name.endswith(("_na","_nb")) or name in prefixes or name=="byte_idle_gate" else (
                2 if name.endswith("_or") or name.startswith("byte_any_") else 0)
            reset=1 if name.endswith(("_na","_nb","_or")) or name=="byte_idle_gate" else 0
            if p.get("OP")!=str(op) or p.get("RESET_VALUE")!=str(reset):raise ValueError("MCU_I2C_GATE_POLICY")
        if model=="AsymmetricC" and any(p.get(k)!=str(v) for k,v in dict(COMMON=1,RISING=1,FALLING=0,
                COMMON_INVERT=0,RISING_INVERT=0,FALLING_INVERT=0,RESET_VALUE=0).items()):
            raise ValueError("MCU_I2C_RETENTION_POLICY")
    return click


def i2c_path_bindings(node, section=None):
    click=validate_i2c_publication(node)
    e={x["id"]:x["rtl_path"] for x in node["endpoints"]}
    c={x["id"]:x["rtl_path"] for x in node["primitives"]}
    selective="receive_0" in c
    cat=lambda xs:"{"+",".join(xs)+"}"
    ids=["observation","frame_payload","snapshot_payload"]+(["frame_phase","snapshot_phase"] if click else [])
    receive=cat([c[f"receive_{i}"]+".q" for i in reversed(range(33))]) if selective else c["receive_all"]+".q"
    d=e["in_data"]; legal=f"(!{d}[14] || (!{d}[97] && {d}[13:8] < 6'd33))"
    pairs=[(e["register_data"],c["data_delay"]+".q"),
        (e["register_data"],cat([c[n]+".d" for n in ids])),
        (e["captured"],cat([c[n]+".q" for n in ids])),
        (e["sources"],cat([d,receive]+[c[n]+".q" for n in ids[1:]])),
        (e["observed"],c["observation"]+".q"),(e["frame_data"],c["frame_payload"]+".q"),
        (e["snapshot_data"],c["snapshot_payload"]+".q"),(e["receive_bytes"],receive),
        (e["write_legal"],legal),(e["byte_register_data"],c["byte_data_delay"]+".q")]
    pairs += [(e["capture"],c[n]+".trigger") for n in ids]
    if click:pairs.append((e["byte_complete"] if selective else e["capture"],c["accepted_phase"]+".trigger"))
    pairs += [(e[port],c[guard]+".q") for port,guard in (("in_acknowledge","acknowledge_guard"),
        ("frame_request","output_guard"),("snapshot_request","return_guard"))]
    ack_source="accepted_phase" if click else "byte_completion" if selective else "admission"
    pairs += [(c[n]+".q",c[g]+".a") for n,g in ((ack_source,"acknowledge_guard"),
        ("frame_phase" if click else "frame_pending","output_guard"),
        ("snapshot_phase" if click else "snapshot_pending","return_guard"))]
    projection=cat([d+"[169:166]",d+"[161]",d+"[160]",d+"[159]",d+"[146]",d+"[145]",d+"[103:98]"])
    frame=cat([d+"[96:90]",receive,d+"[89:24]"])
    parts=[projection,f"({d}[97] ? {frame} : {c['frame_payload']}.q)",
        f"({d}[23] ? {d}[22:15] : {c['snapshot_payload']}.q)"]
    if click:parts += [f"({c['frame_phase']}.q ^ {d}[97])",f"({c['snapshot_phase']}.q ^ {d}[23])"]
    pairs.append((c["data_delay"]+".a",cat(parts)))
    pairs += [(e["in_request"],c["request_delay"]+".a"),
        (e["capture"],c["capture_gate" if click else "admission"]+".q")]
    available=f"((!{d}[97] || "+(f"({e['frame_request']} == {e['frame_acknowledge']})" if click else
        f"(!{e['frame_request']} && !{e['frame_acknowledge']})")+") && (!"+d+"[23] || "+(
        f"({e['snapshot_request']} == {e['snapshot_acknowledge']})" if click else
        f"(!{e['snapshot_request']} && !{e['snapshot_acknowledge']})")+f") && {legal}"
    if selective:available+=f" && {e['byte_idle']}"
    available+=")"
    if click:
        pairs += [(c["request_delay"]+".q",c["pending"]+".a"),(c["accepted_phase"]+".q",c["pending"]+".b")]
        if selective:pairs += [(c["pending"]+".q",c["capture_gate"]+".common"),(available,c["capture_gate"]+".rising")]
        else:pairs += [(c["pending"]+".q",c["capture_gate_na"]+".a"),(available,c["capture_gate_nb"]+".a")]
    else:
        pairs += [(c["request_delay"]+".q",c["admission"]+".common"),(available,c["admission"]+".rising")]
        for effect,valid in (("frame",97),("snapshot",23)):
            pairs += [(f"(!{e[effect+'_acknowledge']} || {e['capture']})",c[effect+"_pending"]+".common"),
                (c[effect+"_publish"]+".q",c[effect+"_pending"]+".rising"),
                (e["capture"],c[effect+"_publish_na"]+".a"),(d+f"[{valid}]",c[effect+"_publish_nb"]+".a")]
    for prefix in (("capture_gate",) if click and not selective else () if click else ("frame_publish","snapshot_publish")):
        pairs += [(c[prefix+"_na"]+".q",c[prefix+"_or"]+".a"),(c[prefix+"_nb"]+".q",c[prefix+"_or"]+".b"),
            (c[prefix+"_or"]+".q",c[prefix]+".a")]
    byte_boundary=len(pairs)
    if selective:
        byte_data=c["byte_data_delay"]+".q"
        selects=[f"({d}[14] && {legal} && {d}[13:8] == 6'd{i})" for i in reversed(range(33))]
        pairs += [(e["byte_sources"],cat([d+"[97]",d+"[14:0]"])),
            (c["byte_data_delay"]+".a",cat(selects+[d+"[7:0]"])),(e["byte_value"],byte_data+"[7:0]")]
        triggers=[]
        for i in range(33):
            reg=c[f"receive_{i}"];capture=c[f"byte_capture_{i}"];triggers.append(capture+".q")
            pairs += [(capture+".common",e["capture"]),(capture+".rising",byte_data+f"[{i+8}]"),
                (reg+".trigger",capture+".q"),(reg+".d",byte_data+"[7:0]"),
                (e[f"byte_trigger_{i}"],reg+".trigger"),(e[f"byte_q_{i}"],reg+".q")]
        pairs.append((e["byte_triggers"],cat(list(reversed(triggers)))))
        level=0
        while len(triggers)>1:
            next_level=[]
            for i in range(0,len(triggers),2):
                if i+1==len(triggers):next_level.append(triggers[i]);continue
                gate=c[f"byte_any_{level}_{i//2}"]
                pairs += [(gate+".a",triggers[i]),(gate+".b",triggers[i+1])];next_level.append(gate+".q")
            triggers=next_level;level+=1
        pairs += [(c["byte_idle_gate"]+".a",triggers[0]),(e["byte_idle"],c["byte_idle_gate"]+".q"),
            (c["byte_completion"]+".common",e["capture"]),
            (c["byte_completion"]+".rising",f"(!{d}[14] || {triggers[0]})"),
            (e["byte_complete"],c["byte_completion"]+".q")]
    else:
        parts=[f"({d}[14] && {legal} && {d}[13:8] == 6'd{i} ? {d}[7:0] : {receive}[{i*8+7}:{i*8}])" for i in reversed(range(33))]
        pairs += [(e["byte_sources"],cat([d+"[97]",d+"[14:0]",receive])),
            (c["byte_data_delay"]+".a",cat(parts)),(c["receive_all"]+".d",e["byte_register_data"]),
            (c["receive_all"]+".trigger",e["capture"])]
    if section is None:return pairs
    if section=="projection":return pairs[:byte_boundary]
    if section=="byte":return pairs[byte_boundary:]
    raise ValueError("MCU_I2C_BINDING_SECTION")


def validate_fabric_inventory(manifest):
    """Required obligations cannot vanish along with their passive markers."""
    def visit(node):
        module = node["module"]
        if re.fullmatch(r"(?:FourPhase|Click)ProgramReturn(?:_[0-9]+)?", module):
            validate_program_return(node)
        if re.fullmatch(r"(?:FourPhase|Click)RamReturn(?:_[0-9]+)?", module):
            validate_ram_return(node)
        if re.fullmatch(r"(?:FourPhase|Click)RecoveryReturn(?:_[0-9]+)?", module):
            validate_recovery_return(node)
        if re.fullmatch(r"(?:FourPhase|Click)PublicationSource(?:_[0-9]+)?", module):
            validate_publication_source(node)
        if re.fullmatch(r"(?:FourPhase|Click)ProgramSource(?:_[0-9]+)?", module):
            validate_program_source(node)
        if re.fullmatch(r"(?:FourPhase|Click)RamSource(?:_[0-9]+)?", module):
            validate_ram_source(node)
        if re.fullmatch(r"(?:FourPhase|Click)Admission(?:_[0-9]+)?", module):
            validate_admission(node)
        if re.fullmatch(r"(?:FourPhase|Click)Completion(?:_[0-9]+)?", module):
            validate_completion(node)
        if re.fullmatch(r"I2cPublication(?:_[0-9]+)?", module):
            validate_i2c_publication(node)
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
    if logic in FRAME_STORE_PATHS:
        validate_frame_store_metadata(node)
        if timing != frame_store_timing(node['module'].startswith('Click'))[0]:
            raise ValueError("FRAME_STORE_PATH_BINDING")
        return
    if logic in PROGRAM_RETURN_PATHS:
        validate_program_return(node,resolved=True)
        return
    if logic in RAM_RETURN_PATHS:
        validate_ram_return(node,resolved=True)
        return
    if logic in RECOVERY_RETURN_PATHS:
        validate_recovery_return(node)
        return
    if logic in PUBLICATION_PATHS:
        validate_publication_source(node)
        return
    if logic in PROGRAM_PATHS:
        validate_program_source(node)
        return
    if logic in (ARM_PATH, RETIRE_PATH):
        validate_ram_source(node)
        return
    if logic in (BD_COMPLETION_PATH, CLICK_COMPLETION_PATH):
        validate_completion(node)
        return
    if logic in (I2C_PROJECTION_PATH,I2C_BYTE_PATH):
        validate_i2c_publication(node)
        return
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
    if manifest["top"] not in ("ClickSoc", "ClickCore", "ClickFabric", "ClickControl", "ClickTelemetry", "ClickSupervisor", "ClickElapsed", "ClickSample", "ClickSram", "ClickI2c", "ClickSpiAdc", "ClickHousekeeping", "ClickCompletion", "ClickAdmission", "ClickRamSource", "ClickProgramSource", "ClickPublicationSource", "ClickFrameStore"):
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


SPI_PROGRAM = {"initialCsN": (1, 0), "initialSclk": (1, 0),
               "occupied": (32, 0xffffffff), "csN": (32, 0x80000000), "sclk": (32, 0x55555555)}


def spi_program_probe(source, manifest, scopes):
    """Check immutable native definitions and the player recipe boundary.

    Register-load behavior is covered separately by actual-player mutation tests.
    Constants are ordinary ports, not dynamic endpoints: assert their exact
    values at every generic mapping step. No endpoint activity check is removed
    or overridden and no program, recipe or derived endpoint is forced.
    """
    comparisons = []
    def visit(node, parent=None):
        native = re.fullmatch(r"(FourPhase|Click)SpiAdc(?:_[0-9]+)?", node["module"])
        if re.fullmatch(r"SpiAdc(?:_[0-9]+)?", node["module"]):
            children = {c["id"]: c["contract"] for c in node["children"]}
            if (set(children) != {"native", "command_bridge", "reply_bridge", "wave_bridge", "capture_bridge"}
                    or not re.fullmatch(r"(FourPhase|Click)SpiAdc(?:_[0-9]+)?", children["native"]["module"])):
                raise ValueError("MCU_SPI_OWNER_INVENTORY")
        if native:
            protocol = "two-phase-bundled-v1" if native[1] == "Click" else "four-phase-bundled-v1"
            if {c["id"]: (c["protocol"], c["role"]) for c in node["channels"]} != {
                    "command": (protocol, "input"), "reply": (protocol, "output"),
                    "wave": (protocol, "output"), "capture": (protocol, "input")}:
                raise ValueError("MCU_SPI_PROTOCOL")
            path = node["rtl_path"]
            ports = scopes[path]["ports"]
            if {p for p in ports if p.startswith("program_")} != {"program_"+f for f in SPI_PROGRAM}:
                raise ValueError("MCU_SPI_PROGRAM_INVENTORY")
            for field, (width, value) in SPI_PROGRAM.items():
                pin = "program_"+field
                if ports[pin] != dict(name=pin, width=width, direction="output"):
                    raise ValueError("MCU_SPI_PROGRAM_PORT")
                comparisons.append(f'if ({path}.{pin} !== {width}\'h{value:x}) $fatal(1,"MCU_SPI_PROGRAM_VALUE:{field}");')
                if parent is not None and re.fullmatch(r"SpiAdc(?:_[0-9]+)?", parent["module"]):
                    player = parent["rtl_path"]
                    recipe = "recipe_"+field
                    if scopes[player]["nets"].get(recipe) != width:
                        raise ValueError("MCU_SPI_PLAYER_PIN")
                    comparisons.append(f'if ({player}.{recipe} !== {path}.{pin}) $fatal(1,"MCU_SPI_PLAYER_BINDING:{field}");')
        for child in node["children"]:
            visit(child["contract"], node)
    visit(manifest["design"])
    if not comparisons:
        return source
    anchor = "task check; begin"
    if source.count(anchor) != 1:
        raise ValueError("MCU_SPI_PROBE_SHAPE")
    return source.replace(anchor, anchor+"\n"+"\n".join(comparisons))


def fabric_path_bindings(node, timing):
    """Actual mux/storage pin comparisons added to the unchanged library probe."""
    if timing.get("logic") in FRAME_STORE_PATHS:
        click=validate_frame_store_metadata(node,resolved=True)
        endpoints={e['id']:e['rtl_path'] for e in node['endpoints']}
        cells={p['id']:p['rtl_path'] for p in node['primitives']}
        if not click:
            return [(endpoints['route_data'],cells['data_delay']+'.q'),
                    (endpoints['route_data'],cells['route']+'.d'),
                    (cells['data_delay']+'.a',"("+endpoints['route_value']+" + 2'h1)"),
                    (endpoints['route_capture'],cells['request_delay']+'.q'),
                    (endpoints['route_capture'],cells['route']+'.trigger'),
                    (endpoints['route_value'],cells['route']+'.q'),
                    (endpoints['in_request'],cells['request_delay']+'.a')]
        cat=lambda values:'{'+','.join(values)+'}'
        state=cat([cells[k+str(i)]+'.q' for i in reversed(range(4)) for k in ('payload','phase')])
        captured=cat([cells['route']+'.q',state])
        data=cat([cells['route']+'.d']+[cells[k+str(i)]+'.d' for i in reversed(range(4)) for k in ('payload','phase')])
        result=[(endpoints['register_data'],cells['data_delay']+'.q'),(endpoints['register_data'],data),
                (endpoints['captured'],captured),
                (endpoints['sources'],cat([cells['route']+'.q',endpoints['in_data'],state])),
                (endpoints['capture_event'],cells['capture']+'.q'),
                (endpoints['in_request'],cells['request_delay']+'.a'),
                (endpoints['in_acknowledge'],cells['acknowledge_guard']+'.q')]
        result += [(endpoints['capture_event'],cells[k]+'.trigger') for k in
                   [kind+str(i) for i in range(4) for kind in ('payload','phase')]+['accepted_phase','route']]
        return result
    if timing.get("logic") in PROGRAM_RETURN_PATHS:
        return program_return_bindings(node,resolved=True)
    if timing.get("logic") in RAM_RETURN_PATHS:
        return ram_return_bindings(node,resolved=True)
    if timing.get("logic") in RECOVERY_RETURN_PATHS:
        return recovery_return_bindings(node)
    if timing.get("logic") in PUBLICATION_PATHS:
        return publication_source_bindings(node)
    if timing.get("logic") in PROGRAM_PATHS:
        return program_source_bindings(node)
    if timing.get("logic") in (ARM_PATH, RETIRE_PATH):
        return ram_source_bindings(node)
    if timing.get("logic") in (BD_COMPLETION_PATH, CLICK_COMPLETION_PATH):
        return completion_bindings(node)
    if timing.get("logic") in (I2C_PROJECTION_PATH,I2C_BYTE_PATH):
        return i2c_path_bindings(node,"byte" if timing["logic"]==I2C_BYTE_PATH else "projection")
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
             + f' {CLICK_FABRIC_PATH!r}: ([], "data_delay", "reply_sources", "register_data"),'
             + f' {I2C_PROJECTION_PATH!r}: ([], "data_delay", "sources", "register_data"),'
             + f' {I2C_BYTE_PATH!r}: ([], "byte_data_delay", "byte_sources", "byte_register_data"),'
             + ','.join(f'{t["logic"]!r}: ([], "data_delay", {t["source"]!r}, {t["sink"]!r})'
                        for t in (frame_store_timing(False)[0],frame_store_timing(True)[0]))+','
             + f' {BD_COMPLETION_PATH!r}: (["reply"], "data_delay", "result_sources", "result"),'
             + f' {CLICK_COMPLETION_PATH!r}: ([], "data_delay", "result_sources", "register_data"),'
             + f' {ARM_PATH!r}: ([], "arm_data_delay", "reserved", "arm_data"),'
             + f' {RETIRE_PATH!r}: ([], "data_delay", "retire_sources", "register_data"),'
             + f' {PROGRAM_PATHS[0]!r}: ([], "arm_data_delay", "arm_sources", "arm_data"),'
             + f' {PROGRAM_PATHS[1]!r}: ([], "data_delay", "retire_sources", "register_data"),'
             + f' {PROGRAM_PATHS[2]!r}: ([], "stored_data_delay", "stored_target", "stored_phase_data"),'
             + ','.join(f'{logic!r}: ([], {delay!r}, {src!r}, {sink!r})' for _,logic,src,sink,delay in PUBLICATION_PATH_TABLE+RECOVERY_RETURN_PATH_TABLE)+','
             + ','.join(f'{t["logic"]!r}: ([], {t["delay_cell"]!r}, '+
                 ("('input_sources' if node['module'].startswith('Click') else 'word_data')" if t['source']=='input_sources' else repr(t['source']))+
                 f', {t["sink"]!r})' for policy in (ram_return_policy,program_return_policy)
                 for t in policy('click')['timings'] if t['kind']=='bundled-data-path-v1')+'}'
             + "\n                validate_fabric_path(node, timing)")
    source = source.replace(anchor, extra)
    anchor = 'if timing["logic"] in ("exclusive-merge-input-mux", "controlled-multiplexer-input-mux"):'
    if source.count(anchor) != 1:
        raise ValueError("MCU_FABRIC_CHECKER_SHAPE_CHANGED")
    source = source.replace(anchor,
        f'if timing["logic"] in ({BD_FABRIC_PATH!r}, {CLICK_FABRIC_PATH!r}, {I2C_PROJECTION_PATH!r}, {I2C_BYTE_PATH!r}, {BD_COMPLETION_PATH!r}, {CLICK_COMPLETION_PATH!r}, {ARM_PATH!r}, {RETIRE_PATH!r}, {PROGRAM_PATHS[0]!r}, {PROGRAM_PATHS[1]!r}, {PROGRAM_PATHS[2]!r},'+','.join(map(repr,PUBLICATION_PATHS+RECOVERY_RETURN_PATHS+RAM_RETURN_PATHS+PROGRAM_RETURN_PATHS+FRAME_STORE_PATHS))+'):\n'
        '                    pairs = fabric_path_bindings(node, timing)\n'
        '                el' + anchor)
    # A mixed-reset raw response is not a same-reset library channel. Its
    # separately closed schema still supplies independent scalar-port packing
    # comparisons; do not infer an aggregate response_bits net that does not exist.
    anchor = '        for endpoint in node["endpoints"]:\n            fields = layouts.get'
    if source.count(anchor) != 1:raise ValueError("RAM_RETURN_LAYOUT_CHECKER_SHAPE")
    source = source.replace(anchor,
        '        if re.fullmatch(r"(?:FourPhase|Click)(?:Ram|Program)Return(?:_[0-9]+)?", node["module"]):\n'
        '            value = endpoint_by_id["response_data"]["source"]\n'
        '            layouts["response_data"] = [{"source": value+".error", "lsb": 0, "width": 1}, {"source": value+".data", "lsb": 1, "width": 32}]\n'
        '        if re.fullmatch(r"(?:FourPhase|Click)FrameStore(?:_[0-9]+)?", node["module"]):\n'
        '            value = endpoint_by_id["available"]["source"]\n'
        '            layouts["available"] = [{"source": value+f"[{i}]", "lsb": i, "width": 1} for i in range(4)]\n' + anchor)
    # BD's captured-word arm uses the explicitly checked request_guard. Keep
    # every original budget comparison and validate its complete wiring above.
    anchor = 'request = next((p for p in budget_owner["primitives"] if p["id"] == "request_delay"), None)'
    if source.count(anchor) != 1:raise ValueError("RAM_RETURN_GUARD_CHECKER_SHAPE")
    source = source.replace(anchor,
        'request = next((p for p in budget_owner["primitives"] if p["id"] == '
        '("request_guard" if re.fullmatch(r"FourPhase(?:Ram|Program)Return(?:_[0-9]+)?", budget_owner["module"]) else "request_delay")), None)')
    anchor = '    if "INACTIVE_ENDPOINT:" in simulation.stdout:'
    if source.count(anchor) != 1:
        raise ValueError("MCU_FABRIC_CHECKER_SHAPE_CHANGED")
    # Preserve the first attempt even if the library starts a larger paired probe.
    return source.replace(anchor,
        '    (directory / "contract_first_simulation.log").write_text(simulation.stdout + simulation.stderr, encoding="utf-8")\n'
        '    (directory / "contract_first_probe.sv").write_text(probe, encoding="utf-8")\n' + anchor)


def activity_diagnostics(source):
    """Report every unmet polarity obligation before the original fatal checks.

    Long SoC runs should expose all missing stimulus combinations in one attempt.
    Keep each original condition/fatal untouched, including literal-leaf masks.
    This adds only observations and never turns a failed campaign into a pass.
    """
    pattern = re.compile(r'^if \((ones_(\d+) !== ([^|]+) \|\| zeros_\2 !== ([^)]+))\) '
                         r'\$fatal\(1, "INACTIVE_ENDPOINT:([^"]+)"\);$', re.M)
    matches = list(pattern.finditer(source))
    if not matches:
        raise ValueError('MAPPING_ACTIVITY_DIAGNOSTIC_SHAPE')
    diagnostics = ''.join(
        f'if ({m[1]}) $display("ACTIVITY_GAP:{m[5]}:ones=%h zeros=%h expected_ones=%h expected_zeros=%h", '
        f'ones_{m[2]}, zeros_{m[2]}, {m[3]}, {m[4]});\n' for m in matches)
    position = matches[0].start()
    return source[:position] + diagnostics + source[position:]


class MappingProbeAttestation:
    """Bind a strict PASS to the exact probe that was compiled and executed.

    resolved.json binds RTL and metadata. This additional receipt prevents a
    later edited testbench from borrowing that positive baseline for mutations.
    Every hash is taken from file bytes; the simulated output is also compared
    with the library's saved log before recording PASS.
    """
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.compiled = None
        self.simulated = None

    def digest(self, name):
        return hashlib.sha256((self.directory / name).read_bytes()).hexdigest()

    def sources(self):
        paths = [Path(line.strip()) for line in
                 (self.directory / 'filelist.f').read_text().splitlines() if line.strip()]
        if any(not (self.directory / p).resolve().is_relative_to(self.directory) for p in paths):
            raise ValueError('MAPPING_ATTESTATION_NONLOCAL_SOURCE')
        if len({p.name for p in paths}) != len(set(paths)):
            raise ValueError('MAPPING_ATTESTATION_AMBIGUOUS_SOURCE')
        return {p.name: self.digest(p) for p in paths}

    def snapshot(self):
        # Closed policies also inspect layer bindings that are not compiled by
        # the mapping probe. Attest those inputs without claiming execution of
        # uninstantiated verification modules; functional suites inline them.
        auxiliary = {str(p.relative_to(self.directory)).replace('\\', '/'): self.digest(p)
                     for p in sorted((self.directory / 'verification').rglob('*')) if p.is_file()}
        return dict(probe_sha256=self.digest('contract_probe.sv'), source_sha256=self.sources(),
                    validation_auxiliary_sha256=auxiliary)

    def validate_command(self, parts, compile_probe):
        if not compile_probe:
            if parts[1:] != ['contract_probe.vvp']:
                raise ValueError('MAPPING_ATTESTATION_SIMULATION_COMMAND')
            return
        files, outputs, tops = [], [], []
        index = 1
        while index < len(parts):
            part = parts[index]
            if part in ('-s', '-o') and index + 1 < len(parts):
                (tops if part == '-s' else outputs).append(parts[index + 1])
                index += 2
            elif part in ('-g2012', '-DCHISEL_ASYNC_MAPPING'):
                index += 1
            elif part.startswith('-'):
                raise ValueError('MAPPING_ATTESTATION_COMPILE_OPTION')
            else:
                files.append((self.directory / part).resolve())
                index += 1
        expected = {(self.directory / line.strip()).resolve() for line in
                    (self.directory / 'filelist.f').read_text().splitlines() if line.strip()}
        expected.add(self.directory / 'contract_probe.sv')
        if outputs != ['contract_probe.vvp'] or tops.count('ContractProbe') != 1 or set(files) != expected or len(files) != len(expected):
            raise ValueError('MAPPING_ATTESTATION_COMPILE_COMMAND')

    def run(self, runner, command, *args, **kwargs):
        parts = list(map(str, command))
        executable = Path(parts[0]).stem.lower()
        compile_probe = executable == 'iverilog' and 'ContractProbe' in parts
        simulate_probe = executable == 'vvp' and 'contract_probe.vvp' in parts
        if not (compile_probe or simulate_probe):
            return runner(command, *args, **kwargs)
        if Path(kwargs.get('cwd', '.')).resolve() != self.directory:
            raise ValueError('MAPPING_ATTESTATION_WORKDIR')
        self.validate_command(parts, compile_probe)
        before = self.snapshot()
        if simulate_probe:
            if self.compiled is None or before != self.compiled['inputs'] or self.digest('contract_probe.vvp') != self.compiled['vvp']:
                raise ValueError('MAPPING_ATTESTATION_CHANGED_BEFORE_EXECUTION')
        else:
            self.compiled = None
        self.simulated = None
        result = runner(command, *args, **kwargs)
        if self.snapshot() != before:
            raise ValueError('MAPPING_ATTESTATION_INPUT_CHANGED_DURING_EXECUTION')
        if compile_probe and result.returncode == 0:
            self.compiled = dict(inputs=before, vvp=self.digest('contract_probe.vvp'), command=parts)
        if simulate_probe:
            if self.digest('contract_probe.vvp') != self.compiled['vvp']:
                raise ValueError('MAPPING_ATTESTATION_BINARY_CHANGED_DURING_EXECUTION')
            self.simulated = dict(returncode=result.returncode, output=result.stdout + result.stderr, command=parts)
        return result

    def finish(self, result):
        if result.get('status') != 'PASS' or self.simulated is None or self.simulated['returncode'] != 0:
            raise ValueError('MAPPING_ATTESTATION_NO_EXECUTED_PASS')
        if self.snapshot() != self.compiled['inputs'] or self.digest('contract_probe.vvp') != self.compiled['vvp']:
            raise ValueError('MAPPING_ATTESTATION_CHANGED_AFTER_EXECUTION')
        output = self.simulated['output']
        if ((self.directory / 'contract_simulation.log').read_text(encoding='utf-8') != output or
                re.findall(r'CONTRACT_PROBES_PASS:(\d+)', output) != [str(result['mapping_checks'])] or
                re.search(r'FATAL|TIMEOUT|DEADLINE', output)):
            raise ValueError('MAPPING_ATTESTATION_SIMULATION_LOG')
        if result['source_sha256'] != self.compiled['inputs']['source_sha256']:
            raise ValueError('MAPPING_ATTESTATION_SOURCE_RECEIPT')
        record = dict(schema='riscay-mapping-probe-attestation-v1', status='PASS',
                      **self.compiled['inputs'], compiled_vvp_sha256=self.compiled['vvp'],
                      simulation_log_sha256=self.digest('contract_simulation.log'),
                      mapping_checks=result['mapping_checks'], semantic_sha256=result['semantic_sha256'],
                      compile_command=self.compiled['command'], simulation_command=self.simulated['command'])
        (self.directory / 'mapping-probe-attestation.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
        return record


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
    library_source = source.read_text()
    exec(compile(fabric_checker_source(library_source), str(source), "exec"), module.__dict__)
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
    module.read_vvp = lambda contents: literal_nets(contents, sram_array_shapes(contents, original_vvp(contents)))
    verified_sram = set()
    def memories(directory, node, scopes):
        macros = sram_scopes(directory, node, scopes)
        verified_sram.update(macros)
        return original_memories(directory, node, scopes) | macros
    module.validate_memories = memories

    def probe(manifest, scopes, paired=False):
        # A failed first attempt must remain a failure when its fallback cannot
        # fit the reviewed resource budget; never allocate the full pair list.
        if paired:
            require_paired_probe_budget(manifest, scopes, library_source)
        top_rtl=(args.directory / (manifest["top"]+".sv")).read_text(encoding="utf-8")
        validate_application_reset(manifest,scopes,top_rtl)
        program_bytes = control_program_bytes(args.directory, manifest, scopes)
        validate_service_reply_rtl(manifest,args.directory,program_bytes)
        native_clock_inventory(manifest,scopes)
        held_bindings = validate_held_receipts(manifest,args.directory,scopes)
        if args.soc or program_bytes is not None:
            if not coordinated_reset(manifest): raise ValueError('SOC_COORDINATED_RESET_REQUIRED')
            check_reset_crossings(args.directory,manifest)
        program_address_proof = (prove_program_address(args.directory, manifest, program_bytes)
                                 if program_bytes is not None else None)
        validate_program_receipts(manifest,args.directory)
        validate_frame_receipts(manifest,args.directory)
        validate_frame_stores(manifest,args.directory,resolved=True)
        validate_return_receipts(manifest,args.directory,scopes)
        source, count = original_probe(manifest, scopes, paired)
        source = service_reply_probe(source, manifest, scopes, program_bytes)
        source = request_receipt_probe(source, manifest, scopes)
        source = held_receipt_probe(source, held_bindings)
        source = spi_program_probe(source, manifest, scopes)
        source, count = register_file_background(source, manifest, count)
        source, count = control_background(source, manifest, scopes, count, program_bytes)
        source, count = frame_head_background(source, manifest, scopes, count)
        source, count = i2c_background(source, manifest, scopes, count)
        source, count = sram_background(source, manifest, scopes, count, program_bytes)
        source, count = service_background(source, manifest, scopes, count)
        source, count = completion_background(source, manifest, scopes, count, program_bytes)
        source, count = publication_recovery_background(source, manifest, scopes, count)
        if args.sleep_clock:
            source, count = sleep_clock_background(source, manifest, scopes, count)
        if args.soc:
            source = generated_reset_probe(source, manifest)
        if args.vector_coverage:
            source = vector_coverage_probe(source, manifest)
        source = completion_constants_probe(source, manifest, scopes,
            (args.directory / (manifest["top"]+".sv")).read_text(encoding="utf-8"))
        source = admission_probe(source, manifest, scopes)
        source = ram_source_probe(source, manifest, scopes)
        literal_obligations=[]
        source = ram_return_probe(source, manifest, scopes, args.directory,literal_obligations=literal_obligations)
        source = program_return_probe(source, manifest, scopes, args.directory,literal_obligations=literal_obligations)
        source = apply_return_literal_obligations(source,literal_obligations)
        source = program_source_probe(source, manifest, scopes)
        source = publication_source_probe(source, manifest, scopes)
        source = frame_receipt_probe(source, manifest, scopes, args.directory)
        if program_address_proof is not None:
            source = program_address_probe(source, program_address_proof)
        if args.vector_coverage:
            source = activity_diagnostics(source)
        return source, count
    module.probe_source = probe

    attestation = MappingProbeAttestation(args.directory)
    (args.directory / 'mapping-probe-attestation.json').write_text(
        json.dumps(dict(schema='riscay-mapping-probe-attestation-v1', status='RUNNING'))+'\n', encoding='utf-8')

    def run(command, *pargs, **kwargs):
        kwargs["timeout"] = probe_timeout(command, kwargs.get("timeout"),
                                         args.probe_timeout, args.probe_compile_timeout)
        return attestation.run(original_run, command, *pargs, **kwargs)

    subprocess.run = run
    try:
        result = module.validate_export(args.directory.resolve())
        attestation.finish(result)
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
