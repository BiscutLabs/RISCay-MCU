# SPDX-License-Identifier: Apache-2.0
import unittest
from check_spi_replay_controls import bind_sites, classify, message_pattern, execute, sha, tree_hashes
import re
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch


class ExactSites(unittest.TestCase):
    def test_formatted_scalar_site_is_bound_to_literal_line_scope(self):
        tb='module Testbench;\ntask retire; begin\nif (wrong) $fatal(1,"SPI_WIRE_RESULT word=%h value=%h valid=%b",word,value,valid);\nend endtask\nendmodule\n'
        sites=bind_sites(tb,[dict(format='SPI_WIRE_RESULT word=%h value=%h valid=%b',scope='Testbench.retire')])
        log='FATAL: testbench.sv:3: SPI_WIRE_RESULT word=f123 value=12345678 valid=1\n       Time: 100 Scope: Testbench.retire\n'
        compile=dict(exit_code=0,timed_out=False);sim=dict(exit_code=1,timed_out=False)
        self.assertEqual(classify(log,compile,sim,sites)[0]['time'],100)
        for changed in [log.replace(':3:',':4:'),log.replace('Testbench.retire','Testbench'),
                        log.replace('SPI_WIRE_RESULT','SPI_OTHER'),log+'SOC_DEADLINE\n',
                        'SPI_WIRE_RESULT word=f123 value=12345678 valid=1\n',
                        log.replace('testbench.sv','other.sv')]:
            with self.assertRaises(ValueError):classify(changed,compile,sim,sites)
        for changed_compile,changed_sim in [(dict(exit_code=1),sim),(compile,dict(exit_code=0)),
                                            (dict(exit_code=0,timed_out=True),sim),
                                            (compile,dict(exit_code=1,timed_out=True))]:
            with self.assertRaises(ValueError):classify(log,changed_compile,changed_sim,sites)

    def test_float_and_space_padded_decimal(self):
        pattern=message_pattern('SPI_FRAME_LENGTH edges=%d duration=%f')
        self.assertIsNotNone(re.fullmatch(pattern,'SPI_FRAME_LENGTH edges=         30 duration=3200.001000'))
        self.assertIsNone(re.fullmatch(pattern,'SPI_FRAME_LENGTH edges=30 duration=oops'))

    def test_site_drift_and_duplicates_rejected(self):
        declaration=dict(format='SPI_FAIL',scope='Testbench')
        for source in ['', '$fatal(1,"OTHER");', '$fatal(1,"SPI_FAIL");\n$fatal(1,"SPI_FAIL");']:
            with self.assertRaises(ValueError):bind_sites(source,[declaration])

    def fixture(self, root):
        root.mkdir()
        (root/'model.sv').write_text('module Model; endmodule\n')
        (root/'testbench.sv').write_text('module Testbench; endmodule\n')
        (root/'filelist.f').write_text('model.sv\n')
        (root/'contract.json').write_text(json.dumps(dict(manifest=dict(top='Model',design=dict(children=[],primitives=[])))))
        before=tree_hashes(root)
        return dict(name='synthetic-wire',export=str(root),mode='wire',
            export_tree_sha256=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),
            source_hashes={'model.sv':sha(root/'model.sv')},oracle_sha256=sha(root/'testbench.sv'),
            cases=[dict(label='unused-after-positive-failure')])

    def test_positive_marker_does_not_override_errors(self):
        for error in ('ERROR unrelated', 'TIMEOUT', 'DEADLINE', 'FATAL: unrelated'):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);group=self.fixture(root/'origin');out=root/'out';out.mkdir()
                def fake_run(command,cwd,label,timeout):
                    if label=='compile': (cwd/'control.vvp').write_text('compiled')
                    return dict(exit_code=0,timed_out=False), 'RISCAY_SOC_PASS\n'+error+'\n'
                with patch('check_spi_replay_controls.run',side_effect=fake_run):
                    with self.assertRaisesRegex(ValueError,'POSITIVE:positive'):execute(group,out)

    def test_source_oracle_and_binary_changes_rejected(self):
        for stage,file,diagnostic in (('compile','model.sv','INPUT_CHANGED_DURING_COMPILE'),
            ('compile','testbench.sv','INPUT_CHANGED_DURING_COMPILE'),
            ('simulation','model.sv','INPUT_CHANGED_DURING_EXECUTION'),
            ('simulation','testbench.sv','INPUT_CHANGED_DURING_EXECUTION'),
            ('simulation','control.vvp','BINARY_CHANGED_DURING_EXECUTION')):
            with self.subTest(stage=stage,file=file),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);group=self.fixture(root/'origin');out=root/'out';out.mkdir()
                def fake_run(command,cwd,label,timeout):
                    if label=='compile': (cwd/'control.vvp').write_text('compiled')
                    if label==stage:(cwd/file).write_text('changed during execution')
                    return dict(exit_code=0,timed_out=False), 'RISCAY_SOC_PASS\n'
                with patch('check_spi_replay_controls.run',side_effect=fake_run):
                    with self.assertRaisesRegex(ValueError,diagnostic):execute(group,out)


if __name__=='__main__':unittest.main()
