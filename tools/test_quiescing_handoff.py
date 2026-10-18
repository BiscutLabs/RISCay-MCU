# SPDX-License-Identifier: Apache-2.0
"""Pure edge-level controls for the narrowly proved held-data handoff."""
import copy
import unittest
from check_reset_crossings import (propagation_graph, reachable, prove_handoff_destinations,
                                  destination_cone, SRAM, NATIVE_STATE, NATIVE_PINS)


class HeldDataHandoffTest(unittest.TestCase):
    def fixture(self):
        cell=dict(type='$mux',port_directions=dict(A='input',B='input',S='input',Y='output'),
                  connections=dict(A=['0'],B=[10],S=[11],Y=[12]))
        item=dict(cell='mask',input_pin='B',output_pin='Y',input_bits=[10],output_bits=[12],select_bits=[11])
        return {'mask':cell},item

    def test_only_data_arc_is_handed_off(self):
        cells,item=self.fixture();model=lambda c:c['type']
        full=propagation_graph(cells,model);cut=propagation_graph(cells,model,[item])
        self.assertIn(12,reachable(full,[10]));self.assertNotIn(12,reachable(cut,[10]))
        self.assertIn(12,reachable(cut,[11]))
        self.assertIn(12,reachable(cut,[12]))  # Never remove an output/sink node.

    def test_parallel_other_cell_arc_survives(self):
        cells,item=self.fixture()
        cells['parallel']=dict(type='$or',port_directions=dict(A='input',B='input',Y='output'),
                               connections=dict(A=[10],B=['0'],Y=[12]))
        # A real graph rejects multiple drivers separately. This deliberately
        # isolates the adjacency builder's obligation to retain every other arc.
        cut=propagation_graph(cells,lambda c:c['type'],[item])
        self.assertIn(12,reachable(cut,[10]))

    def test_separate_bypass_and_native_control_paths_survive(self):
        cells,item=self.fixture()
        cells['native']=dict(type='ChiselAsyncEventRegister_v1',
            port_directions=dict(reset='input',trigger='input',d='input',q='output'),
            connections=dict(reset=[20],trigger=[21],d=[10],q=[22]))
        cut=propagation_graph(cells,lambda c:c['type'],[item])
        for bit in (10,20,21):self.assertIn(22,reachable(cut,[bit]))

    def test_passive_alias_never_cuts_unmasked_reset_or_payload_taint(self):
        cells,item=self.fixture()
        cells['allowance']=dict(type='ChiselAsyncPassiveDataAllowance_v1',
            port_directions=dict(a='input',q='output'),connections=dict(a=[10],q=[22]))
        cut=propagation_graph(cells,lambda c:c['type'],[item])
        self.assertIn(22,reachable(cut,[10]))

    def test_arst_and_clock_are_not_graph_cuts(self):
        cells,item=self.fixture()
        cells['reg']=dict(type='$adff',port_directions=dict(D='input',Q='output',CLK='input',ARST='input'),
                          connections=dict(D=[12],Q=[30],CLK=[10],ARST=[11]))
        graph=propagation_graph(cells,lambda c:c['type'],[item])
        # Sequential pins are inspected by audit_graph; Q is not propagated.
        self.assertNotIn(30,reachable(graph,[10,11,12]))
        self.assertIn(10,reachable(graph,[10]));self.assertIn(11,reachable(graph,[11]))

    def test_raw_ownership_is_uncut_and_final_crossing_restarts_at_origin(self):
        cells,item=self.fixture();full=propagation_graph(cells,lambda c:c['type'])
        cut=propagation_graph(cells,lambda c:c['type'],[item]);origins=[10]
        conservative=reachable(full,origins)
        self.assertIn(12,conservative)
        self.assertNotIn(12,reachable(cut,origins))
        self.assertIn(12,reachable(cut,conservative))  # Demonstrates the old-seed trap.

    def test_destination_policy_uses_cut_only_for_periodic_data(self):
        cells,item=self.fixture();model=lambda c:c['type']
        uncut=reachable(propagation_graph(cells,model),[10])
        cut=reachable(propagation_graph(cells,model,[item]),[10])
        self.assertNotIn(12,destination_cone('D',uncut,cut))
        for pin in ('CLK','ARST','EN','SRST'):
            self.assertIn(12,destination_cone(pin,uncut,cut))
        for pin in ('CLK','CEN','GWEN','WEN','A','D','BEN'):
            self.assertIn(12,destination_cone(pin,uncut,cut,fixed_macro=True))

    def test_post_mask_combinational_route_ends_at_periodic_data(self):
        cells,item=self.fixture()
        cells['logic']=dict(type='$xor',port_directions=dict(A='input',B='input',Y='output'),
                           connections=dict(A=[12],B=[21],Y=[22]))
        cells['reg']=dict(type='$adff',port_directions=dict(D='input',Q='output',CLK='input',ARST='input'),
                         connections=dict(D=[22],Q=[30],CLK=[40],ARST=[41]),
                         parameters=dict(CLK_POLARITY='1',ARST_POLARITY='1'))
        prove=lambda candidate:prove_handoff_destinations(candidate,lambda c:c['type'],[item],[[40]],
                                                         lambda reset,clock: reset==[41] and clock==[40])
        proof=prove(cells)
        self.assertEqual(proof['periodic_data_sinks'],[['reg','D']])
        # Crossing the periodic D boundary does not prove any use of its Q.
        cells['outside']=dict(type=SRAM,port_directions=dict(D='input'),connections=dict(D=[30]))
        self.assertEqual(prove(cells),proof)
        for pin in ('CLK','ARST'):
            changed=copy.deepcopy(cells);changed['reg']['connections'][pin]=[22]
            with self.assertRaisesRegex(ValueError,'^RDC_HELD_DATA_DESTINATION_reg_'+pin+'$'):
                prove(changed)

    def test_periodic_data_requires_proved_clock_edge_and_por(self):
        cells,item=self.fixture()
        cells['reg']=dict(type='$adff',port_directions=dict(D='input',Q='output',CLK='input',ARST='input'),
                         connections=dict(D=[12],Q=[30],CLK=[40],ARST=[41]),
                         parameters=dict(CLK_POLARITY='1',ARST_POLARITY='1'))
        prove=lambda candidate:prove_handoff_destinations(candidate,lambda c:c['type'],[item],[[40],[42]],
                                                         lambda reset,clock: reset==[41])
        self.assertEqual(prove(cells)['periodic_data_sinks'],[['reg','D']])
        related=copy.deepcopy(cells);related['reg']['connections']['CLK']=[42]
        self.assertEqual(prove(related)['periodic_data_sinks'],[['reg','D']])
        for group,pin,value,diagnostic in [
            ('connections','CLK',[99],'CLOCK'),('parameters','CLK_POLARITY','0','CLOCK'),
            ('connections','ARST',[99],'RESET'),('parameters','ARST_POLARITY','0','RESET')]:
            changed=copy.deepcopy(cells);changed['reg'][group][pin]=value
            with self.assertRaisesRegex(ValueError,'^RDC_HELD_DATA_'+diagnostic+'_reg$'):
                prove(changed)
        changed=copy.deepcopy(cells);changed['reg']['type']='$dff'
        with self.assertRaisesRegex(ValueError,'^RDC_HELD_DATA_RESET_reg$'):prove(changed)
        del changed['reg']['connections']['ARST'];del changed['reg']['port_directions']['ARST']
        self.assertEqual(prove(changed)['resetless_data_sinks'],['reg'])

    def test_post_mask_rejects_every_macro_input(self):
        for pin in ('CLK','CEN','GWEN','WEN','A','D','BEN'):
            cells,item=self.fixture()
            cells['memory']=dict(type=SRAM,port_directions={pin:'input'},connections={pin:[12]})
            with self.assertRaisesRegex(ValueError,'^RDC_HELD_DATA_DESTINATION_memory_'+pin+'$'):
                prove_handoff_destinations(cells,lambda c:c['type'],[item])

    def test_post_mask_rejects_native_state_even_before_periodic_data(self):
        for kind in sorted(NATIVE_STATE):
            for pin in NATIVE_PINS[kind]:
                cells,item=self.fixture()
                pins={p:[50+i] for i,p in enumerate(NATIVE_PINS[kind])};pins[pin]=[12];pins['q']=[22]
                cells['native']=dict(type=kind,port_directions={p:'output' if p=='q' else 'input' for p in pins},
                                     connections=pins)
                cells['reg']=dict(type='$dff',port_directions=dict(D='input',Q='output',CLK='input'),
                                  connections=dict(D=[22],Q=[30],CLK=[40]))
                # The old cut hides this route all the way through native Q.
                cut=propagation_graph(cells,lambda c:c['type'],[item])
                self.assertNotIn(22,reachable(cut,[10]))
                with self.assertRaisesRegex(ValueError,'^RDC_HELD_DATA_DESTINATION_native_'+pin+'$'):
                    prove_handoff_destinations(cells,lambda c:c['type'],[item])

    def test_post_mask_rejects_unclassified_cells(self):
        cells,item=self.fixture()
        cells['unknown']=dict(type='opaque',port_directions=dict(in_='input',out='output'),
                              connections=dict(in_=[12],out=[22]))
        with self.assertRaisesRegex(ValueError,'^RDC_HELD_DATA_DESTINATION_unknown_in_$'):
            prove_handoff_destinations(cells,lambda c:c['type'],[item])

    def test_stale_or_broadened_handoff_shape_is_rejected(self):
        for field,value in [('input_pin','S'),('output_pin','Q'),('input_bits',[11]),
                            ('output_bits',[99]),('select_bits',[10])]:
            cells,item=self.fixture();item[field]=value
            with self.assertRaisesRegex(ValueError,'RDC_HELD_DATA_HANDOFF_SHAPE'):
                propagation_graph(cells,lambda c:c['type'],[item])
        for pin,value in [('A',[20]),('S',[20]),('B',[20]),('Y',[20])]:
            cells,item=self.fixture();cells['mask']['connections'][pin]=value
            with self.assertRaisesRegex(ValueError,'RDC_HELD_DATA_HANDOFF_SHAPE'):
                propagation_graph(cells,lambda c:c['type'],[item])
        cells,item=self.fixture()
        with self.assertRaisesRegex(ValueError,'RDC_HELD_DATA_HANDOFF_SHAPE'):
            propagation_graph(cells,lambda c:c['type'],[item,copy.deepcopy(item)])


if __name__=='__main__':unittest.main()
