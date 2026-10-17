# SPDX-License-Identifier: Apache-2.0
"""Reject constraint loss when OpenDB removes hierarchical interface pins."""
import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import gf180_pnr as pnr
import report_gf180_pnr as report
import check_gf180_routed as probe
from gf180_pnr import bind_flat_interfaces, SC

def design():
    return {
        "RiscayMcuDigital":{"ports":{},"cells":{
            "producer":{"type":"Producer","connections":{"a":[20],"b":[21]}},
            "consumer":{"type":"Consumer","connections":{"in_bits_pc":[20]}}}},
        "Producer":{"ports":{"a":{"bits":[1]},"b":{"bits":[1]},"unused":{"bits":[9]}},
                    "cells":{"gate":{"type":SC+"buf_1","connections":{"I":["0"],"Z":[1]},
                                     "port_directions":{"I":"input","Z":"output"}}}},
        "Consumer":{"ports":{"in_bits_pc":{"bits":[2]}},"cells":{}}}

class PnrBindings(unittest.TestCase):
    def test_runtime_binds_wrapped_executable_independently_of_launcher(self):
        from types import SimpleNamespace
        with TemporaryDirectory() as directory:
            root=Path(directory);exe=root/'openroad';wrapped=root/'.openroad-wrapped'
            exe.write_text('unchanged launcher');wrapped.write_text('first resizer')
            selected=SimpleNamespace(input_files=lambda:[exe],host_path=lambda:exe)
            with patch.object(pnr,'pnr_tool',return_value=selected):
                before=pnr.runtime_hashes({})
                wrapped.write_text('changed resizer')
                self.assertNotEqual(pnr.runtime_hashes({}),before)
                wrapped.unlink()
                self.assertNotEqual(pnr.runtime_hashes({}),before)
            self.assertEqual(exe.read_text(),'unchanged launcher')

    def test_electrical_context_retains_every_async_obligation_separately(self):
        cap='set_max_capacitance 0.05 [rp {native/Z}]'
        timing=['set_max_delay 10 -from [all_registers -clock_pins] -to [rp {native/D}]',
                'set_min_delay 1 -from [rp {a/Q}] -to [rp {native/D}]',
                'set_data_check -rise_from [rp {a/Q}] -fall_to [rp {b/E}] -setup 0.5']
        text=pnr.PRELUDE+'\n'+cap+'\n'+'\n'.join(timing)+'\n'
        electrical,record=pnr.electrical_context(text)
        self.assertEqual(electrical,pnr.PRELUDE+cap+'\n')
        self.assertEqual(record['electrical_commands'],[cap])
        self.assertEqual(record['deferred_timing_commands'],timing)
        self.assertFalse(record['async_timing_coverage'])
        self.assertFalse(record['physical_qualification'])
        for bad in ('changed prelude',pnr.PRELUDE+cap+'\n',text+'set_false_path -from [all_registers]\n'):
            with self.assertRaisesRegex(ValueError,'PNR_'):pnr.electrical_context(bad)

    def test_common_outline_rejects_nonfinite_or_too_small(self):
        for side in (0,1400,float('inf'),float('nan')):
            with self.assertRaisesRegex(ValueError,'INVALID_COMMON_OUTLINE'):pnr.geometry(side)
        self.assertEqual(pnr.geometry(3250)['core_um'],[30,30,3220,3220])
    def test_aliased_ports_resolve_to_real_leaf_driver(self):
        # Two output aliases with different parent bit IDs must be unioned,
        # including the alias visited last, rather than overwriting the first.
        self.assertEqual(bind_flat_interfaces(design(),'[rbus {consumer/in_bits_pc} 1]'),
                         '[concat [rp {producer/gate/Z}]]')

    def test_unconnected_unused_output_is_allowed(self):
        d=design(); d['RiscayMcuDigital']['cells']['producer']['connections']['unused']=[]
        self.assertIn('producer/gate/Z',bind_flat_interfaces(d,'[rbus {consumer/in_bits_pc} 1]'))

    def test_missing_driver_is_not_silently_dropped(self):
        d=design(); d['Producer']['cells']={}
        with self.assertRaisesRegex(ValueError,'UNDRIVEN_BOUNDARY'):
            bind_flat_interfaces(d,'[rbus {consumer/in_bits_pc} 1]')

    def test_width_and_missing_interface_fail(self):
        with self.assertRaisesRegex(ValueError,'BOUNDARY_WIDTH_CHANGED'):
            bind_flat_interfaces(design(),'[rbus {consumer/in_bits_pc} 32]')
        with self.assertRaises(KeyError): bind_flat_interfaces(design(),'[rbus {missing} 1]')

    def test_completely_constant_boundary_is_not_timing_coverage(self):
        d=design(); d['Producer']['ports']['a']['bits']=['0']; d['Producer']['ports']['b']['bits']=['0']
        with self.assertRaisesRegex(ValueError,'EMPTY_BOUNDARY'):
            bind_flat_interfaces(d,'[rbus {consumer/in_bits_pc} 1]')

    def test_conflicting_constant_aliases_fail(self):
        d=design()
        d['RiscayMcuDigital']['cells']['producer']['connections'].update(a=['0'],b=['1'])
        with self.assertRaisesRegex(ValueError,'CONFLICTING_BOUNDARY_CONSTANTS'):
            bind_flat_interfaces(d,'[rbus {consumer/in_bits_pc} 1]')

