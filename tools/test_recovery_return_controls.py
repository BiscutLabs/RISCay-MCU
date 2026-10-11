# SPDX-License-Identifier: Apache-2.0
import copy,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from check_capture_pins import capture_monitors
from check_export import validate_native_click
from check_recovery_return_export import validate_recovery_return,validate_return_receipt,validate_return_receipts
from check_recovery_return_capture_controls import CAMPAIGNS,source_oracles


class RecoveryReturnPolicyTests(unittest.TestCase):
    def test_unknown_owners_are_rejected(self):
        for model in ('ClockedReturn','FourPhaseRecoveryReturnAdapter','ClickRecoveryReturnRTZ'):
            with self.assertRaisesRegex(ValueError,'RECOVERY_RETURN_OWNER'):validate_recovery_return(dict(module=model))
        with self.assertRaisesRegex(ValueError,'RETURN_RECEIPT_OWNER'):validate_return_receipt(dict(module='GenericReceipt'))

    def test_click_proof_cannot_hide_four_phase(self):
        node=dict(module='ClickPublicationSource',channels=[],primitives=[],children=[dict(id='recovery_return',
            contract=dict(module='ClickRecoveryReturn',channels=[],primitives=[],children=[]))])
        validate_native_click(dict(top='ClickPublicationSource',design=node))
        for hidden in (dict(module='FourPhaseStage',channels=[],primitives=[],children=[]),
            dict(module='Other',channels=[dict(protocol='four-phase-bundled-v1')],primitives=[],children=[])):
            bad=copy.deepcopy(node);bad['children'][0]['contract']['children'].append(dict(id='hidden',contract=hidden))
            with self.assertRaisesRegex(ValueError,'MCU_CLICK_HAS_RTZ_IMPLEMENTATION'):
                validate_native_click(dict(top='ClickPublicationSource',design=bad))

    def test_control_receipt_requires_exact_endpoint_inventory(self):
        ids=('reset','local_reset','clock','request','request_meta','request_sync','ack_state','acknowledge','quiet')
        for model in ('FourPhaseReturnReceipt','ClickReturnReceipt'):
            node=dict(module=model,capacity=1,channels=[],primitives=[],children=[],timing=[],endpoints=[dict(id=n,width=1) for n in ids])
            validate_return_receipt(node)
            for i in range(len(ids)):
                bad=copy.deepcopy(node);bad['endpoints'].pop(i)
                with self.assertRaisesRegex(ValueError,'RETURN_RECEIPT_INVENTORY'):validate_return_receipt(bad)
            bad=copy.deepcopy(node);bad['channels'].append(dict(id='fake_payload'))
            with self.assertRaisesRegex(ValueError,'RETURN_RECEIPT_INVENTORY'):validate_return_receipt(bad)

    def test_capture_reference_is_independent_across_hierarchy(self):
        node=dict(primitives=[dict(id='debt',rtl_path='Top.parent.debt')])
        monitor=capture_monitors(node,{'debt':None},'TEST',{'debt':'Top.parent.child.clear.q'})
        self.assertIn('always @(posedge dut.parent.child.clear.q) pc_debt_fire=$time;',monitor)
        self.assertIn('always @(posedge dut.parent.debt.trigger or posedge dut.parent.debt.reset)',monitor)
        self.assertNotIn('always @(posedge dut.parent.debt.trigger) pc_debt_fire',monitor)

    def test_receipt_inspects_actual_deduplicated_model_and_rejects_wrong_protocol(self):
        ids=('reset','local_reset','clock','request','request_meta','request_sync','ack_state','acknowledge','quiet')
        for prefix,wrong in (('FourPhase','Click'),('Click','FourPhase')):
            node=dict(module=prefix+'ReturnReceipt_1',rtl_path='Top.receipt',capacity=1,
                channels=[],primitives=[],children=[],timing=[],endpoints=[dict(id=n,width=1) for n in ids])
            manifest=dict(design=node)
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder);(path/(prefix+'ReturnReceipt.sv')).write_text('resolved RTL',encoding='utf-8')
                with patch('check_recovery_return_export.validate_return_receipt_rtl') as check:
                    validate_return_receipts(manifest,path,{'Top.receipt':dict(model=prefix+'ReturnReceipt')})
                    check.assert_called_once_with(node,'resolved RTL')
                for model in (wrong+'ReturnReceipt','CombinationalAlias',''):
                    with self.assertRaisesRegex(ValueError,'RETURN_RECEIPT_RESOLVED_OWNER'):
                        validate_return_receipts(manifest,path,{'Top.receipt':dict(model=model)})

    def test_capture_source_requires_every_seed_in_each_reset_history(self):
        with tempfile.TemporaryDirectory() as folder:
            sources={}
            for campaign in CAMPAIGNS:
                p=Path(folder)/campaign;(p/'export').mkdir(parents=True);(p/'export/contract.json').write_text('{}')
                sources[campaign]=str(p)
                for i in range(1,25):
                    d=p/('seed-'+str(i));d.mkdir();(d/'testbench.sv').write_text('// oracle')
            _,oracles=source_oracles(sources);self.assertEqual(sum(map(len,oracles.values())),72)
            for campaign in CAMPAIGNS:
                p=Path(sources[campaign])/'seed-24/testbench.sv';p.unlink()
                with self.assertRaisesRegex(ValueError,'RETURN_CAPTURE_ORACLE_INVENTORY:'+campaign):source_oracles(sources)
                p.write_text('// oracle')


if __name__=='__main__':unittest.main()
