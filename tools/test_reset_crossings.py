# SPDX-License-Identifier: Apache-2.0
import copy
import unittest
from check_reset_crossings import audit_graph, NATIVE_PINS, SRAM
from reset_bridge_proof import Cone


class ResetCrossingTest(unittest.TestCase):
    def fixture(self):
        def flop(d, q, rst=2, clk=4):
            return dict(type="$adff", parameters=dict(ARST_VALUE="0", ARST_POLARITY="1", CLK_POLARITY="1", WIDTH="1"),
                port_directions=dict(D="input", Q="output", ARST="input", CLK="input"),
                connections=dict(D=[d], Q=[q], ARST=[rst], CLK=[clk]))
        module=dict(ports={},netnames={k:dict(bits=[v]) for k,v in
            dict(reset=2,applicationResetRequest=3,systemReset=3).items()},cells={
                "first":flop(3,10),"second":flop(10,11),"consumer":flop(11,12)})
        return dict(modules=dict(Top=module)),flop

    def result(self, data):
        return audit_graph(data,"Top")

    def test_two_flop_containment_and_exclusive_first_stage_fanout(self):
        good,flop=self.fixture()
        self.assertEqual(self.result(good)["status"],"pass")
        for target in ("D","CLK","ARST"):
            data=copy.deepcopy(good)
            data["modules"]["Top"]["cells"]["consumer"]["connections"][target]=[10]
            self.assertEqual(self.result(data)["status"],"fail",target)
        data=copy.deepcopy(good)
        data["modules"]["Top"]["ports"]["leak"]=dict(direction="output",bits=[10])
        self.assertEqual(self.result(data)["status"],"fail")

    def test_matching_clock_and_por_polarities_are_required(self):
        good,_=self.fixture()
        for change in ("clock","edge","reset","polarity"):
            data=copy.deepcopy(good)
            cell=data["modules"]["Top"]["cells"]["second"]
            if change=="clock":cell["connections"]["CLK"]=[5]
            if change=="edge":cell["parameters"]["CLK_POLARITY"]="0"
            if change=="reset":cell["connections"]["ARST"]=[5]
            if change=="polarity":cell["parameters"]["ARST_POLARITY"]="0"
            self.assertEqual(self.result(data)["status"],"fail",change)

    def test_raw_reset_register_q_and_mux_enable_are_not_hidden(self):
        good,flop=self.fixture()
        for direct in (False,True):
            data=copy.deepcopy(good);m=data["modules"]["Top"]
            m["cells"]["rawState"]=flop("0",20,rst=3)
            m["cells"]["consumer"]["connections"]["D"]=[20 if direct else 21]
            if not direct:
                m["cells"]["select"]=dict(type="$mux",port_directions=dict(A="input",B="input",S="input",Y="output"),
                    connections=dict(A=["0"],B=["1"],S=[20],Y=[21]))
            result=self.result(data)
            self.assertTrue(any(v["source"]=="raw-Q:rawState" and v["sink"]=="consumer" for v in result["violations"]))

    def test_native_status_requires_a_synchronizer_not_a_module_exemption(self):
        data,_=self.fixture();m=data["modules"]["Top"]
        m["netnames"]["ca_child_telemetry_source.eligible"]=dict(bits=[20])
        m["cells"]["consumer"]["connections"]["D"]=[20]
        self.assertEqual(self.result(data)["status"],"fail")
        m["cells"]["first"]["connections"]["D"]=[20]
        m["cells"]["consumer"]["connections"]["D"]=[11]
        self.assertEqual(self.result(data)["status"],"pass")

    def test_unknown_cells_fail_closed(self):
        data,_=self.fixture()
        data["modules"]["Top"]["cells"]["consumer"]["type"]="$mystery"
        with self.assertRaisesRegex(ValueError,"RDC_UNCLASSIFIED_CELL"):
            self.result(data)

    def test_every_native_input_propagates_to_clocked_state(self):
        # A native state element is not an RDC synchronizer. Exercise each
        # actual pin, including data, reset and event/phase controls.
        for kind, inputs in NATIVE_PINS.items():
            for source in inputs:
                with self.subTest(kind=kind, source=source):
                    data, _ = self.fixture(); m = data['modules']['Top']
                    pins = {p: [3 if p == source else '0'] for p in inputs}
                    pins['q'] = [20]
                    m['cells']['native'] = dict(type=kind,
                        port_directions={p: 'output' if p == 'q' else 'input' for p in pins},
                        connections=pins)
                    m['cells']['consumer']['connections']['D'] = [20]
                    violations = self.result(data)['violations']
                    self.assertTrue(any(v['sink'] == 'consumer' and v['pin'] == 'D' for v in violations))

    def test_unknown_native_pin_or_direction_cannot_hide_a_source(self):
        for bad in ('inout', 'extra', 'missing'):
            data, _ = self.fixture(); m = data['modules']['Top']
            pins = dict(reset=[2], trigger=['0'], d=[3], q=[20])
            directions = dict(reset='input', trigger='input', d='input', q='output')
            if bad == 'inout': directions['d'] = 'inout'
            elif bad == 'extra': pins['hidden'] = [3]; directions['hidden'] = 'input'
            else: del pins['d']; del directions['d']
            m['cells']['native'] = dict(type='ChiselAsyncEventRegister_v1',
                port_directions=directions, connections=pins)
            with self.assertRaisesRegex(ValueError, 'RDC_(NATIVE_PIN_SCHEMA|UNCLASSIFIED_PIN_DIRECTION)'):
                self.result(data)

    def test_macro_clock_enable_address_and_data_are_destinations(self):
        for sink in ('CLK', 'CEN', 'GWEN', 'WEN', 'A', 'D'):
            data, _ = self.fixture(); m = data['modules']['Top']
            pins = {p: [3 if p == sink else '0'] for p in ('CLK', 'CEN', 'GWEN', 'WEN', 'A', 'D')}
            pins['Q'] = [30]
            m['cells']['macro'] = dict(type=SRAM, connections=pins,
                port_directions={p: 'output' if p == 'Q' else 'input' for p in pins})
            self.assertTrue(any(v['sink'] == 'macro' and v['pin'] == sink
                for v in self.result(data)['violations']))


