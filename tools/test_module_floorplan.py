# SPDX-License-Identifier: Apache-2.0
import unittest
import json
from pathlib import Path
import tempfile
from module_floorplan import LABELS, owner, region_boxes, units, repair_budget
from gf180_physical import sha
from gf180_pnr import geometry, routability_regions
from report_module_layout import spill, added_buffer_area
from report_routability import Instance


class ModuleFloorplanTests(unittest.TestCase):
    def test_buffer_area_uses_proven_inventory_including_delay_buffers(self):
        instances=[Instance(n,m,'logic','R0',b) for n,m,b in [
            ('original','buf_2',(0,0,100,100)),('delay','dlyb_1',(0,0,2,4)),
            ('repair','buf_8',(0,0,3,4)),('cts','clkbuf_2',(0,0,2,3))]]
        proofs=[dict(added_buffers=['delay','repair']),dict(added_buffers=['cts'])]
        self.assertEqual(added_buffer_area(instances,proofs),26)
        for bad in (proofs+[dict(added_buffers=['delay'])],[dict(added_buffers=['missing'])]):
            with self.assertRaisesRegex(ValueError,'MODULE_BUFFER_INVENTORY'):
                added_buffer_area(instances,bad)

    def test_region_occupancy_includes_foreign_added_and_partial_cells(self):
        instances=[Instance(n,'cell',k,'R0',b) for n,k,b in [
            ('owner','logic',(0,0,2,10)),('foreign','logic',(5,0,15,2)),
            ('repair','logic',(2,2,4,4)),('tap','physical',(4,4,5,6))]]
        row=spill([dict(id='cpu',box_um=[0,0,10,10])],
                  [dict(owner='cpu',cells=['owner'])],instances)['cpu']
        self.assertAlmostEqual(row['owner_fill'],.2)
        self.assertAlmostEqual(row['total_logic_fill'],.34)
        self.assertAlmostEqual(row['total_physical_fill'],.36)
        self.assertEqual(row['spill_fraction'],0)
        moved=spill([dict(id='cpu',box_um=[0,0,10,10])],
                    [dict(owner='cpu',cells=['owner'])],instances,
                    initial={'owner':[-2,0,0,10]})['cpu']
        self.assertEqual(moved['centroid_um'],[1,5])
        self.assertEqual(moved['from_initial_legal_um'],dict(area_weighted_mean=2,maximum=2))

    def test_hierarchy_ownership_includes_transports_without_guessing(self):
        for name, expected in [('fabric/$abc$1','services'),('watchdog/counter','lf_reset'),
                               ('ca_child_program_source/storage','program'),
                               ('ca_child_housekeeping_reply_bridge/state','housekeeping'),
                               ('ca_child_core/ca_child_rf/data','cpu'),
                               ('ca_child_telemetry/bank','telemetry')]:
            self.assertEqual(owner('soc/'+name),expected)
        self.assertEqual(owner('soc/$abc$1'),'platform')
        with self.assertRaisesRegex(ValueError,'UNKNOWN_NATIVE_OWNER'):
            owner('soc/ca_child_unreviewed/state')

    def test_regions_have_requested_fill_and_do_not_overlap(self):
        areas={n: (12000 if n in ('lf_reset','platform') else 140000) for n in LABELS}
        boxes=region_boxes(areas,[30,30,2500,2500],1954)
        self.assertEqual(set(boxes),set(areas))
        for n,b in boxes.items():
            self.assertAlmostEqual(areas[n]/((b[2]-b[0])*(b[3]-b[1])),.60)
        with self.assertRaisesRegex(ValueError,'DO_NOT_FIT|OVERLAP'):
            region_boxes({n:a*5 for n,a in areas.items()},[30,30,2500,2500],1954)
        grid=(.56,3.92)
        snapped=region_boxes(areas,[30,30,2500,2500],1954,grid=grid)
        for n,b in snapped.items():
            for i,v in enumerate(b):
                self.assertAlmostEqual(v/grid[i%2],round(v/grid[i%2]))
                self.assertGreaterEqual(v,boxes[n][i]) if i<2 else self.assertLessEqual(v,boxes[n][i])
            self.assertGreaterEqual(areas[n]/((b[2]-b[0])*(b[3]-b[1])),.60)
            self.assertLessEqual(areas[n]/((b[2]-b[0])*(b[3]-b[1])),.65)

    def test_native_group_is_indivisible_and_every_cell_assigned_once(self):
        cells={'soc/ca_child_telemetry/a':{'type':'native'},'soc/buf':{'type':'buffer'},
               'soc/fabric/reg':{'type':'register'}}
        compact=[dict(cells=['soc/ca_child_telemetry/a','soc/buf'])]
        rows=units(cells,compact,dict(native=10,buffer=2,register=4))
        members=[n for r in rows for n in r['cells']]
        self.assertCountEqual(members,cells)
        self.assertEqual(next(r for r in rows if len(r['cells'])==2)['owner'],'telemetry')
        with self.assertRaisesRegex(ValueError,'CLUSTER_INVENTORY'):
            units(cells,compact+compact,dict(native=10,buffer=2,register=4))

    def test_repair_budget_preserves_mapped_floor_and_actual_halo_capacity(self):
        areas={n:12000 if n in ('lf_reset','platform') else 140000 for n in LABELS}
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'source';source.write_text('measured checkpoint')
            native=Path(td)/'native';native.write_text('{"groups": []}')
            modules=Path(td)/'modules';modules.write_text('{"units": []}')
            budget=Path(td)/'budget.json'
            sources=dict(checkpoint=str(source),netlist=str(source),native=str(native),modules=str(modules))
            inventory=dict(netlist_sha256=sha(source),native_groups=[],module_units=[])
            record=dict(owner_area_um2={n:a/2 for n,a in areas.items()},sources=sources,
                        inputs_sha256={p:sha(Path(p)) for p in sources.values()})
            budget.write_text(json.dumps(record))
            self.assertEqual(repair_budget(budget,areas,inventory)[0],areas)
            with self.assertRaisesRegex(ValueError,'BUDGET_INVENTORY'):
                repair_budget(budget,areas,{**inventory,'native_groups':['wrong']})
            for bad in ({**record['owner_area_um2'],'unknown':1},{k:v for k,v in record['owner_area_um2'].items() if k!='cpu'},
                        {**record['owner_area_um2'],'cpu':float('nan')}):
                budget.write_text(json.dumps({**record,'owner_area_um2':bad}))
                with self.assertRaisesRegex(ValueError,'BUDGET_INVALID'):repair_budget(budget,areas)
            budget.write_text(json.dumps(record));source.write_text('changed')
            with self.assertRaisesRegex(ValueError,'BUDGET_INVALID'):repair_budget(budget,areas)
        g=geometry(2850,.65,2530)
        boxes=region_boxes(areas,g['core_um'],1954,.62,(.56,3.92),g['macro_locations'])
        for b in boxes.values():
            for halo in routability_regions(g)['hard']:
                h=halo['box']
                self.assertFalse(min(b[2],h[2])>max(b[0],h[0]) and min(b[3],h[3])>max(b[1],h[1]))
        b=boxes['program'];effective=(b[2]-b[0])*(b[3]-b[1]-.5*(2100-b[1]))
        self.assertGreaterEqual(areas['program']/effective,.62)
        self.assertLessEqual(areas['program']/effective,.65)


if __name__=='__main__': unittest.main()
