# SPDX-License-Identifier: Apache-2.0
import unittest
from passive_constant_proof import ConstantProof
from passive_allowance_policy import PASSIVE


def cell(kind, inputs, output, parameters=None):
    return dict(type=kind, connections=dict(inputs, Y=output),
                port_directions=dict({p:'input' for p in inputs},Y='output'),
                parameters=parameters or {})


class ConstantProofSpec(unittest.TestCase):
    def prove(self, cells, bits):
        proof=ConstantProof(cells,lambda c:c['type'])
        return [proof.bit(b) for b in bits]

    def test_runtime_and_state_are_unconstrained(self):
        state=dict(type='ChiselAsyncEventRegister_v1',
                   connections={'d':['1'],'reset':['1'],'trigger':['0'],'q':[2]},
                   port_directions={'d':'input','reset':'input','trigger':'input','q':'output'})
        self.assertEqual(self.prove({'state':state},[1,2,'x','z']),[None]*4)

    def test_no_clock_reset_or_native_control_assumptions(self):
        gate=cell('ChiselAsyncControlGate_v1',{'a':['0'],'reset':['1']},[3])
        self.assertEqual(self.prove({'gate':gate},[3]),[None])

    def test_bitwise_forcing_values_are_unconditional(self):
        cells={'and':cell('$and',{'A':[1,'1'],'B':['0',1]},[2,3]),
               'or':cell('$or',{'A':[1,'0'],'B':['1',1]},[4,5])}
        self.assertEqual(self.prove(cells,[2,3,4,5]),[0,None,1,None])

    def test_mux_requires_both_arms_when_select_free(self):
        c=cell('$mux',{'A':['0','1'],'B':['0','0'],'S':[1]},[2,3])
        self.assertEqual(self.prove({'mux':c},[2,3]),[0,None])

    def test_wiring_and_signed_extension(self):
        cells={'concat':cell('$concat',{'A':['1'],'B':['0']},[2,3]),
               'slice':cell('$slice',{'A':[2,3]},[4],{'OFFSET':'1'}),
               'pos':cell('$pos',{'A':['1']},[5,6],{'A_SIGNED':'1'})}
        self.assertEqual(self.prove(cells,[2,3,4,5,6]),[1,0,0,1,1])

    def test_unsigned_binary_operation_zero_extends_both_operands(self):
        c=cell('$or',{'A':['1'],'B':['0','0']},[2,3],{'A_SIGNED':'1','B_SIGNED':'0'})
        self.assertEqual(self.prove({'or':c},[2,3]),[1,0])

    def test_reduction_and_inversion(self):
        cells={'reduce':cell('$reduce_and',{'A':[1,'0']},[2]),
               'not':cell('$not',{'A':[2]},[3]),
               'logic':cell('$logic_not',{'A':[1,'1']},[4]),
               'xor':cell('$reduce_xor',{'A':['1','0','1']},[5])}
        self.assertEqual(self.prove(cells,[2,3,4,5]),[0,1,0,0])

    def test_unsupported_and_feedback_cones_fail_closed(self):
        cells={'unknown':cell('$unreviewed',{'A':['1']},[2]),
               'loop':cell('$not',{'A':[3]},[3])}
        self.assertEqual(self.prove(cells,[2,3]),[None,None])


if __name__=='__main__':unittest.main()
