# SPDX-License-Identifier: Apache-2.0
"""Independent synthetic waveforms and malformed-evidence controls."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

from characterize_gf180_control_native import evaluate, read_trace, crossings, audit_bindings, extract, expected_binding, simulate, tied_constants
from gf180_physical import SC
from compare_control_native_steps import compare


def fixture(variant):
    ports={x:x for x in ("reset","in_req","in_ack","out_req","out_ack")}
    caps={f"cap{i}":[f"cell{j}/"+("E" if variant=="bd" else "CLK") for j in range(i*16,min(i*16+16,315))] for i in range(20)}
    plan=dict(variant=variant,ports=ports,captures=caps,signals={"guard":"guard"})
    events={n:[] for n in list(ports)+["guard"]+list(caps)}
    for n in caps:
        events[n]=[(560,0),(1450,1),(2260,0),(3150,1)] if variant=="bd" else [(560,1),(570,0),(2260,1),(2270,0)]
    events["in_ack"]=[(580,1),(1460,0),(2280,1),(3160,0)] if variant=="bd" else [(580,1),(2280,0)]
    events["out_req"]=[(590,1),(1440,0),(2290,1),(3140,0)] if variant=="bd" else [(590,1),(2290,0)]
    events["in_req"]=[(500,1),(1000,0),(2200,1),(2700,0)] if variant=="bd" else [(500,1),(2200,0)]
    events["out_ack"]=[(1400,1),(1800,0),(3100,1),(3500,0)] if variant=="bd" else [(1400,1),(3100,0)]
    events["reset"]=[(200,0)]
    if variant=="bd":events["in_ack"]=[(580,1),(1050,0),(2280,1),(2750,0)]
    if variant=="click":
        plan["phase"]={k:dict(node="phase"+k,pin="phase/"+k) for k in ("D","CLK","Q")}
        events.update(phaseCLK=[(559.8,1),(568.8,0),(2259.8,1),(2268.8,0)],
                      phaseQ=[(560.6,1),(2260.6,0)],phaseD=[(561,0),(2261,1)])
    measurements={f"q{i}t{j}":3.3 if j<2 else 0 for i in range(315) for j in range(4)}
    measurements.update({f"q{i}{op}{j}":3.3 if j==0 else 0 for i in range(315) for op in ("min","max") for j in range(2)})
    return plan,events,measurements


def trace(path,plan,events):
    times=sorted(set(range(0,3801,10))|{round(t+i*.01,8) for ev in events.values() for t,_ in ev for i in range(21)})
    lines=["time "+" ".join(f"v({n})" for n in events)]
    for t in times:
        values=[]
        for n,ev in events.items():
            value=1 if (plan["variant"]=="bd" and n.startswith("cap")) or n in ("reset","phaseD") else 0
            for time,v in ev:
                ramp=.2 if n in ("reset","in_req","out_ack") else .02
                if time<t<time+ramp:value=value+(v-value)*(t-time)/ramp;break
                if t>=time+ramp:value=v
            values.append(value*3.3)
        lines.append(" ".join(map(str,[t/1e9]+values)))
    path.write_text("\n".join(lines)+"\n")


def synthetic_mapping():
    """Graph-only BD fixture; deliberately not an electrical simulation model."""
    ports={k:dict(direction=d,bits=[b]) for k,d,b in
           (("reset","input",2),("in_req","input",3),("in_ack","output",4),("out_req","output",5),("out_ack","input",10))}
    conns={
        "a":dict(common=[7],rising=[9],falling=[10],q=[6]),
        "acknowledge":dict(common=[7],rising=[8],falling=[9],q=[4]),
        "b":dict(common=[4],rising=["1"],falling=[8],q=[7]),
        "long_hold":dict(a=[6],b=[10],q=[8]),
        "output_delay":dict(a=[6],b=["0"],q=[5]),
        "request_delay":dict(a=[3],b=["0"],q=[9]),
        "payload":dict(closed=[8],d=list(range(1000,1315)),q=list(range(2000,2315))),
        "data_delay":dict(a=list(range(5000,5315)),b=["0"]*315,q=list(range(1000,1315))),
    }
    modules={};stage=dict(ports=ports,cells={});record=dict(bindings=[])
    modules["FourPhaseStage_20"]=stage
    for owner,connections in conns.items():
        connections["reset"]=[2]
        directions={p:"output" if p=="q" else "input" for p in connections}
        name="adapter_"+owner
        stage["cells"]["ca_primitive_"+owner]=dict(type=name,connections=connections,port_directions=directions)
        body=dict(ports={p:dict(direction=directions[p],bits=bits) for p,bits in connections.items()},cells={},netnames={})
        modules[name]=body
        if owner=="data_delay":continue
        if owner=="payload":
            for group in range(20):
                body["cells"][f"buf{group}"]=dict(type=SC+"inv_1",connections={"I":[8],"ZN":[3000+group]},port_directions={"I":"input","ZN":"output"})
            for i in range(315):
                body["cells"][f"latch{i}"]=dict(type=SC+"latrnq_1",connections={"D":[1000+i],"Q":[2000+i],"E":[3000+i//16],"RN":[2]},
                    port_directions={"D":"input","Q":"output","E":"input","RN":"input"})
        else:
            body["cells"]["u0"]=dict(type=SC+"graph_fixture_"+owner,connections=deepcopy(connections),port_directions=directions)
        binding_cells=[]
        for cellname,c in body["cells"].items():
            pins={}
            for pin,bits in c["connections"].items():
                bit=bits[0];symbol=f"net{bit}" if isinstance(bit,int) else "1'b"+bit
                if isinstance(bit,int):body["netnames"][symbol]={"bits":[bit]}
                pins[pin]=symbol
            binding_cells.append(dict(name=cellname,cell=c["type"],pins=pins))
        model,params=expected_binding("bd",owner)
        record["bindings"].append(dict(module=name,model=model,parameters=params,cells=binding_cells))
    return dict(modules=modules),record


class NativeCharacterizationTest(unittest.TestCase):
    def result(self,variant="bd",change=None,log_change=None,trace_change=None):
        plan,events,m=fixture(variant)
        if change:change(plan,events,m)
        log="\n".join(f"{k} = {v}" for k,v in m.items())+"\n"
        if log_change:log=log_change(log)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"trace"
            trace(path,plan,events)
            if trace_change:path.write_text(trace_change(path.read_text()))
            return evaluate(plan,("tt","typical",25,3.3),.2,"input_first",log,path,list(events))

    def test_both_native_baselines(self):
        for v in ("bd","click"):
            r=self.result(v)
            self.assertEqual(r["issues"],[])
            self.assertFalse(r["physical_qualification"])
            self.assertEqual(len(r["metrics"]["transactions"]),2)

    def test_duplicate_measurement(self):
        with self.assertRaisesRegex(ValueError,"NATIVE_Q_MEASUREMENTS"):
            self.result(log_change=lambda x:x+"q0t0 = 3.3\n")

    def test_missing_measurement(self):
        with self.assertRaisesRegex(ValueError,"NATIVE_Q_MEASUREMENTS"):
            self.result(log_change=lambda x:x.replace("q0t0 = 3.3\n",""))

    def test_nonfinite_measurement(self):
        with self.assertRaisesRegex(ValueError,"NATIVE_Q_MEASUREMENTS"):
            self.result(log_change=lambda x:x.replace("q0t0 = 3.3","q0t0 = nan"))

    def test_wrong_payload(self):
        r=self.result(change=lambda p,e,m:m.update(q0t1=0))
        self.assertIn("NATIVE_PAYLOAD_RETENTION",{x["id"] for x in r["issues"]})

    def test_retention_glitch_between_good_snapshots(self):
        r=self.result(change=lambda p,e,m:m.update(q314min0=1))
        self.assertEqual({x["id"] for x in r["issues"]},{"NATIVE_PAYLOAD_GLITCH"})

    def test_reversed_extrema(self):
        with self.assertRaisesRegex(ValueError,"NATIVE_Q_REVERSED_BOUNDS"):
            self.result(change=lambda p,e,m:m.update(q0min0=3.4))

    def test_extra_capture(self):
        def change(p,e,m):e["cap0"]=sorted(e["cap0"]+[(1700,0),(1705,1)])
        r=self.result(change=change)
        self.assertIn("NATIVE_CAPTURE_SEQUENCE",{x["id"] for x in r["issues"]})

    def test_missing_capture(self):
        r=self.result("click",change=lambda p,e,m:e.update(cap19=[]))
        self.assertIn("NATIVE_CAPTURE_SEQUENCE",{x["id"] for x in r["issues"]})

    def test_ack_before_last_capture(self):
        def change(p,e,m):e["cap19"][0]=(600,1)
        r=self.result("click",change=change)
        # Also corrupts pulse order; it must never get an apparent pass.
        self.assertTrue(r["issues"])
        def change_order(p,e,m):e["in_ack"][0]=(550,1)
        r=self.result("click",change=change_order)
        self.assertIn("NATIVE_ACK_BEFORE_CAPTURE",{x["id"] for x in r["issues"]})

    def test_trace_missing_node(self):
        with self.assertRaisesRegex(ValueError,"NATIVE_TRACE_HEADER"):
            self.result(trace_change=lambda x:x.replace("v(cap19)","v(wrong)"))

    def test_trace_nonfinite(self):
        with self.assertRaisesRegex(ValueError,"NATIVE_TRACE_ROW"):
            self.result(trace_change=lambda x:x.replace("0.0 0.0","0.0 nan",1))

    def test_threshold_interpolation(self):
        self.assertEqual(crossings([0,10,20],[0,10,0],5),[(5,"rise"),(15,"fall")])
        self.assertEqual(crossings([0,10,20],[0,10,0],3),[(3,"rise"),(17,"fall")])
        self.assertEqual(crossings([0,10,20],[0,10,0],7),[(7,"rise"),(13,"fall")])

    def test_phase_storage_analysis(self):
        r=self.result("click")
        self.assertEqual(len(r["metrics"]["phase_high_pulse_ns"]),2)
        self.assertAlmostEqual(r["metrics"]["phase_clock_to_q_ns"][0],.8)
        r=self.result("click",change=lambda p,e,m:e.update(phaseQ=[(560.6,1)]))
        self.assertIn("NATIVE_PHASE_SEQUENCE",{x["id"] for x in r["issues"]})

    def test_stimulus_reset_missing(self):
        r=self.result(change=lambda p,e,m:e.update(reset=[]))
        self.assertIn("NATIVE_STIMULUS_MISMATCH",{x["id"] for x in r["issues"]})

    def test_unresolved_sampling(self):
        def drop_fine_samples(text):
            lines=text.splitlines();out=[lines[0]]
            for line in lines[1:]:
                time=float(line.split()[0])*1e9
                if not 560<time<560.2:out.append(line)
            return "\n".join(out)+"\n"
        r=self.result(trace_change=drop_fine_samples)
        self.assertEqual(r["status"],"numerically-unresolved")

    def test_step_comparison(self):
        c=dict(name="case",corner="tt",ramp_ns=.2,order="input_first",fault=None,
               maximum_step_ns=2,events={"node":[[500,"rise"],[600,"fall"]]},issues=[],
               slews=[dict(node="node",edge="rise",time_ns=500,slew_ns=.2)],metrics={"pulse_ns":100})
        a=dict(source_sha256={"source":"hash"},tool_sha256="toolhash",plan_sha256="planhash",cases=[c]);b=deepcopy(a);b["cases"][0]["maximum_step_ns"]=1
        self.assertEqual(compare(a,b)["status"],"step-comparison-pass")
        b["cases"][0]["events"]["node"][0][0]+=.1
        self.assertEqual(compare(a,b)["status"],"step-sensitive")
        b["source_sha256"]={"source":"different"}
        with self.assertRaisesRegex(ValueError,"NATIVE_STEP_SOURCE_MISMATCH"):compare(a,b)
        b=deepcopy(a);b["cases"][0]["maximum_step_ns"]=1;b["tool_sha256"]="different"
        with self.assertRaisesRegex(ValueError,"NATIVE_STEP_TOOL_MISMATCH"):compare(a,b)
        b["tool_sha256"]=a["tool_sha256"]
        a["cases"][0]["issues"]=[dict(id="NATIVE_EDGE_UNRESOLVED",node="node")]
        b["cases"][0]["issues"]=deepcopy(a["cases"][0]["issues"])
        self.assertIn("NATIVE_STEP_UNRESOLVED_INPUT",{x["id"] for x in compare(a,b)["issues"]})
        a["cases"][0]["issues"]=[dict(id="NATIVE_PAYLOAD_RETENTION",lane=0)]
        b["cases"][0]["issues"]=[dict(id="NATIVE_PAYLOAD_RETENTION",lane=1)]
        self.assertIn("NATIVE_STEP_VERDICT",{x["id"] for x in compare(a,b)["issues"]})

    def test_timeout_preserves_partial_log(self):
        def timeout(command,**kwargs):
            kwargs["stdout"].write("partial simulator evidence\n")
            raise subprocess.TimeoutExpired(command,kwargs["timeout"])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"case.spice"
            with patch("characterize_gf180_control_native.subprocess.run",side_effect=timeout):
                with self.assertRaises(subprocess.TimeoutExpired):simulate(path,Path(directory),False)
            self.assertEqual(path.with_suffix(".log").read_text(),"partial simulator evidence\n")
            self.assertTrue(path.with_suffix(".timeout.txt").exists())

    def test_source_extraction_and_pin_census(self):
        n,r=synthetic_mapping();p=extract(n,"bd");audit_bindings(n,r,p)
        self.assertEqual(sum(map(len,p["captures"].values())),315)
        self.assertEqual(len(p["captures"]),20)

    def test_live_clone_checked_even_when_original_definition_survives(self):
        n,r=synthetic_mapping()
        n['modules']['clone']=deepcopy(n['modules']['adapter_payload'])
        n['modules']['FourPhaseStage_20']['cells']['ca_primitive_payload']['type']='clone'
        binding=next(b for b in r['bindings'] if b['module']=='adapter_payload')
        binding['physical_modules']=['clone']
        p=extract(n,'bd');audit_bindings(n,r,p)
        n['modules']['clone']['cells']['latch0']['connections']['D']=[9000]
        with self.assertRaisesRegex(ValueError,'NATIVE_BINDING_CONNECTION'):audit_bindings(n,r,p)

    def test_only_unique_exact_ties_are_protocol_constants(self):
        body=dict(ports={},cells={'tie':dict(type=SC+'tiel',connections={'ZN':[5]},port_directions={'ZN':'output'})})
        self.assertEqual(tied_constants(body),{5:'0'})
        body['cells']['other']=dict(type=SC+'buf_1',connections={'I':[1],'Z':[5]},port_directions={'I':'input','Z':'output'})
        with self.assertRaisesRegex(ValueError,'NATIVE_TIE_DRIVER'):tied_constants(body)
        del body['cells']['other'];body['cells']['tie']['connections']['ZN']=[5,6]
        with self.assertRaisesRegex(ValueError,'NATIVE_TIE_SHAPE'):tied_constants(body)

    def test_wrapper_buffer_requires_exact_receipt_path_and_buffer_master(self):
        n,r=synthetic_mapping()
        p=extract(n,'bd')
        n['modules']['wrapped_payload']=dict(cells={
            'native':dict(type='adapter_payload'),
            'distribution':dict(type=SC+'buf_2')})
        n['modules']['FourPhaseStage_20']['cells']['ca_primitive_payload']['type']='wrapped_payload'
        p['physical_prefix']='soc/stage/'
        with self.assertRaisesRegex(ValueError,'NATIVE_BINDING_WRAPPER'):audit_bindings(n,r,p)
        r['repair_buffers']=['soc/stage/ca_primitive_payload/distribution']
        audit_bindings(n,r,p)
        r['repair_buffers']=['soc/other/ca_primitive_payload/distribution']
        with self.assertRaisesRegex(ValueError,'NATIVE_BINDING_WRAPPER'):audit_bindings(n,r,p)
        r['repair_buffers']=['soc/stage/ca_primitive_payload/distribution']
        n['modules']['wrapped_payload']['cells']['distribution']['type']=SC+'inv_2'
        with self.assertRaisesRegex(ValueError,'NATIVE_BINDING_WRAPPER'):audit_bindings(n,r,p)

    def test_tied_constant_does_not_change_capture_graph(self):
        n,r=synthetic_mapping();old=extract(n,'bd');body=n['modules']['FourPhaseStage_20']
        body['cells']['zero']=dict(type=SC+'tiel',connections={'ZN':[9000]},port_directions={'ZN':'output'})
        body['cells']['ca_primitive_request_delay']['connections']['b']=[9000]
        new=extract(n,'bd')
        self.assertEqual(new['cells'],old['cells'])
        self.assertEqual(new['captures'],old['captures'])

    def test_unused_specialized_constant_port_is_recorded_without_a_path(self):
        n,r=synthetic_mapping();body=n['modules']['FourPhaseStage_20']
        # Model the RISING=0 specialization independently: its declared input
        # exists, but no physical leaf consumes it. The generic graph fixture
        # above deliberately consumes every input and must not be exempted.
        adapter=n['modules']['adapter_b']
        adapter['ports']['rising']['bits']=[9001]
        del adapter['cells']['u0']['connections']['rising']
        adapter['cells']['u0']['port_directions']=dict(adapter['cells']['u0']['port_directions'])
        del adapter['cells']['u0']['port_directions']['rising']
        binding=next(b for b in r['bindings'] if b['module']=='adapter_b')
        del binding['cells'][0]['pins']['rising']
        body['cells']['ca_primitive_b']['connections']['rising']=[9000]
        plan=extract(n,'bd');audit_bindings(n,r,plan)
        self.assertEqual(plan['unused_protocol_inputs'],[dict(owner='b',pin='rising',original_constant=['1'],
            reason='specialized-input-has-no-physical-consumer')])
        # A real consumer or output alias defeats the exemption, even before
        # the independent native recipe audit runs.
        for output in (False,True):
            bad=deepcopy(n);adapter=bad['modules']['adapter_b'];bit=adapter['ports']['rising']['bits'][0]
            if output:adapter['ports']['q']['bits']=[bit]
            else:adapter['cells']['extra']=dict(type=SC+'inv_1',connections={'I':[bit],'ZN':[9999]},
                port_directions={'I':'input','ZN':'output'})
            with self.assertRaisesRegex(ValueError,'NATIVE_PROTOCOL_WIRING'):extract(bad,'bd')

    def test_wrong_keeper_inversion(self):
        n,r=synthetic_mapping();p=extract(n,"bd")
        r["bindings"][0]["parameters"]["COMMON_INVERT"]=0
        with self.assertRaisesRegex(ValueError,"NATIVE_BINDING_SPECIALIZATION"):audit_bindings(n,r,p)

    def test_omitted_capture_leaf(self):
        n,r=synthetic_mapping();del n["modules"]["adapter_payload"]["cells"]["latch314"]
        with self.assertRaisesRegex(ValueError,"NATIVE_STORAGE_INVENTORY"):extract(n,"bd")

    def test_protocol_rewire(self):
        n,r=synthetic_mapping()
        n["modules"]["FourPhaseStage_20"]["cells"]["ca_primitive_a"]["connections"]["common"]=[8]
        with self.assertRaisesRegex(ValueError,"NATIVE_PROTOCOL_WIRING"):extract(n,"bd")

    def test_unexplained_control_load(self):
        n,r=synthetic_mapping()
        n["modules"]["FourPhaseStage_20"]["cells"]["extra"]=dict(type=SC+"inv_1",connections={"I":[6],"ZN":[7000]},port_directions={"I":"input","ZN":"output"})
        with self.assertRaisesRegex(ValueError,"NATIVE_UNEXPLAINED_CUT"):extract(n,"bd")

    def test_recursive_hierarchy(self):
        n,r=synthetic_mapping()
        n["modules"]["adapter_a"]["cells"]["loop"]=deepcopy(n["modules"]["FourPhaseStage_20"]["cells"]["ca_primitive_a"])
        with self.assertRaisesRegex(ValueError,"NATIVE_HIERARCHY_CYCLE"):extract(n,"bd")

    def test_legal_edge_count_illegal_environment(self):
        r=self.result("click",change=lambda p,e,m:e.update(out_ack=[(550,1),(3100,0)]))
        self.assertIn("NATIVE_ILLEGAL_ENVIRONMENT",{x["id"] for x in r["issues"]})

    def test_binding_feedback_corruption(self):
        # One feedback adapter: independently recorded symbolic graph vs netlist.
        cell=dict(type=SC+"inv_1",connections={"I":[2],"ZN":[3]})
        body=dict(cells={"u0":cell},netnames={"state":{"bits":[2]},"inverse":{"bits":[3]}})
        n=dict(modules={"stage":{"cells":{"ca_primitive_test":{"type":"adapter"}}},"adapter":body})
        record=dict(bindings=[dict(model="ChiselAsyncAsymmetricC_v1",module="adapter",cells=[dict(name="u0",cell=SC+"inv_1",pins={"I":"state","ZN":"inverse"})])])
        plan=dict(module="stage",aliases=[dict(path="ca_primitive_test")])
        audit_bindings(n,record,plan)
        bad=deepcopy(n);bad["modules"]["adapter"]["cells"]["u0"]["connections"]["I"]=[3]
        with self.assertRaisesRegex(ValueError,"NATIVE_BINDING_CONNECTION"):audit_bindings(bad,record,plan)
        bad=deepcopy(n);bad["modules"]["adapter"]["cells"]["extra"]=deepcopy(cell)
        with self.assertRaisesRegex(ValueError,"NATIVE_BINDING_CELL_SET"):audit_bindings(bad,record,plan)
        bad=deepcopy(n);bad["modules"]["empty"]={"cells":{}}
        bad["modules"]["stage"]["cells"]["ca_primitive_test"]["type"]="empty"
        with self.assertRaisesRegex(ValueError,"NATIVE_BINDING_WRAPPER"):audit_bindings(bad,record,plan)


if __name__=="__main__":unittest.main()
