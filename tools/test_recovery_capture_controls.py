# SPDX-License-Identifier: Apache-2.0
import tempfile
import unittest
from pathlib import Path
from check_recovery_capture_controls import CAMPAIGNS,source_oracles
from check_publication_source_export import channel_layout


class RecoveryCaptureInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.sources={}
        for name in CAMPAIGNS:
            source=Path(self.temp.name)/name;(source/'export').mkdir(parents=True)
            (source/'export/contract.json').write_text('{}');self.sources[name]=str(source)
            cases=['seed-'+str(i) for i in range(1,25)]
            if name!='required':cases+=['selected-skew-'+x for x in ('selector','clear','reset')]
            for case in cases:
                (source/case).mkdir();(source/case/'testbench.sv').write_text('// inventory')

    def test_complete_inventory_requires_every_seed_and_skew(self):
        _,oracles=source_oracles(self.sources);self.assertEqual(sum(map(len,oracles.values())),105)

    def test_missing_recovery_source_is_rejected(self):
        self.sources['roles']=str(Path(self.temp.name)/'absent')
        with self.assertRaisesRegex(ValueError,'RECOVERY_CAPTURE_MISSING_SOURCE:roles'):source_oracles(self.sources)

    def test_missing_random_seed_is_rejected(self):
        (Path(self.sources['required'])/'seed-24/testbench.sv').unlink()
        with self.assertRaisesRegex(ValueError,'RECOVERY_CAPTURE_ORACLE_INVENTORY:required'):source_oracles(self.sources)

    def test_each_directed_skew_is_mandatory(self):
        for skew in ('selector','clear','reset'):
            p=Path(self.sources['capture_reset'])/('selected-skew-'+skew)/'testbench.sv';p.unlink()
            with self.assertRaisesRegex(ValueError,'RECOVERY_CAPTURE_ORACLE_INVENTORY:capture_reset'):source_oracles(self.sources)
            p.write_text('// restored inventory')

    def test_unrecognized_replay_is_rejected(self):
        p=Path(self.sources['fast'])/'selected-skew-extra';p.mkdir();(p/'testbench.sv').write_text('// extra')
        with self.assertRaisesRegex(ValueError,'RECOVERY_CAPTURE_ORACLE_INVENTORY:fast'):source_oracles(self.sources)

    def test_identity_layout_preserves_both_fields_and_offsets(self):
        self.assertEqual(channel_layout('Owner','reserve',True),[
            dict(field='bits.tag',lsb=0,width=1,signed=False,source='~|Owner>reserve.bits.tag'),
            dict(field='bits.recovery',lsb=1,width=1,signed=False,source='~|Owner>reserve.bits.recovery')])
        self.assertEqual(channel_layout('Owner','decision',False),[
            dict(field='bits',lsb=0,width=1,signed=False,source='~|Owner>decision.bits')])


if __name__=='__main__':unittest.main()
