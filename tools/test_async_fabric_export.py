from test_quiescing_receipt_probe import add_native_request_fixture, request_fixture_rtl
# SPDX-License-Identifier: Apache-2.0
"""Independent controls for the MCU fabric export extension."""
import copy
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
from check_export import (BD_FABRIC_PATH, CLICK_FABRIC_PATH, validate_fabric_path,
                          fabric_path_bindings, fabric_checker_source, validate_native_click,
                          validate_fabric_inventory, validate_click_fabric_controls)
from check_export import control_background, frame_head_background


class FrameHeadBackgroundTests(unittest.TestCase):
    def fixture(self, click):
        top = 'ClickSoc' if click else 'FourPhaseSoc'
        family = 'Click' if click else 'FourPhase'
        store = dict(module=family+'FrameStore', primitives=[dict(id='return_guard',
            rtl_path=top+'.store.guard', model='ChiselAsyncControlGate_v1',
            parameters=dict(WIDTH='4', OP='0', DELAY_FS='32000000', RESET_VALUE='0'),
            ports=[dict(name='q', width=4, direction='output')])])
        banks = [dict(id=f'payload{i}' if click else 'payload', rtl_path=top+f'.store.bank{i}',
                      model='ChiselAsyncEventRegister_v1' if click else 'ChiselAsyncClosingLatch_v1',
                      ports=[dict(name='q', width=337, direction='output')]) for i in range(4)]
        if click:
            store['primitives'].extend(banks)
        else:
            store['children'] = [dict(id=f'storage{i}', contract=dict(primitives=[bank])) for i,bank in enumerate(banks)]
        heads = [dict(module=family+'FrameReceipt_'+str(i+1), rtl_path=top+'.head'+str(i)) for i in range(4)]
        manifest = dict(top=top, design=dict(children=[dict(id='i2c',contract=dict(children=[
            dict(id='frame_store',contract=store), *[dict(id=f'frame_head{i}_bridge',contract=h) for i,h in enumerate(heads)]]))]))
        scopes = {top:dict(registers=dict(gate_enabled=1, fabric_hostFrames_count=2, fabric_hostFrames_first_bank=2,
                                        fabric_hostRetiring=1, fabric_hostRetiringBank=2)),
            **{h['rtl_path']:dict(registers=dict(requestSync=1)) for h in heads}}
        drivers = {scope+'.'+name:width for scope,body in scopes.items() for name,width in body['registers'].items()}
        if not click: drivers[top+'.store.guard.q']=4
        drivers.update({bank['rtl_path']+'.q':337 for bank in banks})
        source = 'initial begin\nforce '+top+".reset = 1'b1; #1;\n" + ''.join(
            f"force {path} = {width}'h0;\n" for path,width in drivers.items())
        source += '\n#1;\n#1; check;\nif (ones_0 !== 1\'h1) $fatal(1,"INACTIVE_ENDPOINT:sample");\n$display("CONTRACT_PROBES_PASS:1");\nend\n'
        return manifest, scopes, source, store, heads

    def test_selected_heads_and_complete_idle_keep_original_oracles(self):
        for click in (False, True):
            manifest, scopes, source, store, heads = self.fixture(click)
            result, count = frame_head_background(source,manifest,scopes,1)
            self.assertEqual(count,13 if click else 14)
            self.assertTrue(result.startswith(source[:source.index('if (ones_0')]))
            self.assertTrue(result.endswith(source[source.index('if (ones_0'):].replace(
                'CONTRACT_PROBES_PASS:1',f'CONTRACT_PROBES_PASS:{count}')))
            for i, head in enumerate(heads):
                self.assertIn(f"force {head['rtl_path']}.requestSync = 1'h1;",result)
                self.assertIn(f"force {manifest['top']}.fabric_hostFrames_first_bank = 2'h{i:x};",result)
                self.assertIn(f"force {manifest['top']}.fabric_hostRetiringBank = 2'h{i:x};",result)
                self.assertIn(f"force {manifest['top']}.store.bank{i}.q = 337'h{(1<<337)-1:x};",result)
            guard = f"force {manifest['top']}.store.guard.q = 4'hf;"
            self.assertEqual(guard in result, not click)
            self.assertNotRegex(result,r'force [^;]*(?:out_ready|\.busy) =')
            self.assertEqual(frame_head_background(source,{'top':'Standalone'},{},1),(source,1))

    def test_return_guard_identity_and_catalogue_are_required(self):
        for fault in ('model','width','delay','operation','reset','uncatalogued'):
            manifest, scopes, source, store, _ = self.fixture(False)
            guard = store['primitives'][0]
            if fault=='model': guard['model']='UnqualifiedSource'
            elif fault=='width': guard['ports'][0]['width']=3
            elif fault=='delay': guard['parameters']['DELAY_FS']='0'
            elif fault=='operation': guard['parameters']['OP']='1'
            elif fault=='reset': guard['parameters']['RESET_VALUE']='15'
            else: source=source.replace("force FourPhaseSoc.store.guard.q = 4'h0;\n",'')
            with self.assertRaisesRegex(ValueError,'FRAME_HEAD_PROBE_'):
                frame_head_background(source,manifest,scopes,1)

    def test_ungated_configuration_and_present_gate_width(self):
        for click in (False, True):
            manifest, scopes, source, _, _ = self.fixture(click)
            top=manifest['top']
            scopes[top]['registers'].pop('gate_enabled')
            source=source.replace(f"force {top}.gate_enabled = 1'h0;\n",'')
            result,count=frame_head_background(source,manifest,scopes,1)
            self.assertEqual(count,13 if click else 14)
            self.assertNotIn('gate_enabled',result)
            scopes[top]['registers']['gate_enabled']=2
            with self.assertRaisesRegex(ValueError,'FRAME_HEAD_PROBE_DRIVER'):
                frame_head_background(source,manifest,scopes,1)

    def test_head_owner_and_actual_register_width_are_required(self):
        for click in (False, True):
            for fault in ('owner','width','uncatalogued'):
                manifest, scopes, source, _, heads = self.fixture(click)
                head=heads[2]
                if fault=='owner': head['module']='EndpointAdapter'
                elif fault=='width': scopes[head['rtl_path']]['registers']['requestSync']=2
                else: source=source.replace(f"force {head['rtl_path']}.requestSync = 1'h0;\n",'')
                with self.assertRaisesRegex(ValueError,'FRAME_HEAD_PROBE_'):
                    frame_head_background(source,manifest,scopes,1)

    def test_borrowed_bank_and_retirement_sources_must_be_catalogued(self):
        for click in (False, True):
            for net,width in (('fabric_hostRetiring',1),('fabric_hostRetiringBank',2),('store.bank3.q',337)):
                manifest,scopes,source,_,_=self.fixture(click)
                source=source.replace(f"force {manifest['top']}.{net} = {width}'h0;\n",'')
                with self.subTest(click=click,net=net), self.assertRaisesRegex(ValueError,'FRAME_HEAD_PROBE_DRIVER'):
                    frame_head_background(source,manifest,scopes,1)