class PnrProvenance(unittest.TestCase):
    def setUp(self):
        # These fixtures exercise P&R checkpoint custody without a physical
        # mapper. Receipt contents have separate adversarial unit controls.
        receipt=patch('repair_gf180_design.validate_receipt',return_value={})
        self.receipt=receipt.start();self.addCleanup(receipt.stop)
        audit=patch.object(pnr,'repair_audit_hashes',return_value={'reviewed.py':'fixed-fixture-hash'})
        self.audit=audit.start();self.addCleanup(audit.stop)
        physical=patch.object(pnr,'physical_input_hashes',return_value={'all-pinned-corners':'fixed'})
        self.physical=physical.start();self.addCleanup(physical.stop)
        runtime=patch.object(pnr,'runtime_hashes',return_value={'pinned-openroad':'fixed'})
        self.runtime=runtime.start();self.addCleanup(runtime.stop)
        self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.mapping=self.root/'mapping'; self.out=self.root/'routed'
        self.mapping.mkdir(); self.out.mkdir()
        self.flow=self.root/'physical/gf180'; self.flow.mkdir(parents=True)
        for name in pnr.MAPPING_INPUTS:
            p=self.mapping/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(name)
        for name in pnr.FLOW_INPUTS: (self.flow/name).write_text(name)
        (self.flow/'routing-lock.json').write_text('{}')
        for name in (*pnr.GENERATED_INPUTS,'protected-baseline.tcl',*[s+'.odb' for s in pnr.STAGES],'routed.spef'):
            (self.out/name).write_text(name)
        self.snapshot,self.hashes=pnr.snapshot_flow(self.out,[self.flow/n for n in pnr.FLOW_INPUTS])
        self.meta=dict(provenance_schema=pnr.PROVENANCE_SCHEMA,
            repair_audit_sources_sha256=pnr.repair_audit_hashes(),
            physical_inputs_sha256=pnr.physical_input_hashes(),
            openroad_runtime_sha256=pnr.runtime_hashes({}),
            source_commit='original-checkout-commit',status='checkpoint-unqualified',
            mapping_inputs_sha256=pnr.mapping_hashes(self.mapping),flow_sources=self.hashes,
            generated_inputs_sha256={n:pnr.sha(self.out/n) for n in pnr.GENERATED_INPUTS},
            mapping_directory=str(self.mapping),output_directory=str(self.out),
            openroad='/fixture/openroad',threads=8,routing_lock_sha256=pnr.sha(self.flow/'routing-lock.json'),
            checkpoints={stage:dict(odb_sha256=pnr.sha(self.out/(stage+'.odb')),
                                   protected_baseline_sha256=pnr.sha(self.out/'protected-baseline.tcl'))
                         for stage in pnr.STAGES})
        for stage,cp in self.meta['checkpoints'].items():
            for name in pnr.electrical_report_names(stage):(self.out/name).write_text(name)
            cp['electrical_reports_sha256']={n:pnr.sha(self.out/n) for n in pnr.electrical_report_names(stage)}
            if stage in ('place','global'):
                for side in ('before','after'):(self.out/(stage+'-repair-'+side+'.tsv')).write_text(side)
                (self.out/(stage+'-repair-proof.json')).write_text('proved')
                (self.out/(stage+'-native-protected-nets.txt')).write_text('protected')
                cp['repair']=dict(proof_sha256=pnr.sha(self.out/(stage+'-repair-proof.json')),
                    protected_nets_sha256=pnr.sha(self.out/(stage+'-native-protected-nets.txt')),
                    inputs_sha256={str((self.out/(stage+'-repair-'+side+'.tsv')).resolve()):pnr.sha(self.out/(stage+'-repair-'+side+'.tsv')) for side in ('before','after')})
        self.meta['checkpoints']['extract']['spef_sha256']=pnr.sha(self.out/'routed.spef')
        self.save()

    def save(self): (self.out/'run.json').write_text(json.dumps(self.meta))

    def test_changed_or_missing_runtime_is_rejected_before_checkpoint_use(self):
        for value in ({'pinned-openroad':'changed'},None):
            self.meta['openroad_runtime_sha256']=value;self.save()
            with self.assertRaisesRegex(ValueError,'PNR_RUNTIME_CHANGED'):
                pnr.validate_provenance(self.mapping,self.out,'extract')

    def test_exact_inputs_and_checkpoint_are_accepted_read_only(self):
        before={p:p.read_bytes() for p in self.out.rglob('*') if p.is_file()}
        self.assertEqual(pnr.validate_provenance(self.mapping,self.out,'extract'),self.meta)
        self.assertTrue(all(p.read_bytes()==b for p,b in before.items()))

    def test_all_rc_views_are_required_and_bound(self):
        with self.assertRaisesRegex(ValueError,'PNR_RC_CORNERS_MISSING'):
            pnr.rc_inputs(self.mapping,self.out,'min')
        self.meta['wire_corners']=list(pnr.RC_CORNERS)
        receipt={}
        for rc in pnr.RC_CORNERS:
            odb=self.out/('extract'+('' if rc=='nom' else '-'+rc)+'.odb')
            spef=self.out/('routed-'+rc+'.spef')
            if not odb.exists():odb.write_text(rc+' database')
            spef.write_text(rc+' parasitics')
            receipt[rc]=dict(odb_sha256=pnr.sha(odb),spef_sha256=pnr.sha(spef))
        self.meta['checkpoints']['extract']['rc_corners']=receipt;self.save()
        self.assertEqual(pnr.rc_inputs(self.mapping,self.out,'max')[1].name,'routed-max.spef')
        (self.out/'routed-min.spef').write_text('nominal substituted for min')
        with self.assertRaisesRegex(ValueError,'PNR_RC_INPUT_CHANGED_min'):
            pnr.rc_inputs(self.mapping,self.out,'nom')

    def test_every_mapping_input_change_is_rejected(self):
        for name in pnr.MAPPING_INPUTS:
            with self.subTest(name=name):
                p=self.mapping/name; old=p.read_bytes(); p.write_bytes(old+b' changed')
                with self.assertRaisesRegex(ValueError,'PNR_MAPPING_INPUT_CHANGED'):
                    pnr.validate_provenance(self.mapping,self.out,'extract')
                p.write_bytes(old)

    def test_database_spef_generated_inputs_and_protection_are_bound(self):
        for name,diagnostic in [('extract.odb','CHECKPOINT'),('routed.spef','SPEF'),
                               ('protected-baseline.tcl','PROTECTED_BASELINE')]+[(n,'GENERATED_INPUT') for n in pnr.GENERATED_INPUTS]:
            with self.subTest(name=name):
                p=self.out/name; old=p.read_bytes(); p.write_bytes(old+b' changed')
                with self.assertRaisesRegex(ValueError,'PNR_'+diagnostic+'_CHANGED'):
                    pnr.validate_provenance(self.mapping,self.out,'extract')
                p.write_bytes(old)

    def test_legacy_record_requires_a_fresh_run_without_rewriting_it(self):
        self.meta.pop('provenance_schema'); self.save(); before=(self.out/'run.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'PNR_FRESH_RUN_REQUIRED'):
            pnr.validate_provenance(self.mapping,self.out,'extract')
        self.assertEqual((self.out/'run.json').read_bytes(),before)

    def test_pre_repair_schema_requires_a_fresh_run(self):
        self.meta['provenance_schema']='riscay-pnr-inputs-v1'; self.save()
        before=(self.out/'run.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'PNR_FRESH_RUN_REQUIRED'):
            pnr.validate_provenance(self.mapping,self.out,'extract')
        self.assertEqual((self.out/'run.json').read_bytes(),before)

    def test_checkpoint_requires_the_exact_repair_receipt_hash(self):
        receipt='electrical-repair/receipt.json'
        self.assertIn(receipt,self.meta['mapping_inputs_sha256'])
        self.meta['mapping_inputs_sha256'].pop(receipt); self.save()
        with self.assertRaisesRegex(ValueError,'PNR_MAPPING_INPUT_CHANGED'):
            pnr.validate_provenance(self.mapping,self.out,'extract')

    def test_repair_validation_failure_stops_every_read_entry_point(self):
        before={p:p.read_bytes() for p in self.out.rglob('*') if p.is_file()}
        for diagnostic in ('REPAIR_RECEIPT_REQUIRED','REPAIR_EVIDENCE_CHANGED','REPAIR_AUDIT_CHANGED'):
            with self.subTest(diagnostic=diagnostic):
                self.receipt.side_effect=ValueError(diagnostic)
                with patch.object(pnr.subprocess,'run') as launch:
                    for call in (lambda:pnr.validate_provenance(self.mapping,self.out,'extract'),
                                 lambda:pnr.rc_inputs(self.mapping,self.out,'min'),
                                 lambda:report.run(self.mapping,self.out),
                                 lambda:report.corner_report(self.mapping,self.out,'tt'),
                                 lambda:probe.run(self.mapping,self.out,'tt')):
                        with self.assertRaisesRegex(ValueError,diagnostic): call()
                    launch.assert_not_called()
        self.assertTrue(all(p.read_bytes()==b for p,b in before.items()))
        self.assertEqual(set(before),{p for p in self.out.rglob('*') if p.is_file()})

    def test_replaced_valid_receipt_cannot_relabel_a_checkpoint(self):
        # The replacement may validate independently, but the old routed graph
        # still belongs to the original receipt, including its source custody.
        (self.mapping/'electrical-repair/receipt.json').write_text('new accepted receipt')
        with patch.object(pnr.subprocess,'run') as launch:
            for call in (lambda:pnr.rc_inputs(self.mapping,self.out,'min'),
                         lambda:report.run(self.mapping,self.out),
                         lambda:report.corner_report(self.mapping,self.out,'tt'),
                         lambda:probe.run(self.mapping,self.out,'tt')):
                with self.assertRaisesRegex(ValueError,'PNR_MAPPING_INPUT_CHANGED'): call()
            launch.assert_not_called()

    def test_each_flow_source_gets_a_distinct_immutable_snapshot(self):
        for name in pnr.FLOW_INPUTS:
            with self.subTest(name=name):
                p=self.flow/name; old=p.read_bytes(); p.write_bytes(old+b' changed')
                new,_=pnr.snapshot_flow(self.out,[self.flow/n for n in pnr.FLOW_INPUTS])
                self.assertNotEqual(new,self.snapshot)
                self.assertEqual((self.snapshot/name).read_bytes(),old)
                with self.assertRaisesRegex(ValueError,'PNR_FLOW_INPUT_CHANGED'):
                    pnr.validate_provenance(self.mapping,self.out,'extract',{n:pnr.sha(self.flow/n) for n in pnr.FLOW_INPUTS})
                p.write_bytes(old)

    def test_snapshot_tampering_is_rejected_not_overwritten(self):
        p=self.snapshot/'power.tcl'; p.write_text('changed')
        with self.assertRaisesRegex(ValueError,'PNR_FLOW_SNAPSHOT_CHANGED'):
            pnr.snapshot_flow(self.out,[self.flow/n for n in pnr.FLOW_INPUTS])
        with self.assertRaisesRegex(ValueError,'PNR_FLOW_SNAPSHOT_CHANGED'):
            pnr.validate_provenance(self.mapping,self.out,'extract')
        self.assertEqual(p.read_text(),'changed')

    def test_resume_rejects_mapping_change_before_any_output_write_or_launch(self):
        (self.mapping/'clocked.sdc').write_text('different timing')
        before={p:p.read_bytes() for p in self.out.rglob('*') if p.is_file()}
        with patch.object(pnr,'ROOT',self.root),patch.object(pnr,'assets') as assets,patch.object(pnr.subprocess,'run') as launch:
            with self.assertRaisesRegex(ValueError,'PNR_MAPPING_INPUT_CHANGED'):
                pnr.run(self.mapping,self.out,'place','place',8)
            assets.assert_not_called(); launch.assert_not_called()
        self.assertTrue(all(p.read_bytes()==b for p,b in before.items()))

    def test_missing_repair_receipt_stops_before_output_or_launch(self):
        self.receipt.side_effect=ValueError('REPAIR_RECEIPT_REQUIRED')
        before={p:p.read_bytes() for p in self.out.rglob('*') if p.is_file()}
        with patch.object(pnr.subprocess,'run') as launch:
            with self.assertRaisesRegex(ValueError,'REPAIR_RECEIPT_REQUIRED'):
                pnr.run(self.mapping,self.out,'place','place',8)
            launch.assert_not_called()
        self.assertTrue(all(p.read_bytes()==b for p,b in before.items()))

    def test_both_report_entry_points_reject_changed_constraints_before_output(self):
        (self.mapping/'constraints-bound.json').write_text('new bounds')
        with patch.object(pnr.subprocess,'run') as launch:
            for call in (lambda:report.run(self.mapping,self.out),lambda:report.corner_report(self.mapping,self.out,'tt'),
                         lambda:probe.run(self.mapping,self.out,'tt')):
                with self.assertRaisesRegex(ValueError,'PNR_MAPPING_INPUT_CHANGED'): call()
            launch.assert_not_called()
        self.assertFalse((self.out/'sta-tt').exists()); self.assertFalse((self.out/'async-tt').exists())

    def test_report_rejects_runtime_changed_while_tool_was_running(self):
        def launched(command,stdout,**kwargs):
            stdout.write('EXTRACTED_STA_COMPLETE\n')
            self.runtime.return_value={'pinned-openroad':'replaced during run'}
            return type('Result',(),{'returncode':0})()
        with patch.object(report,'rc_inputs',return_value=(self.out/'extract.odb',self.out/'routed.spef')),\
             patch.object(report.subprocess,'run',side_effect=launched):
            with self.assertRaisesRegex(ValueError,'PNR_RUNTIME_CHANGED'):
                report.corner_report(self.mapping,self.out,'tt')

    def test_resume_preserves_original_commit_and_history_and_invalidates_later_stages(self):
        (self.out/'place.log').write_text('original failure evidence')
        (self.out/'place-metrics.json').write_text('original failed metrics')
        (self.out/'place.odb').write_text('original failed checkpoint')
        def stage(command,stdout,**kwargs):
            stdout.write('PNR_STAGE_COMPLETE place\n')
            (self.out/'place.odb').write_text('new checkpoint')
            (self.out/'place-metrics.json').write_text('new metrics')
            return type('Result',(),{'returncode':0})()
        before=(self.out/'run.json').read_bytes()
        with patch.object(pnr,'ROOT',self.root),patch.object(pnr,'pdk_verify'),patch.object(pnr,'assets',return_value=self.root),\
             patch.object(pnr.subprocess,'run',side_effect=stage),patch.object(pnr.subprocess,'check_output') as git,\
             patch('check_pnr_repair.check',return_value={'proof_sha256':'checked','inputs_sha256':{}}) as proof:
            pnr.run(self.mapping,self.out,'place','place',8)
            git.assert_not_called()
            proof.assert_called_once_with(self.mapping,self.out,'place')
        after=json.loads((self.out/'run.json').read_text())
        self.assertEqual(after['source_commit'],self.meta['source_commit'])
        self.assertEqual(json.loads((self.out/'resume-history/0/run.json').read_text()),json.loads(before))
        for name,expected in [('place.log','original failure evidence'),('place-metrics.json','original failed metrics'),
                              ('place.odb','original failed checkpoint')]:
            self.assertEqual((self.out/'resume-history/0'/name).read_text(),expected)
        self.assertEqual(set(after['checkpoints']),{'floorplan','place'})
        self.assertEqual(after['checkpoints']['place']['odb_sha256'],pnr.sha(self.out/'place.odb'))

    def test_failed_archive_stops_before_overwriting_retry_evidence(self):
        (self.out/'place.log').write_text('original failure evidence')
        before={p:p.read_bytes() for p in self.out.iterdir() if p.is_file()}
        with patch.object(pnr,'ROOT',self.root),patch.object(pnr,'pdk_verify'),patch.object(pnr,'assets',return_value=self.root),\
             patch.object(pnr.shutil,'copy2',side_effect=OSError('archive full')),patch.object(pnr.subprocess,'run') as launch:
            with self.assertRaisesRegex(OSError,'archive full'):
                pnr.run(self.mapping,self.out,'place','place',8)
            launch.assert_not_called()
        self.assertTrue(all(p.read_bytes()==b for p,b in before.items()))

    def test_changed_repair_auditor_rejected(self):
        self.audit.return_value={'reviewed.py':'changed'}
        with self.assertRaisesRegex(ValueError,'PNR_REPAIR_AUDIT_CHANGED'):
            pnr.validate_provenance(self.mapping,self.out,'floorplan')

    def test_repair_graph_and_proof_are_required_on_resume(self):
        files={str((self.out/('place-repair-'+side+'.tsv')).resolve()):side for side in ('before','after')}
        for path,text in files.items():Path(path).write_text(text)
        proof=self.out/'place-repair-proof.json';proof.write_text('proof')
        self.meta['checkpoints']['place']['repair']=dict(proof_sha256=pnr.sha(proof),
            protected_nets_sha256=pnr.sha(self.out/'place-native-protected-nets.txt'),
            inputs_sha256={p:pnr.sha(Path(p)) for p in files})
        self.save();pnr.validate_provenance(self.mapping,self.out,'place')
        Path(next(iter(files))).write_text('changed')
        with self.assertRaisesRegex(ValueError,'PNR_REPAIR_GRAPH_CHANGED'):
            pnr.validate_provenance(self.mapping,self.out,'place')
        proof.write_text('changed')
        with self.assertRaisesRegex(ValueError,'PNR_REPAIR_PROOF_CHANGED'):
            pnr.validate_provenance(self.mapping,self.out,'place')

    def test_missing_prior_repair_and_corner_reports_rejected(self):
        cp=self.meta['checkpoints'].pop('place');self.save()
        with self.assertRaisesRegex(ValueError,'PNR_PREREQUISITE_MISSING_place'):
            pnr.validate_provenance(self.mapping,self.out,'extract')
        self.meta['checkpoints']['place']=cp;self.save()
        report=self.out/pnr.electrical_report_names('global')[-1];report.write_text('changed')
        with self.assertRaisesRegex(ValueError,'PNR_ELECTRICAL_REPORT_CHANGED_global'):
            pnr.validate_provenance(self.mapping,self.out,'extract')

    def test_changed_physical_corner_rejected(self):
        self.physical.return_value={'all-pinned-corners':'different SS SRAM'}
        with self.assertRaisesRegex(ValueError,'PNR_PHYSICAL_INPUT_CHANGED'):
            pnr.validate_provenance(self.mapping,self.out,'floorplan')

    def test_changed_or_missing_protection_inventory_rejected(self):
        record=self.meta['checkpoints']['place']['repair']
        old=record.pop('protected_nets_sha256');self.save()
        with self.assertRaisesRegex(ValueError,'PNR_REPAIR_PROTECTION_CHANGED'):
            pnr.validate_provenance(self.mapping,self.out,'place')
        record['protected_nets_sha256']=old;self.save()
        (self.out/'place-native-protected-nets.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'PNR_REPAIR_PROTECTION_CHANGED'):
            pnr.validate_provenance(self.mapping,self.out,'place')

if __name__=='__main__': unittest.main()
