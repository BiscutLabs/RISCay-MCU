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


class FloorplanGeometry(unittest.TestCase):
    def test_sram_pin_escape_and_partial_density_are_separate(self):
        for width in (1940,2400,3930):
            g=pnr.geometry(width,height=2530);r=pnr.routability_regions(g)
            self.assertLess(r['band_density_percent'],g['placement_density']*100)
            for macro,halo in zip(g['macro_locations'],r['hard']):
                _,x,y=macro
                self.assertEqual(halo['orientation'],'R0')
                self.assertEqual(halo['box'][1],y-40)
                self.assertLess(halo['box'][0],x)
                self.assertGreater(halo['box'][2],x+301.3)
            self.assertLess(r['band'][1],1966)
            self.assertGreater(r['band'][3],1966)

    def test_zero_router_gate_checks_report_and_final_count(self):
        with TemporaryDirectory() as directory:
            report=Path(directory)/'drc.rpt';report.write_text('')
            self.assertEqual(pnr.router_violations(report,'Number of violations = 9\nNumber of violations = 0')['violations'],0)
            with self.assertRaisesRegex(ValueError,'PNR_ROUTER_VIOLATIONS'):
                pnr.router_violations(report,'Number of violations = 1')
            report.write_text('Short: actual retained violation')
            with self.assertRaisesRegex(ValueError,'PNR_ROUTER_VIOLATIONS'):
                pnr.router_violations(report,'Number of violations = 0')
            with self.assertRaisesRegex(ValueError,'PNR_ROUTER_DRC_COUNT_MISSING'):
                pnr.router_violations(report,'incomplete router log')

    def test_rectangle_keeps_macros_inside_core_and_square_default_unchanged(self):
        for width,height in ((3930,2530),(2530,3930),(1440,1440)):
            g=pnr.geometry(width,height=height)
            self.assertEqual(g['die_um'],[0,0,width,height])
            self.assertEqual(g['core_um'],[30,30,width-30,height-30])
            for _,x,y in g['macro_locations']:
                self.assertGreaterEqual(x,30);self.assertGreaterEqual(y,30)
                self.assertLess(x+301.3,width-30);self.assertLess(y+516,height-30)
        self.assertEqual(pnr.geometry(1440),pnr.geometry(1440,height=1440))
        for width,height in ((0,2530),(3930,0),(float('nan'),2530),(3930,float('inf'))):
            with self.assertRaisesRegex(ValueError,'INVALID_COMMON_OUTLINE'):pnr.geometry(width,height=height)

def design():
    return {
        "RiscayMcuDigital":{"ports":{},"cells":{
            "producer":{"type":"Producer","connections":{"a":[20],"b":[21]}},
            "consumer":{"type":"Consumer","connections":{"in_bits_pc":[20]}}}},
        "Producer":{"ports":{"a":{"bits":[1]},"b":{"bits":[1]},"unused":{"bits":[9]}},
                    "cells":{"gate":{"type":SC+"buf_1","connections":{"I":["0"],"Z":[1]},
                                     "port_directions":{"I":"input","Z":"output"}}}},
        "Consumer":{"ports":{"in_bits_pc":{"bits":[2]}},"cells":{}}}


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
            if stage!='floorplan':
                placement=self.out/(stage+'-native-placement.tsv');placement.write_text('checked geometry')
                cp['native_placement_sha256']=pnr.sha(placement)
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
        (self.out/'route-drc.rpt').write_text('')
        (self.out/'route.log').write_text('Number of violations = 0')
        self.meta['checkpoints']['route']['router_drc']=pnr.router_violations(self.out/'route-drc.rpt',(self.out/'route.log').read_text())
        (self.out/'route-native-routing.tsv').write_text('checked assignment')
        self.meta['checkpoints']['route']['native_routing_sha256']=pnr.sha(self.out/'route-native-routing.tsv')
        paths=[self.out/(name+'.tsv') for name in ('clock-repair-before','clock-repair-after','clock-sinks-before','clock-sinks-after')]
        for path in paths:path.write_text('clock evidence')
        (self.out/'clock-coverage-proof.json').write_text('proved clock inventory')
        self.meta['checkpoints']['clock']['clock_coverage']=dict(
            proof_sha256=pnr.sha(self.out/'clock-coverage-proof.json'),
            inputs_sha256={str(p.resolve()):pnr.sha(p) for p in paths})
        self.save()

    def save(self): (self.out/'run.json').write_text(json.dumps(self.meta))


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


    def test_clock_coverage_is_required_for_every_downstream_checkpoint(self):
        for name in ('clock-coverage-proof.json','clock-repair-after.tsv','clock-sinks-before.tsv'):
            path=self.out/name;old=path.read_bytes();path.write_text('changed')
            with self.assertRaisesRegex(ValueError,'PNR_CLOCK_'):
                pnr.validate_provenance(self.mapping,self.out,'extract')
            path.write_bytes(old)


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


if __name__=='__main__': unittest.main()
