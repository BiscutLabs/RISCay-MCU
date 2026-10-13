# SPDX-License-Identifier: Apache-2.0
"""Reject stale, unsupported or falsely qualified physical export policies."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from gf180_physical import inventory, physical_policy, sha


class PhysicalExportPolicy(unittest.TestCase):
    def test_exact_contract_ports_variant_and_unqualified_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            for variant, top in (("bd", "FourPhaseSoc"), ("click", "ClickSoc")):
                (out / "contract.json").write_text(json.dumps(dict(manifest=dict(top=top))))
                (out / "ports.json").write_text(json.dumps(dict(top=top)))
                policy = dict(schema="riscay-physical-policy-v2", variant=variant, policy_enabled=True,
                    timing_policy="current-supported-digital", qualification="unqualified", verification_layers="inline",
                    timing_intent="contract.json", contract_sha256=sha(out / "contract.json"), ports_sha256=sha(out / "ports.json"))
                def check(value):
                    (out / "physical-policy.json").write_text(json.dumps(value))
                    return physical_policy(out, dict(top=top))
                self.assertEqual(check(policy), policy)
                mutations = [
                    ("schema", "riscay-physical-policy-v1", "PHYSICAL_POLICY_REEXPORT_REQUIRED"),
                    ("policy_enabled", False, "DISABLED_ESTIMATE_POLICY"),
                    ("policy_enabled", 1, "DISABLED_ESTIMATE_POLICY"),
                    ("timing_policy", "legacy-core-experiment", "UNSUPPORTED_PHYSICAL_EXPORT_POLICY"),
                    ("qualification", "qualified", "UNSUPPORTED_PHYSICAL_EXPORT_POLICY"),
                    ("verification_layers", "extracted", "UNSUPPORTED_PHYSICAL_EXPORT_POLICY"),
                    ("timing_intent", "other.json", "UNSUPPORTED_PHYSICAL_EXPORT_POLICY"),
                    ("variant", "bd" if variant == "click" else "click", "PHYSICAL_POLICY_TOP_MISMATCH"),
                    ("contract_sha256", "stale", "STALE_PHYSICAL_EXPORT_POLICY"),
                    ("ports_sha256", "stale", "STALE_PHYSICAL_EXPORT_POLICY"),
                ]
                for field, value, error in mutations:
                    with self.subTest(variant=variant, field=field):
                        mutant = copy.deepcopy(policy); mutant[field] = value
                        with self.assertRaisesRegex(ValueError, "^" + error + "$"): check(mutant)
                for field in policy:
                    with self.subTest(variant=variant, missing=field):
                        mutant = copy.deepcopy(policy); del mutant[field]
                        with self.assertRaises(ValueError): check(mutant)

    def test_assertion_layer_label_does_not_admit_unregistered_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            root = dict(module="FourPhaseSoc", rtl_path="FourPhaseSoc", children=[], primitives=[], timing=[])
            (out / "contract.json").write_text(json.dumps(dict(manifest=dict(top="FourPhaseSoc", design=root))))
            (out / "FourPhaseSoc.sv").write_text("module FourPhaseSoc(); endmodule\n")
            for source in ("verification/assert/FourPhaseSoc_Verification_Assert.sv", "unregistered.sv", "../FourPhaseSoc.sv"):
                (out / "filelist.f").write_text("FourPhaseSoc.sv\n" + source + "\n")
                with self.assertRaisesRegex(ValueError, "^UNREGISTERED_SOURCE$"): inventory(out)
            (out / "filelist.f").write_text("FourPhaseSoc.sv\n")
            self.assertEqual(inventory(out)[0]["top"], "FourPhaseSoc")


if __name__ == "__main__": unittest.main()
