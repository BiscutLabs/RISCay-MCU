# SPDX-License-Identifier: Apache-2.0
"""Independent negative controls for code, stack and linker budget checks."""
from pathlib import Path
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
