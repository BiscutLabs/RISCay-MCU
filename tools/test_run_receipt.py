# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path
import sys
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock
import run_receipt as r


class RunReceiptTest(unittest.TestCase):
    def test_wall_timeout_is_a_retained_failure(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);run=r.RunReceipt(root/'receipt.json')
            worker="from pathlib import Path;import time;Path('started').touch();time.sleep(2);Path('leaked').touch()"
            driver="import subprocess,sys;subprocess.Popen([sys.executable,'-c',sys.argv[1]]).wait()"
            self.assertEqual(run.command([sys.executable,'-c',driver,worker],
                cwd=root,log=root/'timeout.log',timeout=1),124)
            self.assertTrue((root/'started').exists(),'worker must actually run before the timeout')
            time.sleep(2.2) # Full worker delay after return, even if startup was late.
            self.assertFalse((root/'leaked').exists(),'timeout must stop descendants as well as the driver')
            with self.assertRaisesRegex(ValueError,'RUN_FAILED'):run.finish(outputs=[root/'timeout.log'])
            self.assertIn('RUN_WALL_TIMEOUT',(root/'timeout.log').read_text())

    def test_cancellation_cleans_owned_tree_and_preserves_interrupt(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);child=Mock(pid=123,poll=Mock(return_value=None))
            child.wait.side_effect=[KeyboardInterrupt(),0]
            with patch.object(r.subprocess,'Popen',return_value=child), \
                 patch.object(r.subprocess,'run',return_value=Mock(returncode=0)) as kill_tree, \
                 patch.object(r.os,'killpg',create=True) as kill_group:
                with self.assertRaises(KeyboardInterrupt):
                    r.RunReceipt(root/'receipt.json').command(['unused'],cwd=root,log=root/'cancel.log')
                if r.os.name=='nt':self.assertIn('123',kill_tree.call_args.args[0])
                else:kill_group.assert_called_once_with(123,r.signal.SIGKILL)
                child.kill.assert_called_once();self.assertEqual(child.wait.call_count,2)

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
