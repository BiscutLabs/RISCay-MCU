# SPDX-License-Identifier: Apache-2.0
import unittest
from gf180_physical import SC
from gf180_probe_plan import plan


def fixture(a=None):
    cells=[dict(name='gate',cell=SC+'and2_1',pins={'A1':'a','A2':'reset_n','Z':'n'}),
           dict(name='reset',cell=SC+'inv_1',pins={'I':'reset','ZN':'reset_n'}),
           dict(name='delay',cell=SC+'buf_1',pins={'I':'n','Z':'q'})]
    nets={n:('local',n) for c in cells for n in c['pins'].values()}
    if a is not None:nets['a']=('constant',str(a))
    flat={'root/'+c['name']:dict(connections={p:[nets[n]] for p,n in c['pins'].items()}) for c in cells}
    row=dict(id='guard',from_pins=['root/gate/A1'],to_pins=['root/delay/Z'])
    return row,dict(cells=cells),'root',flat


class LocalProbePlan(unittest.TestCase):
    def test_dynamic_input_requires_both_edges_of_its_exact_path(self):
        p=plan(*fixture())
        self.assertEqual(p['pairs'],[dict(source='root/gate/A1',sink='root/delay/Z',inverted=False,reset_only=False)])

    def test_zero_proof_covers_output_without_calling_it_a_timing_pass(self):
        p=plan(*fixture(0))
        self.assertEqual(p['pairs'],[])
        self.assertEqual(p['constant_sinks'],{'root/delay/Z':0})

    def test_literal_one_still_requires_reset_propagation(self):
        p=plan(*fixture(1))
        self.assertEqual(p['constant_sinks'],{})
        self.assertEqual(p['pairs'],[dict(source='root/reset/I',sink='root/delay/Z',inverted=True,reset_only=True)])

    def test_broken_interior_connection_is_not_coverage(self):
        row,binding,root,flat=fixture()
        binding['cells'][-1]['pins']['I']='disconnected'
        with self.assertRaisesRegex(ValueError,'LOCAL_PROBE_GRAPH_UNCOVERED'):
            plan(row,binding,root,flat)

    def test_missing_sink_and_outside_adapter_are_rejected(self):
        row,binding,root,flat=fixture();row['to_pins']=['root/missing/Z']
        with self.assertRaisesRegex(ValueError,'LOCAL_PROBE_GRAPH_UNCOVERED'):
            plan(row,binding,root,flat)
        row['to_pins']=['other/delay/Z']
        with self.assertRaisesRegex(ValueError,'PROBE_OUTSIDE_ADAPTER'):
            plan(row,binding,root,flat)


if __name__=='__main__':unittest.main()