class BridgeConeTest(unittest.TestCase):
    @staticmethod
    def expression(kind, a, b=None, width=4, signed_a=False, signed_b=False):
        pins = dict(A=a, Y=list(range(100, 100+width)))
        if b is not None: pins['B'] = b
        cell = dict(type=kind, connections=pins,
            port_directions={p: 'output' if p == 'Y' else 'input' for p in pins},
            parameters=dict(A_SIGNED=str(int(signed_a)), B_SIGNED=str(int(signed_b))))
        return Cone(dict(cells=dict(expression=cell))), pins['Y']

    @staticmethod
    def literal(value, width):
        return [str((value >> i) & 1) for i in range(width)]

    def test_signed_width_extension_and_mixed_unsigned_operands(self):
        for sa, sb in ((False, False), (True, False), (False, True), (True, True)):
            for a in range(4):
                for b in range(16):
                    av = a-4 if sa and sb and a >= 2 else a
                    bv = b-16 if sa and sb and b >= 8 else b
                    for kind, expected in (('$eq', int(av == bv)), ('$ne', int(av != bv)),
                            ('$add', av+bv), ('$sub', av-bv), ('$mul', av*bv),
                            ('$and', av & bv), ('$or', av | bv), ('$xor', av ^ bv)):
                        cone, out = self.expression(kind, self.literal(a, 2), self.literal(b, 4),
                            width=6, signed_a=sa, signed_b=sb)
                        self.assertEqual(cone.evaluate(out, {}), expected & 63, (kind, sa, sb, a, b))

    def test_undefined_shift_and_unknown_logic_are_not_proof(self):
        for amount in (4, 7):
            cone, out = self.expression('$shiftx', self.literal(15, 4), self.literal(amount, 3),
                width=2, signed_b=True)
            with self.assertRaisesRegex(ValueError, 'RDC_BRIDGE_UNDEFINED_SHIFT'):
                cone.evaluate(out, {})
        cone, out = self.expression('$mystery', ['0'])
        with self.assertRaisesRegex(ValueError, 'RDC_BRIDGE_UNPROVEN_OPERATOR'):
            cone.evaluate(out, {})
        cone, out = self.expression('$not', ['x'])
        with self.assertRaisesRegex(ValueError, 'RDC_BRIDGE_UNPROVEN_INPUT'):
            cone.evaluate(out, {})

    def test_payload_proof_rejects_logic_even_if_a_sample_matches(self):
        cone, out = self.expression('$and', [10], ['1'], width=1)
        with self.assertRaisesRegex(ValueError, 'RDC_BRIDGE_PAYLOAD_LOGIC'):
            cone.payload_leaf(out[0], {}, {10, 11})


if __name__=="__main__":unittest.main()
