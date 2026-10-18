# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import run_receipt as r


class RunReceiptTest(unittest.TestCase):
    def test_one_receipt_hashes_each_distinct_file_once(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); source=root/'source'; source.write_text('input')
            output=root/'output'; output.write_text('result')
            with patch.object(r.hashlib,'sha256',wraps=r.hashlib.sha256) as hashed:
                run=r.RunReceipt(root/'receipt.json',inputs=[source],tools=[source])
                report=run.finish(outputs=[source,output])
                self.assertEqual(hashed.call_count,len(report['sha256']))
            self.assertEqual(set(report['sha256']),{str(source.resolve()),str(output.resolve())})
            self.assertEqual(report['status'],'pass')
            with self.assertRaisesRegex(ValueError,'ALREADY_FINISHED'):run.finish()
            with self.assertRaisesRegex(ValueError,'EXISTS'):r.RunReceipt(root/'receipt.json')

    def test_changed_input_or_failed_command_retains_a_failed_receipt(self):
        for fault in ('input','command','missing-output'):
            with self.subTest(fault=fault),TemporaryDirectory() as folder:
                root=Path(folder); source=root/'source'; source.write_text('before')
                run=r.RunReceipt(root/'receipt.json',inputs=[source])
                if fault=='input':source.write_text('different content')
                if fault=='command':run.command([sys.executable,'-c','raise SystemExit(7)'],cwd=root,log=root/'command.log')
                with self.assertRaisesRegex(ValueError,'RUN_FAILED'):
                    run.finish(outputs=[root/'missing'] if fault=='missing-output' else [])
                report=json.loads((root/'receipt.json').read_text())
                self.assertEqual(report['status'],'fail')
                self.assertTrue(report['changed_inputs'] or report['missing_outputs'] or report['commands'][0]['returncode'])


if __name__=='__main__':unittest.main()
