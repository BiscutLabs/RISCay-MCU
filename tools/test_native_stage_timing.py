# SPDX-License-Identifier: Apache-2.0
"""Adversarial metadata and lane pairing controls independent of a PDK."""
from copy import deepcopy
import unittest

import native_stage_timing as n
import control_relative_timing as r
from test_control_relative_timing import arithmetic


def fixture(variant):
    family="FourPhaseStage" if variant=="bd" else "ClickStage"
    path="Soc.ca_child_stage";module=family+"_99";storage="latch_data" if variant=="bd" else "register_data"
    sources=dict(in_request="in.req",in_data="in.bits",in_acknowledge="in.ack",out_request="out.req",
                 out_data="out.bits",out_acknowledge="out.ack",reset="reset")
    sources.update(dict(latch_data="latchData",latch_closed="latchClosed",state_a="stateA") if variant=="bd" else
                   dict(register_data="registerData",capture="capture"))
    endpoints=[dict(id=k,width=3 if k=="in_data" else 2 if k in ("out_data",storage) else 1,
                    rtl_path=path+".ca_p_"+str(len(k))+"_"+k,source="~|"+module+">"+v) for k,v in sources.items()]
    shapes=dict(data_delay=("ControlGate",dict(OP=0,RESET_VALUE=0,WIDTH=2)),
                request_delay=("ControlGate",dict(OP=0,RESET_VALUE=0,WIDTH=1)))
    if variant=="bd":
        shapes.update(a=("AsymmetricC",dict(COMMON=1,COMMON_INVERT=1,FALLING=1,FALLING_INVERT=1,RISING=1,RISING_INVERT=0,RESET_VALUE=0)),
            b=("AsymmetricC",dict(COMMON=1,COMMON_INVERT=0,FALLING=1,FALLING_INVERT=0,RISING=0,RISING_INVERT=0,RESET_VALUE=0)),
            acknowledge=("AsymmetricC",dict(COMMON=1,COMMON_INVERT=1,FALLING=1,FALLING_INVERT=0,RISING=1,RISING_INVERT=0,RESET_VALUE=0)),
            long_hold=("ControlGate",dict(OP=2,RESET_VALUE=0,WIDTH=1)),output_delay=("ControlGate",dict(OP=0,RESET_VALUE=0,WIDTH=1)),
            payload=("ClosingLatch",dict(WIDTH=2)))
    else:
        shapes.update(fire=("And",dict(INPUTS=2,INVERT=2)),input_phase=("PhaseRegister",dict(RESET_VALUE=0)),
            input_compare=("Xor",{}),output_compare=("Xor",{}),payload=("EventRegister",dict(WIDTH=2,RESET_VALUE=0)),
            acknowledge_guard=("ControlGate",dict(OP=0,RESET_VALUE=0,WIDTH=1)),output_guard=("ControlGate",dict(OP=0,RESET_VALUE=0,WIDTH=1)))
    primitives=[dict(id=k,rtl_path=path+".ca_primitive_"+k,version=1,model="ChiselAsync"+model+"_v1",view="simulation",
                     parameters=dict(params,DELAY_FS=1234)) for k,(model,params) in shapes.items()]
    t=(dict(kind="long-hold-bundling-v2",request="in_request",input_data="in_data",latch_data="latch_data",matched_delay_fs=1234,
            latch_closed="latch_closed",acknowledge="in_acknowledge",output_request="out_request",output_data="out_data",
            output_delay_fs=1234,data_delay=dict(model_fs=1234),latch_delay=dict(model_fs=1234),
            control_delays={k:dict(model_fs=1234) for k in ("a","b","acknowledge","long_hold")}) if variant=="bd" else
       dict(kind="click-bundling-v1",variant="standard",initial_token=False,
            endpoints=["in_request","in_data","in_acknowledge","out_request","out_data","out_acknowledge","capture","register_data"],
            times={k:1234 for k in ("REQUEST_FS","ACKNOWLEDGE_FS","OUTPUT_FS")},
            cells={k:dict(model_fs=1234) for k in ("data_delay","fire","input_compare","input_phase","output_compare","payload")}))
    node=dict(rtl_path=path,module=module,endpoints=endpoints,primitives=primitives,timing=[t],children=[])
    if variant=="bd":node["timing"].append(dict(kind="bundled-data-path-v1",source="in_data",sink="latch_data",
        delay_cell="data_delay",delay_owner=[],budget=dict(model_fs=1234)))
    manifest=dict(top="Soc",design=node)
    netlist=dict(modules={"RiscayMcuDigital":dict(cells={"soc":dict(type="Soc")}),
        "Soc":dict(cells={"ca_child_stage":dict(type=family)}),
        family:dict(cells={"ca_primitive_data_delay":dict(connections=dict(reset=[2]))},
                    ports={k:dict(direction="input",bits=[2]) for k in ("reset","in_req","out_ack","in_bits")})})
    record=dict(bindings=[dict(model=p["model"],parameters=deepcopy(p["parameters"]),instances=[p["rtl_path"]]) for p in primitives])
    return manifest,netlist,record,path,variant


