# SPDX-License-Identifier: Apache-2.0
"""Run chisel-async export checks with MCU timeout/generated-reset support.

The library defaults to 60 seconds, which its small component probes fit. This
adapter extends the contract probe's compilation and simulation limits. With
--soc it checks child reset wiring against the generated system-reset endpoint, rather
than the external POR input. All endpoint/timing/coverage checks are retained.
The library checkout is an explicit development dependency.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import re


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

    def children(node):
        for child in node["children"]:
            yield child["contract"]
            yield from children(child["contract"])

    for node in children(root):
        old = f'if ({node["rtl_path"]}.reset !== {top}.reset) $fatal(1, "RESET_BINDING_MISMATCH");'
        new = f'if ({node["rtl_path"]}.reset !== {reset}) $fatal(1, "RESET_BINDING_MISMATCH");'
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
    spec.loader.exec_module(module)
    original_run = subprocess.run
    original_probe = module.probe_source

    def probe(manifest, scopes, paired=False):
        source, count = original_probe(manifest, scopes, paired)
        source, count = register_file_background(source, manifest, count)
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
        module.probe_source = original_probe
    import json
    print(json.dumps({"status": result["status"], "semantic_sha256": result["semantic_sha256"],
                      "endpoints": len(result["endpoints"]), "mapping_checks": result["mapping_checks"],
                      "probe_timeout_seconds": args.probe_timeout,
                      "probe_compile_timeout_seconds": args.probe_compile_timeout,
                      "sleep_clock_background": args.sleep_clock,
                      "coverage": "packed-equivalent" if args.vector_coverage else "library-scalar",
                      "reset_contract": "generated-system-reset" if args.soc else "flat-library-reset"}, indent=2))


if __name__ == "__main__":
    main()
