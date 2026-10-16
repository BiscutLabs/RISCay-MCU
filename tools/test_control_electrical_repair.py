# SPDX-License-Identifier: Apache-2.0
"""Independent graph-corruption and missing-evidence controls; no PDK required."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import repair_gf180_control as repair
import screen_gf180_control_repair as screen


def fixture():
    def cell(kind, con, directions):
        return dict(type=kind, connections=con, port_directions=directions, parameters={}, attributes={})
    cells={"driver":cell(repair.SC+"nor2_1",{"A1":[2],"A2":[3],"ZN":[4]},
                         {"A1":"input","A2":"input","ZN":"output"})}
    for i in range(9):
        cells[f"sink{i}"]=cell(repair.SC+"mux2_1",{"S":[4],"I0":[2],"I1":[3],"Z":[10+i]},
                               {"S":"input","I0":"input","I1":"input","Z":"output"})
    cells["native"]=cell("ProtectedNative",{"d":[2]}, {"d":"input"})
    stage=dict(cells=cells, ports={"unused":{"direction":"input","bits":[458]}},
               netnames={"unused":{"bits":[458]},"old":{"bits":[4]},"unused_internal":{"bits":[459]}})
    return dict(modules={"Stage":stage,"ProtectedNative":dict(cells={},ports={},netnames={}),
        "RiscayMcuDigital":{"ports":{},"cells":{"soc":cell("Soc",{},{})}},
        "Soc":{"ports":{},"cells":{"ca_child_control":cell("Control",{},{})}},
        "Control":{"ports":{},"cells":{"ca_child_update":cell("Stage",{},{})}}})


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.patch=patch.dict(repair.TARGETS, {"bd":("Stage","driver","nor2_1",4,9)})
        self.patch.start();self.addCleanup(self.patch.stop)
        self.before=fixture();self.after=repair.repair(self.before,"bd")
        self.body=self.after["modules"]["Stage"]

    def reject(self, diagnostic):
        with self.assertRaisesRegex(ValueError,"^"+diagnostic+"$"):
            repair.audit(self.before,self.after,"bd")

    def test_complete_graph_proof(self):
        self.assertEqual(len(repair.audit(self.before,self.after,"bd")["buffers"]),3)
        self.assertEqual(self.before,fixture())

    def test_unused_port_alias(self):
        self.alias_buffer(458);self.reject("REPAIR_NEW_NET")

    def test_unused_named_net_alias(self):
        self.alias_buffer(459);self.reject("REPAIR_NEW_NET")

    def alias_buffer(self,bit):
        name=repair.PREFIX+"branch_0";old=self.body["cells"][name]["connections"]["Z"][0]
        self.body["netnames"][name+"_out"]["bits"]=[bit]
        for c in self.body["cells"].values():
            c["connections"]={p:[bit if b==old else b for b in bs] for p,bs in c["connections"].items()}

    def test_inverter_instead_of_buffer(self):
        self.body["cells"][repair.PREFIX+"root"]["type"]=repair.SC+"inv_4"
        self.reject("REPAIR_BUFFER_BINDING")

    def test_wrong_buffer_source(self):
        self.body["cells"][repair.PREFIX+"root"]["connections"]["I"]=[2]
        self.reject("REPAIR_BUFFER_SOURCE")

    def test_buffer_cycle(self):
        self.body["cells"][repair.PREFIX+"root"]["connections"]["I"]=self.body["cells"][repair.PREFIX+"branch_0"]["connections"]["Z"]
        self.reject("REPAIR_BUFFER_CYCLE")

    def test_missing_sink(self):
        self.body["cells"]["sink0"]["connections"]["S"]=[4]
        self.reject("REPAIR_MISSING_SINK")

    def test_sink_wrong_original_net(self):
        self.body["cells"]["sink0"]["connections"]["S"]=[3]
        self.reject("REPAIR_SINK_NOT_BUFFERED")

    def test_protected_pin_rewire(self):
        self.body["cells"]["native"]["connections"]["d"]=[4]
        self.reject("REPAIR_UNLISTED_EDIT")

    def test_protected_cell_change(self):
        self.body["cells"]["native"]["type"]="DifferentNative"
        self.reject("REPAIR_ORIGINAL_GRAPH_CHANGED")

    def test_unrelated_module_change(self):
        self.after["modules"]["Soc"]["attributes"]={"changed":"1"}
        self.reject("REPAIR_ORIGINAL_GRAPH_CHANGED")

    def test_duplicate_driver(self):
        self.before["modules"]["Stage"]["cells"]["sink0"]["connections"]["Z"]=[4]
        with self.assertRaisesRegex(ValueError,"REPAIR_NET_MEMBERSHIP"):
            repair.target(self.before,"bd")

    def test_protected_sink_is_forbidden(self):
        self.before["modules"]["Stage"]["cells"]["native"]["connections"]["d"]=[4]
        with self.assertRaisesRegex(ValueError,"REPAIR_NONORDINARY_SINK"):
            repair.target(self.before,"bd")

    def test_connectivity_accepts_renumbering_not_rewiring(self):
        x=deepcopy(self.before)
        for m in x["modules"].values():
            for p in m.get("ports",{}).values():p["bits"]=[b+1000 for b in p["bits"]]
            for c in m["cells"].values():c["connections"]={p:[b+1000 for b in bs] for p,bs in c["connections"].items()}
        self.assertEqual(repair.connectivity(x),repair.connectivity(self.before))
        x["modules"]["Stage"]["cells"]["sink0"]["connections"]["S"]=[1002]
        self.assertNotEqual(repair.connectivity(x),repair.connectivity(self.before))

    def test_capacitance_uses_all_branch_loads(self):
        def libcell(pins):
            return "\n".join(f'pin ({p}) {{ {field} : {value}; }}' for p,field,value in pins)
        lib={repair.SC+"nor2_1":libcell([("A1","capacitance",.01),("A2","capacitance",.01),("ZN","max_capacitance",.02)]),
             repair.SC+"mux2_1":libcell([("S","capacitance",.01),("I0","capacitance",.01),("I1","capacitance",.01)]),
             repair.BUFFER:libcell([("I","capacitance",.005),("Z","max_capacitance",.05)])}
        before=repair.electrical(self.before,"bd",{"test":lib})["test"]
        after=repair.electrical(self.after,"bd",{"test":lib})["test"]
        self.assertAlmostEqual(before[0]["pin_load_pf"],.09)
        self.assertFalse(before[0]["within_limit"])
        self.assertAlmostEqual(after[0]["pin_load_pf"],.005)
        branch=next(r for r in after if r["cell"]==repair.PREFIX+"branch_0")
        self.assertEqual(branch["sinks"],8);self.assertFalse(branch["within_limit"])


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.plan=dict(sources=["in_bits_x"],electrical=["driver/ZN"],queries=[
            dict(id="d",role="data",mode="max",sink="payload/D",source_edge="any",sink_edge="rise")])
        self.log="\n".join(["CONTROL_BEGIN",
            "CONTROL_PATH\td\t0\t5\t5\t5\t1.2\tin_bits_x\tpayload/D\tfall\trise",
            "CONTROL_POINTS\td\tin_bits_x\tdriver/ZN\tpayload/D",
            "CONTROL_SLEW\tdriver/ZN\t1.2\t1.0",
            "CONTROL_ELECTRICAL_BEGIN","CONTROL_ELECTRICAL_END","CONTROL_COMPLETE",""])

    def test_complete(self):
        self.assertEqual(screen.parse(self.log,self.plan)["rows"]["d"]["delay_ns"],5)

    def reject(self,log,diagnostic):
        with self.assertRaisesRegex(ValueError,"^"+diagnostic+"$"):screen.parse(log,self.plan)

    def test_nonfinite(self):self.reject(self.log.replace("\t1.2\tin_bits","\tnan\tin_bits"),"CONTROL_NONFINITE")
    def test_missing_completion(self):self.reject(self.log.replace("CONTROL_COMPLETE", "NO_COMPLETE"),"CONTROL_INCOMPLETE")
    def test_duplicate(self):self.reject(self.log+self.log.splitlines()[1]+"\n","CONTROL_QUERY_ID")
    def test_numeric_mismatch(self):self.reject(self.log.replace("\t0\t5\t5\t5", "\t0\t5\t4\t5"),"CONTROL_NUMERIC_CROSSCHECK")
    def test_wrong_polarity(self):self.reject(self.log.replace("\tfall\trise", "\tfall\tfall"),"CONTROL_ENDPOINT_BINDING")
    def test_wrong_source(self):self.reject(self.log.replace("\tin_bits_x\tpayload/D", "\treset\tpayload/D"),"CONTROL_SOURCE_BINDING")
    def test_reversed_min_max(self):
        self.plan["queries"].append(dict(self.plan["queries"][0],id="lo",mode="min"))
        extra="CONTROL_PATH\tlo\t0\t6\t6\t6\t1.2\tin_bits_x\tpayload/D\tfall\trise\nCONTROL_POINTS\tlo\tin_bits_x\tpayload/D\n"
        self.reject(self.log+extra,"CONTROL_REVERSED_BOUNDS")
    def test_missing_slew(self):self.reject(self.log.replace("CONTROL_SLEW\tdriver/ZN\t1.2\t1.0\n", ""),"CONTROL_COVERAGE")
    def test_missing_points(self):self.reject(self.log.replace("CONTROL_POINTS\td\tin_bits_x\tdriver/ZN\tpayload/D\n", ""),"CONTROL_COVERAGE")
    def test_missing_path_is_explicit_evidence_gap(self):
        log="\n".join(l for l in self.log.split("\n") if not l.startswith(("CONTROL_PATH", "CONTROL_POINTS")))
        log=log.replace("CONTROL_BEGIN", "CONTROL_BEGIN\nCONTROL_MISSING\td")
        self.assertEqual(screen.parse(log,self.plan)["missing"],["d"])
    def test_unknown_missing_id(self):self.reject(self.log+"CONTROL_MISSING\tunknown\n", "CONTROL_MISSING_ID")
    def test_tcl_identifier_injection(self):
        with self.assertRaisesRegex(ValueError,"CONTROL_TCL_IDENTIFIER"):screen.brace("name}\nexit")

    def test_data_budget_is_separate_from_capture_and_electrical_failures(self):
        result=dict(rows={"data:0:min:rise":{"delay_ns":1},"data:0:max:rise":{"delay_ns":9}},
                    missing=["capture:0:min:rise"],selected_slews_ns={"driver":[3,4]},electrical_violations=["overload"])
        summary=screen.summarize(result,"bd")
        self.assertTrue(summary["data_budget_numerically_met"])
        self.assertFalse(summary["physical_qualification"])
        result["rows"]["data:0:max:rise"]["delay_ns"]=11
        self.assertFalse(screen.summarize(result,"bd")["data_budget_numerically_met"])


if __name__=="__main__":unittest.main()