from test_service_reply_receipt import add_control_token_fixture, CAPACITIES


class NativeFrameControlProbeTests(unittest.TestCase):
    def candidate(self, click, program_bytes=2048):
        top = 'ClickSoc' if click else 'FourPhaseSoc'
        def cell(identity, path, width, model='ChiselAsyncEventRegister_v1'):
            return dict(id=identity, rtl_path=path, model=model,
                        ports=[dict(name='q', width=width, direction='output')])
        join = dict(children=[dict(id=name, contract=dict(primitives=[cell('payload', top+'.'+name, width)]))
            for name,width in [('left_storage' if click else 'left',CAPACITIES[program_bytes][3]),('right_storage' if click else 'right',379)]])
        add_control_token_fixture(join['children'][0]['contract'],program_bytes)
        banks = [cell('payload'+str(i) if click else 'payload', top+'.bank'+str(i),337,
                      'ChiselAsyncEventRegister_v1' if click else 'ChiselAsyncClosingLatch_v1') for i in range(4)]
        store = dict(module=('Click' if click else 'FourPhase')+'FrameStore',primitives=banks if click else [],
            children=[] if click else [dict(id='storage'+str(i),contract=dict(primitives=[p])) for i,p in enumerate(banks)])
        manifest = dict(top=top,design=dict(children=[
            dict(id='control',contract=dict(module=('Click' if click else 'FourPhase')+'Control',children=[dict(id='join',contract=join)])),
            dict(id='i2c',contract=dict(children=[dict(id='frame_store',contract=store)]))]))
        registers={'ca_child_request_bridge.state':2,'fabric_housekeepingState_now':32,
            'fabric_hostFrames_count':2,'fabric_hostFrames_first_bank':2,'fabric_mmioCommitPending':1,
            'fabric_mmioCommit_applicationWritable':1}
        drivers={top+'.'+name:width for name,width in registers.items()}
        drivers.update({p['rtl_path']+'.q':337 for p in banks})
        drivers.update({c['contract']['primitives'][0]['rtl_path']+'.q':c['contract']['primitives'][0]['ports'][0]['width'] for c in join['children']})
        scopes={top:dict(registers={'fabric_housekeepingState_now':32}),top+'.ca_child_request_bridge':dict(registers={'state':2})}
        inventory={};add_native_request_fixture(manifest,scopes,inventory)
        drivers.update({path+'.'+name:width for path,regs in inventory.items() for name,width in regs.items()})
        source='initial begin\nforce '+top+".reset = 1'b1; #1;\n"+''.join(f"force {p} = {w}'h0;\n" for p,w in drivers.items())
        source+="\n#1;\nif (ones_0 !== 1'h1) $fatal(1,\"INACTIVE_ENDPOINT:sample\");\n$display(\"CONTRACT_PROBES_PASS:1\");\nend\n"
        return manifest,scopes,source,banks

    def test_six_capacities_narrow_control_without_changing_frames_or_c1e_request(self):
        # Token imageLength offsets are independent of the generated layout.
        cases=((4,249,232),(12,253,235),(1024,273,248),(1028,274,249),
               (2048,276,250),(3072,277,251))
        for click in (False,True):
            for capacity,width,length_lo in cases:
                manifest,scopes,source,banks=self.candidate(click,capacity)
                result,count=control_background(source,manifest,scopes,1,capacity)
                top=manifest['top'];left='left_storage' if click else 'left'
                state=top+'.'+left+'.q'
                loading=(1<<(width-3)) | (min(12,capacity)<<length_lo)
                self.assertIn(f"force {state} = {width}'h{loading:x};",result)
                self.assertIn(f"force {top}.ca_child_core.ca_child_address.ca_primitive_payload.q = 70'h",result)
                self.assertGreater(count,4*337*2)
                for bank in banks:
                    values={int(v,16) for v in re.findall(r'force '+re.escape(bank['rtl_path'])+r"\.q = 337'h([0-9a-f]+);",result)}
                    self.assertEqual(len(values),676)
                with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_CONTROL_CAPACITY'):
                    control_background(source,manifest,scopes,1)
                wrong=2048 if capacity!=2048 else 1024
                with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_CONTROL_TOKEN_SCHEMA'):
                    control_background(source,manifest,scopes,1,wrong)
                for field in ('bits.state.received','bits.state.entry','bits.state.imageLength'):
                    bad=copy.deepcopy(manifest)
                    node=bad['design']['children'][0]['contract']['children'][0]['contract']['children'][0]['contract']
                    next(f for f in node['channels'][1]['layout'] if f['field']==field)['lsb']+=1
                    with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_CONTROL_TOKEN_SCHEMA'):
                        control_background(source,bad,scopes,1,capacity)

    def test_every_native_bank_and_all_337_retained_bits_are_exercised(self):
        for click in (False,True):
            manifest,scopes,source,banks=self.candidate(click)
            result,count=control_background(source,manifest,scopes,1,2048)
            self.assertGreater(count,4*337*2)
            self.assertNotIn('fabric_hostFrames_first_frame_',result)
            for i,p in enumerate(banks):
                self.assertIn(f"force {manifest['top']}.fabric_hostFrames_first_bank = 2'h{i:x};",result)
                values={int(v,16) for v in re.findall(r'force '+re.escape(p['rtl_path'])+r"\.q = 337'h([0-9a-f]+);",result)}
                self.assertTrue({0,(1<<337)-1}.issubset(values))
                self.assertTrue(all((1<<bit) in values and ((1<<337)-1)^(1<<bit) in values for bit in range(337)))
            tail='if (ones_0'+source.split('if (ones_0')[1]
            self.assertTrue(result.endswith(tail.replace('CONTRACT_PROBES_PASS:1',f'CONTRACT_PROBES_PASS:{count}')))

    def test_missing_or_wrong_native_storage_is_rejected(self):
        for click in (False,True):
            for fault in ('model','width','uncatalogued'):
                manifest,scopes,source,banks=self.candidate(click)
                if fault=='model':banks[2]['model']='CombinationalEndpoint'
                elif fault=='width':banks[2]['ports'][0]['width']=336
                else:source=source.replace(f"force {banks[2]['rtl_path']}.q = 337'h0;\n",'')
                with self.assertRaisesRegex(ValueError,'CONTROL_PROBE_'):
                    control_background(source,manifest,scopes,1,2048)


