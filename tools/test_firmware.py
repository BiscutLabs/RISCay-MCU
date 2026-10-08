# SPDX-License-Identifier: Apache-2.0
"""Independent negative controls for code, stack and linker budget checks."""
from pathlib import Path
import os
import subprocess
import sys
import unittest
import uuid

from build_firmware import ROOT, audit_instructions, stack_bound


def node(name, size, kind="static"):
    return f'node: {{ title: "{name}" label: "{name}\\n{size} bytes ({kind})" }}'


def edge(a, b):
    return f'edge: {{ sourcename: "{a}" targetname: "{b}" }}'


class FirmwareAuditTest(unittest.TestCase):
    def test_real_wait_helper_preserves_events_arriving_during_processing(self):
        # Execute the actual header against mapped MMIO storage. FabricSpec
        # separately verifies W1C/set arbitration; here we inspect which bits
        # software writes, including an event arriving before the next WAIT.
        output = ROOT / "build/firmware-controls" / uuid.uuid4().hex
        output.mkdir(parents=True)
        source = output / "events.c"
        source.write_text(r'''
#define _GNU_SOURCE
#include <assert.h>
#include <sys/mman.h>
#include "riscay.h"
int main(void) {
    void *base=mmap((void *)0x30000000u,4096,PROT_READ|PROT_WRITE,
        MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    assert(base==(void *)0x30000000u);
    MMIO(4)=123; MMIO(12)=0; MMIO(16)=2;
    uint32_t events=wait_events(500);
    assert(events==2 && MMIO(12)==0 && MMIO(8)==623);
    assert(MMIO(60)==2000 && MMIO(32)==0x57444f47u);
    acknowledge_events(events);
    assert(MMIO(12)==2); /* only the consumed deadline was acknowledged */
    MMIO(12)=0; /* record of later clear writes starts empty */
    MMIO(16)=4; /* GPIO arrived while handling the previous deadline */
    events=wait_events(500);
    assert(events==4 && MMIO(12)==0); /* next wait did not discard it */
    acknowledge_events(events); assert(MMIO(12)==4);
    return munmap(base,4096);
}
''')
        prefix = ["wsl", "-d", "Ubuntu", "--exec"] if os.name == "nt" else []
        def path(value):
            return subprocess.check_output([*prefix, "wslpath", "-u", str(value)], text=True).strip() if prefix else str(value)
        binary = path(output / "events")
        subprocess.run([*prefix, "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-I", path(ROOT / "firmware/include"), path(source), "-o", binary], check=True, timeout=60)
        subprocess.run([*prefix, binary], check=True, timeout=10)

    def test_call_chain_sums_frames_and_takes_largest_branch(self):
        graph = "\n".join([node("main", 12), node("batch", 32), node("transform", 44),
                           node("leaf", 0), node("other", 4), edge("main", "batch"),
                           edge("batch", "transform"), edge("transform", "leaf"), edge("main", "other")])
        bound, path, _ = stack_bound([graph])
        self.assertEqual(bound, 88)
        self.assertEqual(path, ["main", "batch", "transform", "leaf"])

    def test_recursion_missing_frames_and_dynamic_stack_are_rejected(self):
        for graph in [node("main", 4) + edge("main", "main"),
                      node("main", 4) + edge("main", "unknown"),
                      node("main", 4, "dynamic"), ""]:
            with self.subTest(graph=graph), self.assertRaises(ValueError):
                stack_bound([graph])

    def test_isa_audit_rejects_compressed_m_extension_upper_registers_and_empty_input(self):
        self.assertEqual(audit_instructions("10000000: 00028113 addi x2,x5,0"), 1)
        for line in ["10000000: 0001 c.nop", "10000000: 02b50533 mul x10,x10,x11",
                     "10000000: 00100813 addi x16,x0,1", ""]:
            with self.subTest(line=line), self.assertRaises(ValueError):
                audit_instructions(line)

    def test_real_linker_rejects_undersized_program_and_ram(self):
        for option, size, error in [("--program-bytes", "1024", "PROGRAM_BUDGET_EXCEEDED"),
                                    ("--ram-bytes", "128", "RAM_STACK_BUDGET_EXCEEDED")]:
            output = f"build/firmware-controls/{uuid.uuid4().hex}"
            result = subprocess.run([sys.executable, str(ROOT / "tools/build_firmware.py"),
                                     "--app", "runtime_stress", option, size, "--output", output],
                                    cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(error, result.stdout + result.stderr)
            self.assertFalse((ROOT / output / "runtime_stress/report.json").exists())


if __name__ == "__main__":
    unittest.main()
