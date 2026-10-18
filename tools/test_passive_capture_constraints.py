# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest
from unittest.mock import patch
from test_native_allowance_audit import fixture
from passive_capture_constraints import bind_captures


class PassiveCaptureSpec(unittest.TestCase):
    def fixture(self):
        graph, mapping, audit = fixture()
        binding = mapping['bindings'][0]
        binding['model'] = 'ChiselAsyncPassiveDataAllowance_v1'
        binding['cells'] = []
        binding['ports'] = [p for p in binding['ports'] if p['name'] != 'reset']
        del graph['cells']['top/data/u0']
        graph['boundaries']['top/data/a'] = graph['boundaries']['top/data/q']
        fanout = dict(instances=[dict(instance='Top.data', capture_sinks=[
            dict(instance='Top.store', lane=0, model='ChiselAsyncEventRegister_v1',
                 source_lanes=[0], constant_value=None)])])
        return graph, mapping, audit, fanout

    def bind(self, graph, mapping, audit, fanout):
        with patch('passive_capture_constraints.flat', return_value=graph):
            return bind_captures({}, mapping, audit, fanout)['Top.data']

    def test_exact_dynamic_leaf_survives_source_alias_merge(self):
        g,m,a,f = self.fixture()
        g['ports']['source_side_observation'] = dict(direction='output', bits=[('top/',2)])
        result = self.bind(g,m,a,f)
        self.assertEqual(result['sink_pins'], ['top/store/u0/D'])
        self.assertTrue(result['merged_source_fanout'])

    def test_constant_seed_keeps_only_its_owned_capture(self):
        g,m,a,f = self.fixture()
        for port in ('top/data/a','top/data/q','top/store/d'):
            g['boundaries'][port] = [('constant','0')]
        g['cells']['top/store/u0']['connections']['D'] = [('constant','0')]
        g['cells']['unrelated'] = deepcopy(g['cells']['top/store/u0'])
        f['instances'][0]['capture_sinks'][0]['constant_value'] = 0
        result = self.bind(g,m,a,f)
        self.assertEqual(result['sink_pins'], ['top/store/u0/D'])
        self.assertEqual(result['constant_captures'], [dict(instance='Top.store',lane=0,value='0')])

    def test_dynamic_capture_cannot_be_tied_to_a_constant(self):
        g,m,a,f = self.fixture()
        g['boundaries']['top/store/d'] = [('constant','0')]
        g['cells']['top/store/u0']['connections']['D'] = [('constant','0')]
        with self.assertRaisesRegex(ValueError, 'PHYSICAL_CAPTURE_CONSTANT_UNPROVED'):
            self.bind(g,m,a,f)

    def test_other_source_lane_constant_does_not_prove_dynamic_lane(self):
        g,m,a,f = self.fixture()
        m['bindings'][0]['parameters']['WIDTH'] = '2'
        for pin in ('a','q'):
            g['boundaries']['top/data/' + pin].append(('constant','0'))
        g['boundaries']['top/store/d'] = [('constant','0')]
        g['cells']['top/store/u0']['connections']['D'] = [('constant','0')]
        with self.assertRaisesRegex(ValueError, 'PHYSICAL_CAPTURE_CONSTANT_UNPROVED'):
            self.bind(g,m,a,f)

    def test_wrong_constant_polarity_is_rejected(self):
        g,m,a,f = self.fixture()
        f['instances'][0]['capture_sinks'][0]['constant_value'] = 1
        g['boundaries']['top/store/d'] = [('constant','0')]
        g['cells']['top/store/u0']['connections']['D'] = [('constant','0')]
        with self.assertRaisesRegex(ValueError, 'PHYSICAL_CAPTURE_CONSTANT_UNPROVED'):
            self.bind(g,m,a,f)

    def test_capture_cannot_move_to_another_dynamic_source_lane(self):
        g,m,a,f = self.fixture()
        m['bindings'][0]['parameters']['WIDTH'] = '2'
        for pin in ('a','q'):
            g['boundaries']['top/data/' + pin].append(('top/',99))
        g['boundaries']['top/store/d'] = [('top/',99)]
        g['cells']['top/store/u0']['connections']['D'] = [('top/',99)]
        with self.assertRaisesRegex(ValueError, 'PHYSICAL_CAPTURE_DISCONNECTED'):
            self.bind(g,m,a,f)

    def test_disconnected_capture_is_not_waived(self):
        g,m,a,f = self.fixture()
        g['boundaries']['top/store/d'] = [('top/',99)]
        g['cells']['top/store/u0']['connections']['D'] = [('top/',99)]
        with self.assertRaisesRegex(ValueError, 'PHYSICAL_CAPTURE_DISCONNECTED'):
            self.bind(g,m,a,f)

    def test_deleted_or_wrong_owner_proof_rejected(self):
        g,m,a,f = self.fixture()
        f['instances'][0]['capture_sinks'][0]['model'] = 'ChiselAsyncClosingLatch_v1'
        with self.assertRaisesRegex(ValueError, 'PHYSICAL_CAPTURE_MODEL'):
            self.bind(g,m,a,f)
        f['instances'] = []
        with self.assertRaisesRegex(ValueError, 'PHYSICAL_CAPTURE_INVENTORY'):
            self.bind(g,m,a,f)


if __name__ == '__main__': unittest.main()