def fixture(click):
    def primitive(name, model="ChiselAsyncControlGate_v1", **params):
        return {"id": name, "rtl_path": "Top." + name, "model": model,
                "parameters": params}
    source, sink = ("reply_sources", "register_data") if click else ("mux_sources", "mux_result")
    protocol = "two-phase-bundled-v1" if click else "four-phase-bundled-v1"
    node = {"module": "ClickFabric" if click else "FourPhaseFabric", "children": [],
            "channels": [{"id": name, "protocol": protocol, "role": role} for name, role in
                         (("request", "input"), ("response", "output"),
                          ("service_request", "output"), ("service_response", "input"))],
            "endpoints": [{"id": name, "rtl_path": "Top." + name, "width": width} for name, width in
                          ((source, 103), (sink, 33), ("capture_event", 1), ("request_data", 70),
                           ("response_data", 33), ("service_request_data", 70), ("service_response_data", 33), ("service_response_request", 1),
                           ("request_acknowledge", 1), ("response_request", 1), ("service_response_acknowledge", 1), ("service_request_request", 1))],
            "primitives": [primitive("data_delay"), primitive("accepted_phase")], "timing": []}
    if click:
        node["primitives"] += [primitive("payload", "ChiselAsyncEventRegister_v1", WIDTH="33"),
                               primitive("service_response_phase", "ChiselAsyncEventRegister_v1", WIDTH="1")]
        node["primitives"] += [primitive(name, WIDTH="1", OP="0", RESET_VALUE="0", DELAY_FS="110200001")
                               for name in ("request_guard", "request_delay", "output_delay", "acknowledge_guard", "output_guard", "return_guard")]
        node["primitives"] += [primitive("service_request_phase")]
    else:
        node["children"] = [{"id": "reply", "contract": {"module": "FourPhaseStage_2", "children": [],
                             "primitives": [primitive("data_delay")],
                             "endpoints": [{"id": "in_data", "rtl_path": "Top.storage_data"}]}}]
    timing = {"id": "response_mux", "kind": "bundled-data-path-v1", "logic": CLICK_FABRIC_PATH if click else BD_FABRIC_PATH,
              "delay_owner": [] if click else ["reply"], "delay_cell": "data_delay",
              "source": source, "sink": sink}
    node["timing"] = [timing]
    if click:
        node["timing"].append(dict(id="capture_aperture", kind="bundled-setup-hold-v1", launch="request_request",
            transaction="request_data", data_valid="register_data", capture="capture_event", captured="response_data",
            setup_fs="100000", hold_fs="100000"))
        models = {"accepted_phase": "PhaseRegister", "service_request_phase": "PhaseRegister",
                  "payload": "EventRegister", "service_response_phase": "EventRegister",
                  "dispatch": "AsymmetricC", "request_pending": "Xor", "response_occupied": "Xor"}
        models.update({prefix + suffix: "ControlGate" for prefix in ("runnable", "capture") for suffix in ("_na", "_nb", "_or", "")})
        for name, model in models.items():
            cell = next((p for p in node["primitives"] if p["id"] == name), None)
            if cell is None:
                cell = primitive(name); node["primitives"].append(cell)
            cell["model"] = "ChiselAsync" + model + "_v1"
            cell["parameters"]["DELAY_FS"] = "1000000"
        for name, delay in (("data_delay", 10000000), ("request_guard", 11000000), ("request_delay", 11000000), ("output_delay", 32000000)):
            next(p for p in node["primitives"] if p["id"] == name)["parameters"]["DELAY_FS"] = str(delay)
    return node, timing


