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

    def test_local_repack_restores_geometry_and_status_after_failed_dpl(self):
        t=tkinter.Tcl();t.eval((ROOT/'physical/gf180/pnr-native-placement.tcl').read_text())
        t.eval('''
          oo::class create Cell {
            variable x y orient status
            constructor {px py} {set x $px; set y $py; set orient R0; set status PLACED}
            method getBBox {} {return [self]}
            method xMin {} {return $x}; method yMin {} {return $y}
            method xMax {} {return [expr {$x+4}]}; method yMax {} {return [expr {$y+4}]}
            method getName {} {return [self]}; method isPlaced {} {return 1}
            method getOrient {} {return $orient}; method getPlacementStatus {} {return $status}
            method setOrient {v} {if {$status eq "FIRM"} {error FIXED_MOVE}; set orient $v}
            method setPlacementStatus {v} {set status $v}
            method setLocation {px py} {if {$status eq "FIRM"} {error FIXED_MOVE}; set x $px; set y $py}
          }
          Cell create a 10 10; Cell create b 10 100; Cell create neighbor 200 200
          proc block {method args} {
            switch $method {
              getInsts {return {a b neighbor}}
              getDbUnitsPerMicron {return 1}
              findInst {return [lindex $args 0]}
            }
          }
          namespace eval ord {proc get_db_block {} {return block}}
          set native_placement_groups {{fixture 64 {a b}}}
          set out unused; set stage global; set attempts 0; set artifacts {}
          proc write_db {path} {global artifacts; lappend artifacts $path}
          proc check_placement {args} {}
          proc detailed_placement {args} {
            global attempts
            incr attempts
            if {[neighbor getPlacementStatus] ne "FIRM"} {error NEIGHBOR_NOT_FIXED}
            b setLocation 800 900; b setOrient MX
            error DELIBERATE_NO_SPACE
          }
          set before [native_locations]
        ''')
        with self.assertRaisesRegex(tkinter.TclError,'NATIVE_REPACK_NO_LEGAL_NEIGHBORHOOD'):
            t.call('repack_native_groups')
        self.assertEqual(t.eval('expr {[native_locations] eq $before}'),'1')
        self.assertEqual(t.eval('llength $artifacts'),t.eval('set attempts'))
        # Diagnostic I/O failure must not prevent rollback.
        t.eval('proc write_db {path} {error DIAGNOSTIC_IO_ERROR}')
        with self.assertRaisesRegex(tkinter.TclError,'NATIVE_REPACK_NO_LEGAL_NEIGHBORHOOD'):
            t.call('repack_native_groups')
        self.assertEqual(t.eval('expr {[native_locations] eq $before}'),'1')
        t.eval('proc detailed_placement {args} {b setLocation 800 900; error ORDINARY_DPL_FAILED}')
        with self.assertRaisesRegex(tkinter.TclError,'ORDINARY_DPL_FAILED'):
            t.call('native_detailed_placement')
        self.assertEqual(t.eval('expr {[native_locations] eq $before}'),'1')
        t.eval('set stage route')
        with self.assertRaisesRegex(tkinter.TclError,'NATIVE_REPACK_AFTER_ROUTING'):
            t.call('repack_native_groups')
        # Same algorithm accepts a legal local packing, but restores the other
        # cells' original placement status rather than leaving them fixed.
        t.eval('proc detailed_placement {args} {} ; set stage global')
        t.call('repack_native_groups')
        self.assertFalse(t.eval('oversized_native_groups'))
        self.assertEqual(t.eval('neighbor getPlacementStatus'),'PLACED')
        self.assertEqual(t.eval('dict get [native_locations] neighbor'),t.eval('dict get $before neighbor'))
