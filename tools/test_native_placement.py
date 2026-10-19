# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest
import tkinter
from gf180_physical import SC, ROOT
from native_placement import groups


class NativePlacementTest(unittest.TestCase):
    def test_actual_tcl_geometry_gate_rejects_an_overrun_on_either_axis(self):
        t=tkinter.Tcl();t.eval((ROOT/'physical/gf180/pnr-native-placement.tcl').read_text())
        t.call('native_span_bound','fixture',64,12,16)
        for x,y in ((64.001,16),(12,64.001),('Inf',0),('NaN',1),(-1,0)):
            with self.subTest(x=x,y=y),self.assertRaisesRegex(tkinter.TclError,'NATIVE_PLACEMENT_SPREAD'):
                t.call('native_span_bound','fixture',64,x,y)

    def fixture(self):
        cells=[dict(name='a',cell=SC+'aoi21_1',pins=dict(A1='state',ZN='next')),
               dict(name='b',cell=SC+'nor2_1',pins=dict(A1='next',ZN='state')),
               dict(name='c',cell=SC+'buf_1',pins=dict(I='state',Z='q'))]
        return dict(bindings=[dict(model='ChiselAsyncAsymmetricC_v1',cells=cells,instances=['x','y'])]),dict(adapter_instances=dict(x='x/p',y='y/p'))

    def test_keeper_and_output_memberships_merge_without_loss(self):
        m,a=self.fixture()
        ds=[dict(owner=p,driver=p+'/c',buffer=p.rsplit('/',1)[0]+'/out') for p in a['adapter_instances'].values()]
        rows=groups(m,a,ds)
        expected={p+'/'+c['name'] for p in a['adapter_instances'].values() for c in m['bindings'][0]['cells']}|{r['buffer'] for r in ds}
        self.assertEqual({c for r in rows for c in r['cells']},expected)
        self.assertEqual(sum(len(r['cells']) for r in rows),len(expected))
        self.assertTrue(all(set(r['kinds'])=={'keeper','output'} for r in rows))
        self.assertEqual(rows,groups(m,a,list(reversed(ds))))

    def test_missing_keeper_or_internal_parent_is_rejected(self):
        m,a=self.fixture();bad=deepcopy(m);bad['bindings'][0]['cells'][0]['pins']['ZN']='wrong'
        with self.assertRaisesRegex(ValueError,'PLACEMENT_KEEPER_LOOP'):groups(bad,a,[])
        with self.assertRaisesRegex(ValueError,'PLACEMENT_PARENT_INSIDE_NATIVE'):
            groups(m,a,[dict(owner='x/p',driver='x/p/c',buffer='x/p/inside')])
