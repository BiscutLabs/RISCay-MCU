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
        self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.mapping=self.root/'mapping'; self.out=self.root/'routed'
        self.mapping.mkdir(); self.out.mkdir()
        self.flow=self.root/'physical/gf180'; self.flow.mkdir(parents=True)
        for name in pnr.MAPPING_INPUTS: (self.mapping/name).write_text(name)
        for name in pnr.FLOW_INPUTS: (self.flow/name).write_text(name)
        (self.flow/'routing-lock.json').write_text('{}')
        for name in (*pnr.GENERATED_INPUTS,'protected-baseline.tcl','floorplan.odb','extract.odb','routed.spef'):
            (self.out/name).write_text(name)
        self.snapshot,self.hashes=pnr.snapshot_flow(self.out,[self.flow/n for n in pnr.FLOW_INPUTS])
        self.meta=dict(provenance_schema=pnr.PROVENANCE_SCHEMA,
            source_commit='original-checkout-commit',status='checkpoint-unqualified',
            mapping_inputs_sha256=pnr.mapping_hashes(self.mapping),flow_sources=self.hashes,
            generated_inputs_sha256={n:pnr.sha(self.out/n) for n in pnr.GENERATED_INPUTS},
            mapping_directory=str(self.mapping),output_directory=str(self.out),
            openroad=pnr.OPENROAD,threads=8,routing_lock_sha256=pnr.sha(self.flow/'routing-lock.json'),
            checkpoints={stage:dict(odb_sha256=pnr.sha(self.out/(stage+'.odb')),
                                   protected_baseline_sha256=pnr.sha(self.out/'protected-baseline.tcl'))
                         for stage in ('floorplan','extract')})
        self.meta['checkpoints']['extract']['spef_sha256']=pnr.sha(self.out/'routed.spef')
        self.save()

    def save(self): (self.out/'run.json').write_text(json.dumps(self.meta))

    def test_exact_inputs_and_checkpoint_are_accepted_read_only(self):
        before={p:p.read_bytes() for p in self.out.rglob('*') if p.is_file()}
        self.assertEqual(pnr.validate_provenance(self.mapping,self.out,'extract'),self.meta)
        self.assertTrue(all(p.read_bytes()==b for p,b in before.items()))

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

    def test_both_report_entry_points_reject_changed_constraints_before_output(self):
        (self.mapping/'constraints-bound.json').write_text('new bounds')
        with patch.object(pnr.subprocess,'run') as launch:
            for call in (lambda:report.run(self.mapping,self.out),lambda:report.corner_report(self.mapping,self.out,'tt'),
                         lambda:probe.run(self.mapping,self.out,'tt')):
                with self.assertRaisesRegex(ValueError,'PNR_MAPPING_INPUT_CHANGED'): call()
            launch.assert_not_called()
        self.assertFalse((self.out/'sta-tt').exists()); self.assertFalse((self.out/'async-tt').exists())

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
             patch.object(pnr.subprocess,'run',side_effect=stage),patch.object(pnr.subprocess,'check_output') as git:
            pnr.run(self.mapping,self.out,'place','place',8)
            git.assert_not_called()
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

if __name__=='__main__': unittest.main()
