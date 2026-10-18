# SPDX-License-Identifier: Apache-2.0
"""The MCU consumes the library's audit without rewriting generated probes."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from export_structure import digest, validate


def fixture(root):
    files={'design.hw.mlir': 'module {}\n', 'Top.sv': 'module Top; endmodule\n',
           'ports.json': '{}\n', 'filelist.f': 'Top.sv\n'}
    for name, content in files.items():
        (root/name).write_text(content, encoding='utf-8', newline='\n')
    node=dict(rtl_path='Top', primitives=[dict(rtl_path='Top.payload')], children=[])
    manifest=dict(top='Top', design=node,
                  rtl_semantic_sha256={'Top.sv':digest(files['Top.sv'].encode())},
                  port_abi=dict(file='ports.json',sha256=digest(files['ports.json'].encode())))
    semantic=digest(json.dumps(manifest,separators=(',',':')).encode())
    (root/'contract.json').write_text(json.dumps(dict(manifest=manifest,semantic_sha256=semantic)))
    report=dict(schema='chisel-async-structure-v1',status='pass',top='Top',
                contract_semantic_sha256=semantic,hw_sha256=digest(files['design.hw.mlir'].encode()),
                primitive_paths=['Top.payload'],owner_modules={'Top':'Top'})
    (root/'structure.json').write_text(json.dumps(report))
    return report


class ExportStructureTest(unittest.TestCase):
    def test_audit_inventory_matches_contract_and_does_not_claim_physical_checks(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); report=fixture(root)
            result=validate(root)
            self.assertEqual(set(result['primitive_paths']),set(report['primitive_paths']))
            self.assertTrue(result['physical_checks'].startswith('pending mapping:'))
            report['primitive_paths']=[]
            (root/'structure.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'PRIMITIVE_INVENTORY'):validate(root)

    def test_compiler_and_rtl_inputs_cannot_drift(self):
        for filename, diagnostic in [('design.hw.mlir','HW_CHANGED'),('Top.sv','RTL_CHANGED'),
                                     ('ports.json','PORT_ABI_CHANGED')]:
            with self.subTest(filename=filename), TemporaryDirectory() as tmp:
                root=Path(tmp);fixture(root)
                with (root/filename).open('a') as stream:stream.write('changed')
                with self.assertRaisesRegex(ValueError,diagnostic):validate(root)

    def test_file_inventory_cannot_escape_export_or_omit_generated_rtl(self):
        for content, diagnostic in [('../Top.sv\n','FILE_OUTSIDE_EXPORT'),('', 'RTL_INVENTORY')]:
            with self.subTest(content=content), TemporaryDirectory() as tmp:
                root=Path(tmp);fixture(root);(root/'filelist.f').write_text(content)
                with self.assertRaisesRegex(ValueError,diagnostic):validate(root)


if __name__=='__main__':unittest.main()
