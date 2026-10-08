# SPDX-License-Identifier: Apache-2.0
"""Build/audit RV32E sizing workloads with pinned GCC, without a system install."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware"
TOOLCHAIN = ROOT / ".tools/riscv-gcc"
APPS = ("event_loop", "runtime_stress")
FLAGS = ["-march=rv32e", "-mabi=ilp32e", "-Os", "-std=c11", "-ffreestanding",
         "-fno-builtin", "-fno-stack-protector", "-fno-pic", "-msmall-data-limit=0",
         "-mno-relax", "-ffunction-sections", "-fdata-sections", "-fstack-usage",
         "-fcallgraph-info=su", "-Wall", "-Wextra", "-Werror"]
ALLOWED = set("lui auipc jal jalr beq bne blt bge bltu bgeu lb lh lw lbu lhu sb sh sw "
              "addi slti sltiu xori ori andi slli srli srai add sub sll slt sltu xor "
              "srl sra or and fence ebreak".split())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bootstrap() -> None:
    (TOOLCHAIN / "debs").mkdir(parents=True, exist_ok=True)
    for package in json.loads((FW / "toolchain-lock.json").read_text())["packages"]:
        archive = TOOLCHAIN / "debs" / package["file"]
        if not archive.exists():
            with urllib.request.urlopen(package["url"], timeout=60) as response:
                archive.write_bytes(response.read())
        if digest(archive) != package["sha256"]:
            raise ValueError(f"TOOLCHAIN_HASH_MISMATCH: {archive.name}")
        subprocess.run(["dpkg-deb", "-x", str(archive), str(TOOLCHAIN / "root")], check=True, timeout=120)


def audit_instructions(disassembly: str) -> int:
    count = 0
    for line in disassembly.splitlines():
        match = re.match(r"\s*[0-9a-f]+:\s+([0-9a-f]+)\s+(\S+)\s*(.*)", line)
        if not match:
            continue
        encoding, mnemonic, operands = match.groups()
        if len(encoding) != 8 or mnemonic not in ALLOWED:
            raise ValueError(f"UNSUPPORTED_INSTRUCTION: {line.strip()}")
        if any(int(x) >= 16 for x in re.findall(r"\bx(\d+)\b", operands.split("#")[0])):
            raise ValueError(f"RV32E_UPPER_REGISTER: {line.strip()}")
        count += 1
    if count == 0:
        raise ValueError("NO_INSTRUCTIONS")
    return count


def stack_bound(graphs: list[str], root: str = "main") -> tuple[int, list[str], dict[str, int]]:
    frames: dict[str, int] = {}
    edges: dict[str, set[str]] = {}
    for graph in graphs:
        for name, label in re.findall(r'node:\s*\{\s*title:\s*"([^"]+)"\s+label:\s*"([^"]+)"', graph):
            frame = re.search(r"(\d+) bytes \(static\)", label)
            if frame:
                size = int(frame[1])
                if name in frames and frames[name] != size:
                    raise ValueError(f"AMBIGUOUS_STACK_FRAME: {name}")
                frames[name] = size
        for caller, callee in re.findall(r'edge:\s*\{\s*sourcename:\s*"([^"]+)"\s+targetname:\s*"([^"]+)"', graph):
            edges.setdefault(caller, set()).add(callee)
    def visit(name: str, path: list[str]) -> tuple[int, list[str]]:
        if name in path:
            raise ValueError(f"RECURSIVE_STACK: {name}")
        if name not in frames:
            raise ValueError(f"UNBOUNDED_OR_UNKNOWN_STACK: {name}")
        children = [visit(child, path + [name]) for child in sorted(edges.get(name, set()))]
        amount, chain = max(children, default=(0, []), key=lambda value: value[0])
        return frames[name] + amount, [name] + chain
    amount, chain = visit(root, [])
    return amount, chain, frames


def build(app: str, output: Path, memory: dict) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    for name in ("report.json", "firmware.elf", "firmware.bin", "firmware.hex"):
        (output / name).unlink(missing_ok=True)
    prefix = TOOLCHAIN / "root/usr/bin/riscv64-unknown-elf-"
    env = dict(os.environ)
    env["PATH"] = str(prefix.parent) + os.pathsep + env.get("PATH", "")
    def run(tool: str, args: list[str], log: str | None = None) -> str:
        command = [str(prefix) + tool, *args]
        result = subprocess.run(command, cwd=output, env=env, text=True, capture_output=True, timeout=120)
        if log:
            (output / log).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout
    version = run("gcc", ["-dumpfullversion"]).strip()
    if version != json.loads((FW / "toolchain-lock.json").read_text())["gcc_version"]:
        raise ValueError(f"UNPINNED_GCC: {version}")
    sources = [FW / "startup.S", FW / "runtime.c", FW / "apps" / (app + ".c")]
    objects = []
    for source in sources:
        obj = source.stem + ".o"
        run("gcc", [*FLAGS, f"-ffile-prefix-map={ROOT}=.", "-I", str(FW / "include"), "-c", str(source), "-o", obj], source.stem + ".log")
        objects.append(obj)
    definitions = [f"-Wl,--defsym={key}={memory[value]}" for key, value in
                   (("PROGRAM_BYTES", "program_bytes"), ("RAM_BYTES", "working_ram_bytes"),
                    ("STACK_BYTES", "stack_reserve_bytes"), ("GUARD_BYTES", "guard_bytes"))]
    run("gcc", [*FLAGS, "-nostdlib", "-nostartfiles", "-Wl,--no-relax,--gc-sections,--build-id=none",
                *definitions, "-T", str(FW / "linker.ld"), "-Wl,-Map=firmware.map", *objects, "-o", "firmware.elf"], "link.log")
    run("objcopy", ["-O", "binary", "firmware.elf", "firmware.bin"])
    disassembly = run("objdump", ["-d", "-M", "no-aliases,numeric", "firmware.elf"], "firmware.disasm")
    instructions = audit_instructions(disassembly)
    run("readelf", ["-h", "-A", "-S", "-l", "firmware.elf"], "firmware.readelf")
    symbols = {name: int(address, 16) for address, _, name in
               re.findall(r"^([0-9a-f]+)\s+(\S)\s+(\S+)$", run("nm", ["-n", "firmware.elf"]), re.M)}
    sizes = {name: int(size) for name, size in re.findall(r"^(\.\S+)\s+(\d+)\s+\d+$",
                                                       run("size", ["-A", "firmware.elf"], "firmware.size"), re.M)}
    maximum, chain, frames = stack_bound([(output / (source.stem + ".ci")).read_text()
                                       for source in sources if source.suffix == ".c"])
    if maximum > memory["stack_reserve_bytes"]:
        raise ValueError(f"STACK_RESERVE_EXCEEDED: {maximum}")
    binary = (output / "firmware.bin").read_bytes()
    if len(binary) % 4 or len(binary) > memory["program_bytes"]:
        raise ValueError("PROGRAM_IMAGE_BUDGET_OR_ALIGNMENT")
    static = symbols["__static_end"] - memory["ram_origin"]
    if static + memory["guard_bytes"] + maximum > memory["working_ram_bytes"]:
        raise ValueError("RAM_BUDGET_EXCEEDED")
    (output / "firmware.hex").write_text("".join(f"{int.from_bytes(binary[i:i+4], 'little'):08x}\n" for i in range(0, len(binary), 4)))
    report = {
        "application": app, "compiler": run("gcc", ["--version"]).splitlines()[0], "flags": FLAGS,
        "compiler_sha256": digest(Path(str(prefix) + "gcc")),
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in
                          [*sources, FW / "include/riscay.h", FW / "linker.ld", FW / "memory.json"]},
        "binary_sha256": digest(output / "firmware.bin"), "crc32": zlib.crc32(binary),
        "memory": memory, "entry_offset": symbols["_start"] - memory["program_origin"],
        "image_bytes": len(binary), "sections": sizes, "static_ram_bytes": static,
        "static_stack_bound_bytes": maximum, "stack_chain": chain, "stack_frames": frames,
        "ram_required_with_guard_bytes": static + maximum + memory["guard_bytes"],
        "program_spare_bytes": memory["program_bytes"] - len(binary),
        "ram_spare_after_reserved_stack_bytes": memory["working_ram_bytes"] - static - memory["guard_bytes"] - memory["stack_reserve_bytes"],
        "instructions_audited": instructions, "symbols": symbols,
        "limitations": "Direct, static, nonrecursive C call graph only; startup uses no stack. No heap, interrupts, libc, M or C extension. Runtime SP evidence is separate."
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    if os.name == "nt":
        script = subprocess.check_output(["wsl", "-d", "Ubuntu", "--exec", "wslpath", "-u", str(Path(__file__).resolve())], text=True).strip()
        return subprocess.run(["wsl", "-d", "Ubuntu", "--exec", "python3", script, *sys.argv[1:]], check=False).returncode
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--app", choices=APPS, action="append")
    parser.add_argument("--output", default="build/firmware")
    parser.add_argument("--program-bytes", type=int)
    parser.add_argument("--ram-bytes", type=int)
    args = parser.parse_args()
    if args.bootstrap:
        bootstrap()
    memory = json.loads((FW / "memory.json").read_text())
    if args.program_bytes is not None:
        memory["program_bytes"] = args.program_bytes
    if args.ram_bytes is not None:
        memory["working_ram_bytes"] = args.ram_bytes
    for app in args.app or APPS:
        report = build(app, ROOT / args.output / app, memory)
        print(f"{app}: image={report['image_bytes']} static RAM={report['static_ram_bytes']} "
              f"stack bound={report['static_stack_bound_bytes']} guard={memory['guard_bytes']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"firmware: {error}", file=sys.stderr)
        sys.exit(1)
