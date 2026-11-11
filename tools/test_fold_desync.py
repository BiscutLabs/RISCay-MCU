# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest
from fold_desync import fold
from desync_transform import storage_scaffold, flatten_input
from test_desync_partition import fixture


class FoldTests(unittest.TestCase):
    def fixture(self):
        n,p=fixture();n['modules']['RiscayMcuDigital']=n['modules'].pop('chip');p['top']='RiscayMcuDigital'
        for c in n['modules']['RiscayMcuDigital']['cells'].values():c['parameters']['WIDTH']='1'
        n=flatten_input(n,p)
        generated,report=storage_scaffold(n,p)
        return n,p,generated,report

    def test_actual_next_state_data_is_retained_and_reset_and_enable_are_checked(self):
        n,p,g,r=self.fixture();result=fold(n,g,r,policy=p)
        self.assertEqual(result['modules']['RiscayMcuDigital']['cells']['fabric']['connections']['D'],
                         n['modules']['RiscayMcuDigital']['cells']['fabric']['connections']['D'])
        bad=deepcopy(g);bad['modules']['RiscayMcuDigital']['cells']['fabric/master']['connections']['D']=['0']
        # Structural folding deliberately retains the faulty D cone. SAT must
        # reject it; replacing D from the reference here would hide the bug.
        folded=fold(n,bad,r,policy=p)
        self.assertEqual(folded['modules']['RiscayMcuDigital']['cells']['fabric']['connections']['D'],['0'])
        for mutate,diagnostic in [
            (lambda c:c['fabric/slave']['connections'].update(EN=['0']),'PAIR_ENABLE'),
            (lambda c:c['desync/fabric/s/gate_work']['connections'].update(B=['0']),'GATE_CONDITION'),
            (lambda c:c['fabric/slave']['parameters'].update(EN_POLARITY='0'),'LATCH_PARAMETERS')]:
            bad=deepcopy(g);mutate(bad['modules']['RiscayMcuDigital']['cells'])
            with self.assertRaisesRegex(ValueError,diagnostic):fold(n,bad,r,policy=p)
        del r['state'][0]
        with self.assertRaisesRegex(ValueError,'STATE_INVENTORY'):fold(n,g,r,policy=p)


if __name__=='__main__':unittest.main()