class FabricExportTest(unittest.TestCase):
    def test_timing_obligations_cannot_be_removed_or_renamed(self):
        for click in (False, True):
            node, _ = fixture(click)
            validate_fabric_inventory({"design": node})
            for index in range(len(node["timing"])):
                for remove in (False, True):
                    bad = copy.deepcopy(node)
                    if remove:
                        bad["timing"].pop(index)
                    else:
                        bad["timing"][index]["id"] = "unrecognized"
                    with self.assertRaisesRegex(ValueError, "TIMING_INVENTORY"):
                        validate_fabric_inventory({"design": {"module": "Top", "children": [{"contract": bad}]}})

    def test_click_composed_drain_bound_aperture_and_cell_envelope(self):
        node, _ = fixture(True)
        validate_click_fabric_controls(node)
        for name in ("acknowledge_guard", "output_guard", "return_guard"):
            for delay in (1, 32000000, 80200000):
                bad = copy.deepcopy(node)
                next(p for p in bad["primitives"] if p["id"] == name)["parameters"]["DELAY_FS"] = str(delay)
                with self.assertRaisesRegex(ValueError, "DRAIN_GUARD"):
                    validate_click_fabric_controls(bad)
        for name in ("payload", "accepted_phase", "dispatch", "request_pending", "capture_na", "runnable"):
            bad = copy.deepcopy(node)
            next(p for p in bad["primitives"] if p["id"] == name)["parameters"]["DELAY_FS"] = "1000001"
            with self.assertRaisesRegex(ValueError, "CELL_POLICY"):
                validate_click_fabric_controls(bad)
        bad = copy.deepcopy(node); bad["timing"][1]["hold_fs"] = "0"
        with self.assertRaisesRegex(ValueError, "APERTURE"):
            validate_click_fabric_controls(bad)

    def test_custom_paths_reject_changed_owner_schema_and_protocol(self):
        for click in (False, True):
            node, timing = fixture(click)
            validate_fabric_path(node, timing)
            for key, wrong in (("delay_owner", ["unrelated"]), ("delay_cell", "capture"),
                               ("source", "request_data"), ("sink", "response_data")):
                bad = dict(timing, **{key: wrong})
                with self.assertRaisesRegex(ValueError, "PATH_IDENTITY"):
                    validate_fabric_path(node, bad)
            for mutation in (lambda n: n.update(module="Unrelated"),
                             lambda n: n["channels"][0].update(protocol="four-phase-bundled-v1" if click else "two-phase-bundled-v1"),
                             lambda n: n["channels"].pop()):
                bad = copy.deepcopy(node); mutation(bad)
                with self.assertRaisesRegex(ValueError, "PATH_IDENTITY"):
                    validate_fabric_path(bad, timing)
            bad = copy.deepcopy(node); bad["endpoints"][0]["width"] -= 1
            with self.assertRaisesRegex(ValueError, "PATH_WIDTH"):
                validate_fabric_path(bad, timing)
        node, timing = fixture(False); node["children"][0]["contract"]["module"] = "ClickBuffer"
        with self.assertRaisesRegex(ValueError, "REPLY_OWNER"):
            validate_fabric_path(node, timing)

    def test_click_requires_event_storage_and_each_preserved_guard(self):
        node, timing = fixture(True)
        bad = copy.deepcopy(node); bad["primitives"][2]["model"] = "ChiselAsyncClosingLatch_v1"
        with self.assertRaisesRegex(ValueError, "CAPTURE_CELL"):
            validate_fabric_path(bad, timing)
        for name in ("request_guard", "request_delay", "acknowledge_guard", "output_guard", "return_guard"):
            for mutation in (lambda p: p["parameters"].update(OP="1"),
                             lambda p: p["parameters"].update(DELAY_FS="0"),
                             lambda p: p.update(model="Unrelated")):
                bad = copy.deepcopy(node)
                mutation(next(p for p in bad["primitives"] if p["id"] == name))
                with self.assertRaisesRegex(ValueError, "GUARD_CELL"):
                    validate_fabric_path(bad, timing)

    def test_native_click_rejects_rtz_even_in_nested_helpers(self):
        node, _ = fixture(True)
        manifest = {"top": "ClickSoc", "design": node}
        validate_native_click(manifest)
        for mutation in (lambda n: n.update(module="FourPhaseAdapter"),
                         lambda n: n["channels"][0].update(protocol="four-phase-bundled-v1"),
                         lambda n: n["primitives"][2].update(model="ChiselAsyncClosingLatch_v1")):
            bad = copy.deepcopy(node); mutation(bad)
            parent = copy.deepcopy(node); parent["children"] = [{"id": "hidden", "contract": bad}]
            for top in ("ClickSoc", "ClickTelemetry", "ClickSupervisor", "ClickSram", "ClickFrameStore"):
                with self.assertRaisesRegex(ValueError, "HAS_RTZ_IMPLEMENTATION"):
                    validate_native_click({"top": top, "design": parent})

    def test_extension_retains_original_checks_and_fails_on_api_drift(self):
        anchor = '\"initial-token-literal-mux\": ([], \"data\", \"mux_state\", \"out_data\")}'
        binding = 'if timing["logic"] in ("exclusive-merge-input-mux", "controlled-multiplexer-input-mux"):'
        fallback = '    if "INACTIVE_ENDPOINT:" in simulation.stdout:'
        layout = '        for endpoint in node["endpoints"]:\n            fields = layouts.get'
        guard = 'request = next((p for p in budget_owner["primitives"] if p["id"] == "request_delay"), None)'
        original = layout + "\n" + guard + "\n" + anchor + "\n" + binding + "\nrequire(marker_ok, 'MARKER')\nrequire(budget_ok, 'BUDGET')\n" + fallback
        adapted = fabric_checker_source(original)
        self.assertIn('layouts["response_data"]', adapted)
        self.assertIn('layouts["available"]', adapted)
        self.assertIn('"lsb": i, "width": 1} for i in range(4)', adapted)
        self.assertIn('FourPhase(?:Ram|Program)Return', adapted)
        self.assertIn('native program return', adapted)
        self.assertIn('native modulo-four increment feedback; 10 ns complete data budget', adapted)
        self.assertNotIn('temporary slot to retained native route; 10 ns complete data budget', adapted)
        self.assertIn('full selected source/unselected retained data and phase muxes, including every feedback bit', adapted)
        for missing in (layout,guard):
            with self.assertRaisesRegex(ValueError, "RAM_RETURN_.*CHECKER_SHAPE"):
                fabric_checker_source(original.replace(missing,""))
        self.assertIn("validate_fabric_path(node, timing)", adapted)
        self.assertIn("fabric_path_bindings(node, timing)", adapted)
        self.assertIn("require(marker_ok, 'MARKER')", adapted)
        self.assertIn("require(budget_ok, 'BUDGET')", adapted)
        self.assertIn("el" + binding, adapted)
        self.assertIn(fallback, adapted)
        self.assertIn('"contract_first_simulation.log"', adapted)
        self.assertIn('"contract_first_probe.sv"', adapted)
        self.assertLess(adapted.index('"contract_first_simulation.log"'), adapted.index(fallback))
        for wrong in ("", original + anchor, original.replace(binding, ""),
                      original.replace(fallback, ""), original+fallback):
            with self.assertRaisesRegex(ValueError, "SHAPE_CHANGED"):
                fabric_checker_source(wrong)

    def test_mux_data_and_capture_comparisons_reject_each_disconnection(self):
        # Independent pins, no production RTL or generated connection oracle.
        for click in (False, True):
            node, timing = fixture(click)
            pairs = fabric_path_bindings(node, timing)
            signals = sorted({s for pair in pairs for s in pair})
            flat = {s: s.replace(".", "_") for s in signals}
            for broken in [None] + [b for _, b in pairs]:
                declarations = "\n".join("reg [32:0] " + flat[s] + ";" for s in signals)
                checks = "\n".join(f'if ({flat[a]} !== {flat[b]}) $fatal(1,"FABRIC_PIN_BINDING");' for a, b in pairs)
                stimulus = "\n".join(f"{flat[s]}=0;" for s in signals) + "\n#1;\n" + checks
                stimulus += "\n" + "\n".join(flat[s] + "=" + ("0" if s == broken else "33'h1ffffffff") + ";" for s in signals)
                text = ("module Testbench;\n" + declarations + "\ninitial begin\n" + stimulus +
                        '\n#1;\n' + checks + '\n$display("FABRIC_PINS_PASS"); $finish; end endmodule\n')
                with tempfile.TemporaryDirectory(prefix="riscay-fabric-export-") as folder:
                    path = Path(folder); (path / "test.sv").write_text(text)
                    built = subprocess.run(["iverilog", "-g2012", "-s", "Testbench", "-o", "sim.vvp", "test.sv"],
                                           cwd=path, capture_output=True, text=True, timeout=30)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    result = subprocess.run(["vvp", "sim.vvp"], cwd=path, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode == 0, broken is None, result.stdout)
                    self.assertIn("FABRIC_PINS_PASS" if broken is None else "FABRIC_PIN_BINDING", result.stdout)
