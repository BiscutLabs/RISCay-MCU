# SPDX-License-Identifier: Apache-2.0
import copy
import importlib.util
from pathlib import Path
import unittest

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('proposed',root/'check_spi_replay_controls.py')
proposed=importlib.util.module_from_spec(spec)
spec.loader.exec_module(proposed)

class ProposedRunnerChecks(unittest.TestCase):
    def plan(self):
        native={'recipe-occupied','recipe-cs','recipe-sclk','recipe-initial-cs','recipe-initial-sclk'}
        wire=native|{'slot-load','slot-advance','occupancy-terminal','divider-enable','miso-capture'}
        return {'groups':[dict(name=variant+'-'+mode,variant=variant,mode=mode,
                               cases=[dict(label=f,family=f) for f in sorted(families)])
                          for variant in ('bd','click')
                          for mode,families in (('wire',wire),('strict',native))]}

    def test_all_required_families_each_mode(self):
        plan=self.plan()
        proposed.validate_coverage(plan)
        for g, group in enumerate(plan['groups']):
            for c in range(len(group['cases'])):
                reduced=copy.deepcopy(plan)
                del reduced['groups'][g]['cases'][c]
                with self.assertRaises(ValueError): proposed.validate_coverage(reduced)

    def test_paths_names_and_reserved_labels(self):
        self.assertEqual(proposed.local_file(root,'model.sv'),root/'model.sv')
        for p in ('../outside.sv',str((root.parent/'outside.sv').resolve()),'.'):
            with self.assertRaises(ValueError): proposed.local_file(root,p)
        for name in ('../outside','.','..','/absolute',''):
            with self.assertRaises(ValueError): proposed.safe_name(name)
        for change in ('duplicate','positive','unknown'):
            plan=self.plan()
            if change=='duplicate': plan['groups'][0]['cases'][1]['label']=plan['groups'][0]['cases'][0]['label']
            if change=='positive': plan['groups'][0]['cases'][0]['label']='positive'
            if change=='unknown': plan['groups'][0]['cases'][0]['family']='guessed'
            with self.assertRaises(ValueError): proposed.validate_coverage(plan)

if __name__=='__main__': unittest.main()
