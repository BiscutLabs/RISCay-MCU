# SPDX-License-Identifier: Apache-2.0
import tempfile
import unittest
from pathlib import Path
from check_recovery_controls import isolate_child


class RecoveryChildIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.case=Path(self.temp.name)
        self.parent='module Top();\n  Owner ca_child_telemetry_source (.reset(reset));\n  Owner ca_child_housekeeping_source (.reset(reset));\nendmodule\n'
        self.owner='module Owner(input reset);\n wire eligible = ~reset;\nendmodule\n'
        (self.case/'Top.sv').write_text(self.parent)
        (self.case/'Owner.sv').write_text(self.owner)
        (self.case/'filelist.f').write_text('Top.sv\nOwner.sv\n')

    def test_deduplicated_child_is_cloned_without_changing_other_owner(self):
        for child in ('telemetry_source','housekeeping_source'):
            with self.subTest(child=child):
                (self.case/'Top.sv').write_text(self.parent)
                (self.case/'filelist.f').write_text('Top.sv\nOwner.sv\n')
                clone,identity=isolate_child(self.case,{'top':'Top'},child)
                self.assertEqual((self.case/'Owner.sv').read_text(),self.owner)
                self.assertEqual(clone.read_text(),self.owner.replace('module Owner(',f'module {clone.stem}('))
                self.assertEqual((self.case/'Top.sv').read_text(),self.parent.replace('Owner ca_child_'+child,clone.stem+' ca_child_'+child))
                self.assertEqual(identity['emitted_module'],'Owner')
                self.assertEqual((self.case/'filelist.f').read_text(),'Top.sv\nOwner.sv\n'+clone.name+'\n')

    def test_missing_and_duplicate_instances_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'RECOVERY_CHILD_INSTANCE'):
            isolate_child(self.case,{'top':'Top'},'absent')
        (self.case/'Top.sv').write_text(self.parent.replace('housekeeping_source','telemetry_source'))
        with self.assertRaisesRegex(ValueError,'RECOVERY_CHILD_INSTANCE'):
            isolate_child(self.case,{'top':'Top'},'telemetry_source')

    def test_duplicate_module_definition_is_rejected(self):
        (self.case/'Duplicate.sv').write_text(self.owner)
        (self.case/'filelist.f').write_text('Top.sv\nOwner.sv\nDuplicate.sv\n')
        with self.assertRaisesRegex(ValueError,'RECOVERY_CHILD_DEFINITION'):
            isolate_child(self.case,{'top':'Top'},'housekeeping_source')


if __name__=='__main__':unittest.main()
