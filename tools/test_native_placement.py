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
        inputs=[dict(owner='x/p',buffer='x/in',receivers=[dict(cell='x/p/a',pin='A1')])]
        joined=groups(m,a,ds,inputs)
        self.assertEqual({c for r in joined for c in r['cells']},expected|{'x/in'})
        self.assertTrue(any(set(r['kinds'])=={'keeper','output','input'} and 'x/in' in r['cells'] for r in joined))

    def test_missing_keeper_or_internal_parent_is_rejected(self):
        m,a=self.fixture();bad=deepcopy(m);bad['bindings'][0]['cells'][0]['pins']['ZN']='wrong'
        with self.assertRaisesRegex(ValueError,'PLACEMENT_KEEPER_LOOP'):groups(bad,a,[])
        with self.assertRaisesRegex(ValueError,'PLACEMENT_PARENT_INSIDE_NATIVE'):
            groups(m,a,[dict(owner='x/p',driver='x/p/c',buffer='x/p/inside')])

    def test_local_repack_restores_geometry_and_status_after_failed_dpl(self):
        t=tkinter.Tcl();t.eval((ROOT/'physical/gf180/pnr-native-placement.tcl').read_text())
        t.eval((ROOT/'physical/gf180/pnr-module-regions.tcl').read_text())
        t.eval('set module_region_bounded 0')
        t.eval('''
          oo::class create Cell {
            variable x y orient status master
            constructor {px py} {set x $px; set y $py; set orient R0; set status PLACED;set master small}
            method getBBox {} {return [self]}
            method xMin {} {return $x}; method yMin {} {return $y}
            method xMax {} {return [expr {$x+4}]}; method yMax {} {return [expr {$y+4}]}
            method getName {} {return [namespace tail [self]]}; method getMaster {} {return $master}
            method setMaster {v} {set master $v}; method isPlaced {} {return 1}
            method getOrient {} {return $orient}; method getPlacementStatus {} {return $status}
            method setOrient {v} {if {$status eq "FIRM"} {error FIXED_MOVE}; set orient $v}
            method setPlacementStatus {v} {set status $v}
            method setLocation {px py} {if {$status eq "FIRM"} {error FIXED_MOVE}; set x $px; set y $py}
          }
          proc small {method args} {return small};proc large {method args} {return large}
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
        self.assertIn('global-before-native-repack.odb',t.eval('set artifacts'))
        self.assertEqual(t.eval('llength [lsearch -all -inline -glob $artifacts *-failed.odb]'),t.eval('set attempts'))
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
        # Anchored legalization freezes only protected leaves. A resized parent
        # remains movable; failed DPL restores the entire trial, while success
        # keeps an ordinary buffer's new PLACED status.
        t.eval('''
          set protected_cells {{a master {}}}
          neighbor setPlacementStatus UNPLACED
          set anchor_before [native_locations]
          proc check_native_placement {} {}
          proc check_module_bounds {} {}
          proc detailed_placement {args} {
            if {[a getPlacementStatus] ne "FIRM" || [b getPlacementStatus] ne "PLACED"} {error WRONG_ANCHORS}
            neighbor setLocation 240 240; neighbor setPlacementStatus PLACED
            error ANCHOR_TRIAL_FAIL
          }
        ''')
        self.assertEqual(t.call('native_anchor_legalization'),0)
        self.assertEqual(t.eval('expr {[native_locations] eq $anchor_before}'),'1')
        t.eval('''
          proc detailed_placement {args} {
            if {[a getPlacementStatus] ne "FIRM" || [b getPlacementStatus] ne "PLACED"} {error WRONG_ANCHORS}
            neighbor setLocation 240 240; neighbor setPlacementStatus PLACED
          }
        ''')
        self.assertEqual(t.call('native_anchor_legalization'),1)
        self.assertEqual(t.eval('a getPlacementStatus'),'PLACED')
        self.assertEqual(t.eval('neighbor getPlacementStatus'),'PLACED')
        self.assertEqual(t.eval('dict get [native_locations] neighbor'),'240 240 R0 PLACED')
        t.eval('''
          set anchor_before [native_locations]
          proc detailed_placement {args} {neighbor setLocation 280 280}
          proc check_native_placement {} {error AFTER_REPACK_CHECK_FAILED}
        ''')
        self.assertEqual(t.call('native_anchor_legalization'),0)
        self.assertEqual(t.eval('expr {[native_locations] eq $anchor_before}'),'1')
        t.eval('proc check_native_placement {} {}')
        # Repair-backed anchoring restores same-master members to their legal
        # baseline; resized parents remain movable. Any later rejection restores
        # the complete post-repair geometry, orientation and placement statuses.
        t.eval('''
          a setLocation 10 10; b setLocation 18 10
          set baseline [native_repair_baseline]
          a setLocation 100 100; b setMaster large; b setLocation 300 300
          neighbor setPlacementStatus UNPLACED
          set repair_before [native_locations]
          proc detailed_placement {args} {
            if {[a xMin]!=10 || [a getPlacementStatus] ne "FIRM" ||
                [b getPlacementStatus] ne "PLACED" || [b getMaster] ne "large"} {error WRONG_BASELINE_ANCHORS}
            b setLocation 18 10
            neighbor setLocation 280 280;neighbor setPlacementStatus PLACED
          }
          proc check_native_placement {} {error AFTER_REPAIR_CHECK_FAILED}
        ''')
        self.assertEqual(t.call('native_anchor_legalization',t.eval('set baseline')),0)
        self.assertEqual(t.eval('expr {[native_locations] eq $repair_before}'),'1')
        t.eval('proc check_native_placement {} {}')
        self.assertEqual(t.call('native_anchor_legalization',t.eval('set baseline')),1)
        self.assertEqual(t.eval('dict get [native_locations] a'),'10 10 R0 PLACED')
        self.assertEqual(t.eval('b getMaster'),'large')
        self.assertEqual(t.eval('dict get [native_locations] neighbor'),'280 280 R0 PLACED')
        t.eval('set repair_before [native_locations];set missing $baseline;dict unset missing b')
        self.assertEqual(t.call('native_anchor_legalization',t.eval('set missing')),0)
        self.assertEqual(t.eval('expr {[native_locations] eq $repair_before}'),'1')
        # A pre-existing fixed member is never demoted or relocated. A changed
        # fixed baseline rejects and rollback leaves its current state intact.
        t.eval('''
          a setPlacementStatus LOCKED
          set baseline [native_repair_baseline]
          oo::objdefine a method setPlacementStatus {v} {
            if {$status eq "LOCKED" && $v ne "LOCKED"} {error FIXED_DEMOTED}
            set status $v
          }
          proc detailed_placement {args} {
            if {[a getPlacementStatus] ne "LOCKED"} {error FIXED_STATUS_CHANGED}
            neighbor setLocation 300 300
          }
        ''')
        self.assertEqual(t.call('native_anchor_legalization',t.eval('set baseline')),1)
        t.eval('set repair_before [native_locations];dict set baseline a {small 99 99 R0 LOCKED}')
        self.assertEqual(t.call('native_anchor_legalization',t.eval('set baseline')),0)
        self.assertEqual(t.eval('expr {[native_locations] eq $repair_before}'),'1')
        t.eval('''oo::objdefine a deletemethod setPlacementStatus
          a setPlacementStatus PLACED''')
        # Regional selection is whole-box, whole-native-group and nonfixed.
        # Ordinary neighbors may move, but an incomplete native group may not.
        t.eval('''
          b setLocation 10 100
          Cell create near 20 20
          Cell create inside_a 30 30; Cell create inside_b 40 30
          Cell create boundary_a 100 30; Cell create boundary_b 110 30
          Cell create fixed 20 40; fixed setPlacementStatus FIRM
          Cell create covered 20 50; covered setPlacementStatus COVER
          Cell create locked 20 60; locked setPlacementStatus LOCKED
          set fixture_cells {a b neighbor near inside_a inside_b boundary_a boundary_b fixed covered locked}
          proc block {method args} {
            global fixture_cells
            switch $method {
              getInsts {return $fixture_cells}
              getDbUnitsPerMicron {return 1}
              findInst {return [lindex $args 0]}
            }
          }
          lappend native_placement_groups {inside 64 {inside_a inside_b}} {boundary 64 {boundary_a boundary_b}}
          set before [native_locations]
          set selected [native_repack_neighbors [oversized_native_groups] $before [dict create a 1 b 1]]
        ''')
        self.assertEqual(set(t.splitlist(t.eval('dict keys $selected'))),{'a','b','near','inside_a','inside_b'})
        t.eval('''
          proc detailed_placement {args} {
            if {[near getPlacementStatus] eq "FIRM"} {error NEED_REGIONAL_ROOM}
            if {[inside_a getPlacementStatus] ne "PLACED" || [inside_b getPlacementStatus] ne "PLACED"} {error PARTIAL_GROUP}
            if {[boundary_a getPlacementStatus] ne "FIRM" || [boundary_b getPlacementStatus] ne "FIRM"} {error BOUNDARY_GROUP_MOVED}
            near setLocation 24 24
            b setLocation 14 10
          }
        ''')
        t.call('repack_native_groups')
        self.assertFalse(t.eval('oversized_native_groups'))
        for name in ('neighbor','boundary_a','boundary_b','fixed','covered','locked'):
            self.assertEqual(t.eval(f'dict get [native_locations] {name}'),t.eval(f'dict get $before {name}'))
        self.assertNotEqual(t.eval('dict get [native_locations] near'),t.eval('dict get $before near'))
        self.assertEqual(t.eval('near getPlacementStatus'),'PLACED')
        # A legal regional pass may stretch a complete neighboring group. One
        # bounded correction must keep the region's exterior fixed, and failure
        # in that correction must restore the outer baseline too.
        t.eval('''
          restore_native_locations $before
          set cascadeFailure 1; set artifacts {}
          proc write_db {path} {global artifacts; lappend artifacts $path}
          proc detailed_placement {args} {
            global cascadeFailure
            if {$cascadeFailure && [uplevel 1 {set depth}] == 1} {
              inside_b setPlacementStatus PLACED
              inside_b setLocation 800 900
              error CASCADE_NO_SPACE
            }
            if {[near getPlacementStatus] ne "FIRM"} {
              b setLocation 14 10
              inside_b setLocation 110 30
            } elseif {[inside_b getPlacementStatus] ne "FIRM"} {
              inside_b setLocation 34 30
            } else {error NEED_REGIONAL_ROOM}
          }
        ''')
        with self.assertRaisesRegex(tkinter.TclError,'NATIVE_REPACK_NO_LEGAL_NEIGHBORHOOD'):
            t.call('repack_native_groups')
        self.assertEqual(t.eval('expr {[native_locations] eq $before}'),'1')
        self.assertIn('global-cascade-regional-first-before-native-repack.odb',t.eval('set artifacts'))
        self.assertIn('global-cascade-regional-midpoint-before-native-repack.odb',t.eval('set artifacts'))
        self.assertIn('global-before-native-repack.odb',t.eval('set artifacts'))
        artifacts=t.splitlist(t.eval('set artifacts'))
        self.assertEqual(len(artifacts),len(set(artifacts)))
        t.eval('set cascadeFailure 0')
        t.call('repack_native_groups')
        self.assertFalse(t.eval('oversized_native_groups'))
        for name in ('neighbor','boundary_a','boundary_b','fixed','covered','locked'):
            self.assertEqual(t.eval(f'dict get [native_locations] {name}'),t.eval(f'dict get $before {name}'))
        for name in ('a','b','near','inside_a','inside_b'):
            self.assertEqual(t.eval(f'{name} getPlacementStatus'),'PLACED')
        with self.assertRaisesRegex(tkinter.TclError,'NATIVE_REPACK_DEPTH'):
            t.call('repack_native_groups',2)