class MetadataTests(unittest.TestCase):
    def reject(self,mutate,diagnostic,variant="bd"):
        values=fixture(variant);mutate(*values[:3])
        with self.assertRaisesRegex(ValueError,"^"+diagnostic+"$"):n.descriptor(*values)

    def test_deduplicated_modules_and_small_widths(self):
        for variant in ("bd","click"):
            d=n.descriptor(*fixture(variant))
            self.assertEqual(d["payload_width"],2)
            self.assertNotEqual(d["logical_module"],d["module"])

    def test_custom_owner_rejected(self):
        self.reject(lambda m,*_:m["design"].update(module="I2cPublication"),"STAGE_UNSUPPORTED_CONTROLLER")

    def test_wrong_hierarchy(self):
        self.reject(lambda m,l,_:l["modules"]["Soc"]["cells"].clear(),"STAGE_INSTANCE_BINDING")

    def test_resource_bound_precedes_primitive_walk(self):
        def change(m,*_):
            next(e for e in m["design"]["endpoints"] if e["id"]=="out_data")["width"]=1000000000
            m["design"]["primitives"]=None
        self.reject(change,"STAGE_RESOURCE_BOUND")

    def test_duplicate_endpoint(self):
        self.reject(lambda m,*_:m["design"]["endpoints"].append(m["design"]["endpoints"][0]),"STAGE_DUPLICATE_ENDPOINT")

    def test_wrong_endpoint_source(self):
        self.reject(lambda m,*_:m["design"]["endpoints"][0].update(source="~|Other>in.req"),"STAGE_ENDPOINT_BINDING")

    def test_wrong_primitive_path(self):
        self.reject(lambda m,*_:m["design"]["primitives"][0].update(rtl_path="Other"),"STAGE_PRIMITIVE_PATH")

    def test_changed_reset_specialization(self):
        self.reject(lambda m,*_:m["design"]["primitives"][0]["parameters"].update(RESET_VALUE=1),"STAGE_PRIMITIVE_SPECIALIZATION")

    def test_stale_mapping(self):
        self.reject(lambda m,l,b:b["bindings"][0]["parameters"].update(DELAY_FS=5678),"STAGE_MAPPING_METADATA")

    def test_unmodelled_input(self):
        self.reject(lambda m,l,b:l["modules"]["FourPhaseStage"]["ports"].update(extra=dict(direction="input",bits=[9])),"STAGE_UNDECLARED_INPUT")

    def test_wrong_contract_delay(self):
        self.reject(lambda m,*_:m["design"]["timing"][0].update(matched_delay_fs=5678),"STAGE_TIMING_BINDING")

    def test_seeded_click_rejected(self):
        self.reject(lambda m,*_:m["design"]["timing"][0].update(initial_token=True),"STAGE_TIMING_BINDING","click")

    def test_wrong_ack_reference(self):
        self.reject(lambda m,*_:m["design"]["timing"][0].update(acknowledge="out_acknowledge"),"STAGE_TIMING_BINDING")

    def test_wrong_transform_sink(self):
        self.reject(lambda m,*_:m["design"]["timing"][1].update(sink="out_data"),"STAGE_TRANSFORM_BINDING")

    def test_wrong_click_reference(self):
        self.reject(lambda m,*_:m["design"]["timing"][0]["endpoints"].__setitem__(0,"reset"),"STAGE_TIMING_BINDING","click")


class LaneTests(unittest.TestCase):
    def fixture(self):
        # Lexical physical order is intentionally opposite to logical bus order.
        native=dict(q=[20,21],d=[10,11],cells=[dict(path="a",pins=dict(Q=21,D=11)),dict(path="z",pins=dict(Q=20,D=10))])
        return native,dict(d=[10,11]),dict(q=[10,11],a=["0",99]),["a/E","z/E"]

    def test_literal_resolved_by_logical_lane(self):
        constants,lanes=r.lane_bindings(*self.fixture())
        self.assertEqual(constants,{"1":0});self.assertEqual([x["logical"] for x in lanes],[1,0])

    def test_constant_to_dynamic_restores_obligation(self):
        values=self.fixture();values[2]["a"][0]=98
        self.assertEqual(r.lane_bindings(*values)[0],{})

    def test_duplicate_transform_source_is_not_a_constant(self):
        values=self.fixture();values[2]["a"]=[99,99]
        self.assertEqual(r.lane_bindings(*values)[0],{})

    def test_swapped_d_pin_rejected(self):
        values=self.fixture();values[0]["cells"][0]["pins"]["D"]=10
        with self.assertRaisesRegex(ValueError,"RELATIVE_LOGICAL_LANE_PAIRING"):r.lane_bindings(*values)

    def test_duplicate_leaf_rejected(self):
        values=self.fixture();values[3][1]="a/E"
        with self.assertRaisesRegex(ValueError,"RELATIVE_DUPLICATE_STORAGE"):r.lane_bindings(*values)

    def test_x_literal_rejected(self):
        values=self.fixture();values[2]["a"][0]="x"
        with self.assertRaisesRegex(ValueError,"RELATIVE_UNKNOWN_DATA_LITERAL"):r.lane_bindings(*values)

    def test_constant_keeps_capture_ack_obligation(self):
        results,plan,cell=arithmetic();plan.update(payload_width=2,constant_lanes={"1":0})
        for key in list(results["data"]["rows"]):
            if key.startswith("data:1:"):del results["data"]["rows"][key]
        results["common"]["rows"]["capture:1:max"]["delay_ns"]=9
        summary=r.margins(results,plan,cell)
        self.assertEqual(summary["minimum_ack_after_capture_ns"],-3)
        self.assertIsNone(summary["lanes"][1]["maximum_input_data_lag_ns"])
        self.assertEqual(n.numerical_status(summary)["status"],"NEGATIVE_LOCAL_MARGIN")

    def test_positive_local_margin_never_qualifies(self):
        status=n.numerical_status(r.margins(*arithmetic()))
        self.assertEqual(status["negative_metrics"],[]);self.assertFalse(status["physical_qualification"])


if __name__=="__main__":unittest.main()
