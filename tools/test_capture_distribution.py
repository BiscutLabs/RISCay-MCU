# SPDX-License-Identifier: Apache-2.0
import unittest
import tempfile
from pathlib import Path
from measure_capture_distribution import parse
from check_capture_distribution_controls import compare, require_baseline_inputs
from gf180_physical import sha


class CaptureDistributionTest(unittest.TestCase):
    def test_control_requires_the_same_mapping_and_runtime_paths_and_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            paths=[Path(d)/n for n in ('netlist.v','sta-config.json','different-netlist.v','different-config.json')]
            for p in paths:p.write_text('identical bytes')
            baseline=dict(inputs_sha256={str(p.resolve()):sha(p) for p in paths[:2]})
            require_baseline_inputs(baseline,paths[:2])
            for changed in ([paths[2],paths[1]],[paths[0],paths[3]]):
                with self.assertRaisesRegex(ValueError,'BASELINE_BINDING'):require_baseline_inputs(baseline,changed)
            paths[0].write_text('changed mapping')
            with self.assertRaisesRegex(ValueError,'BASELINE_BINDING'):require_baseline_inputs(baseline,paths[:2])

    def fixture(self):
        plan=[dict(instance='frame',root='frame/root/I',targets=['frame/bit0/CLK','frame/bit1/CLK'],latch=False,
            tree_cells=['frame/root'],propagation_and_spread_budget_ns=2.5)]
        lines=['TREE_COMPLETE']
        for edge in ('rise','fall'):
            origin=0 if edge=='rise' else 1
            for mode in ('min','max'):
                for j in range(2):
                    delay=1+j*.2+(0 if mode=='min' else .1);key=f'0:{edge}:{mode}:{j}'
                    lines+=['\t'.join(map(str,('CONTROL_PATH',key,origin,origin+delay,delay,delay,2,'frame/root/I',f'frame/bit{j}/CLK',edge,edge))),
                        '\t'.join(('CONTROL_POINTS',key,'frame/root/I',f'frame/bit{j}/CLK'))]
                lines+=['\t'.join(('TREE_SLEW','0',mode,edge,'2'))]
        return '\n'.join(lines),plan

    def test_every_leaf_both_edges_and_minmax(self):
        log,plan=self.fixture();result=parse(log,plan,2)
        self.assertEqual(len(result),2)
        for row in result:
            self.assertAlmostEqual(row['spread_bound_ns'],.3)
            self.assertTrue(row['within_budget'])
        plan[0]['propagation_and_spread_budget_ns']=1.2
        self.assertFalse(parse(log,plan,2)[0]['within_budget'])

    def test_missing_leaf_changed_slew_and_non_tree_paths_rejected(self):
        log,plan=self.fixture()
        for before,after,error in (('TREE_COMPLETE','','TIMING_INCOMPLETE'),('TREE_SLEW\t0\tmin\trise\t2','TREE_SLEW\t0\tmin\trise\t3','SOURCE_SLEW'),
                                  ('CONTROL_POINTS\t0:rise:min:0\tframe/root/I\tframe/bit0/CLK','CONTROL_POINTS\t0:rise:min:0\tframe/root/I\telsewhere/Q\tframe/bit0/CLK','POINT_BINDING')):
            with self.subTest(error=error):
                with self.assertRaisesRegex(ValueError,'DISTRIBUTION_'+error):parse(log.replace(before,after),plan,2)
        with self.assertRaisesRegex(ValueError,'DISTRIBUTION_COVERAGE'):parse('\n'.join(l for l in log.splitlines() if '0:fall:max:1' not in l),plan,2)
        for diagnostic in ('Warning: invalid endpoint','ERROR: timing failed'):
            with self.assertRaisesRegex(ValueError,'DISTRIBUTION_TIMING_INCOMPLETE'):parse(diagnostic+'\n'+log,plan,2)

    def test_actual_arc_comparison_cannot_count_unaffected_or_missing_rows(self):
        base={'a':[0,1,1,1,2],'b':[0,2,2,2,2]};mutant={'a':[0,1000,1000,1000,2],'b':base['b']}
        self.assertEqual(compare(base,mutant,{'a'}),1)
        with self.assertRaisesRegex(ValueError,'UNEXPECTED_CHANGE'):compare(base,mutant,set())
        with self.assertRaisesRegex(ValueError,'NO_DELAY'):compare(base,base,{'a'})
        with self.assertRaisesRegex(ValueError,'COVERAGE'):compare(base,{'a':mutant['a']},{'a'})


if __name__=='__main__':unittest.main()
