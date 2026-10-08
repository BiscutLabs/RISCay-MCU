# SPDX-License-Identifier: Apache-2.0
import hashlib
import json
import unittest
import tempfile
import copy
from pathlib import Path

from sram_assets import ROOT, verify
from check_export import sram_scopes, sram_array_shapes


class SramAssetsTest(unittest.TestCase):
    def test_vendored_models_match_pinned_upstream_bytes(self):
        lock = json.loads((ROOT / "soc/sram-lock.json").read_text())
        for suffix in (".v", ".blackbox.v"):
            name = lock["macro"] + suffix
            verify((ROOT / "soc/src/main/resources/riscay/sram" / name).read_bytes(),
                   lock["assets"][name]["sha256"])

    def test_corrupt_physical_view_is_rejected(self):
        digest = hashlib.sha256(b"physical view").hexdigest()
        verify(b"physical view", digest)
        with self.assertRaisesRegex(ValueError, "SRAM_ASSET_HASH_MISMATCH"):
            verify(b"changed physical view", digest)

    def test_icarus_descending_array_shape_is_read_only_inside_the_sram_scope(self):
        model = "gf180mcu_ocd_ip_sram__sram1024x8m8wm1"
        scope = {"Top.fabric_ram_macros_0": dict(model=model, memories={})}
        text = (f'S_1 .scope module, "fabric_ram_macros_0" "{model}" 1 1;\n'
                'v1 .array "mem", 0 1023, 7 0;\n'
                'S_2 .scope module, "unknown" "Other" 1 1;\n'
                'v2 .array "mem", 0 7, 2 0;\n')
        result = sram_array_shapes(text, scope)
        self.assertEqual(result["Top.fabric_ram_macros_0"]["memories"], {"mem": (1024,8)})

    def test_export_inventory_rejects_missing_extra_wrong_shape_or_changed_macros(self):
        lock = json.loads((ROOT / "soc/sram-lock.json").read_text())
        model = lock["macro"]
        source = ROOT / "soc/src/main/resources/riscay/sram"
        body = ("`ifdef SYNTHESIS\n" + (source / (model + ".blackbox.v")).read_text() +
                "\n`else\n" + (source / (model + ".v")).read_text().replace("mem[i] = 8'd0;", "mem[i] = 8'bx;") +
                "\n`endif\n")
        instances = [dict(path=f"Top.fabric_{bank}_macros_{i}", bank=bank, index=i)
                     for bank, count in (("program", 2), ("ram", 1)) for i in range(count)]
        inventory = dict(schema="riscay-gf180-sram-v1", macro=model, program_bytes=2048,
                         working_ram_bytes=1024, instances=instances)
        pins = {name: dict(name=name, direction="output" if name == "Q" else "input", width=width)
                for name, width in (("CLK",1), ("CEN",1), ("GWEN",1), ("WEN",8), ("A",10), ("D",8), ("Q",8))}
        scopes = {x["path"]: dict(model=model, ports=pins, memories={"mem": (1024,8)}) for x in instances}
        node = dict(rtl_path="Top")
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            with self.assertRaisesRegex(ValueError, "MISSING_SRAM_INVENTORY"):
                sram_scopes(directory, node, scopes)
            (directory / "sram.json").write_text(json.dumps(inventory))
            rtl = directory / (model + ".sv")
            rtl.write_text("// Generated header\n" + body)
            self.assertEqual(sram_scopes(directory, node, scopes), set(scopes))
            broken = copy.deepcopy(scopes)
            del broken[instances[0]["path"]]
            with self.assertRaisesRegex(ValueError, "SRAM_INSTANCE_MISMATCH"):
                sram_scopes(directory, node, broken)
            broken = copy.deepcopy(scopes)
            broken[instances[0]["path"]]["memories"]["mem"] = (512,8)
            with self.assertRaisesRegex(ValueError, "SRAM_ELABORATED_SHAPE_MISMATCH"):
                sram_scopes(directory, node, broken)
            broken = copy.deepcopy(scopes)
            broken["Top.extra"] = copy.deepcopy(next(iter(scopes.values())))
            with self.assertRaisesRegex(ValueError, "SRAM_INSTANCE_MISMATCH"):
                sram_scopes(directory, node, broken)
            rtl.write_text("// Generated header\n" + body.replace("mem[i] = 8'bx;", "mem[i] = 8'd0;"))
            with self.assertRaisesRegex(ValueError, "SRAM_EMITTED_VIEW_MISMATCH"):
                sram_scopes(directory, node, scopes)


if __name__ == "__main__":
    unittest.main()
