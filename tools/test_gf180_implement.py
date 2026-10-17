# SPDX-License-Identifier: Apache-2.0
"""Native mapping recipes must bind the live adapter after hierarchy cloning."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gf180_implement import audit, SC, SRAM


class AdapterAudit(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.ids=["FourPhaseSoc.owner.first","FourPhaseSoc.owner.second"]
        self.paths={i:"soc/owner/"+i.rsplit('.',1)[1]+"/variant_0.mapped" for i in self.ids}
        self.record={"bindings":[dict(module="Native",instances=self.ids,cells=[
            dict(name="u0",cell=SC+"buf_1",pins={"I":"d[0]","Z":"q"})])]}
        self.modules={
            "RiscayMcuDigital":{"cells":{
                "soc":{"type":"Soc"},
                **{f"ram{i}":{"type":SRAM,"connections":{}} for i in range(3)}}},
            "Soc":{"cells":{"owner":{"type":"Owner"}}},
            "Owner":{"cells":{name:{"type":"Wrapper"} for name in ("first","second")}},
            "Wrapper":{"cells":{"variant_0.mapped":{"type":"Native"}}},
            "Native":{"netnames":{"d":{"bits":[2]},"q":{"bits":[3]}},
                      "cells":{"u0":{"type":SC+"buf_1","connections":{"I":[2],"Z":[3]}}}}}
        (self.root/'netlist.v').write_text('// independent fixture artifact\n')
        self.print_patch=patch('builtins.print'); self.print_patch.start()
        self.addCleanup(self.print_patch.stop)

    def run_audit(self, paths=None):
        (self.root/'mapping.json').write_text(json.dumps(self.record))
        (self.root/'netlist.json').write_text(json.dumps({"modules":self.modules}))
        audit(self.root,adapter_instances=paths)
        return json.loads((self.root/'netlist-audit.json').read_text())

    def clone_first(self):
        self.modules['Native_clone_8']=copy.deepcopy(self.modules['Native'])
        self.modules['Wrapper_clone']={'cells':{'variant_0.mapped':{'type':'Native_clone_8'}}}
        self.modules['Owner']['cells']['first']['type']='Wrapper_clone'
        return self.modules['Native_clone_8']

    def test_fresh_synthesis_discovers_original_modules(self):
        result=self.run_audit()
        self.assertEqual(result['adapter_instances'],self.paths)
        self.assertEqual(result['preserved_async_cells'],2)

    def test_cloned_module_requires_exact_source_paths(self):
        self.clone_first()
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS_OR_MISSING_ADAPTER'):
            self.run_audit()
        self.assertEqual(self.run_audit(self.paths)['adapter_instances'],self.paths)

    def test_pristine_unused_definition_cannot_hide_changed_live_clone(self):
        clone=self.clone_first()
        clone['cells']['u0']['connections']['I']=[3]
        self.assertEqual(self.modules['Native']['cells']['u0']['connections']['I'],[2])
        with self.assertRaisesRegex(ValueError,'PRESERVED_CONNECTION_CHANGED_.*first/variant_0.mapped/u0/I'):
            self.run_audit(self.paths)

    def test_each_instance_of_original_recipe_is_checked(self):
        self.clone_first()
        self.modules['Native']['cells']['u0']['connections']['Z']=[2]
        with self.assertRaisesRegex(ValueError,'PRESERVED_CONNECTION_CHANGED_.*second/'):
            self.run_audit(self.paths)

    def test_clones_cannot_resize_native_master(self):
        self.clone_first()['cells']['u0']['type']=SC+'buf_2'
        with self.assertRaisesRegex(ValueError,'PRESERVED_CELL_MISSING'):
            self.run_audit(self.paths)

    def test_clones_cannot_add_or_remove_native_cells(self):
        clone=self.clone_first()
        original=copy.deepcopy(clone['cells'])
        for cells in ({},dict(original,extra=original['u0'])):
            with self.subTest(cells=list(cells)):
                clone['cells']=cells
                with self.assertRaisesRegex(ValueError,'PRESERVED_CELL_INVENTORY_CHANGED'):
                    self.run_audit(self.paths)

    def test_clones_cannot_add_or_remove_cell_pins(self):
        cell=self.clone_first()['cells']['u0']
        for pins in ({'I':[2]},{'I':[2],'Z':[3],'extra':[4]}):
            with self.subTest(pins=list(pins)):
                cell['connections']=pins
                with self.assertRaisesRegex(ValueError,'PRESERVED_PIN_INVENTORY_CHANGED'):
                    self.run_audit(self.paths)

    def test_missing_recipe_net_is_not_inferred(self):
        del self.clone_first()['netnames']['d']
        with self.assertRaisesRegex(ValueError,'PRESERVED_NET_MISSING'):
            self.run_audit(self.paths)

    def test_instance_inventory_is_exact(self):
        for paths in ({},dict(self.paths,extra='soc/extra'),[] ):
            with self.subTest(paths=paths):
                with self.assertRaisesRegex(ValueError,'ADAPTER_INSTANCE_INVENTORY_CHANGED'):
                    self.run_audit(paths)

    def test_paths_are_unique_nonempty_strings(self):
        for value,diagnostic in ((None,'INVALID'),('','INVALID'),(self.paths[self.ids[1]],'DUPLICATE')):
            with self.subTest(value=value):
                paths=dict(self.paths); paths[self.ids[0]]=value
                with self.assertRaisesRegex(ValueError,diagnostic+'_ADAPTER_INSTANCE_PATH'):
                    self.run_audit(paths)

    def test_path_cannot_move_to_another_owner(self):
        paths={self.ids[0]:self.paths[self.ids[1]],self.ids[1]:self.paths[self.ids[0]]}
        with self.assertRaisesRegex(ValueError,'ORIGINAL_ADAPTER_PATH_CHANGED'):
            self.run_audit(paths)

    def test_missing_original_path_is_not_rediscovered(self):
        self.modules['Wrapper']['cells']['replacement']=self.modules['Wrapper']['cells'].pop('variant_0.mapped')
        with self.assertRaisesRegex(ValueError,'ORIGINAL_ADAPTER_PATH_CHANGED'):
            self.run_audit(self.paths)

    def test_duplicate_recipe_instance_is_rejected(self):
        self.record['bindings'][0]['instances'].append(self.ids[0])
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ADAPTER_INSTANCE'):
            self.run_audit(self.paths)

    def test_original_module_definition_need_not_survive_cloning(self):
        self.clone_first()
        self.modules['Wrapper']['cells']['variant_0.mapped']['type']='Native_clone_8'
        del self.modules['Native']
        self.assertEqual(self.run_audit(self.paths)['preserved_async_cells'],2)


if __name__=='__main__': unittest.main()
